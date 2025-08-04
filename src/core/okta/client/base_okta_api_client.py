import os
import asyncio
import aiohttp
import re
import logging
from typing import Dict, Any, Optional
from urllib.parse import urlencode
from datetime import datetime


class OktaAPIClient:
    """
    Simplified Okta API client that automatically handles pagination based on Link headers.
    
    Usage:
        client = OktaAPIClient()
        result = await client.make_request("/api/v1/logs", params={"since": "2024-01-01T00:00:00.000Z"})
        result = await client.make_request("/api/v1/users", method="POST", body={"profile": {...}})
    """
    
    def __init__(self, timeout: int = 300, max_pages: int = 100):
        """
        Initialize the API client.
        
        Args:
            timeout: HTTP request timeout in seconds
            max_pages: Maximum pages to fetch (safety limit)
        """
        self.timeout = timeout
        self.max_pages = max_pages
        
        # Setup logging - self-contained logging setup
        self.logger = logging.getLogger(f"{__name__}.OktaAPIClient")
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
        
        self._setup_config()
    
    def _setup_config(self):
        """Setup Okta configuration from environment variables."""
        self.logger.debug("Setting up Okta API client configuration")
        
        # Get Okta domain
        self.okta_domain = os.getenv('OKTA_CLIENT_ORGURL') or os.getenv('OKTA_ORG_URL')
        if self.okta_domain:
            self.okta_domain = self.okta_domain.replace('https://', '').rstrip('/')
        
        # Get API token
        self.api_token = os.getenv('OKTA_API_TOKEN') or os.getenv('SSWS_API_KEY')
        
        if not self.okta_domain or not self.api_token:
            self.logger.error("Missing Okta configuration. Required: OKTA_CLIENT_ORGURL and OKTA_API_TOKEN environment variables")
            raise ValueError("Missing Okta configuration. Set OKTA_CLIENT_ORGURL and OKTA_API_TOKEN environment variables.")
        
        # Setup headers
        self.headers = {
            "Authorization": f"SSWS {self.api_token}",
            "Accept": "application/json, text/xml, application/xml, */*",
            "Content-Type": "application/json"
        }
        
        self.base_url = f"https://{self.okta_domain}"
        self.logger.info(f"Okta API client configured for domain: {self.okta_domain}")
        self.logger.debug(f"Client settings - Timeout: {self.timeout}s, Max Pages: {self.max_pages}")
    
    def _optimize_params(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """
        Optimize query parameters for better rate limit efficiency.
        
        Based on Okta best practices: use maximum limit values to reduce API calls.
        """
        if not params:
            params = {}
        else:
            params = params.copy()  # Don't modify original
        
        # Only add limit if not already specified
        if 'limit' not in params:
            # Set optimal limits based on endpoint patterns
            if '/logs' in endpoint:
                params['limit'] = '1000'  # System logs can handle up to 1000
                self.logger.debug(f"Optimized system logs limit to 1000 for endpoint: {endpoint}")
            elif '/users' in endpoint:
                params['limit'] = '200'   # Users endpoint max is 200
                self.logger.debug(f"Optimized users limit to 200 for endpoint: {endpoint}")
            elif '/groups' in endpoint:
                params['limit'] = '200'   # Groups endpoint max is 200  
                self.logger.debug(f"Optimized groups limit to 200 for endpoint: {endpoint}")
            elif '/apps' in endpoint:
                params['limit'] = '200'   # Apps endpoint max is 200
                self.logger.debug(f"Optimized apps limit to 200 for endpoint: {endpoint}")
            else:
                params['limit'] = '100'   # Default safe maximum for most endpoints
                self.logger.debug(f"Applied default limit of 200 for endpoint: {endpoint}")
        else:
            self.logger.debug(f"Using existing limit parameter: {params['limit']} for endpoint: {endpoint}")
        
        return params
    
    async def make_request(self, 
                          endpoint: str,
                          method: str = "GET", 
                          params: Optional[Dict] = None,
                          body: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Make an API request with automatic pagination detection and rate limit optimization.
        
        Args:
            endpoint: API endpoint (e.g., "/api/v1/logs", "/api/v1/users")
            method: HTTP method (GET, POST, PUT, DELETE)
            params: Query parameters
            body: Request body for POST/PUT requests
            
        Returns:
            Dict with status and data/error
        """
        self.logger.info(f"Making {method} request to endpoint: {endpoint}")
        if params:
            self.logger.debug(f"Request parameters: {params}")
        
        try:
            # Optimize parameters for better rate limit efficiency
            if method.upper() == "GET":
                params = self._optimize_params(endpoint, params)
                return await self._handle_get_request(endpoint, params)
            else:
                return await self._handle_single_request(endpoint, method, params, body)
                
        except Exception as e:
            self.logger.error(f"API request failed for {endpoint}: {str(e)}")
            return {
                "status": "error",
                "error": f"API request failed: {str(e)}",
                "error_code": "REQUEST_FAILED"
            }
    
    async def _handle_get_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Handle GET request with automatic pagination detection."""
        
        # Start with the first request
        self.logger.debug(f"Starting GET request for {endpoint}")
        first_result = await self._single_request(endpoint, "GET", params)
        
        if first_result["status"] != "success":
            return first_result
        
        # Check if this response has pagination (Link header with rel="next")
        link_header = first_result.get("link_header", "")
        if not link_header or 'rel="next"' not in link_header:
            # No pagination needed, return single result
            self.logger.debug(f"No pagination detected for {endpoint}")
            return first_result
        
        # Pagination detected, collect all pages
        self.logger.info(f"Pagination detected for {endpoint}, collecting all pages...")
        all_data = []
        
        # Add first page data
        first_data = first_result["data"]
        if isinstance(first_data, list):
            all_data.extend(first_data)
        else:
            all_data.append(first_data)
        
        page_count = 1
        current_link = link_header
        
        self.logger.debug(f"Page 1: Retrieved {len(first_data) if isinstance(first_data, list) else 1} items")
        
        # Continue paginating
        while current_link and page_count < self.max_pages:
            next_url = self._extract_next_url(current_link)
            if not next_url:
                break
            
            page_count += 1
            self.logger.debug(f"Fetching page {page_count} from: {next_url}")
            
            page_result = await self._single_request(next_url, "GET")
            
            if page_result["status"] != "success":
                self.logger.error(f"Failed to retrieve page {page_count}: {page_result.get('error', 'Unknown error')}")
                return page_result
            
            page_data = page_result["data"]
            
            # Handle empty pages (stops infinite pagination)
            if not page_data or (isinstance(page_data, list) and len(page_data) == 0):
                self.logger.info(f"Empty page {page_count} detected, stopping pagination")
                break
            
            # Add page data
            if isinstance(page_data, list):
                all_data.extend(page_data)
                self.logger.debug(f"Page {page_count}: Added {len(page_data)} items (total: {len(all_data)})")
            else:
                all_data.append(page_data)
                self.logger.debug(f"Page {page_count}: Added 1 item (total: {len(all_data)})")
            
            # Get next link for next iteration
            current_link = page_result.get("link_header", "")
            
            # Small delay between requests
            await asyncio.sleep(0.2)
        
        self.logger.info(f"Pagination complete for {endpoint}: {len(all_data)} total items across {page_count} pages")
        
        return {
            "status": "success",
            "data": all_data,
            "pages": page_count,
            "total_items": len(all_data)
        }
    
    async def _handle_single_request(self, endpoint: str, method: str, 
                                   params: Optional[Dict] = None, 
                                   body: Optional[Dict] = None) -> Dict[str, Any]:
        """Handle non-GET requests (POST, PUT, DELETE) - no pagination."""
        return await self._single_request(endpoint, method, params, body)
    
    async def _single_request(self, endpoint: str, method: str, 
                            params: Optional[Dict] = None,
                            body: Optional[Dict] = None) -> Dict[str, Any]:
        """Make a single API request with comprehensive error handling and rate limit monitoring."""
        
        # Build URL - handle both full URLs and endpoints
        if endpoint.startswith('http'):
            # Full URL from pagination
            url = endpoint
        else:
            # Relative endpoint
            if not endpoint.startswith('/'):
                endpoint = f'/{endpoint}'
            url = f"{self.base_url}{endpoint}"
            if params:
                url += f"?{urlencode(params)}"
        
        # Rate limiting retry logic
        max_retries = 5  # Increased retries for rate limiting
        retry_count = 0
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
            while retry_count < max_retries:
                try:
                    async with session.request(
                        method=method.upper(),
                        url=url,
                        headers=self.headers,
                        json=body if body else None
                    ) as response:
                        
                        # Monitor rate limit headers from Okta
                        rate_limit_limit = response.headers.get('X-Rate-Limit-Limit')
                        rate_limit_remaining = response.headers.get('X-Rate-Limit-Remaining') 
                        rate_limit_reset = response.headers.get('X-Rate-Limit-Reset')
                        
                        # Log rate limit info if headers are present
                        if rate_limit_limit and rate_limit_remaining:
                            remaining = int(rate_limit_remaining)
                            limit = int(rate_limit_limit)
                            
                            self.logger.debug(f"Rate limit status: {remaining}/{limit} requests remaining (reset: {rate_limit_reset})")
                            
                            # Warning if we're getting close to rate limit - use debug for proactive warnings
                            if remaining <= (limit * 0.1):  # Less than 10% remaining
                                self.logger.debug(f"Rate limit critical: Only {remaining}/{limit} requests remaining until reset")
                            elif remaining <= (limit * 0.25):  # Less than 25% remaining  
                                self.logger.debug(f"Rate limit low: {remaining}/{limit} requests remaining until reset")
                        
                        # Handle rate limiting (429)
                        if response.status == 429:
                            # Check if this is concurrent or org-wide rate limit
                            is_concurrent = (rate_limit_limit == '0' and rate_limit_remaining == '0')
                            
                            if is_concurrent:
                                # Concurrent rate limit - shorter retry with backoff
                                retry_after = min(int(response.headers.get('Retry-After', '5')), 30)
                                self.logger.warning(f"Concurrent rate limit exceeded on {endpoint}. Waiting {retry_after} seconds for retry {retry_count + 1}/{max_retries}")
                            else:
                                # Org-wide rate limit - use Retry-After header
                                retry_after = int(response.headers.get('Retry-After', '60'))
                                self.logger.warning(f"Org-wide rate limit exceeded on {endpoint}. Waiting {retry_after} seconds for retry {retry_count + 1}/{max_retries}")
                                self.logger.info(f"Rate limit details: {rate_limit_remaining}/{rate_limit_limit} remaining, resets at epoch {rate_limit_reset}")
                            
                            if retry_count < max_retries - 1:  # Don't sleep on last retry
                                # Exponential backoff for consecutive rate limits
                                backoff_multiplier = 1 + (retry_count * 0.5)
                                actual_wait = min(retry_after * backoff_multiplier, 300)  # Max 5 min wait
                                
                                self.logger.info(f"Applying backoff multiplier {backoff_multiplier:.1f}x: waiting {actual_wait:.0f} seconds for rate limit to clear")
                                await asyncio.sleep(actual_wait)
                                retry_count += 1
                                continue
                        
                        # Process response with comprehensive error handling
                        result = await self._process_response(response)
                        
                        # Add Link header and rate limit info for pagination detection
                        if result["status"] == "success":
                            result["link_header"] = response.headers.get('Link', '')
                            
                            # Include rate limit information in successful responses
                            if rate_limit_limit and rate_limit_remaining:
                                result["rate_limit_info"] = {
                                    "limit": int(rate_limit_limit),
                                    "remaining": int(rate_limit_remaining),
                                    "reset_time": rate_limit_reset
                                }
                                self.logger.debug(f"Request successful with rate limit: {rate_limit_remaining}/{rate_limit_limit} remaining")
                        
                        return result
                        
                except asyncio.TimeoutError:
                    self.logger.error(f"Request timeout after {self.timeout} seconds for {endpoint}")
                    return {
                        "status": "error",
                        "error": f"Request timeout after {self.timeout} seconds",
                        "error_code": "TIMEOUT"
                    }
                except aiohttp.ClientError as e:
                    self.logger.error(f"Network error for {endpoint}: {str(e)}")
                    return {
                        "status": "error", 
                        "error": f"Network error: {str(e)}",
                        "error_code": "NETWORK_ERROR"
                    }
                except Exception as e:
                    self.logger.error(f"Unexpected error for {endpoint}: {str(e)}")
                    return {
                        "status": "error",
                        "error": f"Unexpected error: {str(e)}",
                        "error_code": "UNEXPECTED_ERROR"
                    }
            
            # All retries exhausted
            self.logger.error(f"All {max_retries} retries exhausted for {endpoint} due to rate limiting")
            return {
                "status": "error",
                "error": f"Request failed after {max_retries} retries due to rate limiting",
                "error_code": "E0000047",
                "rate_limit_exceeded": True
            }
    
    def _extract_next_url(self, link_header: str) -> Optional[str]:
        """Extract next URL from Link header."""
        if not link_header or 'rel="next"' not in link_header:
            return None
        
        # Parse Link header: <URL>; rel="next"
        next_match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
        if not next_match:
            return None
        
        return next_match.group(1)  # Return full URL for pagination
    
    async def _process_response(self, response) -> Dict[str, Any]:
        """Process a single response with proper Okta error handling."""
        
        # Handle specific HTTP status codes
        if response.status == 401:
            return {
                "status": "error",
                "error": "Authentication failed: Invalid or expired API token",
                "error_code": "E0000011"
            }
        
        if response.status == 403:
            return {
                "status": "error", 
                "error": "Access forbidden: Insufficient permissions for this operation",
                "error_code": "E0000006"
            }
        
        if response.status == 404:
            return {
                "status": "error",
                "error": "Resource not found: The requested resource does not exist",
                "error_code": "E0000007"
            }
        
        if response.status == 429:
            # Rate limiting - check if concurrent or org-wide
            rate_limit_limit = response.headers.get('X-Rate-Limit-Limit', '0')
            rate_limit_remaining = response.headers.get('X-Rate-Limit-Remaining', '0')
            retry_after = response.headers.get('Retry-After', '60')
            
            if rate_limit_limit == '0' and rate_limit_remaining == '0':
                # Concurrent rate limit exceeded
                return {
                    "status": "error",
                    "error": "Too many concurrent requests in flight. Reduce concurrent API calls.",
                    "error_code": "E0000047",
                    "rate_limit_type": "concurrent",
                    "retry_after": retry_after
                }
            else:
                # Org-wide rate limit exceeded
                return {
                    "status": "error",
                    "error": f"Rate limit exceeded: {rate_limit_remaining}/{rate_limit_limit} requests remaining. Retry after {retry_after} seconds",
                    "error_code": "E0000047",
                    "rate_limit_type": "org_wide",
                    "retry_after": retry_after,
                    "limit": rate_limit_limit,
                    "remaining": rate_limit_remaining
                }
        
        if response.status >= 500:
            return {
                "status": "error",
                "error": f"Server error: Okta service temporarily unavailable (HTTP {response.status})",
                "error_code": "E0000009"
            }
        
        if response.status >= 400:
            try:
                error_body = await response.json()
                # Parse Okta-specific error format
                if isinstance(error_body, dict):
                    error_code = error_body.get('errorCode', 'UNKNOWN')
                    error_summary = error_body.get('errorSummary', f'HTTP {response.status} error')
                    error_id = error_body.get('errorId', 'N/A')
                    error_causes = error_body.get('errorCauses', [])
                    
                    error_msg = f"{error_summary}"
                    if error_causes:
                        cause_details = ', '.join([cause.get('errorSummary', str(cause)) for cause in error_causes])
                        error_msg += f" Causes: {cause_details}"
                    
                    return {
                        "status": "error",
                        "error": error_msg,
                        "error_code": error_code,
                        "error_id": error_id,
                        "http_status": response.status
                    }
                else:
                    error_text = str(error_body)
            except:
                error_text = await response.text()
            
            return {
                "status": "error",
                "error": f"HTTP {response.status}: {error_text}",
                "http_status": response.status
            }
        
        # Success case
        try:
            # Check content type to determine how to parse response
            content_type = response.headers.get('Content-Type', '').lower()
            
            if 'xml' in content_type:
                # Handle XML responses (e.g., SAML metadata)
                data = await response.text()
                return {
                    "status": "success", 
                    "data": data
                }
            else:
                # Handle JSON responses (default)
                data = await response.json()
                # Normalize the data structure to ensure consistent format
                normalized_data = self._normalize_okta_response(data)
                return {
                    "status": "success", 
                    "data": normalized_data
                }
        except Exception as e:
            return {
                "status": "error",
                "error": f"Failed to parse response: {str(e)}"
            }

    def _normalize_okta_response(self, data):
        """
        Normalize Okta API responses to a consistent format.
        
        Inspired by Okta SDK's OktaAPIResponse class but handles multiple 
        API response wrapper patterns found in different Okta endpoints.
        
        Common Okta response patterns:
        - Direct array: [{...}, {...}]
        - IAM/SCIM: {"value": [...], "totalResults": N}
        - Search: {"results": [...], "count": N}  
        - Paginated: {"items": [...], "totalCount": N}
        - Collections: {"data": [...]}
        - Embedded: {"_embedded": {"items": [...]}}
        - Single resource: {...}
        """
        # Handle null/empty responses
        if data is None:
            return []
        
        # Direct array - most common case
        if isinstance(data, list):
            return data
        
        # Non-dict responses (primitives, etc.)
        if not isinstance(data, dict):
            return data
        
        # Known wrapper patterns (ordered by frequency in Okta APIs)
        wrapper_keys = [
            'value',    # IAM/SCIM endpoints
            'results',  # Search endpoints  
            'items',    # Paginated endpoints
            'data'      # Collection endpoints
        ]
        
        for key in wrapper_keys:
            if key in data and isinstance(data[key], list):
                self.logger.debug(f"Normalized response with '{key}' wrapper")
                return data[key]
        
        # Check for embedded resources pattern
        if "_embedded" in data and isinstance(data["_embedded"], dict):
            for key, value in data["_embedded"].items():
                if isinstance(value, list):
                    self.logger.debug(f"Normalized embedded response '_embedded.{key}'")
                    return value
        
        # Dynamic wrapper detection (fallback for custom endpoints)
        for key, value in data.items():
            if (isinstance(value, list) and len(value) > 0 and 
                key not in ['_links', 'meta', 'metadata', 'pagination']):
                self.logger.debug(f"Normalized response with dynamic '{key}' wrapper")
                return value
        
        # Single resource detection
        if isinstance(data, dict):
            resource_indicators = ['id', 'okta_id', 'userId', 'groupId', 'appId', 'name', 'login', 'email']
            if any(key in data for key in resource_indicators):
                self.logger.debug("Normalized single resource to list format")
                return [data]
            
            # Metadata-only response
            metadata_keys = {'_links', 'meta', 'metadata', 'totalCount', 'totalResults', 'count', 'size', 'limit', 'after', 'cursor'}
            if all(key in metadata_keys for key in data.keys()):
                self.logger.debug("Metadata-only response, returning empty list")
                return []
        
        # Fallback: return as-is (similar to Okta SDK approach)
        self.logger.debug(f"Response format not recognized, returning as-is: {type(data)}")
        return data



