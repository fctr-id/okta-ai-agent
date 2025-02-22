from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from typing import Dict
import json
from src.backend.app.services.ai_service import AIService
from src.utils.logging import logger

router = APIRouter()

@router.post("/query")
async def process_query(request: Request):
    """Process user queries and return streaming results"""
    try:
        logger.info("Received new query request")
        logger.debug(f"Request headers: {request.headers}")
        
        data = await request.json()
        query = data.get("query")
        
        if not query:
            logger.warning("Received empty query")
            raise HTTPException(status_code=400, detail="Query is required")

        logger.info(f"Processing query: {query}")
        stream = AIService.process_query(query)
        
        logger.debug("Initializing StreamingResponse")
        return StreamingResponse(
            stream,
            media_type='application/json'
        )
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in request: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON payload"
        )
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )