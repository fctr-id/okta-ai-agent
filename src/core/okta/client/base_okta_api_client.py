import os
import sys
import asyncio
import aiohttp
import re
import logging
import random
from typing import Dict, Any, Optional
from urllib.parse import urlencode
from datetime import datetime
import json  # NEW: for structured progress events

# Import settings for configuration
try:
    from src.config.settings import settings
except ImportError:
    # Fallback for different execution contexts
    settings = None

# Import OAuth2 manager for modern authentication
OktaOAuth2Manager = None
import_success = False

try:
    from src.core.security.oauth2_client import OktaOAuth2Manager
    import_success = "src.core.security.oauth2_client"
except ImportError:
    try:
        # Alternative import path for different execution contexts
        import sys
        from pathlib import Path
        
        # Add the security module path
        security_path = Path(__file__).parent.parent.parent / "security"
        sys.path.insert(0, str(security_path))
        
        from oauth2_client import OktaOAuth2Manager
        import_success = "oauth2_client (via security path)"
    except ImportError:
        try:
            # Try relative import
            import sys
            import os
            
            # Get the project root directory
            current_dir = Path(__file__).parent  # client folder
            core_dir = current_dir.parent        # okta folder parent (core)
            security_dir = core_dir / "security"
            
            sys.path.insert(0, str(security_dir))
            from oauth2_client import OktaOAuth2Manager
            import_success = f"oauth2_client (via {security_dir})"
        except ImportError:
            # Final fallback - OAuth2 not available
            import_success = False
            OktaOAuth2Manager = None

# Import centralized logging - DISABLED to prevent stdout contamination in subprocess execution
# Using self-contained logging instead to ensure logs go to stderr
import logging

# Debug: Print import result (will be logged later)
oauth2_import_status = f"OAuth2Manager import: {'✅ ' + import_success if import_success else '❌ Failed'}"


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
        
        # OAuth2 authentication support
        self.oauth2_manager = None
        self.auth_method = 'api_token'  # Default to existing method
        
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
        
        # Progress tracking state (for throttling entity progress updates)
        self._entity_progress_state = {}
        
        self._setup_config()
    
    def _setup_config(self):
        """Setup Okta configuration from environment variables."""
        self.logger.debug("Setting up Okta API client configuration")
        
        # Get Okta domain
        self.okta_domain = os.getenv('OKTA_CLIENT_ORGURL') or os.getenv('OKTA_ORG_URL')
        if self.okta_domain:
            self.okta_domain = self.okta_domain.replace('https://', '').rstrip('/')
        
        if not self.okta_domain:
            self.logger.error("Missing Okta configuration. Required: OKTA_CLIENT_ORGURL environment variable")
            raise ValueError("Missing Okta configuration. Set OKTA_CLIENT_ORGURL environment variable.")
        
        # Get concurrent limit for chunked processing  
        # Based on testing: Trial accounts can handle ~3 concurrent, free accounts ~15
        # Your account consistently hits rate limits at 5+ concurrent requests
        # Setting conservative default based on account testing results
        # Use API_CODE_CONCURRENT_LIMIT for fine-tuning generated code behavior
        if settings:
            self.concurrent_limit = settings.OKTA_CONCURRENT_LIMIT
        else:
            self.concurrent_limit = int(os.getenv('OKTA_CONCURRENT_LIMIT', '3'))
        
        # NEW: Check authentication method
        token_method = os.getenv('TOKEN_METHOD', 'API_TOKEN').upper()
        
        if token_method == 'OAUTH2' and OktaOAuth2Manager:
            self._setup_oauth2_auth()
        else:
            self._setup_api_token_auth()
        
        # Set base URL
        self.base_url = f"https://{self.okta_domain}"
        
        # Log authentication method for visibility
        if self.auth_method == 'oauth2':
            self.logger.info(f"Okta Base API client configured for OAuth2 private key JWT authentication (domain: {self.okta_domain})")
        else:
            self.logger.info(f"Okta Base API client configured for API token authentication (domain: {self.okta_domain})")
            
        self.logger.debug(f"Client settings - Timeout: {self.timeout}s, Max Pages: {self.max_pages}, Concurrent Limit: {self.concurrent_limit}")
    
    def _setup_oauth2_auth(self):
        """Setup OAuth2 authentication."""
        try:
            # Check if OktaOAuth2Manager is available
            if OktaOAuth2Manager is None:
                raise ImportError("OktaOAuth2Manager not available - import failed")
            
            self.oauth2_manager = OktaOAuth2Manager(timeout=self.timeout)
            # Note: OAuth2 client will be initialized async in first request
            self.auth_method = 'oauth2'
            
            # For OAuth2, headers will be set dynamically per request
            self.headers = {
                "Accept": "application/json, text/xml, application/xml, */*",
                "Content-Type": "application/json"
            }
            
        except Exception as e:
            self.logger.error(f"OAuth2 setup failed, falling back to API token: {type(e).__name__}: {str(e)}")
            self._setup_api_token_auth()
    
    def _setup_api_token_auth(self):
        """Setup API token authentication (existing logic)."""
        # Get API token
        self.api_token = os.getenv('OKTA_API_TOKEN') or os.getenv('SSWS_API_KEY')
        
        if not self.api_token:
            self.logger.error("Missing Okta configuration. Required: OKTA_API_TOKEN environment variable")
            raise ValueError("Missing Okta configuration. Set OKTA_API_TOKEN environment variable.")
        
        # Setup headers with SSWS token
        self.headers = {
            "Authorization": f"SSWS {self.api_token}",
            "Accept": "application/json, text/xml, application/xml, */*",
            "Content-Type": "application/json"
        }
        
        self.auth_method = 'api_token'
    
    async def _get_auth_headers(self) -> Dict[str, str]:
        """
        Get appropriate authentication headers based on method.
        
        Returns:
            Dict[str, str]: Headers with proper authorization
        """
        if self.auth_method == 'oauth2' and self.oauth2_manager:
            # Initialize OAuth2 client if not done yet
            if not self.oauth2_manager.is_configured():
                success = await self.oauth2_manager.initialize_from_config(self.okta_domain)
                if not success:
                    self.logger.error("Failed to initialize OAuth2 client, falling back to static headers")
                    return self.headers
            
            # Get dynamic OAuth2 headers
            return await self.oauth2_manager.get_auth_headers()
        else:
            # Return static headers for API token method
            return self.headers
    
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

    # ================================================================
    # PROGRESS EMISSION (INITIAL IMPLEMENTATION)
    # ------------------------------------------------
    # Emits lightweight JSON lines to stderr with a fixed sentinel
    # prefix so the orchestrator (modern_execution_manager) can parse
    # and later forward over SSE without mixing with final stdout JSON.
    # This keeps changes minimal and side‑effect free.
    # ================================================================
    _PROGRESS_SENTINEL = "__PROGRESS__"  # stable marker

    def _emit_progress(self, event_type: str, details: Dict[str, Any]):
        """Emit a structured progress event to stderr.

        Args:
            event_type: Short classifier (e.g., 'pagination_start','page','rate_limit','pagination_complete')
            details: Arbitrary JSON-serializable metadata (small size)
        """
        try:
            # Skip chatty api_call_start events - they don't provide meaningful user value
            if event_type == "api_call_start":
                return
            
            payload = {
                "type": event_type,
                "ts": datetime.utcnow().isoformat() + "Z",
                **details
            }
            # Single line with sentinel so parsers can split cheaply
            print(f"{self._PROGRESS_SENTINEL} {json.dumps(payload, separators=(',',':'))}", file=sys.stderr)
            sys.stderr.flush()  # CRITICAL: Force immediate output for real-time streaming
        except Exception:
            # Never let progress emission break core flow
            pass

    # ---------------- Entity progress (for follow-up API calls over previous step IDs) ---------------
    def start_entity_progress(self, label: str, total: int):
        """Emit start event for entity batch processing.

        Args:
            label: Logical label (e.g., 'user_roles', 'user_detail_calls')
            total: Total entities to process
        """
        if total <= 0:
            return
        self._entity_progress_state[label] = {
            'total': total,
            'last_emitted': 0,
            'emitted_events': 0,
            'errors': 0  # Track errors as they accumulate
        }
        # Fixed schema: entity_start with all fields
        self._emit_progress("entity_start", {
            "label": label, 
            "current": 0, 
            "total": total,
            "percent": None,
            "operation_type": "batch",
            "status": None,
            "success": None,
            "errors": 0,
            "wait_seconds": 0,
            "message": None
        })

    def update_entity_progress(self, label: str, processed: int, errors: int = None):
        """Emit throttled progress for entity batch.

        Emits at most ~50 incremental events (configurable via API_PROGRESS_MAX_EVENTS env) plus final.
        
        Args:
            label: Progress label
            processed: Number of items processed so far
            errors: Current error count (if None, keeps existing count)
        """
        state = self._entity_progress_state.get(label)
        if not state:
            return
        
        # Update error count if provided
        if errors is not None:
            state['errors'] = errors
        
        total = state['total']
        processed = min(processed, total)
        max_events = int(os.getenv('API_PROGRESS_MAX_EVENTS', '20'))  # Reduced from 50 to 20
        if total <= 0:
            return
        # Determine minimum increment to emit another event - less frequent updates
        min_step = max(1, total // max_events)
        
        # Only emit at significant milestones or completion
        is_milestone = (processed % max(10, total // 10) == 0) or processed == total
        
        if processed == total or (processed - state['last_emitted'] >= min_step and is_milestone):
            percent = round((processed / total) * 100, 2)
            # Fixed schema: entity_progress with all fields including current errors
            self._emit_progress("entity_progress", {
                "label": label, 
                "current": processed, 
                "total": total, 
                "percent": percent,
                "operation_type": "batch",
                "status": None,
                "success": None,
                "errors": state['errors'],  # Show current error count
                "wait_seconds": 0,
                "message": None
            })
            state['last_emitted'] = processed
            state['emitted_events'] += 1

    def increment_entity_errors(self, label: str, increment: int = 1):
        """Increment error count for entity batch processing.
        
        Args:
            label: Progress label
            increment: Number of errors to add (default 1)
        """
        state = self._entity_progress_state.get(label)
        if state:
            state['errors'] = state.get('errors', 0) + increment

    def complete_entity_progress(self, label: str, success: bool = True, errors: int = None):
        """Emit completion event for entity batch.
        
        Args:
            label: Progress label
            success: Whether the overall operation succeeded
            errors: Final error count (if None, uses accumulated count)
        """
        state = self._entity_progress_state.get(label)
        if not state:
            return
        
        # Use provided errors or accumulated count
        final_errors = errors if errors is not None else state.get('errors', 0)
        
        # If we have errors, consider the operation partially successful
        if final_errors > 0 and success:
            success = True  # Still successful overall, but with some errors
            
        total = state['total']
        # Fixed schema: entity_complete with all fields
        completion_status = "completed" if success else "terminated_with_error"
        if final_errors > 0 and success:
            completion_status = "completed_with_errors"
            
        self._emit_progress("entity_complete", {
            "label": label, 
            "current": total, 
            "total": total, 
            "percent": 100.0 if success else None,
            "operation_type": "batch",
            "status": completion_status,
            "success": success, 
            "errors": final_errors,
            "wait_seconds": 0,
            "message": f"Completed with {final_errors} errors" if final_errors > 0 else "Completed successfully"
        })
        # Cleanup
        try:
            del self._entity_progress_state[label]
        except KeyError:
            pass
    
    async def make_request(self, 
                          endpoint: str,
                          method: str = "GET", 
                          params: Optional[Dict] = None,
                          body: Optional[Dict] = None,
                          max_results: Optional[int] = None,
                          entity_label: Optional[str] = None) -> Dict[str, Any]:
        """
        Make an API request with automatic pagination detection and rate limit optimization.
        
        Args:
            endpoint: API endpoint (e.g., "/api/v1/logs", "/api/v1/users")
            method: HTTP method (GET, POST, PUT, DELETE)
            params: Query parameters
            body: Request body for POST/PUT requests
            max_results: Maximum total results to return (stops pagination early)
            entity_label: If provided, errors will be automatically tracked for this entity batch
            
        Returns:
            Dict with status and data/error
        """
        # Emit structured progress events - only for max_results limit
        if max_results:
            self._emit_progress("api_call_limit", {"max_results": max_results})
        # self.logger.debug(f"API: {method} {endpoint}")
        # self.logger.debug(f"Making {method} request to endpoint: {endpoint}")
        if params:
            self.logger.debug(f"Request parameters: {params}")
        if max_results:
            self.logger.debug(f"Max results limit: {max_results}")
        
        try:
            # Optimize parameters for better rate limit efficiency
            if method.upper() == "GET":
                params = self._optimize_params(endpoint, params)
                result = await self._handle_get_request(endpoint, params, max_results)
            else:
                result = await self._handle_single_request(endpoint, method, params, body)
            
            # NEW: Automatic error tracking for entity batch operations
            if entity_label and result.get("status") == "error":
                self.increment_entity_errors(entity_label, 1)
                self.logger.debug(f"Auto-tracked error for entity batch '{entity_label}': {result.get('error', 'Unknown error')}")
            
            return result
                
        except Exception as e:
            self.logger.error(f"API request failed for {endpoint}: {str(e)}")
            sys.stderr.flush()  # Flush error logs immediately
            error_result = {
                "status": "error",
                "error": f"API request failed: {str(e)}",
                "error_code": "REQUEST_FAILED"
            }
            
            # NEW: Automatic error tracking for exceptions too
            if entity_label:
                self.increment_entity_errors(entity_label, 1)
                self.logger.debug(f"Auto-tracked exception for entity batch '{entity_label}': {str(e)}")
            
            return error_result
    
    async def _handle_get_request(self, endpoint: str, params: Optional[Dict] = None, max_results: Optional[int] = None) -> Dict[str, Any]:
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
        # Add first page data
        first_data = first_result["data"]
        all_data = []
        if isinstance(first_data, list):
            all_data.extend(first_data)
        else:
            all_data.append(first_data)
        
        # Start entity progress for pagination with special handling for unknown totals
        # Use a descriptive label based on endpoint
        endpoint_label = endpoint.strip('/').replace('/api/v1/', '').replace('/', '_')
        pagination_label = f"paginate_{endpoint_label}"
        
        # For pagination, emit entity_start event with discovery mode - fixed schema
        self._emit_progress("entity_start", {
            "label": pagination_label, 
            "current": len(all_data),  
            "total": 0,  # Unknown total for pagination discovery
            "percent": None,
            "operation_type": "discovery",
            "status": None,
            "success": None,
            "errors": 0,
            "wait_seconds": 0,
            "message": None
        })
        
        # Remove old pagination_start event - replaced by entity_start
        self.logger.info(f"Paginating {endpoint} - collecting all pages...")
        
        page_count = 1
        current_link = link_header
        
        # Emit entity progress for first page with item count - fixed schema
        self._emit_progress("entity_progress", {
            "label": pagination_label, 
            "current": len(all_data),
            "total": 0,  # Unknown total for discovery
            "percent": None,
            "operation_type": "discovery",
            "status": None,
            "success": None,
            "errors": 0,
            "wait_seconds": 0,
            "message": None
        })
        
        self.logger.debug(f"Page 1: Retrieved {len(first_data) if isinstance(first_data, list) else 1} items")
        
        # Check if max_results is reached after first page
        if max_results and len(all_data) >= max_results:
            # Remove old max_results_reached event - completion info is in entity_complete
            self.logger.info(f"Max results reached after page 1: returning {max_results} items")
            # Emit entity completion for early exit due to max_results - fixed schema
            self._emit_progress("entity_complete", {
                "label": pagination_label, 
                "current": max_results,
                "total": max_results,  # Now we know the effective total
                "percent": 100.0,
                "operation_type": "discovery",
                "status": "completed_max_reached",
                "success": True, 
                "errors": 0,
                "wait_seconds": 0,
                "message": f"Completed with max results limit: {max_results} items"
            })
            return {
                "status": "success",
                "data": all_data[:max_results],
                "pages": page_count,
                "total_items": max_results,
                "limited_by_max_results": True
            }
        
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
                sys.stderr.flush()  # Flush error logs immediately
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
            
            # Emit entity progress with increasing item count (every page) - fixed schema
            self._emit_progress("entity_progress", {
                "label": pagination_label, 
                "current": len(all_data),
                "total": 0,  # Still unknown total for discovery
                "percent": None,
                "operation_type": "discovery",
                "status": None,
                "success": None,
                "errors": 0,
                "wait_seconds": 0,
                "message": None
            })
            
            # Remove old page and max_results_reached events - replaced by entity_progress
            
            # Check if max_results is reached
            if max_results and len(all_data) >= max_results:
                # Remove old max_results_reached event - completion info is in entity_complete
                self.logger.info(f"Max results reached after page {page_count}: returning {max_results} items")
                # Emit entity completion for early exit due to max_results - fixed schema
                self._emit_progress("entity_complete", {
                    "label": pagination_label, 
                    "current": max_results,
                    "total": max_results,  # Now we know the effective total
                    "percent": 100.0,
                    "operation_type": "discovery",
                    "status": "completed_max_reached",
                    "success": True, 
                    "errors": 0,
                    "wait_seconds": 0,
                    "message": f"Completed with max results limit: {max_results} items"
                })
                return {
                    "status": "success",
                    "data": all_data[:max_results],
                    "pages": page_count,
                    "total_items": max_results,
                    "limited_by_max_results": True
                }
            
            # Get next link for next iteration
            current_link = page_result.get("link_header", "")
            
            # Small delay between requests
            await asyncio.sleep(0.2)

        # Remove old pagination_complete event - replaced by entity_complete
        self.logger.info(f"Pagination complete for {endpoint}: {len(all_data)} total items across {page_count} pages")
        
        # Emit entity completion with final item count - fixed schema
        self._emit_progress("entity_complete", {
            "label": pagination_label, 
            "current": len(all_data),
            "total": len(all_data),  # Now we know the final total
            "percent": 100.0,
            "operation_type": "discovery",
            "status": "completed",
            "success": True, 
            "errors": 0,
            "wait_seconds": 0,
            "message": f"Pagination completed: {len(all_data)} items across {page_count} pages"
        })
        
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
        
        # Get appropriate auth headers dynamically
        request_headers = await self._get_auth_headers()
        
        # Adjust headers for XML endpoints (SAML metadata and Identity Provider endpoints)
        xml_endpoints = [
            '/sso/saml/metadata',      # Application SAML metadata
            '/metadata.xml',           # Identity Provider SAML metadata  
            '/sso/saml2/'             # SAML assertion consumption service
        ]
        
        if any(xml_pattern in endpoint for xml_pattern in xml_endpoints):
            request_headers = request_headers.copy()
            request_headers["Accept"] = "application/xml, text/xml"
            request_headers.pop("Content-Type", None)  # Remove Content-Type for GET requests
            self.logger.debug(f"Using XML headers for SAML endpoint: {endpoint}")
        
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
                        headers=request_headers,
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
                                retry_after = min(int(response.headers.get('Retry-After', '15')), 30)
                                self.logger.warning(f"Concurrent rate limit exceeded on {endpoint}. Waiting {retry_after} seconds for retry {retry_count + 1}/{max_retries}")
                            else:
                                # Org-wide rate limit - use Retry-After header
                                retry_after = int(response.headers.get('Retry-After', '60'))
                                self.logger.warning(f"Org-wide rate limit exceeded on {endpoint}. Waiting {retry_after} seconds for retry {retry_count + 1}/{max_retries}")
                                self.logger.info(f"Rate limit details: {rate_limit_remaining}/{rate_limit_limit} remaining, resets at epoch {rate_limit_reset}")
                            
                            if retry_count < max_retries - 1:  # Don't sleep on last retry
                                # Use Okta's exact Retry-After header (no multiplier needed)
                                # Okta's rate limits reset at specific times, so we trust their timing
                                actual_wait = min(retry_after, 300)  # Max 5 min wait for safety
                                
                                # Add jitter to prevent retry storms for concurrent rate limits
                                # Concurrent limits don't reset by time - they reset when requests complete
                                # Stagger retries to avoid all requests hitting the same concurrent slots
                                if is_concurrent:
                                    jitter = random.uniform(0, 3)  # 0-3 second random delay for concurrent limits
                                    actual_wait += jitter
                                    self.logger.info(f"Concurrent rate limit: Waiting {actual_wait:.1f}s (base: {retry_after}s + jitter: {jitter:.1f}s)")
                                else:
                                    self.logger.info(f"Org-wide rate limit: Waiting {actual_wait} seconds as specified by Okta Retry-After header")
                                
                                # Standardized rate_limit_wait event - fixed schema
                                self._emit_progress("rate_limit_wait", {
                                    "label": f"rate_limit_{endpoint.strip('/').replace('/api/v1/', '').replace('/', '_')}", 
                                    "current": 0,
                                    "total": 0,
                                    "percent": None,
                                    "operation_type": "rate_limit",
                                    "status": "waiting",
                                    "success": None,
                                    "errors": 0,
                                    "wait_seconds": round(actual_wait, 2),
                                    "message": f"Waiting for {'concurrent' if is_concurrent else 'org-wide'} rate limit..."
                                })
                                await asyncio.sleep(actual_wait)
                                retry_count += 1
                                continue
                        
                        # Process response with comprehensive error handling
                        result = await self._process_response(response)
                        
                        # Add Link header and rate limit info for pagination detection
                        if result["status"] == "success":
                            # Get ALL Link headers (Okta sends multiple Link headers)
                            link_headers = response.headers.getall('Link', [])
                            result["link_header"] = ', '.join(link_headers)
                            
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
                    sys.stderr.flush()  # Flush error logs immediately
                    return {
                        "status": "error",
                        "error": f"Request timeout after {self.timeout} seconds",
                        "error_code": "TIMEOUT"
                    }
                except aiohttp.ClientError as e:
                    self.logger.error(f"Network error for {endpoint}: {str(e)}")
                    sys.stderr.flush()  # Flush error logs immediately
                    return {
                        "status": "error", 
                        "error": f"Network error: {str(e)}",
                        "error_code": "NETWORK_ERROR"
                    }
                except Exception as e:
                    self.logger.error(f"Unexpected error for {endpoint}: {str(e)}")
                    sys.stderr.flush()  # Flush error logs immediately
                    return {
                        "status": "error",
                        "error": f"Unexpected error: {str(e)}",
                        "error_code": "UNEXPECTED_ERROR"
                    }
            
            # All retries exhausted
            self.logger.error(f"All {max_retries} retries exhausted for {endpoint} due to rate limiting")
            sys.stderr.flush()  # Flush error logs immediately
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
            if self.auth_method == 'oauth2':
                error_msg = "Authentication failed: Invalid or expired OAuth2 token"
            else:
                error_msg = "Authentication failed: Invalid or expired API token"
            
            return {
                "status": "error",
                "error": error_msg,
                "error_code": "E0000011"
            }
        
        if response.status == 403:
            if self.auth_method == 'oauth2':
                error_msg = "Access forbidden: Insufficient OAuth2 scopes or permissions"
            else:
                error_msg = "Access forbidden: Insufficient permissions for this operation"
                
            return {
                "status": "error", 
                "error": error_msg,
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


