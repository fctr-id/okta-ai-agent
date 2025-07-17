"""
Hybrid Execution Manager for Okta AI Agent.

This module handles the execution of hybrid SQL+API plans:
- Supports both SQL queries and API calls as steps
- Manages dependencies between SQL and API steps
- Passes data context between steps for proper data flow
- Generates code for all steps understanding the complete workflow
- Executes steps sequentially with proper error handling
- Based on the ExecutionManager pattern but adapted for hybrid workflows
"""

from typing import Dict, List, Any, Optional, Union, Set, Tuple, Callable, AsyncGenerator
import json
import traceback
import time
import uuid
import asyncio
from datetime import datetime
from pydantic import BaseModel, Field

# Import our error handling
from src.utils.error_handling import (
    BaseError, ExecutionError, ApiError, safe_execute_async,
    format_error_for_user, ErrorSeverity
)
from src.utils.logging import get_logger

# Import data layer components
# from src.data.okta_generate_sql import okta_generate_sql  # TODO: Fix import path
from src.core.model_picker import get_agent_model

# Configure logging
logger = get_logger(__name__)

# Error status constants
ERROR_STATUSES = {"error", "not_found", "dependency_failed"}
OPERATION_STATUS_FIELD = "operation_status"

# Character limit before using sampling for results processing
MAX_CHARS_FOR_FULL_RESULTS = 60000

# Number of sample items to include per step result
MAX_SAMPLES_PER_STEP = 5


class StepError(BaseModel):
    """Error information for a specific execution step."""
    step: str = Field(description="Name of the step where the error occurred")
    error: str = Field(description="Error message")
    critical: bool = Field(default=False, description="Whether this was a critical error")
    entity_type: str = Field(default="unknown", description="Type of entity involved in the error")
    step_number: int = Field(default=0, description="Step number in the plan")
    step_type: str = Field(default="unknown", description="Type of step (sql or api)")


class HybridStep(BaseModel):
    """A step in a hybrid execution plan."""
    step_type: str = Field(description="Type of step: 'sql' or 'api'")
    tool_name: str = Field(description="Name of the tool/entity to work with")
    query_context: str = Field(description="Context and instructions for this step")
    critical: bool = Field(default=True, description="Whether this step is critical for plan success")
    reason: str = Field(default="", description="Reason why this step is needed")
    dependencies: List[str] = Field(default_factory=list, description="List of step numbers this depends on")


class HybridExecutionPlan(BaseModel):
    """Execution plan for hybrid SQL+API workflows."""
    steps: List[HybridStep] = Field(description="List of steps to execute")
    reasoning: str = Field(description="Reasoning behind the plan")
    confidence: int = Field(description="Confidence level in the plan (0-100)")
    entities: List[str] = Field(description="List of entities involved")


class HybridExecutionResult(BaseModel):
    """Result of executing a hybrid plan."""
    results: Dict[str, Any] = Field(description="Results from each executed step")
    entities_queried: List[str] = Field(description="Entity types that were queried")
    errors: Optional[List[StepError]] = Field(None, description="Errors encountered during execution")
    metadata: Dict[str, Any] = Field(description="Additional metadata about execution")
    final_result: Any = Field(default=None, description="The final processed result")
    status: str = Field(default="success", description="Overall execution status")
    execution_time_ms: int = Field(default=0, description="Total execution time in milliseconds")
    correlation_id: Optional[str] = Field(default=None, description="Correlation ID for tracing")
    data_flow_summary: Dict[str, Any] = Field(default_factory=dict, description="Summary of data flow between steps")


class HybridExecutionManager:
    """
    Manages the execution of hybrid SQL+API plans.
    
    Key Features:
    1. Supports both SQL queries and API calls as first-class steps
    2. Manages data flow between steps via step_context
    3. Generates workflow-aware code understanding dependencies
    4. Executes steps sequentially with proper error handling
    5. Based on proven ExecutionManager pattern
    """
    
    def __init__(self, db_path: str = None, api_data_path: str = None, schema_path: str = None):
        """
        Initialize the hybrid execution manager.
        
        Args:
            db_path: Path to SQLite database
            api_data_path: Path to API endpoint data
            schema_path: Path to database schema
        """
        self.db_path = db_path or "sqlite_db/okta_sync.db"
        self.api_data_path = api_data_path
        self.schema_path = schema_path
        
        # Track API data for dependency resolution
        self.api_data_cache = {}
        
    def _generate_correlation_id(self) -> str:
        """Generate a unique correlation ID for tracing execution."""
        return f"hybrid-{str(uuid.uuid4())[:8]}"
    
    async def execute_hybrid_plan(
        self, 
        plan: HybridExecutionPlan, 
        query: str = None, 
        correlation_id: str = None
    ) -> Union[HybridExecutionResult, BaseError]:
        """
        Execute a hybrid plan with both SQL and API steps.
        
        Args:
            plan: The hybrid execution plan
            query: The original user query
            correlation_id: Optional correlation ID for tracing
            
        Returns:
            Either successful execution results or an error object
        """
        # Generate correlation ID if not provided
        if not correlation_id:
            correlation_id = self._generate_correlation_id()
            
        start_time = time.time()
        results = {}
        entities_queried = set()
        errors = []
        data_flow = {}
        
        # Log execution start
        logger.info(f"[{correlation_id}] Starting hybrid execution with {len(plan.steps)} steps")
        logger.info(f"[{correlation_id}] Plan reasoning: {plan.reasoning}")
        
        try:
            # PHASE 1: WORKFLOW CODE GENERATION
            # Generate code for all steps understanding their dependencies
            code_gen_start = time.time()
            step_codes, gen_error = await safe_execute_async(
                self._generate_hybrid_workflow_code,
                plan,
                query,
                correlation_id,
                error_message="Failed to generate hybrid workflow code"
            )
            code_gen_time = time.time() - code_gen_start
            
            if gen_error:
                logger.error(f"[{correlation_id}] Hybrid code generation failed: {gen_error}")
                return gen_error
            
            logger.info(f"[{correlation_id}] Generated hybrid workflow code in {code_gen_time:.2f}s")
            
            # PHASE 2: SEQUENTIAL STEP EXECUTION
            # Execute steps with proper context passing
            step_context = {"correlation_id": correlation_id}
            
            for i, (step, code) in enumerate(zip(plan.steps, step_codes)):
                step_number = i + 1
                step_correlation_id = f"{correlation_id}-s{step_number}"
                
                logger.info(f"[{step_correlation_id}] Executing {step.step_type} step: {step.tool_name}")
                
                # Execute step based on type
                step_start_time = time.time()
                if step.step_type == "sql":
                    step_result, step_vars, step_error = await self._execute_sql_step(
                        step, code, step_number, step_context, correlation_id
                    )
                elif step.step_type == "api":
                    step_result, step_vars, step_error = await self._execute_api_step(
                        step, code, step_number, step_context, correlation_id
                    )
                else:
                    step_error = StepError(
                        step=step.tool_name,
                        error=f"Unknown step type: {step.step_type}",
                        critical=step.critical,
                        entity_type=step.tool_name,
                        step_number=step_number,
                        step_type=step.step_type
                    )
                    step_result, step_vars = {}, {}
                
                step_time = time.time() - step_start_time
                
                # Handle errors
                if step_error:
                    logger.warning(f"[{step_correlation_id}] Step failed in {step_time:.2f}s: {step_error.error}")
                    errors.append(step_error)
                    
                    if step.critical:
                        logger.error(f"[{step_correlation_id}] Critical step failed, halting execution")
                        return ExecutionError(
                            message=f"Critical {step.step_type} step failed: {step.tool_name}",
                            step_name=step.tool_name,
                            context={
                                "step_number": step_number,
                                "step_type": step.step_type,
                                "error_details": step_error.error
                            }
                        )
                
                # Store results and update context
                results[str(step_number)] = step_result
                entities_queried.add(step.tool_name)
                
                # Update step context for next steps
                if isinstance(step_result, dict) and 'result' in step_result:
                    step_context["result"] = step_result['result']
                    # Also store result with step number for specific references
                    step_context[f"step_{step_number}_result"] = step_result['result']
                else:
                    step_context["result"] = step_result
                    step_context[f"step_{step_number}_result"] = step_result
                
                if step_vars:
                    step_context.update(step_vars)
                
                # Track data flow
                data_flow[f"step_{step_number}"] = {
                    "type": step.step_type,
                    "tool": step.tool_name,
                    "execution_time_ms": int(step_time * 1000),
                    "result_type": type(step_result).__name__,
                    "data_size": len(str(step_result)) if step_result else 0
                }
                
                logger.info(f"[{step_correlation_id}] Step completed in {step_time:.2f}s")
            
            # PHASE 3: RESULT PROCESSING
            # Combine and process final results
            final_result = await self._process_hybrid_results(results, plan, query, correlation_id)
            
            status = "success" if not errors else "partial_success"
            execution_time_ms = int((time.time() - start_time) * 1000)
            
            logger.info(f"[{correlation_id}] Hybrid execution completed in {execution_time_ms}ms")
            
            return HybridExecutionResult(
                results=results,
                entities_queried=list(entities_queried),
                errors=errors if errors else None,
                final_result=final_result,
                status=status,
                execution_time_ms=execution_time_ms,
                correlation_id=correlation_id,
                data_flow_summary=data_flow,
                metadata={
                    "steps_completed": len(results),
                    "steps_failed": len(errors),
                    "plan_confidence": plan.confidence,
                    "data_flow_enabled": True
                }
            )
            
        except Exception as e:
            logger.error(f"[{correlation_id}] Hybrid execution failed: {str(e)}")
            logger.error(f"[{correlation_id}] Traceback: {traceback.format_exc()}")
            return ExecutionError(
                message=f"Hybrid execution failed: {str(e)}",
                step_name="execution_manager",
                context={"error_details": str(e)}
            )
    
    async def _generate_hybrid_workflow_code(
        self, 
        plan: HybridExecutionPlan, 
        query: str, 
        correlation_id: str
    ) -> Tuple[List[str], Optional[BaseError]]:
        """
        Generate code for all steps in the hybrid workflow.
        
        This understands dependencies between SQL and API steps and generates
        code that properly handles data flow between them.
        
        Args:
            plan: The hybrid execution plan
            query: Original user query
            correlation_id: Correlation ID for tracing
            
        Returns:
            Tuple of (step_codes, error)
        """
        logger.info(f"[{correlation_id}] Generating hybrid workflow code for {len(plan.steps)} steps")
        
        try:
            # Get LLM for code generation
            llm = get_agent_model()
            
            # Build comprehensive context for code generation
            workflow_context = self._build_workflow_context(plan, query)
            
            # Generate code understanding the complete workflow
            system_prompt = f"""You are a code generator for hybrid SQL+API workflows.

Generate Python code for each step that:
1. Understands dependencies between SQL and API steps
2. Uses step_context to access data from previous steps
3. Stores results and variables for subsequent steps
4. Handles errors appropriately based on step criticality

Workflow Context:
{workflow_context}

For SQL steps:
- Use the okta_generate_sql function to generate SQL
- Pass API context if available from previous API steps
- Store result in a 'result' variable
- Extract key data into variables for next steps

For API steps:
- Use MCP tools (get_okta_user, list_okta_groups, etc.)
- Use data from previous steps via step_context
- Store result in a 'result' variable  
- Extract key data into variables for next steps

Always end each step with:
```python
# Store result and extract variables for next steps
result = {{step_result}}
variables = {{extracted_variables}}
```"""

            # Generate code for all steps
            step_codes = []
            for i, step in enumerate(plan.steps):
                step_number = i + 1
                
                user_prompt = f"""Generate code for Step {step_number}:
Type: {step.step_type}
Tool: {step.tool_name}
Context: {step.query_context}
Critical: {step.critical}
Dependencies: {step.dependencies if step.dependencies else "None"}

The code should:
1. Access previous step results via step_context
2. Execute the {step.step_type} operation for {step.tool_name}
3. Store results and variables for next steps
4. Handle errors based on criticality

Available in step_context:
- result: Result from previous step
- step_N_result: Result from specific step N
- correlation_id: Correlation ID for tracing
- Any variables extracted from previous steps"""

                # Generate code using LLM
                response = await llm.generate_text(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt
                )
                
                step_codes.append(response)
                logger.debug(f"[{correlation_id}] Generated code for step {step_number}: {len(response)} chars")
            
            return step_codes, None
            
        except Exception as e:
            logger.error(f"[{correlation_id}] Hybrid code generation failed: {str(e)}")
            return [], ExecutionError(
                message=f"Hybrid code generation failed: {str(e)}",
                step_name="code_generation",
                context={"error_details": str(e)}
            )
    
    def _build_workflow_context(self, plan: HybridExecutionPlan, query: str) -> str:
        """Build comprehensive context for workflow code generation."""
        context_parts = [
            f"Original Query: {query}",
            f"Plan Reasoning: {plan.reasoning}",
            f"Confidence: {plan.confidence}%",
            f"Entities: {', '.join(plan.entities)}",
            "",
            "Step Sequence:"
        ]
        
        for i, step in enumerate(plan.steps):
            step_number = i + 1
            context_parts.append(
                f"  Step {step_number}: {step.step_type.upper()} - {step.tool_name}"
            )
            context_parts.append(f"    Context: {step.query_context}")
            context_parts.append(f"    Critical: {step.critical}")
            if step.dependencies:
                context_parts.append(f"    Depends on: Steps {', '.join(step.dependencies)}")
            context_parts.append("")
        
        return "\n".join(context_parts)
    
    async def _execute_sql_step(
        self, 
        step: HybridStep, 
        code: str, 
        step_number: int, 
        step_context: Dict[str, Any], 
        correlation_id: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Optional[StepError]]:
        """Execute a SQL step with context from previous steps."""
        logger.info(f"[{correlation_id}] Executing SQL step: {step.tool_name}")
        
        try:
            # Prepare API context if available from previous steps
            api_context = self._extract_api_context(step_context)
            
            # TODO: Generate SQL using the enhanced SQL agent
            # sql_agent_result = await okta_generate_sql(
            #     query=step.query_context,
            #     api_context=api_context if api_context else None,
            #     correlation_id=correlation_id
            # )
            
            # Placeholder for SQL execution
            logger.warning(f"[{correlation_id}] SQL step execution not yet implemented")
            result = {
                "result": [],
                "sql_query": "-- SQL execution placeholder",
                "explanation": "SQL step execution not yet implemented",
                "record_count": 0
            }
            
            variables = {
                "sql_result": [],
                "record_count": 0
            }
            
            logger.info(f"[{correlation_id}] SQL step completed: placeholder result")
            return result, variables, None
                
        except Exception as e:
            logger.error(f"[{correlation_id}] SQL step failed: {str(e)}")
            return {}, {}, StepError(
                step=step.tool_name,
                error=f"SQL execution failed: {str(e)}",
                critical=step.critical,
                entity_type=step.tool_name,
                step_number=step_number,
                step_type="sql"
            )
    
    async def _execute_api_step(
        self, 
        step: HybridStep, 
        code: str, 
        step_number: int, 
        step_context: Dict[str, Any], 
        correlation_id: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Optional[StepError]]:
        """Execute an API step using MCP tools."""
        logger.info(f"[{correlation_id}] Executing API step: {step.tool_name}")
        
        try:
            # TODO: Execute the generated code using MCP tools
            # This would use the MCP server to make actual API calls
            # For now, return a placeholder result
            
            logger.warning(f"[{correlation_id}] API step execution not yet implemented")
            return {
                "result": [],
                "message": "API step execution not yet implemented",
                "step_type": "api",
                "tool_name": step.tool_name
            }, {}, None
            
        except Exception as e:
            logger.error(f"[{correlation_id}] API step failed: {str(e)}")
            return {}, {}, StepError(
                step=step.tool_name,
                error=f"API execution failed: {str(e)}",
                critical=step.critical,
                entity_type=step.tool_name,
                step_number=step_number,
                step_type="api"
            )
    
    def _extract_api_context(self, step_context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract API context from step_context for SQL queries."""
        # Look for API data from previous steps
        api_context = {}
        
        for key, value in step_context.items():
            if key.startswith("step_") and key.endswith("_result"):
                # This is a result from a previous step
                if isinstance(value, list) and value:
                    # Extract the data for API context
                    api_context[key] = value
        
        return api_context if api_context else None
    
    async def _process_hybrid_results(
        self, 
        results: Dict[str, Any], 
        plan: HybridExecutionPlan, 
        query: str, 
        correlation_id: str
    ) -> Dict[str, Any]:
        """Process and combine results from all hybrid steps."""
        logger.info(f"[{correlation_id}] Processing hybrid results from {len(results)} steps")
        
        # Simple result combination for now
        # TODO: Implement sophisticated result processing
        
        combined_result = {
            "summary": f"Executed {len(results)} steps successfully",
            "steps": len(results),
            "plan_reasoning": plan.reasoning,
            "entities": plan.entities,
            "step_results": results
        }
        
        # Find the last successful step result as the primary result
        if results:
            last_step_key = max(results.keys(), key=int)
            last_result = results[last_step_key]
            if isinstance(last_result, dict) and 'result' in last_result:
                combined_result["primary_result"] = last_result['result']
        
        return combined_result
    
    def format_result_for_output(self, execution_result: HybridExecutionResult) -> Dict[str, Any]:
        """Format execution result for output display."""
        return {
            "status": execution_result.status,
            "execution_time_ms": execution_result.execution_time_ms,
            "steps_completed": len(execution_result.results),
            "entities_queried": execution_result.entities_queried,
            "data_flow_summary": execution_result.data_flow_summary,
            "final_result": execution_result.final_result,
            "errors": [
                {
                    "step": error.step,
                    "error": error.error,
                    "type": error.step_type,
                    "critical": error.critical
                }
                for error in (execution_result.errors or [])
            ]
        }


# Test function to demonstrate usage
async def test_hybrid_execution():
    """Test the hybrid execution manager with a sample plan."""
    
    # Create a sample hybrid plan
    plan = HybridExecutionPlan(
        steps=[
            HybridStep(
                step_type="api",
                tool_name="system_log",
                query_context="Get user login events from last 7 days",
                critical=True,
                reason="Need login data to identify active users"
            ),
            HybridStep(
                step_type="sql",
                tool_name="users",
                query_context="Get user details and groups for users from step 1",
                critical=True,
                reason="Need user profile and group data",
                dependencies=["1"]
            )
        ],
        reasoning="API-first approach: Get login events via API, then use SQL for user details",
        confidence=85,
        entities=["system_log", "users"]
    )
    
    # Create execution manager
    manager = HybridExecutionManager()
    
    # Execute the plan
    result = await manager.execute_hybrid_plan(
        plan=plan,
        query="Find users who logged in the last 7 days and get their groups"
    )
    
    if isinstance(result, BaseError):
        print(f"❌ Execution failed: {result}")
        return result
    else:
        print(f"✅ Execution completed: {result.status}")
        print(f"📊 Steps: {len(result.results)}")
        print(f"⏱️ Time: {result.execution_time_ms}ms")
        return result


if __name__ == "__main__":
    # Run test
    asyncio.run(test_hybrid_execution())
