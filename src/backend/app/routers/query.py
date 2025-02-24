from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from typing import Dict, AsyncGenerator
import json
from src.utils.logging import logger
from src.backend.app.services.ai_service import AIService

router = APIRouter()

@router.post("/query")
async def process_query(request: Request):
    """Process queries using AIService and return streaming results"""
    try:
        data = await request.json()
        query = data.get("query")
        
        if not query:
            return JSONResponse(
                status_code=400,
                content={
                    "type": "error",
                    "content": "Query is required"
                }
            )

        logger.info(f"Processing query: {query}")
        
        async def generate_stream():
            async for result in AIService.process_query(query):
                # Parse the JSON string from AIService
                result_dict = json.loads(result)
                
                if result_dict.get("status") == "error":
                    yield json.dumps({
                        "type": "error",
                        "content": result_dict.get("message", "Unknown error occurred")
                    }) + "\n"
                else:
                    # Format successful response
                    yield json.dumps({
                        "type": "stream",
                        "content": result_dict.get("results", []),
                        "metadata": {
                            "query": result_dict.get("query"),
                            "sql": result_dict.get("sql"),
                            "explanation": result_dict.get("explanation"),
                            "last_sync": result_dict.get("last_sync"),
                            "headers": [
                                {"text": key.title(), "value": key} 
                                for key in (result_dict.get("results", [{}])[0].keys() if result_dict.get("results") else [])
                            ]
                        }
                    }) + "\n"

        return StreamingResponse(
            generate_stream(),
            media_type='application/x-ndjson'
        )

    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "type": "error",
                "content": str(e)
            }
        )