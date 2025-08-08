"""
Realtime Hybrid Execution Router - Modern Execution Manager Integration

This module provides SSE streaming integration with the Modern Execution Manager
while maintaining full API contracts and frontend compatibility.

Key Features:
- Modern Execution Manager integration via execute_query() method
- SSE (Server-Sent Events) streaming for real-time updates
- Plan and step status callbacks for live progress updates
- Enhanced error handling and database health checking
- Chunked streaming for large result sets
- Full API contract compatibility with existing frontend
"""

import asyncio
import os
import uuid
import json
import re
import time
from enum import Enum
from typing import Dict, Any, AsyncGenerator, List, Optional, Tuple

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from fastapi import APIRouter, HTTPException, Request, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from html_sanitizer import Sanitizer

# --- Modern Execution Manager Imports ---
from src.core.orchestration.modern_execution_manager import ModernExecutionManager

# --- Project-specific Imports ---
from src.core.security.dependencies import get_current_user
from src.core.okta.sync.models import AuthUser

from src.utils.error_handling import BaseError, format_error_for_user
from src.utils.logging import get_logger, set_correlation_id

# Using main "okta_ai_agent" namespace for unified logging across all components
logger = get_logger("okta_ai_agent")

# --- Configuration ---
RESULT_STREAM_CHUNK_SIZE = int(os.getenv("RESULT_STREAM_CHUNK_SIZE", "500"))  # Reduced from 1000 for faster streaming
RESULT_STREAM_DELAY = float(os.getenv("RESULT_STREAM_DELAY", "0.01"))  # Configurable delay between chunks

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

# --- Chunked Streaming Support ---
def _chunk_large_response(data: Dict[str, Any], chunk_size: int = None) -> List[Dict[str, Any]]:
    """
    Chunk large response data for streaming to prevent large JSON payloads
    Args:
        data: The response data dictionary
        chunk_size: Number of records per chunk (defaults to RESULT_STREAM_CHUNK_SIZE env var)
    Returns:
        List of chunks to stream
    """
    # Use environment variable if chunk_size not provided
    if chunk_size is None:
        chunk_size = RESULT_STREAM_CHUNK_SIZE
        
    if isinstance(data, dict) and 'formatted_response' in data:
        formatted_response = data['formatted_response']
        if isinstance(formatted_response.get('content'), list):
            # Large table data - chunk the content array
            content_array = formatted_response['content']
            # Only chunk if dataset is significantly large (increased threshold)
            # This reduces unnecessary chunking for medium-sized datasets
            if len(content_array) > (chunk_size * 1.5):  # Only chunk if 50% larger than chunk_size
                logger.info(f" CHUNKED STREAMING: Breaking {len(content_array)} records into chunks of {chunk_size}")
                # Create chunks
                chunks = []
                for i in range(0, len(content_array), chunk_size):
                    chunk_data = content_array[i:i + chunk_size]
                    chunk = {
                        **data,  # Copy all other data (process_id, status, etc.)
                        'formatted_response': {
                            **formatted_response,  # Copy metadata, display_type, etc.
                            'content': chunk_data
                        },  
                        'chunk_info': {
                            'chunk_number': i // chunk_size + 1,
                            'total_chunks': (len(content_array) + chunk_size - 1) // chunk_size,
                            'chunk_size': len(chunk_data),
                            'total_size': len(content_array),
                            'is_final_chunk': i + chunk_size >= len(content_array)
                        }
                    }
                    chunks.append(chunk)
                return chunks
    
    # Not chunkable or small data - return as single chunk
    return [data]

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

# Global modern execution manager instance
modern_executor = ModernExecutionManager()


async def get_last_sync_info_for_realtime() -> Dict[str, Any]:
    """Get sync timestamp for the most recent successful sync (realtime version)"""
    try:
        from src.core.okta.sync.operations import DatabaseOperations
        from src.config.settings import settings
        from sqlalchemy import text
        
        db = DatabaseOperations()
        
        # Simple query that just gets the timestamp
        query = """
        SELECT 
            end_time
        FROM sync_history
        WHERE tenant_id = :tenant_id
        AND success = 1
        ORDER BY start_time DESC
        LIMIT 1
        """
        
        # Execute query with parameters
        params = {"tenant_id": settings.tenant_id}
        
        # Use session to execute query
        async with db.get_session() as session:
            sql_text = text(query)
            result = await session.execute(sql_text, params)
            row = result.fetchone()
            
            # Default response if no data
            if not row or not row[0]:
                return {"last_sync": "No data"}
            
            # Get timestamp as string from result
            timestamp_str = row[0]
            
            # Return the timestamp as-is - frontend will handle formatting
            return {"last_sync": timestamp_str}
        
    except Exception as e:
        # Keep error logging (always important)
        logger.error(f"Error retrieving sync timestamp for realtime: {str(e)}")
        return {"last_sync": "Error"}





async def execute_plan_and_stream(
    process_id: str,
    query: str,
    user: AuthUser | None
) -> AsyncGenerator[Dict[str, str], None]:
    """
    Execute query using Modern Execution Manager exactly like test_query_1.py.
    
    Uses execute_query() for complete end-to-end execution with:
    - Single correlation ID (process_id) for isolation between users
    - Single planning execution (no duplicates)
    - Built-in Results Formatter processing
    - Comprehensive logging and error handling
    """
    global active_processes
    set_correlation_id(process_id)
    logger.info(f"[{process_id}] Starting Modern Execution Manager execution (test_query_1.py pattern) for query: \"{query}\"")

    def check_cancellation() -> bool:
        """Check if the process has been cancelled"""
        proc_data = active_processes.get(process_id)
        cancelled_by_status = proc_data.get("status") == ProcessStatus.CANCELLED if proc_data else False
        explicitly_cancelled_flag = proc_data.get("cancelled", False) if proc_data else True
        
        cancelled = cancelled_by_status or explicitly_cancelled_flag
        if cancelled:
            logger.info(f"[{process_id}] Cancellation detected")
            # Use proper cancel method instead of direct manipulation
            modern_executor.cancel_query(process_id, "Cancellation detected during execution")
        return cancelled

    try:
        if process_id not in active_processes:
            logger.error(f"[{process_id}] Process data missing at execution start. Aborting.")
            missing_process_event = {
                "type": "error",
                "content": {
                    'process_id': process_id, 
                    'status': ProcessStatus.ERROR.value, 
                    'message': 'Internal error: Process data lost before execution.'
                }
            }
            yield json.dumps(missing_process_event) + "\n"
            if RESULT_STREAM_DELAY > 0:
                await asyncio.sleep(RESULT_STREAM_DELAY)
            return

        # Update status to running
        active_processes[process_id]["status"] = ProcessStatus.RUNNING_EXECUTION
        status_event = {
            "type": "status",
            "content": {
                'process_id': process_id,
                'status': ProcessStatus.RUNNING_EXECUTION.value,
                'message': 'Executing with Modern Execution Manager (test_query_1.py pattern)'
            }
        }
        yield json.dumps(status_event) + "\n"
        if RESULT_STREAM_DELAY > 0:
            await asyncio.sleep(RESULT_STREAM_DELAY)

        # Store step info to yield when plan is ready
        step_info_ready = asyncio.Event()
        step_info_data = None
        
        # Event queue for step status updates
        step_status_queue = asyncio.Queue()

        # Set up callback to capture step info when plan is ready (before execution starts)
        async def on_plan_ready(execution_plan):
            nonlocal step_info_data
            logger.info(f"[{process_id}] on_plan_ready callback triggered with {len(execution_plan.steps)} steps")
            step_info_data = [
                {
                    'id': i,
                    'tool_name': step.tool_name,
                    'operation': getattr(step, 'operation', None),
                    'entity': getattr(step, 'entity', None),
                    'query_context': step.query_context,
                    'critical': step.critical,
                    'status': 'pending'  # Steps start as pending
                }
                for i, step in enumerate(execution_plan.steps)
            ]
            logger.info(f"[{process_id}] on_plan_ready - step_info_data created: {step_info_data}")
            step_info_ready.set()
            logger.info(f"[{process_id}] on_plan_ready - step_info_ready event set")
            
            # IMMEDIATE YIELD: Send step_plan_info event immediately when plan is ready
            logger.info(f"[{process_id}] Sending step_plan_info event with {len(step_info_data)} steps")
            plan_event = {
                "type": "plan",
                "content": {
                    'process_id': process_id, 
                    'steps': step_info_data
                }
            }
            await step_status_queue.put(json.dumps(plan_event) + "\n")

        async def on_step_status(step_number, step_type, status):
            """Callback when step status changes - send real-time step updates"""
            try:
                step_status_data = {
                    'process_id': process_id,
                    'step_number': step_number,
                    'step_name': step_type,  # Use actual step type from execution manager
                    'status': status  # running, completed, error
                }
                
                # Log error status for debugging
                if status == 'error':
                    logger.error(f"[{process_id}] ERROR STATUS - Step {step_number} ({step_type}) failed")
                
                # Create step status event in frontend format
                step_event = {
                    "type": "step_status",
                    "content": step_status_data
                }
                
                # Queue the step status event
                await step_status_queue.put(json.dumps(step_event) + "\n")
                
                logger.info(f"[{process_id}] Step status sent: {step_number} - {step_type} - {status}")
            except Exception as e:
                logger.warning(f"[{process_id}] Step status callback error: {e}")

        # Set the callbacks before executing
        modern_executor.plan_ready_callback = on_plan_ready
        modern_executor.step_status_callback = on_step_status
        
        async def on_planning_phase(phase_status: str):
            # Map phase_status directly to status content
            if phase_status in ("planning_start", "planning_complete"):
                phase_event = {
                    "type": "status",
                    "content": {
                        'process_id': process_id,
                        'status': phase_status,
                        'message': 'Planning started' if phase_status == 'planning_start' else 'Planning completed'
                    }
                }
                await step_status_queue.put(json.dumps(phase_event) + "\n")
        modern_executor.planning_phase_callback = on_planning_phase

        # Execute using EXACT same pattern as test_query_1.py - ONE call only!
        logger.info(f"[{process_id}] Executing with Modern Execution Manager (same as test_query_1.py)...")
        
        # CONCURRENT EXECUTION: Start execution and process events concurrently
        # Create a task for the execution
        execution_task = asyncio.create_task(modern_executor.execute_query(query))
        
        # Process events from the queue while execution is running
        while not execution_task.done():
            try:
                # Wait for either an event or the execution to complete (with short timeout)
                event = await asyncio.wait_for(step_status_queue.get(), timeout=0.1)
                yield event
                if RESULT_STREAM_DELAY > 0:
                    await asyncio.sleep(RESULT_STREAM_DELAY)
                step_status_queue.task_done()
            except asyncio.TimeoutError:
                # No event received, continue checking if execution is done
                continue
                step_status_queue.task_done()
            except asyncio.TimeoutError:
                # No event received, continue checking if execution is done
                continue
        
        # Get the execution result
        result = await execution_task
        
        # Process any remaining events after execution completes
        while not step_status_queue.empty():
            try:
                step_event = step_status_queue.get_nowait()
                yield step_event
                if RESULT_STREAM_DELAY > 0:
                    await asyncio.sleep(RESULT_STREAM_DELAY)
                step_status_queue.task_done()
            except asyncio.QueueEmpty:
                break
        
        # Clear callbacks post-execution (still inside try)
        modern_executor.plan_ready_callback = None
        modern_executor.step_status_callback = None
        modern_executor.planning_phase_callback = None

        # Log execution summary
        logger.info(f"[{process_id}] EXECUTION RESULTS:")
        logger.info(f"[{process_id}] Overall Success: {result.get('success', False)}")
        logger.info(f"[{process_id}] Correlation ID: {result.get('correlation_id', process_id)}")
        logger.info(f"[{process_id}] Total Steps: {result.get('total_steps', 0)}")
        logger.info(f"[{process_id}] Successful Steps: {result.get('successful_steps', 0)}")
        logger.info(f"[{process_id}] Failed Steps: {result.get('failed_steps', 0)}")
        
        # Get step results for logging and status updates (exact same as test_query_1.py)
        step_results = result.get('step_results', [])
        
        # Log step details (exact same as test_query_1.py)
        if step_results:
            logger.info(f"[{process_id}] STEP EXECUTION DETAILS:")
            for i, step_result in enumerate(step_results, 1):
                success = step_result.get('success', False)
                step_type = step_result.get('step_type', 'unknown')
                status = "SUCCESS" if success else "FAILED"
                logger.info(f"[{process_id}]    {status} Step {i} ({step_type})")
                if step_result.get('error'):
                    logger.info(f"[{process_id}]       Error: {step_result['error']}")
                elif step_result.get('result_type'):
                    logger.info(f"[{process_id}]       Result: {step_result['result_type']}")
        
        # Get formatted response (execute_query already handles Results Formatter)
        formatted_response = result.get('processed_summary', {})
        
        # Extract execution statistics from result
        failed_steps = result.get('failed_steps', 0)
        successful_steps = result.get('successful_steps', 0)
        total_steps = result.get('total_steps', 0)
        overall_success = result.get('success', False)
        
        # Process execution results and send appropriate SSE events
        logger.info(f"[{process_id}] Modern Execution Manager completed - processing results for streaming")
        
        # Check for planning failures or execution failures
        if not overall_success or failed_steps > 0:
            # Planning failed or some steps failed
            active_processes[process_id]["status"] = ProcessStatus.COMPLETED_WITH_ERRORS
            
            # Determine appropriate error message and type
            error_type = "execution_error"  # Default type
            if total_steps == 0 and not overall_success:
                # Planning failure - no steps were generated
                error_message = "Planning failed: Unable to generate execution plan"
                error_type = "planning_error"
                logger.error(f"[{process_id}] Planning failure detected - no steps generated")
            else:
                # Step execution failures - be more specific about what failed
                failed_step_types = []
                results_formatter_failed = False
                
                for step_result in step_results:
                    if not step_result.get('success', True):
                        step_type = step_result.get('step_type', 'unknown')
                        if step_type == 'results_formatter':
                            results_formatter_failed = True
                        else:
                            failed_step_types.append(step_type)
                
                # Create specific error message based on failure types
                if results_formatter_failed:
                    error_message = "Results processing failed: Unable to format query results"
                    error_type = "results_formatter_error"
                elif failed_step_types:
                    unique_types = list(set(failed_step_types))
                    if len(unique_types) == 1:
                        step_type = unique_types[0].upper()
                        error_message = f"{step_type} execution failed: Unable to complete {step_type.lower()} operations"
                        error_type = f"{step_type.lower()}_error"
                    else:
                        error_message = f"Multiple step failures: {', '.join(unique_types)} operations failed"
                        error_type = "multiple_step_errors"
                else:
                    error_message = f"Execution completed with {failed_steps} failed steps"
                    error_type = "execution_error"
                
                logger.error(f"[{process_id}] Step execution failures detected - {error_type}: {error_message}")
            
            # Send step status updates for failed steps (if any steps existed)
            for i, step_result in enumerate(step_results):
                if not step_result.get('success', True):
                    step_error = step_result.get('error', 'Step execution failed')
                    step_type = step_result.get('step_type', 'unknown')
                    
                    step_error_event = {
                        "type": "step_error",
                        "content": {
                            'process_id': process_id,
                            'step_index': i,  # 0-based index
                            'step_type': step_type,  # Include step type for frontend
                            'status': 'error',
                            'operation_status': 'error',
                            'error_message': step_error,
                            'error_type': error_type  # Add error type classification
                        }
                    }
                    
                    yield json.dumps(step_error_event) + "\n"
                    if RESULT_STREAM_DELAY > 0:
                        await asyncio.sleep(RESULT_STREAM_DELAY)
            
            # Send error event with enhanced error information
            error_event = {
                "type": "error",
                "content": {
                    'process_id': process_id,
                    'status': ProcessStatus.COMPLETED_WITH_ERRORS.value,
                    'message': error_message,
                    'error_type': error_type,  # Add specific error type for frontend
                    'failed_steps': failed_steps,
                    'total_steps': total_steps,
                    'error_details': {
                        'planning_failed': total_steps == 0 and not overall_success,
                        'step_failures': [
                            {
                                'step_type': step_result.get('step_type', 'unknown'),
                                'error': step_result.get('error', 'Unknown error')
                            }
                            for step_result in step_results if not step_result.get('success', True)
                        ]
                    }
                }
            }
            yield json.dumps(error_event) + "\n"
            if RESULT_STREAM_DELAY > 0:
                await asyncio.sleep(RESULT_STREAM_DELAY)
            
        else:
            # All steps successful
            active_processes[process_id]["status"] = ProcessStatus.COMPLETED
            
            # Send step completion updates
            for i, step_result in enumerate(step_results):
                step_completion_event = {
                    "type": "step_status",
                    "content": {
                        'process_id': process_id,
                        'step_index': i,  # 0-based index
                        'status': 'completed',
                        'operation_status': 'completed',
                        'result_summary': f'Step {i+1} completed successfully'
                    }
                }
                yield json.dumps(step_completion_event) + "\n"
                if RESULT_STREAM_DELAY > 0:
                    await asyncio.sleep(RESULT_STREAM_DELAY)
            
            # Handle final result with formatted response from Results Formatter
            final_result_content = "Execution completed successfully"
            display_type = 'markdown'  # Default display type
            
            # Check if we have a formatted response from the results formatter
            if formatted_response:
                #  ERROR DETECTION: Check if the formatted response contains error content
                usage_info = formatted_response.get('usage_info', {})
                has_error = usage_info.get('error') is not None
                
                # Check if content contains error text patterns
                content = formatted_response.get('content', {})
                error_patterns = ["**Processing Error**", "Results formatting failed", "Unable to parse LLM response"]
                content_has_error = False
                
                if isinstance(content, dict) and content.get('text'):
                    content_text = content['text']
                    content_has_error = any(pattern in content_text for pattern in error_patterns)
                elif isinstance(content, str):
                    content_has_error = any(pattern in content for pattern in error_patterns)
                
                # If we detect error content, send plan_error instead of final_result
                if has_error or content_has_error:
                    error_message = "Results processing failed"
                    if isinstance(content, dict) and content.get('text'):
                        # Extract clean error message from content
                        error_text = content['text']
                        if "Results formatting failed:" in error_text:
                            # Extract the specific error message
                            error_message = error_text.split("Results formatting failed: ")[1] if "Results formatting failed: " in error_text else error_message
                    elif usage_info.get('error'):
                        error_message = usage_info['error']
                    
                    logger.error(f"[{process_id}] Results Formatter error detected in formatted response: {error_message}")
                    
                    # Update process status to error
                    active_processes[process_id]["status"] = ProcessStatus.COMPLETED_WITH_ERRORS
                    
                    # Send error event instead of final_result
                    formatter_error_event = {
                        "type": "error", 
                        "content": {
                            'process_id': process_id,
                            'status': ProcessStatus.COMPLETED_WITH_ERRORS.value,
                            'message': error_message,
                            'error_type': 'results_formatter_error',
                            'failed_steps': 1,  # Results formatter step failed
                            'total_steps': total_steps,
                            'error_details': {
                                'results_formatter_failed': True,
                                'original_error': usage_info.get('error', 'Unknown error'),
                                'formatted_response_available': True
                            }
                        }
                    }
                    yield json.dumps(formatter_error_event) + "\n"
                    if RESULT_STREAM_DELAY > 0:
                        await asyncio.sleep(RESULT_STREAM_DELAY)
                    return  # Exit early - don't send final_result
                
                # No error detected - proceed with normal processing
                display_type = formatted_response.get('display_type', 'markdown')
                
                # Extract content based on display type
                if display_type == 'vuetify_table' and content:
                    final_result_content = f"Table with {len(content)} records"
                elif display_type == 'vuetify_table' and not content:
                    # Special case: successful query but no results found
                    final_result_content = "No results found for your query"
                    display_type = 'markdown'  # Change to markdown for better no-results display
                elif display_type == 'markdown' and isinstance(content, dict) and content.get('text'):
                    final_result_content = content['text']
                elif isinstance(content, str):
                    final_result_content = content
                else:
                    if isinstance(content, dict):
                        final_result_content = f"Results available in {display_type} format"
                    else:
                        final_result_content = str(content) if content else "Results processed successfully"
            elif result.get('final_result'):
                # Fallback to handling final_result if no formatted response
                final_result = result['final_result']
                if hasattr(final_result, 'sql') and hasattr(final_result, 'explanation'):
                    sql_result = final_result
                    record_count = len(sql_result.data) if sql_result.data else 0
                    final_result_content = f"Query executed successfully. Found {record_count} records.\n\n**Query Details:**\n{sql_result.explanation}"
                elif hasattr(final_result, 'code') and hasattr(final_result, 'explanation'):
                    api_result = final_result
                    if api_result.executed:
                        if isinstance(api_result.data, list):
                            record_count = len(api_result.data)
                            final_result_content = f"API call executed successfully. Found {record_count} records."
                        else:
                            final_result_content = "API call executed successfully."
                        final_result_content += f"\n\n**API Details:**\n{api_result.explanation}"
                    else:
                        final_result_content = f"API call failed: {api_result.error or 'Unknown error'}\n\n**API Details:**\n{api_result.explanation}"
                else:
                    try:
                        final_result_content = str(final_result)
                    except:
                        final_result_content = "Execution completed successfully"
            
            # Determine data source types used in execution
            used_sql = any('SQL' in step_result.get('step_type', '').upper() for step_result in step_results)
            used_api = any('API' in step_result.get('step_type', '').upper() for step_result in step_results)
            
            # Determine display mode for frontend (use data_source_type to match frontend expectation)
            if used_sql and used_api:
                data_source_type = "hybrid"  # Show "Hybrid (API + DB Updated): [timestamp]"
            elif used_sql:
                data_source_type = "sql"  # Show "DB Last Updated: [timestamp]"
            else:
                data_source_type = "realtime"  # Show "Realtime Mode"
            
            # Get database timestamp if SQL was used
            last_sync_metadata = {"data_source_type": data_source_type}
            if used_sql:
                try:
                    sync_info = await get_last_sync_info_for_realtime()
                    last_sync_metadata.update(sync_info)
                    logger.info(f"[{process_id}] {data_source_type} mode - retrieved database timestamp: {sync_info}")
                except Exception as e:
                    logger.warning(f"[{process_id}] Failed to get database timestamp: {e}")
                    last_sync_metadata["last_sync"] = "Error"
            
            # Send final result with proper display type from Results Formatter
            final_result_data = {
                'process_id': process_id,
                'status': ProcessStatus.COMPLETED.value,
                'result_content': final_result_content,
                'display_type': display_type,
                'message': f'Successfully executed {successful_steps}/{total_steps} steps'
            }
            
            # Always include metadata with data source information
            if formatted_response:
                final_result_data['formatted_response'] = formatted_response
                if 'metadata' not in final_result_data['formatted_response']:
                    final_result_data['formatted_response']['metadata'] = {}
                final_result_data['formatted_response']['metadata'].update(last_sync_metadata)
            else:
                final_result_data['formatted_response'] = {
                    'metadata': last_sync_metadata
                }
            
            active_processes[process_id]["final_result_data"] = final_result_data

            # CHUNKED STREAMING
            chunks = list(_chunk_large_response(final_result_data))
            if len(chunks) > 1:
                logger.info(f"[{process_id}] CHUNKED STREAMING: Sending {len(chunks)} chunks for large response")
                
                # Calculate total records from the first chunk's chunk_info
                total_records = 0
                if chunks and chunks[0].get('chunk_info'):
                    total_records = chunks[0]['chunk_info']['total_size']
                
                metadata_event = {
                    "type": "metadata",
                    "content": {
                        "total_batches": len(chunks),
                        "total_records": total_records,  # Add total records for progress calculation
                        "process_id": process_id,
                        "display_type": display_type
                    }
                }
                yield json.dumps(metadata_event) + "\n"
                # Use configurable delay for consistency
                if RESULT_STREAM_DELAY > 0:
                    await asyncio.sleep(RESULT_STREAM_DELAY)
                for i, chunk in enumerate(chunks):
                    batch_event = {
                        "type": "batch",
                        "content": chunk,
                        "metadata": {
                            "batch_number": i + 1,
                            "total_batches": len(chunks),
                            "is_final": i == len(chunks) - 1
                        }
                    }
                    yield json.dumps(batch_event) + "\n"
                    # Only add delay if configured (0 = no delay for maximum speed)
                    if RESULT_STREAM_DELAY > 0:
                        await asyncio.sleep(RESULT_STREAM_DELAY)
                completion_event = {
                    "type": "complete",
                    "content": {
                        "total_chunks": len(chunks),
                        "process_id": process_id
                    }
                }
                yield json.dumps(completion_event) + "\n"
            else:
                complete_event = {
                    "type": "complete",
                    "content": final_result_data
                }
                yield json.dumps(complete_event) + "\n"
                # Use configurable delay for consistency
                if RESULT_STREAM_DELAY > 0:
                    await asyncio.sleep(RESULT_STREAM_DELAY)

    except Exception as e:
        logger.error(f"[{process_id}] Error during Modern Execution Manager execution: {e}", exc_info=True)
        
        # Determine error type based on exception details
        error_str = str(e).lower()
        error_type = "execution_error"  # Default
        user_message = "An unexpected error occurred during execution."
        
        # Classify error types for better frontend handling
        if "planning" in error_str or "plan" in error_str:
            error_type = "planning_error"
            user_message = "Planning failed: Unable to generate execution plan."
        elif "sql" in error_str and ("database" in error_str or "query" in error_str):
            error_type = "sql_error"
            user_message = "Database query failed: Unable to execute SQL operations."
        elif "api" in error_str and ("request" in error_str or "endpoint" in error_str):
            error_type = "api_error" 
            user_message = "API request failed: Unable to complete API operations."
        elif "format" in error_str or "results" in error_str:
            error_type = "results_formatter_error"
            user_message = "Results processing failed: Unable to format query results."
        elif "timeout" in error_str or "cancelled" in error_str:
            error_type = "timeout_error"
            user_message = "Query execution timed out or was cancelled."
        elif isinstance(e, BaseError):
            error_type = "application_error"
            user_message = format_error_for_user(e)
        
        if process_id in active_processes:
            active_processes[process_id]["status"] = ProcessStatus.ERROR
            active_processes[process_id]["error_message"] = user_message
            active_processes[process_id]["error_type"] = error_type
        else:
            user_message = "Critical error: Process context lost during exception."
            error_type = "critical_error"
        
        try:
            exception_error_event = {
                "type": "error",
                "content": {
                    'process_id': process_id, 
                    'status': ProcessStatus.ERROR.value, 
                    'message': user_message,
                    'error_type': error_type,
                    'error_details': {
                        'exception_type': type(e).__name__,
                        'critical_error': process_id not in active_processes
                    }
                }
            }
            yield json.dumps(exception_error_event) + "\n"
            if RESULT_STREAM_DELAY > 0:
                await asyncio.sleep(RESULT_STREAM_DELAY)
        except Exception as send_err:
            logger.error(f"[{process_id}] Failed to send error SSE event: {send_err}")
    
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

    # Create a simple placeholder plan for immediate UI response (actual plan will be sent during execution)
    placeholder_plan = ApiPlan(
        original_query=sanitized_query,
        reasoning="Analyzing query and generating execution plan",
        confidence=None,
        steps=[
            ApiStep(
                id=0,
                tool_name="planning",
                query_context={"description": "Analyzing query and determining optimal execution strategy"},
                reason="Planning execution approach",
                critical=True,
                status="pending"
            )
        ]
    )

    # Store process data (no execution_plan needed - execute_query handles everything)
    active_processes[process_id] = {
        "process_id": process_id,
        "query": sanitized_query,
        "user_id": username,
        "api_plan_for_initial_response": placeholder_plan.model_dump(),
        "status": ProcessStatus.PLAN_GENERATED,
        "cancelled": False,
        "timestamp": time.time(),
        "error_message": None,
        "final_result_data": None
    }

    logger.info(f"[{process_id}] [/start-process] Process created - ready for execution")
    return StartProcessResponse(process_id=process_id, plan=placeholder_plan)

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
            error_event = {
                "type": "error",
                "content": {'process_id': process_id, 'status': 'error', 'message': 'Process not found or session expired.'}
            }
            yield json.dumps(error_event) + "\n"
            if RESULT_STREAM_DELAY > 0:
                await asyncio.sleep(RESULT_STREAM_DELAY)
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
            if current_process_status == ProcessStatus.ERROR:
                error_message = process_info.get("error_message", "Process previously ended in error.")
                error_type = process_info.get("error_type", "unknown_error")
                event = {
                    "type": "error",
                    "content": {
                        'process_id': process_id,
                        'status': 'error',
                        'message': error_message,
                        'error_type': error_type,
                        'error_details': {
                            'terminal_state': True,
                            'previous_execution': True
                        }
                    }
                }
            elif current_process_status == ProcessStatus.CANCELLED:
                event = {
                    "type": "error",
                    "content": {
                        'process_id': process_id,
                        'status': 'cancelled',
                        'message': 'Process was previously cancelled.'
                    }
                }
            elif current_process_status == ProcessStatus.COMPLETED_WITH_ERRORS:
                error_message = process_info.get("error_message", "Process previously completed with errors.")
                error_type = process_info.get("error_type", "execution_error")
                event = {
                    "type": "error",
                    "content": {
                        'process_id': process_id,
                        'status': 'completed_with_errors',
                        'message': error_message,
                        'error_type': error_type,
                        'error_details': {
                            'terminal_state': True,
                            'previous_execution': True,
                            'partial_success': True
                        }
                    }
                }
            else:
                final_data = process_info.get("final_result_data", {})
                if isinstance(final_data, dict):
                    event_content = final_data.copy()
                else:
                    event_content = {'result_content': str(final_data) if final_data is not None else "No result available."}
                
                # Ensure standard fields
                if "status" not in event_content: 
                    event_content["status"] = current_process_status.value
                if "message" not in event_content: 
                    event_content["message"] = "Process previously completed."
                if "display_type" not in event_content: 
                    event_content["display_type"] = "markdown"
                    
                event = {
                    "type": "complete",
                    "content": event_content
                }

            yield json.dumps(event) + "\n"
            delay = float(os.getenv("RESULT_STREAM_DELAY", "0.01"))
            await asyncio.sleep(delay)
        return EventSourceResponse(terminal_status_generator())

    # Handle running state (reconnection)
    if current_process_status == ProcessStatus.RUNNING_EXECUTION:
        logger.warning(f"[{process_id}] Client reconnected to running execution")
        async def already_running_generator():
            event = {
                "type": "status",
                "content": {
                    'process_id': process_id,
                    'status': 'reconnected_to_running',
                    'message': 'Reconnected to ongoing Modern Execution Manager execution.'
                }
            }
            yield json.dumps(event) + "\n"
            delay = float(os.getenv("RESULT_STREAM_DELAY", "0.01"))
            await asyncio.sleep(delay)
        return EventSourceResponse(already_running_generator())

    # Validate ready to execute
    if current_process_status != ProcessStatus.PLAN_GENERATED:
        logger.warning(f"[{process_id}] Invalid status for streaming: {current_process_status}")
        async def invalid_status_generator():
            event = {
                "type": "error",
                "content": {'process_id': process_id, 'status': 'error', 'message': f'Process cannot be streamed. Current state: {current_process_status}'}
            }
            yield json.dumps(event) + "\n"
            delay = float(os.getenv("RESULT_STREAM_DELAY", "0.01"))
            await asyncio.sleep(delay)
        return EventSourceResponse(invalid_status_generator())

    # Check for pre-cancellation
    if process_info.get("cancelled", False):
        logger.info(f"[{process_id}] Process cancelled before execution stream started.")
        active_processes[process_id]["status"] = ProcessStatus.CANCELLED
        async def cancelled_generator():
            event = {
                "type": "error",
                "content": {'process_id': process_id, 'status': 'cancelled', 'message': 'Process was cancelled before execution started.'}
            }
            yield json.dumps(event) + "\n"
            delay = float(os.getenv("RESULT_STREAM_DELAY", "0.01"))
            await asyncio.sleep(delay)
        return EventSourceResponse(cancelled_generator())

    # Start execution with Modern Execution Manager
    logger.info(f"[{process_id}] Starting Modern Execution Manager execution stream")

    query = process_info.get("query", "N/A")

    # Create the event generator
    event_generator = execute_plan_and_stream(
        process_id,
        query,
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
    modern_executor.cancel_query(process_id, f"User cancellation via API by {username}")  # Use proper cancel method
    
    if current_status == ProcessStatus.PLAN_GENERATED or current_status == ProcessStatus.PLAN_GENERATION:
        active_processes[process_id]["status"] = ProcessStatus.CANCELLED
        logger.info(f"[{process_id}] Process marked as cancelled in '{current_status}' state")

    return {"message": f"Cancellation signal sent for process {process_id} using Modern Execution Manager"}

@router.post("/execute-query")
async def execute_query_endpoint(
    request: Request,
    payload: RealtimeQueryRequest,
    current_user: AuthUser = Depends(get_current_user)
):
    """
    Execute query with Modern Execution Manager - Direct Query Execution
    
    This endpoint replicates the functionality from test_query_1.py, providing
    complete end-to-end execution with comprehensive results including:
    - Planning → Execution → Results formatting
    - Success rates and step details
    - Final formatted results
    - Correlation ID tracking
    
    This is similar to the test file's modern_executor.execute_query(query) method.
    """
    correlation_id = str(uuid.uuid4())
    username = current_user.username if current_user and hasattr(current_user, 'username') else "dev_user"
    set_correlation_id(correlation_id)

    logger.info(f"[{correlation_id}] [/execute-query] Direct Modern Execution Manager request for query: \"{payload.query}\" by user: {username}")

    # Sanitize query
    sanitized_query, warnings = sanitize_query(payload.query)
    
    # Log security warnings
    if warnings:
        client_ip = request.client.host if request.client else "unknown"
        logger.warning(f"Security warnings for query from user {current_user.id} (IP {client_ip}): {', '.join(warnings)}")

    try:
        # Execute the query using Modern Execution Manager's complete execute_query method
        # This replicates what test_query_1.py does: result = await modern_executor.execute_query(query)
        logger.info(f"[{correlation_id}] Executing with Modern Execution Manager's execute_query method...")
        result = await modern_executor.execute_query(sanitized_query)
        
        # Log comprehensive execution results (like the test does)
        logger.info(f"[{correlation_id}] EXECUTION RESULTS:")
        logger.info(f"[{correlation_id}] Overall Success: {result.get('success', False)}")
        logger.info(f"[{correlation_id}] Correlation ID: {result.get('correlation_id', 'N/A')}")
        logger.info(f"[{correlation_id}] Total Steps: {result.get('total_steps', 0)}")
        logger.info(f"[{correlation_id}] Successful Steps: {result.get('successful_steps', 0)}")
        logger.info(f"[{correlation_id}] Failed Steps: {result.get('failed_steps', 0)}")
        
        # Log step details (like the test does)
        step_results = result.get('step_results', [])
        if step_results:
            logger.info(f"[{correlation_id}] STEP EXECUTION DETAILS:")
            for i, step_result in enumerate(step_results, 1):
                success = step_result.get('success', False)
                step_type = step_result.get('step_type', 'unknown')
                status = "SUCCESS" if success else "FAILED"
                logger.info(f"[{correlation_id}]    {status} Step {i} ({step_type})")
                if step_result.get('error'):
                    logger.info(f"[{correlation_id}]       Error: {step_result['error']}")
                elif step_result.get('result_type'):
                    logger.info(f"[{correlation_id}]       Result: {step_result['result_type']}")
        
        # Log final result (like the test does)
        final_result = result.get('final_result')
        if final_result:
            logger.info(f"[{correlation_id}] FINAL RESULT:")
            logger.info(f"[{correlation_id}]    Type: {type(final_result).__name__}")
            logger.info(f"[{correlation_id}]    Available: YES")
        else:
            logger.info(f"[{correlation_id}] NO FINAL RESULT")
        
        # Assess success (like the test does)
        overall_success = result.get('success', False)
        success_rate = result.get('success_rate', 0)
        
        logger.info(f"[{correlation_id}] EXECUTION ASSESSMENT:")
        if overall_success and success_rate >= 1.0:
            logger.info(f"[{correlation_id}] QUERY EXECUTION - COMPLETE SUCCESS!")
            logger.info(f"[{correlation_id}]    All steps executed successfully")
        elif overall_success and success_rate >= 0.5:
            logger.info(f"[{correlation_id}] QUERY EXECUTION - SUCCESS!")
            logger.info(f"[{correlation_id}]    Success rate: {success_rate:.1%}")
        else:
            logger.info(f"[{correlation_id}] QUERY EXECUTION - FAILED")
            logger.info(f"[{correlation_id}]    Success rate: {success_rate:.1%}")
        
        # Return comprehensive results that match test expectations
        return {
            "success": overall_success,
            "correlation_id": result.get('correlation_id'),
            "query": sanitized_query,
            "execution_results": {
                "total_steps": result.get('total_steps', 0),
                "successful_steps": result.get('successful_steps', 0),
                "failed_steps": result.get('failed_steps', 0),
                "success_rate": success_rate,
                "step_details": step_results
            },
            "final_result": {
                "available": final_result is not None,
                "type": type(final_result).__name__ if final_result else None,
                "data": final_result
            },
            "formatted_response": result.get('processed_summary', {}),
            "execution_method": "Modern Execution Manager execute_query",
            "message": f"Query executed via Modern Execution Manager with {success_rate:.1%} success rate"
        }

    except Exception as e:
        logger.error(f"[{correlation_id}] Error during Modern Execution Manager execute_query: {e}", exc_info=True)
        error_detail = format_error_for_user(e) if isinstance(e, BaseError) else f"Query execution failed: {str(e)}"
        
        raise HTTPException(
            status_code=500, 
            detail={
                "error": error_detail,
                "correlation_id": correlation_id,
                "execution_method": "Modern Execution Manager execute_query",
                "success": False
            }
        )

@router.get("/okta-entities")
async def get_okta_entities(
    current_user: AuthUser = Depends(get_current_user) 
):
    """Retrieve all available Okta API entities organized by functional areas using entity-grouped format."""
    import json
    from pathlib import Path
    
    try:
        # Read entities from the new lightweight API reference (entity-grouped format)
        lightweight_api_path = Path("src/data/schemas/lightweight_api_reference.json")
        
        if not lightweight_api_path.exists():
            logger.warning("Lightweight API reference file not found, falling back to Modern Execution Manager")
            # Fallback to Modern Execution Manager
            entities_list = []
            for entity in modern_executor.available_entities:
                entities_list.append({
                    "entity_name": entity,
                    "display_name": entity.replace('_', ' ').title(),
                    "description": f"Okta {entity.replace('_', ' ').title()} operations and management",
                    "operations_count": 0,  # Unknown without reference file
                    "source": "Modern Execution Manager"
                })
                    
            entities_list.sort(key=lambda x: x["display_name"])
            return {
                "entities_count": len(entities_list),
                "entities": entities_list,
                "source": "Modern Execution Manager (Fallback)"
            }
        
        # Read and parse the entity-grouped API reference
        with open(lightweight_api_path, 'r', encoding='utf-8') as f:
            api_data = json.load(f)
        
        # Extract entities from the new entity-grouped format
        entities_dict = api_data.get('entities', {})
        
        entities_list = []
        for entity_name, entity_data in entities_dict.items():
            operations = entity_data.get('operations', [])
            operations_count = len(operations)
            
            # Create display name by replacing underscores with spaces and title casing
            display_name = entity_name.replace('_', ' ').title()
            
            # Create description based on entity name
            description = f"Okta {display_name} operations and management ({operations_count} operations available)"
            
            entities_list.append({
                "entity_name": entity_name,
                "display_name": display_name,
                "description": description,
                "operations_count": operations_count,
                "operations": operations[:5] if operations_count > 5 else operations,  # Show first 5 operations
                "source": "Lightweight API Reference"
            })
        
        # Sort entities alphabetically by display name
        entities_list.sort(key=lambda x: x["display_name"])
        
        return {
            "entities_count": len(entities_list),
            "entities": entities_list,
            "source": "Entity-Grouped Format (lightweight_api_reference.json)",
            "format_version": "entity_grouped"
        }
        
    except Exception as e:
        logger.error(f"Error reading lightweight API reference: {e}")
        
        # Fallback to Modern Execution Manager on error
        try:
            entities_list = []
            for entity in modern_executor.available_entities:
                entities_list.append({
                    "entity_name": entity,
                    "display_name": entity.replace('_', ' ').title(),
                    "description": f"Okta {entity.replace('_', ' ').title()} operations and management",
                    "operations_count": 0,  # Unknown in fallback
                    "source": "Modern Execution Manager"
                })
            
            entities_list.sort(key=lambda x: x["display_name"])
            return {
                "entities_count": len(entities_list),
                "entities": entities_list,
                "source": "Modern Execution Manager (Error Fallback)"
            }
        except Exception as fallback_error:
            logger.error(f"Error using Modern Execution Manager fallback: {fallback_error}")
            # Ultimate fallback - empty list
            return {
                "entities_count": 0,
                "entities": [],
                "source": "Empty Fallback"
            }
