from typing import Dict, List, Optional, Union, Any
from datetime import datetime
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext, ModelRetry
import logging
import time
import json

from src.legacy.realtime_mode.agents.base import OktaRealtimeDeps, RateLimited, EntityError, EntityResponse
from src.legacy.realtime_mode.client_errors import RateLimitError, OktaRealtimeError
from src.core.models.model_picker import ModelConfig, ModelType

# Set up logger for this module
logger = logging.getLogger(__name__)

# Define structured input and output models
class EventQuery(BaseModel):
    """Parameters for event log queries."""
    event_type: Optional[str] = None
    user_id: Optional[str] = None
    application_id: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    limit: int = 100

class EventDetails(BaseModel):
    """Event log details."""
    event_id: str
    event_type: str
    actor: Optional[Dict[str, Any]] = None
    target: Optional[List[Dict[str, Any]]] = None
    published: Optional[str] = None
    outcome: Optional[Dict[str, Any]] = None
    client_info: Optional[Dict[str, Any]] = Field(None, alias="client")
    
    class Config:
        populate_by_name = True
        extra = "ignore"  # Ignore extra fields from Okta API

class EventResponse(EntityResponse):
    """Success response with event data."""
    events: List[EventDetails]
    total_count: int
    query_id: Optional[str] = None  # For tracking
    execution_time_ms: Optional[int] = None  # For performance monitoring
    
    def __str__(self) -> str:
        if not self.events:
            return "No events found"
        elif len(self.events) == 1:
            event = self.events[0]
            return f"Event: {event.event_type} (ID: {event.event_id})"
        else:
            return f"Found {self.total_count} events"

# Define the combined response type
EventResult = Union[EventResponse, RateLimited, EntityError]

# Create the event agent
event_agent = Agent(
    model=ModelConfig.get_model(ModelType.REASONING),
    deps_type=OktaRealtimeDeps,
    output_type=EventResult,
    system_prompt="""
    You are a specialized agent for querying Okta event logs in real-time.
    
    Your role is to interpret natural language queries about events and translate them 
    into API calls to retrieve the requested information.
    
    You have access to event properties including:
    - Event details: event_id, event_type, published date
    - Actor information: who performed the action
    - Target information: what was affected by the action
    - Client information: browser, IP, etc.
    - Outcome details: success, failure, reason
    
    IMPORTANT GUIDELINES:
    1. Always interpret the user's query in the context of Okta events and logs
    2. When the query doesn't specify a time range, ask for clarification
    3. Always handle rate limits gracefully by explaining which data is missing
    4. Format responses chronologically when presenting multiple events
    5. Default to retrieving at most 100 events unless specified otherwise
    6. Prioritize data security - never infer or guess sensitive information
    
    Use the provided tools to search for events or retrieve specific event details.
    """
)

@event_agent.on_start
async def initialize_query(ctx: RunContext[OktaRealtimeDeps]):
    """Initialize the query context with tracking information."""
    # Get query ID from dependencies or generate one
    query_id = getattr(ctx.deps, "query_id", "unknown")
    
    # Store start time and query ID in the context
    ctx.extra["query_id"] = query_id
    ctx.extra["start_time"] = time.time()
    
    # Log the start of processing
    user_query = ctx.messages[0].content if ctx.messages else "Unknown query"
    logger.info(f"[FLOW:{query_id}] Starting event agent with query: '{user_query}'")

@event_agent.tool
async def get_events(
    ctx: RunContext[OktaRealtimeDeps],
    filter_expression: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100
) -> EventResult:
    """
    Get event logs with optional filtering.
    
    Args:
        filter_expression: Filter expression for events (e.g., 'eventType eq "user.login.success"')
        start_date: Start date in ISO format (e.g., '2023-01-01T00:00:00Z')
        end_date: End date in ISO format (e.g., '2023-01-31T23:59:59Z')
        limit: Maximum number of results (1-200)
        
    Returns:
        Event search results or error information
    """
    query_id = ctx.extra.get("query_id", "unknown")
    start_time = time.time()
    
    logger.info(f"[FLOW:{query_id}] Getting events with filter: '{filter_expression}', date range: {start_date} to {end_date}, limit: {limit}")
    
    try:
        # Ensure reasonable limits
        actual_limit = max(1, min(limit, 200))
        logger.debug(f"[FLOW:{query_id}] Adjusted limit to {actual_limit}")
        
        # Parse dates if provided
        start_datetime = None
        end_datetime = None
        
        if start_date:
            try:
                logger.debug(f"[FLOW:{query_id}] Parsing start date: {start_date}")
                start_datetime = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            except ValueError:
                logger.error(f"[FLOW:{query_id}] Invalid start date format: {start_date}")
                return EntityError(
                    message=f"Invalid start date format: {start_date}. Use ISO format (YYYY-MM-DDTHH:MM:SSZ).",
                    error_type="Validation Error",
                    entity="events"
                )
        
        if end_date:
            try:
                logger.debug(f"[FLOW:{query_id}] Parsing end date: {end_date}")
                end_datetime = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            except ValueError:
                logger.error(f"[FLOW:{query_id}] Invalid end date format: {end_date}")
                return EntityError(
                    message=f"Invalid end date format: {end_date}. Use ISO format (YYYY-MM-DDTHH:MM:SSZ).",
                    error_type="Validation Error",
                    entity="events"
                )
        
        # Get events from Okta
        logger.debug(f"[FLOW:{query_id}] Calling Okta API to get events")
        events = await ctx.deps.okta_client.get_events(
            filter_expression=filter_expression,
            start_date=start_datetime,
            end_date=end_datetime,
            limit=actual_limit
        )
        
        # Log success
        elapsed = time.time() - start_time
        logger.info(f"[FLOW:{query_id}] Found {len(events)} events in {elapsed:.2f}s")
        
        # Transform to our response model
        event_details = [
            EventDetails(
                event_id=event.get("uuid", ""),
                event_type=event.get("eventType", ""),
                actor=event.get("actor"),
                target=event.get("target"),
                published=event.get("published"),
                outcome=event.get("outcome"),
                client=event.get("client")
            )
            for event in events
        ]
        
        # Log sample data at debug level
        if event_details and len(event_details) > 0:
            logger.debug(f"[FLOW:{query_id}] Sample event: {json.dumps(event_details[0].model_dump())}")
        
        return EventResponse(
            events=event_details,
            total_count=len(event_details),
            metadata={
                "filter": filter_expression,
                "start_date": start_date,
                "end_date": end_date,
                "limit": actual_limit
            },
            query_id=query_id,
            execution_time_ms=int(elapsed * 1000)
        )
    except RateLimitError as e:
        # Handle rate limit errors gracefully
        elapsed = time.time() - start_time
        logger.warning(f"[FLOW:{query_id}] Rate limit reached while retrieving events: {e.message} after {elapsed:.2f}s")
        return RateLimited(
            message=f"Rate limit reached while retrieving events: {e.message}",
            rate_limit_reset=e.reset_seconds
        )
    except OktaRealtimeError as e:
        # Handle other API errors
        elapsed = time.time() - start_time
        logger.error(f"[FLOW:{query_id}] API error while retrieving events: {str(e)} after {elapsed:.2f}s")
        return EntityError(
            message=str(e),
            error_type="API Error",
            entity="events"
        )
    except Exception as e:
        # Handle unexpected errors
        elapsed = time.time() - start_time
        logger.exception(f"[FLOW:{query_id}] Unexpected error while retrieving events: {str(e)} after {elapsed:.2f}s")
        return EntityError(
            message=f"Unexpected error: {str(e)}",
            error_type="Unknown Error",
            entity="events"
        )

@event_agent.result_validator
async def validate_event_result(
    ctx: RunContext[OktaRealtimeDeps],
    result: EventResult
) -> EventResult:
    """
    Validate the event agent response and handle any issues.
    
    Args:
        result: The result object to validate
        
    Returns:
        Validated or corrected result
    """
    query_id = ctx.extra.get("query_id", "unknown")
    start_time = ctx.extra.get("start_time", time.time())
    total_elapsed = time.time() - start_time
    
    # If we got a RateLimited response, update the rate limit info
    if isinstance(result, RateLimited) and result.rate_limit_reset:
        logger.warning(f"[FLOW:{query_id}] Updating rate limit info: reset in {result.rate_limit_reset}s")
        ctx.deps.update_rate_limit_info("events", {
            "rate_limited": True,
            "reset_seconds": result.rate_limit_reset
        })
        
    # If we got an EventResponse but it's empty, suggest a retry or clarification
    if isinstance(result, EventResponse) and not result.events:
        logger.info(f"[FLOW:{query_id}] Empty event results, considering retry")
        if ctx.retry < 1:  # Only retry once
            logger.info(f"[FLOW:{query_id}] Requesting retry for empty results")
            raise ModelRetry("No events found. Please try a different filter or date range.")
        else:
            logger.info(f"[FLOW:{query_id}] Already retried, returning empty results")
    
    # Log completion
    if isinstance(result, EventResponse):
        logger.info(f"[FLOW:{query_id}] Event agent completed successfully in {total_elapsed:.2f}s - found {result.total_count} events")
    elif isinstance(result, RateLimited):
        logger.warning(f"[FLOW:{query_id}] Event agent completed with rate limit in {total_elapsed:.2f}s")
    else:  # EntityError
        logger.error(f"[FLOW:{query_id}] Event agent completed with error in {total_elapsed:.2f}s: {str(result)}")
            
    return result

@event_agent.on_end
async def finalize_query(ctx: RunContext[OktaRealtimeDeps], result: EventResult):
    """Log final query stats when event agent completes."""
    query_id = ctx.extra.get("query_id", "unknown")
    start_time = ctx.extra.get("start_time", time.time())
    total_elapsed = time.time() - start_time
    
    logger.info(f"[FLOW:{query_id}] Event agent completed in {total_elapsed:.2f}s")
    
    # Log token usage if available
    if hasattr(result, "token_usage") and result.token_usage:
        logger.info(f"[FLOW:{query_id}] Token usage: {result.token_usage}")