"""
Shared callback utilities for multi-agent architecture.

Provides standardized notification functions that all agents can use
to communicate progress to the frontend via SSE.
"""

import time
from typing import Optional, Callable, Awaitable, Dict, Any
from src.utils.logging import get_logger

logger = get_logger("okta_ai_agent")


async def notify_progress_to_user(
    correlation_id: str,
    progress_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]],
    message: str,
    details: Optional[str] = None
) -> None:
    """
    Send progress update to frontend (intermediate progress during tool execution).
    
    This is different from notify_step_start/end:
    - notify_step_start/end: Phase boundaries (SQL Discovery Phase, API Discovery Phase, etc.)
    - notify_progress_to_user: Intermediate updates within a phase (e.g., "Executed query #1", "Fetched 10 users")
    
    Args:
        correlation_id: Correlation ID for logging
        progress_callback: Optional callback to send progress events (from deps)
        message: Progress message to display
        details: Optional additional details
    """
    # Strip emojis from message (safety net if LLM adds them)
    import re
    clean_message = re.sub(r'[\U0001F300-\U0001F9FF\u2600-\u26FF\u2700-\u27BF]', '', message).strip()
    
    # Log to backend
    log_msg = f"[{correlation_id}] Progress: {clean_message}"
    if details:
        log_msg += f" - {details}"
    logger.info(log_msg)
    
    # Send to frontend if callback available
    if progress_callback:
        await progress_callback({
            "type": "STEP-PROGRESS",
            "message": clean_message,
            "details": details or "",
            "timestamp": time.time()
        })


async def notify_step_start_to_user(
    correlation_id: str,
    current_step: int,
    step_start_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]],
    title: str,
    reasoning: str
) -> int:
    """
    Notify frontend that a major step is starting.
    
    Args:
        correlation_id: Correlation ID for logging
        current_step: Current step number (will be incremented)
        step_start_callback: Callback to send step start events
        title: Step title
        reasoning: Reasoning for this step
    
    Returns:
        Updated step number
    """
    new_step = current_step + 1
    
    logger.info(f"[{correlation_id}] 🎯 STEP {new_step} START: {title}")
    logger.debug(f"[{correlation_id}] 💭 Reasoning: {reasoning}")
    
    if step_start_callback:
        await step_start_callback({
            "step": new_step,
            "title": title,
            "text": reasoning,
            "timestamp": time.time()
        })
    
    return new_step


async def notify_step_end_to_user(
    correlation_id: str,
    current_step: int,
    step_end_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]],
    title: str,
    result: str,
    success: bool = True
) -> None:
    """
    Notify frontend that a major step has completed.
    
    Args:
        correlation_id: Correlation ID for logging
        current_step: Current step number
        step_end_callback: Callback to send step end events
        title: Step title
        result: Result summary
        success: Whether the step succeeded
    """
    status = "✅" if success else "❌"
    logger.info(f"[{correlation_id}] {status} STEP {current_step} END: {title}")
    logger.debug(f"[{correlation_id}] 📋 Result: {result}")
    
    if step_end_callback:
        await step_end_callback({
            "step": current_step,
            "title": title,
            "text": result,
            "success": success,
            "timestamp": time.time()
        })
