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
import logging
import json
import traceback
import time
from datetime import datetime
from pydantic import BaseModel, Field

from src.core.realtime.agents.base import EntityError
from src.core.realtime.okta_realtime_client import OktaRealtimeDeps
from src.core.realtime.agents.reasoning_agent import ExecutionPlan, PlanStep
from src.core.realtime.agents.coding_agent import coding_agent
from src.core.realtime.code_execution_utils import execute_okta_code, is_error_result
from src.config.settings import settings

# Tool registry imports
from src.utils.tool_registry import get_tool_prompt, get_all_tools

# Configure logging
logger = logging.getLogger(__name__)

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
        
        logger.debug(f"Initialized tool entity map with {len(self._tool_entity_map)} entries")
    
    async def execute_plan(self, plan: ExecutionPlan) -> Union[ExecutionResult, EntityError]:
        """
        Execute a plan by generating code for all steps, then running them sequentially.
        
        Args:
            plan: The execution plan with steps to run
            
        Returns:
            Either successful execution results or an error object
        """
        start_time = time.time()
        results = {}
        entities_queried = set()
        errors = []
        
        try:
            # PHASE 1: PREPARATION
            # Collect tool documentation and generate code
            tool_docs, queried_entities = self._collect_tool_documentation(plan)
            entities_queried.update(queried_entities)
            
            # Generate code for all steps
            code_generation_result = await self._generate_code_for_steps(plan, tool_docs)
            if isinstance(code_generation_result, EntityError):
                return code_generation_result
                
            step_codes = code_generation_result
            
            # PHASE 2: EXECUTION
            # Execute each step and collect results
            step_context = {}
            
            for i, (step, code) in enumerate(zip(plan.steps, step_codes)):
                step_number = i + 1
                
                # Execute and process this step
                step_result = await self._execute_step(
                    step=step,
                    code=code,
                    step_number=step_number,
                    step_context=step_context, 
                    total_steps=len(plan.steps)
                )
                
                # Update tracking variables based on step result
                entity_type = self._get_entity_type(step.tool_name)
                entities_queried.add(entity_type)
                
                # Check for critical errors that should halt execution
                if isinstance(step_result, EntityError):
                    return step_result
                
                # Unpack the execution results
                result_data, step_vars, step_error = step_result
                
                # Store results and update context for next steps
                results[step.tool_name] = result_data
                if step_vars:
                    step_context.update(step_vars)
                
                # Track errors if any occurred
                if step_error:
                    errors.append(StepError(
                        step=step.tool_name,
                        error=step_error.error,
                        critical=step.critical,
                        entity_type=entity_type,
                        step_number=step_number
                    ))
            
            # PHASE 3: RESULT PROCESSING
            # Process final result and create response
            final_result = self._process_final_result(results, plan)
            status = "success" if not errors else "partial_success"
            execution_time_ms = int((time.time() - start_time) * 1000)
            
            return ExecutionResult(
                results=results,
                entities_queried=list(entities_queried),
                errors=errors if errors else None,
                final_result=final_result,
                status=status,
                execution_time_ms=execution_time_ms,
                metadata={
                    "steps_completed": len(results),
                    "steps_total": len(plan.steps),
                    "has_errors": len(errors) > 0,
                    "execution_time_ms": execution_time_ms
                }
            )
            
        except Exception as e:
            # Log detailed error information with traceback
            logger.error(f"Error executing plan: {str(e)}")
            logger.error(traceback.format_exc())
            
            return EntityError(
                message=f"Execution error: {str(e)}",
                error_type="execution_error",
                entity="unknown"
            )
    
    def _collect_tool_documentation(self, plan: ExecutionPlan) -> Tuple[List[str], Set[str]]:
        """
        Collect documentation for all tools in the plan.
        
        Args:
            plan: The execution plan
            
        Returns:
            Tuple of (tool_docs, queried_entities)
        """
        logger.info(f"Generating code for all {len(plan.steps)} steps")
        
        tool_docs = []
        queried_entities = set()
        
        for step in plan.steps:
            # Get tool documentation
            tool_doc = self._get_tool_prompt(step.tool_name)
            tool_docs.append(tool_doc)
            
            # Track entity type if documentation was found
            if tool_doc:
                entity_type = self._get_entity_type(step.tool_name)
                if entity_type != "unknown":
                    queried_entities.add(entity_type)
        
        return tool_docs, queried_entities
    
    async def _generate_code_for_steps(
        self, plan: ExecutionPlan, tool_docs: List[str]
    ) -> Union[List[str], EntityError]:
        """
        Generate code for all steps in the plan.
        
        Args:
            plan: The execution plan
            tool_docs: Documentation for each tool
            
        Returns:
            Either list of step codes or an error
        """
        try:
            # Use the coding agent to generate all step code
            code_generation = await coding_agent.generate_workflow_code(
                plan, 
                tool_docs, 
                flow_id=self.okta_deps.query_id
            )
            
            # Log the raw response at debug level only
            logger.debug("Workflow Code Generation Response:\n%s", code_generation.raw_response)
            
            # Check for generation errors
            if hasattr(code_generation, 'metadata') and code_generation.metadata.get('error'):
                error = code_generation.metadata.get('error')
                return EntityError(
                    message=f"Code generation failed: {error}",
                    error_type="generation_error",
                    entity="code"
                )
            
            return code_generation.step_codes
            
        except Exception as e:
            logger.error(f"Error generating code: {str(e)}")
            logger.error(traceback.format_exc())
            
            return EntityError(
                message=f"Code generation failed: {str(e)}",
                error_type="generation_error",
                entity="code"
            )
    
    async def _execute_step(
        self,
        step: PlanStep,
        code: str,
        step_number: int,
        step_context: Dict[str, Any],
        total_steps: int
    ) -> Union[Tuple[Dict[str, Any], Dict[str, Any], Optional[StepError]], EntityError]:
        """
        Execute a single step of the plan.
        
        Args:
            step: The plan step to execute
            code: Generated code for this step
            step_number: Current step number (1-based)
            step_context: Context variables from previous steps
            total_steps: Total number of steps in plan
            
        Returns:
            Either tuple of (step_result, variables, error) or EntityError for critical failures
        """
        logger.info(f"Executing step {step_number}/{total_steps}: {step.tool_name}")
        
        # Display code being executed
        self._print_step_info(step_number, step.tool_name, code)
        
        try:
            # Execute the code with current context
            execution_result = await execute_okta_code(
                code,
                self.okta_deps.client,
                self.okta_deps.domain,
                self.okta_deps.query_id,
                extra_context=step_context
            )
            
            # Get entity type for this tool
            entity_type = self._get_entity_type(step.tool_name)
            
            # Check if result indicates an error
            step_error = None
            if is_error_result(execution_result.get('result')):
                error_msg = self._extract_error_message(execution_result)
                logger.warning(f"Step {step.tool_name} returned error: {error_msg}")
                print(f"Error in step {step_number}: {error_msg}")
                
                # Create error object
                step_error = StepError(
                    step=step.tool_name,
                    error=error_msg,
                    critical=step.critical,
                    entity_type=entity_type,
                    step_number=step_number
                )
                
                # If critical step failed, return EntityError to halt execution
                if step.critical:
                    return EntityError(
                        message=f"Critical step failed: {step.tool_name} - {error_msg}",
                        error_type="execution_error",
                        entity=entity_type
                    )
            else:
                # Step succeeded
                logger.info(f"Step {step.tool_name} completed successfully")
                
                # Display intermediate result
                self._print_intermediate_result(execution_result.get('result'))
                
            # Extract variables for next steps
            variables = execution_result.get('variables', {})
            
            # Log variables at debug level
            if variables:
                logger.debug(f"Variables after step {step_number}:")
                for var_name, var_value in variables.items():
                    var_preview = str(var_value)[:80] + ('...' if len(str(var_value)) > 80 else '')
                    logger.debug(f"  {var_name}: {var_preview}")
            
            return execution_result, variables, step_error
            
        except Exception as e:
            # Handle unexpected execution errors
            logger.error(f"Error executing step {step.tool_name}: {str(e)}")
            logger.error(traceback.format_exc())
            
            error_msg = str(e)
            print(f"Error in step {step_number}: {error_msg}")
            
            # For critical steps, halt execution
            if step.critical:
                return EntityError(
                    message=f"Critical step failed: {step.tool_name} - {error_msg}",
                    error_type="execution_error",
                    entity=self._get_entity_type(step.tool_name)
                )
            
            # For non-critical steps, create error object but continue
            step_error = StepError(
                step=step.tool_name,
                error=error_msg,
                critical=step.critical,
                entity_type=self._get_entity_type(step.tool_name),
                step_number=step_number
            )
            
            # Return empty result, no variables, and error
            return {}, {}, step_error
    
    def _print_step_info(self, step_number: int, tool_name: str, code: str) -> None:
        """Print information about the current step."""
        print(f"\nStep {step_number}: {tool_name}")
        print("-" * 60)
        print(code)
        print("-" * 60)
    
    def _print_intermediate_result(self, result: Any) -> None:
        """Print intermediate result from a step."""
        if result:
            print(f"\nIntermediate result:")
            if isinstance(result, (dict, list)):
                # Truncate long JSON output
                result_json = json.dumps(result, indent=2, default=str)
                if len(result_json) > 500:
                    print(result_json[:500] + "\n... (truncated)")
                else:
                    print(result_json)
            else:
                print(result)
    
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
                "timestamp": datetime.now().isoformat()
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