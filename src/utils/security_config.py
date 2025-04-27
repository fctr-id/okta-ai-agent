"""
Centralized security configuration for the Okta AI Agent.

This module defines all security controls, restrictions, and policies
used throughout the application to enforce secure operations.
"""

from typing import List, Dict, Any, Set, Optional
import re
import ast
from src.utils.logging import get_logger

# Configure logging
logger = get_logger(__name__)

# ------------------------------------------------------------------------
# Code Execution Security
# ------------------------------------------------------------------------

# Allowed Okta SDK methods 
ALLOWED_SDK_METHODS: Set[str] = {
    # User operations
    'get_user', 'get_users', 'list_users',
    
    # Group operations
    'get_group', 'list_groups', 'list_group_users',
    'list_assigned_applications_for_group',
    
    # Application operations
    'get_application', 'list_applications',
    'list_application_assignments',
    
    # Datetime utility operations
    'get_current_time', 'parse_relative_time', 'format_date_for_query',
    
    #application operations
    'list_applications ', 'get_application_details', 'list_application_users', 'list_application_groups',
    
    # Other operations
    'get_event_logs', 'get_logs','list_user_groups',
    'list_factors', 'list_supported_factors',
    'get_user_factors', 'format_event_logs'
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
    
    # Pagination methods
    'next', 'has_next', 'has_prev', 'prev_page', 'next_page', 'total_pages', 'paginate_results',
    
    # General methods
    'get'
}

# Allowed modules
ALLOWED_MODULES: Set[str] = {
    'okta', 'asyncio', 'typing', 'datetime', 'json', 'time', 'src.utils.pagination_limits'
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