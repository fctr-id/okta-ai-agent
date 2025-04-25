"""
Utilities for secure code execution in the Okta AI Agent.
Provides validation, execution, and result processing for generated code.
"""

from typing import Dict, List, Any, Optional, Union, Callable, Tuple
import re
import ast
import textwrap
import asyncio
import json
import time
from datetime import datetime
from urllib.parse import urlparse

# Import our new error handling
from src.utils.error_handling import (
    BaseError, SecurityError, ExecutionError, ConfigurationError, 
    ValidationError, safe_execute, safe_execute_async, format_error_for_user, ErrorSeverity
)
from src.utils.logging import get_logger

# Configure logging
logger = get_logger(__name__)

class ReturnValueException(Exception):
    """Exception used to capture return statements in executed code."""
    def __init__(self, value):
        self.value = value
        super().__init__(f"Return value: {value}")

# Security configuration - centralized allowed SDK methods
ALLOWED_SDK_METHODS = {
    # User operations
    'get_user', 'get_users', 'list_users',
    
    # Group operations
    'get_group', 'list_groups', 'list_group_users',
    'list_assigned_applications_for_group',
    
    # Application operations
    'get_application', 'list_applications',
    'list_application_assignments',
    
    # Other operations
    'get_logs', 'list_user_groups',
    'list_factors', 'list_supported_factors',
    'get_user_factors'
}

# Security configuration - allowed utility methods
ALLOWED_UTILITY_METHODS = {
    # Data conversion methods
    'to_dict', 'as_dict', 'dict', 'json',
    
    # Common list operations
    'append', 'extend', 'insert', 'remove', 'pop', 'clear', 
    'index', 'count', 'sort', 'reverse',
    
    # String methods
    'join', 'split', 'strip', 'lstrip', 'rstrip', 'upper', 'lower',
    
    # Pagination methods
    'next', 'has_next', 'has_prev', 'prev_page', 'next_page', 'total_pages',
    
    # General methods
    'get'
}

# Security configuration - allowed modules
ALLOWED_MODULES = {
    'okta', 'asyncio', 'typing', 'datetime', 'json', 'time'
}
    
class CodeValidator:
    """Validates generated code for security."""
    
    # Reference the centralized security configurations
    ALLOWED_MODULES = ALLOWED_MODULES
    ALLOWED_METHODS = ALLOWED_SDK_METHODS.union(ALLOWED_UTILITY_METHODS)
    
    @classmethod
    def validate_code(cls, code: str, okta_domain: str) -> Union[bool, ValidationError]:
        """
        Validate code meets security requirements.
        
        Args:
            code: Python code to validate
            okta_domain: Allowed Okta domain
            
        Returns:
            True if valid, ValidationError if invalid
        """
        # Parse the code into an AST
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return ValidationError(
                message=f"Generated code contains syntax errors",
                field="code",
                context={"error": str(e)}
            )
        
        # Check for imports
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module_name = node.names[0].name.split('.')[0] if isinstance(node, ast.Import) else node.module.split('.')[0]
                if module_name not in cls.ALLOWED_MODULES:
                    return SecurityError(
                        message=f"Unauthorized module import",
                        security_type="prohibited_import",
                        context={
                            "module": module_name,
                            "allowed_modules": list(cls.ALLOWED_MODULES)
                        }
                    )
                    
        # Check for method calls
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                method_name = node.func.attr
                if method_name not in cls.ALLOWED_METHODS:
                    return SecurityError(
                        message=f"Unauthorized method call",
                        security_type="prohibited_method",
                        context={
                            "method": method_name,
                            "allowed_methods_count": len(cls.ALLOWED_METHODS)
                        }
                    )
                    
        # Check for URL restrictions
        url_pattern = re.compile(r'https?://([^/]+)')
        urls = url_pattern.findall(code)
        for url in urls:
            if okta_domain not in url:
                return SecurityError(
                    message=f"Unauthorized domain in URL",
                    security_type="prohibited_domain",
                    context={"url": url, "allowed_domain": okta_domain}
                )

        # Look for potentially dangerous patterns
        dangerous_patterns = [
            (r'os\s*\.\s*system', "System command execution"),
            (r'subprocess', "Subprocess execution"),
            (r'exec\s*\(', "Dynamic code execution"),
            (r'eval\s*\(', "Dynamic code evaluation"),
            (r'__import__\s*\(', "Dynamic module import"),
            (r'open\s*\(', "File operations"),
            (r'input\s*\(', "User input")
        ]
        
        for pattern, reason in dangerous_patterns:
            if re.search(pattern, code):
                return SecurityError(
                    message=f"{reason} is not allowed",
                    security_type="prohibited_pattern",
                    context={"pattern": pattern, "reason": reason}
                )
        
        return True


def prepare_execution_environment(
    okta_client: Any, 
    extra_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Prepare the execution environment with necessary variables.
    
    Args:
        okta_client: The Okta client instance
        extra_context: Variables from previous steps
        
    Returns:
        Dictionary with execution namespace
    """
    # Execution environment with standard variables
    namespace = {
        'client': okta_client,  # The Okta client
        'okta_client': okta_client,  # Alias for the Okta client
        'asyncio': asyncio,
        'json': json,
        'datetime': datetime,
        'logger': logger,
        'ReturnValueException': ReturnValueException
    }
    
    # Add any variables from previous steps
    if extra_context:
        if isinstance(extra_context, dict):
            # Extract variables from extra_context
            for key, value in extra_context.items():
                if isinstance(value, dict) and 'variables' in value:
                    # This is a structured result from a previous step
                    namespace.update(value['variables'])
                else:
                    # This is a simple variable
                    namespace[key] = value
    
    return namespace


def transform_code_for_execution(code: str) -> str:
    """
    Transform code to capture return statements using exceptions.
    
    Args:
        code: The original Python code
        
    Returns:
        Modified code with return statements replaced
    """
    modified_code = code
    return_pattern = re.compile(r'return\s+(.*?)(\n|$)')
    
    for match in return_pattern.finditer(code):
        return_expr = match.group(1).strip()
        replacement = f"raise ReturnValueException({return_expr})"
        modified_code = modified_code.replace(f"return {return_expr}", replacement)
    
    return modified_code


def wrap_code_in_function(code: str) -> str:
    """
    Wrap the code in a function for better error handling.
    
    Args:
        code: The Python code to wrap
        
    Returns:
        Function code as a string
    """
    return f"""
async def _execute_step():
    # Make context variables available
    result = None
    
    # Execute the generated code
    try:
{textwrap.indent(code, '        ')}
    except ReturnValueException as rv:
        result = rv.value
    except Exception as exec_error:
        # Trap exceptions inside the execution function
        result = {{"status": "error", "error": str(exec_error)}}
        
    # Return all local variables
    return_dict = locals()
    return_dict['result'] = result
    return return_dict
"""


def process_execution_result(
    local_vars: Dict[str, Any], 
    has_tuple_unpacking: bool
) -> Tuple[Any, Dict[str, Any]]:
    """
    Process the local variables after code execution to extract results.
    
    Args:
        local_vars: Dictionary of local variables after execution
        has_tuple_unpacking: Whether the code uses tuple unpacking pattern
        
    Returns:
        Tuple of (result, variables for next step)
    """
    # Define excluded variables that should not be passed to the next step
    excluded_vars = {
        'client', 'okta_client', 'asyncio', 'json', 
        'datetime', 'logger', 'ReturnValueException'
    }
    
    # Extract variables for the next step
    variables = {
        k: v for k, v in local_vars.items() 
        if not k.startswith('_') and k not in excluded_vars
    }
    
    # Determine the result value, prioritizing explicit returns
    result = local_vars.get('result')
    
    # Check for Okta errors if using tuple unpacking
    if has_tuple_unpacking and 'err' in variables and variables['err'] is not None:
        result = {
            "status": "error", 
            "error": str(variables['err']),
            "data": None
        }
    
    # If no explicit result from return statement, try to infer from common variable names
    if result is None:
        # Common result variable names in order of priority
        result_var_names = [
            'user_details', 'result', 'users_list', 'user', 'users', 
            'groups', 'applications', 'email', 'combined_results'
        ]
        
        for name in result_var_names:
            if name in variables:
                # Check if this is actually a tuple from unpacking
                if isinstance(variables[name], tuple) and len(variables[name]) == 3:
                    # It's a tuple from Okta SDK - extract the data part
                    data, resp, err = variables[name]
                    if err:
                        result = {
                            "status": "error",
                            "error": str(err),
                            "data": None
                        }
                    else:
                        result = data
                else:
                    # Regular variable
                    result = variables[name]
                break
    
    # Check for empty results (e.g., [], {}) and differentiate from None
    empty_result_vars = ['users_list', 'users', 'groups', 'results']
    if result is None and any(name in variables and variables[name] == [] for name in empty_result_vars):
        # Empty list is a valid result, not an error
        result = []
        
    # Normalize the result structure
    if result is not None and not isinstance(result, (str, int, float, bool)):
        if is_error_result(result):
            # Already contains error information, make sure it's properly structured
            if isinstance(result, dict) and "status" not in result and "error" in result:
                result = {
                    "status": "error",
                    "error": result["error"],
                    "data": None
                }
    
    return result, variables


def is_error_result(result: Any) -> bool:
    """
    Check if a result represents an error condition.
    
    Args:
        result: Any result object to check
        
    Returns:
        True if the result indicates an error, False otherwise
    """
    # Error statuses
    ERROR_STATUSES = {"error", "not_found", "dependency_failed"}
    
    # Check dictionary with standard error structure
    if isinstance(result, dict):
        if "status" in result and result["status"] in ERROR_STATUSES:
            return True
        if "error" in result:
            return True
            
    return False


def normalize_result(result: Any) -> Dict[str, Any]:
    """
    Normalize a result into a standard structure.
    
    Args:
        result: Any result value
        
    Returns:
        A standardized result dictionary
    """
    # Already properly structured
    if isinstance(result, dict) and "status" in result:
        return result
        
    # Error dictionary without status
    if isinstance(result, dict) and "error" in result:
        return {
            "status": "error",
            "error": result["error"],
            "data": None
        }
        
    # Regular success result
    return {
        "status": "success",
        "data": result,
        "error": None
    }


def extract_code_from_llm_response(response: str) -> str:
    """
    Extract Python code from an LLM response using various formats.
    
    Args:
        response: The raw response from the LLM
        
    Returns:
        The extracted Python code or ValidationError
    """
    try:
        # First, try to extract from XML-style tags
        code_match = re.search(r'<CODE>(.*?)</CODE>', response, re.DOTALL)
        if code_match:
            return code_match.group(1).strip()
        
        # Next, try to extract from JSON (legacy support)
        try:
            # Check for JSON format (either directly or in code blocks)
            json_match = re.search(r'```json\s*(.*?)```', response, re.DOTALL) 
            if json_match:
                json_str = json_match.group(1).strip()
            elif response.strip().startswith('{') and response.strip().endswith('}'):
                json_str = response.strip()
            else:
                json_str = None
                
            if json_str:
                data = json.loads(json_str)
                if 'code' in data:
                    return data['code']
        except json.JSONDecodeError:
            pass  # Silently continue if JSON parsing fails
        
        # Check for Python code blocks with ```python
        if "```python" in response:
            return response.split("```python")[1].split("```")[0].strip()
        # Check for generic code blocks with ```
        elif "```" in response:
            return response.split("```")[1].split("```")[0].strip()
        
        # Otherwise return the whole response
        return response.strip()
        
    except Exception as e:
        return ValidationError(
            message="Failed to extract code from LLM response",
            original_exception=e,
            context={"response_preview": response[:100] + "..." if len(response) > 100 else response}
        )


def log_execution_details(query_id: str, code: str, variables: Dict[str, Any], elapsed_time: float):
    """
    Log details about the code execution.
    
    Args:
        query_id: Identifier for the query/flow
        code: The executed code
        variables: Variables from the execution
        elapsed_time: Execution time in seconds
    """
    logger.info(f"Code execution completed in {elapsed_time:.2f}ms")
    
    # Log variables at debug level
    logger.debug(f"Executed code:\n%s", code)
    logger.debug(f"Variables:")
    for var_name, var_value in variables.items():
        if var_name in ['err'] and var_value is not None:
            logger.debug(f"%s = %s (ERROR DETECTED)", var_name, var_value)
        elif var_name not in ['resp', 'client']:
            var_preview = str(var_value)[:100] + '...' if len(str(var_value)) > 100 else str(var_value)
            logger.debug(f"%s = %s = %s", var_name, type(var_value).__name__, var_preview)


async def execute_okta_code(
    code: str, 
    okta_client: Any, 
    okta_domain: str,
    query_id: str = "unknown",
    extra_context: Dict[str, Any] = None,
    execution_timeout: float = 5.0  # 5 second timeout
) -> Dict[str, Any]:
    """
    Execute generated Okta SDK code in a secure environment.
    
    Args:
        code: The Python code to execute
        okta_client: The Okta client instance
        okta_domain: The Okta domain for validation
        query_id: Identifier for the query/flow
        extra_context: Variables from previous steps
        execution_timeout: Maximum execution time in seconds
        
    Returns:
        Dictionary with execution results and metadata
    """
    start_time = time.time()
    logger.info(f"Validating and executing generated code")
    logger.debug(f"Code to execute:\n{code}")
    
    try:
        # Step 1: Validate code for security
        validation_result = CodeValidator.validate_code(code, okta_domain)
        if validation_result is not True:
            if isinstance(validation_result, BaseError):
                validation_result.log()
                error_message = format_error_for_user(validation_result)
            else:
                error_message = str(validation_result)
                
            logger.warning(f"Code validation failed: {error_message}")
            return {
                "result": {
                    "status": "error",
                    "error": f"Code validation failed: {error_message}",
                    "data": None
                },
                "execution_time_ms": 0,
                "code": code,
                "success": False
            }
        
        # Step 2: Prepare execution environment
        namespace = prepare_execution_environment(okta_client, extra_context)
        
        # Step 3: Detect code patterns
        has_tuple_unpacking = re.search(r'(\w+),\s*(\w+),\s*(\w+)\s*=\s*await\s+client\.', code) is not None
        
        # Step 4: Transform code for execution
        transformed_code, transform_error = safe_execute(
            transform_code_for_execution,
            code,
            error_message="Failed to transform code for execution"
        )
        
        if transform_error:
            transform_error.log()
            return {
                "result": {
                    "status": "error",
                    "error": format_error_for_user(transform_error),
                    "data": None
                },
                "execution_time_ms": int((time.time() - start_time) * 1000),
                "code": code,
                "success": False,
                "error": format_error_for_user(transform_error)
            }
        
        # Step 5: Wrap code in an execution function
        func_code = wrap_code_in_function(transformed_code)
        
        # Step 6: Execute the code with timeout protection
        exec_result, exec_error = await safe_execute_async(
            async_execute_with_timeout,
            func_code,
            namespace,
            execution_timeout,
            error_message="Code execution failed"
        )
        
        if exec_error:
            exec_error.log()
            return {
                "result": {
                    "status": "error",
                    "error": format_error_for_user(exec_error),
                    "data": None
                },
                "execution_time_ms": int((time.time() - start_time) * 1000),
                "code": code,
                "success": False,
                "error": format_error_for_user(exec_error)
            }
        
        # Unpack execution result
        is_timeout, local_vars = exec_result
        
        # Handle timeout case
        if is_timeout:
            timeout_error = ExecutionError(
                message=f"Execution timed out after {execution_timeout} seconds",
                context={"timeout_seconds": execution_timeout}
            )
            timeout_error.log()
            return {
                "result": {
                    "status": "error",
                    "error": format_error_for_user(timeout_error),
                    "data": None
                },
                "execution_time_ms": int((time.time() - start_time) * 1000),
                "code": code,
                "success": False,
                "error": format_error_for_user(timeout_error)
            }
        
        # Step 7: Process and normalize results
        result, variables = process_execution_result(local_vars, has_tuple_unpacking)
        
        # Step 8: Log execution details
        elapsed = time.time() - start_time
        log_execution_details(query_id, code, variables, elapsed * 1000)
        
        # Step 9: Return execution results
        return {
            "result": result,
            "execution_time_ms": int(elapsed * 1000),
            "code": code,
            "success": not is_error_result(result),
            "variables": variables,
            "error": result["error"] if is_error_result(result) and isinstance(result, dict) and "error" in result else None
        }
        
    except Exception as e:
        # Create a proper error object
        error = ExecutionError(
            message="Unexpected error during code execution",
            original_exception=e,
            context={"code_preview": code[:100] + "..." if len(code) > 100 else code}
        )
        error.log()
        
        # Return structured error response
        elapsed = time.time() - start_time
        return {
            "result": {
                "status": "error",
                "error": format_error_for_user(error),
                "data": None
            },
            "execution_time_ms": int(elapsed * 1000),
            "code": code,
            "success": False,
            "error": format_error_for_user(error)
        }


async def async_execute_with_timeout(
    func_code: str,
    namespace: Dict[str, Any],
    timeout: float
) -> Tuple[bool, Dict[str, Any]]:
    """
    Execute code with timeout protection.
    
    Args:
        func_code: The function code to execute
        namespace: The execution namespace
        timeout: Timeout in seconds
        
    Returns:
        Tuple of (is_timeout, local_vars)
    """
    # Execute the function code
    exec(func_code, namespace)
    
    try:
        # Run with timeout protection
        execution_task = namespace['_execute_step']()
        local_vars = await asyncio.wait_for(execution_task, timeout=timeout)
        return False, local_vars  # Not a timeout
    except asyncio.TimeoutError:
        return True, {}  # Timeout occurred