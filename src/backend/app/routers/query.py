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
        
        # Get the first response to check type
        async for first_response in AIService.process_query(query):
            response_data = json.loads(first_response)
            
            # If it's a text response, return directly without streaming
            if response_data.get("type") == "text":
                return JSONResponse(content=response_data)
                
            # For stream data, continue with streaming
            async def generate_stream():
                # Yield the first response we already got
                yield first_response + "\n"
                # Continue with remaining stream
                async for result in AIService.process_query(query):
                    yield result + "\n"

            return StreamingResponse(
                generate_stream(),
                media_type='application/x-ndjson'
            )

    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"type": "error", "content": str(e)}
        )