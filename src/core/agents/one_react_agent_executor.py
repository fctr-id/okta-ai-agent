"""
ReAct Agent Execution Wrapper with SSE Streaming Support

This module wraps the ReAct agent execution with:
1. Discovery phase streaming (7 thinking steps)
2. Security validation of generated code
3. Subprocess execution with progress streaming
4. Error handling and cleanup

Usage:
    executor = ReActAgentExecutor(correlation_id, user_query, deps)
    async for event in executor.execute_with_streaming():
        # Send event to frontend via SSE
        yield event
"""

import asyncio
import json
import logging
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from src.core.agents.one_react_agent import (
    execute_react_query, 
    ReactAgentDependencies,
    should_force_api_only_mode,
    check_database_health
)
from src.utils.security_config import validate_generated_code

logger = logging.getLogger(__name__)


# ============================================================================
# Event Types (Match Tako/realtime_hybrid.py format)
# ============================================================================

class EventType:
    """SSE event types matching Tako architecture"""
    STEP_START = "STEP-START"       # Discovery step begins
    STEP_END = "STEP-END"           # Discovery step completes
    STEP_PROGRESS = "STEP-PROGRESS" # Progress during subprocess execution
    STEP_TOKENS = "STEP-TOKENS"     # Token usage report
    SCRIPT_GENERATED = "SCRIPT-GENERATED"  # Generated script code
    RESULT_METADATA = "RESULT-METADATA"    # Result streaming metadata (total batches/records)
    RESULT_BATCH = "RESULT-BATCH"          # Result batch chunk
    COMPLETE = "COMPLETE"           # Final completion (no data, just signal)
    ERROR = "ERROR"                 # Error occurred


@dataclass
class ExecutionState:
    """Track execution state across phases"""
    correlation_id: str
    user_query: str
    current_step: int = 0
    total_steps: int = 7  # Typical ReAct discovery steps
    discovery_complete: bool = False
    validation_complete: bool = False
    execution_complete: bool = False
    script_path: Optional[str] = None
    final_results: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# ============================================================================
# ReAct Agent Executor
# ============================================================================

class ReActAgentExecutor:
    """
    Executes ReAct agent with SSE streaming for real-time UI updates.
    
    Three phases:
    1. Discovery: ReAct agent discovers and generates code (streams thinking)
    2. Validation: Security scan of generated code
    3. Execution: Run code in subprocess with progress streaming
    """
    
    def __init__(
        self,
        correlation_id: str,
        user_query: str,
        deps: ReactAgentDependencies,
        cancellation_check: Optional[callable] = None,
        force_api_only: bool = False
    ):
        self.correlation_id = correlation_id
        
        # Check database health and modify query if needed
        should_force_api, modified_query = should_force_api_only_mode(user_query, force_api_only)
        self.user_query = modified_query
        self.api_only_mode = should_force_api
        
        # Log if query was modified
        if modified_query != user_query:
            logger.info(f"[{correlation_id}] Query modified for API-only mode")
        
        self.deps = deps
        self.cancellation_check = cancellation_check
        
        # Pass cancellation check to dependencies if provided
        if cancellation_check:
            self.deps.cancellation_check = cancellation_check
            
        self.state = ExecutionState(
            correlation_id=correlation_id,
            user_query=user_query
        )
        
    async def execute_with_streaming(self) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Execute ReAct agent with streaming events.
        
        Yields SSE events for:
        - Each discovery step (STEP-START, STEP-END)
        - Token usage (STEP-TOKENS)
        - Validation results
        - Subprocess progress (STEP-PROGRESS)
        - Final completion (COMPLETE)
        - Errors (ERROR)
        """
        try:
            # Phase 1: Discovery (ReAct agent generates code)
            logger.info(f"[{self.correlation_id}] Phase 1: Starting ReAct discovery")
            async for event in self._execute_discovery_phase():
                yield event
            
            if self.state.error:
                yield self._create_error_event(self.state.error)
                return
            
            # Check for direct answer (Special Tool) - Skip validation/execution if no script
            if (self.state.discovery_complete and 
                self.state.final_results and 
                not self.state.final_results.get("complete_production_code") and
                self.state.final_results.get("results")):
                
                logger.info(f"[{self.correlation_id}] ⚡ Direct answer detected (no script generated)")
                
                # The results should be the markdown summary from the special tool
                special_tool_output = self.state.final_results["results"]
                
                # Extract llm_summary if results is a dict (special tool output)
                if isinstance(special_tool_output, dict) and "llm_summary" in special_tool_output:
                    content = special_tool_output["llm_summary"]
                    logger.info(f"[{self.correlation_id}] Extracted llm_summary from special tool output")
                else:
                    content = special_tool_output
                    logger.debug(f"[{self.correlation_id}] Using raw results (type: {type(special_tool_output)})")
                
                # Yield COMPLETE event with markdown content
                yield {
                    "event_type": EventType.COMPLETE,
                    "display_type": "markdown",
                    "content": content,
                    "timestamp": time.time(),
                    "is_special_tool": True
                }
                return
            
            # Phase 2: Security Validation
            logger.info(f"[{self.correlation_id}] Phase 2: Validating generated code")
            async for event in self._execute_validation_phase():
                yield event
            
            if self.state.error:
                yield self._create_error_event(self.state.error)
                return
            
            # Phase 3: Subprocess Execution
            logger.info(f"[{self.correlation_id}] Phase 3: Executing validated code")
            async for event in self._execute_subprocess_phase():
                yield event
            
            # Stream results in chunks (for large datasets)
            async for event in self._stream_results():
                yield event

        except asyncio.CancelledError:
            logger.warning(f"[{self.correlation_id}] Execution cancelled")
            yield {
                "event_type": EventType.ERROR,
                "error": "Process cancelled by user",
                "timestamp": time.time()
            }
            return
        except Exception as e:
            logger.error(f"[{self.correlation_id}] Executor failed: {e}", exc_info=True)
            yield self._create_error_event(str(e))
        finally:
            # Cleanup temporary script
            self._cleanup()
    
    async def _execute_discovery_phase(self) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Execute ReAct agent discovery with step-by-step streaming.
        
        Attaches callbacks to ReactAgentDependencies to capture:
        - step_start_callback: When agent starts a discovery step
        - step_end_callback: When agent completes a discovery step
        - step_tokens_callback: Final token usage
        """
        # Queue with size limit to prevent unbounded growth if frontend disconnects
        step_queue = asyncio.Queue(maxsize=100)
        
        # Define callbacks to capture agent progress
        async def on_step_start(data: Dict[str, Any]):
            """Called when agent starts a step"""
            self.state.current_step += 1
            
            title = data.get("title", "")
            reasoning = data.get("text", "")
            
            event = {
                "event_type": EventType.STEP_START,
                "step": self.state.current_step,
                "title": title,
                "reasoning": reasoning,
                "timestamp": data.get("timestamp", time.time())
            }
            try:
                await asyncio.wait_for(step_queue.put(event), timeout=1.0)
            except asyncio.TimeoutError:
                logger.warning(f"[{self.correlation_id}] Queue full, dropping step_start event")
        
        async def on_step_end(data: Dict[str, Any]):
            """Called when agent completes a step"""
            title = data.get("title", "")
            result_text = data.get("text", "")
            
            event = {
                "event_type": EventType.STEP_END,
                "step": self.state.current_step,
                "title": title,
                "result": result_text,
                "timestamp": data.get("timestamp", time.time())
            }
            try:
                await asyncio.wait_for(step_queue.put(event), timeout=1.0)
            except asyncio.TimeoutError:
                logger.warning(f"[{self.correlation_id}] Queue full, dropping step_end event")
        
        async def on_tokens(data: Dict[str, Any]):
            """Called with token usage info"""
            event = {
                "event_type": EventType.STEP_TOKENS,
                "input_tokens": data.get("input_tokens", 0),
                "output_tokens": data.get("output_tokens", 0),
                "total_tokens": data.get("total_tokens", 0),
                "requests": data.get("requests", 0)
            }
            try:
                await asyncio.wait_for(step_queue.put(event), timeout=1.0)
            except asyncio.TimeoutError:
                logger.warning(f"[{self.correlation_id}] Queue full, dropping tokens event")
        
        async def on_tool_call(data: Dict[str, Any]):
            """Called when a tool is invoked"""
            event = {
                "event_type": "TOOL-CALL",
                "tool_name": data.get("tool_name", ""),
                "description": data.get("description", ""),
                "timestamp": data.get("timestamp", time.time())
            }
            try:
                await asyncio.wait_for(step_queue.put(event), timeout=1.0)
            except asyncio.TimeoutError:
                logger.warning(f"[{self.correlation_id}] Queue full, dropping tool_call event")
        
        # Attach callbacks to deps
        self.deps.step_start_callback = on_step_start
        self.deps.step_end_callback = on_step_end
        self.deps.step_tokens_callback = on_tokens
        self.deps.tool_call_callback = on_tool_call
        
        # Run agent in background task
        async def run_agent():
            try:
                execution_result, usage = await execute_react_query(
                    self.user_query,
                    self.deps
                )
                
                # Store results
                self.state.discovery_complete = True
                self.state.final_results = {
                    "success": execution_result.success,
                    "execution_plan": execution_result.execution_plan,
                    "steps_taken": execution_result.steps_taken,
                    "complete_production_code": execution_result.complete_production_code,
                    "results": execution_result.results
                }
                
                # Log the final production script summary (not full content to avoid log spam)
                if execution_result.complete_production_code:
                    script_length = len(execution_result.complete_production_code)
                    script_lines = execution_result.complete_production_code.split('\n')
                    total_lines = len(script_lines)
                    logger.info(f"[{self.correlation_id}] ✅ SYNTHESIS COMPLETE: Generated final production code ({script_length} chars, {total_lines} lines)")
                    
                    # Only log first 30 and last 20 lines to avoid log flooding
                    if total_lines > 50:
                        logger.debug(f"[{self.correlation_id}] First 30 lines:")
                        for i, line in enumerate(script_lines[:30], 1):
                            logger.debug(f"[{self.correlation_id}] {i:4d} | {line}")
                        logger.debug(f"[{self.correlation_id}] ... ({total_lines - 50} lines omitted) ...")
                        logger.debug(f"[{self.correlation_id}] Last 20 lines:")
                        for i, line in enumerate(script_lines[-20:], total_lines - 19):
                            logger.debug(f"[{self.correlation_id}] {i:4d} | {line}")
                    else:
                        # Small script - log all
                        for i, line in enumerate(script_lines, 1):
                            logger.debug(f"[{self.correlation_id}] {i:4d} | {line}")
                
                if not execution_result.success:
                    self.state.error = execution_result.error or "Discovery failed"
                    # Send error event to frontend
                    await step_queue.put(self._create_error_event(self.state.error))
            
            except asyncio.CancelledError:
                logger.warning(f"[{self.correlation_id}] Agent execution cancelled inside run_agent")
                raise
            except Exception as e:
                # Check if it's a wrapped cancellation error
                if "Execution cancelled by user" in str(e):
                    logger.warning(f"[{self.correlation_id}] Agent execution cancelled (caught via exception message)")
                    raise asyncio.CancelledError("Execution cancelled by user")
                
                self.state.error = f"Discovery phase error: {str(e)}"
                logger.error(f"[{self.correlation_id}] {self.state.error}", exc_info=True)
                # Send error event to frontend
                await step_queue.put(self._create_error_event(self.state.error))
            finally:
                await step_queue.put(None)  # Signal completion
        
        # Start agent task
        agent_task = asyncio.create_task(run_agent())
        
        # Stream events as they arrive
        while True:
            # Check for cancellation
            if self.cancellation_check and self.cancellation_check():
                logger.warning(f"[{self.correlation_id}] Cancellation detected in discovery phase")
                agent_task.cancel()
                try:
                    await agent_task
                except asyncio.CancelledError:
                    logger.info(f"[{self.correlation_id}] Agent task cancelled successfully")
                except Exception as e:
                    logger.error(f"[{self.correlation_id}] Error cancelling agent task: {e}")
                
                # Ensure we stop the generator
                raise asyncio.CancelledError("Process cancelled by user")

            try:
                # Use timeout to allow periodic cancellation checks
                event = await asyncio.wait_for(step_queue.get(), timeout=0.5)
                if event is None:  # Completion signal
                    break
                yield event
            except asyncio.TimeoutError:
                continue
        
        # Wait for agent to finish
        try:
            await agent_task
        except asyncio.CancelledError:
            logger.info(f"[{self.correlation_id}] Agent task cancelled (awaited)")
            raise
        except Exception as e:
            logger.error(f"[{self.correlation_id}] Agent task failed: {e}")
        
        # After discovery completes, send the generated script
        if (self.state.discovery_complete and 
            self.state.final_results and 
            self.state.final_results.get("complete_production_code")):
            
            script_code = self.state.final_results["complete_production_code"]
            script_length = len(script_code)
            
            logger.info(f"[{self.correlation_id}] 📜 Yielding SCRIPT-GENERATED event ({script_length} chars)")
            
            yield {
                "event_type": EventType.SCRIPT_GENERATED,
                "script_code": script_code,
                "script_length": script_length,
                "timestamp": time.time()
            }
    
    async def _execute_validation_phase(self) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Validate generated code with security scanner.
        
        Checks for:
        - Unsafe imports (only allow whitelist)
        - File operations (only allow writes to src/core/data/)
        - API calls (only allow /api/v1/ endpoints)
        - Dangerous patterns (no eval/exec/subprocess)
        """
        if not self.state.final_results or not self.state.final_results.get("complete_production_code"):
            self.state.error = "No code generated to validate"
            return
        
        code = self.state.final_results["complete_production_code"]
        
        # Send validation start event
        yield {
            "event_type": EventType.STEP_START,
            "step": "validation",
            "title": "Security Validation",
            "text": "Scanning generated code for security issues",
            "timestamp": time.time()
        }
        
        # Run validation
        validation_result = validate_generated_code(code)
        
        if not validation_result.is_valid:
            self.state.error = f"Security validation failed: {', '.join(validation_result.violations)}"
            yield {
                "event_type": EventType.STEP_END,
                "step": "validation",
                "title": "Security Validation Failed",
                "text": self.state.error,
                "timestamp": time.time()
            }
            return
        
        # Validation passed
        self.state.validation_complete = True
        
        yield {
            "event_type": EventType.STEP_END,
            "step": "validation",
            "title": "Security Validation Passed",
            "text": f"Code is safe to execute (risk level: {validation_result.risk_level})",
            "timestamp": time.time()
        }
    
    async def _execute_subprocess_phase(self) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Execute validated code in subprocess with progress streaming.
        
        Uses the proven pattern from modern_execution_manager.py:
        - Write code to temporary file
        - Execute with asyncio.create_subprocess_exec
        - Capture stderr for __PROGRESS__ events
        - Stream progress to frontend
        """
        if not self.state.validation_complete:
            self.state.error = "Cannot execute: validation not complete"
            return
        
        code = self.state.final_results["complete_production_code"]
        
        # Write code to temporary file
        script_path = self._write_temp_script(code)
        self.state.script_path = script_path
        
        # Send execution start event
        yield {
            "event_type": EventType.STEP_START,
            "step": "execution",
            "title": "Executing Code",
            "text": f"Running script: {Path(script_path).name}",
            "timestamp": time.time()
        }
        
        # Execute with streaming
        try:
            async for progress_event in self._run_subprocess_with_streaming(script_path):
                yield progress_event
            
            self.state.execution_complete = True
            
            yield {
                "event_type": EventType.STEP_END,
                "step": "execution",
                "title": "Execution Complete",
                "text": "Script executed successfully",
                "timestamp": time.time()
            }
            
        except Exception as e:
            self.state.error = f"Execution failed: {str(e)}"
            yield {
                "event_type": EventType.STEP_END,
                "step": "execution",
                "title": "Execution Failed",
                "text": self.state.error,
                "timestamp": time.time()
            }
    
    def _write_temp_script(self, code: str) -> str:
        """Write code to temporary Python file and copy dependencies"""
        import shutil
        # Use generated_scripts directory at project root (same level as sqlite_db)
        project_root = Path(__file__).parent.parent.parent.parent
        temp_dir = project_root / "generated_scripts"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        script_path = temp_dir / f"react_execution_{self.correlation_id}.py"
        
        # Copy base_okta_api_client.py to the same directory so imports work
        api_client_source = Path(__file__).parent.parent / "okta" / "client" / "base_okta_api_client.py"
        api_client_dest = temp_dir / "base_okta_api_client.py"
        
        if api_client_source.exists():
            shutil.copy2(api_client_source, api_client_dest)
            logger.debug(f"[{self.correlation_id}] Copied base_okta_api_client.py to execution directory")
        else:
            logger.warning(f"[{self.correlation_id}] base_okta_api_client.py not found at {api_client_source}")
        
        # Modify code to use local import instead of src.core.okta.client
        modified_code = code.replace(
            "from src.core.okta.client.base_okta_api_client import OktaAPIClient",
            "from base_okta_api_client import OktaAPIClient"
        )
        
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(modified_code)
        
        logger.debug(f"[{self.correlation_id}] Script written to: {script_path.absolute()}")
        return str(script_path)
    
    async def _run_subprocess_with_streaming(self, script_path: str) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Execute Python script in subprocess, streaming progress events in real-time.
        
        Simple pattern: read stderr line → parse → immediately yield event.
        Based on modern_execution_manager.py proven approach.
        """
        # Determine Python executable (use venv if available)
        python_exe = self._get_python_executable()
        
        # Get script directory and filename (for cwd and execution)
        script_path_obj = Path(script_path)
        script_dir = script_path_obj.parent
        script_filename = script_path_obj.name
        
        # Create subprocess with cwd set to script directory
        proc = await asyncio.create_subprocess_exec(
            python_exe,
            "-u",  # Unbuffered output
            script_filename,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(script_dir),
            limit=1024*1024  # 1MB buffer
        )
        
        # Storage with size limits to prevent memory issues
        stdout_lines = []
        stderr_lines = []
        MAX_STDOUT_LINES = 10000  # Cap at 10k lines (~1MB assuming 100 chars/line)
        
        # Deduplication tracking for rate limit events
        last_rate_limit_time = 0
        rate_limit_cooldown = 2.0  # Only send one rate limit event per 2 seconds
        
        # Simple callback that yields events immediately
        async def handle_stderr_line(line_str: str):
            """Parse stderr line and yield event if needed - called for each line in real-time"""
            stderr_lines.append(line_str)
            
            # Check for __PROGRESS__ event
            if line_str.startswith("__PROGRESS__"):
                try:
                    json_str = line_str.replace("__PROGRESS__", "").strip()
                    progress_data = json.loads(json_str)
                    
                    return {
                        "event_type": EventType.STEP_PROGRESS,
                        "progress_type": progress_data.get("type", ""),
                        "entity": progress_data.get("entity", ""),
                        "current": progress_data.get("current", 0),
                        "total": progress_data.get("total", 0),
                        "timestamp": time.time()
                    }
                except json.JSONDecodeError:
                    logger.warning(f"[{self.correlation_id}] Invalid progress JSON: {line_str}")
            
            # Check for rate limit warnings (deduplicate to avoid spam from parallel threads)
            elif "rate limit exceeded" in line_str.lower() and "waiting" in line_str.lower():
                nonlocal last_rate_limit_time
                current_time = time.time()
                
                # Only emit rate limit event if enough time has passed since last one
                if current_time - last_rate_limit_time < rate_limit_cooldown:
                    return None  # Skip duplicate
                
                try:
                    import re
                    match = re.search(r'waiting (\d+(?:\.\d+)?) seconds', line_str.lower())
                    if match:
                        wait_seconds = int(float(match.group(1)))
                        last_rate_limit_time = current_time
                        logger.debug(f"[{self.correlation_id}] Rate limit: {wait_seconds}s")
                        return {
                            "event_type": EventType.STEP_PROGRESS,
                            "progress_type": "rate_limit",
                            "wait_seconds": wait_seconds,
                            "message": f"Rate limit - waiting {wait_seconds}s",
                            "timestamp": current_time
                        }
                except Exception as e:
                    logger.debug(f"[{self.correlation_id}] Failed to parse rate limit: {e}")
            
            return None
        
        # Define async stream readers
        async def read_stdout():
            """Read stdout line by line with size limit"""
            if proc.stdout:
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    
                    # Prevent unbounded growth
                    if len(stdout_lines) >= MAX_STDOUT_LINES:
                        logger.warning(f"[{self.correlation_id}] stdout buffer limit reached, truncating old lines")
                        stdout_lines[:] = stdout_lines[-5000:]  # Keep last 5k lines
                    
                    stdout_lines.append(line.decode('utf-8'))
        
        async def read_stderr_and_yield():
            """Read stderr and yield events immediately - no queuing"""
            if proc.stderr:
                while True:
                    # Check for cancellation periodically
                    if self.cancellation_check and self.cancellation_check():
                        logger.warning(f"[{self.correlation_id}] Cancellation detected in stderr reader")
                        raise asyncio.CancelledError("Process cancelled by user")

                    try:
                        # Use timeout to allow periodic cancellation checks
                        line = await asyncio.wait_for(proc.stderr.readline(), timeout=0.5)
                    except asyncio.TimeoutError:
                        continue

                    if not line:
                        break
                    line_str = line.decode('utf-8').strip()
                    if not line_str:
                        continue
                    
                    # Parse line and get event if any
                    event = await handle_stderr_line(line_str)
                    if event:
                        logger.info(f"[{self.correlation_id}] Yielding event: {event.get('progress_type', 'unknown')}")
                        yield event
        
        # Start stdout reading (stderr handled in generator below)
        stdout_task = asyncio.create_task(read_stdout())
        
        try:
            # Yield events from stderr as they arrive
            async for event in read_stderr_and_yield():
                yield event
            
            # Wait for stdout to complete
            await stdout_task
            
            # Wait for process to complete
            await proc.wait()
            
            # Check for errors
            if proc.returncode != 0:
                error_msg = f"Script exited with code {proc.returncode}"
                if stderr_lines:
                    last_errors = "\n".join(stderr_lines[-20:])
                    logger.error(f"[{self.correlation_id}] Script failed. Last 20 stderr lines:\n{last_errors}")
                    error_msg = f"Script execution failed: {last_errors}"
                
                # Yield error event to frontend so it stops waiting
                yield self._create_error_event(error_msg)
                raise RuntimeError(f"Script exited with code {proc.returncode}")
            
            logger.info(f"[{self.correlation_id}] Script completed successfully")
            
            # Parse stdout
            stdout = ''.join(stdout_lines)
            results_data = self._parse_script_output(stdout)
            if results_data:
                self.state.final_results["script_output"] = results_data
            
        except asyncio.CancelledError:
            logger.warning(f"[{self.correlation_id}] Subprocess execution cancelled")
            raise
        except Exception as e:
            logger.error(f"[{self.correlation_id}] Subprocess failed: {e}", exc_info=True)
            raise
        finally:
            # Ensure process is terminated
            if proc.returncode is None:
                try:
                    proc.terminate()
                    # Give it a moment to terminate gracefully
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        logger.warning(f"[{self.correlation_id}] Process did not terminate, killing...")
                        proc.kill()
                        await proc.wait()
                except Exception as e:
                    logger.error(f"[{self.correlation_id}] Error cleaning up process: {e}")
    
    async def _stream_results(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream results in chunks for large datasets"""
        results = self.state.final_results.get("script_output", {})
        display_type = results.get("display_type", "table")
        
        # Handle Markdown/Text content
        if display_type == "markdown":
            content = results.get("content", "")
            yield {
                "event_type": EventType.COMPLETE,
                "success": True,
                "display_type": "markdown",
                "content": content,
                "execution_plan": self.state.final_results.get("execution_plan", ""),
                "timestamp": time.time()
            }
            return

        # Handle Table/Data content
        data = results.get("data", [])
        headers = results.get("headers", [])
        count = results.get("count", 0)
        execution_plan = self.state.final_results.get("execution_plan", "")
        
        # Chunk size for streaming (500 records per batch)
        CHUNK_SIZE = 500
        
        # Only chunk if dataset is large (> 750 records = 1.5x chunk size)
        if len(data) > CHUNK_SIZE * 1.5:
            # Large dataset - stream in chunks
            total_chunks = (len(data) + CHUNK_SIZE - 1) // CHUNK_SIZE
            logger.info(f"[{self.correlation_id}] Streaming {len(data)} results in {total_chunks} chunks")
            
            # Send metadata event first
            yield {
                "event_type": EventType.RESULT_METADATA,
                "display_type": "table",
                "total_batches": total_chunks,
                "total_records": len(data),
                "headers": headers,
                "execution_plan": execution_plan,
                "timestamp": time.time()
            }
            
            # Stream chunks
            for i in range(0, len(data), CHUNK_SIZE):
                chunk_data = data[i:i + CHUNK_SIZE]
                chunk_number = i // CHUNK_SIZE + 1
                is_final = i + CHUNK_SIZE >= len(data)
                
                yield {
                    "event_type": EventType.RESULT_BATCH,
                    "results": chunk_data,
                    "batch_number": chunk_number,
                    "total_batches": total_chunks,
                    "is_final": is_final,
                    "timestamp": time.time()
                }
                
                # Small delay between chunks (10ms)
                await asyncio.sleep(0.01)
            
            # Send final completion signal
            yield {
                "event_type": EventType.COMPLETE,
                "success": True,
                "count": count,
                "timestamp": time.time()
            }
        else:
            # Small dataset - send in single COMPLETE event (backward compatible)
            logger.info(f"[{self.correlation_id}] Sending {len(data)} results in single COMPLETE event")
            yield {
                "event_type": EventType.COMPLETE,
                "success": True,
                "display_type": "table",
                "results": data,
                "count": count,
                "execution_plan": execution_plan,
                "headers": headers,
                "timestamp": time.time()
            }
    
    def _get_python_executable(self) -> str:
        """Get Python executable path (prefer venv)"""
        venv_python = Path("venv/Scripts/python.exe")
        if venv_python.exists():
            return str(venv_python)
        
        # Fallback to system python
        return "python"
    
    def _parse_script_output(self, stdout: str) -> Optional[Dict[str, Any]]:
        """
        Parse JSON results from script stdout with Vuetify headers support.
        
        Expects script to print JSON between markers:
        ================================================================================
        QUERY RESULTS
        ================================================================================
        {
          "data": [...],
          "headers": [...],
          "count": N
        }
        ================================================================================
        """
        try:
            # Look for JSON between the markers
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
                json_str = '\n'.join(json_lines)
                parsed_output = json.loads(json_str)
                
                # Support both old format (array) and new format (object with data/headers)
                if isinstance(parsed_output, list):
                    # Old format: just an array - auto-generate headers
                    return {
                        "display_type": "table",
                        "data": parsed_output,
                        "count": len(parsed_output)
                    }
                elif isinstance(parsed_output, dict):
                    # Check for explicit display_type
                    display_type = parsed_output.get("display_type", "table")
                    
                    if display_type == "markdown":
                        return {
                            "display_type": "markdown",
                            "content": parsed_output.get("content", ""),
                            "count": 1
                        }
                    elif "data" in parsed_output:
                        # New format: object with data, headers, count
                        return {
                            "display_type": "table",
                            "data": parsed_output.get("data", []),
                            "headers": parsed_output.get("headers", []),
                            "count": parsed_output.get("count", len(parsed_output.get("data", [])))
                        }
                    else:
                        # Fallback: treat as single result
                        return {
                            "display_type": "table",
                            "data": [parsed_output] if parsed_output else [],
                            "count": 1 if parsed_output else 0
                        }
                else:
                    # Fallback: treat as single result
                    return {
                        "display_type": "table",
                        "data": [parsed_output] if parsed_output else [],
                        "count": 1 if parsed_output else 0
                    }
        except Exception as e:
            logger.warning(f"[{self.correlation_id}] Failed to parse script output as JSON: {e}")
            # Return raw output if JSON parsing fails
            return {
                "raw_output": stdout,
                "count": 0
            }
        
        return None
    
    def _create_error_event(self, error: str) -> Dict[str, Any]:
        """Create error event"""
        return {
            "event_type": EventType.ERROR,
            "error": error,
            "timestamp": time.time()
        }
    
    def _cleanup(self):
        """Clean up temporary files"""
        if self.state.script_path and os.path.exists(self.state.script_path):
            try:
                # Check if we're in debug mode (via env var)
                keep_scripts = os.getenv("KEEP_TEMP_SCRIPTS", "false").lower() == "true"
                
                if keep_scripts:
                    logger.debug(f"[{self.correlation_id}] Script kept for debugging: {self.state.script_path}")
                else:
                    os.remove(self.state.script_path)
                    logger.debug(f"[{self.correlation_id}] Cleaned up script: {self.state.script_path}")
                    
                    # Also cleanup the copied base_okta_api_client.py if it exists
                    script_dir = Path(self.state.script_path).parent
                    api_client_copy = script_dir / "base_okta_api_client.py"
                    if api_client_copy.exists():
                        os.remove(api_client_copy)
                        
            except Exception as e:
                logger.warning(f"[{self.correlation_id}] Failed to cleanup script: {e}")
