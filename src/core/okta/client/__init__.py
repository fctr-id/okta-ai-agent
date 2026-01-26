"""
Okta Client Module

Exports:
- OktaClientWrapper: Async wrapper for Okta SDK (used by sync engine)
- OktaAPIClient: Base API client for direct HTTP calls (used by agents)
"""

from .client import OktaClientWrapper
from .base_okta_api_client import OktaAPIClient

# Alias for convenience
OktaClient = OktaAPIClient

__all__ = ['OktaClientWrapper', 'OktaAPIClient', 'OktaClient']
