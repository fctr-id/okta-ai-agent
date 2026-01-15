"""
ReAct Agent Streaming Router - SSE Integration

This module provides SSE streaming for the One-ReAct agent execution.

Key Features:
- One-ReAct agent integration via ReActAgentExecutor
- SSE (Server-Sent Events) streaming for real-time discovery steps
- Security validation before code execution
- Subprocess execution with progress streaming
- Cancellation support

Event Types:
- STEP-START: Discovery step begins
- STEP-END: Discovery step completes
- STEP-PROGRESS: Subprocess progress updates
- STEP-TOKENS: Token usage reporting
- COMPLETE: Final completion
- ERROR: Error occurred
"""

import asyncio
import json
import os
import sqlite3
import time
import uuid
import shutil
from pathlib import Path
from typing import Dict, Any, AsyncGenerator

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from src.config.settings import Settings
from src.core.security.dependencies import get_current_user
from src.core.okta.sync.models import AuthUser
from src.core.agents.orchestrator import execute_multi_agent_query, OrchestratorResult
from src.core.okta.client import OktaClient
from src.utils.logging import get_logger, set_correlation_id
from src.utils.security_config import validate_generated_code

# Load environment variables
load_dotenv()

# Load settings
settings = Settings()

logger = get_logger("okta_ai_agent")

# --- Router Setup ---
router = APIRouter(prefix="/react", tags=["react-agent"])

# --- Process Tracking ---
active_processes: Dict[str, Any] = {}


# ============================================================================
# Request/Response Models
# ============================================================================

class QueryRequest(BaseModel):
    """Request body for ReAct query"""
    query: str


class QueryResponse(BaseModel):
    """Response with process ID for SSE connection"""
    process_id: str
    message: str


class CancelRequest(BaseModel):
    """Request to cancel execution"""
    process_id: str


# ============================================================================
# Helper Functions for Script Execution
# ============================================================================

def _write_temp_script(process_id: str, code: str) -> str:
    """Write code to temporary Python file"""
    project_root = Path(__file__).parent.parent.parent.parent
    temp_dir = project_root / "generated_scripts"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    script_path = temp_dir / f"react_execution_{process_id}.py"
    
    # Security check
    normalized_script = os.path.normpath(str(script_path))
    normalized_temp = os.path.normpath(str(temp_dir))
    if not normalized_script.startswith(normalized_temp + os.sep):
        raise ValueError("Invalid script path - potential path traversal")
    
    # Copy base_okta_api_client.py ONLY if script actually needs it (API-based queries)
    if "base_okta_api_client" in code or "OktaAPIClient" in code:
        api_client_source = project_root / "src" / "core" / "okta" / "client" / "base_okta_api_client.py"
        api_client_dest = temp_dir / "base_okta_api_client.py"
        
        if api_client_source.exists():
            shutil.copy2(api_client_source, api_client_dest)
            logger.debug(f"[{process_id}] Copied base_okta_api_client.py to {api_client_dest}")
        else:
            logger.error(f"[{process_id}] base_okta_api_client.py not found at {api_client_source}")
            raise FileNotFoundError(f"Required file not found: {api_client_source}")
    else:
        logger.debug(f"[{process_id}] Script is SQL-only, skipping API client copy")
    
    # Modify code to use local import
    modified_code = code.replace(
        "from src.core.okta.client.base_okta_api_client import OktaAPIClient",
        "from base_okta_api_client import OktaAPIClient"
    )
    
    # Write script directly without repr() to avoid escaping quotes
    with open(normalized_script, "w", encoding="utf-8", newline='\n') as f:
        f.write(modified_code)
    
    logger.debug(f"[{process_id}] Script written to: {normalized_script}")
    return normalized_script


async def _execute_script(process_id: str, script_path: str, check_cancelled: callable) -> AsyncGenerator[Dict[str, Any], None]:
    """Execute script and stream results"""
    # Get Python executable
    venv_python = Path("venv/Scripts/python.exe")
    python_exe = str(venv_python) if venv_python.exists() else "python"
    
    script_path_obj = Path(script_path)
    script_dir = script_path_obj.parent
    script_filename = script_path_obj.name
    
    # Create subprocess
    # COMMENTED: Reduces log noise during script execution
    # logger.debug(f"[{process_id}] Starting subprocess: {python_exe} -u {script_filename}")
    # logger.debug(f"[{process_id}] CWD: {script_dir}")
    proc = await asyncio.create_subprocess_exec(
        python_exe,
        "-u",
        script_filename,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(script_dir),
        limit=1024*1024
    )
    # logger.debug(f"[{process_id}] Subprocess created with PID: {proc.pid}")
    
    stdout_lines = []
    stderr_lines = []
    
    # Read stdout
    async def read_stdout():
        # COMMENTED: Reduces log noise
        # logger.debug(f"[{process_id}] Starting stdout reader")
        if proc.stdout:
            line_count = 0
            while True:
                line = await proc.stdout.readline()
                if not line:
                    # logger.debug(f"[{process_id}] Stdout reader: no more lines, read {line_count} total")
                    break
                line_str = line.decode('utf-8', errors='replace').rstrip()
                stdout_lines.append(line_str)
                line_count += 1
                # COMMENTED: Reduces log noise during script execution
                # logger.debug(f"[{process_id}] Stdout line {line_count}: {line_str[:100]}")
        else:
            logger.warning(f"[{process_id}] proc.stdout is None!")
    
    # Stream stderr events
    async def read_stderr_and_yield():
        if proc.stderr:
            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
                line_str = line.decode('utf-8', errors='replace').rstrip()
                stderr_lines.append(line_str)
                
                # Check for progress events
                if line_str.startswith("__PROGRESS__"):
                    try:
                        progress_json = line_str.replace("__PROGRESS__", "").strip()
                        progress_data = json.loads(progress_json)
                        yield {
                            "type": "STEP-PROGRESS",
                            **progress_data,
                            "timestamp": time.time()
                        }
                    except json.JSONDecodeError:
                        pass
    
    # Start stdout reader
    stdout_task = asyncio.create_task(read_stdout())
    
    try:
        # Stream stderr events
        async for event in read_stderr_and_yield():
            if check_cancelled():
                proc.kill()
                break
            yield event
        
        # Wait for stdout to complete
        # COMMENTED: Reduces log noise
        # logger.debug(f"[{process_id}] Waiting for stdout task...")
        await stdout_task
        # logger.debug(f"[{process_id}] Stdout task complete")
        
        # Wait for process
        # logger.debug(f"[{process_id}] Waiting for process to exit...")
        await proc.wait()
        # logger.debug(f"[{process_id}] Process exited with returncode: {proc.returncode}")
        
        # Check for errors
        if proc.returncode != 0:
            error_msg = '\n'.join(stderr_lines[-10:]) if stderr_lines else "Script failed"
            raise Exception(f"Script execution failed: {error_msg}")
        
        # Parse results from stdout
        stdout = '\n'.join(stdout_lines)
        # COMMENTED: Reduces log noise
        # logger.debug(f"[{process_id}] Captured {len(stdout_lines)} lines of stdout ({len(stdout)} chars)")
        # if len(stdout) < 500:
        #     logger.debug(f"[{process_id}] Full stdout:\n{stdout}")
        # else:
        #     logger.debug(f"[{process_id}] First 500 chars of stdout:\n{stdout[:500]}")
        
        results_data = _parse_script_output(stdout)
        
        if results_data:
            # Send final results
            yield {
                "type": "COMPLETE",
                "success": True,
                "display_type": results_data.get("display_type", "table"),
                "results": results_data.get("data", []),
                "headers": results_data.get("headers", []),
                "count": results_data.get("count", 0),
                "timestamp": time.time()
            }
    
    finally:
        # Ensure process is terminated
        if proc.returncode is None:
            proc.kill()


def _parse_script_output(stdout: str) -> Dict[str, Any]:
    """Parse JSON results from script output"""
    try:
        # Look for JSON between the markers (same logic as one_react_agent_executor.py)
        lines = stdout.split('\n')
        json_lines = []
        in_json = False
        
        for line in lines:
            if line.strip() == "QUERY RESULTS":
                in_json = True
                continue
            elif line.strip().startswith("====") and in_json and json_lines:
                # End of JSON block
                break
            elif in_json and line.strip() and not line.strip().startswith("===="):
                json_lines.append(line)
        
        if json_lines:
            json_text = '\n'.join(json_lines)
            parsed_output = json.loads(json_text)
            
            # Support both old format (array) and new format (object with data/headers)
            if isinstance(parsed_output, list):
                return {
                    "display_type": "table",
                    "data": parsed_output,
                    "count": len(parsed_output)
                }
            elif isinstance(parsed_output, dict):
                # Already has the right structure
                return parsed_output
            
    except Exception as e:
        logger.warning(f"Failed to parse script output: {e}")
        return {"raw_output": stdout, "count": 0}
    
    return None


# UNUSED: Cleanup disabled for debugging purposes - scripts are kept in generated_scripts/
# def _cleanup_temp_script(script_path: str):
#     """Clean up temporary script file"""
#     try:
#         script_file = Path(script_path)
#         if script_file.exists():
#             script_file.unlink()
#             logger.debug(f"Cleaned up temp script: {script_path}")
#     except Exception as e:
#         logger.warning(f"Failed to cleanup temp script: {e}")


# ============================================================================
# Routes
# ============================================================================

@router.post("/start-react-process", response_model=QueryResponse)
async def start_react_process(
    request: QueryRequest,
    current_user: AuthUser = Depends(get_current_user)
):
    """
    Start ReAct agent discovery process.
    
    Returns process_id for connecting to SSE stream.
    Frontend should immediately call /stream-react-updates with this process_id.
    """
    correlation_id = str(uuid.uuid4())
    set_correlation_id(correlation_id)
    
    try:
        username = current_user.username if current_user and hasattr(current_user, 'username') else "dev_user"
        logger.info(f"[{correlation_id}] Starting ReAct process for user: {username}")
        logger.info(f"[{correlation_id}] Query: {request.query}")
        
        # Create process tracking entry
        active_processes[correlation_id] = {
            "status": "initializing",
            "query": request.query,
            "user_id": current_user.id,
            "created_at": time.time(),
            "cancelled": False
        }
        
        return QueryResponse(
            process_id=correlation_id,
            message="ReAct process started. Connect to /stream-react-updates to receive events."
        )
        
    except Exception as e:
        logger.error(f"[{correlation_id}] Failed to start process: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start ReAct process: {str(e)}"
        )


@router.get("/stream-react-updates")
async def stream_react_updates(
    process_id: str,
    current_user: AuthUser = Depends(get_current_user)
):
    """
    Stream ReAct agent execution events via SSE.
    """
    # Validate process_id is a valid UUID to prevent path traversal
    import uuid
    try:
        uuid.UUID(process_id, version=4)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid process ID format. Must be a valid UUID."
        )

    if process_id not in active_processes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Process ID not found"
        )
    
    process = active_processes[process_id]
    
    # Verify user owns this process
    if process["user_id"] != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this process"
        )
    
    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events from Multi-Agent Orchestrator execution"""
        artifacts_file = None
        okta_client = None
        
        try:
            # Update status
            process["status"] = "executing"
            
            # Create artifacts file
            artifacts_file = await _create_artifacts_file(process_id)
            
            # Create Okta client
            okta_client = OktaClient()
            
            # Event queue for SSE streaming
            event_queue = asyncio.Queue()
            
            # Create cancellation check
            def check_cancelled():
                return process.get("cancelled", False)
            
            # Callback for orchestrator events
            async def event_callback(event_type: str, event_data: Dict[str, Any]):
                """Convert orchestrator events to SSE format and queue them"""
                if event_type == "step_start":
                    sse_event = {
                        "type": "STEP-START",
                        "step": event_data.get("step", 0),
                        "title": event_data.get("title", ""),
                        "text": event_data.get("text", ""),
                        "tools": event_data.get("tools", []),  # Tool calls for frontend
                        "timestamp": time.time()
                    }
                    await event_queue.put(sse_event)
                
                elif event_type == "step_end":
                    sse_event = {
                        "type": "STEP-END",
                        "step": event_data.get("step", 0),
                        "title": event_data.get("title", ""),
                        "text": event_data.get("text", ""),
                        "success": event_data.get("success", True),
                        "timestamp": time.time()
                    }
                    await event_queue.put(sse_event)
                
                elif event_type == "tool_call":
                    sse_event = {
                        "type": "TOOL-CALL",
                        "tool_name": event_data.get("tool_name", "unknown"),
                        "description": event_data.get("description", ""),
                        "timestamp": event_data.get("timestamp", time.time())
                    }
                    await event_queue.put(sse_event)
                
                elif event_type == "progress":
                    message = event_data.get("message", "")
                    
                    # Filter out internal progress messages
                    skip_prefixes = ["STARTING:", "ANALYSING:", "ANALYZING:", "CLASSIFYING:", "CHECKING:", "LOADING:"]
                    if any(message.startswith(prefix) for prefix in skip_prefixes):
                        return  # Skip this progress event
                    
                    sse_event = {
                        "type": "STEP-PROGRESS",
                        "message": message,
                        "details": event_data.get("details", ""),
                        "timestamp": time.time()
                    }
                    await event_queue.put(sse_event)
            
            # Run orchestrator in background
            async def run_orchestrator():
                """Execute orchestrator and send sentinel when done"""
                try:
                    return await execute_multi_agent_query(
                        user_query=process["query"],
                        correlation_id=process_id,
                        artifacts_file=artifacts_file,
                        okta_client=okta_client,
                        cancellation_check=check_cancelled,
                        event_callback=event_callback
                    )
                finally:
                    # Send sentinel to signal completion
                    await event_queue.put(None)
            
            # Start orchestrator
            logger.info(f"[{process_id}] Starting multi-agent orchestrator")
            orchestrator_task = asyncio.create_task(run_orchestrator())
            
            # Stream events as they arrive (loop until sentinel)
            while True:
                # Check for cancellation
                if check_cancelled():
                    orchestrator_task.cancel()
                    break
                
                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=0.5)
                    if event is None:  # Sentinel - orchestrator done
                        break
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    continue
            
            # Get orchestrator result
            result = await orchestrator_task
            
            # Orchestrator already logged completion and phases
            
            if not result.success:
                error_event = {
                    "type": "ERROR",
                    "error": result.error or "Orchestrator failed",
                    "timestamp": time.time()
                }
                yield f"data: {json.dumps(error_event)}\n\n"
                logger.error(f"[{process_id}] Multi-agent orchestrator failed: {result.error}")
                process["status"] = "error"
                return
            
            # Send SCRIPT-GENERATED event (matching one_react_agent_executor.py pattern)
            if result.script_code:
                # Orchestrator already logged synthesis completion
                script_length = len(result.script_code)
                
                # COMMENTED: Script preview logging disabled to reduce log noise
                # Log first 30 and last 20 lines to avoid log flooding
                # if total_lines > 50:
                #     logger.debug(f"[{process_id}] First 30 lines:")
                #     for i, line in enumerate(script_lines[:30], 1):
                #         logger.debug(f"[{process_id}] {i:4d} | {line}")
                #     logger.debug(f"[{process_id}] ... ({total_lines - 50} lines omitted) ...")
                #     logger.debug(f"[{process_id}] Last 20 lines:")
                #     for i, line in enumerate(script_lines[-20:], total_lines - 19):
                #         logger.debug(f"[{process_id}] {i:4d} | {line}")
                # else:
                #     # Small script - log all
                #     logger.debug(f"[{process_id}] Complete script:")
                #     for i, line in enumerate(script_lines, 1):
                #         logger.debug(f"[{process_id}] {i:4d} | {line}")
                
                # Send SCRIPT-GENERATED event to frontend
                script_event = {
                    "type": "SCRIPT-GENERATED",
                    "script_code": result.script_code,
                    "script_length": script_length,
                    "timestamp": time.time()
                }
                yield f"data: {json.dumps(script_event)}\n\n"
                logger.debug(f"[{process_id}] Sent SCRIPT-GENERATED event")
            
            # Check for direct answer (Special Tool) - Skip validation/execution if no script
            if not result.script_code:
                logger.info(f"[{process_id}] ⚡ No script generated - checking for direct answer")
                
                # Check if we have direct results (from special tool)
                if result.success:
                    # Send COMPLETE event with direct results
                    complete_event = {
                        "type": "COMPLETE",
                        "display_type": "markdown",
                        "content": result.error or "Query completed successfully",
                        "timestamp": time.time(),
                        "is_special_tool": True
                    }
                    yield f"data: {json.dumps(complete_event)}\n\n"
                else:
                    # No script and no results - error
                    error_event = {
                        "type": "ERROR",
                        "error": result.error or "No script generated and no results available",
                        "timestamp": time.time()
                    }
                    yield f"data: {json.dumps(error_event)}\n\n"
                
                process["status"] = "completed" if result.success else "error"
                return
            
            # Phase 2: Validate generated script
            logger.info(f"[{process_id}] Phase 2: Starting security validation")
            validation_start = {
                "type": "STEP-START",
                "step": "validation",  # String to match frontend check
                "title": "Security Validation",
                "text": "Scanning generated code for security issues",
                "tools": [],  # No tools used in validation
                "timestamp": time.time()
            }
            yield f"data: {json.dumps(validation_start)}\n\n"
            
            validation_result = validate_generated_code(result.script_code)
            logger.debug(f"[{process_id}] Validation result: is_valid={validation_result.is_valid}, risk_level={validation_result.risk_level}")
            
            if not validation_result.is_valid:
                validation_error = {
                    "type": "STEP-END",
                    "step": "validation",  # String to match frontend check
                    "title": "Security Validation Failed",
                    "text": f"Security issues found: {', '.join(validation_result.violations)}",
                    "success": False,
                    "timestamp": time.time()
                }
                yield f"data: {json.dumps(validation_error)}\n\n"
                
                error_event = {
                    "type": "ERROR",
                    "error": f"Security validation failed: {', '.join(validation_result.violations)}",
                    "timestamp": time.time()
                }
                yield f"data: {json.dumps(error_event)}\n\n"
                process["status"] = "error"
                return
            
            validation_success = {
                "type": "STEP-END",
                "step": "validation",  # String to match frontend check
                "title": "Security Validation Passed",
                "text": f"Code is safe to execute (risk level: {validation_result.risk_level})",
                "success": True,
                "timestamp": time.time()
            }
            yield f"data: {json.dumps(validation_success)}\n\n"
            logger.info(f"[{process_id}] Phase 2 complete: Security validation passed")
            
            # Emit token usage BEFORE execution (so frontend receives it before COMPLETE)
            token_event = {
                "type": "STEP-TOKENS",
                "input_tokens": result.total_input_tokens,
                "output_tokens": result.total_output_tokens,
                "total_tokens": result.total_tokens,
                "requests": result.total_requests,
                "timestamp": time.time()
            }
            yield f"data: {json.dumps(token_event)}\n\n"
            
            # Phase 3: Execute script
            logger.info(f"[{process_id}] Phase 3: Starting script execution")
            execution_start = {
                "type": "STEP-START",
                "step": "execution",  # String to match frontend check
                "title": "Executing Script",
                "text": "Running generated code to fetch results",
                "tools": [],  # No tools used in execution
                "timestamp": time.time()
            }
            yield f"data: {json.dumps(execution_start)}\n\n"
            
            # Write script to temp file
            script_path = _write_temp_script(process_id, result.script_code)
            # _write_temp_script already logged the path
            
            # Execute and stream results
            # COMMENTED: Reduces log noise (subprocess execution is implicit)
            # logger.info(f"[{process_id}] Starting subprocess execution")
            async for execution_event in _execute_script(process_id, script_path, check_cancelled):
                yield f"data: {json.dumps(execution_event)}\n\n"
            
            # Note: Cleanup disabled - scripts kept in generated_scripts/ for debugging
            logger.debug(f"[{process_id}] Script retained for debugging: {script_path}")
            
            execution_success = {
                "type": "STEP-END",
                "step": "execution",  # String to match frontend check
                "title": "Execution Complete",
                "text": "Script executed successfully",
                "success": True,
                "timestamp": time.time()
            }
            yield f"data: {json.dumps(execution_success)}\n\n"
            
            logger.info(f"[{process_id}] Phase 3 complete: Script executed successfully")
            
            # Log token usage summary at end for visibility
            if result.total_tokens > 0:
                avg_per_call = result.total_input_tokens / result.total_requests if result.total_requests > 0 else 0
                logger.info(
                    f"[{process_id}] 📊 Final Token Usage: "
                    f"{result.total_input_tokens:,} input, {result.total_output_tokens:,} output, "
                    f"{result.total_tokens:,} total (across {result.total_requests} API calls, "
                    f"avg {avg_per_call:,.0f} input/call)"
                )
            
            logger.info(f"[{process_id}] ✅ All phases complete - query execution finished")
            process["status"] = "complete"
            
        except asyncio.CancelledError:
            logger.info(f"[{process_id}] Process cancelled by user")
            error_data = {
                "type": "ERROR",
                "error": "Process cancelled by user",
                "timestamp": time.time()
            }
            yield f"data: {json.dumps(error_data)}\n\n"
            
        except Exception as e:
            logger.error(f"[{process_id}] Stream error: {e}", exc_info=True)
            process["status"] = "error"
            
            error_data = {
                "type": "ERROR",
                "error": "An internal error has occurred. Please try again later.",
                "timestamp": time.time()
            }
            yield f"data: {json.dumps(error_data)}\n\n"
        
        finally:
            # Cleanup (OktaAPIClient uses async context managers, no manual close needed)
            if process_id in active_processes:
                logger.info(f"[{process_id}] Cleaning up process tracking")
                del active_processes[process_id]
            
            # Send explicit close event
            try:
                yield "event: close\ndata: Stream ended\n\n"
            except:
                pass
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post("/cancel")
async def cancel_react_process(
    request: CancelRequest,
    current_user: AuthUser = Depends(get_current_user)
):
    """
    Cancel a running ReAct process.
    
    Sets the cancelled flag, which the executor checks between steps.
    """
    process_id = request.process_id
    
    if process_id not in active_processes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Process ID not found"
        )
    
    process = active_processes[process_id]
    
    # Verify user owns this process
    if process["user_id"] != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to cancel this process"
        )
    
    # Set cancelled flag
    process["cancelled"] = True
    process["status"] = "cancelled"
    
    logger.info(f"[{process_id}] Process cancellation requested")
    
    return JSONResponse(
        content={
            "success": True,
            "message": "Process cancellation requested"
        }
    )


# ============================================================================
# Helper Functions
# ============================================================================

async def _create_artifacts_file(correlation_id: str) -> Path:
    """
    Create artifacts file for multi-agent orchestrator.
    
    Returns path to artifacts file.
    """
    artifacts_dir = Path("logs")
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    artifacts_file = artifacts_dir / f"artifacts_{correlation_id}.json"
    
    # Initialize empty artifacts file as flat array
    with open(artifacts_file, 'w', encoding='utf-8') as f:
        json.dump([], f)
    
    logger.info(f"[{correlation_id}] Created artifacts file: {artifacts_file}")
    return artifacts_file

