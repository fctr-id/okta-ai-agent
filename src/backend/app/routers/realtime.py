from fastapi import APIRouter, Depends, Request, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
import json
import asyncio
import logging
from typing import Dict, Any, Optional
import base64
from datetime import datetime

from src.core.auth.dependencies import get_current_user
from src.core.realtime.okta_realtime_client import OktaRealtimeClient
from src.core.realtime.agents.base import OktaRealtimeDeps
from src.core.realtime.agents.reasoning_agent import coordinator_agent
from src.core.realtime.conversation_manager import conversation_manager
# Import your existing OktaClient initializer
from src.core.auth import get_okta_client

router = APIRouter(prefix="/api/realtime", tags=["realtime"])

logger = logging.getLogger(__name__)

@router.post("/query")
async def realtime_query(
    request: Request,
    query: str,
    current_user: Dict = Depends(get_current_user),
    message_history: Optional[str] = None
):
    """Handle real-time Okta API queries with conversation history.
    
    Args:
        request: Request object (for IP extraction)
        query: The natural language query
        current_user: The authenticated user
        message_history: Optional JSON encoded message history
        
    Returns:
        The query result and updated message history
    """
    try:
        # Generate user key from IP and forwarded headers
        client_ip = request.client.host
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Use the first forwarded IP if available
            client_ip = forwarded_for.split(",")[0].strip()
        
        user_agent_str = request.headers.get("User-Agent", "")
        user_key = conversation_manager.generate_user_key(client_ip, user_agent_str)
        
        # Create Okta client and dependencies
        okta_client = OktaRealtimeClient(get_okta_client())
        deps = OktaRealtimeDeps(okta_client=okta_client, user_id=current_user["sub"])
        
        # Get conversation history
        messages = []
        if message_history:
            # If explicit history is provided, use it
            messages = conversation_manager.deserialize_conversation(message_history)
        else:
            # Otherwise get from in-memory storage
            messages = conversation_manager.get_conversation(user_key)
        
        # Run the coordinator agent
        result = await coordinator_agent.run(query, deps=deps, message_history=messages)
        
        # Update conversation history
        new_messages = result.new_messages()
        conversation_manager.update_conversation(user_key, new_messages)
        
        # Return results with conversation state
        return {
            "result": result.data,
            "message_history": conversation_manager.serialize_conversation(user_key)
        }
    except Exception as e:
        logger.error(f"Error processing realtime query: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error processing query: {str(e)}"
        )

@router.post("/stream")
async def realtime_stream(
    request: Request,
    query: str,
    current_user: Dict = Depends(get_current_user),
    message_history: Optional[str] = None
):
    """Stream real-time Okta API query results.
    
    Args:
        request: Request object (for IP extraction)
        query: The natural language query
        current_user: The authenticated user
        message_history: Optional JSON encoded message history
        
    Returns:
        Streaming response with incremental results
    """
    # Generate user key from IP
    client_ip = request.client.host
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    
    user_agent_str = request.headers.get("User-Agent", "")
    user_key = conversation_manager.generate_user_key(client_ip, user_agent_str)
    
    async def stream_generator():
        """Generate streaming response."""
        try:
            # Create Okta client and dependencies
            okta_client = OktaRealtimeClient(get_okta_client())
            deps = OktaRealtimeDeps(okta_client=okta_client, user_id=current_user["sub"])
            
            # Get conversation history
            messages = []
            if message_history:
                messages = conversation_manager.deserialize_conversation(message_history)
            else:
                messages = conversation_manager.get_conversation(user_key)
            
            # Start streaming response
            async with coordinator_agent.run_stream(
                query, 
                deps=deps,
                message_history=messages
            ) as stream:
                # Stream text chunks as they become available
                async for text in stream.stream_text():
                    yield f"data: {json.dumps({'type': 'text', 'content': text})}\n\n"
                    await asyncio.sleep(0)  # Yield control
                
                # Get final result with complete structured data
                final_data = await stream.get_data()
                
                # Update conversation history
                new_messages = stream.new_messages()
                conversation_manager.update_conversation(user_key, new_messages)
                
                # Send final result with message history
                yield f"data: {json.dumps({
                    'type': 'final', 
                    'result': final_data,
                    'message_history': conversation_manager.serialize_conversation(user_key)
                })}\n\n"
        
        except Exception as e:
            logger.error(f"Error in stream: {str(e)}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream"
    )

@router.get("/status")
async def rate_limit_status(current_user: Dict = Depends(get_current_user)):
    """Get current rate limit status for Okta API."""
    try:
        # Create Okta client
        okta_client = OktaRealtimeClient(get_okta_client())
        
        # Return rate limit information
        return {
            "rate_limits": okta_client.rate_limits,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting rate limit status: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, 
            detail=f"Error retrieving rate limit status: {str(e)}"
        )