"""
Shared utilities for Okta tool operations including pagination and rate limiting.
"""

import asyncio
import logging
from typing import Dict, List, Any, Optional, Callable, Tuple

logger = logging.getLogger(__name__)

# Get concurrent limit from settings
try:
    from src.config.settings import settings
    DEFAULT_CONCURRENT_LIMIT = settings.OKTA_CONCURRENT_LIMIT
except (ImportError, AttributeError):
    DEFAULT_CONCURRENT_LIMIT = 10  # Default fallback

# Global semaphore for rate limiting across tool calls
_RATE_LIMIT_SEMAPHORE = asyncio.Semaphore(DEFAULT_CONCURRENT_LIMIT)

async def paginate_results(client_method, method_args=None, method_kwargs=None, 
                          entity_name="items", flow_id=None):
    """
    Handle pagination for Okta API calls with rate limiting.
    
    Args:
        client_method: The client method to call (e.g., client.list_groups)
        method_args: Arguments to pass to the method
        method_kwargs: Keyword arguments to pass to the method
        entity_name: Name of the entity for logging
        flow_id: Flow ID for logging context
        
    Returns:
        List of all items across pages, or error dict
    """
    if method_args is None:
        method_args = []
    if method_kwargs is None:
        method_kwargs = {}
    
    log_prefix = f"[FLOW:{flow_id}] " if flow_id else ""
    all_items = []
    page_count = 0
    
    try:
        # Use semaphore to control concurrency
        async with _RATE_LIMIT_SEMAPHORE:
            logger.debug(f"{log_prefix}Fetching first page of {entity_name}")
            items, resp, err = await client_method(*method_args, **method_kwargs)
            
            if err:
                logger.error(f"{log_prefix}Error fetching {entity_name}: {err}")
                return {"status": "error", "error": str(err)}
            
            # Process first page
            if items:
                all_items.extend([item.as_dict() for item in items])
                page_count += 1
                logger.debug(f"{log_prefix}Retrieved page {page_count} with {len(items)} {entity_name}")
            
            # Fetch additional pages if available
            while resp and resp.has_next():
                # Small delay to prevent hitting rate limits too hard
                await asyncio.sleep(0.2)
                
                async with _RATE_LIMIT_SEMAPHORE:
                    try:
                        items, err = await resp.next()
                        
                        if err:
                            logger.warning(f"{log_prefix}Error fetching page {page_count+1}: {err}")
                            break
                            
                        if items:
                            all_items.extend([item.as_dict() for item in items])
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
            entity, resp, err = await client_method(*method_args, **method_kwargs)
            
            if err:
                logger.error(f"{log_prefix}Error fetching {entity_type} {entity_id}: {err}")
                return {"status": "not_found", "entity": entity_type, "id": entity_id}
            
            logger.debug(f"{log_prefix}Successfully retrieved {entity_type} {entity_id}")
            return entity.as_dict()
            
    except Exception as e:
        logger.error(f"{log_prefix}Error in {entity_type} request: {str(e)}")
        return {"status": "error", "error": str(e)}