"""
Core Security Module

Provides comprehensive security validation for the Okta AI Agent system.
Implements simple but effective security controls:

1. Method Whitelisting - Validates Python code and operations
2. Network Security - Restricts HTTP traffic to authorized domains
3. Polars Security - Controls data processing operations

Usage:
    from src.core.security import validate_generated_code, validate_url, validate_polars_operation
    
    # Validate generated code
    result = validate_generated_code(python_code)
    if not result.is_valid:
        logger.error(f"Security violation: {result.violations}")
    
    # Validate network request
    result = validate_url(request_url)
    if not result.is_allowed:
        logger.error(f"Network blocked: {result.blocked_reason}")
    
    # Validate Polars operation
    result = validate_polars_operation("head")
    if not result.is_allowed:
        logger.error(f"Polars operation blocked: {result.violations}")
"""

# Import main validation functions from consolidated security_config
from ...utils.security_config import (
    validate_generated_code,
    validate_http_method,
    validate_api_endpoint,
    SecurityValidationResult,
    EnhancedSecurityValidator
)

from .network_security import (
    validate_url,
    validate_request,
    get_security_headers,
    NetworkSecurityValidator,
    NetworkSecurityResult
)

from .polars_security import (
    validate_polars_operation,
    validate_polars_chain,
    get_safe_polars_operations,
    PolarsSecurityValidator,
    PolarsSecurityResult
)

__all__ = [
    # Method whitelisting (consolidated into security_config)
    'validate_generated_code',
    'validate_http_method', 
    'validate_api_endpoint',
    'EnhancedSecurityValidator',
    'SecurityValidationResult',
    
    # Network security
    'validate_url',
    'validate_request',
    'get_security_headers',
    'NetworkSecurityValidator',
    'NetworkSecurityResult',
    
    # Polars security
    'validate_polars_operation',
    'validate_polars_chain',
    'get_safe_polars_operations',
    'PolarsSecurityValidator',
    'PolarsSecurityResult',
]

# Version info
__version__ = "1.0.0"
__description__ = "Security validation module for Okta AI Agent"
