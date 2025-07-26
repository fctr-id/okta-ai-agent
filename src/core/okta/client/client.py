"""
Okta API Client Wrapper

Provides async interface to Okta's API with:
- Pagination handling
- Rate limiting
- Relationship resolution
- Data transformation
- Error handling
- Global API request rate limiting with semaphore
- Cancellation support

Usage:
    async with OktaClientWrapper(tenant_id, cancellation_flag) as client:
        users = await client.list_users()
"""

import asyncio
import os
from urllib.parse import urlparse
import time, logging, re
from okta.client import Client as OktaClient
from datetime import datetime
from typing import List, Any, Optional, Tuple, TypeVar, Type, Dict, Final, Callable, Union
from src.config.settings import settings
from src.utils.logging import logger    
from okta.models import User, Group, Policy, Application
from datetime import timezone
from src.utils.pagination_limits import _paginate_direct_api


T = TypeVar('T')


def parse_timestamp(timestamp_str: Optional[str]) -> Optional[datetime]:
    """Convert Okta timestamp string to UTC datetime object"""
    if not timestamp_str:
        return None
    try:
        # Parse ISO format and ensure UTC
        dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        return dt.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None


def normalize_okta_response(response):
    """
    Normalize different Okta API response formats to (results, error).
    
    The Okta SDK can return responses in several formats:
    - 3-tuple: (results, response, error)
    - 2-tuple: (results, response)
    - Direct result object
    
    This function standardizes all formats to a consistent (results, error) format
    for use with pagination, and filters out rate limit errors.
    """
    try:
        if isinstance(response, tuple):
            if len(response) == 3:
                # Standard SDK response: (results, response, error)
                results, resp_obj, error = response
                
                # Filter out rate limit errors silently (no notification)
                if error:
                    if (isinstance(error, dict) and error.get('errorCode') == 'E0000047') or \
                       (hasattr(error, 'error_code') and error.error_code == 'E0000047') or \
                       (isinstance(error, str) and 'E0000047' in error):
                        # It's a rate limit error, return empty list or original results if available
                        # The SDK has already logged the timeout message
                        return [] if results is None else results, None
                
                return results, error
            elif len(response) == 2:
                # Sometimes returns: (results, response)
                return [] if response[0] is None else response[0], None  # (results, None)
            else:
                logger.error(f"Unexpected response tuple length: {len(response)}")
                return [], ValueError(f"Unexpected response format: {response}")
        elif response is None:
            return [], ValueError("Received None response")
        else:
            # Handle single result object
            return response, None
    except Exception as e:
        logger.error(f"Error normalizing Okta response: {e}")
        return [], e

class OktaSDKLogHandler(logging.Handler):
    """Custom handler for Okta SDK log messages with rate limit consolidation"""
    
    def __init__(self, target_logger):
        super().__init__()
        self.target_logger = target_logger  # The logger to forward filtered messages to
        self.last_rate_limit_msg_time = 0
        self.cooldown_seconds = 5
        self.buffer_seconds = 3  # Add buffer seconds to reported wait time
        self.rate_limit_pattern = re.compile(r'Hit rate limit\. Retry request in (\d+\.\d+|\d+) seconds\.')
    
    def emit(self, record):
        try:
            # Check if it's a rate limit message
            if hasattr(record, 'msg'):
                msg = record.msg
                if isinstance(msg, str):
                    match = self.rate_limit_pattern.search(msg)
                    if match:
                        current_time = time.time()
                        wait_time = float(match.group(1))
                        
                        # If we're within cooldown period, ignore this message
                        if current_time - self.last_rate_limit_msg_time < self.cooldown_seconds:
                            return
                        
                        # Update cooldown timer
                        self.last_rate_limit_msg_time = current_time
                        
                        # Create a new message with buffer
                        buffered_time = wait_time + self.buffer_seconds
                        self.target_logger.warning(
                            f"Hit Okta API rate limit. Operations will resume in approximately {buffered_time:.0f} seconds."
                        )
                        return
            
            # For non-rate limit messages or other loggers, pass through based on level
            if record.levelno >= logging.WARNING:
                self.target_logger.log(record.levelno, record.getMessage())
                
        except Exception as e:
            self.target_logger.error(f"Error in log handler: {e}")
            
def configure_okta_sdk_logging(target_logger=None):
    """
    Configure Okta SDK logging to prevent duplicate rate limit messages.
    
    Args:
        target_logger: Logger to send filtered messages to. If None, uses the root logger.
    """
    if target_logger is None:
        target_logger = logging.getLogger()
    
    # Create a filter that captures rate limit information and blocks the original message
    class RateLimitFilter(logging.Filter):
        def __init__(self):
            super().__init__()
            self.last_message_time = 0
            self.cooldown = 5  # seconds between messages
            self.rate_limit_pattern = re.compile(r'Hit rate limit\. Retry request in (\d+\.\d+|\d+) seconds\.')
            
        def filter(self, record):
            # Check if it's a rate limit message
            msg = str(record.msg)
            match = self.rate_limit_pattern.search(msg)
            if match:
                current_time = time.time()
                # If within cooldown, block message completely
                if current_time - self.last_message_time < self.cooldown:
                    return False
                
                # It's been long enough, update cooldown timer
                self.last_message_time = current_time
                
                # Extract the wait time and log our consolidated message
                wait_time = float(match.group(1))
                buffered_time = wait_time + 3  # Add buffer
                target_logger.warning(
                    f"Hit Okta API rate limit. Operations will resume in approximately {buffered_time:.0f} seconds."
                )
                
                # Block the original message
                return False
            
            # Allow other messages through
            return True
    
    # Get the main okta logger - this is where rate limit messages originate
    main_logger = logging.getLogger('okta-sdk-python')
    
    # Remove any existing handlers & add our filter
    for handler in list(main_logger.handlers):
        main_logger.removeHandler(handler)
    
    # Add our filter and stop propagation
    main_logger.addFilter(RateLimitFilter())
    main_logger.propagate = False    

class OktaClientWrapper:
    """
    Async wrapper for Okta API client with relationship handling.
    
    Features:
    - Configurable page sizes and rate limits
    - Parallel processing of related entities
    - Data transformation to match database models
    - Error handling and logging
    - Global API request rate limiting with semaphore
    - Cancellation support
    """
    
    # API pagination limits
    USER_PAGE_SIZE: Final[int] = 200
    GROUP_PAGE_SIZE: Final[int] = 1000
    APP_PAGE_SIZE: Final[int] = 100
    POLICY_PAGE_SIZE: Final[int] = 200
    AUTH_PAGE_SIZE: Final[int] = 100
    FACTOR_PAGE_SIZE: Final[int] = 50
    DEVICE_PAGE_SIZE: Final[int] = 200
  
    # Rate limit delay between requests
    RATE_LIMIT_DELAY: Final[float] = 0.1
    
    def __init__(self, tenant_id: str, cancellation_flag=None):
        self.tenant_id = tenant_id
        self.cancellation_flag = cancellation_flag  # Store cancellation flag
        configure_okta_sdk_logging(logger)
        self.config = {
            'orgUrl': settings.OKTA_CLIENT_ORGURL,
            'token': settings.OKTA_API_TOKEN,
            'requestTimeout': 30,
            'rateLimit': {
                'maxRetries': 1  # Increased from 1 to take advantage of SDK's built-in retry logic
            },
            'logging': {
                'enabled': True,
                'logLevel': 'INFO'
            }
        }
        self.client = None
        
        # Initialize API request semaphore based on settings
        self.api_semaphore = asyncio.Semaphore(settings.OKTA_CONCURRENT_LIMIT)
        logger.info(f"Initialized API semaphore with limit: {settings.OKTA_CONCURRENT_LIMIT}")
        

    async def __aenter__(self):
        self.client = OktaClient(self.config)
        logger.info(f"Okta concurrent limit: {settings.OKTA_CONCURRENT_LIMIT}, "
               f"max concurrent users: {settings.MAX_CONCURRENT_USERS}")        
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.client = None

    async def _execute_with_semaphore(self, api_func, *args, **kwargs):
        """
        Execute an API call with semaphore control to respect rate limits.
        """
        try:
            # DIAGNOSTIC: Add detailed logging about the cancellation flag
            if self.cancellation_flag and self.cancellation_flag.is_set():
                logger.info(f"Cancellation flag exists in _execute_with_semaphore: type={type(self.cancellation_flag)}")
                if hasattr(self.cancellation_flag, 'is_set'):
                    logger.info(f"Cancellation flag is_set()={self.cancellation_flag.is_set()}")
                else:
                    logger.info(f"Cancellation flag value={self.cancellation_flag}")
                    
                # Check for cancellation before acquiring semaphore
                if (hasattr(self.cancellation_flag, 'is_set') and self.cancellation_flag.is_set()) or \
                   (isinstance(self.cancellation_flag, bool) and self.cancellation_flag):
                    logger.info("Cancellation requested, skipping API call")
                    raise asyncio.CancelledError("Sync process was cancelled")
            
            # Acquire semaphore before making API call
            async with self.api_semaphore:
                # Execute the API call
                result = await api_func(*args, **kwargs)
                
                # Add a small delay to prevent burst requests
                await asyncio.sleep(self.RATE_LIMIT_DELAY)
                
                return result
                    
        except asyncio.CancelledError:
            logger.info("API call cancelled due to cancellation flag")
            raise
        except Exception as e:
            logger.error(f"Error executing API call with semaphore: {str(e)}")
            raise

    async def _paginate(
        self,
        api_method,
        query_params,
        transform_batch_func,
        processor_func=None,
        page_size=None,
        entity_name="items",
        batch_size=None,
        concurrent_transform=False,
        *args, **kwargs
    ) -> Union[List[Dict], int]:
        """
        Common pagination function for all Okta API methods.
        
        Args:
            api_method: Okta API method to call
            query_params: Query parameters for API call
            transform_batch_func: Function to transform items in a batch
            processor_func: Optional function to process transformed items immediately
            page_size: Page size for logging
            entity_name: Entity name for logging
            batch_size: Size of batches for concurrent processing
            concurrent_transform: If True, transform items in parallel
            *args, **kwargs: Additional arguments to pass to API method
            
        Returns:
            If processor_func provided: Count of processed records
            Otherwise: List of transformed items
        """
        try:
            logger.info(f"Starting {entity_name} sync with page size: {page_size}")
            
            # Tracking variables
            total_processed = 0
            all_items = []
            
            # Initial API call
            api_response = await self._execute_with_semaphore(
                api_method, *args, query_params=query_params, **kwargs
            )
            
            # Process initial response
            items, error = normalize_okta_response(api_response)
            
            if error:
                logger.error(f"Error retrieving {entity_name}: {error}")
                return [] if not processor_func else 0
            
            # Get response object for pagination
            response = api_response[1] if isinstance(api_response, tuple) and len(api_response) > 1 else None
            
            # Process first page
            if items:
                if batch_size and concurrent_transform:
                    # Process items in smaller batches with concurrency
                    for i in range(0, len(items), batch_size):
                        # Check for cancellation
                        if self.cancellation_flag and self.cancellation_flag.is_set():
                            logger.info(f"Cancellation requested, stopping {entity_name} processing")
                            return [] if not processor_func else total_processed
                            
                        small_batch = items[i:i + batch_size]
                        logger.debug(f"Processing batch of {len(small_batch)} {entity_name} concurrently")
                        
                        # Process items with concurrent transformations
                        batch_tasks = []
                        for item in small_batch:
                            if asyncio.iscoroutinefunction(transform_batch_func):
                                batch_tasks.append(transform_batch_func(item))
                            else:
                                batch_tasks.append(asyncio.to_thread(transform_batch_func, item))
                        
                        # Gather results and filter failures
                        batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
                        transformed_batch = [r for r in batch_results if not isinstance(r, Exception) and r]
                        
                        # Process or collect the transformed batch
                        if processor_func and transformed_batch:
                            await processor_func(transformed_batch)
                            total_processed += len(transformed_batch)
                            logger.info(f"Processed {len(transformed_batch)} {entity_name}, total: {total_processed}")
                        elif transformed_batch:
                            all_items.extend(transformed_batch)
                        
                        # Short delay between batches
                        await asyncio.sleep(0.2)
                else:
                    # Simple transformation for the whole batch
                    if asyncio.iscoroutinefunction(transform_batch_func):
                        transformed_batch = await transform_batch_func(items)
                    else:
                        transformed_batch = transform_batch_func(items)
                    
                    if processor_func and transformed_batch:
                        await processor_func(transformed_batch)
                        total_processed += len(transformed_batch)
                        logger.info(f"Processed {len(transformed_batch)} {entity_name}, total: {total_processed}")
                    elif transformed_batch:
                        all_items.extend(transformed_batch)
            
            # Process remaining pages
            page_num = 1
            while response and hasattr(response, 'has_next') and response.has_next():
                # Check for cancellation before fetching next page
                if self.cancellation_flag and self.cancellation_flag.is_set():
                    logger.info(f"Cancellation requested, stopping {entity_name} pagination")
                    break
                    
                page_num += 1
                logger.info(f"Fetching page {page_num} of {entity_name}")
                
                try:
                    # Get next page
                    async with self.api_semaphore:
                        next_response = await response.next()
                        await asyncio.sleep(self.RATE_LIMIT_DELAY)
                    
                    # Process response
                    items, error = normalize_okta_response(next_response)
                    
                    if error:
                        logger.error(f"Error retrieving page {page_num} of {entity_name}: {error}")
                        break
                        
                    if not items:
                        logger.info(f"Page {page_num} contained no {entity_name}")
                        continue
                    
                    # Process items using the same logic as the first page
                    if batch_size and concurrent_transform:
                        # Process items in smaller batches with concurrency
                        for i in range(0, len(items), batch_size):
                            # Check for cancellation
                            if self.cancellation_flag and self.cancellation_flag.is_set():  # Check is_set() method
                                logger.info(f"Cancellation requested, stopping {entity_name} pagination")
                                break
                                
                            small_batch = items[i:i + batch_size]
                            logger.debug(f"Processing batch of {len(small_batch)} {entity_name} from page {page_num} concurrently")
                            
                            # Process items with concurrent transformations
                            batch_tasks = []
                            for item in small_batch:
                                if asyncio.iscoroutinefunction(transform_batch_func):
                                    batch_tasks.append(transform_batch_func(item))
                                else:
                                    batch_tasks.append(asyncio.to_thread(transform_batch_func, item))
                            
                            # Gather results and filter failures
                            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
                            transformed_batch = [r for r in batch_results if not isinstance(r, Exception) and r]
                            
                            # Process or collect the transformed batch
                            if processor_func and transformed_batch:
                                await processor_func(transformed_batch)
                                total_processed += len(transformed_batch)
                                logger.info(f"Processed {len(transformed_batch)} {entity_name} from page {page_num}, total: {total_processed}")
                            elif transformed_batch:
                                all_items.extend(transformed_batch)
                            
                            # Short delay between batches
                            await asyncio.sleep(0.2)
                    else:
                        # Simple transformation for the whole batch
                        if asyncio.iscoroutinefunction(transform_batch_func):
                            transformed_batch = await transform_batch_func(items)
                        else:
                            transformed_batch = transform_batch_func(items)
                        
                        if processor_func and transformed_batch:
                            await processor_func(transformed_batch)
                            total_processed += len(transformed_batch)
                            logger.info(f"Processed {len(transformed_batch)} {entity_name} from page {page_num}, total: {total_processed}")
                        elif transformed_batch:
                            all_items.extend(transformed_batch)
                    
                except StopAsyncIteration:
                    logger.info(f"Pagination complete after {page_num - 1} pages")
                    break
                except Exception as e:
                    logger.error(f"Error processing page {page_num} of {entity_name}: {str(e)}")
                    break
            
            # Return appropriate result
            if processor_func:
                logger.info(f"Completed processing all {total_processed} {entity_name}")
                return total_processed
            else:
                logger.info(f"Retrieved {len(all_items)} {entity_name} total")
                return all_items
                
        except asyncio.CancelledError:
            logger.info(f"Pagination cancelled for {entity_name}")
            return [] if not processor_func else total_processed
        except Exception as e:
            logger.error(f"Error in pagination for {entity_name}: {str(e)}")
            raise
        
    async def list_groups(
        self, 
        since: Optional[datetime] = None,
        processor_func: Optional[Callable] = None
    ) -> Union[List[Dict], int]:
        """
        Fetch groups without app assignments for faster initial sync.
        This is the first step in our sync process.
        
        Args:
            since: Optional timestamp for incremental sync
            processor_func: Function to process batches immediately
                
        Returns:
            If processor_func is provided: Count of processed records
            Otherwise: List of group dictionaries without relationships
        """
        try:
            # Set up query parameters
            query_params = {"limit": self.GROUP_PAGE_SIZE}
            
            # Add filter for incremental sync if needed
            if since:
                since_str = since.strftime("%Y-%m-%dT%H:%M:%S.000Z")
                query_params["filter"] = f"lastUpdated gt \"{since_str}\""
            
            # Use common pagination function
            return await self._paginate(
                api_method=self.client.list_groups,
                query_params=query_params,
                transform_batch_func=self._transform_groups_batch,
                processor_func=processor_func,
                page_size=self.GROUP_PAGE_SIZE,
                entity_name="groups"
            )
                
        except Exception as e:
            logger.error(f"Error listing groups: {str(e)}")
            raise
    
    def _transform_groups_batch(self, groups) -> List[Dict]:
        """Transform a batch of group objects to dictionaries"""
        transformed = []
        for group in groups:
            # Handle both model objects and dictionaries
            if hasattr(group, 'id'):
                # It's a model object
                profile = getattr(group, 'profile', None)
                transformed.append({
                    'okta_id': group.id,
                    'name': getattr(profile, 'name', None) if profile else None,
                    'description': getattr(profile, 'description', None) if profile else None,
                    'created_at': parse_timestamp(getattr(group, 'created', None)),
                    'last_updated_at': parse_timestamp(getattr(group, 'lastUpdated', None))
                })
            else:
                # It's a dictionary
                transformed.append({
                    'okta_id': group.get('id'),
                    'name': group.get('profile', {}).get('name'),
                    'description': group.get('profile', {}).get('description'),
                    'created_at': parse_timestamp(group.get('created')),
                    'last_updated_at': parse_timestamp(group.get('lastUpdated'))
                })
        return transformed

    async def list_applications(
        self, 
        since: Optional[datetime] = None,
        processor_func: Optional[Callable] = None
    ) -> Union[List[Dict], int]:
        """
        List applications with group assignments.
        This runs after groups are already in the database.
        
        Args:
            since: Optional timestamp for incremental sync
            processor_func: Function to process batches immediately
            
        Returns:
            If processor_func is provided: Count of processed records
            Otherwise: List of transformed application dictionaries
        """
        try:
            # Set up query parameters
            query_params = {"limit": self.APP_PAGE_SIZE}
            
            # Add filter for incremental sync if needed
            if since:
                since_str = since.strftime("%Y-%m-%dT%H:%M:%S.000Z")
                query_params["filter"] = f"lastUpdated gt \"{since_str}\""
            
            # Use common pagination function with parallel processing
            return await self._paginate(
                api_method=self.client.list_applications,
                query_params=query_params,
                transform_batch_func=self._transform_app_with_groups,
                processor_func=processor_func,
                page_size=self.APP_PAGE_SIZE,
                entity_name="applications",
                batch_size=settings.MAX_CONCURRENT_APPS,
                concurrent_transform=True
            )
                
        except Exception as e:
            logger.error(f"Error listing applications: {str(e)}")
            raise
            
    async def list_users(
        self, 
        since: Optional[datetime] = None,
        processor_func: Optional[Callable] = None
    ) -> int:
        try:
            query_params = {"limit": self.USER_PAGE_SIZE}
            
            # Check if we need to ADD deprovisioned users
            if settings.SYNC_DEPROVISIONED_USERS:
                # Build conditions for deprovisioned users
                deprovisioned_conditions = ['status eq "DEPROVISIONED"']
                
                # Add date filters only if specified by user
                if settings.depr_user_created_after_iso:
                    deprovisioned_conditions.append(f'created gt "{settings.depr_user_created_after_iso}"')
                
                if settings.depr_user_updated_after_iso:
                    deprovisioned_conditions.append(f'lastUpdated gt "{settings.depr_user_updated_after_iso}"')
                
                # Add incremental sync to deprovisioned users as well
                if since:
                    since_str = since.strftime("%Y-%m-%dT%H:%M:%S.000Z")
                    deprovisioned_conditions.append(f'lastUpdated gt "{since_str}"')
                
                # Build the deprovisioned user filter
                deprovisioned_filter = " and ".join(deprovisioned_conditions)
                
                # Use epoch date to capture all default users (instead of status ne "DEPROVISIONED")
                #epoch_date = "1970-01-01T00:00:00.000Z"
                #default_conditions = [f'created gt "{epoch_date}"']
                default_conditions = [
                    'status eq "STAGED"',
                    'status eq "PROVISIONED"', 
                    'status eq "ACTIVE"',
                    'status eq "RECOVERY"',
                    'status eq "PASSWORD_EXPIRED"',
                    'status eq "LOCKED_OUT"',
                    'status eq "SUSPENDED"'
                ]
                
                # Add incremental sync to default users if needed
                if since:
                    since_str = since.strftime("%Y-%m-%dT%H:%M:%S.000Z")
                    # For incremental sync, we need to AND the status conditions with the date filter
                    status_filter = " or ".join(default_conditions)
                    default_filter = f"({status_filter}) and lastUpdated gt \"{since_str}\""
                else:
                    # For full sync, just OR all the status conditions
                    default_filter = " or ".join(default_conditions)
                
                # Combine: (default users) OR (deprovisioned users with conditions)
                query_params["search"] = f'({default_filter}) or ({deprovisioned_filter})'
                
                logger.info(f"Using combined search: default users + deprovisioned users")
                logger.info(f"Deprovisioned user filter: {deprovisioned_filter}")
                logger.debug(f"Final search expression: {query_params['search']}")
                
            else:
                # Use default Okta behavior with optional incremental sync
                if since:
                    since_str = since.strftime("%Y-%m-%dT%H:%M:%S.000Z")
                    query_params["filter"] = f"lastUpdated gt \"{since_str}\""
                    logger.info(f"Using default behavior with incremental sync: lastUpdated gt \"{since_str}\"")
                else:
                    logger.info("Using default Okta behavior: syncing active users only")
            
            return await self._paginate(
                api_method=self.client.list_users,
                query_params=query_params,
                transform_batch_func=self._process_single_user,
                processor_func=processor_func,
                page_size=self.USER_PAGE_SIZE,
                entity_name="users",
                batch_size=settings.MAX_CONCURRENT_USERS,
                concurrent_transform=True
            )
                
        except Exception as e:
            logger.error(f"Error listing users: {str(e)}")
            raise
        
    async def _process_single_user(self, user) -> Dict:
        """Process single user with relationships concurrently"""
        try:
            # Import settings here to avoid circular imports
            from src.config.settings import settings
            
            # Extract user ID from either object or dict
            user_okta_id = user['id'] if isinstance(user, dict) else getattr(user, 'id')
            user_dict = user if isinstance(user, dict) else user.as_dict() if hasattr(user, 'as_dict') else {}
            
            # Get profile data safely
            profile = user_dict.get('profile', {})
            user_status = user_dict.get('status')
            
            # Initialize empty relationship data
            app_links = []
            group_memberships = []
            factors = []
            
            # Only fetch relationships for non-deprovisioned users
            if user_status != 'DEPROVISIONED':
                # Fetch relationships with small delays between calls
                app_links = await self.get_user_app_links(user_okta_id)
                await asyncio.sleep(0.1)  # Small delay after first API call
                
                group_memberships = await self.get_user_groups(user_okta_id)
                await asyncio.sleep(0.1)  # Small delay after second API call
                
                factors = await self.list_user_factors([user_okta_id])
            else:
                logger.debug(f"User {user_okta_id} is DEPROVISIONED - skipping relationship fetching")
            
            custom_attributes = {}
            for attr_name in settings.okta_user_custom_attributes_list:
                value = profile.get(attr_name)
                # Only store meaningful values (not None, empty string, or whitespace-only)
                if value is not None and str(value).strip():
                    custom_attributes[attr_name] = value
            
            transformed_user = {
                'okta_id': user_okta_id,
                'email': profile.get('email'),
                'first_name': profile.get('firstName'),
                'last_name': profile.get('lastName'),
                'login': profile.get('login'),
                'status': user_status,
                'mobile_phone': profile.get('mobilePhone'),
                'primary_phone': profile.get('primaryPhone'),
                'employee_number': profile.get('employeeNumber'),
                'department': profile.get('department'),
                'manager': profile.get('manager'),
                'created_at': parse_timestamp(user_dict.get('created')),
                'last_updated_at': parse_timestamp(user_dict.get('lastUpdated')),
                'password_changed_at': parse_timestamp(user_dict.get('passwordChanged')),
                'status_changed_at': parse_timestamp(user_dict.get('statusChanged')),
                'user_type': profile.get('userType'),
                'country_code': profile.get('countryCode'),
                'title': profile.get('title'),
                'organization': profile.get('organization'),
                'custom_attributes': custom_attributes,  # Add custom attributes
                'factors': factors,
                'app_links': app_links,
                'group_memberships': group_memberships
            }
            
            if user_status == 'DEPROVISIONED':
                logger.debug(f"User {user_okta_id} (DEPROVISIONED) processed with basic data only")
            else:
                logger.debug(
                    f"User {user_okta_id} processed with {len(app_links)} app links, "
                    f"{len(group_memberships)} groups, {len(factors)} factors, "
                    f"and {len(custom_attributes)} custom attributes"
                )
            return transformed_user
            
        except Exception as e:
            logger.error(f"Error processing user: {str(e)}")
            raise
    
    async def _transform_app_with_groups(self, app) -> Dict:
        """Transform application with group assignments"""
        try:
            # Extract app ID
            okta_id = app.get('id') if isinstance(app, dict) else getattr(app, 'id', None)
            if not okta_id:
                logger.error(f"Missing required okta_id for app")
                return None
            
            # Get base app data
            app_data = await self._transform_application(app)
            if not app_data:
                return None
            
            # Get group assignments for this app - use app_group_assignments instead of 'groups'
            group_assignments = await self.get_app_groups(okta_id)
            await asyncio.sleep(0.1)  # Add small delay after API call
            
            if group_assignments:
                app_data['app_group_assignments'] = group_assignments
            
            return app_data
            
        except Exception as e:
            logger.error(f"Error transforming app with groups: {str(e)}")
            return None
        
    async def _transform_application(self, app) -> Dict:
        """Transform application with required field validation"""
        try:
            # Handle both dictionary and object formats
            app_dict = app if isinstance(app, dict) else app.as_dict() if hasattr(app, 'as_dict') else {}
            
            # Extract ID
            okta_id = app_dict.get('id') if isinstance(app_dict, dict) else getattr(app, 'id', None)
            if not okta_id:
                logger.error(f"Missing required okta_id for app")
                return None
    
            # Extract nested data safely
            links = app_dict.get('_links', {})
            credentials = app_dict.get('credentials', {})
            settings = app_dict.get('settings', {})
            sign_on = settings.get('signOn', {})
            visibility = app_dict.get('visibility', {})
            
            # Transform data
            return {
                'okta_id': okta_id,
                'name': app_dict.get('name'),
                'label': app_dict.get('label'),
                'status': app_dict.get('status'),
                'sign_on_mode': app_dict.get('signOnMode'),
                'sign_on_url': sign_on.get('ssoAcsUrl'),
                'audience': sign_on.get('audience'),
                'destination': sign_on.get('destination'),
                'created_at': parse_timestamp(app_dict.get('created')),
                'last_updated_at': parse_timestamp(app_dict.get('lastUpdated')),
                
                # Links
                'metadata_url': links.get('metadata', {}).get('href'),
                'policy_id': links.get('accessPolicy', {}).get('href', '').split('/')[-1] if links.get('accessPolicy', {}).get('href') else None,
                
                # Credentials
                'signing_kid': credentials.get('signing', {}).get('kid'),
                'username_template': credentials.get('userNameTemplate', {}).get('template'),
                'username_template_type': credentials.get('userNameTemplate', {}).get('type'),
                
                # Settings
                'implicit_assignment': settings.get('implicitAssignment', False),
                'admin_note': settings.get('notes', {}).get('admin'),
                'attribute_statements': sign_on.get('attributeStatements', []),
                'honor_force_authn': sign_on.get('honorForceAuthn', False),
                
                # Visibility
                'hide_ios': visibility.get('hide', {}).get('ios', False),
                'hide_web': visibility.get('hide', {}).get('web', False),
            }
    
        except Exception as e:
            logger.error(f"Error transforming application: {str(e)}")
            return None

    async def list_policies(
        self, 
        since: Optional[datetime] = None,
        processor_func: Optional[Callable] = None
    ) -> Union[List[Dict], int]:
        """
        List policies with optional API-to-DB streaming support.
        
        Args:
            since: Optional timestamp filter
            processor_func: Function to process batches immediately
            
        Returns:
            If processor_func is provided: Count of processed records
            Otherwise: List of policy dictionaries
        """
        try:
            # Basic policy types
            base_policies = [
                'OKTA_SIGN_ON',    # Global session
                'PASSWORD',        # Password
                'MFA_ENROLL',      # Authenticator enrollment
                'ACCESS_POLICY'    # IdP discovery
            ]
            
            total_processed = 0
            all_policies = []
            
            for policy_type in base_policies:
                # Check for cancellation between policy types
                if self.cancellation_flag and self.cancellation_flag.is_set():
                    logger.info(f"Cancellation requested, stopping policy sync")
                    break
                
                logger.info(f"Fetching policies of type: {policy_type}")
                query_params = {
                    "type": policy_type,
                    "limit": self.POLICY_PAGE_SIZE
                }
                
                if since:
                    since_str = since.strftime("%Y-%m-%dT%H:%M:%S.000Z")
                    query_params["filter"] = f"lastUpdated gt \"{since_str}\""
                
                try:
                    # Use common pagination function for each policy type
                    # Create a transform function specifically for this policy type
                    def transform_policy_batch(policies, policy_type=policy_type):
                        transformed_batch = []
                        for policy in policies:
                            try:
                                # First try object attribute access
                                policy_dict = {
                                    'okta_id': getattr(policy, 'id', None),
                                    'name': getattr(policy, 'name', None),
                                    'description': getattr(policy, 'description', None),
                                    'status': getattr(policy, 'status', None),
                                    'type': policy_type,
                                    'created_at': parse_timestamp(getattr(policy, 'created', None)),
                                    'last_updated_at': parse_timestamp(getattr(policy, 'lastUpdated', None))
                                }
                                
                                # Ensure we have the required fields
                                if policy_dict['okta_id'] and policy_dict['name']:
                                    transformed_batch.append(policy_dict)
                                else:
                                    logger.warning(f"Skipping policy with missing data: {policy}")
                                    
                            except Exception as e:
                                logger.error(f"Error transforming policy: {e}")
                        return transformed_batch
                    
                    # Process this policy type
                    result = await self._paginate(
                        api_method=self.client.list_policies,
                        query_params=query_params,
                        transform_batch_func=transform_policy_batch,
                        processor_func=processor_func,
                        page_size=self.POLICY_PAGE_SIZE,
                        entity_name=f"{policy_type} policies"
                    )
                    
                    # Accumulate results
                    if processor_func:
                        total_processed += result
                    else:
                        all_policies.extend(result)
                
                except Exception as e:
                    logger.error(f"Error processing {policy_type} policies: {str(e)}")
                    continue
            
            # Return appropriate result
            if processor_func:
                logger.info(f"Completed processing all {total_processed} policies")
                return total_processed
            else:
                logger.info(f"Retrieved {len(all_policies)} policies total")
                return all_policies
                    
        except Exception as e:
            logger.error(f"Error listing policies: {str(e)}")
            raise

    async def list_authenticators(
        self, 
        since: Optional[datetime] = None,
        processor_func: Optional[Callable] = None
    ) -> Union[List[Dict], int]:
        """
        List authenticators with optional streaming support.
        
        Args:
            since: Optional timestamp filter (not used)
            processor_func: Function to process batches immediately
            
        Returns:
            If processor_func is provided: Count of processed records
            Otherwise: List of authenticator dictionaries
        """
        try:
            logger.info("Starting authenticators sync")
            
            # Initial API call with semaphore protection
            api_response = await self._execute_with_semaphore(
                self.client.list_authenticators
            )
            
            # Process initial response using normalize_okta_response
            authenticators, error = normalize_okta_response(api_response)
            
            if error:
                logger.error(f"Error retrieving authenticators: {error}")
                return [] if not processor_func else 0
            
            # Transform authenticators - Handle as objects, not dictionaries
            transformed_authenticators = []
            for auth in authenticators:
                # Get properties using attribute access, not dictionary get()
                transformed_authenticators.append({
                    'okta_id': getattr(auth, 'id', None),
                    'name': getattr(auth, 'name', None),
                    'status': getattr(auth, 'status', None),
                    'type': getattr(auth, 'type', None)
                })
            
            # Either process or return
            if processor_func:
                await processor_func(transformed_authenticators)
                logger.info(f"Processed {len(transformed_authenticators)} authenticators")
                return len(transformed_authenticators)
            else:
                logger.info(f"Retrieved {len(transformed_authenticators)} authenticators")
                return transformed_authenticators
                
        except Exception as e:
            logger.error(f"Error listing authenticators: {str(e)}")
            raise
        
    async def list_user_factors(self, user_ids: List[str]) -> List[Dict]:
        """Fetch MFA factors for users - sequential processing to avoid rate limits"""
        try:
            if not user_ids:
                return []
        
            all_factors = []
            valid_ids = [uid for uid in user_ids if isinstance(uid, str) and len(uid) > 10]
    
            # Process sequentially - no batching
            for user_id in valid_ids:
                # Check for cancellation
                if self.cancellation_flag and self.cancellation_flag.is_set():
                    logger.info(f"Cancellation requested, stopping factor processing")
                    break
                
                try:
                    # Use semaphore for API request
                    api_response = await self._execute_with_semaphore(
                        self.client.list_factors,
                        user_id
                    )
                    
                    # Process response using normalize_okta_response
                    factors, error = normalize_okta_response(api_response)
                    
                    if error:
                        # Handle 404s gracefully - these are expected for deprovisioned/deleted users
                        error_str = str(error)
                        if "404" in error_str or "E0000007" in error_str or "Not found" in error_str:
                            logger.debug(f"User {user_id} not found for factors (likely deprovisioned/deleted) - skipping")
                            continue
                        else:
                            logger.error(f"Factors API error for user {user_id}: {error}")
                            continue
    
                    transformed_factors = []
                    for factor in factors:
                        transformed = await self._transform_factor(factor, user_id)
                        if transformed:
                            transformed_factors.append(transformed)
    
                    all_factors.extend(transformed_factors)
                    
                except Exception as e:
                    error_str = str(e)
                    if "404" in error_str or "E0000007" in error_str or "Not found" in error_str:
                        logger.debug(f"User {user_id} not accessible for factors - skipping")
                    else:
                        logger.error(f"Error fetching factors for user {user_id}: {str(e)}")
                    continue
    
            return all_factors
        except Exception as e:
            logger.error(f"Error in factor processing: {str(e)}", exc_info=True)
            return []
        
    async def _transform_factor(self, factor, user_id: str) -> Dict:
        """Transform MFA factor to dictionary"""
        try:
            # Base factor data
            base_factor = {
                'okta_id': getattr(factor, 'id', None),
                'factor_type': getattr(factor, 'factor_type', None),
                'provider': getattr(factor, 'provider', None),
                'status': getattr(factor, 'status', None),
                'created_at': None,
                'last_updated_at': None,
                'user_okta_id': user_id
            }
    
            # Handle timestamps
            created = getattr(factor, 'created', None)
            last_updated = getattr(factor, 'last_updated', None)
    
            if created:
                base_factor['created_at'] = parse_timestamp(created)
    
            if last_updated:
                base_factor['last_updated_at'] = parse_timestamp(last_updated)
    
            # Handle profile data based on factor type
            if hasattr(factor, 'profile') and factor.profile is not None:
                if base_factor['factor_type'] == 'email':
                    base_factor['email'] = getattr(factor.profile, 'email', None)
                elif base_factor['factor_type'] == 'sms':
                    base_factor['phone_number'] = getattr(factor.profile, 'phone_number', None)
                elif base_factor['factor_type'] in ['push', 'signed_nonce']:
                    base_factor.update({
                        'device_type': getattr(factor.profile, 'device_type', None),
                        'device_name': getattr(factor.profile, 'name', None),
                        'platform': getattr(factor.profile, 'platform', None)
                    })
    
            return base_factor
                
        except Exception as e:
            logger.error(f"Error transforming factor: {str(e)}")
            return {}
    
    async def get_user_app_links(self, user_okta_id: str) -> List[Dict]:
        """Fetch application assignments for a user using SDK's list_app_links method"""
        try:
            logger.debug(f"Fetching app links for user {user_okta_id}")
            
            # Check for cancellation
            if self.cancellation_flag and self.cancellation_flag.is_set():
                logger.info(f"Cancellation requested, skipping app links for user {user_okta_id}")
                return []
            
            # Use correct SDK method with semaphore
            api_response = await self._execute_with_semaphore(
                self.client.list_app_links,
                user_okta_id
            )
            
            # Process response using normalize_okta_response
            app_links, error = normalize_okta_response(api_response)
            
            # Get response object for pagination
            response = api_response[1] if isinstance(api_response, tuple) and len(api_response) > 1 else None
            
            if error:
                logger.error(f"Error getting app links for user {user_okta_id}: {error}")
                return []
    
            # Transform app links to our model format with validation
            transformed_links = []
            for link in app_links:
                # Handle both dict and object formats
                if isinstance(link, dict):
                    app_instance_id = link.get('appInstanceId')
                    if app_instance_id:  # Only include if appInstanceId exists
                        transformed_links.append({
                            'user_okta_id': user_okta_id,
                            'application_okta_id': app_instance_id,
                            'assignment_id': link.get('appAssignmentId'),
                            'app_instance_id': app_instance_id,
                            'credentials_setup': link.get('credentialsSetup', False),
                            'hidden': link.get('hidden', False)
                        })
                else:
                    app_instance_id = getattr(link, 'appInstanceId', None)
                    if app_instance_id:  # Only include if appInstanceId exists
                        transformed_links.append({
                            'user_okta_id': user_okta_id,
                            'application_okta_id': app_instance_id,
                            'assignment_id': getattr(link, 'appAssignmentId', None),
                            'app_instance_id': app_instance_id,
                            'credentials_setup': getattr(link, 'credentialsSetup', False),
                            'hidden': getattr(link, 'hidden', False)
                        })
            
            # Handle pagination if needed
            page_num = 1
            while response and hasattr(response, 'has_next') and response.has_next():
                # Check for cancellation
                if self.cancellation_flag and self.cancellation_flag.is_set():
                    logger.info(f"Cancellation requested, stopping app links pagination for user {user_okta_id}")
                    break
                
                page_num += 1
                
                try:
                    # Get next page with semaphore protection
                    async with self.api_semaphore:
                        next_response = await response.next()
                        await asyncio.sleep(self.RATE_LIMIT_DELAY)
                    
                    # Process next_response using normalize_okta_response
                    app_links, error = normalize_okta_response(next_response)
                    
                    if error:
                        logger.error(f"Error on page {page_num} for user {user_okta_id} app links: {error}")
                        break
                    
                    # Process this page with validation
                    for link in app_links:
                        if isinstance(link, dict):
                            app_instance_id = link.get('appInstanceId')
                            if app_instance_id:  # Only include if appInstanceId exists
                                transformed_links.append({
                                    'user_okta_id': user_okta_id,
                                    'application_okta_id': app_instance_id,
                                    'assignment_id': link.get('appAssignmentId'),
                                    'app_instance_id': app_instance_id,
                                    'credentials_setup': link.get('credentialsSetup', False),
                                    'hidden': link.get('hidden', False)
                                })
                        else:
                            app_instance_id = getattr(link, 'appInstanceId', None)
                            if app_instance_id:  # Only include if appInstanceId exists
                                transformed_links.append({
                                    'user_okta_id': user_okta_id,
                                    'application_okta_id': app_instance_id,
                                    'assignment_id': getattr(link, 'appAssignmentId', None),
                                    'app_instance_id': app_instance_id,
                                    'credentials_setup': getattr(link, 'credentialsSetup', False),
                                    'hidden': getattr(link, 'hidden', False)
                                })
                
                except StopAsyncIteration:
                    break
                except Exception as e:
                    logger.error(f"Error processing app links for user {user_okta_id}: {str(e)}")
                    break
            
            return transformed_links
            
        except Exception as e:
            logger.error(f"Error getting app links for user {user_okta_id}: {str(e)}")
            return []

    async def get_user_groups(self, user_okta_id: str) -> List[Dict]:
        """Get groups a user is a member of"""
        try:
            # Check for cancellation
            if self.cancellation_flag and self.cancellation_flag.is_set():
                logger.info(f"Cancellation requested, skipping groups for user {user_okta_id}")
                return []
                
            # Use SDK's method with semaphore
            api_response = await self._execute_with_semaphore(
                self.client.list_user_groups,
                user_okta_id
            )
            
            # Process response using normalize_okta_response
            groups, error = normalize_okta_response(api_response)
            
            # Get response object for pagination
            response = api_response[1] if isinstance(api_response, tuple) and len(api_response) > 1 else None
            
            if error:
                logger.error(f"Error getting groups for user {user_okta_id}: {error}")
                return []
            
            # Transform to our model format
            transformed_groups = []
            for group in groups:
                group_id = group.id if hasattr(group, 'id') else group.get('id')
                if group_id:
                    transformed_groups.append({
                        'user_okta_id': user_okta_id,
                        'group_okta_id': group_id
                    })
            
            # Handle pagination if needed
            page_num = 1
            while response and hasattr(response, 'has_next') and response.has_next():
                # Check for cancellation
                if self.cancellation_flag and self.cancellation_flag.is_set():
                    logger.info(f"Cancellation requested, stopping groups pagination for user {user_okta_id}")
                    break
                
                page_num += 1
                
                try:
                    # Get next page with semaphore protection
                    async with self.api_semaphore:
                        next_response = await response.next()
                        await asyncio.sleep(self.RATE_LIMIT_DELAY)
                    
                    # Process next_response using normalize_okta_response
                    groups, error = normalize_okta_response(next_response)
                    
                    if error:
                        logger.error(f"Error on page {page_num} for user {user_okta_id} groups: {error}")
                        break
                    
                    # Process this page
                    for group in groups:
                        group_id = group.id if hasattr(group, 'id') else group.get('id')
                        if group_id:
                            transformed_groups.append({
                                'user_okta_id': user_okta_id,
                                'group_okta_id': group_id
                            })
                
                except StopAsyncIteration:
                    break
                except Exception as e:
                    logger.error(f"Error processing groups for user {user_okta_id}: {str(e)}")
                    break
            
            return transformed_groups
            
        except Exception as e:
            logger.error(f"Error getting groups for user {user_okta_id}: {str(e)}")
            return []

    async def get_app_groups(self, app_okta_id: str) -> List[Dict]:
        """Get groups assigned to an application with pagination"""
        try:
            logger.debug(f"Fetching groups for application {app_okta_id}")
            
            # Check for cancellation
            if self.cancellation_flag and self.cancellation_flag.is_set():
                logger.info(f"Cancellation requested, skipping groups for app {app_okta_id}")
                return []
                
            # Set pagination parameters
            query_params = {"limit": 100}  # Use a larger page size for efficiency
            
            # Initial API call with semaphore protection
            api_response = await self._execute_with_semaphore(
                self.client.list_application_group_assignments,
                app_okta_id, 
                query_params=query_params
            )
            
            # Process initial response using normalize_okta_response
            groups, error = normalize_okta_response(api_response)
            
            # Get response object for pagination
            response = api_response[1] if isinstance(api_response, tuple) and len(api_response) > 1 else None
            
            if error:
                logger.error(f"Error getting groups for app {app_okta_id}: {error}")
                return []
            
            # Process first page
            all_groups = []
            for group in groups:
                group_id = group.id if hasattr(group, 'id') else group.get('id')
                if group_id:
                    all_groups.append({
                        'application_okta_id': app_okta_id,
                        'group_okta_id': group_id,
                        'assignment_id': f"{app_okta_id}-{group_id}"
                    })
            
            # Handle pagination
            page_num = 1
            while response and hasattr(response, 'has_next') and response.has_next():
                # Check for cancellation
                if self.cancellation_flag and self.cancellation_flag.is_set():
                    logger.info(f"Cancellation requested, stopping groups pagination for app {app_okta_id}")
                    break
                
                page_num += 1
                logger.debug(f"Fetching page {page_num} of groups for application {app_okta_id}")
                
                try:
                    # Get next page with semaphore protection
                    async with self.api_semaphore:
                        next_response = await response.next()
                        await asyncio.sleep(self.RATE_LIMIT_DELAY)
                    
                    # Process next_response using normalize_okta_response
                    groups, error = normalize_okta_response(next_response)
                    
                    if error:
                        logger.error(f"Error on page {page_num} for app {app_okta_id}: {error}")
                        break
                        
                    # Process this page
                    for group in groups:
                        group_id = group.id if hasattr(group, 'id') else group.get('id')
                        if group_id:
                            all_groups.append({
                                'application_okta_id': app_okta_id,
                                'group_okta_id': group_id,
                                'assignment_id': f"{app_okta_id}-{group_id}"
                            })
                
                except StopAsyncIteration:
                    logger.info(f"Pagination complete after {page_num - 1} pages")
                    break
                except Exception as e:
                    logger.error(f"Error processing page {page_num} for app {app_okta_id}: {str(e)}")
                    break
            
            logger.debug(f"Retrieved {len(all_groups)} total groups for application {app_okta_id}")
            return all_groups
            
        except Exception as e:
            logger.error(f"Error getting groups for app {app_okta_id}: {str(e)}")
            return []

    async def get_group_apps(self, group_okta_id: str) -> List[Dict]:
        """Get applications assigned to a group using SDK's list_group_assigned_applications"""
        try:
            # Check for cancellation
            if self.cancellation_flag and self.cancellation_flag.is_set():
                logger.info(f"Cancellation requested, skipping apps for group {group_okta_id}")
                return []
                
            # Use SDK's method with semaphore
            api_response = await self._execute_with_semaphore(
                self.client.list_group_assigned_applications,
                group_okta_id
            )
            
            # Process initial response using normalize_okta_response
            apps, error = normalize_okta_response(api_response)
            
            # Get response object for pagination
            response = api_response[1] if isinstance(api_response, tuple) and len(api_response) > 1 else None
            
            if error:
                logger.error(f"Error getting apps for group {group_okta_id}: {error}")
                return []

            # Transform apps to our model format
            transformed_apps = []
            for app in apps:
                app_id = app.id if hasattr(app, 'id') else app.get('id')
                if app_id:
                    transformed_apps.append({
                        'group_okta_id': group_okta_id,
                        'application_okta_id': app_id,
                        'assignment_id': f"{group_okta_id}-{app_id}"
                    })
            
            # Handle pagination if needed
            page_num = 1
            while response and hasattr(response, 'has_next') and response.has_next():
                # Check for cancellation
                if self.cancellation_flag and self.cancellation_flag.is_set():
                    logger.info(f"Cancellation requested, stopping apps pagination for group {group_okta_id}")
                    break
                    
                page_num += 1
                logger.debug(f"Fetching page {page_num} of apps for group {group_okta_id}")
                
                try:
                    # Get next page with semaphore protection
                    async with self.api_semaphore:
                        next_response = await response.next()
                        await asyncio.sleep(self.RATE_LIMIT_DELAY)
                    
                    # Process next_response using normalize_okta_response
                    apps, error = normalize_okta_response(next_response)
                    
                    if error:
                        logger.error(f"Error on page {page_num} for group {group_okta_id}: {error}")
                        break
                        
                    # Process this page
                    for app in apps:
                        app_id = app.id if hasattr(app, 'id') else app.get('id')
                        if app_id:
                            transformed_apps.append({
                                'group_okta_id': group_okta_id,
                                'application_okta_id': app_id,
                                'assignment_id': f"{group_okta_id}-{app_id}"
                            })
                
                except StopAsyncIteration:
                    logger.info(f"Pagination complete after {page_num - 1} pages")
                    break
                except Exception as e:
                    logger.error(f"Error processing page {page_num} for group {group_okta_id}: {str(e)}")
                    break
            
            return transformed_apps
            
        except Exception as e:
            logger.error(f"Error getting apps for group {group_okta_id}: {str(e)}")
            return []
        
    #### DEVICES SYNC ####
    
    async def list_devices(
        self, 
        since: Optional[datetime] = None,
        processor_func: Optional[Callable] = None
    ) -> Union[List[Dict], int]:
        """List devices using direct API calls with reusable pagination."""
        try:
            logger.info("Starting device sync with direct API calls")
            
            # Build query parameters
            query_params = {
                "limit": self.DEVICE_PAGE_SIZE,
                "expand": "userSummary"
            }
            
            if since:
                since_str = since.strftime("%Y-%m-%dT%H:%M:%S.000Z")
                query_params["search"] = f'lastUpdated gt "{since_str}"'
                logger.debug(f"Using since filter: {since_str}")
            
            # Use the imported pagination function directly
            result = await _paginate_direct_api(
                self, 
                endpoint="/api/v1/devices",
                query_params=query_params,
                transform_func=self._transform_device_with_embedded_users,
                processor_func=processor_func,
                entity_name="devices",
                flow_id=getattr(self, 'flow_id', None)
            )
            
            if processor_func:
                logger.info(f"Processed {result} device records")
            else:
                logger.info(f"Retrieved {len(result)} device records")
                
            return result
            
        except Exception as e:
            logger.error(f"Error listing devices: {str(e)}")
            raise
    
    def _transform_device_with_embedded_users(self, devices) -> List[Dict]:
        """Transform devices with embedded user relationships from expand=userSummary"""
        transformed_devices = []
        
        # Handle both single device and list of devices
        device_list = devices if isinstance(devices, list) else [devices]
        
        for device in device_list:
            try:
                # Handle both dictionary and object formats
                device_dict = device if isinstance(device, dict) else device.as_dict() if hasattr(device, 'as_dict') else {}
                
                # Extract ID
                okta_id = device_dict.get('id')
                if not okta_id:
                    logger.error(f"Missing required okta_id for device")
                    continue
    
                # Extract profile data safely
                profile = device_dict.get('profile', {})
                
                # Transform base device data
                device_data = {
                    'okta_id': okta_id,
                    'status': device_dict.get('status'),
                    'display_name': profile.get('displayName'),
                    'platform': profile.get('platform'),
                    'manufacturer': profile.get('manufacturer'),
                    'model': profile.get('model'),
                    'os_version': profile.get('osVersion'),
                    'serial_number': profile.get('serialNumber'),
                    'udid': profile.get('udid'),
                    'registered': profile.get('registered', False),
                    'secure_hardware_present': profile.get('secureHardwarePresent', False),
                    'disk_encryption_type': profile.get('diskEncryptionType'),
                    'created_at': parse_timestamp(device_dict.get('created')),
                    'last_updated_at': parse_timestamp(device_dict.get('lastUpdated'))
                }
                
                # Extract embedded user relationships - FIXED LOGIC
                embedded_data = device_dict.get('_embedded', {})
                embedded_users = embedded_data.get('users', [])
                
                if embedded_users:
                    user_devices = []
                    for user_relationship in embedded_users:
                        # Get the nested user object
                        user_info = user_relationship.get('user', {})
                        user_id = user_info.get('id')  # This is the okta_id
                        
                        if user_id:
                            user_device_data = {
                                'device_okta_id': okta_id,
                                'user_okta_id': user_id,  # This should match users.okta_id
                                'management_status': user_relationship.get('managementStatus'),
                                'screen_lock_type': user_relationship.get('screenLockType'),  # Note: camelCase in API
                                'user_device_created_at': parse_timestamp(user_relationship.get('created'))
                            }
                            user_devices.append(user_device_data)
                            
                            # Debug logging
                            logger.debug(f"Created user-device relationship: device={okta_id}, user={user_id}, mgmt={user_device_data['management_status']}")
                    
                    if user_devices:
                        device_data['user_devices'] = user_devices
                        logger.debug(f"Device {okta_id} has {len(user_devices)} user relationships")
                else:
                    logger.debug(f"Device {okta_id} has no embedded users")
                
                transformed_devices.append(device_data)
                logger.debug(f"Transformed device: {device_data['display_name']} ({okta_id})")
    
            except Exception as e:
                logger.error(f"Error transforming device: {str(e)}")
                continue
        
        logger.info(f"Transformed {len(transformed_devices)} devices with embedded user relationships")
        return transformed_devices 