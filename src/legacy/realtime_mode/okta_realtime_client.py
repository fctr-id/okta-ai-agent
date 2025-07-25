import asyncio
import uuid
from dataclasses import dataclass
import logging

from okta.client import Client as OktaClient
from config.settings import settings

logger = logging.getLogger(__name__)

class OktaRealtimeClient:
    """Wrapper around the Okta SDK client for real-time API calls."""
    
    def __init__(self, client: OktaClient):
        """Initialize with an authenticated Okta client."""
        self.client = client
        self._rate_limits = {}  # Track rate limit info per endpoint

    def update_rate_limit(self, endpoint: str, reset_seconds: int):
        """Update rate limit information for an endpoint."""
        self._rate_limits[endpoint] = {
            'reset_seconds': reset_seconds,
            'updated_at': asyncio.get_event_loop().time()
        }

    def is_rate_limited(self, endpoint: str) -> bool:
        """Check if an endpoint is currently rate limited."""
        if endpoint not in self._rate_limits:
            return False

        limit_info = self._rate_limits[endpoint]
        current_time = asyncio.get_event_loop().time()
        elapsed = current_time - limit_info['updated_at']
        
        # If reset time has passed, remove the rate limit entry
        if elapsed >= limit_info['reset_seconds']:
            del self._rate_limits[endpoint]
            return False
            
        return True

    def get_reset_seconds(self, endpoint: str) -> int:
        """Get seconds until rate limit reset for endpoint."""
        if endpoint not in self._rate_limits:
            return 0
            
        limit_info = self._rate_limits[endpoint]
        current_time = asyncio.get_event_loop().time()
        elapsed = current_time - limit_info['updated_at']
        remaining = max(0, limit_info['reset_seconds'] - elapsed)
        
        return int(remaining)

@dataclass
class OktaRealtimeDeps:
    """Dependencies for Okta real-time API operations."""
    domain: str
    api_token: str
    query_id: str = None
    client: OktaClient = None
    
    def __post_init__(self):
        """Set defaults for missing values and initialize client if needed."""
        if self.query_id is None:
            self.query_id = str(uuid.uuid4())
            
        if self.client is None:
            config = {
                'orgUrl': self.domain,
                'token': self.api_token
            }
            self.client = OktaClient(config)

def get_okta_client() -> OktaClient:
    """Get an authenticated Okta client."""
    # Check if the required settings are present
    if not settings.OKTA_CLIENT_ORGURL or not settings.OKTA_API_TOKEN:
        raise ValueError(
            "Missing required settings. "
            "Please ensure OKTA_DOMAIN and OKTA_API_TOKEN "
            "are set in your .env file."
        )
    
    config = {
        'orgUrl': settings.OKTA_CLIENT_ORGURL,
        'token': settings.OKTA_API_TOKEN
    }
    return OktaClient(config)

def get_okta_realtime_deps(query_id: str = None) -> OktaRealtimeDeps:
    """Create a fully initialized OktaRealtimeDeps object."""
    return OktaRealtimeDeps(
        domain=settings.OKTA_CLIENT_ORGURL,
        api_token=settings.OKTA_API_TOKEN,
        query_id=query_id or str(uuid.uuid4())
    )