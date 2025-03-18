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

async def execute_okta_code(
    code: str, 
    okta_client: Any, 
    okta_domain: str,
    query_id: str = "unknown",
    extra_context: Dict[str, Any] = None
) -> Dict[str, Any]:
    """Execute generated Okta SDK code in a secure environment."""
    start_time = time.time()
    logger.info(f"[FLOW:{query_id}] Validating and executing generated code")
    
    # Validate code
    validation_result = CodeValidator.validate_code(code, okta_domain)
    if validation_result is not True:
        logger.warning(f"[FLOW:{query_id}] Code validation failed: {validation_result}")
        raise ValueError(f"Code validation failed: {validation_result}")
    
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
        # Check if this is a structured results dict or flat variables dict
        if isinstance(extra_context, dict):
            # Extract variables directly or from nested structure
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
    
    # Wrap the modified code in a function
    func_code = f"""
async def _execute_step():
    # Make context variables available
    result = None
    
    # Execute the generated code
    try:
{textwrap.indent(modified_code, '        ')}
    except ReturnValueException as rv:
        result = rv.value
        
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
        
        # Try to find the most likely result value
        result = local_vars.get('result')
        
        # First check for Okta errors if using tuple unpacking
        if has_tuple_unpacking and 'err' in variables and variables['err'] is not None:
            result = {"error": str(variables['err'])}
        
        # If no explicit result from return statement, try to infer from common variable names
        if result is None:
            for name in ['user_details', 'result', 'users_list', 'user', 'users', 'groups', 'applications', 'email']:
                if name in variables:
                    # Check if this is actually a tuple from unpacking
                    if isinstance(variables[name], tuple) and len(variables[name]) == 3:
                        # It's a tuple from Okta SDK - extract the data part
                        data, resp, err = variables[name]
                        if err:
                            result = {"error": str(err)}
                        else:
                            result = data
                    else:
                        # Regular variable
                        result = variables[name]
                    break
        
        elapsed = time.time() - start_time
        logger.info(f"[FLOW:{query_id}] Code execution completed in {elapsed:.2f}ms")
        
        # Log variables at debug level instead of printing
        logger.debug("Executed code:\n%s", code)
        logger.debug("Variables:")
        for var_name, var_value in variables.items():
            if var_name in ['err'] and var_value is not None:
                logger.debug("%s = %s (ERROR DETECTED)", var_name, var_value)
            elif var_name not in ['resp', 'client']:
                var_preview = str(var_value)[:100] + '...' if len(str(var_value)) > 100 else str(var_value)
                logger.debug("%s = %s = %s", var_name, type(var_value).__name__, var_preview)
        
        # Return execution results
        return {
            "result": result,
            "execution_time_ms": int(elapsed * 1000),
            "code": code,
            "success": True,
            "variables": variables
        }
        
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[FLOW:{query_id}] Code execution failed: {str(e)}", exc_info=True)
        
        return {
            "result": None,
            "error": str(e),
            "execution_time_ms": int(elapsed * 1000),
            "code": code,
            "success": False
        }