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
import time
import uuid
from typing import Dict, Any, AsyncGenerator

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from src.config.settings import Settings
from src.core.security.dependencies import get_current_user
from src.core.okta.sync.models import AuthUser
from src.core.agents.one_react_agent_executor import ReActAgentExecutor, EventType
from src.core.agents.one_react_agent import ReactAgentDependencies
from src.core.okta.client.base_okta_api_client import OktaAPIClient
from src.utils.logging import get_logger, set_correlation_id

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
    
    Events:
    - STEP-START: Discovery step begins (title, text)
    - STEP-END: Discovery step completes (title, text)
    - STEP-PROGRESS: Subprocess progress (entity, current, total)
    - STEP-TOKENS: Token usage (input, output, total)
    - COMPLETE: Final completion (results)
    - ERROR: Error occurred (error message)
    """
    set_correlation_id(process_id)
    
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
    
    async def event_generator() -> AsyncGenerator[Dict[str, Any], None]:
        """Generate SSE events from ReAct execution"""
        try:
            # Update status
            process["status"] = "executing"
            
            # Create dependencies for agent
            deps = await _create_react_dependencies(
                correlation_id=process_id,
                user_query=process["query"]
            )
            
            # Create executor
            executor = ReActAgentExecutor(
                correlation_id=process_id,
                user_query=process["query"],
                deps=deps
            )
            
            # Stream events
            async for event in executor.execute_with_streaming():
                # Check for cancellation
                if process.get("cancelled", False):
                    logger.info(f"[{process_id}] Process cancelled by user")
                    error_data = {
                        "type": "ERROR",
                        "error": "Process cancelled by user",
                        "timestamp": time.time()
                    }
                    yield f"event: ERROR\ndata: {json.dumps(error_data)}\n\n"
                    break
                
                # Convert event to SSE format (string)
                event_type = event.get("type", "message")
                yield f"event: {event_type}\ndata: {json.dumps(event)}\n\n"
                
                # Small delay to prevent overwhelming frontend
                await asyncio.sleep(0.01)
            
            # Mark as complete
            process["status"] = "complete"
            logger.info(f"[{process_id}] ReAct process completed")
            
        except Exception as e:
            logger.error(f"[{process_id}] Stream error: {e}", exc_info=True)
            process["status"] = "error"
            
            error_data = {
                "type": "ERROR",
                "error": str(e),
                "timestamp": time.time()
            }
            yield f"event: ERROR\ndata: {json.dumps(error_data)}\n\n"
        
        finally:
            # Cleanup after 5 minutes
            asyncio.create_task(_cleanup_process(process_id, delay=300))
    
    return EventSourceResponse(event_generator())


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

async def _create_react_dependencies(
    correlation_id: str,
    user_query: str
) -> ReactAgentDependencies:
    """
    Create ReactAgentDependencies with all required resources.
    
    This mirrors the setup in scripts/okta_react_agent_test.py.
    """
    import aiohttp
    import sqlite3
    from pathlib import Path
    
    # Get Okta credentials from settings (OktaAPIClient reads from env vars internally)
    okta_domain = settings.OKTA_CLIENT_ORGURL
    okta_token = settings.OKTA_API_TOKEN
    
    if not okta_domain or not okta_token:
        raise ValueError("OKTA_CLIENT_ORGURL and OKTA_API_TOKEN must be set in environment")
    
    # Create Okta client (reads credentials from env)
    okta_client = OktaAPIClient()
    
    # Load endpoints (lightweight)
    endpoints = []  # Would load from API catalog
    
    # Load lightweight entities
    lightweight_entities = {}  # Would load from SQLite
    
    # Create SQLite connection using settings
    db_path = Path(settings.SQLITE_PATH)
    sqlite_conn = sqlite3.connect(str(db_path))
    
    # Create operation mapping
    operation_mapping = {}  # Would load from config
    
    # Create dependencies
    deps = ReactAgentDependencies(
        correlation_id=correlation_id,
        endpoints=endpoints,
        lightweight_entities=lightweight_entities,
        okta_client=okta_client,
        sqlite_connection=sqlite_conn,
        operation_mapping=operation_mapping,
        user_query=user_query
    )
    
    return deps


async def _cleanup_process(process_id: str, delay: int = 300):
    """Clean up process tracking entry after delay"""
    await asyncio.sleep(delay)
    
    if process_id in active_processes:
        logger.info(f"[{process_id}] Cleaning up process tracking")
        del active_processes[process_id]
