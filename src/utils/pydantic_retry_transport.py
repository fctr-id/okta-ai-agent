"""
PydanticAI Native Retry System - HTTP Transport Layer Retry

This module implements PydanticAI's native retry functionality using AsyncTenacityTransport
to handle rate limits at the HTTP transport layer before they reach the agent.

Features:
- Automatic Retry-After header parsing for intelligent rate limit handling
- HTTP transport layer retry (more efficient than function-level retry)
- Exponential backoff fallback when no Retry-After header is present
- Integration with existing model picker architecture
- Support for all AI providers (OpenAI, Anthropic, Azure, etc.)

Usage:
    from src.utils.pydantic_retry_transport import create_retrying_http_client
    
    # Create HTTP client with retry support
    client = create_retrying_http_client()
    
    # Use with any provider
    provider = OpenAIProvider(http_client=client)
    model = OpenAIModel('gpt-4', provider=provider)
"""

import asyncio
from typing import Optional, Callable
import httpx
from tenacity import AsyncRetrying, stop_after_attempt, retry_if_exception_type
from pydantic_ai.retries import AsyncTenacityTransport, wait_retry_after, wait_exponential

from src.utils.logging import get_logger

logger = get_logger("pydantic_retry_transport")


def create_retrying_http_client(
    retry_callback: Optional[Callable] = None,
    max_attempts: int = 3,
    correlation_id: str = None,
    agent_type: str = "ai_agent"
) -> httpx.AsyncClient:
    """
    Create an HTTP client with PydanticAI native retry functionality.
    
    Args:
        retry_callback: Optional callback for frontend notifications
            Signature: async def callback(correlation_id, attempt, wait_time, reason, agent_type)
        max_attempts: Maximum number of retry attempts (default 3)
        correlation_id: Correlation ID for logging and callbacks
        agent_type: Type of agent for logging (planning_agent, sql_agent, etc.)
        
    Returns:
        httpx.AsyncClient configured with retry transport
        
    Example:
        client = create_retrying_http_client(
            retry_callback=my_callback,
            correlation_id="query-123",
            agent_type="planning_agent"
        )
        provider = OpenAIProvider(http_client=client)
        model = OpenAIModel('gpt-4', provider=provider)
    """
    
    def retry_before_sleep_callback(retry_state):
        """Enhanced retry callback with detailed timing information"""
        attempt = retry_state.attempt_number
        
        # Calculate expected wait time based on retry strategy
        wait_time = retry_state.next_action.sleep if hasattr(retry_state.next_action, 'sleep') else 0
        
        # Log the retry attempt
        logger.warning(f"[{correlation_id or 'unknown'}] {agent_type} HTTP retry {attempt} after rate limit - waiting {wait_time:.0f}s (respecting Retry-After headers)")
        
        # Notify frontend via callback if available
        if retry_callback:
            try:
                # Call the callback with detailed retry information
                asyncio.create_task(retry_callback(
                    correlation_id=correlation_id or 'unknown',
                    attempt=attempt,
                    wait_time=int(wait_time),
                    reason="Rate limit exceeded (HTTP transport)",
                    agent_type=agent_type
                ))
            except Exception as callback_error:
                logger.error(f"[{correlation_id or 'unknown'}] {agent_type} retry callback failed: {callback_error}")
    
    def should_retry_response(response):
        """
        Check if HTTP response should trigger a retry.
        
        This function is called for every HTTP response to determine if it represents
        a failure that should be retried. For rate limits and server errors, we
        raise an exception that the retry mechanism can catch.
        """
        if response.status_code in (429, 502, 503, 504):
            # Log the rate limit/server error
            if response.status_code == 429:
                retry_after = response.headers.get('Retry-After', 'unknown')
                logger.warning(f"[{correlation_id or 'unknown'}] {agent_type} received 429 rate limit, Retry-After: {retry_after}")
            else:
                logger.warning(f"[{correlation_id or 'unknown'}] {agent_type} received server error: {response.status_code}")
            
            # Raise HTTPStatusError for retry mechanism to catch
            response.raise_for_status()
    
    # Create the AsyncRetrying controller with PydanticAI's smart wait strategy
    async_retrying = AsyncRetrying(
        # Retry on HTTP errors (429, 5xx) and connection issues
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException)),
        
        # Smart waiting: respects Retry-After headers, falls back to exponential backoff
        wait=wait_retry_after(
            fallback_strategy=wait_exponential(multiplier=2, min=15, max=120),
            max_wait=600  # Never wait more than 10 minutes
        ),
        
        # Stop after max attempts
        stop=stop_after_attempt(max_attempts),
        
        # Add retry callback for logging and notifications
        before_sleep=retry_before_sleep_callback,
        
        # Re-raise the last exception if all retries fail
        reraise=True
    )
    
    # Create the AsyncTenacityTransport
    transport = AsyncTenacityTransport(
        controller=async_retrying,
        validate_response=should_retry_response
    )
    
    # Create HTTP client with retry transport
    client = httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(60.0)  # 60 second timeout per request
    )
    
    logger.info(f"[{correlation_id or 'unknown'}] Created retrying HTTP client for {agent_type} with {max_attempts} max attempts")
    
    return client


def create_simple_retrying_http_client(max_attempts: int = 3) -> httpx.AsyncClient:
    """
    Create a simple HTTP client with retry functionality without callbacks.
    
    Args:
        max_attempts: Maximum number of retry attempts
        
    Returns:
        httpx.AsyncClient configured with basic retry transport
    """
    return create_retrying_http_client(
        retry_callback=None,
        max_attempts=max_attempts,
        correlation_id=None,
        agent_type="agent"
    )


# Predefined retry clients for common scenarios
def create_planning_agent_http_client(correlation_id: str, retry_callback: Optional[Callable] = None) -> httpx.AsyncClient:
    """Create retrying HTTP client specifically for planning agent"""
    return create_retrying_http_client(
        retry_callback=retry_callback,
        correlation_id=correlation_id,
        agent_type="planning_agent"
    )


def create_sql_agent_http_client(correlation_id: str, retry_callback: Optional[Callable] = None) -> httpx.AsyncClient:
    """Create retrying HTTP client specifically for SQL agent"""
    return create_retrying_http_client(
        retry_callback=retry_callback,
        correlation_id=correlation_id,
        agent_type="sql_agent"
    )


def create_api_agent_http_client(correlation_id: str, retry_callback: Optional[Callable] = None) -> httpx.AsyncClient:
    """Create retrying HTTP client specifically for API code gen agent"""
    return create_retrying_http_client(
        retry_callback=retry_callback,
        correlation_id=correlation_id,
        agent_type="api_agent"
    )


def create_api_sql_agent_http_client(correlation_id: str, retry_callback: Optional[Callable] = None) -> httpx.AsyncClient:
    """Create retrying HTTP client specifically for API-SQL agent"""
    return create_retrying_http_client(
        retry_callback=retry_callback,
        correlation_id=correlation_id,
        agent_type="api_sql_agent"
    )


def create_results_formatter_http_client(correlation_id: str, retry_callback: Optional[Callable] = None) -> httpx.AsyncClient:
    """Create retrying HTTP client specifically for results formatter agent"""
    return create_retrying_http_client(
        retry_callback=retry_callback,
        correlation_id=correlation_id,
        agent_type="results_formatter"
    )
