"""
Method Whitelisting Security Module

Provides security validation for code generation and execution in the modern execution manager.
Implements simple but effective security controls:
- Python code pattern validation
- HTTP method restrictions
- Module import restrictions
"""

import re
import ast
import logging
from typing import List, Set, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class SecurityValidationResult:
    """Result of security validation"""
    is_valid: bool
    violations: List[str]
    blocked_patterns: List[str]
    risk_level: str  # 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'

class MethodWhitelistValidator:
    """Validates generated code against security policies"""
    
    # Dangerous patterns that should never appear in generated code
    BLOCKED_PATTERNS = [
        r'os\.system\s*\(',
        r'subprocess\.',
        r'exec\s*\(',
        r'eval\s*\(',
        r'__import__\s*\(',
        r'open\s*\(',
        r'input\s*\(',
        r'file\s*\(',
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
    
    # Allowed Python modules for API code generation (HTTP calls, not SDK)
    ALLOWED_MODULES = {
        'asyncio', 'json', 'datetime', 'time', 'aiohttp', 'sys', 'pathlib',
        'logging', 're', 'typing', 'dataclasses', 'pydantic', 'urllib.parse',
        'base64', 'hashlib', 'hmac', 'uuid', 'collections', 'itertools',
        'utils.pagination_limits',  # From security_config.py
        'base_okta_api_client'      # Our API client module
    }
    
    # Allowed HTTP methods (GET only for security)
    ALLOWED_HTTP_METHODS = {'GET'}
    
    # Safe built-in functions
    ALLOWED_BUILTINS = {
        'len', 'str', 'int', 'float', 'bool', 'list', 'dict', 'tuple', 'set',
        'range', 'enumerate', 'zip', 'sorted', 'reversed', 'sum', 'min', 'max',
        'abs', 'round', 'isinstance', 'issubclass', 'type', 'id', 'hash',
        'repr', 'format', 'print',  # Allow print for debugging
        'any', 'all',  # Boolean aggregation functions (any=at least one True, all=every element True)
        
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
        
        # Main execution functions
        'main', 'run_*', 'execute_*', 'start_*'
    }
    
    # Allowed Python methods for HTTP API calls and data processing
    ALLOWED_PYTHON_METHODS = {
        # HTTP/aiohttp methods
        'ClientSession', 'get', 'post', 'put', 'delete', 'request',
        'headers', 'params', 'timeout', 'raise_for_status',
        
        # JSON methods
        'loads', 'dumps', 'load', 'dump',
        
        # Dictionary/list operations
        'to_dict', 'as_dict', 'dict', 'items', 'keys', 'values', 'get',
        'append', 'extend', 'insert', 'add', 'remove', 'pop', 'clear',
        'index', 'count', 'sort', 'reverse',
        
        # String methods
        'join', 'split', 'strip', 'lstrip', 'rstrip', 'upper', 'lower',
        'capitalize', 'title', 'startswith', 'endswith', 'replace', 'format',
        
        # Data processing
        'filter', 'map', 'any', 'all', 'flatten_dict', 'combine_results',
        'sorted', 'sum', 'min', 'max', 'len', 'round', 'enumerate', 'zip',
        
        # Pagination helpers (from security_config.py)
        'paginate_results', 'handle_single_entity_request',
        'next', 'has_next', 'has_prev', 'prev_page', 'next_page', 'total_pages',
        
        # Security validation (from security_config.py)
        'is_okta_url_allowed', 'validate_api_operation', 'sanitize_response', 'is_code_safe',
        
        # OktaAPIClient methods (simplified client)
        'make_request', 'get_paginated_data',
        
        # Datetime operations
        'now', 'utcnow', 'strftime', 'strptime', 'isoformat', 'timestamp',
        'timedelta', 'date', 'time', 'datetime',
        
        # Async operations
        'await', 'async', 'create_task', 'gather', 'sleep'
    }
    
    def __init__(self):
        """Initialize the validator"""
        self.compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in self.BLOCKED_PATTERNS]
    
    def _is_allowed_user_function(self, func_name: str) -> bool:
        """
        Check if a function name matches allowed user-defined function patterns
        
        Args:
            func_name: Name of the function to check
            
        Returns:
            True if function name matches allowed patterns
        """
        for pattern in self.ALLOWED_USER_FUNCTION_PATTERNS:
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
                    if method_name not in self.ALLOWED_PYTHON_METHODS and method_name not in self.ALLOWED_BUILTINS:
                        violations.append(f"Function '{func_node.name}' contains unauthorized method call: {method_name}")
                elif isinstance(node.func, ast.Name):
                    func_call_name = node.func.id
                    # Allow calls to other user functions but block dangerous builtins
                    if func_call_name not in self.ALLOWED_BUILTINS and not self._is_safe_user_function_call(func_call_name):
                        violations.append(f"Function '{func_node.name}' contains unauthorized function call: {func_call_name}")
            
            # Check for dangerous imports within functions
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module_name = alias.name.split('.')[0]
                        if module_name not in self.ALLOWED_MODULES:
                            violations.append(f"Function '{func_node.name}' contains unauthorized import: {alias.name}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    module_name = node.module.split('.')[0]
                    if module_name not in self.ALLOWED_MODULES:
                        violations.append(f"Function '{func_node.name}' contains unauthorized import from: {node.module}")
        
        return violations
    
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
            'run_', 'execute_', 'start_', 'stop_', 'end_'
        ]
        
        # Check if function starts with any safe pattern
        for pattern in safe_patterns:
            if func_name.startswith(pattern):
                return True
        
        # Allow single word function names (likely user-defined)
        if '_' not in func_name and func_name.islower() and len(func_name) > 2:
            return True
            
        return False
    
    def validate_python_code(self, code: str) -> SecurityValidationResult:
        """
        Validate Python code against security policies
        
        Args:
            code: Python code string to validate
            
        Returns:
            SecurityValidationResult with validation details
        """
        violations = []
        blocked_patterns = []
        risk_level = 'LOW'
        
        # Check for blocked patterns
        for pattern, compiled_pattern in zip(self.BLOCKED_PATTERNS, self.compiled_patterns):
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
                        if module_name not in self.ALLOWED_MODULES:
                            violations.append(f"Unauthorized import: {alias.name}")
                            risk_level = 'HIGH'
                            
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        module_name = node.module.split('.')[0]  # Get top-level module
                        if module_name not in self.ALLOWED_MODULES:
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
                            if method_name not in self.ALLOWED_PYTHON_METHODS and method_name not in self.ALLOWED_BUILTINS:
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
                            if func_name not in self.ALLOWED_BUILTINS:
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
        
        if method_upper not in self.ALLOWED_HTTP_METHODS:
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

# Create a global validator instance
security_validator = MethodWhitelistValidator()

def validate_generated_code(code: str) -> SecurityValidationResult:
    """
    Convenience function to validate generated Python code
    
    Args:
        code: Python code string to validate
        
    Returns:
        SecurityValidationResult with validation details
    """
    return security_validator.validate_python_code(code)

def validate_http_method(method: str) -> SecurityValidationResult:
    """
    Convenience function to validate HTTP method
    
    Args:
        method: HTTP method to validate
        
    Returns:
        SecurityValidationResult with validation details
    """
    return security_validator.validate_http_method(method)

def validate_api_endpoint(endpoint_data: Dict[str, Any]) -> SecurityValidationResult:
    """
    Convenience function to validate API endpoint
    
    Args:
        endpoint_data: Endpoint data dictionary
        
    Returns:
        SecurityValidationResult with validation details
    """
    return security_validator.validate_api_endpoint(endpoint_data)
