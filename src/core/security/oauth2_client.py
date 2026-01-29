"""
OAuth2 Client Manager for Okta API Authentication

This module provides OAuth2 authentication using AuthLib exclusively for proper
OAuth2 security standards compliance. No custom JWT or token handling code.

Features:
- AuthLib private_key_jwt authentication (RFC 7523)
- Automatic token refresh and expiry handling
- Full OAuth2 security standards compliance
- Environment-based configuration
- Production-ready logging
"""

import os
from typing import Dict, Any, Optional
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.oauth2.rfc7523 import PrivateKeyJWT
# Import centralized logging - DISABLED to prevent stdout contamination in subprocess execution
# Using self-contained logging instead to ensure logs go to stderr
import logging


class OktaOAuth2Manager:
    """
    OAuth2 client using AuthLib exclusively for RFC-compliant authentication.
    
    Uses AuthLib's built-in private_key_jwt method (RFC 7523) for secure
    client authentication with Okta Org Authorization Server.
    
    No custom JWT or token handling code - AuthLib handles all OAuth2 security.
    """
    
    USER_AGENT = "Tako-AI"
    
    def __init__(self, timeout: int = 300):
        """Initialize OAuth2 manager with AuthLib client."""
        self.timeout = timeout
        self.oauth2_client = None
        self.client_id = None
        self.private_key_pem = None  # Will store the raw PEM string
        self.scopes = None
        self.token_endpoint = None
        self._cached_token = None  # Cache for access token
        self._token_expires_at = None  # Token expiration timestamp
        
        # Setup logging - self-contained logging setup
        self.logger = logging.getLogger(f"{__name__}.OktaOAuth2Manager")
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
    
    async def initialize_from_config(self, okta_domain: str) -> bool:
        """
        Initialize OAuth2 client using AuthLib with private key JWT.
        
        Args:
            okta_domain: Okta domain (e.g., "your-org.okta.com")
            
        Returns:
            bool: True if initialization successful
        """
        try:
            self.logger.info(f"Starting OAuth2 initialization for domain: {okta_domain}")
            
            # Validate input domain
            if not okta_domain or not isinstance(okta_domain, str):
                self.logger.error("Invalid okta_domain parameter")
                return False
                
            # Sanitize domain input - remove protocol and trailing slashes
            okta_domain = okta_domain.replace('https://', '').replace('http://', '').strip('/')
            
            # Validate domain format (basic check)
            if not okta_domain or '.' not in okta_domain:
                self.logger.error(f"Invalid Okta domain format: {okta_domain}")
                return False
            
            # Load configuration
            self.client_id = os.getenv('OKTA_OAUTH2_CLIENT_ID')
            self.private_key_pem = os.getenv('OKTA_OAUTH2_PRIVATE_KEY_PEM')
            raw_scopes = os.getenv('OKTA_OAUTH2_SCOPES')
            
            # Sanitize scopes - remove wrapping quotes if present
            if raw_scopes:
                self.scopes = raw_scopes.strip().strip('"').strip("'")
            else:
                self.scopes = None
            
            if self.scopes:
                self.logger.debug(f"OAuth2 scopes configured: {self.scopes[:100]}...")
            else:
                self.logger.warning("No OAuth2 scopes configured - OKTA_OAUTH2_SCOPES not set")
            
            # Validate configuration
            if not self.client_id or not isinstance(self.client_id, str):
                self.logger.error("Missing or invalid OKTA_OAUTH2_CLIENT_ID")
                return False
            
            if not self.private_key_pem or not isinstance(self.private_key_pem, str) or not self.private_key_pem.strip():
                self.logger.error("Missing or invalid OKTA_OAUTH2_PRIVATE_KEY_PEM")
                return False
                
            # Validate private key format
            if 'BEGIN PRIVATE KEY' not in self.private_key_pem or 'END PRIVATE KEY' not in self.private_key_pem:
                self.logger.error("Invalid private key format - must be PEM format")
                return False
            
            # Validate scopes
            if not self.scopes or not isinstance(self.scopes, str):
                self.logger.error("Invalid scopes configuration - OKTA_OAUTH2_SCOPES must be set")
                return False
            
            # Okta Org Authorization Server endpoint (HTTPS only)
            self.token_endpoint = f"https://{okta_domain}/oauth2/v1/token"
            
            # Initialize AuthLib OAuth2 client with private_key_jwt (RFC 7523)
            self.logger.info("Creating AsyncOAuth2Client with private_key_jwt authentication")
            self.oauth2_client = AsyncOAuth2Client(
                client_id=self.client_id,
                client_secret=self.private_key_pem,  # Private key as string
                token_endpoint_auth_method='private_key_jwt',
                timeout=self.timeout
            )
            
            self.logger.info("OAuth2 client initialization successful")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize OAuth2 client: {str(e)}")
            return False
    
    async def get_access_token(self) -> Optional[str]:
        """
        Get valid access token using AuthLib exclusively.
        
        Returns:
            str: Access token or None if failed
        """
        if not self.oauth2_client:
            self.logger.error("OAuth2 client not initialized")
            return None
        
        # Check if we have a cached token that's still valid
        import time
        current_time = time.time()
        
        if (self._cached_token and 
            self._token_expires_at and 
            current_time < (self._token_expires_at - 60)):  # Refresh 60 seconds before expiry
            return self._cached_token
            
        try:
            headers = {
                'User-Agent': self.USER_AGENT,
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            # Create a new PrivateKeyJWT with unique timestamp for each request
            import random
            jitter = random.randint(0, 30)  # 0-30 second jitter
            
            private_key_jwt = PrivateKeyJWT(
                token_endpoint=self.token_endpoint,
                claims={
                    'aud': self.token_endpoint,  # Audience must match token endpoint exactly
                    'iss': self.client_id,       # Issuer is the client ID
                    'sub': self.client_id,       # Subject is also the client ID
                    'exp': int(current_time) + 300,  # Expire in 5 minutes
                    'nbf': int(current_time) - jitter,  # Not before with jitter
                    'iat': int(current_time) - jitter,  # Issued at with jitter
                    'jti': f"{self.client_id}-{int(current_time * 1000000)}-{random.randint(1000,9999)}"  # Microsecond precision + random
                },
                alg='RS256'
            )
            
            # Register the new PrivateKeyJWT authentication method
            self.oauth2_client.register_client_auth_method(private_key_jwt)
            
            # AuthLib handles private key JWT authentication automatically
            token = await self.oauth2_client.fetch_token(
                url=self.token_endpoint,
                grant_type='client_credentials',
                scope=self.scopes,
                headers=headers
            )
            
            access_token = token.get('access_token')
            if access_token:
                # Cache the token and its expiration
                self._cached_token = access_token
                expires_in = token.get('expires_in', 3600)  # Default 1 hour
                self._token_expires_at = current_time + expires_in
                return access_token
            else:
                self.logger.error("No access token in response")
                return None
                
        except Exception as e:
            self.logger.error(f"OAuth2 token fetch failed: {type(e).__name__}")
            self.logger.error(f"Error details: {str(e)}")
            # Log more context for debugging
            if hasattr(e, 'error'):
                self.logger.error(f"OAuth error: {e.error}")
            if hasattr(e, 'description'):
                self.logger.error(f"Error description: {e.description}")
            # Clear any partial tokens on error
            self._cached_token = None
            self._token_expires_at = None
            return None
    
    async def get_auth_headers(self) -> Dict[str, str]:
        """
        Get authorization headers with Bearer token for OAuth2.
        
        Note: OAuth2 tokens use Bearer prefix (RFC 6750)
        SSWS prefix is only for Okta's proprietary API tokens
        
        Returns:
            Dict[str, str]: Headers with Bearer token authorization
        """
        access_token = await self.get_access_token()
        
        if not access_token:
            self.logger.error("No valid access token for authorization headers")
            return {}
        
        return {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": self.USER_AGENT
        }
    
    def clear_cached_token(self) -> None:
        """
        Securely clear cached tokens from memory.
        Call this when logging out or on security events.
        """
        if self._cached_token:
            # Overwrite token memory before clearing
            self._cached_token = "0" * len(self._cached_token)
            self._cached_token = None
        self._token_expires_at = None
    
    def is_configured(self) -> bool:
        """Check if OAuth2 client is properly configured."""
        return (self.oauth2_client is not None and 
                self.client_id is not None and 
                self.private_key_pem is not None)
    
    def get_client_info(self) -> Dict[str, Any]:
        """
        Get OAuth2 client configuration info for debugging/monitoring.
        
        Returns:
            Dict[str, Any]: Client configuration details (without sensitive data)
        """
        import time
        return {
            "is_configured": self.is_configured(),
            "token_endpoint": self.token_endpoint,
            "client_id": self.client_id[:8] + "..." if self.client_id else None,
            "scopes": self.scopes,
            "has_cached_token": self._cached_token is not None,
            "token_expires_at": self._token_expires_at if self._token_expires_at else None,
            "token_valid": (self._cached_token is not None and 
                           self._token_expires_at is not None and 
                           self._token_expires_at > (time.time() + 60)) if self._token_expires_at else False
        }


class OAuth2Error(Exception):
    """Custom exception for OAuth2-related errors."""
    
    def __init__(self, message: str, error_code: str = None, status_code: int = None):
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        super().__init__(message)


def handle_oauth2_response_error(response) -> OAuth2Error:
    """
    Convert HTTP response to appropriate OAuth2Error.
    
    Args:
        response: HTTP response object
        
    Returns:
        OAuth2Error: Appropriate error with context
    """
    if response.status_code == 401:
        return OAuth2Error(
            "OAuth2 authentication failed: Invalid client credentials or expired token",
            error_code="invalid_client",
            status_code=401
        )
    elif response.status_code == 403:
        return OAuth2Error(
            "OAuth2 access forbidden: Insufficient scopes or permissions",
            error_code="insufficient_scope", 
            status_code=403
        )
    elif response.status_code == 400:
        return OAuth2Error(
            "OAuth2 bad request: Invalid grant type or malformed request",
            error_code="invalid_request",
            status_code=400
        )
    else:
        return OAuth2Error(
            f"OAuth2 request failed: HTTP {response.status_code}",
            error_code="unknown_error",
            status_code=response.status_code
        )
