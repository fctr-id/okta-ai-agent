"""
Centralized security configuration for the Okta AI Agent.

This module defines all security controls, restrictions, and policies
used throughout the application to enforce secure operations.
"""

from typing import List, Dict, Any, Set, Optional
import re
import ast
from src.utils.logging import get_logger
import os
from urllib.parse import urlparse

# Configure logging
logger = get_logger(__name__)

# ------------------------------------------------------------------------
# Code Execution Security
# ------------------------------------------------------------------------

# Allowed Okta SDK methods 
ALLOWED_SDK_METHODS: Set[str] = {
    # User operations from user_tools.py
    'get_user',                 # Used in get_user_details and for resolving email to ID
    'list_users',               # Used in search_users
    'list_factors',             # Used in list_user_factors
    'list_user_groups',         # Used with paginate_results
    
    # Group operations from group_tools.py
    'list_groups',              # Used in list_groups
    'list_group_users',         # Used with paginate_results in get_group_members
    'list_assigned_applications_for_group',  # Used in list_group_applications
    
    # Application operations from application_tools.py
    'get_application',          
    'list_applications',        
    'list_application_users',   
    'list_application_group_assignments',
    
    # Log/Event operations from logevents_tools.py
    'get_logs','get_event_logs'                 # Used in get_event_logs
    
    # Datetime utility operations from datetime_tools.py
    'get_current_time',         # No direct client call but used as a tool
    'parse_relative_time',      # No direct client call but used as a tool
    'format_date_for_query',    # No direct client call but used as a tool
    
        # Policy operations from policy_tools.py
    'list_policy_rules',        # Used in list_policy_rules
    'get_network_zone',        # Used in get_network_zones
    'list_network_zones',      # Used in list_network_zones
    
    # Additional method needed for direct API calls
    'make_async_request',       # Helper for direct API calls
    
    # For 'paginate_results' function used in many tools
    'paginate_results',
    
    # Request executor methods
    'get_request_executor',
    'create_request',
    'execute',
    'get_body',
    'get_type'    
}


# Allowed utility methods 
ALLOWED_UTILITY_METHODS: Set[str] = {
    # Data conversion methods
    'to_dict', 'as_dict', 'dict', 'json',
    
    # Common list operations
    'append', 'extend', 'insert', 'add', 'remove', 'pop', 'clear', 
    'index', 'count', 'sort', 'reverse',
    
    # String methods
    'join', 'split', 'strip', 'lstrip', 'rstrip', 'upper', 'lower',
    'capitalize', 'title', 'startswith', 'endswith', 'replace', 'format',
    
    # Pagination methods
    'next', 'has_next', 'has_prev', 'prev_page', 'next_page', 'total_pages', 'paginate_results', 'handle_single_entity_request'
    
    # General methods
    'get', 'is_okta_url_allowed',
    
    'items', 'keys', 'values', 'enumerate', 'zip',  # Dictionary/list operations
    'format', 'replace', 'startswith', 'endswith',  # String processing
    'sorted', 'filter', 'map', 'any', 'all',        # Data processing
    'sum', 'min', 'max', 'len', 'round',            # Math and sizing
    'flatten_dict', 'combine_results',              # Results processing helpers
}

# Allowed modules
ALLOWED_MODULES: Set[str] = {
    'okta', 'asyncio', 'typing', 'datetime', 'json', 'time', 'src.utils.pagination_limits', 'aiohttp'
}

# Dangerous patterns to check for in code
DANGEROUS_PATTERNS: List[tuple] = [
    (r'os\s*\.\s*system', "System command execution"),
    (r'subprocess', "Subprocess execution"),
    (r'exec\s*\(', "Dynamic code execution"),
    (r'eval\s*\(', "Dynamic code evaluation"),
    (r'__import__\s*\(', "Dynamic module import"),
    (r'open\s*\(', "File operations"),
    (r'input\s*\(', "User input")
]

# ------------------------------------------------------------------------
# Code Validation Functions
# ------------------------------------------------------------------------

def is_code_safe(code: str, okta_domain: str = None) -> bool:
    """
    Validate if the provided code adheres to security policies.
    
    Args:
        code: The code string to validate
        okta_domain: Optional Okta domain to check URLs against
        
    Returns:
        True if code is safe, False otherwise
    """
    try:
        # Parse the code into an AST
        tree = ast.parse(code)
    except SyntaxError as e:
        logger.warning(f"Code validation failed: syntax error: {e}")
        return False
    
    # Check for imports
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module_name = node.names[0].name.split('.')[0] if isinstance(node, ast.Import) else node.module.split('.')[0]
            if module_name not in ALLOWED_MODULES:
                logger.warning(f"Code validation failed: unauthorized module import: {module_name}")
                return False
                
    # Check for method calls
    all_allowed_methods = ALLOWED_SDK_METHODS.union(ALLOWED_UTILITY_METHODS)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            method_name = node.func.attr
            
            # Special case for dictionary methods like .get()
            if method_name in ['get', 'items', 'keys', 'values']:
                continue
                
            if method_name not in all_allowed_methods:
                logger.warning(f"Code validation failed: unauthorized method call: {method_name}")
                return False
    
    # Check for URL restrictions (if domain provided)
    if okta_domain:
        url_pattern = re.compile(r'https?://([^/]+)')
        urls = url_pattern.findall(code)
        for url in urls:
            if okta_domain not in url:
                logger.warning(f"Code validation failed: unauthorized domain in URL: {url}")
                return False

    # Look for potentially dangerous patterns
    for pattern, reason in DANGEROUS_PATTERNS:
        if re.search(pattern, code):
            logger.warning(f"Code validation failed: {reason}")
            return False
    
    return True

def validate_api_operation(entity_type: str, operation: str) -> bool:
    """
    Check if an API operation is allowed.
    
    Args:
        entity_type: Type of entity (user, group, etc.)
        operation: Operation to perform
        
    Returns:
        True if operation is allowed, False otherwise
    """
    # API operations allowed for the AI agent
    ALLOWED_API_OPERATIONS: Dict[str, List[str]] = {
        "user": ["list", "get", "search", "get_groups"], 
        "group": ["list", "get", "get_members", "get_applications"],
        "application": ["list", "get"]
    }
    
    if entity_type not in ALLOWED_API_OPERATIONS:
        logger.warning(f"Security validation failed: entity type '{entity_type}' not allowed")
        return False
        
    allowed = operation in ALLOWED_API_OPERATIONS[entity_type]
    if not allowed:
        logger.warning(f"Security validation failed: operation '{operation}' not allowed on '{entity_type}'")
        
    return allowed

def sanitize_response(data: Any) -> Any:
    """
    Remove sensitive fields from response data.
    
    Args:
        data: The response data to sanitize
        
    Returns:
        Sanitized data
    """
    # Implementation would depend on data structure
    # This is a placeholder for the actual implementation
    return data


def is_okta_url_allowed(url: str) -> bool:
    """
    Validates if a URL is allowed for direct API calls by checking
    if it belongs to the configured Okta organization domain.
    
    Args:
        url: The URL to validate
        
    Returns:
        True if URL is allowed (matches Okta org URL), False otherwise
    """
    try:
        # Get the Okta organization URL from environment
        okta_org_url = os.getenv('OKTA_CLIENT_ORGURL')
        if not okta_org_url:
            logger.error("OKTA_CLIENT_ORGURL environment variable not set")
            return False
        
        # Normalize URLs by removing trailing slashes
        if okta_org_url.endswith('/'):
            okta_org_url = okta_org_url[:-1]
            
        # Parse the URLs to compare domains and paths
        parsed_okta_url = urlparse(okta_org_url)
        parsed_request_url = urlparse(url)
        
        # Extract the base domain for comparison
        okta_domain = parsed_okta_url.netloc
        request_domain = parsed_request_url.netloc
        
        # Check if domains match
        if request_domain != okta_domain:
            logger.warning(f"URL validation failed: unauthorized domain: {request_domain}")
            return False
            
        # Check if request URL starts with Okta org URL
        if not url.startswith(okta_org_url):
            logger.warning(f"URL validation failed: URL {url} does not belong to Okta org URL {okta_org_url}")
            return False
            
        logger.debug(f"URL validation passed: {url}")
        return True
        
    except Exception as e:
        logger.error(f"Error validating URL: {str(e)}")
        return False