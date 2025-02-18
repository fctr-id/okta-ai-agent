"""
Okta API Client Wrapper

Provides async interface to Okta's API with:
- Pagination handling
- Rate limiting
- Relationship resolution
- Data transformation
- Error handling

Usage:
    async with OktaClientWrapper(tenant_id) as client:
        users = await client.list_users()
"""

import os
import asyncio
from okta.client import Client as OktaClient
from datetime import datetime
from typing import List, Any, Optional, Tuple, TypeVar, Type, Dict, Final
from src.config.settings import settings
from src.utils.logging import logger    
from okta.models import User, Group, Policy, Application


T = TypeVar('T')


from datetime import datetime, timezone

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

class OktaClientWrapper:
    """
    Async wrapper for Okta API client with relationship handling.
    
    Features:
    - Configurable page sizes and rate limits
    - Parallel processing of related entities
    - Data transformation to match database models
    - Error handling and logging
    """
    
    # API pagination limits
    USER_PAGE_SIZE: Final[int] = 200
    GROUP_PAGE_SIZE: Final[int] = 1000
    APP_PAGE_SIZE: Final[int] = 100
    POLICY_PAGE_SIZE: Final[int] = 200
    AUTH_PAGE_SIZE: Final[int] = 100
    FACTOR_PAGE_SIZE: Final[int] = 50
    FACTOR_RATE_LIMIT: Final[float] = 0  # 200ms between factor requests

    
    # Rate limit delay between requests
    RATE_LIMIT_DELAY: Final[float] = 2

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.config = {
            'orgUrl': settings.OKTA_CLIENT_ORGURL,
            'token': settings.OKTA_CLIENT_TOKEN,
            'requestTimeout': 30,
            'rateLimit': {
                'maxRetries': 3
            },
            'logging': {
                'enabled': True,
                'logLevel': settings.LOG_LEVEL
            }
        }
        self.client = None

    async def __aenter__(self):
        self.client = OktaClient(self.config)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.client = None

    async def _paginate_results(
        self, 
        method, 
        response_type: Type[T], 
        page_size: int,
        query_params: Optional[Dict] = None
    ) -> List[Dict]:
        """
        Handle API pagination with configurable page sizes.
        
        Args:
            method: Okta API method to call
            response_type: Expected response model type
            page_size: Number of records per page
            query_params: Additional query parameters
            
        Returns:
            List of API response dictionaries
            
        Handles:
        - Rate limiting between pages
        - Error checking
        - Response transformation
        """
        all_results = []
        params = query_params or {}
        params['limit'] = page_size
        
        try:
            logger.debug(f"Starting pagination with page_size={page_size}, params={params}")
            results, resp, err = await method(params)
            
            if err:
                logger.error(f"Okta API error: {err}")
                raise Exception(f"Okta API error: {err}")
            
            all_results.extend([r.as_dict() for r in results])
            logger.debug(f"Retrieved page 1 with {len(results)} records")
            
            page = 1
            while resp and resp.has_next():
                await asyncio.sleep(self.RATE_LIMIT_DELAY)
                
                page += 1
                results, resp, err = await resp.next()
                
                if err:
                    logger.error(f"Pagination error on page {page}: {err}")
                    raise Exception(f"Pagination error: {err}")
                    
                all_results.extend([r.as_dict() for r in results])
                logger.debug(f"Retrieved page {page} with {len(results)} records")
            
            logger.info(f"Total records retrieved: {len(all_results)}")
            return all_results
            
        except Exception as e:
            logger.error(f"Error in pagination: {str(e)}")
            raise     
        
   
    async def list_users(self, since: Optional[datetime] = None) -> List[Dict]:
        try:
            users = await self._paginate_results(
                self.client.list_users,  
                User,
                self.USER_PAGE_SIZE
            )
            logger.info(f"Retrieved {len(users)} total users")
            transformed_users = []
            
            for i in range(0, len(users), settings.NUM_OF_THREADS):
                batch = users[i:i + settings.NUM_OF_THREADS]
                logger.info(f"Processing batch {i//settings.NUM_OF_THREADS + 1} with {len(batch)} users")
                
                # Process batch concurrently
                batch_tasks = [self._process_single_user(user) for user in batch]
                batch_results = await asyncio.gather(*batch_tasks)
                transformed_users.extend(batch_results)
                
                logger.info(f"Completed batch {i//settings.NUM_OF_THREADS + 1}")
            
            return transformed_users
                
        except Exception as e:
            logger.error(f"Error listing users with relationships: {str(e)}")
            raise
        
    async def _process_single_user(self, user: Dict) -> Dict:
        """Process single user with relationships concurrently"""
        user_okta_id = user['id']
        
        app_links, group_memberships, factors = await asyncio.gather(
            self.get_user_app_links(user_okta_id),
            self.get_user_groups(user_okta_id),
            self.list_user_factors([user_okta_id])
        )
        
        transformed_user = {
            'okta_id': user_okta_id,
            'email': user.get('profile', {}).get('email'),
            'first_name': user.get('profile', {}).get('firstName'),
            'last_name': user.get('profile', {}).get('lastName'),
            'login': user.get('profile', {}).get('login'),
            'status': user.get('status'),
            'mobile_phone': user.get('profile', {}).get('mobilePhone'),
            'primary_phone': user.get('profile', {}).get('primaryPhone'),
            'employee_number': user.get('profile', {}).get('employeeNumber'),
            'department': user.get('profile', {}).get('department'),
            'manager': user.get('profile', {}).get('manager'),
            'created_at': parse_timestamp(user.get('created')),
            'last_updated_at': parse_timestamp(user.get('lastUpdated')),            
            'factors': factors,
            'app_links': app_links,
            'group_memberships': group_memberships
        }
        
        logger.info(
            f"User {user_okta_id} processed with {len(app_links)} app links, "
            f"{len(group_memberships)} groups, and {len(factors)} factors"
        )
        return transformed_user          

    async def list_groups(self, since: Optional[datetime] = None) -> List[Dict]:
        """
        Fetch groups with app assignments in parallel batches.
        
        Args:
            since: Optional timestamp for incremental sync
            
        Returns:
            List of group dictionaries with:
            - Basic group data
            - Application assignments
            
        Handles parallel processing of app assignments.
        """
        try:
            query_params = None
            if since:
                since_str = since.strftime("%Y-%m-%dT%H:%M:%S.000Z")
                #query_params = {"filter": f"lastUpdated gt \"{since_str}\""}
            
            # Get initial groups list
            results = await self._paginate_results(
                self.client.list_groups,
                Group,
                self.GROUP_PAGE_SIZE,
                query_params
            )
            
            transformed_groups = []
            # Process in batches
            for i in range(0, len(results), settings.NUM_OF_THREADS):
                batch = results[i:i + settings.NUM_OF_THREADS]
                tasks = [self._transform_group_with_apps(group) for group in batch]
                
                # Execute batch
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Process results
                for result in batch_results:
                    if isinstance(result, Exception):
                        logger.error(f"Error processing group: {result}")
                        continue
                    transformed_groups.append(result)
                
                logger.info(f"Processed batch of {len(batch)} groups")
            
            return transformed_groups
            
        except Exception as e:
            logger.error(f"Error listing groups: {str(e)}")
            raise
              
    
    async def _transform_group_with_apps(self, group: Dict) -> Dict:
        """Transform group data including application assignments"""
        try:
            # Get group's application assignments
            group_id = group['id']
            app_assignments = await self.get_group_apps(group_id)
            
            return {
                'okta_id': group_id,
                'name': group.get('profile', {}).get('name'),
                'description': group.get('profile', {}).get('description'),
                'created_at': parse_timestamp(group.get('created')),
                'last_updated_at': parse_timestamp(group.get('lastUpdated')),                
                'applications': app_assignments  # Include app assignments
            }
        except Exception as e:
            logger.error(f"Error transforming group with apps: {str(e)}")
            raise

    async def list_applications(self, since: Optional[datetime] = None) -> List[Dict]:
        """
        Transform raw application data to normalized format.
        
        Args:
            app: Raw application data from API
            
        Returns:
            Normalized application dictionary with:
            - Basic app data
            - SSO settings
            - Security settings
            - UI settings
            - Timestamps
            
        Handles nested data extraction safely.
        """
        try:
            # Get initial applications list
            results = await self._paginate_results(
                self.client.list_applications,
                Application,
                self.APP_PAGE_SIZE
            )
            
            transformed_apps = []
            # Process in batches
            for i in range(0, len(results), settings.NUM_OF_THREADS):
                batch = results[i:i + settings.NUM_OF_THREADS]
                tasks = [self._transform_application(app) for app in batch]
                
                # Execute batch
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Process results
                for result in batch_results:
                    if isinstance(result, Exception):
                        logger.error(f"Error processing application: {result}")
                        continue
                    transformed_apps.append(result)
                
                logger.info(f"Processed batch of {len(batch)} applications")
            
            return transformed_apps
            
        except Exception as e:
            logger.error(f"Error listing applications: {str(e)}")
            raise
    
    async def _transform_application(self, app) -> Dict:
        """Transform application with required field validation"""
        try:
            # Debug raw data
            logger.debug(f"Raw app data: {app}")
            
            # Extract ID from app object or dict
            okta_id = app.get('id') if isinstance(app, dict) else getattr(app, 'id', None)
            if not okta_id:
                logger.error(f"Missing required okta_id for app: {app}")
                return None
    
            # Extract nested data safely
            links = app.get('_links', {}) if isinstance(app, dict) else getattr(app, '_links', {})
            credentials = app.get('credentials', {}) if isinstance(app, dict) else getattr(app, 'credentials', {})
            settings = app.get('settings', {}) if isinstance(app, dict) else getattr(app, 'settings', {})
            sign_on = settings.get('signOn', {}) if isinstance(settings, dict) else getattr(settings, 'signOn', {})
            visibility = app.get('visibility', {}) if isinstance(app, dict) else getattr(app, 'visibility', {})
            
            # Transform data
            return {
                'okta_id': okta_id,
                'name': app.get('name') if isinstance(app, dict) else getattr(app, 'name', None),
                'label': app.get('label') if isinstance(app, dict) else getattr(app, 'label', None),
                'status': app.get('status') if isinstance(app, dict) else getattr(app, 'status', None),
                'sign_on_mode': app.get('signOnMode') if isinstance(app, dict) else getattr(app, 'signOnMode', None),
                'sign_on_url': sign_on.get('ssoAcsUrl') if isinstance(sign_on, dict) else getattr(sign_on, 'ssoAcsUrl', None),
                'audience': sign_on.get('audience') if isinstance(sign_on, dict) else getattr(sign_on, 'audience', None),
                'destination': sign_on.get('destination') if isinstance(sign_on, dict) else getattr(sign_on, 'destination', None),
                'created_at': parse_timestamp(app.get('created')),
                'last_updated_at': parse_timestamp(app.get('lastUpdated')),
                
                # Links
                
                'metadata_url': links.get('metadata', {}).get('href'),
                #'access_policy_url': links.get('accessPolicy', {}).get('href'),
                'policy_id': links.get('accessPolicy', {}).get('href', '').split('/')[-1] if links.get('accessPolicy', {}).get('href') else None,
                
                # Credentials
                'signing_kid': credentials.get('signing', {}).get('kid'),
                'username_template': credentials.get('userNameTemplate', {}).get('template'),
                'username_template_type': credentials.get('userNameTemplate', {}).get('type'),
                
                # Settings
                'implicit_assignment': settings.get('implicitAssignment', False),
                'admin_note': settings.get('notes', {}).get('admin'),
                'attribute_statements': settings.get('signOn', {}).get('attributeStatements', []),
                'honor_force_authn': settings.get('signOn', {}).get('honorForceAuthn', False),
                
                # Visibility
                'hide_ios': visibility.get('hide', {}).get('ios', False),
                'hide_web': visibility.get('hide', {}).get('web', False),
                
                # Timestamps
                'created_at': datetime.fromisoformat(app.get('created', '').replace('Z', '+00:00')) if app.get('created') else None,
                'last_updated_at': datetime.fromisoformat(app.get('lastUpdated', '').replace('Z', '+00:00')) if app.get('lastUpdated') else None
            }
    
        except Exception as e:
            logger.error(f"Error transforming application: {str(e)}")
            return None


    async def list_policies(self, since: Optional[datetime] = None) -> List[Dict]:
        """List policies with proper object handling"""
        try:
            # Basic policy types
            base_policies = [
                'OKTA_SIGN_ON',    # Global session
                'PASSWORD',        # Password
                'MFA_ENROLL',      # Authenticator enrollment
                'ACCESS_POLICY'    # IdP discovery
            ]
            
            all_policies = []
            
            for policy_type in base_policies:
                logger.info(f"Fetching policies of type: {policy_type}")
                query_params = {
                    "type": policy_type,
                    "limit": 200
                }
                
                if since:
                    since_str = since.strftime("%Y-%m-%dT%H:%M:%S.000Z")
                    query_params["filter"] = f"lastUpdated gt \"{since_str}\""
                
                try:
                    response = await self.client.list_policies(query_params)
                    policies = response[0] if isinstance(response, tuple) else response
                    
                    # Convert policy objects to dict
                    transformed = []
                    for policy in policies:
                        policy_dict = {
                            'okta_id': policy.id,
                            'name': policy.name,
                            'description': policy.description,
                            'status': policy.status,
                            'type': policy_type,
                            'created_at': parse_timestamp(getattr(policy, 'created', None)),
                            'last_updated_at': parse_timestamp(getattr(policy, 'lastUpdated', None))                            
                        }
                        transformed.append(policy_dict)
                    
                    all_policies.extend(transformed)
                    logger.info(f"Retrieved {len(transformed)} {policy_type} policies")
                    
                except Exception as e:
                    logger.error(f"Error processing {policy_type} policies: {str(e)}")
                    continue
            
            return all_policies
                
        except Exception as e:
            logger.error(f"Error listing policies: {str(e)}")
            raise
    

    async def list_authenticators(self, since: Optional[datetime] = None) -> List[Dict]:
        """List authenticators with pagination"""
        try:
            results = await self._paginate_results(
                self.client.list_authenticators,
                Any,
                self.AUTH_PAGE_SIZE
            )
            
            return [{
                'okta_id': r['id'],
                'name': r.get('name'),
                'status': r.get('status'),
                'type': r.get('type')
            } for r in results]
        except Exception as e:
            logger.error(f"Error listing authenticators: {str(e)}")
            raise
        
    async def list_user_factors(self, user_ids: List[str]) -> List[Dict]:
        """
        Fetch MFA factors for users in parallel batches.
        
        Args:
            user_ids: List of Okta user IDs
            
        Returns:
            List of factor dictionaries with:
            - Factor type and provider
            - Status and configuration
            - Device details for push factors
            
        Handles:
        - Parallel batch processing
        - Rate limiting
        - Error handling per user
        """        
        try:
            logger.info(f"Starting list_user_factors for {len(user_ids)} users")
            if not user_ids:
                return []
        
            all_factors = []
            valid_ids = [uid for uid in user_ids if isinstance(uid, str) and len(uid) > 10]
    
            for i in range(0, len(valid_ids), settings.NUM_OF_THREADS):
                batch = valid_ids[i:i + settings.NUM_OF_THREADS]
                logger.info(f"Processing batch of {len(batch)} users")
                tasks = [self.client.list_factors(user_id) for user_id in batch]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
    
                for user_id, result in zip(batch, batch_results):
                    if isinstance(result, Exception):
                        logger.error(f"Error fetching factors for user {user_id}: {result}")
                        continue
    
                    factors, resp, err = result
                    if err:
                        logger.error(f"API error for user {user_id}: {err}")
                        continue
    
                    #logger.info(f"Found {len(factors)} raw factors for user {user_id}")
                    transformed_factors = []
                    for factor in factors:
                        logger.debug(f"Processing factor: {vars(factor)} for user {user_id}")
                        transformed = await self._transform_factor(factor, user_id)
                        if transformed:
                            transformed_factors.append(transformed)
                            logger.debug(f"Transformed factor: {transformed}")
    
                    all_factors.extend(transformed_factors)
                    logger.debug(f"Added {len(transformed_factors)} factors for user {user_id}")
    
            return all_factors
    
        except Exception as e:
            logger.error(f"Error in batch factor processing: {str(e)}", exc_info=True)
            return []
        
    async def _transform_factor(self, factor, user_id: str) -> Dict:
        try:
            logger.debug(f"Raw factor data: {vars(factor)}")
            
            # Match test code attribute names
            base_factor = {
                'okta_id': getattr(factor, 'id', None),
                'factor_type': getattr(factor, 'factor_type', None),
                'provider': getattr(factor, 'provider', None),
                'status': getattr(factor, 'status', None),
                'created_at': None,
                'last_updated_at': None,
                'user_okta_id': user_id
            }
    
            # Handle timestamps using test pattern
            created = getattr(factor, 'created', None)
            last_updated = getattr(factor, 'last_updated', None)
    
            if created:
                try:
                    base_factor['created_at'] = datetime.fromisoformat(created.replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    logger.warning(f"Invalid created timestamp for factor {base_factor['okta_id']}")
    
            if last_updated:
                try:
                    base_factor['last_updated_at'] = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    logger.warning(f"Invalid last_updated timestamp for factor {base_factor['okta_id']}")
    
            # Handle profile data matching test code
            if hasattr(factor, 'profile') and factor.profile is not None:
                logger.debug(f"Factor type: {base_factor['factor_type']}")
                if base_factor['factor_type'] == 'email':
                    base_factor['email'] = getattr(factor.profile, 'email', None)
                elif base_factor['factor_type'] == 'sms':
                    base_factor['phone_number'] = getattr(factor.profile, 'phone_number', None)
                elif base_factor['factor_type'] in ['push', 'signed_nonce']:  # Check for converted type
                    logger.debug(f"Push factor profile: {vars(factor.profile)}")
                    base_factor.update({
                        'device_type': getattr(factor.profile, 'device_type', None),
                        'device_name': getattr(factor.profile, 'name', None),
                        'platform': getattr(factor.profile, 'platform', None)
                    })  
    
            logger.debug(f"Transformed factor: {base_factor}")
            return base_factor
                
        except Exception as e:
            logger.error(f"Error transforming factor: {str(e)}")
            return {}
    
    async def get_user_app_links(self, user_okta_id: str) -> List[Dict]:
        """
        Fetch application assignments for a user.
        
        Args:
            user_okta_id: Okta user ID
            
        Returns:
            List of app link dictionaries with:
            - Application IDs
            - Assignment details
            -
        """            
        try:
            # Create request for appLinks endpoint
            request, error = await self.client.get_request_executor().create_request(
                method='GET', 
                url=f'/api/v1/users/{user_okta_id}/appLinks'
            )
            
            if error:
                logger.error(f"Error creating appLinks request: {error}")
                return []

            # Execute request
            response, error = await self.client.get_request_executor().execute(request)
            
            if error:
                logger.error(f"Error executing appLinks request: {error}")
                return []

            app_links = response.get_body()
            
            # Transform appLinks into our model format
            transformed_links = []
            for link in app_links:
                transformed_links.append({
                    'user_okta_id': user_okta_id,
                    'application_okta_id': link.get('appInstanceId'),
                    'assignment_id': link.get('appAssignmentId'),
                    'app_instance_id': link.get('appInstanceId'),
                    'credentials_setup': link.get('credentialsSetup', False),
                    'hidden': link.get('hidden', False)
                })
            
            return transformed_links
            
        except Exception as e:
            logger.error(f"Error getting appLinks for user {user_okta_id}: {str(e)}")
            return []

    async def get_user_groups(self, user_okta_id: str) -> List[Dict]:
        """Get groups a user is a member of"""
        try:
            groups, resp, err = await self.client.list_user_groups(user_okta_id)
            
            if err:
                logger.error(f"Error getting groups for user {user_okta_id}: {err}")
                return []
                
            return [{
                'user_okta_id': user_okta_id,
                'group_okta_id': group.id
            } for group in groups]
            
        except Exception as e:
            logger.error(f"Error getting groups for user {user_okta_id}: {str(e)}")
            return []

    async def get_group_apps(self, group_okta_id: str) -> List[Dict]:
        """Get applications assigned to a group"""
        try:
            # Create request for group apps endpoint
            request, error = await self.client.get_request_executor().create_request(
                method='GET',
                url=f'/api/v1/groups/{group_okta_id}/apps'
            )
            
            if error:
                logger.error(f"Error creating group apps request: {error}")
                return []

            response, error = await self.client.get_request_executor().execute(request)
            
            if error:
                logger.error(f"Error executing group apps request: {error}")
                return []

            apps = response.get_body()
            
            # Transform apps into our model format  
            transformed_apps = []
            for app in apps:
                transformed_apps.append({
                    'group_okta_id': group_okta_id,
                    'application_okta_id': app.get('id'),
                    'assignment_id': app.get('id')  # Using app ID as assignment ID
                })
                
            return transformed_apps
            
        except Exception as e:
            logger.error(f"Error getting apps for group {group_okta_id}: {str(e)}")
            return []    