"""
Realtime Hybrid Execution Router - Modern Execution Manager Integration

This module replaces the legacy realtime execution system with the Modern Execution Manager
while maintaining full SSE streaming compatibility and API contracts.

Key Features:
- Modern Execution Manager integration for robust execution
- SSE (Server-Sent Events) streaming for real-time updates
- User-friendly step display names
- Enhanced error handling and database health checking
- Full API contract preservation for frontend compatibility
"""

import asyncio
import os
import uuid
import json
import re
import time
from enum import Enum
from typing import Dict, Any, AsyncGenerator, List, Optional, Callable, Tuple, Union

from fastapi import APIRouter, HTTPException, Request, Depends, Body, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from html_sanitizer import Sanitizer

# --- Modern Execution Manager Imports ---
from src.core.orchestration.modern_execution_manager import ModernExecutionManager
from src.core.agents.planning_agent import planning_agent, PlanningDependencies, ExecutionPlan, ExecutionStep

# --- Project-specific Imports ---
from src.core.security.dependencies import get_current_user, get_db_session
from src.core.okta.sync.models import AuthUser, UserRole
from sqlalchemy.ext.asyncio import AsyncSession

from src.utils.error_handling import BaseError, format_error_for_user
from src.utils.logging import get_logger, set_correlation_id
from src.utils.tool_registry import build_tools_documentation

logger = get_logger(__name__)

# --- Query sanitization (same as legacy) ---
custom_sanitizer = Sanitizer({
    'tags': ('__nonexistent_tag__',),
    'attributes': {},
    'empty': set(),
    'separate': set()
})

def sanitize_query(query: str) -> Tuple[str, List[str]]:
    """Natural language-aware query sanitization"""
    if not query:
        return "", []
        
    warnings = []
    
    # Convert to string if not already
    query = str(query)
    
    # Limit length to prevent DoS
    if len(query) > 2000:
        query = query[:2000]
        warnings.append("Query truncated due to excessive length")
        
    # Control character removal
    original_length = len(query)
    query = re.sub(r'[\x00-\x08\x0B-\x1F\x7F]', '', query)
    if len(query) != original_length:
        warnings.append("Control characters removed from query")
    
    # Detect suspicious patterns
    suspicious_patterns = [
        (r'```.*?```', "code block"),
        (r'<\s*script\b[^>]*>', "script tag"),
        (r'javascript\s*:', "JavaScript protocol"),
        (r'(?i)(?:select|insert|update|delete|drop|alter|create)\s+(?:from|into|table|database)', "SQL-like syntax"),
        (r'\{\{.*?\}\}', "template expression"),
        (r'\$\{.*?\}', "expression injection"),
        (r'`.*?`', "command backticks"),
        (r'\$\(.*?\)', "command substitution")
    ]
    
    for pattern, description in suspicious_patterns:
        matches = re.findall(pattern, query, re.DOTALL | re.IGNORECASE)
        if matches:
            match_preview = matches[0][:20] + "..." if len(matches[0]) > 20 else matches[0]
            warnings.append(f"Suspicious {description} detected: '{match_preview}'")
    
    sanitized_query = custom_sanitizer.sanitize(query)
    sanitized_query = re.sub(r'data\s*:\s*\w+/\w+\s*;\s*base64', 'data-removed', sanitized_query, flags=re.IGNORECASE)
    
    return sanitized_query.strip(), warnings

# --- Process Status Enum (same as legacy) ---
class ProcessStatus(str, Enum):  
    IDLE = "idle"
    PLAN_GENERATION = "plan_generation"
    PLAN_GENERATED = "plan_generated"
    RUNNING_EXECUTION = "running_execution"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    CANCELLED = "cancelled"
    ERROR = "error"
    UNKNOWN = "unknown"

# --- API Pydantic Models (same as legacy) ---
class ApiStep(BaseModel):
    id: int
    tool_name: str
    query_context: Dict[str, Any] = {}
    reason: str = ""
    critical: bool = False
    status: str = "pending"
    code: Optional[str] = None
    result_summary: Optional[str] = None
    error_message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

class ApiPlan(BaseModel):
    original_query: str
    reasoning: str
    confidence: Optional[float] = None
    steps: List[ApiStep]

class StartProcessResponse(BaseModel):
    process_id: str
    plan: ApiPlan

class RealtimeQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, description="The natural language query for the realtime agent.")

router = APIRouter()

active_processes: Dict[str, Any] = {}
MAX_PROCESS_AGE_SECONDS = 3600  # 1 hour

# Global modern execution manager instance
modern_executor = ModernExecutionManager()

async def cleanup_old_processes():
    """Periodically cleans up old process data."""
    while True:
        await asyncio.sleep(600)  # Run every 10 minutes
        now = time.time()
        expired_keys = [
            pid for pid, data in list(active_processes.items()) # Iterate over a copy
            if now - data.get("timestamp", 0) > MAX_PROCESS_AGE_SECONDS
        ]
        for key in expired_keys:
            logger.info(f"Cleaning up expired process data for process_id: {key}")
            active_processes.pop(key, None)

@router.on_event("startup")
async def startup_event():
    asyncio.create_task(cleanup_old_processes())

def get_step_display_name(tool_name: str, entity: Optional[str] = None) -> str:
    """
    Map backend tool names to user-friendly display names.
    
    Args:
        tool_name: The backend tool name (e.g., "api", "sql")
        entity: The entity being operated on (e.g., "users", "groups")
    
    Returns:
        User-friendly display name for the frontend
    """
    if not entity:
        return tool_name
        
    display_mapping = {
        "api": entity,  # "users", "groups", "system_log", etc.
        "sql": f"sql_{entity}",  # "sql_users", "sql_groups", etc.
    }
    
    return display_mapping.get(tool_name, tool_name)

def _map_modern_step_to_api_step(modern_step: ExecutionStep, index: int) -> ApiStep:
    """Map Modern Execution Manager step to API step format"""
    # Extract entity from query_context if available
    entity = None
    if hasattr(modern_step, 'entity'):
        entity = modern_step.entity
    elif hasattr(modern_step, 'query_context') and isinstance(modern_step.query_context, dict):
        entity = modern_step.query_context.get('entity')
    
    # Get user-friendly display name
    display_name = get_step_display_name(modern_step.tool_name, entity)
    
    # Handle query_context properly
    api_query_context_for_model: Dict[str, Any] = {}
    if hasattr(modern_step, 'query_context'):
        raw_query_context = modern_step.query_context
        if isinstance(raw_query_context, dict):
            api_query_context_for_model = raw_query_context
        elif raw_query_context is not None:
            logger.warning(
                f"Step {index} ('{display_name}'): "
                f"query_context is of type '{type(raw_query_context)}' (value: '{raw_query_context}'), "
                f"but ApiStep.query_context expects a dictionary. Using empty dictionary."
            )
    
    return ApiStep(
        id=index,
        tool_name=display_name,  # Use display name instead of raw tool name
        query_context=api_query_context_for_model,
        reason=getattr(modern_step, 'reason', ''),
        critical=getattr(modern_step, 'critical', False),
        status="pending"
    )

async def generate_plan_with_modern_manager(query: str, process_id: str, user: AuthUser | None) -> tuple[ApiPlan, ExecutionPlan]:
    """Generate execution plan using Modern Execution Manager's planning agent"""
    logger.info(f"[{process_id}] Generating plan with Modern Execution Manager for query: \"{query}\"")
    set_correlation_id(process_id)

    try:
        # Check database health before planning
        if not modern_executor._check_database_health():
            raise ValueError("Database connectivity issues detected. Please try again later.")
        
        # Create planning dependencies
        planning_deps = PlanningDependencies(
            available_entities=modern_executor.available_entities,
            entity_summary=modern_executor.entity_summary,
            sql_tables=modern_executor.sql_tables
        )
        
        # Use the modern planning agent
        agent_response = await planning_agent.run(query, deps=planning_deps)
        execution_plan = agent_response.data
        
        if not execution_plan or not hasattr(execution_plan, 'steps') or not execution_plan.steps:
            logger.error(f"[{process_id}] Planning agent returned invalid plan structure: {execution_plan}")
            raise ValueError("Execution plan structure from planning agent is invalid or empty.")

        # Map to API format for frontend compatibility
        api_steps = []
        for i, step in enumerate(execution_plan.steps):
            api_steps.append(_map_modern_step_to_api_step(step, i))

        api_plan = ApiPlan(
            original_query=query,
            reasoning=execution_plan.reasoning,
            confidence=getattr(execution_plan, 'confidence', None),
            steps=api_steps
        )
        
        return api_plan, execution_plan

    except Exception as e:
        logger.error(f"[{process_id}] Failed to generate plan with Modern Execution Manager: {e}", exc_info=True)
        user_message = format_error_for_user(e) if isinstance(e, BaseError) else "Failed to generate execution plan due to an internal error."
        raise HTTPException(status_code=500, detail=user_message)

async def execute_plan_and_stream(
    process_id: str,
    query: str,
    execution_plan: ExecutionPlan,
    user: AuthUser | None
) -> AsyncGenerator[Dict[str, str], None]:
    """
    Execute plan using Modern Execution Manager and stream SSE events.
    
    This function wraps the Modern Execution Manager's execute_steps method
    and converts its results to SSE events that the frontend expects.
    """
    global active_processes
    set_correlation_id(process_id)
    logger.info(f"[{process_id}] Starting Modern Execution Manager execution for query: \"{query}\"")

    def check_cancellation() -> bool:
        """Check if the process has been cancelled"""
        proc_data = active_processes.get(process_id)
        cancelled_by_status = proc_data.get("status") == ProcessStatus.CANCELLED if proc_data else False
        explicitly_cancelled_flag = proc_data.get("cancelled", False) if proc_data else True
        
        cancelled = cancelled_by_status or explicitly_cancelled_flag
        if cancelled:
            logger.info(f"[{process_id}] Cancellation detected")
            # Add to Modern Execution Manager's cancellation set
            modern_executor.cancelled_queries.add(process_id)
        return cancelled

    try:
        if process_id not in active_processes:
            logger.error(f"[{process_id}] Process data missing at execution start. Aborting.")
            yield {
                "event": "plan_error",
                "data": json.dumps({'process_id': process_id, 'status': ProcessStatus.ERROR.value, 'message': 'Internal error: Process data lost before execution.'})
            }
            await asyncio.sleep(0.01)
            return

        # Update status to running
        active_processes[process_id]["status"] = ProcessStatus.RUNNING_EXECUTION
        yield {
            "event": "plan_status",
            "data": json.dumps({
                'process_id': process_id,
                'status': ProcessStatus.RUNNING_EXECUTION.value,
                'message': 'Execution starting with Modern Execution Manager'
            })
        }
        await asyncio.sleep(0.01)

        # Execute the plan using Modern Execution Manager
        logger.info(f"[{process_id}] Calling Modern Execution Manager execute_steps")
        execution_results = await modern_executor.execute_steps(execution_plan, process_id)
        
        # Check for cancellation after execution
        if check_cancellation():
            active_processes[process_id]["status"] = ProcessStatus.CANCELLED
            yield {
                "event": "plan_cancelled",
                "data": json.dumps({'process_id': process_id, 'status': ProcessStatus.CANCELLED.value, 'message': 'Execution cancelled.'})
            }
            await asyncio.sleep(0.01)
            return

        # Process execution results and send appropriate SSE events
        if execution_results.failed_steps > 0:
            # Some steps failed
            active_processes[process_id]["status"] = ProcessStatus.COMPLETED_WITH_ERRORS
            
            # Send step status updates for failed steps
            for step_result in execution_results.steps:
                if not step_result.success:
                    yield {
                        "event": "step_status_update",
                        "data": json.dumps({
                            'process_id': process_id,
                            'step_index': step_result.step_number - 1,  # Convert to 0-based index
                            'status': 'error',
                            'operation_status': 'error',
                            'error_message': step_result.error or 'Step execution failed'
                        })
                    }
                    await asyncio.sleep(0.01)
            
            # Send error event
            error_message = f"Execution completed with {execution_results.failed_steps} failed steps"
            yield {
                "event": "plan_error",
                "data": json.dumps({
                    'process_id': process_id,
                    'status': ProcessStatus.COMPLETED_WITH_ERRORS.value,
                    'message': error_message
                })
            }
            await asyncio.sleep(0.01)
            
        else:
            # All steps successful
            active_processes[process_id]["status"] = ProcessStatus.COMPLETED
            
            # Send step completion updates
            for step_result in execution_results.steps:
                yield {
                    "event": "step_status_update",
                    "data": json.dumps({
                        'process_id': process_id,
                        'step_index': step_result.step_number - 1,  # Convert to 0-based index
                        'status': 'completed',
                        'operation_status': 'completed',
                        'result_summary': f'Step {step_result.step_number} completed successfully'
                    })
                }
                await asyncio.sleep(0.01)
            
            # Send final result
            final_result_data = {
                'process_id': process_id,
                'status': ProcessStatus.COMPLETED.value,
                'result_content': execution_results.final_result or "Execution completed successfully",
                'display_type': 'markdown',  # Default display type
                'message': f'Successfully executed {execution_results.successful_steps}/{execution_results.total_steps} steps'
            }
            
            # Store final result in process data
            active_processes[process_id]["final_result_data"] = final_result_data
            
            yield {
                "event": "final_result",
                "data": json.dumps(final_result_data)
            }
            await asyncio.sleep(0.01)

    except Exception as e:
        logger.error(f"[{process_id}] Error during Modern Execution Manager execution: {e}", exc_info=True)
        
        if process_id in active_processes:
            active_processes[process_id]["status"] = ProcessStatus.ERROR
            error_detail = format_error_for_user(e) if isinstance(e, BaseError) else "An unexpected error occurred during execution."
            active_processes[process_id]["error_message"] = error_detail
        else:
            error_detail = "Critical error: Process context lost during exception."
        
        try:
            yield {
                "event": "plan_error",
                "data": json.dumps({'process_id': process_id, 'status': ProcessStatus.ERROR.value, 'message': error_detail})
            }
            await asyncio.sleep(0.01)
        except Exception as send_err:
            logger.error(f"[{process_id}] Failed to send plan_error SSE event: {send_err}")
    
    finally:
        final_status = active_processes.get(process_id, {}).get('status', ProcessStatus.UNKNOWN)
        logger.info(f"[{process_id}] Modern Execution Manager streaming ended. Final status: {final_status.value if isinstance(final_status, Enum) else final_status}")

@router.post("/start-process", response_model=StartProcessResponse)
async def start_realtime_process_endpoint(
    request: Request,
    payload: RealtimeQueryRequest,
    current_user: AuthUser = Depends(get_current_user)  
):
    """Start a new realtime process with Modern Execution Manager"""
    process_id = str(uuid.uuid4())
    username = current_user.username if current_user and hasattr(current_user, 'username') else "dev_user"
    set_correlation_id(process_id)

    logger.info(f"[{process_id}] [/start-process] Modern Execution Manager request for query: \"{payload.query}\" by user: {username}")

    # Sanitize query
    sanitized_query, warnings = sanitize_query(payload.query)
    
    # Log security warnings
    if warnings:
        client_ip = request.client.host if request.client else "unknown"
        logger.warning(f"Security warnings for query from user {current_user.id} (IP {client_ip}): {', '.join(warnings)}")

    # Generate plan using Modern Execution Manager
    api_plan_response, execution_plan = await generate_plan_with_modern_manager(sanitized_query, process_id, current_user)

    # Store process data
    active_processes[process_id] = {
        "process_id": process_id,
        "query": sanitized_query,
        "user_id": username,
        "api_plan_for_initial_response": api_plan_response.model_dump(),
        "execution_plan": execution_plan,  # Store the Modern Execution Manager plan
        "status": ProcessStatus.PLAN_GENERATED,
        "cancelled": False,
        "timestamp": time.time(),
        "error_message": None,
        "final_result_data": None
    }

    logger.info(f"[{process_id}] [/start-process] Plan generated with Modern Execution Manager")
    return StartProcessResponse(process_id=process_id, plan=api_plan_response)

@router.get("/stream-updates/{process_id}")
async def stream_realtime_updates_endpoint(
    process_id: str,
    request: Request,
    current_user: AuthUser = Depends(get_current_user)
):
    """Stream execution updates using Modern Execution Manager"""
    set_correlation_id(process_id)

    if process_id not in active_processes:
        logger.warning(f"[{process_id}] [/stream-updates] Process not found or session expired.")
        async def not_found_generator():
            yield {
                "event": "plan_error",
                "data": json.dumps({'process_id': process_id, 'status': 'error', 'message': 'Process not found or session expired.'})
            }
            await asyncio.sleep(0.01)
        return EventSourceResponse(not_found_generator())

    process_info = active_processes[process_id]
    current_process_status = process_info.get("status")
    user_id_for_logging = process_info.get("user_id", "unknown_user")

    logger.info(f"[{process_id}] [/stream-updates] Modern Execution Manager connection by {user_id_for_logging}. Status: {current_process_status}")

    # Handle terminal states
    terminal_statuses = [
        ProcessStatus.COMPLETED, ProcessStatus.COMPLETED_WITH_ERRORS,
        ProcessStatus.ERROR, ProcessStatus.CANCELLED
    ]
    if current_process_status in terminal_statuses:
        logger.info(f"[{process_id}] Process in terminal state: {current_process_status}")
        async def terminal_status_generator():
            event_to_send = {"process_id": process_id}
            event_name = "generic_status"

            if current_process_status == ProcessStatus.ERROR:
                event_name = "plan_error"
                event_to_send.update({
                    'status': 'error',
                    'message': process_info.get("error_message", "Process previously ended in error.")
                })
            elif current_process_status == ProcessStatus.CANCELLED:
                event_name = "plan_cancelled"
                event_to_send['message'] = 'Process was previously cancelled.'
            else:
                event_name = "final_result"
                final_data = process_info.get("final_result_data", {})
                if isinstance(final_data, dict):
                    event_to_send.update(final_data)
                else:
                    event_to_send['result_content'] = str(final_data) if final_data is not None else "No result available."
                
                # Ensure standard fields
                if "status" not in event_to_send: 
                    event_to_send["status"] = current_process_status.value
                if "message" not in event_to_send: 
                    event_to_send["message"] = "Process previously completed."
                if "display_type" not in event_to_send: 
                    event_to_send["display_type"] = "markdown"

            yield {"event": event_name, "data": json.dumps(event_to_send)}
            await asyncio.sleep(0.01)
        return EventSourceResponse(terminal_status_generator())

    # Handle running state (reconnection)
    if current_process_status == ProcessStatus.RUNNING_EXECUTION:
        logger.warning(f"[{process_id}] Client reconnected to running execution")
        async def already_running_generator():
            yield {
                "event": "plan_status",
                "data": json.dumps({
                    'process_id': process_id,
                    'status': 'reconnected_to_running',
                    'message': 'Reconnected to ongoing Modern Execution Manager execution.'
                })
            }
            await asyncio.sleep(0.01)
        return EventSourceResponse(already_running_generator())

    # Validate ready to execute
    if current_process_status != ProcessStatus.PLAN_GENERATED:
        logger.warning(f"[{process_id}] Invalid status for streaming: {current_process_status}")
        async def invalid_status_generator():
            yield {
                "event": "plan_error",
                "data": json.dumps({'process_id': process_id, 'status': 'error', 'message': f'Process cannot be streamed. Current state: {current_process_status}'})
            }
            await asyncio.sleep(0.01)
        return EventSourceResponse(invalid_status_generator())

    # Check for pre-cancellation
    if process_info.get("cancelled", False):
        logger.info(f"[{process_id}] Process cancelled before execution stream started.")
        active_processes[process_id]["status"] = ProcessStatus.CANCELLED
        async def cancelled_generator():
            yield {
                "event": "plan_cancelled",
                "data": json.dumps({'process_id': process_id, 'message': 'Process was cancelled before execution started.'})
            }
            await asyncio.sleep(0.01)
        return EventSourceResponse(cancelled_generator())

    # Start execution with Modern Execution Manager
    logger.info(f"[{process_id}] Starting Modern Execution Manager execution stream")

    execution_plan = process_info.get("execution_plan")
    query = process_info.get("query", "N/A")

    if not execution_plan:
        logger.error(f"[{process_id}] No execution plan found for Modern Execution Manager")
        active_processes[process_id]["status"] = ProcessStatus.ERROR
        active_processes[process_id]["error_message"] = 'Internal error: Execution plan not found.'
        async def plan_error_generator():
            yield {
                "event": "plan_error",
                "data": json.dumps({'process_id': process_id, 'status': 'error', 'message': active_processes[process_id]["error_message"]})
            }
            await asyncio.sleep(0.01)
        return EventSourceResponse(plan_error_generator())

    # Create the event generator
    event_generator = execute_plan_and_stream(
        process_id,
        query,
        execution_plan,
        current_user
    )
    return EventSourceResponse(event_generator)

@router.post("/cancel/{process_id}", status_code=200)
async def cancel_realtime_process_endpoint(
    process_id: str,
    current_user: AuthUser = Depends(get_current_user) 
):
    """Cancel a realtime process (compatible with Modern Execution Manager)"""
    set_correlation_id(process_id)
    if process_id not in active_processes:
        logger.warning(f"[{process_id}] [/cancel] Process not found for cancellation.")
        raise HTTPException(status_code=404, detail="Process not found.")

    process_info = active_processes[process_id]
    username = current_user.username if current_user and hasattr(current_user, 'username') else "dev_user"
    current_status = process_info.get("status")

    terminal_statuses_for_cancel_check = [
        ProcessStatus.COMPLETED, ProcessStatus.COMPLETED_WITH_ERRORS,
        ProcessStatus.CANCELLED, ProcessStatus.ERROR, ProcessStatus.UNKNOWN
    ]
    if current_status in terminal_statuses_for_cancel_check:
        msg = f"Process {process_id} is already in terminal state: {current_status}"
        logger.info(f"[{process_id}] [/cancel] {msg}")
        return JSONResponse(content={"message": msg, "status": current_status.value}, status_code=200)

    logger.info(f"[{process_id}] [/cancel] Cancellation requested by {username}. Status: {current_status}")
    
    # Set cancellation flags
    active_processes[process_id]["cancelled"] = True
    modern_executor.cancelled_queries.add(process_id)  # Add to Modern Execution Manager cancellation set
    
    if current_status == ProcessStatus.PLAN_GENERATED or current_status == ProcessStatus.PLAN_GENERATION:
        active_processes[process_id]["status"] = ProcessStatus.CANCELLED
        logger.info(f"[{process_id}] Process marked as cancelled in '{current_status}' state")

    return {"message": f"Cancellation signal sent for process {process_id} using Modern Execution Manager"}

@router.get("/available-tools")
async def get_available_tools(
    current_user: AuthUser = Depends(get_current_user) 
):
    """Retrieve all available tools from the Modern Execution Manager."""
    tools_json_str = build_tools_documentation()
    tools_list = json.loads(tools_json_str)
    
    tools_list.sort(key=lambda x: (x.get("category", ""), x["tool_name"]))
    
    return {
        "tools_count": len(tools_list),
        "tools": tools_list,
        "execution_engine": "Modern Execution Manager"
    }
