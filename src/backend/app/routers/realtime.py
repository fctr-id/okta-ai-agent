import asyncio
import os
import uuid
import json
import time # Added for process timestamping
from typing import Dict, Any, AsyncGenerator, List, Optional, Callable

from fastapi import APIRouter, HTTPException, Request, Depends, Body # Added Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

# --- Project-specific Imports ---
# Assuming these are the correct paths based on your project structure
from src.core.auth.dependencies import get_current_user
from src.okta_db_sync.db.models import AuthUser, UserRole

from src.core.realtime.okta_realtime_client import get_okta_realtime_deps
from src.core.realtime.agents.reasoning_agent import routing_agent, ExecutionPlan as CoreExecutionPlan, RoutingResult
from src.core.realtime.execution_manager import ExecutionManager
from src.utils.error_handling import BaseError, format_error_for_user
from src.utils.logging import get_logger, set_correlation_id
from src.utils.tool_registry import build_tools_documentation


logger = get_logger(__name__)

# --- Process Status Enum (Optional but good practice) ---
class ProcessStatus:
    PLAN_GENERATION = "plan_generation"
    PLAN_GENERATED = "plan_generated"
    RUNNING_EXECUTION = "running_execution"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    CANCELLED = "cancelled"
    ERROR = "error"
    UNKNOWN = "unknown"


# --- API Pydantic Models ---
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

async def get_current_user_dev_optional(request: Request) -> AuthUser | None:
    if os.getenv("APP_ENV", "production").lower() == "development":
        logger.info("Development mode - Skipping authentication.")
        return AuthUser(
            id=-1,
            username="dev_user",
            password_hash="dummy_password_hash_not_for_prod",
            role=UserRole.ADMIN,
            is_active=True,
        )
    # Ensure get_current_user is awaitable if it does async operations
    user = await get_current_user(request=request)
    return user


active_processes: Dict[str, Any] = {}
MAX_PROCESS_AGE_SECONDS = 3600  # 1 hour

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


def sanitize_realtime_query(query: str) -> str:
    logger.debug(f"Sanitizing query (currently placeholder): {query}")
    return query

def _map_core_step_to_api_step(core_step_obj: Any, index: int) -> ApiStep:
    raw_query_context = getattr(core_step_obj, 'query_context', None)
    api_query_context_for_model: Dict[str, Any] = {}

    if isinstance(raw_query_context, dict):
        api_query_context_for_model = raw_query_context
    elif raw_query_context is not None:
        logger.warning(
            f"Step {index} ('{getattr(core_step_obj, 'tool_name', 'UnknownTool')}'): "
            f"core_step_obj.query_context is of type '{type(raw_query_context)}' (value: '{raw_query_context}'), "
            f"but ApiStep.query_context expects a dictionary. "
            f"Using an empty dictionary for ApiStep.query_context. "
            f"The original value will be used by the execution backend."
        )
    return ApiStep(
        id=index,
        tool_name=getattr(core_step_obj, 'tool_name', 'UnknownTool'),
        query_context=api_query_context_for_model,
        reason=getattr(core_step_obj, 'reason', ''),
        critical=getattr(core_step_obj, 'critical', False),
        status="pending"
    )

async def generate_and_map_plan(query: str, process_id: str, user: AuthUser | None) -> tuple[ApiPlan, CoreExecutionPlan]:
    logger.info(f"[{process_id}] Generating plan for query: \"{query}\"")
    set_correlation_id(process_id) # Ensure correlation ID is set

    try:
        # Assuming routing_agent.run is an async method
        agent_response = await routing_agent.run(query)
        routing_result_obj: RoutingResult = agent_response.output

        if not routing_result_obj or not hasattr(routing_result_obj, 'plan') or not routing_result_obj.plan:
            logger.error(f"[{process_id}] routing_agent returned an unexpected plan structure: {routing_result_obj}")
            raise ValueError("Execution plan structure from routing_agent is invalid or empty.")

        core_execution_plan_for_manager: CoreExecutionPlan = routing_result_obj.plan

        api_steps = []
        for i, step_obj in enumerate(core_execution_plan_for_manager.steps):
            api_steps.append(_map_core_step_to_api_step(step_obj, i))

        api_plan = ApiPlan(
            original_query=query,
            reasoning=core_execution_plan_for_manager.reasoning,
            confidence=getattr(routing_result_obj, 'confidence', None),
            steps=api_steps
        )
        return api_plan, core_execution_plan_for_manager

    except Exception as e:
        logger.error(f"[{process_id}] Failed to generate and map plan: {e}", exc_info=True)
        user_message = format_error_for_user(e) if isinstance(e, BaseError) else "Failed to generate execution plan due to an internal error."
        raise HTTPException(status_code=500, detail=user_message)


async def run_execution_and_stream(
    process_id: str,
    query: str,
    actual_core_execution_plan: CoreExecutionPlan,
    user: AuthUser | None
) -> AsyncGenerator[Dict[str, str], None]: # MODIFIED: Type hint to Dict[str, str]
    global active_processes
    set_correlation_id(process_id)
    logger.info(f"[{process_id}] Starting execution stream for query: \"{query}\"")

    def check_cancellation() -> bool:
        proc_data = active_processes.get(process_id)
        cancelled = proc_data.get("cancelled", False) if proc_data else True
        if cancelled:
            logger.info(f"[{process_id}] Cancellation flag checked: True")
        return cancelled

    okta_deps = None
    try:
        if process_id not in active_processes:
            logger.error(f"[{process_id}] Process data missing at the start of execution stream. Aborting.")
            yield {
                "event": "plan_error",
                "data": json.dumps({'process_id': process_id, 'status': 'error', 'message': 'Internal error: Process data lost before execution.'})
            }
            await asyncio.sleep(0.01)
            return

        active_processes[process_id]["status"] = ProcessStatus.RUNNING_EXECUTION # Use Enum value
        # MODIFIED: Yield a dictionary
        yield {
            "event": "plan_status",
            "data": json.dumps({
                'process_id': process_id,
                'status': ProcessStatus.RUNNING_EXECUTION, # Use Enum value
                'message': 'Execution of the plan is starting.'
            })
        }
        await asyncio.sleep(0.01)

        okta_deps = get_okta_realtime_deps(process_id)
        if hasattr(okta_deps, 'initialize_clients') and asyncio.iscoroutinefunction(okta_deps.initialize_clients):
            await okta_deps.initialize_clients()

        execution_manager = ExecutionManager(okta_deps=okta_deps)

        async for event_dict_from_manager in execution_manager.async_execute_plan_streaming(
            plan_model=actual_core_execution_plan,
            query=query,
            correlation_id=process_id,
            cancellation_callback=check_cancellation
        ):
            event_type = event_dict_from_manager.get("event_type", "generic_update")
            event_data = event_dict_from_manager.get("data", {})
            if "process_id" not in event_data: # Ensure process_id is present
                 event_data["process_id"] = process_id

            logger.debug(f"[{process_id}] Yielding SSE event: {event_type}, data: {json.dumps(event_data)}")
            # MODIFIED: Yield a dictionary
            yield {
                "event": event_type,
                "data": json.dumps(event_data)
            }
            await asyncio.sleep(0.01)

            if event_type == "plan_cancelled":
                active_processes[process_id]["status"] = ProcessStatus.CANCELLED
                logger.info(f"[{process_id}] Execution stream: Plan cancelled event received.")
                break
            elif event_type == "final_result":
                final_event_status_str = event_data.get("status", ProcessStatus.COMPLETED)
                try:
                    active_processes[process_id]["status"] = ProcessStatus[final_event_status_str.upper()] if isinstance(final_event_status_str, str) else final_event_status_str
                except (KeyError, AttributeError): # Handle if status is not a valid string for Enum
                    logger.warning(f"[{process_id}] Invalid status '{final_event_status_str}' in final_result, defaulting to COMPLETED.")
                    active_processes[process_id]["status"] = ProcessStatus.COMPLETED
                active_processes[process_id]["final_result_data"] = event_data
                logger.info(f"[{process_id}] Execution stream: Final result event received. Status: {active_processes[process_id]['status']}")
                break
            elif event_type == "plan_error":
                active_processes[process_id]["status"] = ProcessStatus.ERROR
                active_processes[process_id]["error_message"] = event_data.get("message", "Unknown plan error")
                logger.info(f"[{process_id}] Execution stream: Plan error event received.")
                break

        current_process_status = active_processes.get(process_id, {}).get("status")
        terminal_statuses_for_check = [
            ProcessStatus.CANCELLED, ProcessStatus.COMPLETED,
            ProcessStatus.COMPLETED_WITH_ERRORS, ProcessStatus.ERROR
        ]
        if check_cancellation() and current_process_status not in terminal_statuses_for_check:
            active_processes[process_id]["status"] = ProcessStatus.CANCELLED
            logger.info(f"[{process_id}] Execution stream ended; process marked cancelled post-loop because flag was set.")
            # MODIFIED: Yield a dictionary
            yield {
                "event": "plan_cancelled",
                "data": json.dumps({'process_id': process_id, 'message': 'Execution cancelled post-loop.'})
            }
            await asyncio.sleep(0.01)
        elif current_process_status == ProcessStatus.RUNNING_EXECUTION:
            logger.warning(f"[{process_id}] ExecutionManager stream ended without a clear terminal status event. Marking as 'error'.")
            active_processes[process_id]["status"] = ProcessStatus.ERROR
            active_processes[process_id]["error_message"] = "Execution ended abruptly without a final status."
            # MODIFIED: Yield a dictionary
            yield {
                "event": "plan_error",
                "data": json.dumps({'process_id': process_id, 'status': 'error', 'message': active_processes[process_id]["error_message"]})
            }
            await asyncio.sleep(0.01)

    except HTTPException:
        logger.warning(f"[{process_id}] HTTPException during execution stream.", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"[{process_id}] Unhandled error during plan execution stream: {e}", exc_info=True)
        if process_id in active_processes:
            active_processes[process_id]["status"] = ProcessStatus.ERROR
            error_detail = format_error_for_user(e) if isinstance(e, BaseError) else "An unexpected error occurred during execution."
            active_processes[process_id]["error_message"] = error_detail
        else:
            error_detail = "Critical error: Process context lost during exception."
        try:
            # MODIFIED: Yield a dictionary
            yield {
                "event": "plan_error",
                "data": json.dumps({'process_id': process_id, 'status': 'error', 'message': error_detail})
            }
            await asyncio.sleep(0.01)
        except Exception as send_err:
            logger.error(f"[{process_id}] Failed to send plan_error SSE event after an exception: {send_err}")
    finally:
        final_status_in_dict = active_processes.get(process_id, {}).get('status', ProcessStatus.UNKNOWN)
        logger.info(f"[{process_id}] SSE stream processing ended for run_execution_and_stream. Final process status in dict: {final_status_in_dict}")
        if okta_deps and hasattr(okta_deps, 'close_clients') and asyncio.iscoroutinefunction(okta_deps.close_clients):
            try:
                await okta_deps.close_clients()
            except Exception as close_ex:
                logger.error(f"[{process_id}] Error closing OktaRealtimeDeps for execution: {close_ex}", exc_info=True)


@router.post("/start-process", response_model=StartProcessResponse)
async def start_realtime_process_endpoint(
    payload: RealtimeQueryRequest, # Use RealtimeQueryRequest which expects a JSON body
    current_user: AuthUser | None = Depends(get_current_user_dev_optional)
):
    process_id = str(uuid.uuid4())
    username = current_user.username if current_user and hasattr(current_user, 'username') else "dev_user"
    set_correlation_id(process_id)

    logger.info(f"[{process_id}] [/start-process] Received for query: \"{payload.query}\" by user: {username}")

    sanitized_query = sanitize_realtime_query(payload.query)
    api_plan_response, core_plan_to_execute = await generate_and_map_plan(sanitized_query, process_id, current_user)

    active_processes[process_id] = {
        "process_id": process_id, # Added for easier access
        "query": sanitized_query,
        "user_id": username, # Changed from "user" for clarity
        "api_plan_for_initial_response": api_plan_response.model_dump(),
        "core_plan_model_for_execution": core_plan_to_execute,
        "status": ProcessStatus.PLAN_GENERATED, # Use Enum
        "cancelled": False,
        "timestamp": time.time(), # Added for cleanup logic
        "error_message": None,
        "final_result_data": None
    }

    logger.info(f"[{process_id}] [/start-process] Plan generated. API Plan: {api_plan_response.model_dump(exclude_none=True)}")
    return StartProcessResponse(process_id=process_id, plan=api_plan_response)


@router.get("/stream-updates/{process_id}")
async def stream_realtime_updates_endpoint(
    process_id: str,
    request: Request,
    current_user: AuthUser | None = Depends(get_current_user_dev_optional)
):
    set_correlation_id(process_id)

    if process_id not in active_processes:
        logger.warning(f"[{process_id}] [/stream-updates] Process not found or session expired.")
        async def not_found_generator():
            # MODIFIED: Yield a dictionary
            yield {
                "event": "plan_error",
                "data": json.dumps({'process_id': process_id, 'status': 'error', 'message': 'Process not found or session expired.'})
            }
            await asyncio.sleep(0.01)
        return EventSourceResponse(not_found_generator())

    process_info = active_processes[process_id]
    current_process_status = process_info.get("status")
    user_id_for_logging = process_info.get("user_id", "unknown_user")

    logger.info(f"[{process_id}] [/stream-updates] Connection attempt by {user_id_for_logging}. Process status: {current_process_status}")

    terminal_statuses = [
        ProcessStatus.COMPLETED, ProcessStatus.COMPLETED_WITH_ERRORS,
        ProcessStatus.ERROR, ProcessStatus.CANCELLED
    ]
    if current_process_status in terminal_statuses:
        logger.info(f"[{process_id}] Process already in a terminal state: {current_process_status}. Sending final status and closing.")
        async def terminal_status_generator():
            event_to_send = {"process_id": process_id}
            event_name = "generic_status" # Default event name

            if current_process_status == ProcessStatus.ERROR:
                event_name = "plan_error"
                event_to_send.update({
                    'status': 'error',
                    'message': process_info.get("error_message", "Process previously ended in error.")
                })
            elif current_process_status == ProcessStatus.CANCELLED:
                event_name = "plan_cancelled"
                event_to_send['message'] = 'Process was previously cancelled.'
            else: # COMPLETED or COMPLETED_WITH_ERRORS
                event_name = "final_result"
                final_data = process_info.get("final_result_data", {})
                # Ensure final_data is a dict and merge, not overwrite event_to_send
                if isinstance(final_data, dict):
                    event_to_send.update(final_data)
                else: # if final_result_data was just a string or something unexpected
                    event_to_send['result_content'] = str(final_data) if final_data is not None else "No detailed result available."
                
                # Ensure standard fields are present if not in final_data
                if "status" not in event_to_send: event_to_send["status"] = current_process_status
                if "message" not in event_to_send: event_to_send["message"] = "Process previously completed."
                if "display_type" not in event_to_send: event_to_send["display_type"] = "markdown"


            # MODIFIED: Yield a dictionary
            yield {"event": event_name, "data": json.dumps(event_to_send)}
            await asyncio.sleep(0.01)
        return EventSourceResponse(terminal_status_generator())

    if current_process_status == ProcessStatus.RUNNING_EXECUTION:
        logger.warning(f"[{process_id}] Client reconnected to an already running execution. Robust reconnect not fully implemented. Sending current status.")
        async def already_running_generator():
            # MODIFIED: Yield a dictionary
            yield {
                "event": "plan_status",
                "data": json.dumps({
                    'process_id': process_id,
                    'status': 'reconnected_to_running',
                    'message': 'Reconnected to an ongoing execution. Event history may be incomplete. Prior events will not be re-sent.'
                })
            }
            await asyncio.sleep(0.01)
            # This stream will end here. The original stream continues if active.
        return EventSourceResponse(already_running_generator())


    if current_process_status != ProcessStatus.PLAN_GENERATED:
        logger.warning(f"[{process_id}] Attempt to stream process with status: {current_process_status}. Aborting stream as it's not in '{ProcessStatus.PLAN_GENERATED}' state.")
        async def invalid_status_generator():
            # MODIFIED: Yield a dictionary
            yield {
                "event": "plan_error",
                "data": json.dumps({'process_id': process_id, 'status': 'error', 'message': f'Process cannot be streamed. Current state: {current_process_status}'})
            }
            await asyncio.sleep(0.01)
        return EventSourceResponse(invalid_status_generator())

    if process_info.get("cancelled", False):
        logger.info(f"[{process_id}] [/stream-updates] Process was cancelled before execution stream started.")
        active_processes[process_id]["status"] = ProcessStatus.CANCELLED
        async def cancelled_generator():
            # MODIFIED: Yield a dictionary
            yield {
                "event": "plan_cancelled",
                "data": json.dumps({'process_id': process_id, 'message': 'Process was cancelled before execution started.'})
            }
            await asyncio.sleep(0.01)
        return EventSourceResponse(cancelled_generator())

    logger.info(f"[{process_id}] [/stream-updates] Client connected for SSE updates. Starting execution.")

    core_plan_to_execute = process_info.get("core_plan_model_for_execution")
    query = process_info.get("query", "N/A")

    if not core_plan_to_execute or not isinstance(core_plan_to_execute, CoreExecutionPlan):
        logger.error(f"[{process_id}] Critical: Core plan model not found or invalid for the process despite '{ProcessStatus.PLAN_GENERATED}' status. Plan: {core_plan_to_execute}")
        active_processes[process_id]["status"] = ProcessStatus.ERROR
        active_processes[process_id]["error_message"] = 'Internal error: Core plan model not found or invalid for execution.'
        async def core_plan_error_generator():
            # MODIFIED: Yield a dictionary
            yield {
                "event": "plan_error",
                "data": json.dumps({'process_id': process_id, 'status': 'error', 'message': active_processes[process_id]["error_message"]})
            }
            await asyncio.sleep(0.01)
        return EventSourceResponse(core_plan_error_generator())

    event_generator = run_execution_and_stream(
        process_id,
        query,
        core_plan_to_execute,
        current_user
    )
    return EventSourceResponse(event_generator)


@router.post("/cancel/{process_id}", status_code=200)
async def cancel_realtime_process_endpoint(
    process_id: str,
    current_user: AuthUser | None = Depends(get_current_user_dev_optional)
):
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
        msg = f"Process {process_id} is already in a terminal state: {current_status} and cannot be cancelled."
        logger.info(f"[{process_id}] [/cancel] {msg}")
        # Return 200 but indicate it was already terminal, or 400 if preferred.
        # For now, let's use 200 with a clear message.
        return JSONResponse(content={"message": msg, "status": current_status}, status_code=200)


    logger.info(f"[{process_id}] [/cancel] Cancellation requested by user: {username}. Current status: {current_status}")
    active_processes[process_id]["cancelled"] = True
    
    # If it's just planned or generating plan, we can directly set it to cancelled.
    # If running, the check_cancellation callback in run_execution_and_stream will handle it.
    if current_status == ProcessStatus.PLAN_GENERATED or current_status == ProcessStatus.PLAN_GENERATION:
        active_processes[process_id]["status"] = ProcessStatus.CANCELLED
        logger.info(f"[{process_id}] [/cancel] Process was in '{current_status}' state, marked as '{ProcessStatus.CANCELLED}'.")

    return {"message": f"Cancellation signal sent for process {process_id}. If running, it will attempt to stop."}

@router.get("/available-tools")
async def get_available_tools(
    current_user: AuthUser | None = Depends(get_current_user_dev_optional)
):
    """Retrieve all available tools from the tool registry."""
    tools_json_str = build_tools_documentation()
    tools_list = json.loads(tools_json_str)
    
    # Sort tools by category then name for better organization
    tools_list.sort(key=lambda x: (x.get("category", ""), x["tool_name"]))
    
    return {
        "tools_count": len(tools_list),
        "tools": tools_list
    }