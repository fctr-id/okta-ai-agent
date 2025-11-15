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

from src.core.agents.one_react_agent import execute_react_query, ReactAgentDependencies
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
    COMPLETE = "COMPLETE"           # Final completion
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
        deps: ReactAgentDependencies
    ):
        self.correlation_id = correlation_id
        self.user_query = user_query
        self.deps = deps
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
            
            # Final completion
            yield self._create_complete_event()
            
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
        step_queue = asyncio.Queue()
        
        # Define callbacks to capture agent progress
        async def on_step_start(data: Dict[str, Any]):
            """Called when agent starts a step"""
            self.state.current_step += 1
            event = {
                "event_type": EventType.STEP_START,
                "step": self.state.current_step,
                "title": data.get("title", ""),
                "text": data.get("text", ""),
                "timestamp": data.get("timestamp", time.time())
            }
            await step_queue.put(event)
        
        async def on_step_end(data: Dict[str, Any]):
            """Called when agent completes a step"""
            event = {
                "event_type": EventType.STEP_END,
                "step": self.state.current_step,
                "title": data.get("title", ""),
                "text": data.get("text", ""),
                "timestamp": data.get("timestamp", time.time())
            }
            await step_queue.put(event)
        
        async def on_tokens(data: Dict[str, Any]):
            """Called with token usage info"""
            event = {
                "event_type": EventType.STEP_TOKENS,
                "input_tokens": data.get("input_tokens", 0),
                "output_tokens": data.get("output_tokens", 0),
                "total_tokens": data.get("total_tokens", 0),
                "requests": data.get("requests", 0)
            }
            await step_queue.put(event)
        
        # Attach callbacks to deps
        self.deps.step_start_callback = on_step_start
        self.deps.step_end_callback = on_step_end
        self.deps.step_tokens_callback = on_tokens
        
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
                
                if not execution_result.success:
                    self.state.error = execution_result.error or "Discovery failed"
                
            except Exception as e:
                self.state.error = f"Discovery phase error: {str(e)}"
                logger.error(f"[{self.correlation_id}] {self.state.error}", exc_info=True)
            finally:
                await step_queue.put(None)  # Signal completion
        
        # Start agent task
        agent_task = asyncio.create_task(run_agent())
        
        # Stream events as they arrive
        while True:
            event = await step_queue.get()
            if event is None:  # Completion signal
                break
            yield event
        
        # Wait for agent to finish
        await agent_task
    
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
        temp_dir = Path("src/core/data/testing")
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
        
        logger.info(f"[{self.correlation_id}] ==========================================")
        logger.info(f"[{self.correlation_id}] Script written to: {script_path.absolute()}")
        logger.info(f"[{self.correlation_id}] ==========================================")
        return str(script_path)
    
    async def _run_subprocess_with_streaming(self, script_path: str) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Execute Python script in subprocess, streaming progress events.
        
        Expects script to print __PROGRESS__ events to stderr:
        __PROGRESS__ {"type": "entity_start", "entity": "users", "total": 100}
        __PROGRESS__ {"type": "entity_progress", "current": 50, "total": 100}
        __PROGRESS__ {"type": "entity_complete", "entity": "users", "count": 100}
        """
        # Determine Python executable (use venv if available)
        python_exe = self._get_python_executable()
        
        # Get script directory and filename (for cwd and execution)
        script_path_obj = Path(script_path)
        script_dir = script_path_obj.parent
        script_filename = script_path_obj.name
        
        # Create subprocess with cwd set to script directory
        # Use just the filename since cwd is set to the script directory
        proc = await asyncio.create_subprocess_exec(
            python_exe,
            "-u",  # Unbuffered output
            script_filename,  # Just the filename, not full path
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(script_dir)  # Set working directory to script location
        )
        
        # Read stderr for progress events
        stderr_lines = []  # Collect all stderr for error reporting
        async def read_stderr():
            if proc.stderr:
                async for line in proc.stderr:
                    line_str = line.decode('utf-8').strip()
                    stderr_lines.append(line_str)  # Store for error reporting
                    
                    # Check for progress event
                    if line_str.startswith("__PROGRESS__"):
                        try:
                            json_str = line_str.replace("__PROGRESS__", "").strip()
                            progress_data = json.loads(json_str)
                            
                            # Emit STEP-PROGRESS event
                            yield {
                                "event_type": EventType.STEP_PROGRESS,
                                "progress_type": progress_data.get("type", ""),
                                "entity": progress_data.get("entity", ""),
                                "current": progress_data.get("current", 0),
                                "total": progress_data.get("total", 0),
                                "timestamp": time.time()
                            }
                        except json.JSONDecodeError:
                            logger.warning(f"[{self.correlation_id}] Invalid progress JSON: {line_str}")
                    else:
                        # Log other stderr output
                        logger.error(f"[{self.correlation_id}] Script stderr: {line_str}")
        
        # Read stdout for final results
        async def read_stdout():
            output = []
            if proc.stdout:
                async for line in proc.stdout:
                    line_str = line.decode('utf-8')
                    output.append(line_str)
                    # Log stdout in real-time
                    logger.debug(f"[{self.correlation_id}] Script output: {line_str.strip()}")
            return ''.join(output)
        
        # Wait for both streams and process to complete
        try:
            stdout_task = asyncio.create_task(read_stdout())
            
            # Stream stderr events
            async for event in read_stderr():
                yield event
            
            # Wait for process completion
            await proc.wait()
            
            # Get stdout
            stdout = await stdout_task
            
            if proc.returncode != 0:
                # Log stderr for debugging
                if stderr_lines:
                    logger.error(f"[{self.correlation_id}] Script stderr output:\n" + "\n".join(stderr_lines))
                raise RuntimeError(f"Script exited with code {proc.returncode}. Check logs for stderr output.")
            
            logger.info(f"[{self.correlation_id}] Script completed successfully")
            
            # Parse stdout for JSON results
            results_data = self._parse_script_output(stdout)
            
            # Store results in state
            if results_data:
                self.state.final_results["script_output"] = results_data
            
        except Exception as e:
            logger.error(f"[{self.correlation_id}] Subprocess execution failed: {e}", exc_info=True)
            
            # Try to kill process if still running
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            
            raise
    
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
                        "data": parsed_output,
                        "count": len(parsed_output)
                    }
                elif isinstance(parsed_output, dict) and "data" in parsed_output:
                    # New format: object with data, headers, count
                    return {
                        "data": parsed_output.get("data", []),
                        "headers": parsed_output.get("headers", []),
                        "count": parsed_output.get("count", len(parsed_output.get("data", [])))
                    }
                else:
                    # Fallback: treat as single result
                    return {
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
    
    def _create_complete_event(self) -> Dict[str, Any]:
        """Create final completion event with results and headers"""
        results = self.state.final_results.get("script_output", {})
        
        event = {
            "event_type": EventType.COMPLETE,
            "success": True,
            "results": results.get("data", []),
            "count": results.get("count", 0),
            "execution_plan": self.state.final_results.get("execution_plan", ""),
            "timestamp": time.time()
        }
        
        # Include headers if present for Vuetify table
        if "headers" in results:
            event["headers"] = results["headers"]
        
        return event
    
    def _create_error_event(self, error: str) -> Dict[str, Any]:
        """Create error event"""
        return {
            "event_type": EventType.ERROR,
            "error": error,
            "timestamp": time.time()
        }
    
    def _cleanup(self):
        """Clean up temporary files - DISABLED for debugging"""
        if self.state.script_path and os.path.exists(self.state.script_path):
            # Comment out cleanup to debug script errors
            logger.info(f"[{self.correlation_id}] Script kept for debugging: {self.state.script_path}")
            # try:
            #     os.remove(self.state.script_path)
            #     logger.info(f"[{self.correlation_id}] Cleaned up script: {self.state.script_path}")
            # except Exception as e:
            #     logger.warning(f"[{self.correlation_id}] Failed to cleanup script: {e}")
