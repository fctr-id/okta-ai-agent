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
import sqlite3
import time
import uuid
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, AsyncGenerator, Optional, List

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from src.config.settings import Settings
from src.core.security.dependencies import get_current_user
from src.core.okta.sync.models import AuthUser, QueryHistory
from src.core.okta.sync.operations import DatabaseOperations
from src.core.agents.orchestrator import execute_multi_agent_query, OrchestratorResult
from src.core.okta.client import OktaClient
from src.data.schemas.runtime_storage import (
    RuntimeTurnPaths,
    create_runtime_turn_paths,
    prepare_runtime_script_code,
    update_turn_metadata,
    write_turn_summary,
)
from src.data.schemas.artifact_manifest import append_artifacts_with_result_sets

# Track background tasks to prevent memory leaks
background_tasks: set = set()
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
    session_id: Optional[str] = None


class ScriptExecuteRequest(BaseModel):
    """Request body for direct script execution"""
    query: str
    script_code: str
    session_id: Optional[str] = None


class QueryResponse(BaseModel):
    """Response with process ID for SSE connection"""
    process_id: str
    session_id: str
    run_id: str
    turn_number: int
    message: str


class CancelRequest(BaseModel):
    """Request to cancel execution"""
    process_id: str


# ============================================================================
# Helper Functions for Script Execution
# ============================================================================

def _derive_session_title(query: str, *, max_length: int = 120) -> str:
    """Create a compact default session title from the first query."""
    cleaned = " ".join(query.split()).strip()
    if len(cleaned) <= max_length:
        return cleaned or "New conversation"
    return cleaned[: max_length - 3].rstrip() + "..."


def _build_turn_output_summary(complete_event: Optional[Dict[str, Any]]) -> str:
    if not complete_event:
        return "Completed successfully."

    display_type = str(complete_event.get("display_type") or "markdown")
    if display_type == "markdown":
        markdown = str(complete_event.get("content") or "").strip()
        compact_markdown = " ".join(markdown.replace("#", " ").split())
        if len(compact_markdown) <= 240:
            return compact_markdown or "Completed with markdown response."
        return f"{compact_markdown[:237].rstrip()}..."

    metadata = complete_event.get("metadata") if isinstance(complete_event.get("metadata"), dict) else {}
    summary_text = str(metadata.get("summary") or "").strip()
    if summary_text:
        return summary_text

    count = complete_event.get("count")
    if count == 0:
        return "No matching data was found for this turn."
    if isinstance(count, int):
        return f"Returned {count} results."

    return "Completed with structured results."


def _resolve_path_within_directory(path: Path, directory: Path, *, error_message: str) -> Path:
    resolved_directory = directory.resolve()
    resolved_path = path.resolve()
    try:
        resolved_path.relative_to(resolved_directory)
    except ValueError as exc:
        raise ValueError(error_message) from exc
    return resolved_path


def _build_turn_output_artifact_payload(
    complete_event: Dict[str, Any],
    *,
    include_results: bool = True,
    result_set_refs: Optional[List[str]] = None,
) -> str:
    display_type = str(complete_event.get("display_type") or "markdown")
    if display_type == "markdown":
        return str(complete_event.get("content") or "")

    metadata = complete_event.get("metadata") if isinstance(complete_event.get("metadata"), dict) else {}
    results: List[Any] = []
    if include_results:
        raw_results = complete_event.get("results")
        if raw_results is None and isinstance(complete_event.get("content"), list):
            raw_results = complete_event.get("content")
        if isinstance(raw_results, list):
            results = raw_results

    if not isinstance(results, list):
        results = []

    headers = complete_event.get("headers") if isinstance(complete_event.get("headers"), list) else []
    payload = {
        "display_type": display_type,
        "results": results,
        "headers": headers,
        "count": complete_event.get("count", len(results)),
        "metadata": metadata,
    }
    if result_set_refs:
        payload["result_set_refs"] = result_set_refs
        payload["content_omitted"] = True
    return json.dumps(payload, indent=2, default=str)


def _persist_turn_output_artifact(
    *,
    artifacts_file: Optional[Path],
    complete_event: Optional[Dict[str, Any]],
) -> None:
    if not artifacts_file or not complete_event:
        return

    display_type = str(complete_event.get("display_type") or "markdown")
    artifact_summary = _build_turn_output_summary(complete_event)
    metadata = complete_event.get("metadata") if isinstance(complete_event.get("metadata"), dict) else {}

    artifact_payload = {
        "key": "turn_output_final",
        "category": "turn_output",
        "display_type": display_type,
        "content": _build_turn_output_artifact_payload(complete_event),
        "notes": artifact_summary[:500],
        "canonical_turn_output": True,
        "row_count": complete_event.get("count"),
        "entity_type": metadata.get("entity_type"),
        "metadata": metadata,
    }

    saved_artifacts, result_refs = append_artifacts_with_result_sets(
        artifacts_file,
        [artifact_payload],
        source_specialist="unknown",
    )

    if display_type != "markdown" and result_refs:
        result_set_ids = [result_ref.result_set_id for result_ref in result_refs]
        compact_payload = _build_turn_output_artifact_payload(
            complete_event,
            include_results=False,
            result_set_refs=result_set_ids,
        )
        for saved_artifact in reversed(saved_artifacts):
            if saved_artifact.get("key") == "turn_output_final" and saved_artifact.get("category") == "turn_output":
                saved_artifact["content"] = compact_payload
                saved_artifact["content_omitted"] = True
                break

        with open(artifacts_file, "w", encoding="utf-8") as file_handle:
            json.dump(saved_artifacts, file_handle, indent=2, default=str)


async def _bootstrap_conversation_process(
    *,
    correlation_id: str,
    query: str,
    requested_session_id: Optional[str],
    user_id: str,
    source: str,
) -> tuple[str, int]:
    """Create or reuse the session, then preallocate the turn identity before streaming."""
    db_ops = DatabaseOperations()
    await db_ops.init_db()

    session_id = requested_session_id or correlation_id
    conversation_session = await db_ops.create_conversation_session(
        tenant_id=settings.tenant_id,
        user_id=user_id,
        session_id=session_id,
        source=source,
        title=_derive_session_title(query),
        status="active",
    )
    if not conversation_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND if requested_session_id else status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Conversation session could not be created or accessed.",
        )

    conversation_turn = await db_ops.create_conversation_turn(
        tenant_id=settings.tenant_id,
        user_id=user_id,
        session_id=session_id,
        run_id=correlation_id,
        query_text=query,
        source=source,
        status="created",
        started_at=datetime.now(timezone.utc),
    )
    if not conversation_turn:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Conversation turn could not be created.",
        )

    return session_id, conversation_turn.turn_number

def _write_temp_script(process_id: str, code: str) -> str:
    """Write code to temporary Python file"""
    project_root = Path(__file__).parent.parent.parent.parent.resolve()
    temp_dir = (project_root / "generated_scripts").resolve()
    temp_dir.mkdir(parents=True, exist_ok=True)

    script_path = _resolve_path_within_directory(
        temp_dir / f"react_execution_{process_id}.py",
        temp_dir,
        error_message="Invalid script path - potential path traversal",
    )
    
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
    
    modified_code = prepare_runtime_script_code(code)
    
    # Write script directly without repr() to avoid escaping quotes
    with open(script_path, "w", encoding="utf-8", newline='\n') as f:
        f.write(modified_code)

    logger.debug(f"[{process_id}] Script written to: {script_path}")
    return str(script_path)


async def _execute_script(
    process_id: str,
    script_path: str,
    check_cancelled: callable,
    orchestrator_result: 'OrchestratorResult' = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Execute script and stream results"""
    # Get Python executable
    venv_python = Path("venv/Scripts/python.exe")
    python_exe = str(venv_python) if venv_python.exists() else "python"
    
    project_root = Path(__file__).parent.parent.parent.parent.resolve()
    temp_dir = (project_root / "generated_scripts").resolve()
    script_path_obj = _resolve_path_within_directory(
        Path(script_path),
        temp_dir,
        error_message="Invalid script path - potential path traversal",
    )
    
    # Create subprocess
    # COMMENTED: Reduces log noise during script execution
    # logger.debug(f"[{process_id}] Starting subprocess: {python_exe} -u {script_filename}")
    # logger.debug(f"[{process_id}] CWD: {script_dir}")
    proc = await asyncio.create_subprocess_exec(
        python_exe,
        "-u",
        str(script_path_obj),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(project_root),
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
        logger.debug(f"[{process_id}] Captured {len(stdout_lines)} lines of stdout ({len(stdout)} chars)")
        if len(stdout) < 2000:
            logger.debug(f"[{process_id}] Full stdout:\n{stdout}")
        else:
            logger.debug(f"[{process_id}] First 1000 chars of stdout:\n{stdout[:1000]}")
        
        results_data = _parse_script_output(stdout)
        logger.debug(f"[{process_id}] Parse result: {results_data is not None}")
        outcome_payload = orchestrator_result.outcome_metadata() if orchestrator_result else {}
        
        if results_data:
            # Check if script returned markdown format (for summaries/special responses)
            if results_data.get("display_type") == "markdown":
                logger.info(f"[{process_id}] Script returned markdown format")
                yield {
                    "type": "COMPLETE",
                    "success": True,
                    "display_type": "markdown",
                    "content": results_data.get("content", ""),
                    **outcome_payload,
                    "timestamp": time.time()
                }
            # Check if results are empty (no data found)
            elif results_data.get("count", 0) == 0:
                logger.info(f"[{process_id}] Script returned zero results - sending empty results message")
                script_empty_payload = {**outcome_payload, "outcome": "empty", "result_mode": "empty"}
                # Send markdown message instead of empty table
                yield {
                    "type": "COMPLETE",
                    "success": True,
                    "display_type": "markdown",
                    "content": "## No Results Found\n\nYour query completed successfully, but no matching data was found.",
                    **script_empty_payload,
                    "timestamp": time.time()
                }
            else:
                # Send normal table results
                result_count = results_data.get("count", 0)
                
                # Build metadata with data source information
                metadata = {}
                if orchestrator_result and hasattr(orchestrator_result, 'data_source_type'):
                    if orchestrator_result.data_source_type:
                        metadata["data_source_type"] = orchestrator_result.data_source_type
                        
                        # Add last_sync timestamp if SQL was used
                        if orchestrator_result.data_source_type in ["sql", "hybrid"] and orchestrator_result.last_sync_time:
                            metadata["last_sync"] = {"last_sync": orchestrator_result.last_sync_time}
                        
                        logger.info(f"[{process_id}] Metadata: {metadata}")
                    metadata.update(outcome_payload)
                
                yield {
                    "type": "COMPLETE",
                    "success": True,
                    "display_type": results_data.get("display_type", "table"),
                    "results": results_data.get("data", []),
                    "headers": results_data.get("headers", []),
                    "count": result_count,
                    "metadata": metadata,
                    "timestamp": time.time()
                }
    
    finally:
        # Ensure process is terminated
        if proc.returncode is None:
            proc.kill()
        try:
            if script_path_obj.exists():
                script_path_obj.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            logger.debug(f"[{process_id}] Failed to clean up temp script: {script_path_obj}")


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

        session_id, turn_number = await _bootstrap_conversation_process(
            correlation_id=correlation_id,
            query=request.query,
            requested_session_id=request.session_id,
            user_id=username,
            source="web",
        )
        
        # Create process tracking entry
        active_processes[correlation_id] = {
            "status": "initializing",
            "query": request.query,
            "session_id": session_id,
            "run_id": correlation_id,
            "turn_number": turn_number,
            "user_id": username,
            "created_at": time.time(),
            "cancelled": False,
            "source": "web",
        }
        
        return QueryResponse(
            process_id=correlation_id,
            session_id=session_id,
            run_id=correlation_id,
            turn_number=turn_number,
            message="ReAct process started. Connect to /stream-react-updates to receive events."
        )

    except HTTPException:
        raise
        
    except Exception as e:
        logger.error(f"[{correlation_id}] Failed to start process: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start ReAct process: {str(e)}"
        )


@router.post("/execute-script", response_model=QueryResponse)
async def execute_script_directly(
    request: ScriptExecuteRequest,
    current_user: AuthUser = Depends(get_current_user)
):
    """
    Start execution of a pre-generated script.
    
    Returns process_id for connecting to SSE stream.
    Skips the multi-agent discovery phase.
    """
    correlation_id = str(uuid.uuid4())
    set_correlation_id(correlation_id)
    
    try:
        username = current_user.username if current_user and hasattr(current_user, 'username') else "dev_user"
        logger.info(f"[{correlation_id}] Starting direct script execution for user: {username}")

        session_id, turn_number = await _bootstrap_conversation_process(
            correlation_id=correlation_id,
            query=request.query,
            requested_session_id=request.session_id,
            user_id=username,
            source="saved_script",
        )
        
        # Create process tracking entry with pre-generated script
        active_processes[correlation_id] = {
            "status": "initializing",
            "query": request.query,
            "script_code": request.script_code,  # Pre-generated script
            "session_id": session_id,
            "run_id": correlation_id,
            "turn_number": turn_number,
            "user_id": username,
            "created_at": time.time(),
            "cancelled": False,
            "skip_discovery": True,  # Flag to skip orchestrator
            "source": "saved_script",
        }
        
        return QueryResponse(
            process_id=correlation_id,
            session_id=session_id,
            run_id=correlation_id,
            turn_number=turn_number,
            message="Script execution started. Connect to /stream-react-updates to receive events."
        )

    except HTTPException:
        raise
        
    except Exception as e:
        logger.error(f"[{correlation_id}] Failed to start direct execution: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start direct execution: {str(e)}"
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
    if process["user_id"].lower() != current_user.username.lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this process"
        )
    
    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events from Multi-Agent Orchestrator execution"""
        artifacts_file = None
        runtime_paths = None
        okta_client = None
        orchestrator_task = None
        stream_started = False  # Track if stream actually started
        auto_save_legacy_query_history = process.get("source") not in {"web", "saved_script"}

        async def mirror_runtime_state() -> None:
            if not runtime_paths:
                return

            try:
                db_ops = DatabaseOperations()
                mirrored = await db_ops.mirror_runtime_turn_state(
                    tenant_id=settings.tenant_id,
                    run_id=process_id,
                    runtime_paths=runtime_paths,
                )
                if not mirrored:
                    logger.warning(f"[{process_id}] Runtime-to-SQL mirror skipped because the turn row was not found")
            except Exception as mirror_error:
                logger.error(f"[{process_id}] Failed to mirror runtime turn state: {mirror_error}", exc_info=True)
        
        try:
            # Update status
            process["status"] = "executing"
            stream_started = True  # Mark that we successfully started streaming
            
            # Create session/turn runtime folder and artifacts file
            runtime_paths = await _create_runtime_turn_paths(process_id, process)
            process["runtime_paths"] = runtime_paths
            artifacts_file = runtime_paths.artifacts_file
            update_turn_metadata(
                runtime_paths,
                status="executing",
                user_query=process["query"],
            )
            await mirror_runtime_state()
            
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
                    text = event_data.get("text", "")
                    
                    # Filter out internal status messages that start with "WORD:" pattern
                    # This catches: "STARTING:", "ROUTING:", "CLASSIFYING:", "ANALYZING:", etc.
                    import re
                    if re.match(r'^[🎯🔍⚡]*\s*[A-Z]+:', text):
                        return  # Skip messages with prefix pattern
                    
                    sse_event = {
                        "type": "STEP-START",
                        "step": event_data.get("step", 0),
                        "title": event_data.get("title", ""),
                        "text": text,
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
                    
                    # Filter out internal progress messages using same pattern as step_start
                    import re
                    if re.match(r'^[🎯🔍⚡]*\s*[A-Z]+:', message):
                        return  # Skip messages with prefix pattern
                    
                    sse_event = {
                        "type": "STEP-PROGRESS",
                        "message": message,
                        "details": event_data.get("details", ""),
                        "timestamp": time.time()
                    }
                    await event_queue.put(sse_event)
            
            # Check if we should skip discovery and use pre-generated script
            if process.get("skip_discovery") and process.get("script_code"):
                logger.info(f"[{process_id}] Skipping discovery phase, using pre-generated script")
                
                # Create a minimal OrchestratorResult
                from src.core.agents.orchestrator import OrchestratorResult
                result = OrchestratorResult()
                result.success = True
                result.script_code = process["script_code"]
                result.data_source_type = "hybrid" # Default for re-execution
                
                # Send a notification that we are starting from a saved script
                await event_callback("progress", {"message": "🚀 Starting execution from saved script..."})
                
            else:
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
                
                # Get orchestrator result (handle cancellation)
                try:
                    result = await orchestrator_task
                except asyncio.CancelledError:
                    logger.info(f"[{process_id}] Orchestrator task was cancelled")
                    raise  # Re-raise to exit generator
            
            # Orchestrator already logged completion and phases
            
            # Check if discovery succeeded but found no data (0 artifacts)
            if result.no_data_found:
                logger.info(f"[{process_id}] Discovery succeeded but found no data")
                no_data_message = result.user_message or "Your query completed successfully, but no matching data was found."
                complete_event = {
                    "type": "COMPLETE",
                    "success": True,
                    "display_type": "markdown",
                    "content": f"## No Results Found\n\n{no_data_message}",
                    **result.outcome_metadata(),
                    "timestamp": time.time()
                }
                yield f"data: {json.dumps(complete_event)}\n\n"
                _persist_turn_output_artifact(
                    artifacts_file=artifacts_file,
                    complete_event=complete_event,
                )
                write_turn_summary(runtime_paths, {
                    "status": "completed",
                    "user_query": process["query"],
                    "final_response_summary": _build_turn_output_summary(complete_event),
                    "display_type": "markdown",
                    "result_count": 0,
                    "artifact_file": artifacts_file.as_posix(),
                    "outcome": result.outcome_metadata(),
                })
                update_turn_metadata(runtime_paths, status="completed", completed_at=time.time())
                await mirror_runtime_state()

                if auto_save_legacy_query_history:
                    try:
                        logger.debug(f"[{process_id}] Starting no-data history save...")
                        db_ops = DatabaseOperations()
                        await asyncio.shield(
                            db_ops.save_query_history(
                                tenant_id=settings.tenant_id,
                                user_id=process.get("user_id", "localadmin"),
                                query_text=process["query"],
                                final_script="",
                                results_summary=no_data_message
                            )
                        )
                        logger.info(f"[{process_id}] ✅ No-data query history saved")
                    except asyncio.CancelledError:
                        logger.warning(f"[{process_id}] No-data history save cancelled")
                    except Exception as e:
                        logger.error(f"[{process_id}] Failed to save no-data query history: {e}", exc_info=True)
                else:
                    logger.debug(f"[{process_id}] Skipping legacy query history auto-save for conversation-backed web run")

                process["status"] = "complete"

                done_event = {
                    "type": "DONE",
                    "timestamp": time.time()
                }
                yield f"data: {json.dumps(done_event)}\n\n"
                return
            
            if not result.success:
                error_event = {
                    "type": "ERROR",
                    "error": result.error or "Orchestrator failed",
                    **result.outcome_metadata(),
                    "timestamp": time.time()
                }
                yield f"data: {json.dumps(error_event)}\n\n"
                logger.error(f"[{process_id}] Multi-agent orchestrator failed: {result.error}")
                update_turn_metadata(runtime_paths, status="error", error=result.error, completed_at=time.time())
                await mirror_runtime_state()
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
                    **result.outcome_metadata(),
                    "timestamp": time.time()
                }
                yield f"data: {json.dumps(script_event)}\n\n"
                logger.debug(f"[{process_id}] Sent SCRIPT-GENERATED event")
            
            # Check for direct answer (Special Tool) - Skip validation/execution if special tool
            # SECURITY: Verify this is actually from special tools phase (defense in depth)
            if result.is_special_tool and 'special' in result.phases_executed:
                logger.info(f"[{process_id}] ⚡ Special tool result - skipping validation and execution")
                
                # Send COMPLETE event with special tool results
                complete_event = {
                    "type": "COMPLETE",
                    "display_type": result.display_type or "markdown",
                    "content": result.script_code,  # Contains the llm_summary
                    "timestamp": time.time(),
                    "is_special_tool": True,
                    **result.outcome_metadata(),
                }
                yield f"data: {json.dumps(complete_event)}\n\n"
                _persist_turn_output_artifact(
                    artifacts_file=artifacts_file,
                    complete_event=complete_event,
                )
                write_turn_summary(runtime_paths, {
                    "status": "completed",
                    "user_query": process["query"],
                    "final_response_summary": _build_turn_output_summary(complete_event),
                    "display_type": result.display_type or "markdown",
                    "artifact_file": artifacts_file.as_posix(),
                    "is_special_tool": True,
                    "outcome": result.outcome_metadata(),
                })
                update_turn_metadata(runtime_paths, status="completed", completed_at=time.time())
                await mirror_runtime_state()
                
                if auto_save_legacy_query_history:
                    try:
                        logger.debug(f"[{process_id}] Starting special tool history save...")
                        db_ops = DatabaseOperations()
                        summary = (result.script_code[:100] + "...") if result.script_code else "Special tool result"

                        await asyncio.shield(
                            db_ops.save_query_history(
                                tenant_id=settings.tenant_id,
                                user_id=process.get("user_id", "localadmin"),
                                query_text=process["query"],
                                final_script="",  # Special tools don't have a script
                                results_summary=summary
                            )
                        )
                        logger.info(f"[{process_id}] ✅ Special tool history saved")
                    except asyncio.CancelledError:
                        logger.warning(f"[{process_id}] Special tool history save cancelled")
                    except Exception as e:
                        logger.error(f"[{process_id}] Failed to save special tool history: {e}", exc_info=True)
                else:
                    logger.debug(f"[{process_id}] Skipping legacy query history auto-save for conversation-backed web run")
                
                # Send DONE after save completes
                done_event = {
                    "type": "DONE",
                    "timestamp": time.time()
                }
                yield f"data: {json.dumps(done_event)}\n\n"
                
                process["status"] = "completed"
                return
            
            # Check for no script - this is always an error
            if not result.script_code:
                logger.error(f"[{process_id}] ❌ Synthesis completed but no script generated")
                
                # No script means synthesis failed to produce code - treat as error
                error_event = {
                    "type": "ERROR",
                    "error": result.error or "Synthesis agent completed but failed to generate executable code. Please try rephrasing your query or check the logs.",
                    "timestamp": time.time()
                }
                yield f"data: {json.dumps(error_event)}\n\n"
                
                process["status"] = "error"
                update_turn_metadata(
                    runtime_paths,
                    status="error",
                    error=error_event["error"],
                    completed_at=time.time(),
                )
                await mirror_runtime_state()
                
                # Send DONE event to close stream
                done_event = {
                    "type": "DONE",
                    "timestamp": time.time()
                }
                yield f"data: {json.dumps(done_event)}\n\n"
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
                update_turn_metadata(
                    runtime_paths,
                    status="error",
                    error=error_event["error"],
                    completed_at=time.time(),
                )
                await mirror_runtime_state()
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
            execution_succeeded = False
            final_execution_event = None
            
            async for execution_event in _execute_script(process_id, script_path, check_cancelled, result):
                yield f"data: {json.dumps(execution_event)}\n\n"
                
                # Track final completion event for history save
                if execution_event.get("type") == "COMPLETE" and execution_event.get("success"):
                    execution_succeeded = True
                    final_execution_event = execution_event

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
            _persist_turn_output_artifact(
                artifacts_file=artifacts_file,
                complete_event=final_execution_event,
            )
            write_turn_summary(runtime_paths, {
                "status": "completed",
                "user_query": process["query"],
                "final_response_summary": _build_turn_output_summary(final_execution_event),
                "display_type": final_execution_event.get("display_type") if final_execution_event else result.display_type,
                "result_count": final_execution_event.get("count") if final_execution_event else None,
                "artifact_file": artifacts_file.as_posix(),
                "outcome": result.outcome_metadata(),
                "token_usage": {
                    "input_tokens": result.total_input_tokens,
                    "output_tokens": result.total_output_tokens,
                    "total_tokens": result.total_tokens,
                    "requests": result.total_requests,
                },
            })
            update_turn_metadata(runtime_paths, status="completed", completed_at=time.time())
            await mirror_runtime_state()
            
            logger.info(f"[{process_id}] Phase 3 complete: Script executed successfully")
            
            # Legacy QueryHistory auto-save is intentionally disabled for conversation-backed web runs.
            logger.debug(f"[{process_id}] History save check: execution_succeeded={execution_succeeded}, has_event={final_execution_event is not None}, auto_save_legacy_query_history={auto_save_legacy_query_history}")
            if auto_save_legacy_query_history and execution_succeeded and final_execution_event:
                try:
                    logger.debug(f"[{process_id}] Starting history save...")
                    db_ops = DatabaseOperations()
                    summary = ""
                    if final_execution_event.get("display_type") == "markdown":
                        summary = (final_execution_event.get("content", "")[:100] + "...")
                    else:
                        summary = f"Found {final_execution_event.get('count', 0)} results"
                    
                    # Shield from cancellation
                    await asyncio.shield(
                        db_ops.save_query_history(
                            tenant_id=settings.tenant_id,
                            user_id=process.get("user_id", "localadmin"),  # From active_processes
                            query_text=process["query"],
                            final_script=result.script_code,
                            results_summary=summary
                        )
                    )
                    logger.info(f"[{process_id}] ✅ Query history saved to database")
                except asyncio.CancelledError:
                    logger.warning(f"[{process_id}] History save cancelled - attempting to complete anyway")
                    # Try one more time without shield
                    try:
                        await db_ops.save_query_history(
                            tenant_id=settings.tenant_id,
                            user_id=process.get("user_id", "localadmin"),
                            query_text=process["query"],
                            final_script=result.script_code,
                            results_summary=summary
                        )
                        logger.info(f"[{process_id}] ✅ Query history saved on retry")
                    except Exception as retry_err:
                        logger.error(f"[{process_id}] Failed to save history on retry: {retry_err}", exc_info=True)
                except Exception as e:
                    logger.error(f"[{process_id}] Failed to save query history: {e}", exc_info=True)
            elif execution_succeeded and final_execution_event:
                logger.debug(f"[{process_id}] Skipping legacy query history auto-save for conversation-backed web run")
            
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
            
            # Send final DONE event to close the stream
            done_event = {
                "type": "DONE",
                "timestamp": time.time()
            }
            yield f"data: {json.dumps(done_event)}\n\n"
            
        except asyncio.CancelledError:
            logger.info(f"[{process_id}] Process cancelled by user")
            if runtime_paths:
                update_turn_metadata(runtime_paths, status="cancelled", completed_at=time.time())
                await mirror_runtime_state()
            error_data = {
                "type": "ERROR",
                "error": "Process cancelled by user",
                "timestamp": time.time()
            }
            yield f"data: {json.dumps(error_data)}\n\n"
            
        except Exception as e:
            logger.error(f"[{process_id}] Stream error: {e}", exc_info=True)
            process["status"] = "error"
            if runtime_paths:
                update_turn_metadata(runtime_paths, status="error", error=str(e), completed_at=time.time())
                await mirror_runtime_state()
            
            error_data = {
                "type": "ERROR",
                "error": "An internal error has occurred. Please try again later.",
                "timestamp": time.time()
            }
            yield f"data: {json.dumps(error_data)}\n\n"
        
        finally:
            # Cancel orchestrator task if it's still running (e.g. client disconnect)
            if orchestrator_task and not orchestrator_task.done():
                logger.warning(f"[{process_id}] Stream disconnected - cancelling background orchestrator task")
                orchestrator_task.cancel()
                try:
                    await orchestrator_task
                except asyncio.CancelledError:
                    logger.debug(f"[{process_id}] Orchestrator task cancelled successfully")
                except Exception as e:
                    logger.error(f"[{process_id}] Error during orchestrator task cancellation: {e}")

            # Cleanup AFTER orchestrator is fully stopped to avoid race condition
            # Always remove from active_processes to prevent stale entries
            if process_id in active_processes:
                process_status = active_processes[process_id].get("status", "unknown")
                logger.info(f"[{process_id}] Cleaning up process tracking (status: {process_status}, stream_started: {stream_started})")
                del active_processes[process_id]
                logger.debug(f"[{process_id}] Remaining active processes: {list(active_processes.keys())}")
            else:
                logger.warning(f"[{process_id}] Process already removed from active_processes during cleanup")
            
            # Note: Do NOT yield in finally block - causes GeneratorExit issues
            # The stream closes naturally when generator exits
    
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
    Returns 404 if process not found (may have already completed).
    """
    process_id = request.process_id
    
    logger.info(f"[{process_id}] Cancel request received from user: {current_user.username}")
    logger.debug(f"[{process_id}] Active processes: {list(active_processes.keys())}")
    
    if process_id not in active_processes:
        logger.warning(f"[{process_id}] Process ID not found in active_processes - may have already completed")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Process ID not found"
        )
    
    process = active_processes[process_id]
    
    # Verify user owns this process
    if process["user_id"].lower() != current_user.username.lower():
        logger.warning(f"[{process_id}] User {current_user.username} attempted to cancel process owned by {process['user_id']}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to cancel this process"
        )
    
    # Set cancelled flag
    process["cancelled"] = True
    process["status"] = "cancelled"
    
    logger.info(f"[{process_id}] Process cancellation flag set successfully")
    
    return JSONResponse(
        content={
            "success": True,
            "message": "Process cancellation requested"
        }
    )


# ============================================================================
# Helper Functions
# ============================================================================

async def _create_runtime_turn_paths(correlation_id: str, process: Dict[str, Any]) -> RuntimeTurnPaths:
    """Create runtime session/turn folders for one web request."""
    try:
        uuid.UUID(correlation_id, version=4)
    except ValueError as exc:
        raise ValueError(f"Invalid correlation_id format; expected UUID v4, got: {correlation_id}") from exc

    runtime_paths = create_runtime_turn_paths(
        user_id=process.get("user_id", "localadmin"),
        session_id=process.get("session_id") or correlation_id,
        run_id=process.get("run_id") or correlation_id,
        turn_number=process.get("turn_number"),
    )
    logger.info(f"[{correlation_id}] Created runtime turn folder: {runtime_paths.turn_dir}")
    logger.info(f"[{correlation_id}] Created artifacts file: {runtime_paths.artifacts_file}")
    return runtime_paths


# ============================================================================
# Special Tools Discovery Endpoint
# ============================================================================

@router.get("/special-tools")
async def get_special_tools(current_user: AuthUser = Depends(get_current_user)):
    """
    Get available special tools with metadata for UI discovery.
    
    Returns dynamic list of special tools with:
    - name: Tool display name
    - description: What the tool does
    - examples: Sample queries that use this tool
    """
    try:
        from src.core.tools.special_tools import get_special_tool_endpoints
        
        # Get all special tool endpoints
        endpoints = get_special_tool_endpoints()
        
        # Transform to UI-friendly format
        tools = []
        seen_operations = set()  # Deduplicate by operation name
        
        for endpoint in endpoints:
            operation = endpoint.get("operation", "")
            
            # Skip duplicates
            if operation in seen_operations:
                continue
            seen_operations.add(operation)
            
            # Extract display name from operation (remove "special_tool_" prefix)
            display_name = operation.replace("special_tool_", "").replace("_", " ").title()
            
            tool_data = {
                "name": display_name,
                "description": endpoint.get("description", ""),
                "examples": endpoint.get("examples", [])
            }
            
            tools.append(tool_data)
        
        logger.info(f"Returning {len(tools)} special tools for UI")
        
        return {
            "success": True,
            "tools": tools
        }
        
    except Exception as e:
        logger.error(f"Error fetching special tools: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch special tools"
        )
