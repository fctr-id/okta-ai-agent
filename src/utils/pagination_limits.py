"""
Shared utilities for Okta tool operations including pagination and rate limiting.
"""

import asyncio
import logging
from typing import Dict, List, Any, Optional, Callable, Tuple, Union

logger = logging.getLogger(__name__)

# Get concurrent limit from settings
try:
    from src.config.settings import settings
    DEFAULT_CONCURRENT_LIMIT = settings.OKTA_CONCURRENT_LIMIT
except (ImportError, AttributeError):
    DEFAULT_CONCURRENT_LIMIT = 10  # Default fallback

# Global semaphore for rate limiting across tool calls
_RATE_LIMIT_SEMAPHORE = asyncio.Semaphore(DEFAULT_CONCURRENT_LIMIT)

def normalize_okta_response(response):
    """
    Normalize Okta API responses to handle various formats and edge cases.
    
    Args:
        response: The response from an Okta API call, which could be:
            - A 3-tuple (items, response_obj, error)
            - A 2-tuple (items, response_obj)
            - A list of items directly
            - A dictionary with _embedded key
            - A single object with as_dict method
            - None
        
    Returns:
        Tuple of (items, response, error) where items is a list or None
    """
    # Case: Response is already a tuple
    if isinstance(response, tuple):
        if len(response) == 3:
            # Standard SDK response: (results, response_obj, error)
            results, resp_obj, error = response
            
            # Handle rate limit errors specially
            if error:
                if (isinstance(error, dict) and error.get('errorCode') == 'E0000047') or \
                   (hasattr(error, 'error_code') and error.error_code == 'E0000047') or \
                   (isinstance(error, str) and 'E0000047' in error):
                    # It's a rate limit error, return original results if available
                    return [] if results is None else results, resp_obj, None
                
                # Other error, return as is
                return results, resp_obj, error
                
            # No error
            return results, resp_obj, None
            
        elif len(response) == 2:
            # Sometimes returns: (results, response_obj)
            results, resp_obj = response
            return [] if results is None else results, resp_obj, None
            
        else:
            # Unexpected tuple length
            return None, None, f"Unexpected response tuple length: {len(response)}"
    
    # Handle None response
    if response is None:
        return None, None, "No response received from Okta API"
    
    # Extract items from different response formats
    items = None
    resp_obj = response  # Use the response as the response object for non-tuple cases
    
    try:
        # Case: Response is already a list of items
        if isinstance(response, list):
            items = response
        
        # Case: Response has _embedded field (common Okta collection format)
        elif (isinstance(response, dict) and 
              "_embedded" in response and 
              isinstance(response["_embedded"], dict)):
            # Find the first list in _embedded - usually this is the entity collection
            for key, value in response["_embedded"].items():
                if isinstance(value, list):
                    items = value
                    break
        
        # Case: Response is a single object that should be wrapped in a list
        elif hasattr(response, "as_dict") or isinstance(response, dict):
            items = [response]
        
        # If we couldn't extract items in any recognizable format
        if items is None:
            return None, resp_obj, f"Could not extract items from response of type: {type(response)}"
        
        return items, resp_obj, None
    
    except Exception as e:
        return None, resp_obj, f"Error normalizing response: {str(e)}"

async def paginate_results(client_method=None, method_name=None, method_args=None, 
                          method_kwargs=None, query_params=None, entity_name="items", 
                          flow_id=None, preserve_links=False, client=None):
    """
    Handle pagination for Okta API calls with support for both method objects and string names.
    
    Args:
        client_method: The client method to call (legacy parameter, e.g., client.list_groups)
        method_name: String name of the client method (preferred parameter, e.g., "list_groups")
        method_args: List of positional arguments (e.g., [user_id] for list_user_groups)
        method_kwargs: Dictionary of keyword arguments (legacy parameter)
        query_params: Dictionary of query parameters (preferred parameter)
        entity_name: Name of the entity for logging
        flow_id: Flow ID for logging context
        preserve_links: Whether to preserve _links in the response
        client: Optional client instance (only needed if method_name is provided)
        
    Returns:
        List of items across all pages, or error dict
    """
    import inspect
    
    # Initialize parameters
    if method_args is None:
        method_args = []
    if method_kwargs is None:
        method_kwargs = {}
    if query_params is None:
        query_params = {}
    
    # Merge query_params into method_kwargs for backward compatibility
    if query_params:
        if 'query_params' in method_kwargs:
            # If both are provided, merge query_params into the existing one
            method_kwargs['query_params'].update(query_params)
        else:
            method_kwargs['query_params'] = query_params
    
    log_prefix = f"[FLOW:{flow_id}] " if flow_id else ""
    
    # Handle string method name if provided
    if method_name and not client_method:
        if not client:
            logger.error(f"{log_prefix}Client is required when using method_name")
            return {"status": "error", "error": "Client is required when using method_name"}
        
        try:
            client_method = getattr(client, method_name)
            logger.debug(f"{log_prefix}Successfully resolved method '{method_name}'")
        except AttributeError:
            logger.error(f"{log_prefix}Method not found: {method_name}")
            return {"status": "error", "error": f"Unknown method: {method_name}"}
    
    # Verify we have a callable method
    if not client_method or not callable(client_method):
        logger.error(f"{log_prefix}No callable method provided")
        return {"status": "error", "error": "No callable method provided"}
    
    # Extract method name for logging
    method_display_name = method_name or (client_method.__name__ if hasattr(client_method, '__name__') else 'unknown')
    
    # Handle query_params specifically based on method signature
    if 'query_params' in method_kwargs:
        query_params_value = method_kwargs.pop('query_params', {})
        if query_params_value:
            # Use inspection to determine correct parameter passing
            try:
                sig = inspect.signature(client_method)
                param_names = list(sig.parameters.keys())
                
                # Skip 'self' parameter
                if param_names and param_names[0] == 'self':
                    param_names = param_names[1:]
                
                # If the method accepts query_params as a parameter, pass it as kwarg
                if 'query_params' in param_names:
                    logger.debug(f"{log_prefix}Method {method_display_name} accepts query_params parameter")
                    method_kwargs['query_params'] = query_params_value
                else:
                    # For methods that don't accept query_params, expand it as direct kwargs
                    logger.debug(f"{log_prefix}Adding query params as direct kwargs for {method_display_name}")
                    method_kwargs.update(query_params_value)
            except Exception as e:
                # If inspection fails, default to passing as query_params
                logger.warning(f"{log_prefix}Error inspecting method: {str(e)}, using default query_params handling")
                method_kwargs['query_params'] = query_params_value
    
    # Automatically preserve links for application entities
    should_preserve_links = preserve_links or entity_name in ["application", "applications"]
    
    logger.debug(f"{log_prefix}Calling {method_display_name} with args={method_args}, kwargs={method_kwargs}")
    
    all_items = []
    page_count = 0
    
    try:
        # Use semaphore to control concurrency
        async with _RATE_LIMIT_SEMAPHORE:
            logger.debug(f"{log_prefix}Fetching first page of {entity_name}")
            response = await client_method(*method_args, **method_kwargs)
            
            # Normalize response to handle different return formats
            items, resp, err = normalize_okta_response(response)
            
            if err:
                logger.error(f"{log_prefix}Error fetching {entity_name}: {err}")
                return {"status": "error", "error": str(err)}
            
            # Process first page
            if items:
                # Convert objects to dictionaries if needed
                processed_items = []
                for item in items:
                    if hasattr(item, "as_dict"):
                        item_dict = item.as_dict()
                    else:
                        item_dict = item
                    
                    # Remove _links unless it should be preserved
                    if not should_preserve_links and "_links" in item_dict:
                        del item_dict["_links"]
                    
                    processed_items.append(item_dict)
                
                all_items.extend(processed_items)
                page_count += 1
                logger.debug(f"{log_prefix}Retrieved page {page_count} with {len(items)} {entity_name}")
            
            # Fetch additional pages if available
            while resp and hasattr(resp, "has_next") and resp.has_next():
                # Small delay to prevent hitting rate limits too hard
                await asyncio.sleep(0.2)
                
                async with _RATE_LIMIT_SEMAPHORE:
                    try:
                        next_response = await resp.next()
                        
                        # Normalize next page response
                        items, resp, err = normalize_okta_response(next_response)
                        
                        if err:
                            logger.warning(f"{log_prefix}Error fetching page {page_count+1}: {err}")
                            break
                            
                        if items:
                            # Convert objects to dictionaries if needed
                            processed_items = []
                            for item in items:
                                if hasattr(item, "as_dict"):
                                    item_dict = item.as_dict()
                                else:
                                    item_dict = item
                                
                                # Remove _links unless it should be preserved
                                if not should_preserve_links and "_links" in item_dict:
                                    del item_dict["_links"]
                                
                                processed_items.append(item_dict)
                            
                            all_items.extend(processed_items)
                            page_count += 1
                            logger.debug(f"{log_prefix}Retrieved page {page_count} with {len(items)} {entity_name}")
                    except Exception as e:
                        logger.error(f"{log_prefix}Exception during pagination: {str(e)}")
                        break
        
        logger.info(f"{log_prefix}Completed fetching {len(all_items)} {entity_name} in {page_count} pages")
        return all_items
        
    except asyncio.CancelledError:
        logger.info(f"{log_prefix}Pagination cancelled for {entity_name}")
        return all_items
    except Exception as e:
        logger.error(f"{log_prefix}Error in pagination for {method_display_name}: {str(e)}")
        import traceback
        logger.error(f"{log_prefix}Traceback: {traceback.format_exc()}")
        return {"status": "error", "error": str(e)}

async def handle_single_entity_request(client_method, entity_type, entity_id, 
                                     method_args=None, method_kwargs=None, flow_id=None):
    """
    Handle single entity requests (get) with proper error handling.
    
    Args:
        client_method: The client method to call
        entity_type: Type of entity for error handling
        entity_id: ID of the entity being requested
        method_args: Arguments to pass to the method
        method_kwargs: Keyword arguments to pass to the method
        flow_id: Flow ID for logging context
        
    Returns:
        Entity data dict with status field or error dict
    """
    if method_args is None:
        method_args = []
    if method_kwargs is None:
        method_kwargs = {}
    
    log_prefix = f"[FLOW:{flow_id}] " if flow_id else ""
    
    try:
        async with _RATE_LIMIT_SEMAPHORE:
            logger.debug(f"{log_prefix}Fetching {entity_type} with ID: {entity_id}")
            response = await client_method(*method_args, **method_kwargs)
            
            # Normalize response to handle different return formats
            entity, resp, err = normalize_okta_response(response)
            
            if err:
                logger.error(f"{log_prefix}Error fetching {entity_type} {entity_id}: {err}")
                return {"status": "not_found", "entity": entity_type, "id": entity_id}
            
            # Handle case where entity is a list (should be a single item)
            if isinstance(entity, list):
                if len(entity) == 0:
                    return {"status": "not_found", "entity": entity_type, "id": entity_id}
                entity = entity[0]
            
            # Convert to dictionary if needed
            if hasattr(entity, "as_dict"):
                entity_dict = entity.as_dict()
            else:
                entity_dict = entity
            
            # Add a status field to indicate success
            if isinstance(entity_dict, dict) and "status" not in entity_dict:
                entity_dict = {"status": "success", "data": entity_dict}
            
            return entity_dict
            
    except Exception as e:
        logger.error(f"{log_prefix}Error in {entity_type} request: {str(e)}")
        return {"status": "error", "error": str(e)}
    
async def make_async_request(client, method: str, url: str, headers: Dict = None, json_data: Dict = None, return_object=False, object_type=None):
    """
    Make an API request using the Okta SDK client's request executor.
    
    Args:
        client: The Okta client instance
        method: HTTP method (GET, POST, etc.)
        url: URL path or full URL
        headers: Optional additional headers
        json_data: Optional request body as dictionary
        return_object: Whether to return an Okta object (True) or raw response (False)
        object_type: Okta model type to use when return_object is True
        
    Returns:
        The API response as JSON or Okta object, or error dict on failure
    """
    try:
        # First determine if this is a full URL or a relative path
        is_full_url = url.startswith(('http://', 'https://'))
        
        # If it's a relative path, use it as-is
        api_url = url if is_full_url else url
        
        # If it's a full URL, we need to validate and extract the path
        if is_full_url:
            # Validate the URL before proceeding
            from src.utils.security_config import is_okta_url_allowed
            if not is_okta_url_allowed(url):
                error_msg = f"Security violation: URL {url} is not an authorized Okta URL"
                logger.error(error_msg)
                return {"status": "error", "error": error_msg}
                
            # Extract the path from the full URL
            from urllib.parse import urlparse
            parsed_url = urlparse(url)
            api_url = parsed_url.path
            if parsed_url.query:
                api_url += f"?{parsed_url.query}"
        
        # Set up headers
        request_headers = {}
        if headers:
            request_headers.update(headers)
        
        # Prepare request body
        body = json_data if json_data else {}
        
        # Log request details for debugging
        logger.debug(f"Making SDK client request: {method} {api_url}")
        
        # Create request using client's request executor
        request, error = await client.get_request_executor().create_request(
            method=method,
            url=api_url,
            body=body,
            headers=request_headers,
            oauth=False
        )
        
        if error:
            logger.error(f"Error creating request: {error}")
            return {"status": "error", "error": f"Error creating request: {error}"}
        
        # Execute the request
        if return_object and object_type:
            # Execute with object type for deserialization
            response, error = await client.get_request_executor().execute(request, object_type)
            
            if error:
                logger.error(f"Error executing request: {error}")
                return {"status": "error", "error": f"Error executing request: {error}"}
                
            # Get the typed object
            response_body = client.form_response_body(response.get_body())
            result = response.get_type()(response_body)
            return result
        else:
            # Execute without object type for raw response
            response, error = await client.get_request_executor().execute(request, None)
            
            if error:
                logger.error(f"Error executing request: {error}")
                return {"status": "error", "error": f"Error executing request: {error}"}
                
            # Get raw response body
            response_body = response.get_body()
            
            # Use normalize_okta_response to handle various response formats
            items, resp, err = normalize_okta_response(response_body)
            
            if err:
                return {"status": "error", "error": str(err)}
                
            # Return the normalized items directly for consistency
            # with other pagination functions
            return items if items is not None else response_body
            
    except Exception as e:
        # Log full exception details including traceback
        import traceback
        tb = traceback.format_exc()
        logger.error(f"Error making SDK request: {str(e)}")
        logger.debug(f"Exception traceback: {tb}")
        
        return {"status": "error", "error": f"Error making SDK request: {str(e)}"}   
    
async def _paginate_direct_api(
    self,
    endpoint: str,
    query_params: Optional[Dict] = None,
    transform_func: Optional[Callable] = None,
    processor_func: Optional[Callable] = None,
    entity_name: str = "items",
    flow_id: str = None
) -> Union[List[Dict], int]:
    """
    Generic direct API pagination using aiohttp for Okta REST endpoints.
    
    Args:
        endpoint: API endpoint path (e.g., "/api/v1/devices")
        query_params: Optional query parameters dict
        transform_func: Function to transform raw API response data
        processor_func: Optional function to process transformed data immediately
        entity_name: Entity name for logging
        flow_id: Flow ID for logging context
        
    Returns:
        If processor_func provided: Count of processed records
        Otherwise: List of items (transformed or raw)
    """
    log_prefix = f"[FLOW:{flow_id}] " if flow_id else ""
    
    try:
        logger.info(f"{log_prefix}Starting direct API pagination for {entity_name}")
        
        # Build initial URL
        current_url = endpoint
        if query_params:
            from urllib.parse import urlencode
            current_url += f"?{urlencode(query_params)}"
        
        # Get auth config
        base_url = self.config['orgUrl'].rstrip('/')
        api_token = self.config['token']
        
        headers = {
            "Authorization": f"SSWS {api_token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        all_items = []
        page_count = 0
        
        import aiohttp
        import re
        from urllib.parse import urlparse
        
        async with aiohttp.ClientSession() as session:
            while current_url:
                # Check for cancellation
                if hasattr(self, 'cancellation_flag') and self.cancellation_flag and self.cancellation_flag.is_set():
                    logger.info(f"{log_prefix}Cancellation requested, stopping {entity_name} pagination")
                    break
                
                page_count += 1
                full_url = f"{base_url}{current_url}"
                logger.debug(f"{log_prefix}Fetching page {page_count} of {entity_name} from: {current_url}")
                
                # Rate limiting with semaphore
                semaphore = getattr(self, 'api_semaphore', _RATE_LIMIT_SEMAPHORE)
                async with semaphore:
                    async with session.get(full_url, headers=headers) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            logger.error(f"{log_prefix}HTTP {response.status} error for {entity_name}: {error_text}")
                            break
                        
                        # Get response data
                        items = await response.json()
                        logger.debug(f"{log_prefix}Retrieved page {page_count} with {len(items)} {entity_name}")
                        
                        if not items:
                            logger.debug(f"{log_prefix}No {entity_name} returned, stopping pagination")
                            break
                        
                        # Transform items if function provided
                        if transform_func:
                            try:
                                if asyncio.iscoroutinefunction(transform_func):
                                    transformed_items = await transform_func(items)
                                else:
                                    transformed_items = transform_func(items)
                                logger.debug(f"{log_prefix}Transformed {len(items)} {entity_name} items")
                            except Exception as e:
                                logger.error(f"{log_prefix}Error transforming {entity_name}: {str(e)}")
                                transformed_items = items  # Fall back to raw items
                        else:
                            transformed_items = items
                        
                        # Process immediately or collect
                        if processor_func and transformed_items:
                            try:
                                await processor_func(transformed_items)
                                logger.debug(f"{log_prefix}Processed {len(transformed_items)} {entity_name} from page {page_count}")
                            except Exception as e:
                                logger.error(f"{log_prefix}Error processing {entity_name}: {str(e)}")
                        elif transformed_items:
                            all_items.extend(transformed_items)
                        
                        # Handle pagination using Link headers
                        current_url = None
                        all_link_headers = response.headers.getall('Link')
                        
                        # Check each Link header for rel="next"
                        for link_header in all_link_headers:
                            if 'rel="next"' in link_header:
                                logger.debug(f"{log_prefix}Found next link in page {page_count}")
                                
                                # Extract URL from: <URL>; rel="next"
                                next_match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
                                if next_match:
                                    full_next_url = next_match.group(1)
                                    
                                    # Extract path and query
                                    parsed_next = urlparse(full_next_url)
                                    current_url = parsed_next.path
                                    if parsed_next.query:
                                        current_url += f"?{parsed_next.query}"
                                    break
                        
                        if not current_url:
                            logger.debug(f"{log_prefix}No more pages - {entity_name} pagination complete")
                        
                        # Safety check
                        if page_count > 100:
                            logger.error(f"{log_prefix}Too many pages ({page_count}), stopping {entity_name} pagination")
                            break
                
                # Add delay between requests
                rate_limit_delay = getattr(self, 'RATE_LIMIT_DELAY', 0.2)
                await asyncio.sleep(rate_limit_delay)
        
        # Return results
        if processor_func:
            logger.info(f"{log_prefix}Completed processing {entity_name} across {page_count} pages")
            return page_count  # Return page count as processed count
        else:
            logger.info(f"{log_prefix}Completed fetching {len(all_items)} {entity_name} in {page_count} pages")
            return all_items
            
    except asyncio.CancelledError:
        logger.info(f"{log_prefix}Direct API pagination cancelled for {entity_name}")
        return all_items if not processor_func else page_count
    except Exception as e:
        logger.error(f"{log_prefix}Error in direct API pagination for {entity_name}: {str(e)}")
        import traceback
        logger.error(f"{log_prefix}Traceback: {traceback.format_exc()}")
        raise  
    
#async def paginate_with_request_executor(
#    client,
#    initial_url: str,
#    method: str = "GET",
#    headers: Optional[Dict] = None,
#    body: Optional[Dict] = None,
#    entity_name: str = "records",
#    **kwargs
#) -> Union[List[Dict], Dict]:
#    """
#    Handle pagination for request executor calls (devices, etc.)
#    Request executor responses don't have has_next() method like SDK methods.
#    """
#    import json
#    from urllib.parse import urlparse
#    
#    # Security check for full URLs
#    if initial_url.startswith(('http://', 'https://')):
#        from src.utils.security_config import is_okta_url_allowed
#        if not is_okta_url_allowed(initial_url):
#            return {"status": "error", "error": f"Unauthorized URL: {initial_url}"}
#        
#        # Extract path for SDK
#        parsed_url = urlparse(initial_url)
#        current_url = parsed_url.path
#        if parsed_url.query:
#            current_url += f"?{parsed_url.query}"
#    else:
#        current_url = initial_url
##    
#    logger.info(f"DEBUG: Starting pagination for {entity_name}")
#    
#    try:
#        all_items = []
#       page_count = 0
#        next_url = current_url
#        
#        while next_url:
#            page_count += 1
#            logger.info(f"DEBUG: Processing page {page_count} - URL: {next_url}")
#            
#            # Create and execute request
#            async with _RATE_LIMIT_SEMAPHORE:
#                request, error = await client.get_request_executor().create_request(
#                    method=method,
#                    url=next_url,
#                    body=body or {},
#                    headers=headers or {}
#                )
#                
#                if error:
#                    logger.error(f"DEBUG: Error creating request: {error}")
#                    return {"status": "error", "error": f"Error creating request: {error}"}
#                
#                response, error = await client.get_request_executor().execute(request, None)
#                
#                if error:
#                    logger.error(f"DEBUG: Error executing request: {error}")
#                    return {"status": "error", "error": f"Error executing request: {error}"}
#            
#            # Extract items from response
#            if hasattr(response, 'get_body'):
#                response_body = response.get_body()
#                logger.info(f"DEBUG: Response body type: {type(response_body)}")
#                
#                # Parse response body
#                if isinstance(response_body, str):
#                    try:
#                        data = json.loads(response_body)
#                    except json.JSONDecodeError as e:
#                        logger.error(f"DEBUG: JSON decode error: {e}")
#                        break
#                else:
#                    data = response_body
#                
#                # Extract items
##                if isinstance(data, list):
 #                   items = data
#                elif isinstance(data, dict):
#                    items = data.get('records', data.get('results', data.get('items', [])))
#                    if not items and data and '_embedded' not in data:
#                        items = [data]
#                else:
#                    items = []
#                
#                logger.info(f"DEBUG: Page {page_count} has {len(items)} items")
#                
#                # Add items to collection
#                if items:
#                    processed_items = []
#                    for item in items:
#                        if hasattr(item, "as_dict"):
#                            processed_items.append(item.as_dict())
#                        else:
#                            processed_items.append(item)
#                    all_items.extend(processed_items)#
#                else:
#                    logger.info(f"DEBUG: No items in page {page_count}, stopping")
#                    break
#                
#                # Check for next page using Link header (not has_next())
#                next_url = None
#                if hasattr(response, 'get_headers'):
#                    headers = response.get_headers()
##                    link_header = headers.get('Link', '')
#                   logger.info(f"DEBUG: Link header: {link_header}")
#                   
#                    # Parse Link header for next URL
#                    if 'rel="next"' in link_header:
#                        # Extract next URL from Link header
#                        # Format: <https://domain/api/v1/devices?after=...&limit=1>; rel="next"
#                        import re
#                        next_match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
#                        if next_match:
#                            full_next_url = next_match.group(1)
#                            # Extract just the path and query
#                            parsed_next = urlparse(full_next_url)
#                            next_url = parsed_next.path
#                            if parsed_next.query:
#                                next_url += f"?{parsed_next.query}"
#                            logger.info(f"DEBUG: Found next page URL: {next_url}")
#                        else:
#                            logger.info(f"DEBUG: Could not parse next URL from Link header")
#                    else:
#                        logger.info(f"DEBUG: No rel='next' found in Link header")
#                else:
#                    logger.info(f"DEBUG: No headers available")
#                
#                if not next_url:
#                    logger.info(f"DEBUG: No more pages, stopping")
#                    break
#                    
#                await asyncio.sleep(0.2)  # Rate limit delay
#            else:
##                logger.error(f"DEBUG: Response has no get_body method")
#                break
#        
#        logger.info(f"DEBUG: Completed pagination: {len(all_items)} {entity_name} in {page_count} pages")
#        return all_items
#        
#    except Exception as e:
#        logger.error(f"DEBUG: Error in pagination: {str(e)}")
#        import traceback
#        logger.error(f"DEBUG: Traceback: {traceback.format_exc()}")
#        return {"status": "error", "error": str(e)}

