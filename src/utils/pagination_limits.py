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
    
async def paginate_with_request_executor(
    client,
    initial_url: str,
    method: str = "GET",
    headers: Optional[Dict] = None,
    body: Optional[Dict] = None,
    entity_name: str = "records",
    flow_id: Optional[str] = None,
    preserve_links: bool = False
) -> Union[List[Dict], Dict]:
    """
    Handle pagination using Okta SDK request executor.
    """
    import json
    from urllib.parse import urlparse
    
    log_prefix = f"[FLOW:{flow_id}] " if flow_id else ""
    
    # Security check for full URLs
    if initial_url.startswith(('http://', 'https://')):
        from src.utils.security_config import is_okta_url_allowed
        if not is_okta_url_allowed(initial_url):
            error_msg = f"Security violation: URL {initial_url} is not an authorized Okta URL"
            logger.error(f"{log_prefix}{error_msg}")
            return {"status": "error", "error": error_msg}
        
        # Extract path for SDK request executor
        parsed_url = urlparse(initial_url)
        current_url = parsed_url.path
        if parsed_url.query:
            current_url += f"?{parsed_url.query}"
    else:
        current_url = initial_url
    
    all_items = []
    page_count = 0
    
    logger.info(f"{log_prefix}Starting pagination for {entity_name} using request executor")
    
    try:
        # Make initial request
        async with _RATE_LIMIT_SEMAPHORE:
            request, error = await client.get_request_executor().create_request(
                method=method,
                url=current_url,
                body=body or {},
                headers=headers or {},
                oauth=False
            )
            
            if error:
                logger.error(f"{log_prefix}Error creating initial request: {error}")
                return {"status": "error", "error": f"Error creating request: {error}"}
            
            response, error = await client.get_request_executor().execute(request, None)
            
            if error:
                logger.error(f"{log_prefix}Error executing initial request: {error}")
                return {"status": "error", "error": f"Error executing request: {error}"}
        
        # Process all pages - handle both response types
        while True:
            page_count += 1
            logger.debug(f"{log_prefix}Processing page {page_count}")
            
            # Handle different response types
            if isinstance(response, list):
                # Response is already a list of items
                logger.debug(f"{log_prefix}Response is a list with {len(response)} items")
                items = response
                has_next = False  # List responses typically don't have pagination
            elif hasattr(response, 'get_body'):
                # Response is an OktaAPIResponse object
                response_body = response.get_body()
                
                if not response_body:
                    logger.debug(f"{log_prefix}Empty response body for page {page_count}")
                    break
                
                # Parse JSON response
                try:
                    if isinstance(response_body, str):
                        data = json.loads(response_body)
                    else:
                        data = response_body
                except json.JSONDecodeError as e:
                    logger.error(f"{log_prefix}Error parsing JSON response: {e}")
                    break
                
                # Extract items from response
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict):
                    items = data.get('records', data.get('results', data.get('items', [])))
                    if not items and data and '_embedded' not in data:
                        items = [data]
                else:
                    items = []
                
                # Check if there are more pages
                has_next = hasattr(response, "has_next") and response.has_next()
            else:
                # Unknown response type
                logger.error(f"{log_prefix}Unknown response type: {type(response)}")
                break
            
            if not items:
                logger.debug(f"{log_prefix}No items found in page {page_count}")
                break
            
            # Process items
            processed_items = []
            for item in items:
                # Convert to dict if needed
                if hasattr(item, "as_dict"):
                    item_dict = item.as_dict()
                else:
                    item_dict = item
                
                # Remove _links unless preserved
                if not preserve_links and isinstance(item_dict, dict) and "_links" in item_dict:
                    del item_dict["_links"]
                
                processed_items.append(item_dict)
            
            all_items.extend(processed_items)
            logger.debug(f"{log_prefix}Page {page_count}: retrieved {len(processed_items)} {entity_name}")
            
            # Check for next page
            if has_next:
                logger.debug(f"{log_prefix}More pages available, fetching next page")
                
                # Small delay to avoid rate limits
                await asyncio.sleep(0.2)
                
                async with _RATE_LIMIT_SEMAPHORE:
                    try:
                        # Get next page
                        response, error = await response.next()
                        
                        if error:
                            logger.error(f"{log_prefix}Error getting next page: {error}")
                            break
                        
                    except StopAsyncIteration:
                        logger.debug(f"{log_prefix}Reached end of pagination")
                        break
                    except Exception as e:
                        logger.error(f"{log_prefix}Error during pagination: {str(e)}")
                        break
            else:
                logger.debug(f"{log_prefix}No more pages available")
                break
        
        logger.info(f"{log_prefix}Completed pagination: {len(all_items)} {entity_name} in {page_count} pages")
        return all_items
        
    except Exception as e:
        logger.error(f"{log_prefix}Error in request executor pagination: {str(e)}")
        import traceback
        logger.error(f"{log_prefix}Traceback: {traceback.format_exc()}")
        return {"status": "error", "error": str(e)}