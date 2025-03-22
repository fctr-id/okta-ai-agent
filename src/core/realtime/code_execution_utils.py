from typing import Dict, List, Any, Optional, Union, Callable
import logging
import time
import ast
import re
import inspect
from urllib.parse import urlparse
import textwrap
import asyncio
import json
from datetime import datetime

logger = logging.getLogger(__name__)

class CodeValidator:
    """Validates generated code for security."""
    
    ALLOWED_MODULES = {
        'okta', 'asyncio', 'typing', 'datetime', 'json', 
        'logging', 'time'
    }
    
    ALLOWED_METHODS = {
        # Only permit GET operations for now
        'get_user', 'get_users', 'list_users',
        'get_group', 'list_groups',
        'get_application', 'list_applications',
        'list_application_assignments',
        'get_logs', 'list_user_groups',
        'list_factors', 'list_supported_factors',
        'get_user_factors',
        'to_dict', 'dict', 'json', 'as_dict',
        # Common list operations
        'append', 'extend', 'insert', 'remove', 'pop', 'clear', 'index', 'count', 'sort', 'reverse',
        # String methods
        'join', 'split', 'strip', 'lstrip', 'rstrip', 'upper', 'lower'
    }
    
    @classmethod
    def validate_code(cls, code: str, okta_domain: str) -> Union[bool, str]:
        """
        Validate code meets security requirements.
        
        Args:
            code: Python code to validate
            okta_domain: Allowed Okta domain
            
        Returns:
            True if valid, error message string if invalid
        """
        # Parse the code into an AST
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return "Generated code contains syntax errors"
        
        # Check for imports
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
                module_name = node.names[0].name.split('.')[0] if isinstance(node, ast.Import) else node.module.split('.')[0]
                if module_name not in cls.ALLOWED_MODULES:
                    return f"Unauthorized module: {module_name}"
                    
        # Check for method calls
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    method_name = node.func.attr
                    if method_name not in cls.ALLOWED_METHODS:
                        return f"Unauthorized method: {method_name}"
                        
        # Check for URL restrictions
        url_pattern = re.compile(r'https?://([^/]+)')
        urls = url_pattern.findall(code)
        for url in urls:
            if okta_domain not in url:
                return f"Unauthorized domain in URL: {url}"
        
        return True

def extract_code_from_llm_response(response: str) -> str:
    """
    Extract Python code from an LLM response using various formats.
    
    Args:
        response: The raw response from the LLM
        
    Returns:
        The extracted Python code
    """
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
    except Exception:
        pass  # Silently continue if JSON parsing fails
    
    # Check for Python code blocks with ```python
    if "```python" in response:
        return response.split("```python")[1].split("```")[0].strip()
    # Check for generic code blocks with ```
    elif "```" in response:
        return response.split("```")[1].split("```")[0].strip()
    
    # Otherwise return the whole response
    return response.strip()

def is_error_result(result: Any) -> bool:
    """
    Check if a result represents an error condition.
    
    Args:
        result: Any result object to check
        
    Returns:
        True if the result indicates an error, False otherwise
    """
    # Check dictionary with standard error structure
    if isinstance(result, dict):
        if "status" in result and result["status"] in ["error", "not_found", "dependency_failed"]:
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

async def execute_okta_code(
    code: str, 
    okta_client: Any, 
    okta_domain: str,
    query_id: str = "unknown",
    extra_context: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Execute generated Okta SDK code in a secure environment.
    
    Args:
        code: The Python code to execute
        okta_client: The Okta client instance
        okta_domain: The Okta domain for validation
        query_id: Identifier for the query/flow
        extra_context: Variables from previous steps
        
    Returns:
        Dictionary with execution results and metadata
    """
    start_time = time.time()
    logger.info(f"[FLOW:{query_id}] Validating and executing generated code")
    
    # Validate code
    validation_result = CodeValidator.validate_code(code, okta_domain)
    if validation_result is not True:
        logger.warning(f"[FLOW:{query_id}] Code validation failed: {validation_result}")
        return {
            "result": {
                "status": "error",
                "error": f"Code validation failed: {validation_result}",
                "data": None
            },
            "execution_time_ms": 0,
            "code": code,
            "success": False
        }
    
    # Execution environment
    namespace = {
        'client': okta_client,  # The Okta client
        'okta_client': okta_client,  # Alias for the Okta client
        'asyncio': asyncio,
        'json': json,
        'datetime': datetime,
        'logger': logger
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
    
    # Check if the code uses the tuple unpacking pattern
    has_tuple_unpacking = re.search(r'(\w+),\s*(\w+),\s*(\w+)\s*=\s*await\s+client\.', code) is not None
    
    # Define ReturnValueException to capture return statements
    class ReturnValueException(Exception):
        def __init__(self, value):
            self.value = value
            super().__init__(f"Return value: {value}")
    
    # Add exception to namespace
    namespace['ReturnValueException'] = ReturnValueException
    
    # Modify code to capture return statements
    modified_code = code
    return_pattern = re.compile(r'return\s+(.*?)(\n|$)')
    for match in return_pattern.finditer(code):
        return_expr = match.group(1).strip()
        replacement = f"raise ReturnValueException({return_expr})"
        modified_code = modified_code.replace(f"return {return_expr}", replacement)
    
    # Wrap the modified code in a function with better error trapping
    func_code = f"""
async def _execute_step():
    # Make context variables available
    result = None
    
    # Execute the generated code
    try:
{textwrap.indent(modified_code, '        ')}
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
    
    try:
        # Compile and execute the function code
        exec(func_code, namespace)
        
        # Call the function and get all local variables
        local_vars = await namespace['_execute_step']()
        
        # Handle non-dictionary return (shouldn't happen with our approach, but just in case)
        if not isinstance(local_vars, dict):
            logger.warning(f"[FLOW:{query_id}] Unexpected return type from code execution: {type(local_vars)}")
            local_vars = {'result': local_vars}
        
        # Extract variables for the next step
        variables = {}
        for k, v in local_vars.items():
            if not k.startswith('_') and k not in ['client', 'okta_client', 'asyncio', 'json', 'datetime', 'logger', 'ReturnValueException']:
                variables[k] = v
        
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
            for name in ['user_details', 'result', 'users_list', 'user', 'users', 'groups', 'applications', 'email', 'combined_results']:
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
        if result is None and any(name in variables and variables[name] == [] for name in ['users_list', 'users', 'groups', 'results']):
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
        
        elapsed = time.time() - start_time
        logger.info(f"[FLOW:{query_id}] Code execution completed in {elapsed:.2f}ms")
        
        # Log variables at debug level
        logger.debug("Executed code:\n%s", code)
        logger.debug("Variables:")
        for var_name, var_value in variables.items():
            if var_name in ['err'] and var_value is not None:
                logger.debug("%s = %s (ERROR DETECTED)", var_name, var_value)
            elif var_name not in ['resp', 'client']:
                var_preview = str(var_value)[:100] + '...' if len(str(var_value)) > 100 else str(var_value)
                logger.debug("%s = %s = %s", var_name, type(var_value).__name__, var_preview)
        
        # Return execution results with normalized result format
        return {
            "result": result,
            "execution_time_ms": int(elapsed * 1000),
            "code": code,
            "success": not is_error_result(result),
            "variables": variables,
            "error": result["error"] if is_error_result(result) and isinstance(result, dict) and "error" in result else None
        }
        
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[FLOW:{query_id}] Code execution failed: {str(e)}", exc_info=True)
        
        return {
            "result": {
                "status": "error",
                "error": str(e),
                "data": None
            },
            "execution_time_ms": int(elapsed * 1000),
            "code": code,
            "success": False,
            "error": str(e)
        }