"""
Utilities for secure code execution in the Okta AI Agent.
Provides validation, execution, and result processing for generated code.
"""

from typing import Dict, List, Any, Optional, Union, Callable, Tuple
import re
import os
import traceback
import ast
import textwrap
import asyncio
import json
import time
from datetime import datetime
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv(override=True)

# Import our new error handling
from src.utils.error_handling import (
    BaseError, SecurityError, ExecutionError, ConfigurationError, 
    ValidationError, safe_execute, safe_execute_async, format_error_for_user, ErrorSeverity
)
from src.utils.logging import logger
from src.legacy.realtime_mode.tools.datetime_tools import (
    get_current_time, parse_relative_time, format_date_for_query
)
from src.legacy.realtime_mode.tools.logevents_tools import format_event_logs
# Import security controls from centralized config
from src.utils.security_config import (
    is_code_safe
)
# Error status constants
ERROR_STATUSES = {"error", "not_found", "dependency_failed"}
OPERATION_STATUS_FIELD = "operation_status"

class ReturnValueException(Exception):
    """Exception used to capture return statements in executed code."""
    def __init__(self, value):
        self.value = value
        super().__init__(f"Return value: {value}")
    
class CodeValidator:
    """Validates generated code for security."""
    
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
        # Use centralized security validation
        result = is_code_safe(code, okta_domain)
        if result is not True:
            return SecurityError(
                message="Unauthorized code detected",
                security_type="prohibited_code",
                context={"code_preview": code[:100] + "..." if len(code) > 100 else code}
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
        'ReturnValueException': ReturnValueException,
        'get_current_time': get_current_time,
        'parse_relative_time': parse_relative_time,
        'format_date_for_query': format_date_for_query,
        'format_event_logs': format_event_logs,
    }
    
    # Add any variables from previous steps
    if extra_context:
        if isinstance(extra_context, dict):
            # First, ensure 'result' is directly accessible regardless of nesting
            if 'result' in extra_context:
                namespace['result'] = extra_context['result']
                
            # Extract variables from extra_context
            for key, value in extra_context.items():
                # Skip 'result' since we already handled it above
                if key != 'result':
                    if isinstance(value, dict) and 'variables' in value:
                        # Update with variables from structured result
                        namespace.update(value['variables'])
                    else:
                        # Normal variable handling
                        namespace[key] = value
    
    return namespace


def transform_code_for_execution(code: str) -> str:
    """
    Transform code to capture return statements using AST to correctly handle complex expressions.
    """
    class ReturnTransformer(ast.NodeTransformer):
        def visit_Return(self, node):
            # Create a new node that raises ReturnValueException with the return value
            return ast.Raise(
                exc=ast.Call(
                    func=ast.Name(id='ReturnValueException', ctx=ast.Load()),
                    args=[node.value],
                    keywords=[]
                ),
                cause=None
            )
    
    try:
        # Parse the code into an AST
        tree = ast.parse(code)
        
        # Transform all return statements
        transformer = ReturnTransformer()
        new_tree = transformer.visit(tree)
        ast.fix_missing_locations(new_tree)
        
        # Generate the new code
        return ast.unparse(new_tree)
    except SyntaxError:
        # Fall back to the original code if there are syntax errors in the input
        logger.warning("Syntax error in code, skipping return transformation")
        return code


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
    result = globals().get('result', None)
    
    # Execute the generated code
    try:
{textwrap.indent(code, '        ')}
    except ReturnValueException as rv:
        result = rv.value
    except Exception as exec_error:
        # Trap exceptions inside the execution function
        result = {{"{OPERATION_STATUS_FIELD}": "error", "error": str(exec_error)}}
        
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
            OPERATION_STATUS_FIELD: "error", 
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
                            OPERATION_STATUS_FIELD: "error",
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
            if isinstance(result, dict) and OPERATION_STATUS_FIELD not in result and "error" in result:
                result = {
                    OPERATION_STATUS_FIELD: "error",
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
    # Empty lists and empty dicts are valid results, not errors
    if result == [] or result == {}:
        return False
    
    # Lists are never errors themselves, even if they contain items with status fields
    if isinstance(result, list):
        return False
        
    # None might indicate an error depending on context
    if result is None:
        return False
    
    # Check dictionary with standard error structure
    if isinstance(result, dict):
        if OPERATION_STATUS_FIELD in result and result[OPERATION_STATUS_FIELD] in ERROR_STATUSES:
            return True
        if "error" in result and result["error"]:  # Only if error has a value
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
    if isinstance(result, dict) and OPERATION_STATUS_FIELD in result:
        return result
        
    # Error dictionary without status
    if isinstance(result, dict) and "error" in result:
        return {
            OPERATION_STATUS_FIELD: "error",
            "error": result["error"],
            "data": None
        }
        
    # Regular success result
    return {
        OPERATION_STATUS_FIELD: "success",
        "data": result,
        "error": None
    }


def extract_code_from_llm_response(response: str) -> Union[str, ValidationError]:
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
        try:
            local_vars = await asyncio.wait_for(execution_task, timeout=timeout)
            return False, local_vars  # Not a timeout
        except asyncio.TimeoutError:
            return True, {}  # Timeout occurred
        except Exception as e:
            # Capture and print the actual error that occurred during execution
            error_tb = traceback.format_exc()
            print(f"\n============= EXECUTION ERROR =============")
            print(f"{type(e).__name__}: {str(e)}")
            print(f"\n{error_tb}")
            print(f"==========================================\n")
            
            # Also log the error
            logger.error(f"Execution error: {type(e).__name__}: {str(e)}")
            logger.debug(f"Error traceback:\n{error_tb}")
            
            # Return structured error information
            return False, {
                "result": {
                    OPERATION_STATUS_FIELD: "error", 
                    "error": f"{type(e).__name__}: {str(e)}",
                    "traceback": error_tb
                }
            }
    except Exception as outer_e:
        # Handle any errors in setting up the execution task
        error_tb = traceback.format_exc()
        print(f"\n========= EXECUTION SETUP ERROR =========")
        print(f"{type(outer_e).__name__}: {str(outer_e)}")
        print(f"\n{error_tb}")
        print(f"========================================\n")
        
        logger.error(f"Execution setup error: {type(outer_e).__name__}: {str(outer_e)}")
        logger.debug(f"Setup error traceback:\n{error_tb}")
        
        return False, {
            "result": {
                OPERATION_STATUS_FIELD: "error", 
                "error": f"Setup error: {type(outer_e).__name__}: {str(outer_e)}",
                "traceback": error_tb
            }
        }


async def execute_okta_code(
    code: str, 
    okta_client: Any, 
    okta_domain: str,
    query_id: str = "unknown",
    extra_context: Dict[str, Any] = None,
    execution_timeout: float = float(os.getenv("RLTIME_STEP_EXECUTION_TIMEOUT", 300))
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
        Dictionary with execution results
    """
    start_time = time.time()
    logger.info(f"[{query_id}] Validating and executing generated code")
    logger.debug(f"[{query_id}] Starting code execution with extra_context keys: {list(extra_context.keys()) if extra_context else 'None'}")
    if extra_context and 'result' in extra_context:
        logger.debug(f"[{query_id}] extra_context['result'] type: {type(extra_context['result']).__name__}")
        
        # If it's a dict and has 'result' key (double nested)
        if isinstance(extra_context['result'], dict) and 'result' in extra_context['result']:
            logger.debug(f"[{query_id}] extra_context['result']['result'] found! ID: {extra_context['result']['result'].get('id', 'NO_ID')}")    
    
    try:
        # Step 1: Validate code for security
        validation_result = CodeValidator.validate_code(code, okta_domain)
        if validation_result is not True:
            if isinstance(validation_result, BaseError):
                validation_result.log()
                error_message = format_error_for_user(validation_result)
            else:
                error_message = str(validation_result)
                
            logger.warning(f"[{query_id}] Code validation failed: {error_message}")
            return {
                "result": {
                    OPERATION_STATUS_FIELD: "error",
                    "error": f"Code validation failed: {error_message}",
                    "data": None
                },
                "execution_time_ms": 0,
                "code": code,
                "success": False
            }
        
        # Step 2: Prepare execution environment
        namespace = prepare_execution_environment(okta_client, extra_context)
        logger.debug(f"[{query_id}] Execution namespace keys: {list(namespace.keys())}")
        if 'result' in namespace:
            logger.debug(f"[{query_id}] Execution namespace 'result' type: {type(namespace['result']).__name__}")
            if isinstance(namespace['result'], dict):
                logger.debug(f"[{query_id}] Execution namespace 'result' ID: {namespace['result'].get('id', 'NO_ID')}")
        
        # Step 3: Detect code patterns
        has_tuple_unpacking = re.search(r'(\w+),\s*(\w+),\s*(\w+)\s*=\s*await\s+client\.', code) is not None
        
        # Step 4: Transform code for execution
        transformed_code = transform_code_for_execution(code)
        func_code = wrap_code_in_function(transformed_code)
        
        # Step 5: Execute the code with timeout protection
        logger.debug(f"[{query_id}] Executing code with {execution_timeout}s timeout")
        
        is_timeout, local_vars = await async_execute_with_timeout(
            func_code, namespace, execution_timeout
        )
        
        # Handle timeout case
        if is_timeout:
            elapsed = (time.time() - start_time) * 1000  # in ms
            logger.warning(f"[{query_id}] Execution timed out after {execution_timeout}s")
            return {
                "result": {
                    OPERATION_STATUS_FIELD: "error",
                    "error": f"Execution timed out after {execution_timeout} seconds",
                    "data": None
                },
                "execution_time_ms": int(elapsed),
                "code": code,
                "success": False
            }
        
        # Step 6: Process and normalize results
        result, variables = process_execution_result(local_vars, has_tuple_unpacking)
        
        # Step 7: Return execution results
        elapsed = (time.time() - start_time) * 1000  # in ms
        logger.info(f"[{query_id}] Code execution completed in {elapsed:.2f}ms")
        
        return {
            "result": result,
            "execution_time_ms": int(elapsed),
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
        elapsed = (time.time() - start_time) * 1000  # in ms
        logger.error(f"[{query_id}] Unexpected error after {elapsed:.2f}ms: {str(e)}")
        return {
            "result": {
                OPERATION_STATUS_FIELD: "error",
                "error": format_error_for_user(error),
                "data": None
            },
            "execution_time_ms": int(elapsed),
            "code": code,
            "success": False,
            "error": format_error_for_user(error)
        }