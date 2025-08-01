"""
Centralized security configuration for the Okta AI Agent.

This module defines all security controls, restrictions, and policies
used throughout the application to enforce secure operations.

Consolidates security validation for:
- API code generation (Okta SDK + HTTP calls)  
- General Python code validation
- SQL statement validation
- HTTP method validation
- Module import restrictions
"""

from typing import List, Dict, Any, Set, Optional
import re
import ast
import os
from urllib.parse import urlparse
from dataclasses import dataclass

# Use standard logging for better compatibility
import logging

# Configure logging
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------
# Security Validation Result Classes
# ------------------------------------------------------------------------

@dataclass
class SecurityValidationResult:
    """Result of security validation"""
    is_valid: bool
    violations: List[str]
    blocked_patterns: List[str]
    risk_level: str  # 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'

# ------------------------------------------------------------------------
# Enhanced Security Patterns (from method_whitelist.py)
# ------------------------------------------------------------------------

# Comprehensive dangerous patterns that should never appear in generated code
COMPREHENSIVE_BLOCKED_PATTERNS = [
    r'os\.system\s*\(',
    r'subprocess\.',
    r'exec\s*\(',
    r'eval\s*\(',
    r'__import__\s*\(',
    r'open\s*\(',
    r'input\s*\(',
    r'\bfile\s*\(',  # Word boundary to avoid matching "profile("
    r'execfile\s*\(',
    r'compile\s*\(',
    r'globals\s*\(',
    r'locals\s*\(',
    r'setattr\s*\(',
    r'getattr\s*\(',
    r'delattr\s*\(',
    r'hasattr\s*\(',
    r'reload\s*\(',
    r'__.*__\s*\(',  # Dunder methods (magic methods)
]

# Enhanced allowed modules (consolidating both systems)
COMPREHENSIVE_ALLOWED_MODULES: Set[str] = {
    # Core Python modules
    'asyncio', 'json', 'datetime', 'time', 'sys', 'pathlib',
    'logging', 're', 'typing', 'dataclasses', 'pydantic', 'urllib.parse',
    'base64', 'hashlib', 'hmac', 'uuid', 'collections', 'itertools',
    
    # HTTP and networking
    'aiohttp',
    
    # Okta-specific
    'okta',
    'base_okta_api_client',      # Our API client module
    
    # Utility modules
    'utils.pagination_limits',   # From existing security_config.py
    
    # Data processing (but NOT Polars methods - those handled by polars_security.py)
}

# Safe built-in functions (enhanced list)
COMPREHENSIVE_ALLOWED_BUILTINS = {
    'len', 'str', 'int', 'float', 'bool', 'list', 'dict', 'tuple', 'set',
    'range', 'enumerate', 'zip', 'sorted', 'reversed', 'sum', 'min', 'max',
    'abs', 'round', 'isinstance', 'issubclass', 'type', 'id', 'hash',
    'repr', 'format', 'print',  # Allow print for debugging
    'any', 'all',  # Boolean aggregation functions
    'iter', 'next', 'map', 'filter',  # Iterator functions commonly used in data processing
    'getattr', 'hasattr',  # Attribute access functions (safe when used properly)
    'slice',  # For list slicing operations
    
    # Essential function calls that should be allowed
    'OktaAPIClient',  # Our API client class
    'Path',           # Pathlib Path for file operations
    'main',           # Main function
    'timedelta',      # DateTime operations
    'datetime',       # DateTime class
    'run',            # asyncio.run
    'dumps',          # json.dumps  
    'loads',          # json.loads
    'next',           # Iterator function (needed for some operations)
}

# Common user-defined function patterns that LLMs generate
ALLOWED_USER_FUNCTION_PATTERNS = {
    # Data processing functions (using wildcards)
    'fetch_*', 'get_*', 'extract_*', 'process_*', 'parse_*', 'format_*',
    'collect_*', 'aggregate_*', 'combine_*', 'merge_*', 'filter_*',
    
    # Helper functions
    'handle_*', 'create_*', 'build_*', 'setup_*', 'init_*',
    'calculate_*', 'validate_*', 'check_*', 'verify_*',
    'safe_*',  # Safe helper functions like safe_join, safe_get, etc.
    
    # Main execution functions
    'main', 'run_*', 'execute_*', 'start_*'
}

# Comprehensive allowed Python methods (excluding Polars - those in polars_security.py)
COMPREHENSIVE_ALLOWED_PYTHON_METHODS = {
    # HTTP/aiohttp methods
    'ClientSession', 'get', 'post', 'put', 'delete', 'request',
    'headers', 'params', 'timeout', 'raise_for_status',
    
    # JSON methods
    'loads', 'dumps', 'load', 'dump',              # Core JSON serialization/deserialization
    'JSONDecodeError', 'JSONEncoder', 'JSONDecoder', # JSON error handling and custom processing
    
    # Dictionary/list operations
    'to_dict', 'as_dict', 'dict', 'items', 'keys', 'values', 'get',
    'append', 'extend', 'insert', 'add', 'remove', 'pop', 'clear',
    'index', 'count', 'sort', 'reverse', 'update',  # Added 'update' for set.update()
    'fromkeys', 'setdefault', 'popitem',            # Additional dict methods
    'copy', 'deepcopy',                             # Safe copying methods
    
    # Set operations commonly used in data processing
    'difference', 'intersection', 'union', 'symmetric_difference',
    'discard', 'isdisjoint', 'issubset', 'issuperset',
    
    # String methods
    'join', 'split', 'strip', 'lstrip', 'rstrip', 'upper', 'lower',
    'capitalize', 'title', 'startswith', 'endswith', 'replace', 'format',
    'encode', 'decode', 'find', 'rfind', 'count',   # Additional string methods for JSON processing
    
    # Data processing
    'filter', 'map', 'any', 'all', 'flatten_dict', 'combine_results',
    'sorted', 'sum', 'min', 'max', 'len', 'round', 'enumerate', 'zip',
    'iter', 'next', 'range',                        # Iterator and range operations
    'safe_join', 'safe_get', 'safe_split',          # Safe helper functions for data processing
    
    # Pagination helpers (from original security_config.py)
    'paginate_results', 'handle_single_entity_request',
    'next', 'has_next', 'has_prev', 'prev_page', 'next_page', 'total_pages',
    
    # Security validation (from original security_config.py)
    'is_okta_url_allowed', 'validate_api_operation', 'sanitize_response', 'is_code_safe',
    
    # OktaAPIClient methods (simplified client)
    'make_request', 'get_paginated_data',
    
    # Datetime operations
    'now', 'utcnow', 'strftime', 'strptime', 'isoformat', 'timestamp',
    'timedelta', 'date', 'time', 'datetime',
    
    # Async operations
    'await', 'async', 'create_task', 'gather', 'sleep',
    
    # NOTE: Polars methods are NOT included here - they're handled by polars_security.py
}

# Allowed HTTP methods (GET only for security)
ALLOWED_HTTP_METHODS = {'GET'}

# ------------------------------------------------------------------------
# Code Execution Security (Original)
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
    'encode', 'decode', 'find', 'rfind', 'count',   # Additional string methods for JSON processing
    
    # Pagination methods
    'next', 'has_next', 'has_prev', 'prev_page', 'next_page', 'total_pages', 'paginate_results', 'handle_single_entity_request'
    
    # General methods
    'get', 'is_okta_url_allowed',
    
    'items', 'keys', 'values', 'enumerate', 'zip',  # Dictionary/list operations
    'fromkeys', 'setdefault', 'popitem',            # dict.fromkeys() for deduplication, dict.setdefault(), dict.popitem()
    'copy', 'deepcopy',                             # copy.copy(), copy.deepcopy() for safe copying
    'format', 'replace', 'startswith', 'endswith',  # String processing (duplicate cleanup)
    'sorted', 'filter', 'map', 'any', 'all',        # Data processing
    'sum', 'min', 'max', 'len', 'round',            # Math and sizing
    'flatten_dict', 'combine_results',              # Results processing helpers
    'safe_join', 'safe_get', 'safe_split',          # Safe helper functions for data processing
    
    # Additional list/set operations commonly used in data processing
    'difference', 'intersection', 'union', 'symmetric_difference',  # Set operations
    'discard', 'isdisjoint', 'issubset', 'issuperset',             # Set comparison methods
    'slice', 'step',                                                # List slicing operations
    
    # JSON and data structure methods for Results Formatter
    'dumps', 'loads', 'load', 'dump',               # json.dumps(), json.loads(), json.load(), json.dump()
    'JSONDecodeError', 'JSONEncoder', 'JSONDecoder', # JSON error handling and custom encoders/decoders
    'isinstance', 'type', 'str', 'int', 'float', 'bool', 'list', 'tuple', 'set', 'dict',  # Type checking and conversion
    'range', 'iter', 'next',                        # For loops and iterations
}

# Allowed modules (legacy - use COMPREHENSIVE_ALLOWED_MODULES for new code)
ALLOWED_MODULES: Set[str] = {
    'okta', 'asyncio', 'typing', 'datetime', 'json', 'time', 'utils.pagination_limits', 'aiohttp'
}

# Dangerous patterns to check for in code (legacy - use COMPREHENSIVE_BLOCKED_PATTERNS for new code)
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
    LEGACY FUNCTION - Use validate_generated_code() for new code
    
    Validate if the provided code adheres to security policies.
    
    Args:
        code: The code string to validate
        okta_domain: Optional Okta domain to check URLs against
        
    Returns:
        True if code is safe, False otherwise
    """
    # Use the new enhanced validation for better security
    result = validate_generated_code(code)
    
    # If using the new system fails, fall back to legacy validation for compatibility
    if not result.is_valid:
        logger.warning(f"Enhanced validation failed: {'; '.join(result.violations)}")
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

# ------------------------------------------------------------------------
# Enhanced Security Validation Classes (from method_whitelist.py)
# ------------------------------------------------------------------------

class EnhancedSecurityValidator:
    """Enhanced security validator that consolidates all validation logic"""
    
    def __init__(self):
        """Initialize the validator"""
        self.compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in COMPREHENSIVE_BLOCKED_PATTERNS]
    
    def _is_allowed_user_function(self, func_name: str) -> bool:
        """
        Check if a function name matches allowed user-defined function patterns
        
        Args:
            func_name: Name of the function to check
            
        Returns:
            True if function name matches allowed patterns
        """
        for pattern in ALLOWED_USER_FUNCTION_PATTERNS:
            if pattern.endswith('*'):
                # Wildcard pattern - check if function name starts with the prefix
                prefix = pattern[:-1]  # Remove the *
                if func_name.startswith(prefix):
                    return True
            else:
                # Exact match
                if func_name == pattern:
                    return True
        return False
    
    def _is_safe_user_function_call(self, func_name: str) -> bool:
        """
        Check if a function call is safe (either matches patterns or is user-defined)
        This is a more permissive check for function calls within user functions
        
        Args:
            func_name: Name of the function being called
            
        Returns:
            True if the function call is considered safe
        """
        # Allow common safe function name patterns
        safe_patterns = [
            'fetch_', 'get_', 'extract_', 'process_', 'parse_', 'format_',
            'collect_', 'aggregate_', 'combine_', 'merge_', 'filter_',
            'handle_', 'create_', 'build_', 'setup_', 'init_',
            'calculate_', 'validate_', 'check_', 'verify_',
            'run_', 'execute_', 'start_', 'stop_', 'end_',
            'safe_'  # Allow safe_ prefixed functions like safe_join
        ]
        
        # Check if function starts with any safe pattern
        for pattern in safe_patterns:
            if func_name.startswith(pattern):
                return True
        
        # Allow single word function names (likely user-defined)
        if '_' not in func_name and func_name.islower() and len(func_name) > 2:
            return True
            
        return False
    
    def _validate_function_body(self, func_node: ast.FunctionDef) -> List[str]:
        """
        Validate the body of a user-defined function for security violations
        
        Args:
            func_node: AST node representing the function definition
            
        Returns:
            List of security violations found in the function body
        """
        violations = []
        
        # Check all nodes within the function body
        for node in ast.walk(func_node):
            # Skip the function definition itself
            if node == func_node:
                continue
                
            # Check for dangerous patterns in function calls
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    method_name = node.func.attr
                    # Block dangerous methods even in user functions
                    if (method_name not in COMPREHENSIVE_ALLOWED_PYTHON_METHODS and 
                        method_name not in COMPREHENSIVE_ALLOWED_BUILTINS):
                        violations.append(f"Function '{func_node.name}' contains unauthorized method call: {method_name}")
                elif isinstance(node.func, ast.Name):
                    func_call_name = node.func.id
                    # Allow calls to other user functions but block dangerous builtins
                    if (func_call_name not in COMPREHENSIVE_ALLOWED_BUILTINS and 
                        not self._is_safe_user_function_call(func_call_name)):
                        violations.append(f"Function '{func_node.name}' contains unauthorized function call: {func_call_name}")
            
            # Check for dangerous imports within functions
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module_name = alias.name.split('.')[0]
                        if module_name not in COMPREHENSIVE_ALLOWED_MODULES:
                            violations.append(f"Function '{func_node.name}' contains unauthorized import: {alias.name}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    module_name = node.module.split('.')[0]
                    if module_name not in COMPREHENSIVE_ALLOWED_MODULES:
                        violations.append(f"Function '{func_node.name}' contains unauthorized import from: {node.module}")
        
        return violations
    
    def validate_python_code(self, code: str, allow_polars: bool = False) -> SecurityValidationResult:
        """
        Validate Python code against comprehensive security policies
        
        Args:
            code: Python code string to validate
            allow_polars: Whether to allow Polars methods (should use polars_security.py instead)
            
        Returns:
            SecurityValidationResult with validation details
        """
        violations = []
        blocked_patterns = []
        risk_level = 'LOW'
        
        # Check for blocked patterns
        for pattern, compiled_pattern in zip(COMPREHENSIVE_BLOCKED_PATTERNS, self.compiled_patterns):
            if compiled_pattern.search(code):
                blocked_patterns.append(pattern)
                violations.append(f"Blocked pattern found: {pattern}")
                risk_level = 'CRITICAL'
        
        # Check for dangerous imports and method calls
        try:
            tree = ast.parse(code)
            
            # First pass: collect user-defined function names and validate their bodies
            user_defined_functions = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    user_defined_functions.add(node.name)
                    # Validate the function body for security violations
                    func_violations = self._validate_function_body(node)
                    if func_violations:
                        violations.extend(func_violations)
                        risk_level = 'HIGH'
            
            # Second pass: validate imports and function calls
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module_name = alias.name.split('.')[0]  # Get top-level module
                        if module_name not in COMPREHENSIVE_ALLOWED_MODULES:
                            violations.append(f"Unauthorized import: {alias.name}")
                            risk_level = 'HIGH'
                            
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        module_name = node.module.split('.')[0]  # Get top-level module
                        if module_name not in COMPREHENSIVE_ALLOWED_MODULES:
                            violations.append(f"Unauthorized import from: {node.module}")
                            risk_level = 'HIGH'
                
                # Check method calls against whitelist (only at module level, not within functions)
                elif isinstance(node, ast.Call):
                    # Skip validation if this call is inside a function (already validated in function body)
                    parent_function = None
                    for parent in ast.walk(tree):
                        if isinstance(parent, ast.FunctionDef):
                            if any(child_node == node for child_node in ast.walk(parent)):
                                parent_function = parent
                                break
                    
                    if parent_function is None:  # This is a module-level call
                        if isinstance(node.func, ast.Attribute):
                            method_name = node.func.attr
                            # Check if method is in allowed Python methods
                            if (method_name not in COMPREHENSIVE_ALLOWED_PYTHON_METHODS and 
                                method_name not in COMPREHENSIVE_ALLOWED_BUILTINS):
                                # Special handling for Polars methods - suggest using polars_security.py
                                if not allow_polars and any(polars_hint in code.lower() for polars_hint in ['polars', 'pl.', 'dataframe']):
                                    violations.append(f"Polars method '{method_name}' detected - use polars_security.py for Polars validation")
                                else:
                                    violations.append(f"Unauthorized method call: {method_name}")
                                risk_level = 'HIGH'
                        elif isinstance(node.func, ast.Name):
                            func_name = node.func.id
                            # Allow calls to user-defined functions
                            if func_name in user_defined_functions:
                                continue
                            # Allow calls to safe user function patterns
                            if self._is_safe_user_function_call(func_name):
                                continue
                            # Check if function is in allowed builtins
                            if func_name not in COMPREHENSIVE_ALLOWED_BUILTINS:
                                violations.append(f"Unauthorized function call: {func_name}")
                                risk_level = 'HIGH'
                            
        except SyntaxError as e:
            violations.append(f"Syntax error in code: {e}")
            risk_level = 'MEDIUM'
        except Exception as e:
            violations.append(f"Code analysis error: {e}")
            risk_level = 'MEDIUM'
        
        is_valid = len(violations) == 0
        
        return SecurityValidationResult(
            is_valid=is_valid,
            violations=violations,
            blocked_patterns=blocked_patterns,
            risk_level=risk_level
        )
    
    def validate_http_method(self, method: str) -> SecurityValidationResult:
        """
        Validate HTTP method against allowed methods
        
        Args:
            method: HTTP method to validate (GET, POST, etc.)
            
        Returns:
            SecurityValidationResult with validation details
        """
        violations = []
        method_upper = method.upper()
        
        if method_upper not in ALLOWED_HTTP_METHODS:
            violations.append(f"HTTP method '{method}' not allowed. Only GET methods are permitted.")
            risk_level = 'HIGH'
        else:
            risk_level = 'LOW'
        
        is_valid = len(violations) == 0
        
        return SecurityValidationResult(
            is_valid=is_valid,
            violations=violations,
            blocked_patterns=[],
            risk_level=risk_level
        )
    
    def validate_api_endpoint(self, endpoint_data: Dict[str, Any]) -> SecurityValidationResult:
        """
        Validate API endpoint data for security compliance
        
        Args:
            endpoint_data: Dictionary containing endpoint information
            
        Returns:
            SecurityValidationResult with validation details
        """
        violations = []
        risk_level = 'LOW'
        
        # Check HTTP method
        method = endpoint_data.get('method', '')
        method_result = self.validate_http_method(method)
        if not method_result.is_valid:
            violations.extend(method_result.violations)
            risk_level = method_result.risk_level
        
        # Check for suspicious endpoint patterns
        url_pattern = endpoint_data.get('url_pattern', '')
        operation = endpoint_data.get('operation', '')
        
        # Block operations that suggest modification
        dangerous_operations = [
            'create', 'update', 'delete', 'replace', 'activate', 'deactivate',
            'assign', 'unassign', 'revoke', 'suspend', 'unlock', 'reset'
        ]
        
        if operation.lower() in dangerous_operations:
            violations.append(f"Operation '{operation}' not allowed in GET-only mode")
            risk_level = 'HIGH'
        
        is_valid = len(violations) == 0
        
        return SecurityValidationResult(
            is_valid=is_valid,
            violations=violations,
            blocked_patterns=[],
            risk_level=risk_level
        )

# ------------------------------------------------------------------------
# Global Validator Instances and Convenience Functions
# ------------------------------------------------------------------------

# Create global validator instances
enhanced_security_validator = EnhancedSecurityValidator()

# Enhanced convenience functions that replace method_whitelist.py functions
def validate_generated_code(code: str, allow_polars: bool = False) -> SecurityValidationResult:
    """
    Validate generated Python code with enhanced security policies
    
    Args:
        code: Python code string to validate
        allow_polars: Whether to allow Polars methods (should use polars_security.py instead)
        
    Returns:
        SecurityValidationResult with validation details
    """
    return enhanced_security_validator.validate_python_code(code, allow_polars)

def validate_http_method(method: str) -> SecurityValidationResult:
    """
    Convenience function to validate HTTP method
    
    Args:
        method: HTTP method to validate
        
    Returns:
        SecurityValidationResult with validation details
    """
    return enhanced_security_validator.validate_http_method(method)

def validate_api_endpoint(endpoint_data: Dict[str, Any]) -> SecurityValidationResult:
    """
    Convenience function to validate API endpoint
    
    Args:
        endpoint_data: Endpoint data dictionary
        
    Returns:
        SecurityValidationResult with validation details
    """
    return enhanced_security_validator.validate_api_endpoint(endpoint_data)

# Backward compatibility functions for existing code
def is_code_safe(code: str, okta_domain: Optional[str] = None) -> bool:
    """
    Legacy function for backward compatibility - now uses enhanced validation
    
    Args:
        code: Python code to validate
        okta_domain: Optional Okta domain (for URL validation)
        
    Returns:
        True if code passes security validation
    """
    result = validate_generated_code(code)
    return result.is_valid

def get_allowed_methods_for_prompt() -> str:
    """
    Generate a formatted string of allowed methods for inclusion in LLM prompts.
    This ensures the LLM knows exactly what methods it can use, reducing security violations.
    
    Returns:
        Formatted string listing all allowed methods categorized by type
    """
    
    # Built-in functions that are safe to use
    builtins = sorted([
        'len', 'str', 'int', 'float', 'bool', 'list', 'dict', 'tuple', 'set',
        'range', 'enumerate', 'zip', 'sorted', 'sum', 'min', 'max', 'isinstance', 
        'type', 'any', 'all', 'iter', 'next', 'print'
    ])
    
    # Dictionary and list methods
    dict_list_methods = sorted([
        'get', 'items', 'keys', 'values', 'append', 'extend', 'insert', 'add', 
        'remove', 'pop', 'clear', 'index', 'count', 'sort', 'reverse', 'update', 
        'fromkeys', 'setdefault', 'copy'
    ])
    
    # String methods
    string_methods = sorted([
        'join', 'split', 'strip', 'lstrip', 'rstrip', 'upper', 'lower', 
        'startswith', 'endswith', 'replace', 'format', 'find', 'count'
    ])
    
    # JSON methods
    json_methods = sorted(['dumps', 'loads', 'load', 'dump', 'JSONDecodeError'])
    
    # Set operations
    set_methods = sorted([
        'difference', 'intersection', 'union', 'discard', 'isdisjoint', 
        'issubset', 'issuperset'
    ])
    
    return f"""**Built-in Functions:** {', '.join(f'`{m}`' for m in builtins)}

**Dict/List Methods:** {', '.join(f'`{m}`' for m in dict_list_methods)}

**String Methods:** {', '.join(f'`{m}`' for m in string_methods)}

**JSON Methods:** {', '.join(f'`{m}`' for m in json_methods)}

**Set Operations:** {', '.join(f'`{m}`' for m in set_methods)}

**Safe Helper Functions:** You may define helper functions starting with `safe_`, `get_`, `build_`, `process_`, `format_` (e.g., `safe_join()`, `build_lookup()`)"""