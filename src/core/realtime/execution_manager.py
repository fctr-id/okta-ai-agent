# filepath: c:\Users\Dharanidhar\Desktop\github-repos\okta-ai-agent\src\core\realtime\execution_manager.py
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

class ExecutionResult(BaseModel):
    """Result of executing an entire plan."""
    results: Dict[str, Any] = Field(description="Results from each executed step")
    entities_queried: List[str] = Field(description="Entity types that were queried")
    errors: Optional[List[str]] = Field(None, description="Errors encountered during execution")
    metadata: Dict[str, Any] = Field(description="Additional metadata about execution")

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
                    
                    # Store results for this step
                    results[step.tool_name] = step_result
                    
                    # Update the context with variables from this step
                    if 'variables' in step_result:
                        step_context.update(step_result['variables'])
                        # Log variables at debug level
                        logger.debug("Variables after step %d:", i+1)
                        for var_name, var_value in step_result['variables'].items():
                            logger.debug("  %s: %s", var_name, str(var_value)[:80] + ('...' if len(str(var_value)) > 80 else ''))
                    
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
                    errors.append({"step": step.tool_name, "error": str(e)})
                    print(f"Error in step {i+1}: {str(e)}")
                    
                    if step.critical:
                        return EntityError(
                            message=f"Critical step failed: {step.tool_name}",
                            error_type="execution_error",
                            entity=self._tool_entity_map.get(step.tool_name, "unknown")
                        )
            
            # Add the required metadata field
            return ExecutionResult(
                results=results,
                entities_queried=list(entities_queried),
                errors=errors if errors else None,
                metadata={
                    "steps_completed": len(results),
                    "steps_total": len(plan.steps)
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