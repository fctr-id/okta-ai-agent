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

async def paginate_results(client_method, method_args=None, method_kwargs=None, 
                          entity_name="items", flow_id=None, preserve_links=False):
    """
    Handle pagination for Okta API calls with rate limiting.
    
    Args:
        client_method: The client method to call (e.g., client.list_groups)
        method_args: Arguments to pass to the method
        method_kwargs: Keyword arguments to pass to the method
        entity_name: Name of the entity for logging
        flow_id: Flow ID for logging context
        preserve_links: Whether to preserve _links in the response (defaults to False)
        
    Returns:
        List of all items across pages, or error dict
    """
    if method_args is None:
        method_args = []
    if method_kwargs is None:
        method_kwargs = {}
    
    # Automatically preserve links for application entities
    should_preserve_links = preserve_links or entity_name in ["application", "applications"]
    
    log_prefix = f"[FLOW:{flow_id}] " if flow_id else ""
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
        logger.error(f"{log_prefix}Error in pagination: {str(e)}")
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
        Entity data dict or error dict
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
                return entity.as_dict()
            else:
                return entity
            
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