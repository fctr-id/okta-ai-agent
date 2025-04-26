"""
Execution Manager for Okta AI Agent.

This module handles the execution of plans created by the Reasoning Agent:
- Fetches tool documentation from registry
- Generates code for all steps using the Coding Agent
- Executes each step securely
- Tracks results and manages error handling
- Provides structured output for the final response
"""

from typing import Dict, List, Any, Optional, Union, Set, Tuple
import json
import traceback
import time
import uuid
from datetime import datetime
from pydantic import BaseModel, Field
# Add these imports at the top
from pydantic_ai import capture_run_messages
from datetime import datetime
from typing import Dict, Any, List, Optional
from src.utils.pagination_limits import paginate_results as _base_paginate_results


# Import our new error handling
from src.utils.error_handling import (
    BaseError, ExecutionError, ApiError, safe_execute_async,
    format_error_for_user, ErrorSeverity
)
from src.utils.logging import get_logger

from src.core.realtime.okta_realtime_client import OktaRealtimeDeps
from src.core.realtime.agents.reasoning_agent import ExecutionPlan, PlanStep
from src.core.realtime.agents.coding_agent import coding_agent
from src.core.realtime.code_execution_utils import execute_okta_code, is_error_result
from src.config.settings import settings

# Tool registry imports
from src.utils.tool_registry import get_tool_prompt, get_all_tools

# Configure logging
logger = get_logger(__name__)

# Error status constants
ERROR_STATUSES = {"error", "not_found", "dependency_failed"}


class StepError(BaseModel):
    """Error information for a specific execution step."""
    step: str = Field(description="Name of the step where the error occurred")
    error: str = Field(description="Error message")
    critical: bool = Field(default=False, description="Whether this was a critical error")
    entity_type: str = Field(default="unknown", description="Type of entity involved in the error")
    step_number: int = Field(default=0, description="Step number in the plan")


class ExecutionResult(BaseModel):
    """Result of executing an entire plan."""
    results: Dict[str, Any] = Field(description="Results from each executed step")
    entities_queried: List[str] = Field(description="Entity types that were queried")
    errors: Optional[List[StepError]] = Field(None, description="Errors encountered during execution")
    metadata: Dict[str, Any] = Field(description="Additional metadata about execution")
    final_result: Any = Field(default=None, description="The final processed result")
    status: str = Field(default="success", description="Overall execution status")
    execution_time_ms: int = Field(default=0, description="Total execution time in milliseconds")
    correlation_id: Optional[str] = Field(default=None, description="Correlation ID for tracing")




class ExecutionManager:
    """
    Manages the execution of plans created by the Coordinator Agent.
    
    Responsibilities:
    1. Generate Okta SDK code for all steps in one go
    2. Securely execute generated code with validation
    3. Manage results and handle errors
    4. Provide aggregated, structured responses
    """
    
    def __init__(self, okta_deps: OktaRealtimeDeps = None):
        """
        Initialize the execution manager with Okta dependencies.
        
        Args:
            okta_deps: Dependencies for Okta API operations
        """
        # Initialize Okta dependencies
        if okta_deps is None:
            from src.core.realtime.okta_realtime_client import OktaRealtimeDeps
            self.okta_deps = OktaRealtimeDeps(
                domain=settings.OKTA_CLIENT_ORGURL,
                api_token=settings.OKTA_API_TOKEN,
                query_id="default"
            )
        else:
            self.okta_deps = okta_deps
        
        # Initialize the tool entity mapping from registry
        self._initialize_tool_entity_map()
    
    def _initialize_tool_entity_map(self) -> None:
        """Initialize the mapping of tool names to entity types from the registry."""
        self._tool_entity_map = {}
        
        # Build entity map from all registered tools
        all_tools = get_all_tools()
        for tool in all_tools:
            if hasattr(tool, 'name') and hasattr(tool, 'entity_type'):
                self._tool_entity_map[tool.name] = tool.entity_type
                
                # Also map aliases for more robust lookups
                if hasattr(tool, 'aliases'):
                    for alias in tool.aliases:
                        self._tool_entity_map[alias] = tool.entity_type
        
        correlation_id = self.okta_deps.query_id if hasattr(self.okta_deps, 'query_id') else "init"
        logger.debug(f"[{correlation_id}] Initialized tool entity map with {len(self._tool_entity_map)} entries")
    
    def _generate_correlation_id(self) -> str:
        """Generate a unique correlation ID for tracing execution."""
        return f"exec-{str(uuid.uuid4())[:8]}"
    
    async def execute_plan(self, plan: ExecutionPlan, correlation_id: str = None) -> Union[ExecutionResult, BaseError]:
        """
        Execute a plan by generating code for all steps, then running them sequentially.
        
        Args:
            plan: The execution plan with steps to run
            correlation_id: Optional correlation ID for tracing
            
        Returns:
            Either successful execution results or an error object
        """
        # Generate correlation ID if not provided
        if not correlation_id:
            correlation_id = self._generate_correlation_id()
            
        # Update the query ID in Okta dependencies for consistent tracing
        self.okta_deps.query_id = correlation_id
        
        start_time = time.time()
        results = {}
        entities_queried = set()
        errors = []
        
        # Log execution start with step count
        logger.info(f"[{correlation_id}] Starting execution of plan with {len(plan.steps)} steps")
        
        try:
            # PHASE 1: PREPARATION
            # Collect tool documentation and generate code
            tool_docs_start = time.time()
            tool_docs, queried_entities = self._collect_tool_documentation(plan, correlation_id)
            entities_queried.update(queried_entities)
            tool_docs_time = time.time() - tool_docs_start
            
            logger.debug(f"[{correlation_id}] Collected tool documentation in {tool_docs_time:.2f}s")
            
            # Generate code for all steps
            code_gen_start = time.time()
            code_generation_result, gen_error = await safe_execute_async(
                self._generate_code_for_steps,
                plan,
                tool_docs,
                correlation_id,
                error_message="Failed to generate code for execution plan"
            )
            code_gen_time = time.time() - code_gen_start
            
            if gen_error:
                logger.error(f"[{correlation_id}] Code generation failed after {code_gen_time:.2f}s: {gen_error}")
                return gen_error
            
            logger.info(f"[{correlation_id}] Generated code for {len(plan.steps)} steps in {code_gen_time:.2f}s")    
            step_codes = code_generation_result
            
            # PHASE 2: EXECUTION
            # Execute each step and collect results
            step_context = {}
            
            for i, (step, code) in enumerate(zip(plan.steps, step_codes)):
                step_number = i + 1
                step_correlation_id = f"{correlation_id}-s{step_number}"
                
                # Log step start with correlation ID
                #logger.info(f"[{step_correlation_id}] Executing step {step_number}/{len(plan.steps)}: {step.tool_name}")
                
                # Execute and process this step
                step_start_time = time.time()
                step_result, step_exec_error = await safe_execute_async(
                    self._execute_step,
                    step=step,
                    code=code,
                    step_number=step_number,
                    step_context=step_context, 
                    total_steps=len(plan.steps),
                    correlation_id=step_correlation_id,
                    error_message=f"Failed to execute step {step_number}: {step.tool_name}"
                )
                step_time = time.time() - step_start_time
                
                # Check if step execution itself failed (not the step logic but our code)
                if step_exec_error:
                    logger.warning(f"[{step_correlation_id}] Step execution failed after {step_time:.2f}s: {format_error_for_user(step_exec_error)}")
                    
                    if step.critical:
                        return step_exec_error
                    
                    # Non-critical step, add error and continue
                    entity_type = self._get_entity_type(step.tool_name)
                    errors.append(StepError(
                        step=step.tool_name,
                        error=format_error_for_user(step_exec_error),
                        critical=step.critical,
                        entity_type=entity_type,
                        step_number=step_number
                    ))
                    continue
                
                # Update tracking variables based on step result
                entity_type = self._get_entity_type(step.tool_name)
                entities_queried.add(entity_type)
                
                # Check for critical errors that should halt execution
                if isinstance(step_result, BaseError):
                    logger.error(f"[{step_correlation_id}] Critical step error after {step_time:.2f}s: {step_result}")
                    return step_result
                
                # Unpack the execution results
                result_data, step_vars, step_error = step_result
                
                # Store results and update context for next steps
                results[step.tool_name] = result_data
                if step_vars:
                    step_context.update(step_vars)
                
                # Track errors if any occurred
                if step_error:
                    logger.warning(f"[{step_correlation_id}] Step completed with errors in {step_time:.2f}s: {step_error.error}")
                    errors.append(step_error)
                else:
                    # Log successful completion with timing
                    result_summary = self._get_result_summary(result_data)
                    logger.info(f"[{step_correlation_id}] Step completed in {step_time:.2f}s: {result_summary}")
            
            # PHASE 3: RESULT PROCESSING
            # Process final result and create response
            final_result = self._process_final_result(results, plan)
            status = "success" if not errors else "partial_success"
            execution_time_ms = int((time.time() - start_time) * 1000)
            
            # Log execution completion with stats
            error_count = len(errors)
            success_steps = len(results) - error_count
            logger.info(
                f"[{correlation_id}] Execution completed in {execution_time_ms}ms: "
                f"{success_steps}/{len(plan.steps)} steps successful"
            )
            
            return ExecutionResult(
                results=results,
                entities_queried=list(entities_queried),
                errors=errors if errors else None,
                final_result=final_result,
                status=status,
                execution_time_ms=execution_time_ms,
                correlation_id=correlation_id,
                metadata={
                    "steps_completed": len(results),
                    "steps_total": len(plan.steps),
                    "has_errors": len(errors) > 0,
                    "execution_time_ms": execution_time_ms,
                    "code_generation_time_ms": int(code_gen_time * 1000)
                }
            )
            
        except Exception as e:
            # Convert to our error framework
            elapsed_time = time.time() - start_time
            error = ExecutionError(
                message="Error executing plan",
                original_exception=e,
                context={"plan_steps": len(plan.steps) if plan else 0}
            )
            logger.error(f"[{correlation_id}] Execution failed after {elapsed_time:.2f}s: {str(e)}")
            error.log()
            return error
    
    def _collect_tool_documentation(self, plan: ExecutionPlan, correlation_id: str) -> Tuple[List[str], Set[str]]:
        """
        Collect documentation for all tools in the plan.
        
        Args:
            plan: The execution plan
            correlation_id: Correlation ID for tracing
            
        Returns:
            Tuple of (tool_docs, queried_entities)
        """
        logger.info(f"[{correlation_id}] Collecting tool documentation for {len(plan.steps)} steps")
        
        tool_docs = []
        queried_entities = set()
        
        for i, step in enumerate(plan.steps):
            # Get tool documentation
            tool_doc = self._get_tool_prompt(step.tool_name)
            tool_docs.append(tool_doc)
            
            # Track entity type if documentation was found
            if tool_doc:
                entity_type = self._get_entity_type(step.tool_name)
                if entity_type != "unknown":
                    queried_entities.add(entity_type)
            else:
                logger.warning(f"[{correlation_id}] No documentation found for tool: {step.tool_name} (step {i+1})")
        
        return tool_docs, queried_entities
    
    async def _generate_code_for_steps(
        self, plan: ExecutionPlan, tool_docs: List[str], correlation_id: str
    ) -> Union[List[str], BaseError]:
        """
        Generate code for all steps in the plan.
        
        Args:
            plan: The execution plan
            tool_docs: Documentation for each tool
            correlation_id: Correlation ID for tracing
            
        Returns:
            Either list of step codes or an error
        """
        logger.info(f"[{correlation_id}] Generating code for workflow with {len(plan.steps)} steps")
        
        # Use the coding agent to generate all step code
        code_generation = await coding_agent.generate_workflow_code(
            plan, 
            tool_docs, 
            flow_id=correlation_id
        )
        
        # Log the raw response at debug level only
        logger.debug(f"[{correlation_id}] Workflow Code Generation Response:\n%s", code_generation.raw_response)
        
        # Check for generation errors
        if hasattr(code_generation, 'metadata') and code_generation.metadata.get('error'):
            error = code_generation.metadata.get('error')
            logger.error(f"[{correlation_id}] Code generation failed: {error}")
            raise ExecutionError(
                message=f"Code generation failed",
                step_name="code_generation",
                context={"error_details": error}
            )
        
        # Log code generation success with stats
        step_codes = code_generation.step_codes
        total_lines = sum(len(code.split('\n')) for code in step_codes)
        logger.info(f"[{correlation_id}] Generated {total_lines} lines of code across {len(step_codes)} steps")
        
        return step_codes
    
    async def _execute_step(
            self,
            step: PlanStep,
            code: str,
            step_number: int,
            step_context: Dict[str, Any],
            total_steps: int,
            correlation_id: str
        ) -> Union[Tuple[Dict[str, Any], Dict[str, Any], Optional[StepError]], BaseError]:
            """
            Execute a single step of the plan.
            
            Args:
                step: The plan step to execute
                code: Generated code for this step
                step_number: Current step number (1-based)
                step_context: Context variables from previous steps
                total_steps: Total number of steps in plan
                correlation_id: Correlation ID for this step
                
            Returns:
                Either tuple of (step_result, variables, error) or BaseError for critical failures
            """
            logger.info(f"[{correlation_id}] Executing step {step_number}/{total_steps}: {step.tool_name}")
            
            # Count lines of code for metrics
            code_lines = len([line for line in code.split('\n') if line.strip()])
            logger.debug(f"[{correlation_id}] Executing {code_lines} lines of code")
            
            # Display code being executed
            self._print_step_info(step_number, step.tool_name, code)
            
            # Get entity type for this tool
            entity_type = self._get_entity_type(step.tool_name)
            
            # Define the pagination helper function that will be available in the execution context
            async def paginate_results(method_name, method_args=None, query_params=None, entity_name="items"):
                """
                Helper function to handle pagination for Okta API calls.
                
                Args:
                    method_name: Name of the client method to call (like "list_users")
                    method_args: Optional list of positional arguments for the method
                    query_params: Optional dict of query parameters
                    entity_name: Name of the entity being paginated ("users", "groups", etc.)
                    
                Returns:
                    List of all items across all pages or an error dict
                """
                # Get the method from the client by name
                method = getattr(self.okta_deps.client, method_name)
                
                # Build kwargs dict for the method
                method_kwargs = {}
                
                # Check if this method accepts query_params by inspecting its signature
                import inspect
                sig = inspect.signature(method)
                accepts_query_params = 'query_params' in sig.parameters
                
                # Only add query_params if the method accepts them and they're provided
                if accepts_query_params and query_params:
                    method_kwargs["query_params"] = query_params
                
                # Call the imported pagination utility with the actual method
                try:
                    return await _base_paginate_results(
                        method,
                        method_args=method_args,
                        method_kwargs=method_kwargs,
                        entity_name=entity_name,
                        flow_id=correlation_id
                    )
                except Exception as e:
                    logger.error(f"[{correlation_id}] Error in pagination: {str(e)}")
                    return {"status": "error", "error": f"Error during pagination: {str(e)}"}
            
            # Execute the code with current context and pagination helper
            execution_start = time.time()
            execution_result, exec_error = await safe_execute_async(
                execute_okta_code,
                code,
                self.okta_deps.client,
                self.okta_deps.domain,
                correlation_id,  # Pass correlation ID to code execution
                extra_context={
                    **step_context,
                    'paginate_results': paginate_results  # Add pagination helper to context
                },
                error_message=f"Error executing code for step {step.tool_name}"
            )
            execution_time = time.time() - execution_start
            
            # Handle execution errors
            if exec_error:
                error_msg = format_error_for_user(exec_error)
                logger.warning(f"[{correlation_id}] Step execution failed after {execution_time:.2f}s: {error_msg}")
                logger.error(f"Error in step {step_number}: {error_msg}")
                
                # Create error object
                step_error = StepError(
                    step=step.tool_name,
                    error=error_msg,
                    critical=step.critical,
                    entity_type=entity_type,
                    step_number=step_number
                )
                
                # If critical step failed, return error to halt execution
                if step.critical:
                    return ExecutionError(
                        message=f"Critical step failed: {step.tool_name}",
                        step_name=step.tool_name,
                        context={
                            "step_number": step_number,
                            "error_details": error_msg,
                            "entity_type": entity_type,
                            "execution_time_ms": int(execution_time * 1000)
                        },
                        severity=ErrorSeverity.ERROR
                    )
                
                # For non-critical steps, return empty result with error
                return {}, {}, step_error
            
            # Check if result indicates an error
            step_error = None
            if is_error_result(execution_result.get('result')):
                error_msg = self._extract_error_message(execution_result)
                logger.warning(f"[{correlation_id}] Step returned error after {execution_time:.2f}s: {error_msg}")
                logger.error(f"Error in step {step_number}: {error_msg}")
                
                # Create error object
                step_error = StepError(
                    step=step.tool_name,
                    error=error_msg,
                    critical=step.critical,
                    entity_type=entity_type,
                    step_number=step_number
                )
                
                # If critical step failed, return error to halt execution
                if step.critical:
                    return ExecutionError(
                        message=f"Critical step failed: {step.tool_name}",
                        step_name=step.tool_name,
                        context={
                            "step_number": step_number,
                            "error_details": error_msg,
                            "entity_type": entity_type
                        },
                        severity=ErrorSeverity.ERROR
                    )
            else:
                # Step succeeded
                result_summary = self._get_result_summary(execution_result.get('result'))
                logger.info(f"[{correlation_id}] Step completed in {execution_time:.2f}s: {result_summary}")
                
                # Display intermediate result
                self._print_intermediate_result(execution_result.get('result'))
            
            # Extract variables for next steps
            variables = execution_result.get('variables', {})
            
            # Log variables at debug level
            if variables:
                logger.debug(f"[{correlation_id}] Variables after step {step_number}:")
                for var_name, var_value in variables.items():
                    var_preview = str(var_value)[:80] + ('...' if len(str(var_value)) > 80 else '')
                    logger.debug(f"[{correlation_id}]   {var_name}: {var_preview}")
            
            return execution_result, variables, step_error
    
    def _print_step_info(self, step_number: int, tool_name: str, code: str) -> None:
        """Print information about the current step."""
        logger.info(f"\nStep {step_number}: {tool_name}")
        logger.debug("-" * 60)
        logger.debug(code)
        logger.debug("-" * 60)
    
    def _print_intermediate_result(self, result: Any) -> None:
        """Print intermediate result from a step."""
        if result:
            logger.debug(f"\nIntermediate result:")
            if isinstance(result, (dict, list)):
                # Truncate long JSON output
                result_json = json.dumps(result, indent=2, default=str)
                if len(result_json) > 500:
                    logger.debug(result_json[:500] + "\n... (truncated)")
                else:
                    logger.debug(result_json)
            else:
                logger.debug(result)
    
    def _get_tool_prompt(self, tool_name: str) -> Optional[str]:
        """Get documentation prompt for a specific tool from the registry."""
        prompt = get_tool_prompt(tool_name)
        if not prompt:
            logger.warning(f"Documentation not found for tool: {tool_name}")
        return prompt
    
    def _get_entity_type(self, tool_name: str) -> str:
        """
        Get the entity type for a tool based on tool registry.
        
        Args:
            tool_name: Name of the tool
            
        Returns:
            Entity type or "unknown" if not found
        """
        # Check the exact name first for efficiency
        if tool_name in self._tool_entity_map:
            return self._tool_entity_map[tool_name]
            
        # Try normalizing the name for more flexible matching
        normalized_name = tool_name.lower().replace("_", "").replace(" ", "")
        for name, entity_type in self._tool_entity_map.items():
            if name.lower().replace("_", "").replace(" ", "") == normalized_name:
                return entity_type
                
        # Fallback to unknown if not found
        logger.warning(f"Entity type not found for tool: {tool_name}")
        return "unknown"
    
    def _get_result_summary(self, result: Any) -> str:
        """Generate a summary of the result for logging."""
        if not result:
            return "No result returned"
            
        # Handle common result patterns
        if isinstance(result, list):
            return f"Retrieved {len(result)} items"
            
        if isinstance(result, dict):
            # Handle error status
            if "status" in result and result["status"] in ERROR_STATUSES:
                return f"Error: {result.get('error', 'Unknown error')}"
            
            # Look for list data in the result using common patterns
            for key, value in result.items():
                if isinstance(value, list):
                    # Use the key name to make the summary more descriptive
                    entity_name = key.lower()
                    # Remove common prefixes/suffixes for cleaner output
                    for prefix in ['get_', 'list_', '_list', '_data']:
                        entity_name = entity_name.replace(prefix, '')
                    
                    # Format the entity name for output
                    if entity_name.endswith('s'):
                        # Already plural
                        return f"Retrieved {len(value)} {entity_name}"
                    else:
                        # Make singular keys plural for readability
                        return f"Retrieved {len(value)} {entity_name}s"
            
            # If we found no lists but have a data field
            if "data" in result:
                if result["data"] is None:
                    return "No data returned"
                elif isinstance(result["data"], dict):
                    return f"Retrieved data object with {len(result['data'])} fields"
                else:
                    return f"Retrieved data ({type(result['data']).__name__})"
                    
            return f"Retrieved result with {len(result)} fields"
            
        return f"Operation completed successfully ({type(result).__name__})"
    
    def _extract_error_message(self, execution_result: Dict[str, Any]) -> str:
        """
        Extract a human-readable error message from an execution result.
        
        Args:
            execution_result: Result from code execution
            
        Returns:
            Extracted error message
        """
        # Get the result data
        if not execution_result or 'result' not in execution_result:
            return "Unknown error (no result data)"
            
        result = execution_result['result']
        
        # Handle different error formats
        if isinstance(result, dict):
            # Direct error message
            if 'error' in result:
                return str(result['error'])
            
            # User-friendly message
            if 'message' in result:
                return str(result['message'])
                
            # Status with no message
            if 'status' in result and result['status'] in ERROR_STATUSES:
                return f"Operation failed with status: {result['status']}"
        
        # If there's a top-level error key
        if 'error' in execution_result:
            return str(execution_result['error'])
                
        # Fallback message
        return "Unknown error (could not extract specific message)"
    
    def _process_final_result(self, results: Dict[str, Any], plan: ExecutionPlan) -> Any:
        """
        Process results from all steps to create a final result.
        By default, returns the result of the last step.
        
        Args:
            results: Results from all executed steps
            plan: The original execution plan
            
        Returns:
            Final processed result
        """
        # Try to get the result of the last successful step
        for step in reversed(plan.steps):
            if step.tool_name in results:
                step_result = results[step.tool_name]
                if isinstance(step_result, dict) and 'result' in step_result:
                    if not is_error_result(step_result['result']):
                        return step_result['result']
        
        # If we didn't find a valid result, return empty dict
        return {}
    
    def format_result_for_output(self, execution_result: ExecutionResult) -> Dict[str, Any]:
        """
        Format the execution result for API or CLI output.
        
        Args:
            execution_result: Raw execution result
            
        Returns:
            Formatted result for presentation
        """
        # Start with the final result as the main output
        output = {
            "data": execution_result.final_result,
            "metadata": {
                "status": execution_result.status,
                "entities_queried": execution_result.entities_queried,
                "step_count": execution_result.metadata.get("steps_completed", 0),
                "execution_time_ms": execution_result.execution_time_ms,
                "timestamp": datetime.now().isoformat(),
                "correlation_id": execution_result.correlation_id
            }
        }
        
        # Add error information if present
        if execution_result.errors:
            output["errors"] = [
                {
                    "step": err.step,
                    "step_number": err.step_number,
                    "message": err.error, 
                    "entity_type": err.entity_type,
                    "critical": err.critical
                }
                for err in execution_result.errors
            ]
            
        return output
    
    async def debug_execution(
        self, 
        query: str, 
        correlation_id: str
    ) -> Dict[str, Any]:
        """
        Capture detailed execution steps for debugging
        
        This method is prepared for future use with more advanced debugging
        but currently just returns basic execution info.
        
        Args:
            query: The user query to debug
            correlation_id: Correlation ID for tracing
            
        Returns:
            Dictionary with debugging information
        """
        debug_info = {
            "query": query,
            "correlation_id": correlation_id,
            "timestamp": datetime.now().isoformat(),
            "execution_path": []
        }
        
        # In the future, we could use capture_run_messages here
        # For now, just return the basic structure
        return debug_info    
    
    async def execute_with_diagnostics(
        self, 
        plan, 
        correlation_id: str,
        enable_advanced_diagnostics: bool = False
    ):
        """
        Execute a plan with extra diagnostics information
        
        Args:
            plan: The execution plan to follow
            correlation_id: Correlation ID for tracing
            enable_advanced_diagnostics: If True, collect detailed diagnostics (may affect performance)
            
        Returns:
            Execution results with added diagnostics
        """
        # Start with normal execution
        results = await self.execute(plan, correlation_id)
        
        # Add placeholder for advanced diagnostics that could be enabled in the future
        if enable_advanced_diagnostics:
            # This is where we would use capture_run_messages in the future
            results["diagnostics"] = {
                "message_count": "Not currently enabled",
                "token_usage": "Not currently enabled",
                "potential_issues": []
            }
        
        return results     