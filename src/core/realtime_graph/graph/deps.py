from dataclasses import dataclass
from typing import Any, Optional
import logging

@dataclass
class OktaDeps:
    """Dependencies for Okta graph operations."""
    client: Any  # OktaClient
    domain: str
    query_id: str = "unknown"
    logger: Any = None  # Logger
    
    def __post_init__(self):
        """Initialize the logger if not provided."""
        if self.logger is None:
            self.logger = logging.getLogger("okta_graph")


def get_okta_graph_deps(query_id: str = "unknown", client: Optional[Any] = None) -> OktaDeps:
    """
    Create dependencies for the Okta graph operations.
    
    Args:
        query_id: Unique identifier for this query/session
        client: Optional Okta client instance (will create if not provided)
        
    Returns:
        OktaDeps instance
    """
    from src.config.settings import settings
    from okta.client import Client as OktaClient
    
    # Create client if not provided
    if client is None:
        # Create Okta client configuration
        config = {
            'orgUrl': settings.OKTA_CLIENT_ORGURL,
            'token': settings.OKTA_API_TOKEN,
            'requestTimeout': 30,
            'rateLimit': {
                'maxRetries': 2,
                'maxRequestsPerSecond': 5
            }
        }
        
        # Create client
        client = OktaClient(config)
    
    # Create dependencies
    return OktaDeps(
        client=client,
        domain=settings.OKTA_CLIENT_ORGURL,
        query_id=query_id
    )