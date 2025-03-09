from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from typing import Dict, AsyncGenerator, Tuple, List
import json
import re
from src.utils.logging import logger
from src.backend.app.services.ai_service import AIService

router = APIRouter()

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
    
    # Limit length to prevent DoS
    if len(query) > 2000:
        query = query[:2000]
        warnings.append("Query truncated due to excessive length")
        
    # Remove control characters except newlines and tabs
    original_length = len(query)
    query = ''.join(char for char in query if ord(char) >= 32 or char in '\n\t')
    if len(query) != original_length:
        warnings.append("Control characters removed from query")
    
    # Detect patterns that shouldn't be in natural language queries
    suspicious_patterns = [
        # Code blocks
        (r'```.*?```', "code block"),
        
        # Script injection attempts - Enhanced patterns
        (r'<\s*script\b[^>]*>.*?<\s*/\s*script\s*>', "script tag"),
        (r'javascript\s*:', "JavaScript protocol"),
        
        # SQL in what should be natural language
        (r'(?i)(?:select|insert|update|delete|drop|alter|create)\s+(?:from|into|table|database)', "SQL-like syntax"),
        
        # HTML/XML-like syntax - Enhanced patterns
        (r'<\s*[a-z]+\b[^>]*>', "HTML-like tag"),
        
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
    
    # Enhanced script tag removal
    # This handles variations like <script>, < script>, </script >, etc.
    query = re.sub(r'<\s*script\b[^>]*>.*?<\s*/\s*script\s*>', '', query, flags=re.IGNORECASE | re.DOTALL)
    
    # Also handle unclosed script tags
    query = re.sub(r'<\s*script\b[^>]*>', '', query, flags=re.IGNORECASE)
    
    # Enhanced event handler removal that handles more variations
    query = re.sub(r'\bon\w+\s*=\s*([\'"]|&quot;|&#39;).*?\1', '', query, flags=re.IGNORECASE)
    query = re.sub(r'\bon\w+\s*=\s*[^\s>]+', '', query, flags=re.IGNORECASE)  # Unquoted handlers
    
    # Remove data: URIs which can contain JavaScript
    query = re.sub(r'data\s*:\s*\w+/\w+\s*;\s*base64', 'data-removed', query, flags=re.IGNORECASE)
    
    return query.strip(), warnings

@router.post("/query")
async def process_query(request: Request):
    try:
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
        
        # Log security warnings if any were found
        if warnings:
            logger.warning(f"Security warnings for query from IP {client_ip}: {', '.join(warnings)}")
        
        logger.info(f"Processing query from {client_ip}: {sanitized_query[:100]}...")
            
        async def generate_stream():
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