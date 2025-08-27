"""
Cleaned Security Configuration for Modern Okta AI Agent

Streamlined security validation focused on current Polars-based architecture.
Removes legacy SDK validation and consolidates only necessary security controls.

Current Usage:
- API code generation validation (base_okta_api_client.py usage)
- Template system security (results_template_agent)
- Generated Python code validation
- HTTP method/endpoint validation

Removed:
- Legacy Okta SDK methods (replaced by Polars)
- Complex SQL validation (simplified with Polars)
- Unused utility method validation
"""

from typing import List, Dict, Any, Set, Optional
import re
import ast
from dataclasses import dataclass
import logging

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
# Core Security Patterns
# ------------------------------------------------------------------------

# Dangerous patterns that should never appear in generated code
BLOCKED_PATTERNS = [
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
    r'delattr\s*\(',
    r'reload\s*\(',
    r'__.*__\s*\(',  # Dunder methods (magic methods) - except allowed ones
]

# Allowed modules for generated code
ALLOWED_MODULES: Set[str] = {
    # Core Python modules
    'asyncio', 'json', 'datetime', 'time', 'sys', 'pathlib',
    'logging', 're', 'typing', 'collections', 'itertools',
    'pprint',  # For template config formatting
    'xml.etree.ElementTree',  # For SAML certificate and XML processing
    'xml.etree',  # For XML processing imports (from xml.etree import ElementTree)
    'base64',  # For base64 encoding/decoding (SAML certificates)
    'dotenv',  # For loading environment variables from .env file
    
    # Cryptography for SAML certificate processing
    'cryptography',  # Certificate parsing and validation
    'cryptography.hazmat.backends',  # Cryptographic backends
    'cryptography.hazmat.primitives',  # Cryptographic primitives
    'cryptography.x509',  # X.509 certificate handling
    'ssl',  # SSL/TLS certificate processing for SAML metadata
    
    # HTTP and networking
    'aiohttp',
    
    # Our API client
    'base_okta_api_client',
    
    # Special tools
    'user_access_analysis',  # Access analysis special tool
    
    # Template system (specific allowlist for security)
    'src.core.agents.results_template_agent',
    'src',  # Allow src module imports for template system
}

# Safe built-in functions and classes
ALLOWED_BUILTINS = {
    'len', 'str', 'int', 'float', 'bool', 'list', 'dict', 'tuple', 'set',
    'range', 'enumerate', 'zip', 'sorted', 'reversed', 'sum', 'min', 'max',
    'abs', 'round', 'isinstance', 'issubclass', 'type', 'repr', 'format',
    'print',  # Allow print for debugging in generated code
    'any', 'all', 'iter', 'next', 'map', 'filter',
    'getattr', 'hasattr',  # Safe attribute access
    
    # Essential classes/functions for generated code
    'OktaAPIClient',  # Our API client class
    'Path',           # Pathlib Path
    'main',           # Main function
    'timedelta', 'datetime',  # DateTime operations
    'dumps', 'loads',  # JSON operations
    
    # Template system functions (allow direct function calls)
    'execute_results_template_from_dict',  # Results template processor
}

# Allowed Python methods for generated code
ALLOWED_PYTHON_METHODS = {
    # HTTP/aiohttp methods
    'ClientSession', 'get', 'post', 'put', 'delete', 'request',
    'headers', 'params', 'timeout', 'raise_for_status',
    
    # JSON methods
    'loads', 'dumps', 'load', 'dump', 'JSONDecodeError',
    
    # Data structure operations
    'items', 'keys', 'values', 'get', 'append', 'extend', 'insert',
    'add', 'remove', 'pop', 'clear', 'index', 'count', 'sort', 'reverse',
    'update', 'copy', 'setdefault',
    
    # String methods
    'join', 'split', 'strip', 'lstrip', 'rstrip', 'upper', 'lower',
    'startswith', 'endswith', 'replace', 'format', 'encode', 'decode',
    
    # OktaAPIClient methods (our simplified client)
    'make_request', 'get_paginated_data',
    
    # Datetime operations
    'now', 'utcnow', 'strftime', 'strptime', 'isoformat', 'timestamp',
    
    # Async operations
    'await', 'async', 'create_task', 'gather', 'sleep', 'run',
    
    # Template system methods
    'execute_results_template_from_dict', 'model_dump', 'pformat',
}

# Allowed HTTP methods (GET only for security)
ALLOWED_HTTP_METHODS = {'GET'}

# ------------------------------------------------------------------------
# Enhanced Security Validator
# ------------------------------------------------------------------------

class EnhancedSecurityValidator:
    """Enhanced security validator for modern Polars-based architecture"""
    
    def __init__(self):
        self.blocked_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in BLOCKED_PATTERNS]
        self.allowed_modules = ALLOWED_MODULES
        self.allowed_builtins = ALLOWED_BUILTINS
        self.allowed_methods = ALLOWED_PYTHON_METHODS
        
    def validate_python_code(self, code: str) -> SecurityValidationResult:
        """
        Validate Python code for security compliance.
        Focused on generated API code and template system validation.
        """
        violations = []
        blocked_patterns = []
        risk_level = 'LOW'
        
        try:
            # Parse AST to validate structure
            tree = ast.parse(code)
            
            # Check for dangerous patterns
            for pattern in self.blocked_patterns:
                if pattern.search(code):
                    violations.append(f"Blocked pattern detected: {pattern.pattern}")
                    blocked_patterns.append(pattern.pattern)
                    risk_level = 'HIGH'
            
            # Validate imports and function calls
            for node in ast.walk(tree):
                # Check imports
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name not in self.allowed_modules:
                            violations.append(f"Unauthorized import: {alias.name}")
                            risk_level = 'MEDIUM'
                
                elif isinstance(node, ast.ImportFrom):
                    module_name = node.module or ''
                    
                    # Check full module path first
                    if module_name in self.allowed_modules:
                        continue
                    
                    # Check top-level module as fallback
                    top_level_module = module_name.split('.')[0] if module_name else ''
                    if top_level_module not in self.allowed_modules:
                        violations.append(f"Unauthorized import from: {module_name}")
                        risk_level = 'MEDIUM'
                
                # Check function calls
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        func_name = node.func.id
                        # Allow user-defined functions (not in builtins but also not dangerous)
                        # Only block if it's NOT in allowed builtins AND matches dangerous patterns
                        if func_name not in self.allowed_builtins:
                            # Check if it's a dangerous function name
                            dangerous_patterns = ['exec', 'eval', 'compile', 'open', 'input', 'system']
                            if any(dangerous in func_name.lower() for dangerous in dangerous_patterns):
                                violations.append(f"Unauthorized function call: {func_name}")
                                risk_level = 'HIGH'
                            # Allow user-defined functions like fetch_user_roles, process_data, etc.
                    
                    elif isinstance(node.func, ast.Attribute):
                        attr_name = node.func.attr
                        if attr_name not in self.allowed_methods:
                            # Check if it's a dangerous method name
                            dangerous_patterns = ['exec', 'eval', 'compile', 'open', 'input', 'system']
                            if any(dangerous in attr_name.lower() for dangerous in dangerous_patterns):
                                violations.append(f"Unauthorized method call: {attr_name}")
                                risk_level = 'HIGH'
                            # Allow user-defined methods
        
        except SyntaxError as e:
            violations.append(f"Syntax error in code: {e}")
            risk_level = 'HIGH'
        except Exception as e:
            violations.append(f"Code validation error: {e}")
            risk_level = 'MEDIUM'
        
        is_valid = len(violations) == 0
        return SecurityValidationResult(is_valid, violations, blocked_patterns, risk_level)
    
    def validate_http_method(self, method: str) -> SecurityValidationResult:
        """Validate HTTP method is allowed"""
        method_upper = method.upper()
        
        if method_upper not in ALLOWED_HTTP_METHODS:
            return SecurityValidationResult(
                is_valid=False,
                violations=[f"HTTP method '{method}' not allowed. Only GET is permitted."],
                blocked_patterns=[],
                risk_level='HIGH'
            )
        
        return SecurityValidationResult(
            is_valid=True,
            violations=[],
            blocked_patterns=[],
            risk_level='LOW'
        )
    
    def validate_api_endpoint(self, endpoint_data: Dict[str, Any]) -> SecurityValidationResult:
        """Validate API endpoint configuration"""
        violations = []
        risk_level = 'LOW'
        
        # Check HTTP method if present
        method = endpoint_data.get('method', 'GET')
        method_result = self.validate_http_method(method)
        if not method_result.is_valid:
            violations.extend(method_result.violations)
            risk_level = 'HIGH'
        
        # Basic URL validation (simplified - detailed validation in network_security.py)
        # Allow special tool endpoints to bypass standard API pattern validation
        url_pattern = endpoint_data.get('url_pattern', '') or endpoint_data.get('path', '')
        
        # Exempt special tool endpoints from standard API pattern validation
        # Special tools use /special-tools/ path prefix instead of /api/v1/
        if url_pattern.startswith('/special-tools/'):
            # Special tools have their own validation rules
            pass
        elif not url_pattern.startswith('/api/v1/'):
            violations.append(f"Invalid API endpoint pattern: {url_pattern}")
            risk_level = 'MEDIUM'
            violations.append(f"Invalid API endpoint pattern: {url_pattern}")
            risk_level = 'MEDIUM'
        
        is_valid = len(violations) == 0
        return SecurityValidationResult(is_valid, violations, [], risk_level)

# ------------------------------------------------------------------------
# Global Validator Instance and Public Functions
# ------------------------------------------------------------------------

# Create global validator instance
enhanced_security_validator = EnhancedSecurityValidator()

def validate_generated_code(code: str, allow_polars: bool = False) -> SecurityValidationResult:
    """
    Validate generated Python code for security compliance.
    
    Args:
        code: Python code to validate
        allow_polars: Legacy parameter - kept for compatibility but ignored
        
    Returns:
        SecurityValidationResult with validation status and details
    """
    return enhanced_security_validator.validate_python_code(code)

def validate_http_method(method: str) -> SecurityValidationResult:
    """Validate HTTP method is allowed"""
    return enhanced_security_validator.validate_http_method(method)

def validate_api_endpoint(endpoint_data: Dict[str, Any]) -> SecurityValidationResult:
    """Validate API endpoint configuration"""
    return enhanced_security_validator.validate_api_endpoint(endpoint_data)

# ------------------------------------------------------------------------
# Legacy Compatibility Functions
# ------------------------------------------------------------------------

def is_code_safe(code: str, okta_domain: Optional[str] = None) -> bool:
    """
    LEGACY COMPATIBILITY FUNCTION
    
    Simplified wrapper for backward compatibility.
    Use validate_generated_code() for detailed results.
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
