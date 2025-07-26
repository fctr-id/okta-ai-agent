from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from typing import Dict, AsyncGenerator, Tuple, List, Any
import json
import re
from src.utils.logging import logger
from src.api.services.ai_service import AIService
from html_sanitizer import Sanitizer
from src.core.security.dependencies import get_current_user, get_db_session
from sqlalchemy.ext.asyncio import AsyncSession
import sys

router = APIRouter()

custom_sanitizer = Sanitizer({
    'tags': ('__nonexistent_tag__',),  # Using a tag that will never exist in real content
    'attributes': {},                  # No attributes allowed
    'empty': set(),                    # No empty elements allowed
    'separate': set()                  # No separate elements needed
})


def sanitize_query(query: str) -> Tuple[str, List[str]]:
    """
    Natural language-aware query sanitization
    
    Args:
        query: Raw user input (expected to be natural language)
        
    Returns:
        Tuple of (sanitized_query, warnings)
    """
    if not query:
        return "", []
        
    warnings = []
    
    # Convert to string if not already
    query = str(query)
    
    # Limit length to prevent DoS
    if len(query) > 2000:
        query = query[:2000]
        warnings.append("Query truncated due to excessive length")
        
    # More efficient control character removal using regex
    original_length = len(query)
    query = re.sub(r'[\x00-\x08\x0B-\x1F\x7F]', '', query)
    if len(query) != original_length:
        warnings.append("Control characters removed from query")
    
    # Detect patterns that shouldn't be in natural language queries
    suspicious_patterns = [
        # Code blocks
        (r'```.*?```', "code block"),
        
        # Script injection attempts
        (r'<\s*script\b[^>]*>', "script tag"),
        (r'javascript\s*:', "JavaScript protocol"),
        
        # SQL in what should be natural language
        (r'(?i)(?:select|insert|update|delete|drop|alter|create)\s+(?:from|into|table|database)', "SQL-like syntax"),
        
        # Common injection techniques
        (r'\{\{.*?\}\}', "template expression"),
        (r'\$\{.*?\}', "expression injection"),
        
        # Shell command markers
        (r'`.*?`', "command backticks"),
        (r'\$\(.*?\)', "command substitution")
    ]
    
    # Check for suspicious patterns but preserve original text
    for pattern, description in suspicious_patterns:
        matches = re.findall(pattern, query, re.DOTALL | re.IGNORECASE)
        if matches:
            match_preview = matches[0][:20] + "..." if len(matches[0]) > 20 else matches[0]
            warnings.append(f"Suspicious {description} detected: '{match_preview}'")
    
    # Use html-sanitizer to strip ALL HTML tags securely
    sanitized_query = custom_sanitizer.sanitize(query)
    
    # Remove data: URIs which can contain JavaScript (sanitizer might miss these)
    sanitized_query = re.sub(r'data\s*:\s*\w+/\w+\s*;\s*base64', 'data-removed', sanitized_query, flags=re.IGNORECASE)
    
    return sanitized_query.strip(), warnings

@router.post("/query")
async def process_query(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    current_user: Any = Depends(get_current_user)
):
    try:
        # Extract auth_check query parameter (if this is just an auth check)
        auth_check = request.query_params.get("auth_check") == "true"
        
        # If this is just an auth check, return early with success
        if auth_check:
            return JSONResponse(
                status_code=200, 
                content={"authenticated": True}
            )
            
        # Validate JSON schema
        try:
            data = await request.json()
            if not isinstance(data, dict):
                return JSONResponse(
                    status_code=400, 
                    content={"type": "error", "content": "Invalid request format"}
                )
        except json.JSONDecodeError:
            return JSONResponse(
                status_code=400,
                content={"type": "error", "content": "Invalid JSON"}
            )
            
        raw_query = data.get("query", "")
        
        if not raw_query or not isinstance(raw_query, str):
            return JSONResponse(
                status_code=400,
                content={"type": "error", "content": "Query is required and must be a string"}
            )

        # Sanitize and check for security issues
        sanitized_query, warnings = sanitize_query(raw_query)
        
        # Enhanced security logging
        client_ip = request.client.host if request.client else "unknown"
        user_id = getattr(current_user, "id", "unknown")
        
        # Log security warnings if any were found
        if warnings:
            logger.warning(f"Security warnings for query from user {user_id} (IP {client_ip}): {', '.join(warnings)}")
        
        logger.info(f"Processing query from user {user_id} (IP {client_ip}): {sanitized_query[:100]}...")
            
        async def generate_stream():
            # We rely on FastAPI's automatic client disconnect detection
            # When client disconnects, the generator will be stopped automatically
            async for response in AIService.process_query(sanitized_query):
                yield response + "\n"

        return StreamingResponse(
            generate_stream(),
            media_type='application/x-ndjson'
        )

    except Exception as e:
        # Log the full error for debugging
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        
        # Return a generic error message to the user
        return JSONResponse(
            status_code=500,
            content={
                "type": "error", 
                "content": "Error processing request. Please try again."
            }
        )