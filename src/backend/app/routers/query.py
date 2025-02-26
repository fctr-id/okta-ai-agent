from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from typing import Dict, AsyncGenerator
import json
from src.utils.logging import logger
from src.backend.app.services.ai_service import AIService

router = APIRouter()

@router.post("/query")
async def process_query(request: Request):
    try:
        data = await request.json()
        query = data.get("query")
        
        if not query:
            return JSONResponse(
                status_code=400,
                content={"type": "error", "content": "Query is required"}
            )

        logger.info(f"Processing query: {query}")
        
        async def generate_stream():
            async for response in AIService.process_query(query):
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