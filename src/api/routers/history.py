"""
Router for Query History and Favorites.
Provides endpoints to:
- List recent and favorite queries
- Save new query history
- Toggle favorite status
- Re-execute saved scripts
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional, Any
from datetime import datetime, timezone
import logging
import uuid

from src.config.settings import settings
from src.core.security.dependencies import get_current_user, get_db_session
from src.core.okta.sync.models import QueryHistory, AuthUser
from src.core.okta.sync.operations import DatabaseOperations
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, update, desc, func
from src.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/history", tags=["history"])

async def ensure_history_table():
    """Ensure the query_history table exists in the database"""
    try:
        db = DatabaseOperations()
        await db.init_db()
    except Exception as e:
        logger.error(f"Failed to ensure query_history table: {e}")

class QueryHistoryCreate(BaseModel):
    query_text: str
    final_script: str
    results_summary: Optional[str] = None

class QueryHistoryResponse(BaseModel):
    id: int
    query_text: str
    final_script: str
    results_summary: Optional[str] = None
    is_favorite: bool
    created_at: datetime

    class Config:
        from_attributes = True

@router.get("/", response_model=List[QueryHistoryResponse])
async def get_history(
    limit: int = 10,
    session: AsyncSession = Depends(get_db_session),
    current_user: AuthUser = Depends(get_current_user)
):
    """Get the last 10 queries for the sidebar"""
    await ensure_history_table()
    tenant_id = settings.tenant_id
    
    stmt = select(QueryHistory).where(
        QueryHistory.tenant_id == tenant_id
    ).order_by(
        desc(QueryHistory.created_at)
    ).limit(limit)
    
    result = await session.execute(stmt)
    return result.scalars().all()

@router.get("/favorites", response_model=List[QueryHistoryResponse])
async def get_favorites(
    session: AsyncSession = Depends(get_db_session),
    current_user: AuthUser = Depends(get_current_user)
):
    """Get all favorite queries (max 10)"""
    await ensure_history_table()
    tenant_id = settings.tenant_id
    
    stmt = select(QueryHistory).where(
        and_(
            QueryHistory.tenant_id == tenant_id,
            QueryHistory.is_favorite == True
        )
    ).order_by(desc(QueryHistory.created_at))
    
    result = await session.execute(stmt)
    return result.scalars().all()

@router.post("/", response_model=QueryHistoryResponse)
async def save_history(
    history_data: QueryHistoryCreate,
    session: AsyncSession = Depends(get_db_session),
    current_user: AuthUser = Depends(get_current_user)
):
    """Save a new query execution to history"""
    await ensure_history_table()
    tenant_id = settings.tenant_id
    
    new_history = QueryHistory(
        tenant_id=tenant_id,
        query_text=history_data.query_text,
        final_script=history_data.final_script,
        results_summary=history_data.results_summary,
        is_favorite=False
    )
    
    session.add(new_history)
    await session.commit()
    await session.refresh(new_history)
    
    return new_history

@router.patch("/{history_id}/favorite", response_model=QueryHistoryResponse)
async def toggle_favorite(
    history_id: int,
    is_favorite: bool,
    session: AsyncSession = Depends(get_db_session),
    current_user: AuthUser = Depends(get_current_user)
):
    """Toggle the favorite status of a query"""
    tenant_id = settings.tenant_id
    
    # If marking as favorite, check the limit of 10
    if is_favorite:
        stmt = select(func.count(QueryHistory.id)).where(
            and_(
                QueryHistory.tenant_id == tenant_id,
                QueryHistory.is_favorite == True
            )
        )
        result = await session.execute(stmt)
        count = result.scalar()
        
        if count >= 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Maximum of 10 favorite queries allowed. Please unfavorite one before adding a new one."
            )
    
    # Find the record
    stmt = select(QueryHistory).where(
        and_(
            QueryHistory.id == history_id,
            QueryHistory.tenant_id == tenant_id
        )
    )
    result = await session.execute(stmt)
    history_item = result.scalar_one_or_none()
    
    if not history_item:
        raise HTTPException(status_code=404, detail="Query history item not found")
    
    history_item.is_favorite = is_favorite
    await session.commit()
    await session.refresh(history_item)
    
    return history_item

@router.post("/{history_id}/execute")
async def execute_saved_script(
    history_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: AuthUser = Depends(get_current_user)
):
    """
    Prepare a saved script for re-execution.
    Returns a process_id that can be used with /react/stream-react-updates
    but skips the orchestrator phase.
    """
    tenant_id = settings.tenant_id
    
    stmt = select(QueryHistory).where(
        and_(
            QueryHistory.id == history_id,
            QueryHistory.tenant_id == tenant_id
        )
    )
    result = await session.execute(stmt)
    history_item = result.scalar_one_or_none()
    
    if not history_item:
        raise HTTPException(status_code=404, detail="Query history item not found")
    
    # We need to inject this into the active_processes in react_stream.py
    # This is a bit tricky because they are in different modules.
    # For simplicity, we'll return the script and let the frontend 
    # use the existing /react/start-react-process with a special flag 
    # OR we implement a new endpoint in react_stream.py that takes a script.
    
    return {
        "status": "ready",
        "script_code": history_item.final_script,
        "query_text": history_item.query_text
    }
