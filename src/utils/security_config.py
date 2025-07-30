"""
Centralized security configuration for the Okta AI Agent.

This module defines all security controls, restrictions, and policies
used throughout the application to enforce secure operations.
"""

from typing import List, Dict, Any, Set, Optional
import re
import ast
import os
from urllib.parse import urlparse
try:
    from .logging import get_logger
except ImportError:
    # Fallback for direct execution
    import logging
    def get_logger(name: str) -> logging.Logger:
        return logging.getLogger(name)

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
    
    # Common list/set operations
    'append', 'extend', 'insert', 'add', 'remove', 'pop', 'clear', 
    'index', 'count', 'sort', 'reverse', 'update',  # Added 'update' for set.update()
    
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
    'okta', 'asyncio', 'typing', 'datetime', 'json', 'time', 'utils.pagination_limits', 'aiohttp'
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
# SQL Security Configuration
# ------------------------------------------------------------------------

# Allowed SQL statement types
ALLOWED_SQL_STATEMENTS: Set[str] = {
    'CREATE TEMPORARY TABLE',
    'INSERT INTO',
    'SELECT'
}

# Forbidden SQL patterns
FORBIDDEN_SQL_PATTERNS: List[tuple] = [
    (r'DROP\s+', "DROP statements not allowed"),
    (r'DELETE\s+', "DELETE statements not allowed"),
    (r'UPDATE\s+', "UPDATE statements not allowed"),
    (r'ALTER\s+', "ALTER statements not allowed"),
    (r'TRUNCATE\s+', "TRUNCATE statements not allowed"),
    (r'--', "SQL comments not allowed"),
    (r'/\*', "SQL comments not allowed"),
    (r';\s*DROP', "SQL injection attempt"),
    (r';\s*DELETE', "SQL injection attempt"),
    # (r'UNION\s+SELECT', "UNION statements not allowed"),  # Allow UNION for legitimate relationship queries
    (r'xp_', "Extended procedures not allowed"),
    (r'sp_', "System procedures not allowed")
]

# Allowed column types for temp tables
ALLOWED_COLUMN_TYPES: Set[str] = {
    'TEXT', 'INTEGER', 'REAL', 'BLOB'
}

# Required temp table name pattern
TEMP_TABLE_PATTERN = re.compile(r'^temp_api_[a-zA-Z0-9_]+$')

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

# ------------------------------------------------------------------------
# SQL Security Validation Functions
# ------------------------------------------------------------------------

def validate_sql_statements(sql_list: List[str]) -> bool:
    """
    Validate a list of SQL statements for security compliance.
    
    Args:
        sql_list: List of SQL statements to validate
        
    Returns:
        True if all statements are safe, False otherwise
    """
    if not sql_list:
        logger.warning("SQL validation failed: empty statement list")
        return False
        
    for i, sql in enumerate(sql_list):
        if not validate_single_sql_statement(sql, i):
            return False
            
    return True

def validate_single_sql_statement(sql: str, index: int = 0) -> bool:
    """
    Validate a single SQL statement for security compliance.
    
    Args:
        sql: SQL statement to validate
        index: Statement index for logging
        
    Returns:
        True if statement is safe, False otherwise
    """
    if not sql or not sql.strip():
        logger.warning(f"SQL validation failed (statement {index}): empty statement")
        return False
        
    sql_upper = sql.strip().upper()
    
    # Check for forbidden patterns first
    for pattern, reason in FORBIDDEN_SQL_PATTERNS:
        if re.search(pattern, sql_upper):
            logger.warning(f"SQL validation failed (statement {index}): {reason}")
            return False
    
    # Validate based on statement type
    if sql_upper.startswith('CREATE TEMPORARY TABLE'):
        return validate_create_temp_table(sql, index)
    elif sql_upper.startswith('INSERT INTO'):
        return validate_insert_statement(sql, index)  
    elif sql_upper.startswith('SELECT'):
        return validate_select_statement(sql, index)
    else:
        logger.warning(f"SQL validation failed (statement {index}): unauthorized statement type")
        return False

def validate_create_temp_table(sql: str, index: int = 0) -> bool:
    """
    Validate CREATE TEMPORARY TABLE statement.
    
    Args:
        sql: CREATE statement to validate
        index: Statement index for logging
        
    Returns:
        True if statement is safe, False otherwise
    """
    sql_upper = sql.upper()
    
    # Must be temporary table
    if 'TEMPORARY TABLE' not in sql_upper:
        logger.warning(f"SQL validation failed (statement {index}): only temporary tables allowed")
        return False
    
    # Extract table name and validate pattern (case insensitive)
    table_match = re.search(r'CREATE\s+TEMPORARY\s+TABLE\s+([A-Z0-9_]+)', sql_upper)
    if not table_match:
        logger.warning(f"SQL validation failed (statement {index}): invalid table name format")
        return False
        
    table_name = table_match.group(1).lower()  # Convert to lowercase for pattern matching
    if not TEMP_TABLE_PATTERN.match(table_name):
        logger.warning(f"SQL validation failed (statement {index}): table name must match temp_api_* pattern")
        return False
    
    # Validate column types
    for col_type in ALLOWED_COLUMN_TYPES:
        if col_type in sql_upper:
            continue
    
    # Check for forbidden column types (basic check)
    forbidden_types = ['EXEC', 'BINARY', 'VARBINARY']
    for forbidden in forbidden_types:
        if forbidden in sql_upper:
            logger.warning(f"SQL validation failed (statement {index}): forbidden column type {forbidden}")
            return False
    
    return True

def validate_insert_statement(sql: str, index: int = 0) -> bool:
    """
    Validate INSERT statement.
    
    Args:
        sql: INSERT statement to validate
        index: Statement index for logging
        
    Returns:
        True if statement is safe, False otherwise
    """
    sql_upper = sql.upper()
    sql_cleaned = ' '.join(sql_upper.split())  # Remove extra whitespace
    
    # Must be INSERT INTO temp table with VALUES (case insensitive)
    pattern = r'INSERT\s+INTO\s+TEMP_API_[A-Z0-9_]+'
    if not re.search(pattern, sql_cleaned):
        logger.warning(f"SQL validation failed (statement {index}): INSERT must target temp_api_* table")
        return False
        
    # Must use VALUES format, not SELECT
    if 'VALUES' not in sql_upper:
        logger.warning(f"SQL validation failed (statement {index}): INSERT must use VALUES format")
        return False
        
    if 'SELECT' in sql_upper:
        logger.warning(f"SQL validation failed (statement {index}): INSERT with SELECT not allowed")
        return False
    
    return True

def validate_select_statement(sql: str, index: int = 0) -> bool:
    """
    Validate SELECT statement.
    
    Args:
        sql: SELECT statement to validate  
        index: Statement index for logging
        
    Returns:
        True if statement is safe, False otherwise
    """
    sql_upper = sql.upper()
    
    # Basic SELECT validation - ensure it's a query only
    if not sql_upper.startswith('SELECT'):
        logger.warning(f"SQL validation failed (statement {index}): statement must start with SELECT")
        return False
    
    # Must include tenant filtering for security
    if 'TENANT_ID' not in sql_upper:
        logger.warning(f"SQL validation failed (statement {index}): SELECT must include tenant_id filtering")
        return False
    
    return True

def validate_sql_for_execution(sql_statements: List[str]) -> tuple[bool, str]:
    """
    Main entry point for SQL security validation.
    
    Args:
        sql_statements: List of SQL statements to execute
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        if not sql_statements:
            return False, "Empty SQL statement list"
            
        # Validate each statement
        if not validate_sql_statements(sql_statements):
            return False, "SQL security validation failed - check logs for details"
            
        # Additional validation: must have CREATE, INSERT, SELECT pattern
        has_create = any(stmt.strip().upper().startswith('CREATE') for stmt in sql_statements)
        has_insert = any(stmt.strip().upper().startswith('INSERT') for stmt in sql_statements)
        has_select = any(stmt.strip().upper().startswith('SELECT') for stmt in sql_statements)
        
        if not (has_create and has_insert and has_select):
            return False, "SQL must contain CREATE TEMPORARY TABLE, INSERT, and SELECT statements"
            
        logger.debug(f"SQL validation passed for {len(sql_statements)} statements")
        return True, "SQL validation passed"
        
    except Exception as e:
        logger.error(f"Error during SQL validation: {str(e)}")
        return False, f"SQL validation error: {str(e)}"