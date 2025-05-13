"""
Execution Manager for Okta AI Agent.

This module handles the execution of plans created by the Reasoning Agent:
- Fetches tool documentation from registry
- Generates code for all steps using the Coding Agent
- Executes each step securely
- Tracks results and manages error handling
- Processes results for optimal display with Results Processor
- Provides structured output for the final response
"""

from typing import Dict, List, Any, Optional, Union, Set, Tuple
import json
import traceback
import time
import uuid
from datetime import datetime
import sys
import asyncio
from pydantic import BaseModel, Field
# Add these imports at the top
from pydantic_ai import capture_run_messages
from datetime import datetime
from typing import Dict, List, Any, Optional, Union, Set, Tuple, Callable, AsyncGenerator
from src.utils.pagination_limits import paginate_results as _base_paginate_results, handle_single_entity_request as _base_handle_single_entity_request, make_async_request, normalize_okta_response
from src.core.realtime.tools.specialized_tools.user_app_access import can_user_access_application


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

# Import results processor agent
from src.core.realtime.agents.results_processor_agent import results_processor

# Tool registry imports
from src.utils.tool_registry import get_tool_prompt, get_all_tools

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
    display_type: Optional[str] = Field(default=None, description="Suggested display format (markdown, table, combined)")
    display_hints: Optional[Dict[str, Any]] = Field(default=None, description="Display hints for frontend rendering")


class ExecutionManager:
    """
    Manages the execution of plans created by the Coordinator Agent.
    
    Responsibilities:
    1. Generate Okta SDK code for all steps in one go
    2. Securely execute generated code with validation
    3. Manage results and handle errors
    4. Process results for optimal display format
    5. Provide aggregated, structured responses
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
        #logger.debug(f"[{correlation_id}] Initialized tool entity map with {len(self._tool_entity_map)} entries")
    
    def _generate_correlation_id(self) -> str:
        """Generate a unique correlation ID for tracing execution."""
        return f"exec-{str(uuid.uuid4())[:8]}"
    
    async def execute_plan(self, plan: ExecutionPlan, query: str = None, correlation_id: str = None) -> Union[ExecutionResult, BaseError]:
        """
        Execute a plan by generating code for all steps, then running them sequentially.
        
        Args:
            plan: The execution plan with steps to run
            query: The original user query (for results processing)
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
                results[str(step_number)] = result_data
                
                # In _execute_step after unpacking step_result:
                if isinstance(result_data, dict) and 'result' in result_data:
                    step_context["result"] = result_data['result']  # Unwrap the inner result
                else:
                    step_context["result"] = result_data  # Keep as is if not nested
                

                #logger.debug(f"[{correlation_id}] Setting result in step_context: {type(result_data).__name__}, value: {result_data}")
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
            final_result, display_type, display_hints = await self._process_results(results, plan, query, correlation_id)
            
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
                display_type=display_type,
                display_hints=display_hints,
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

    async def async_execute_plan_streaming(
        self,
        plan_model: ExecutionPlan, # This is the ExecutionPlan model from reasoning_agent
        query: str,
        correlation_id: str, # This is the process_id from realtime.py
        cancellation_callback: Callable[[], bool],
        # plan_confidence was passed from realtime.py in previous suggestions,
        # but it's already correctly derived from plan_model.confidence inside this method.
        # So, no need to pass it as a separate argument if plan_model is always ExecutionPlan.
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Executes a plan by generating code, running steps sequentially, and processing results,
        yielding events for each stage to be streamed via SSE.
        """
        self.okta_deps.query_id = correlation_id # For consistent tracing in OktaRealtimeDeps
        start_time = time.time()
        
        step_results_for_processing: Dict[str, Any] = {} 
        all_step_errors: List[StepError] = [] 

        if not plan_model or not hasattr(plan_model, 'steps'):
            logger.error(f"[{correlation_id}] Invalid plan structure: 'plan_model.steps' is missing. Plan: {plan_model}")
            yield {
                "event_type": "plan_error",
                "data": {OPERATION_STATUS_FIELD: "error", "message": "Invalid plan structure received for execution."}
            }
            await asyncio.sleep(0.01) # ADDED SLEEP
            return
        
        actual_steps = plan_model.steps 
        plan_reasoning = plan_model.reasoning if hasattr(plan_model, 'reasoning') else "No reasoning provided."
        plan_confidence = plan_model.confidence if hasattr(plan_model, 'confidence') else None


        if not actual_steps: 
            logger.warning(f"[{correlation_id}] Plan has no steps to execute for query: \"{query}\"")
            yield {
                "event_type": "plan_status",
                "data": {
                    "status": "completed_no_steps",
                    "message": "Plan generated with no executable steps.",
                    "plan_details": {
                        "original_query": query,
                        "reasoning": plan_reasoning,
                        "confidence": plan_confidence, 
                        "steps_summary": []
                    }
                }
            }
            await asyncio.sleep(0.01) # ADDED SLEEP
            yield { 
                "event_type": "final_result",
                "data": {
                    "status": "completed_no_steps",
                    "message": "Plan execution finished: No steps to execute.",
                    "result_content": "No actions were taken as the plan had no steps.",
                    "display_type": "markdown",
                    "display_hints": {},
                    "errors": None,
                    "execution_time_ms": int((time.time() - start_time) * 1000),
                    "metadata": {
                        "steps_total": 0,
                        "errors_count": 0,
                    }
                }
            }
            await asyncio.sleep(0.01) # ADDED SLEEP
            return

        logger.info(f"[{correlation_id}] Starting STREAMING execution of plan with {len(actual_steps)} steps for query: \"{query}\"")
        
        initial_plan_steps_summary = []
        for i, step_obj in enumerate(actual_steps): 
            initial_plan_steps_summary.append({
                "step_index": i,
                "tool_name": getattr(step_obj, 'tool_name', 'UnknownTool'),
                "reason": getattr(step_obj, 'reason', ''),
                "critical": getattr(step_obj, 'critical', False),
                "query_context": getattr(step_obj, 'query_context', {})
            })

        yield {
            "event_type": "plan_status",
            "data": {
                "status": "starting_execution",
                "message": f"Starting execution of plan with {len(actual_steps)} steps.",
                "plan_details": { 
                    "original_query": query,
                    "reasoning": plan_reasoning, 
                    "confidence": plan_confidence, 
                    "steps_summary": initial_plan_steps_summary
                }
            }
        }
        await asyncio.sleep(0.01) # ADDED SLEEP

        try:
            if cancellation_callback():
                yield {"event_type": "plan_cancelled", "data": {"message": "Execution cancelled before tool documentation."}}
                await asyncio.sleep(0.01) # ADDED SLEEP
                return

            yield {"event_type": "phase_update", "data": {"phase": "collecting_tool_docs", "message": "Collecting tool documentation..."}}
            await asyncio.sleep(0.01) # ADDED SLEEP
            tool_docs_start_time = time.time()
            tool_docs, queried_entities = self._collect_tool_documentation(plan_model, correlation_id)
            logger.debug(f"[{correlation_id}] Collected tool documentation in {time.time() - tool_docs_start_time:.2f}s")
            yield {
                "event_type": "tool_docs_collected", 
                "data": {
                    "num_tools": len(actual_steps), 
                    "queried_entities": list(queried_entities),
                    "message": "Tool documentation collected."
                }
            }
            await asyncio.sleep(0.01) # ADDED SLEEP

            if cancellation_callback():
                yield {"event_type": "plan_cancelled", "data": {"message": "Execution cancelled before code generation."}}
                await asyncio.sleep(0.01) # ADDED SLEEP
                return

            yield {"event_type": "phase_update", "data": {"phase": "generating_code", "message": "Generating code for steps..."}}
            await asyncio.sleep(0.01) # ADDED SLEEP
            code_gen_start_time = time.time()
            code_generation_result, gen_error = await safe_execute_async(
                self._generate_code_for_steps,
                plan_model, 
                tool_docs,
                correlation_id,
                error_message="Failed to generate code for execution plan"
            )
            code_gen_duration = time.time() - code_gen_start_time

            if gen_error:
                logger.error(f"[{correlation_id}] Code generation failed: {gen_error}")
                yield {
                    "event_type": "plan_error",
                    "data": {
                        OPERATION_STATUS_FIELD: "error",
                        "message": "Code generation failed.",
                        "details": format_error_for_user(gen_error)
                    }
                }
                await asyncio.sleep(0.01) # ADDED SLEEP
                return 

            step_codes = code_generation_result 
            logger.info(f"[{correlation_id}] Generated code for {len(actual_steps)} steps in {code_gen_duration:.2f}s")
            yield {
                "event_type": "code_generation_complete",
                "data": {
                    "num_steps_with_code": len(step_codes) if step_codes else 0,
                    "message": "Code generation completed successfully."
                }
            }
            await asyncio.sleep(0.01) # ADDED SLEEP
            
            if not step_codes or len(step_codes) != len(actual_steps):
                logger.error(f"[{correlation_id}] Mismatch between number of steps and generated codes. Steps: {len(actual_steps)}, Codes: {len(step_codes) if step_codes else 0}")
                yield {
                    "event_type": "plan_error",
                    "data": {
                        OPERATION_STATUS_FIELD: "error",
                        "message": "Code generation resulted in an incorrect number of code blocks.",
                    }
                }
                await asyncio.sleep(0.01) # ADDED SLEEP
                return

            step_context = {} 

            for i, (step_model_obj, code_for_step) in enumerate(zip(actual_steps, step_codes)): 
                step_index = i 
                step_number_display = i + 1 
                step_correlation_id = f"{correlation_id}-s{step_number_display}"

                if cancellation_callback():
                    yield {"event_type": "plan_cancelled", "data": {"message": f"Execution cancelled before step {step_number_display}."}}
                    await asyncio.sleep(0.01) # ADDED SLEEP
                    return

                current_tool_name = getattr(step_model_obj, 'tool_name', 'UnknownTool')
                is_critical_step = getattr(step_model_obj, 'critical', False)

                yield {
                    "event_type": "step_status_update",
                    "data": {
                        "step_index": step_index,
                        "tool_name": current_tool_name,
                        "status": "running",
                        "message": f"Executing step {step_number_display}: {current_tool_name}",
                        "code_snippet": code_for_step.split('\n')[0] + "..." if code_for_step else "N/A"
                    }
                }
                await asyncio.sleep(0.01) # ADDED SLEEP
                
                step_exec_start_time = time.time()
                step_execution_outcome, step_exec_error_obj = await safe_execute_async(
                    self._execute_step,
                    step=step_model_obj, 
                    code=code_for_step,
                    step_number=step_number_display,
                    step_context=step_context,
                    total_steps=len(actual_steps),
                    correlation_id=step_correlation_id,
                    error_message=f"Failed to execute step {step_number_display}: {current_tool_name}"
                )
                step_exec_duration = time.time() - step_exec_start_time

                if step_exec_error_obj: 
                    logger.warning(f"[{step_correlation_id}] Step {step_number_display} infrastructure execution failed: {format_error_for_user(step_exec_error_obj)}")
                    yield {
                        "event_type": "step_status_update",
                        "data": {
                            "step_index": step_index, "tool_name": current_tool_name, OPERATION_STATUS_FIELD: "error",
                            "error_message": f"Execution infrastructure error: {format_error_for_user(step_exec_error_obj)}",
                            "details": {"critical": is_critical_step}
                        }
                    }
                    await asyncio.sleep(0.01) # ADDED SLEEP
                    if is_critical_step:
                        yield {"event_type": "plan_error", "data": {OPERATION_STATUS_FIELD: "error", "message": f"Critical step {step_number_display} infrastructure failed.", "details": format_error_for_user(step_exec_error_obj)}}
                        await asyncio.sleep(0.01) # ADDED SLEEP
                        return
                    all_step_errors.append(StepError(step=current_tool_name, error=format_error_for_user(step_exec_error_obj), critical=is_critical_step, entity_type=self._get_entity_type(current_tool_name), step_number=step_number_display))
                    continue 

                if isinstance(step_execution_outcome, BaseError):
                    critical_step_error_msg = format_error_for_user(step_execution_outcome)
                    logger.error(f"[{step_correlation_id}] Critical error in step {step_number_display} logic: {critical_step_error_msg}")
                    yield {
                        "event_type": "step_status_update",
                        "data": {
                            "step_index": step_index, "tool_name": current_tool_name, OPERATION_STATUS_FIELD: "error",
                            "error_message": critical_step_error_msg,
                            "details": {"critical": True, "error_type": step_execution_outcome.__class__.__name__}
                        }
                    }
                    await asyncio.sleep(0.01) # ADDED SLEEP
                    yield {"event_type": "plan_error", "data": {OPERATION_STATUS_FIELD: "error", "message": f"Critical step {step_number_display} logic failed.", "details": critical_step_error_msg}}
                    await asyncio.sleep(0.01) # ADDED SLEEP
                    return 

                step_result_data_wrapper, new_vars_from_step, non_critical_step_error_obj = step_execution_outcome
                
                step_results_for_processing[str(step_number_display)] = step_result_data_wrapper.get('result') if isinstance(step_result_data_wrapper, dict) else step_result_data_wrapper

                if new_vars_from_step:
                    step_context.update(new_vars_from_step)

                if non_critical_step_error_obj:
                    logger.warning(f"[{step_correlation_id}] Step {step_number_display} completed with non-critical error: {non_critical_step_error_obj.error}")
                    all_step_errors.append(non_critical_step_error_obj)
                    yield {
                        "event_type": "step_status_update",
                        "data": {
                            "step_index": step_index, "tool_name": current_tool_name, "status": "completed_with_error",
                            "error_message": non_critical_step_error_obj.error,
                            "result_summary": self._get_result_summary(step_results_for_processing.get(str(step_number_display))),
                            "details": {"critical": False}
                        }
                    }
                    await asyncio.sleep(0.01) # ADDED SLEEP
                else:
                    result_summary = self._get_result_summary(step_results_for_processing.get(str(step_number_display)))
                    logger.info(f"[{step_correlation_id}] Step {step_number_display} completed successfully in {step_exec_duration:.2f}s. Summary: {result_summary}")
                    yield {
                        "event_type": "step_status_update",
                        "data": {
                            "step_index": step_index, "tool_name": current_tool_name, "status": "completed",
                            "result_summary": result_summary,
                        }
                    }
                    await asyncio.sleep(0.01) # ADDED SLEEP
            
            if cancellation_callback():
                yield {"event_type": "plan_cancelled", "data": {"message": "Execution cancelled before final result processing."}}
                await asyncio.sleep(0.01) # ADDED SLEEP
                return

            yield {"event_type": "phase_update", "data": {"phase": "processing_final_results", "message": "Processing final results..."}}
            await asyncio.sleep(0.01) # ADDED SLEEP
            
            final_result_content, display_type, display_hints = await self._process_results(
                step_results_for_processing, plan_model, query, correlation_id
            )
            
            execution_time_ms = int((time.time() - start_time) * 1000)
            final_status = "completed_with_errors" if all_step_errors else "completed"

            logger.info(f"[{correlation_id}] STREAMING Execution completed. Status: {final_status}. Total time: {execution_time_ms}ms")
            
            final_errors_payload = None
            if all_step_errors:
                final_errors_payload = [err.model_dump() for err in all_step_errors]

            yield {
                "event_type": "final_result",
                "data": {
                    "status": final_status,
                    "message": "Plan execution finished.",
                    "result_content": final_result_content,
                    "display_type": display_type,
                    "display_hints": display_hints,
                    "errors": final_errors_payload, 
                    "execution_time_ms": execution_time_ms,
                    "metadata": {
                        "steps_total": len(actual_steps),
                        "errors_count": len(all_step_errors),
                    }
                }
            }
            await asyncio.sleep(0.01) # ADDED SLEEP

        except Exception as e:
            logger.error(f"[{correlation_id}] Unhandled exception during streaming execution: {e}", exc_info=True)
            error_obj = e if isinstance(e, BaseError) else ExecutionError(message="Unhandled error in streaming execution", original_exception=e)
            if hasattr(error_obj, 'log') and callable(error_obj.log):
                error_obj.log() 

            yield {
                "event_type": "plan_error",
                "data": {
                    OPERATION_STATUS_FIELD: "error",
                    "message": "An unexpected error occurred during plan execution.",
                    "details": format_error_for_user(error_obj)
                }
            }
            await asyncio.sleep(0.01) # ADDED SLEEP
        finally:
            logger.info(f"[{correlation_id}] Streaming execution flow finished or terminated.")


    async def _process_results(
        self, 
        results: Dict[str, Any], 
        plan: ExecutionPlan, 
        query: str, 
        correlation_id: str
    ) -> Tuple[Any, str, Dict[str, Any]]:
        """
        Process execution results using the Results Processor Agent.
        
        Args:
            results: Results from all steps
            plan: The execution plan
            query: Original user query
            correlation_id: Correlation ID for tracing
            
        Returns:
            Tuple of (processed_result, display_type, display_hints)
        """
        try:
            # Prepare results for processing
            results_data, is_sample, metadata = self._prepare_results_for_processor(results, correlation_id)
            
        # DEBUG: Print the complete sampled data
            if is_sample:
                try:
                    # Convert to string with pretty formatting for better readability
                    import pprint
                    sample_data_str = pprint.pformat(results_data, indent=2, depth=4)
                    logger.info(f"[{correlation_id}] FULL SAMPLED DATA: \n{sample_data_str}")
                except Exception as e:
                    logger.error(f"[{correlation_id}] Error printing sampled data: {str(e)}")
                    # Try a simpler approach if pretty printing fails
                    logger.info(f"[{correlation_id}] SAMPLED DATA KEYS: {list(results_data.keys())}")            
            
            # Log whether we're using sampled data
            log_message = "Using sampled data" if is_sample else "Using complete data"
            results_size = len(json.dumps(results_data, default=str))
            logger.info(f"[{correlation_id}] Results processing: {log_message} ({results_size} chars)")
            
            # Process the results with appropriate agent
            process_start = time.time()
            processing_result = await results_processor.process_results(
                query=query,
                results=results_data,
                original_plan=plan,
                is_sample=is_sample,
                metadata={
                    "flow_id": correlation_id,
                    "total_records": metadata.get("record_counts", {})
                }
            )
            process_time = (time.time() - process_start) * 1000
            logger.info(f"[{correlation_id}] Results processed in {process_time:.2f}ms")
            
            # Check if we got a raw AgentRunResult
            if hasattr(processing_result, 'output') and isinstance(processing_result.output, str):
                # Extract content from AgentRunResult
                output_content = processing_result.output
                
                # Extract JSON from markdown code blocks if present
                import re
                json_match = re.search(r'```json\s+(.*?)\s+```', output_content, re.DOTALL)
                
                if json_match:
                    try:
                        # Parse JSON from markdown code block
                        json_str = json_match.group(1)
                        processed_result = json.loads(json_str)
                        
                        # Extract structured content
                        final_result = processed_result.get('content', {})
                        display_type = processed_result.get('display_type', 'default')
                        display_hints = processed_result.get('metadata', {})
                        
                        return final_result, display_type, display_hints
                    except json.JSONDecodeError:
                        logger.warning(f"[{correlation_id}] Failed to parse JSON from processor output")
                
                # If we didn't find valid JSON in markdown blocks, try parsing the raw output
                try:
                    # Try parsing the entire output as JSON
                    cleaned_output = re.sub(r'```json\s+|\s+```', '', output_content)
                    processed_result = json.loads(cleaned_output)
                    
                    # Extract structured content
                    final_result = processed_result.get('content', {})
                    display_type = processed_result.get('display_type', 'default')
                    display_hints = processed_result.get('metadata', {})
                    
                    return final_result, display_type, display_hints
                except json.JSONDecodeError:
                    logger.warning(f"[{correlation_id}] Failed to parse cleaned output as JSON")
                    
                # If all parsing attempts failed, return the raw output as markdown
                return output_content, "markdown", {}
                
            # Handle sampled data with processing code
            if is_sample and hasattr(processing_result, 'processing_code') and processing_result.processing_code:
                # Execute processing code with the full results
                logger.info(f"[{correlation_id}] Executing processing code for large dataset")
                processed_data = await self._execute_processor_code(
                    processing_result.processing_code,
                    results,  # Use full results
                    correlation_id
                )
                
                # Extract formatted data
                final_result = processed_data.get("content", {})
                display_type = processed_data.get("display_type", "table")
                display_hints = processed_data.get("metadata", {})
            else:
                # Use direct output from processor
                if hasattr(processing_result, 'content'):
                    # Handle properly structured response
                    final_result = processing_result.content
                    display_type = getattr(processing_result, 'display_type', 'default')
                    display_hints = getattr(processing_result, 'metadata', {})
                else:
                    # Handle unstructured response
                    final_result = processing_result
                    display_type = "default"
                    display_hints = {}
            
            return final_result, display_type, display_hints
            
        except Exception as e:
            logger.error(f"[{correlation_id}] Error processing results: {str(e)}")
            # Fall back to the last step's result
            default_result = self._get_last_step_result(results, plan)
            return default_result, "default", {}
    
    def _prepare_results_for_processor(
        self, 
        results: Dict[str, Any], 
        correlation_id: str
    ) -> Tuple[Dict[str, Any], bool, Dict[str, Any]]:
        """
        Prepare results for processing, sampling if necessary.
        
        Args:
            results: Results from all steps
            correlation_id: Correlation ID for tracing
            
        Returns:
            Tuple of (prepared_results, is_sample, metadata)
        """
        # First, serialize all data to ensure consistent types
        serialized_results = self._serialize_results(results)
        
        # Convert to JSON string to estimate size
        results_json = json.dumps(serialized_results)  # No default=str needed as already serialized
        results_size = len(results_json)
        logger.debug(f"[{correlation_id}] Total results size: {results_size} characters")
        
        # If under threshold, use complete results
        if results_size <= MAX_CHARS_FOR_FULL_RESULTS:
            logger.debug(f"[{correlation_id}] Results under threshold, using complete data")
            return serialized_results, False, {}
            
        # Otherwise, sample the results
        logger.info(f"[{correlation_id}] Results exceed threshold ({results_size} chars), sampling data")
        
        sampled_results = {}
        record_counts = {}
        
        # Sample each step's results
        for step_key, step_data in serialized_results.items():
            # Extract the result value (handle both dict with 'result' key and direct values)
            result_value = step_data.get('result') if isinstance(step_data, dict) and 'result' in step_data else step_data
            
            # Get entity name for this step based on key
            entity_name = f"step_{step_key}"
            
            # Sample the data
            sampled_value, count = self._sample_result(result_value, MAX_SAMPLES_PER_STEP)
            sampled_results[step_key] = sampled_value
            
            if count > MAX_SAMPLES_PER_STEP:
                record_counts[entity_name] = count
        
        metadata = {
            "record_counts": record_counts,
            "is_sample": True,
            "original_size": results_size
        }
        
        return sampled_results, True, metadata
    
    def _serialize_results(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert all data to serializable types, handling enums and special objects.
        
        Args:
            results: Raw results to serialize
            
        Returns:
            Dict with all values serialized to JSON-safe types
        """
        if results is None:
            return None
        
        if isinstance(results, dict):
            serialized_dict = {}
            for key, value in results.items():
                serialized_dict[key] = self._serialize_results(value)
            return serialized_dict
        
        elif isinstance(results, list):
            return [self._serialize_results(item) for item in results]
        
        elif hasattr(results, 'value') and not callable(results.value):
            # Handle enum-like objects
            return str(results.value)
        
        elif hasattr(results, '__dict__') and not isinstance(results, (str, int, float, bool, type(None))):
            # Handle custom objects by converting to dict
            return self._serialize_results(results.__dict__)
        
        else:
            # Return basic types as is
            return results
    
    def _sample_result(self, result: Any, max_samples: int) -> Tuple[Any, int]:
        """
        Sample a result value to a maximum number of items.
        
        Args:
            result: The result value to sample
            max_samples: Maximum number of items to include
            
        Returns:
            Tuple of (sampled_result, total_count)
        """
        # Handle lists - take first N items
        if isinstance(result, list):
            total_count = len(result)
            if total_count > max_samples:
                return result[:max_samples], total_count
            return result, total_count
            
        # Handle dicts with nested lists - sample each list
        if isinstance(result, dict):
            total_count = 1  # Start with 1 for the dict itself
            sampled_dict = {}
            
            for key, value in result.items():
                if isinstance(value, list):
                    list_count = len(value)
                    total_count += list_count
                    if list_count > max_samples:
                        sampled_dict[key] = value[:max_samples]
                    else:
                        sampled_dict[key] = value
                else:
                    sampled_dict[key] = value
            
            return sampled_dict, total_count
            
        # For other types, return as is
        return result, 1
    
    async def _execute_processor_code(
        self, 
        code: str, 
        all_results: Dict[str, Any], 
        correlation_id: str
    ) -> Dict[str, Any]:
        """
        Execute generated processing code on full results.
        
        Args:
            code: Generated Python code for processing
            all_results: Complete results from all steps
            correlation_id: Correlation ID for tracing
            
        Returns:
            Processed results
        """
        # Add debug logging before execution
        logger.info(f"[{correlation_id}] Preparing to execute processor code")
        logger.info(f"[{correlation_id}] all_results keys: {list(all_results.keys())}")
        
        # Debug key data structures
        for key in all_results:
            logger.info(f"[{correlation_id}] Key '{key}' type: {type(all_results[key]).__name__}")
        
        # Normalize all data structures for consistency
        processed_results = self._normalize_step_results(all_results)
        
        # Log normalized structures
        for key in processed_results:
            logger.info(f"[{correlation_id}] Normalized key '{key}' type: {type(processed_results[key]).__name__}")
            if isinstance(processed_results[key], list):
                logger.info(f"[{correlation_id}] Normalized key '{key}' has {len(processed_results[key])} items")
        
        # Prepare the code to execute - we expect this to create a 'result' variable
        # Important: No indentation for the code template string
        execution_code = f"""
# Variables with data needed for processing
full_results = all_results

# Structure documentation for reference
'''
All result keys contain normalized data with consistent structure:
- List results are always provided as lists
- Single entity results are wrapped in a list for consistent handling
- Results with a 'result' key have that value extracted
- Each step's results are stored under the step number as string key ('1', '2', etc.)
'''

# Debug info without prohibited imports
print(f"DEBUG: full_results keys: {{list(full_results.keys())}}")
for key in full_results:
    if isinstance(full_results[key], list):
        print(f"DEBUG: full_results[{{key}}] is a list with {{len(full_results[key])}} items")
    else:
        print(f"DEBUG: full_results[{{key}}] type: {{type(full_results[key]).__name__}}")

# Start of generated code
{code}
# End of generated code

# Debug the result
if 'result' in locals():
    if isinstance(result, dict):
        print(f"DEBUG: Result keys: {{list(result.keys())}}")
        if "content" in result and isinstance(result["content"], dict):
            content = result["content"]
            print(f"DEBUG: Content keys: {{list(content.keys())}}")
            if "items" in content:
                print(f"DEBUG: Items count: {{len(content['items'])}}")
                if content['items']:
                    print(f"DEBUG: First item keys: {{list(content['items'][0].keys()) if content['items'] else []}}")
            else:
                print("DEBUG: No 'items' key found in content")
    else:
        print(f"DEBUG: Result is not a dict, but a {{type(result).__name__}}")
else:
    print("DEBUG: No 'result' variable created")

# The code should have created a 'result' variable
if 'result' not in locals():
    result = {{
        "display_type": "markdown",
        "content": "*Error: Processing code did not create a 'result' variable*",
        "metadata": {{"error": "missing_result"}}
        }}
        """
        
        # Execute the code securely
        exec_result, exec_error = await safe_execute_async(
            execute_okta_code,
            execution_code,
            self.okta_deps.client,
            self.okta_deps.domain,
            correlation_id, 
            extra_context={
                'all_results': processed_results  # Use the normalized results
            },
            error_message="Error executing results processing code"
        )
        
        if exec_error:
            logger.error(f"[{correlation_id}] Results processing code execution failed: {exec_error}")
            return {
                "display_type": "markdown",
                "content": f"*Error processing results: {str(exec_error)}*",
                "metadata": {
                    "error": str(exec_error)
                }
            }
        
        # Extract the result variable from the execution context
        if isinstance(exec_result, dict) and 'result' in exec_result:
            result = exec_result['result']
            
            # Log result details for debugging
            if isinstance(result, dict):
                logger.info(f"[{correlation_id}] Result has keys: {list(result.keys())}")
                
                if "content" in result and isinstance(result["content"], dict):
                    content = result["content"]
                    logger.info(f"[{correlation_id}] Content has keys: {list(content.keys())}")
                    
                    if "items" in content:
                        item_count = len(content["items"])
                        logger.info(f"[{correlation_id}] Content has {item_count} items")
                        if item_count == 0:
                            logger.warning(f"[{correlation_id}] No items were created - possible data processing issue")
                    else:
                        logger.warning(f"[{correlation_id}] Content does not have 'items' key")
            
            # Validate the result has the required structure
            if (isinstance(result, dict) and 
                "display_type" in result and 
                "content" in result):
                return result
            else:
                logger.warning(f"[{correlation_id}] Results processing produced invalid structure")
                return {
                    "display_type": "markdown",
                    "content": "*Results processing produced invalid output structure*",
                    "metadata": {"error": "invalid_structure"}
                }
        
        # Fallback if we couldn't extract a proper result
        logger.warning(f"[{correlation_id}] Results processing did not produce a result variable")
        return {
            "display_type": "markdown", 
            "content": "*Results processing completed but did not produce a result*",
            "metadata": {"error": "missing_result"}
        }
    
    def _normalize_step_results(self, all_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize all step results to consistent structures.
        
        This ensures that regardless of how the API returned data, the processing
        code will always receive data in a consistent structure.
        
        Args:
            all_results: The raw results from execution steps
            
        Returns:
            Normalized results with consistent structure
        """
        normalized = {}
        
        for key, value in all_results.items():
            # Apply consistent normalization to ALL keys
            if isinstance(value, dict) and 'result' in value:
                # Extract result from result wrapper
                result_value = value['result']
                normalized[key] = self._normalize_result_value(result_value)
            else:
                # Apply normalization directly to the value
                normalized[key] = self._normalize_result_value(value)
        
        return normalized
    
    def _normalize_result_value(self, value: Any) -> Any:
        """
        Normalize a single result value to a consistent structure.
        
        Args:
            value: The value to normalize
            
        Returns:
            Normalized value
        """
        # Lists stay as lists
        if isinstance(value, list):
            return value
        
        # Single entity results (dicts with id, name, etc.) get wrapped in a list
        elif isinstance(value, dict):
            # If it looks like a single entity (has common entity fields)
            entity_indicators = ['id', 'name', 'login', 'profile', 'status']
            if any(indicator in value for indicator in entity_indicators):
                return [value]
            
            # If it contains a list under a key like 'items', 'data', 'users', etc.
            # Extract and return that list
            for list_key in ['items', 'data', 'users', 'groups', 'applications', 'factors']:
                if list_key in value and isinstance(value[list_key], list):
                    return value[list_key]
                    
            # Otherwise return as is
            return value
        
        # Non-dict, non-list values return as is
        return value
    
    def _get_last_step_result(self, results: Dict[str, Any], plan: ExecutionPlan) -> Any:
        """Get the result from the last successful step as fallback."""
        # Convert keys to integers for proper sorting
        step_keys = sorted([int(k) for k in results.keys() if k.isdigit()])
        if not step_keys:
            return {}
            
        # Get the last step's result
        last_key = str(step_keys[-1])
        step_result = results.get(last_key)
        
        # Extract the result value
        if isinstance(step_result, dict) and 'result' in step_result:
            return step_result['result']
        return step_result
    
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
                    return {OPERATION_STATUS_FIELD: "error", "error": f"Error during pagination: {str(e)}"}
            
            # Define the single entity request helper function
            async def handle_single_entity_request(method_name, entity_type, entity_id, method_args=None, method_kwargs=None):
                """
                Helper function to handle single entity requests for Okta API calls.
                
                Args:
                    method_name: Name of the client method to call (like "get_user")
                    entity_type: Type of entity being requested ("user", "group", etc.)
                    entity_id: ID or login of the entity
                    method_args: Optional list of positional arguments for the method
                    method_kwargs: Optional dict of keyword arguments
                    
                Returns:
                    Entity data or error dict
                """
                # Get the method from the client by name
                method = getattr(self.okta_deps.client, method_name)
                
                # Call the imported single entity request utility
                try:
                    return await _base_handle_single_entity_request(
                        method,
                        entity_type=entity_type,
                        entity_id=entity_id,
                        method_args=method_args,
                        method_kwargs=method_kwargs,
                        flow_id=correlation_id
                    )
                except Exception as e:
                    logger.error(f"[{correlation_id}] Error in single entity request: {str(e)}")
                    return {OPERATION_STATUS_FIELD: "error", "error": f"Error during entity request: {str(e)}"}
            
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
                    'paginate_results': paginate_results,  # Add pagination helper to context
                    'handle_single_entity_request': handle_single_entity_request,  # Add single entity helper
                    'make_async_request': make_async_request,  # Add async request helper
                    'can_user_access_application': can_user_access_application, # Add access check helper
                    'normalize_okta_response': normalize_okta_response  # Add normalization helper
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
                        }
                    )
                
                # For non-critical steps, return empty result with error
                return {}, {}, step_error
            
            # Check if result indicates an error
            step_error = None
            result = execution_result.get('result')
            
            # Special handling for empty lists - they are valid results, not errors
            if isinstance(result, list) and len(result) == 0:
                # Empty list is a valid result representing "no matches found"
                logger.info(f"[{correlation_id}] Step completed in {execution_time:.2f}s: No matching items found (empty result)")
                
                # Display intermediate result
                self._print_intermediate_result(result)
                
                # For critical steps, stop execution but return a friendly message
                if step.critical:
                    logger.info(f"[{correlation_id}] Critical step returned empty result - halting plan")
                    return ExecutionError(
                        message="No matching records found",
                        step_name=step.tool_name,
                        context={
                            "step_number": step_number,
                            "error_details": "No matching records found for the search criteria",
                            "entity_type": entity_type,
                            "status": "not_found"  # Special status to indicate empty result
                        }
                    )
                
                # For non-critical steps, just return the empty result normally
                return execution_result, execution_result.get('variables', {}), None
            elif isinstance(result, dict) and OPERATION_STATUS_FIELD in result and result[OPERATION_STATUS_FIELD] == "not_found":
                logger.info(f"[{correlation_id}] Step completed in {execution_time:.2f}s: Entity not found")
                
                # Display intermediate result
                self._print_intermediate_result(result)
                
                # For critical steps, stop execution but return a friendly message
                if step.critical:
                    logger.info(f"[{correlation_id}] Critical step returned not_found - halting plan")
                    return ExecutionError(
                        message=f"No matching {result.get('entity', 'record')} found",
                        step_name=step.tool_name,
                        context={
                            "step_number": step_number,
                            "error_details": f"No matching {result.get('entity', 'record')} found with ID {result.get('id', 'unknown')}",
                            "entity_type": entity_type,
                            OPERATION_STATUS_FIELD: "not_found"
                        }
                    )
                
                # For non-critical steps, just return the not_found result normally
                return execution_result, execution_result.get('variables', {}), None            
            elif is_error_result(result):
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
                # Step succeeded with non-empty result
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
        logger.info(code)
        logger.debug("-" * 60)
    
    def _print_intermediate_result(self, result: Any) -> None:
        """Print intermediate result from a step."""
        if result:
            logger.debug(f"\nIntermediate result:")
            if isinstance(result, (dict, list)):
                # Truncate long JSON output
                result_json = json.dumps(result, indent=2, default=str)
                if len(result_json) > 5000:
                    logger.debug(result_json[:5000] + "\n... (truncated)")
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
            if OPERATION_STATUS_FIELD in result and result[OPERATION_STATUS_FIELD] in ERROR_STATUSES:
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
        if OPERATION_STATUS_FIELD in result and result[OPERATION_STATUS_FIELD] in ERROR_STATUSES:
            return f"Operation failed with status: {result[OPERATION_STATUS_FIELD]}"
        
        # If there's a top-level error key
        if 'error' in execution_result:
            return str(execution_result['error'])
                
        # Fallback message
        return "Unknown error (could not extract specific message)"
    
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
            "display_type": execution_result.display_type or "default",
            "display_hints": execution_result.display_hints or {},
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
        results = await self.execute_plan(plan, correlation_id)
        
        # Add placeholder for advanced diagnostics that could be enabled in the future
        if enable_advanced_diagnostics:
            # This is where we would use capture_run_messages in the future
            results["diagnostics"] = {
                "message_count": "Not currently enabled",
                "token_usage": "Not currently enabled",
                "potential_issues": []
            }
        
        return results