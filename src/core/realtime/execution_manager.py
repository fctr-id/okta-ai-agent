from typing import Dict, List, Any, Optional, Union
import logging, json
from pydantic import BaseModel, Field

from src.core.realtime.agents.base import EntityError
from src.core.realtime.okta_realtime_client import OktaRealtimeDeps
from src.core.realtime.agents.reasoning_agent import ExecutionPlan, PlanStep, RoutingResult
from src.core.realtime.agents.coding_agent import coding_agent
from src.core.realtime.code_execution_utils import execute_okta_code
from src.config.settings import settings

# Import tool documentation modules
from src.core.realtime.tools.user_tools import get_user_tool_prompt, get_all_user_tools

logger = logging.getLogger(__name__)

class StepError(BaseModel):
    """Error information for a specific execution step."""
    step: str = Field(description="Name of the step where the error occurred")
    error: str = Field(description="Error message")
    critical: bool = Field(default=False, description="Whether this was a critical error")
    entity_type: str = Field(default="unknown", description="Type of entity involved in the error")

class ExecutionResult(BaseModel):
    """Result of executing an entire plan."""
    results: Dict[str, Any] = Field(description="Results from each executed step")
    entities_queried: List[str] = Field(description="Entity types that were queried")
    errors: Optional[List[StepError]] = Field(None, description="Errors encountered during execution")
    metadata: Dict[str, Any] = Field(description="Additional metadata about execution")
    final_result: Any = Field(default=None, description="The final processed result")
    status: str = Field(default="success", description="Overall execution status")

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
        # If no dependencies are provided, create them from settings
        if okta_deps is None:
            from src.core.realtime.okta_realtime_client import OktaRealtimeDeps
            self.okta_deps = OktaRealtimeDeps(
                domain=settings.OKTA_CLIENT_ORGURL,
                api_token=settings.OKTA_API_TOKEN,
                query_id="default"
            )
        else:
            self.okta_deps = okta_deps
            
        # Cache of tool name to entity_type mapping for faster lookups
        self._tool_entity_map = {
            tool.name: tool.entity_type for tool in get_all_user_tools()
        }
        
    async def execute_plan(self, plan: ExecutionPlan) -> Union[ExecutionResult, EntityError]:
        """Execute a plan by generating all code at once, then running each step in sequence."""
        results = {}
        entities_queried = set()
        errors = []
        
        try:
            # First, generate code for all steps at once
            logger.info(f"Generating code for all {len(plan.steps)} steps")
            
            # Collect tool documentation for all steps
            tool_docs = []
            for step in plan.steps:
                tool_docs.append(self._get_tool_prompt(step.tool_name))
            
            # Use the coding agent to generate code for all steps
            code_generation = await coding_agent.generate_workflow_code(plan, tool_docs)
            step_codes = code_generation.step_codes
            
            # Log the raw response at debug level
            logger.debug("Workflow Code Generation Response:\n%s", code_generation.raw_response)
            
            # Track variables between steps
            step_context = {}
            
            # Execute each step with its generated code
            for i, (step, code) in enumerate(zip(plan.steps, step_codes)):
                logger.info(f"Executing step {i+1}/{len(plan.steps)}: {step.tool_name}")
                
                # Print the code being executed
                print(f"\nStep {i+1}: {step.tool_name}")
                print("-" * 60)
                print(code)
                print("-" * 60)
                
                try:
                    # Look up the entity type for this tool
                    entity_type = self._tool_entity_map.get(step.tool_name, "unknown")
                    entities_queried.add(entity_type)
                    
                    # Execute the code with the current context
                    step_result = await execute_okta_code(
                        code,
                        self.okta_deps.client,
                        self.okta_deps.domain,
                        self.okta_deps.query_id,
                        extra_context=step_context
                    )
                    
                    # Check if result indicates an error
                    if self._is_error_result(step_result):
                        error_msg = self._extract_error_message(step_result)
                        errors.append(StepError(
                            step=step.tool_name,
                            error=error_msg,
                            critical=step.critical,
                            entity_type=entity_type
                        ))
                        logger.warning(f"Step {step.tool_name} returned error: {error_msg}")
                        print(f"Error in step {i+1}: {error_msg}")
                        
                        if step.critical:
                            return EntityError(
                                message=f"Critical step failed: {step.tool_name} - {error_msg}",
                                error_type="execution_error",
                                entity=entity_type
                            )
                    
                    # Store results for this step
                    results[step.tool_name] = step_result
                    
                    # Update the context with variables from this step
                    if 'variables' in step_result:
                        step_context.update(step_result['variables'])
                        # Log variables at debug level
                        logger.debug("Variables after step %d:", i+1)
                        for var_name, var_value in step_result['variables'].items():
                            logger.debug("  %s: %s", var_name, str(var_value)[:80] + ('...' if len(str(var_value)) > 80 else ''))
                    
                    # Add the primary result to the context with the step name for easy reference
                    if 'result' in step_result:
                        step_context[step.tool_name] = step_result['result']
                    
                    # Show step result
                    if step_result.get('result'):
                        print(f"\nIntermediate result:")
                        if isinstance(step_result['result'], (dict, list)):
                            print(json.dumps(step_result['result'], indent=2, default=str)[:500])
                            if len(json.dumps(step_result['result'])) > 500:
                                print("... (truncated)")
                        else:
                            print(step_result['result'])
                    
                    logger.info(f"Step {step.tool_name} completed successfully")
                    
                except Exception as e:
                    logger.error(f"Error executing step {step.tool_name}: {str(e)}")
                    error = StepError(
                        step=step.tool_name,
                        error=str(e),
                        critical=step.critical,
                        entity_type=self._tool_entity_map.get(step.tool_name, "unknown")
                    )
                    errors.append(error)
                    print(f"Error in step {i+1}: {str(e)}")
                    
                    if step.critical:
                        return EntityError(
                            message=f"Critical step failed: {step.tool_name}",
                            error_type="execution_error",
                            entity=self._tool_entity_map.get(step.tool_name, "unknown")
                        )
            
            # Process the final result
            final_result = self._process_final_result(results, plan)
            status = "success" if not errors else "partial_success"
            
            # Add the required metadata field
            return ExecutionResult(
                results=results,
                entities_queried=list(entities_queried),
                errors=errors if errors else None,
                final_result=final_result,
                status=status,
                metadata={
                    "steps_completed": len(results),
                    "steps_total": len(plan.steps),
                    "has_errors": len(errors) > 0
                }
            )
            
        except Exception as e:
            logger.error(f"Error executing plan: {str(e)}")
            return EntityError(
                message=f"Execution error: {str(e)}",
                error_type="execution_error",
                entity="unknown"
            )
            
    def _get_tool_prompt(self, tool_name: str) -> Optional[str]:
        """Get documentation prompt for a specific tool."""
        return get_user_tool_prompt(tool_name)
    
    def _get_entity_type(self, tool_name: str) -> str:
        """Get the entity type for a tool based on tool registry."""
        # Use the cached mapping with fallback to unknown
        return self._tool_entity_map.get(tool_name, "unknown")
    
    def _is_error_result(self, step_result: Dict[str, Any]) -> bool:
        """Check if a step result indicates an error."""
        # Check for standard error indicator in result
        if not step_result or 'result' not in step_result:
            return False
            
        result = step_result['result']
        
        if isinstance(result, dict) and 'status' in result:
            if result['status'] in ['error', 'not_found', 'dependency_failed']:
                return True
                
        return False
    
    def _extract_error_message(self, step_result: Dict[str, Any]) -> str:
        """Extract a human-readable error message from a step result."""
        if not step_result or 'result' not in step_result:
            return "Unknown error (no result)"
            
        result = step_result['result']
        
        if isinstance(result, dict):
            if 'error' in result:
                return str(result['error'])
            elif 'message' in result:
                return str(result['message'])
            elif 'status' in result and result['status'] in ['error', 'not_found', 'dependency_failed']:
                return f"Operation failed with status: {result['status']}"
                
        return "Unknown error (couldn't extract message)"
    
    def _process_final_result(self, results: Dict[str, Any], plan: ExecutionPlan) -> Any:
        """
        Process results from all steps to create a final result.
        By default, returns the result of the last step.
        """
        # Simple strategy: return the result of the last step that produced a result
        for step in reversed(plan.steps):
            if step.tool_name in results and 'result' in results[step.tool_name]:
                return results[step.tool_name]['result']
        
        # If no results were found, return an empty dict
        return {}
    
    def _format_result_for_output(self, execution_result: ExecutionResult) -> Dict[str, Any]:
        """Format the execution result for API output."""
        # Start with the final result as the main output
        output = {
            "data": execution_result.final_result,
            "metadata": {
                "status": execution_result.status,
                "entities_queried": execution_result.entities_queried,
                "step_count": execution_result.metadata.get("steps_completed", 0)
            }
        }
        
        # Add error information if present
        if execution_result.errors:
            output["errors"] = [
                {"step": err.step, "message": err.error, "entity_type": err.entity_type}
                for err in execution_result.errors
            ]
            
        return output