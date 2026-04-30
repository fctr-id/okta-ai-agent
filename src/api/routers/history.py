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
from src.core.okta.sync.models import QueryHistory, AuthUser, ConversationSession, ConversationTurn
from src.core.okta.sync.operations import DatabaseOperations
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, update, desc, func
from src.utils.logging import get_logger
from pathlib import Path
import os

logger = get_logger(__name__)

router = APIRouter(prefix="/history", tags=["history"])
sessions_router = APIRouter(prefix="/sessions", tags=["sessions"])

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


class ConversationSessionCreate(BaseModel):
    session_id: Optional[str] = None
    source: str = "web"
    title: Optional[str] = None
    summary: Optional[str] = None
    parent_session_id: Optional[str] = None
    handoff_reason: Optional[str] = None
    started_from_query_history_id: Optional[int] = None


class ConversationSessionUpdate(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    status: Optional[str] = None
    is_pinned: Optional[bool] = None
    is_archived: Optional[bool] = None
    archived_at: Optional[datetime] = None
    parent_session_id: Optional[str] = None
    handoff_reason: Optional[str] = None


class ConversationTurnResponse(BaseModel):
    id: int
    session_id: str
    run_id: str
    turn_number: int
    query_text: str
    source: str
    status: str
    completion_mode: Optional[str] = None
    approval_state: Optional[str] = None
    deferred_execution_state: Optional[str] = None
    display_type: Optional[str] = None
    final_response_summary: Optional[str] = None
    result_count: Optional[int] = None
    is_partial_result: bool
    token_usage_json: Optional[Any] = None
    turn_dir: Optional[str] = None
    artifact_file: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ConversationSessionResponse(BaseModel):
    id: int
    session_id: str
    source: str
    title: Optional[str] = None
    summary: Optional[str] = None
    status: str
    last_activity_at: datetime
    created_at: datetime
    updated_at: datetime
    slack_thread_ts: Optional[str] = None
    parent_session_id: Optional[str] = None
    handoff_reason: Optional[str] = None
    is_pinned: bool
    is_archived: bool
    archived_at: Optional[datetime] = None
    started_from_query_history_id: Optional[int] = None


class ConversationSessionDetailResponse(ConversationSessionResponse):
    turns: List[ConversationTurnResponse]


def _serialize_conversation_session(item: ConversationSession) -> ConversationSessionResponse:
    return ConversationSessionResponse(
        id=item.id,
        session_id=item.session_id,
        source=item.source,
        title=item.title,
        summary=item.summary,
        status=item.status,
        last_activity_at=item.last_activity_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
        slack_thread_ts=item.slack_thread_ts,
        parent_session_id=item.parent_session_id,
        handoff_reason=item.handoff_reason,
        is_pinned=item.is_pinned,
        is_archived=item.is_archived,
        archived_at=item.archived_at,
        started_from_query_history_id=item.started_from_query_history_id,
    )


def _serialize_conversation_turn(item: ConversationTurn) -> ConversationTurnResponse:
    return ConversationTurnResponse(
        id=item.id,
        session_id=item.session_id,
        run_id=item.run_id,
        turn_number=item.turn_number,
        query_text=item.query_text,
        source=item.source,
        status=item.status,
        completion_mode=item.completion_mode,
        approval_state=item.approval_state,
        deferred_execution_state=item.deferred_execution_state,
        display_type=item.display_type,
        final_response_summary=item.final_response_summary,
        result_count=item.result_count,
        is_partial_result=item.is_partial_result,
        token_usage_json=item.token_usage_json,
        turn_dir=item.turn_dir,
        artifact_file=item.artifact_file,
        started_at=item.started_at,
        completed_at=item.completed_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )

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
        and_(
            QueryHistory.tenant_id == tenant_id,
            func.lower(QueryHistory.user_id) == func.lower(current_user.username)
        )
    ).order_by(
        desc(QueryHistory.is_favorite),
        desc(QueryHistory.last_run_at)
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
            func.lower(QueryHistory.user_id) == func.lower(current_user.username),
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
    """
    Save a new query execution to history.
    
    NOTE: This endpoint is rarely used - history is auto-saved by react_stream.py
    using DatabaseOperations.save_query_history() which has full UPSERT logic.
    This endpoint exists for manual saves or testing.
    """
    await ensure_history_table()
    tenant_id = settings.tenant_id
    
    new_history = QueryHistory(
        tenant_id=tenant_id,
        user_id=current_user.username,
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
    """Toggle the favorite status of a query (max 10 favorites enforced)"""
    tenant_id = settings.tenant_id
    
    # If marking as favorite, check the limit with row-level locking
    if is_favorite:
        # Use SELECT FOR UPDATE to prevent race condition (per-user limit)
        stmt = select(func.count(QueryHistory.id)).where(
            and_(
                QueryHistory.tenant_id == tenant_id,
                func.lower(QueryHistory.user_id) == func.lower(current_user.username),
                QueryHistory.is_favorite == True
            )
        ).with_for_update()
        
        result = await session.execute(stmt)
        count = result.scalar()
        
        if count >= 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Maximum of 10 favorite queries allowed. Please unfavorite one before adding a new one."
            )
    
    # Find and lock the record to prevent concurrent modifications
    # Security: verify user owns this history item
    stmt = select(QueryHistory).where(
        and_(
            QueryHistory.id == history_id,
            QueryHistory.tenant_id == tenant_id,
            func.lower(QueryHistory.user_id) == func.lower(current_user.username)
        )
    ).with_for_update()
    
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
            QueryHistory.tenant_id == tenant_id,
            func.lower(QueryHistory.user_id) == func.lower(current_user.username)
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


@sessions_router.post("/", response_model=ConversationSessionResponse)
async def create_conversation_session(
    session_data: ConversationSessionCreate,
    current_user: AuthUser = Depends(get_current_user)
):
    """Create or reuse a conversation session for the current user."""
    await ensure_history_table()
    db = DatabaseOperations()
    session_id = session_data.session_id or str(uuid.uuid4())
    created = await db.create_conversation_session(
        tenant_id=settings.tenant_id,
        user_id=current_user.username,
        session_id=session_id,
        source=session_data.source,
        title=session_data.title,
        summary=session_data.summary,
        parent_session_id=session_data.parent_session_id,
        handoff_reason=session_data.handoff_reason,
        started_from_query_history_id=session_data.started_from_query_history_id,
    )
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create conversation session")
    return _serialize_conversation_session(created)


@sessions_router.get("/", response_model=List[ConversationSessionResponse])
async def list_conversation_sessions(
    limit: int = 10,
    include_archived: bool = False,
    current_user: AuthUser = Depends(get_current_user)
):
    """List recent conversation sessions for the current user."""
    await ensure_history_table()
    db = DatabaseOperations()
    sessions = await db.list_conversation_sessions(
        tenant_id=settings.tenant_id,
        user_id=current_user.username,
        limit=limit,
        include_archived=include_archived,
    )
    return [_serialize_conversation_session(item) for item in sessions]


@sessions_router.get("/{session_id}", response_model=ConversationSessionDetailResponse)
async def get_conversation_session_detail(
    session_id: str,
    turn_limit: int = 100,
    current_user: AuthUser = Depends(get_current_user)
):
    """Get one conversation session with lightweight turn history."""
    await ensure_history_table()
    db = DatabaseOperations()
    conversation_session = await db.get_conversation_session(
        tenant_id=settings.tenant_id,
        user_id=current_user.username,
        session_id=session_id,
    )
    if not conversation_session:
        raise HTTPException(status_code=404, detail="Conversation session not found")

    turns = await db.list_conversation_turns(
        tenant_id=settings.tenant_id,
        user_id=current_user.username,
        session_id=session_id,
        limit=turn_limit,
    )
    return ConversationSessionDetailResponse(
        **_serialize_conversation_session(conversation_session).dict(),
        turns=[_serialize_conversation_turn(item) for item in turns],
    )


@sessions_router.get("/{session_id}/turns/{turn_number}", response_model=ConversationTurnResponse)
async def get_conversation_turn_detail(
    session_id: str,
    turn_number: int,
    current_user: AuthUser = Depends(get_current_user)
):
    """Get one conversation turn owned by the current user."""
    await ensure_history_table()
    db = DatabaseOperations()
    conversation_turn = await db.get_conversation_turn(
        tenant_id=settings.tenant_id,
        user_id=current_user.username,
        session_id=session_id,
        turn_number=turn_number,
    )
    if not conversation_turn:
        raise HTTPException(status_code=404, detail="Conversation turn not found")
    return _serialize_conversation_turn(conversation_turn)


@sessions_router.patch("/{session_id}", response_model=ConversationSessionResponse)
async def update_conversation_session_metadata(
    session_id: str,
    session_data: ConversationSessionUpdate,
    current_user: AuthUser = Depends(get_current_user)
):
    """Rename or update lightweight conversation session metadata."""
    await ensure_history_table()
    update_payload = session_data.model_dump(exclude_none=True) if hasattr(session_data, "model_dump") else session_data.dict(exclude_none=True)
    if not update_payload:
        raise HTTPException(status_code=400, detail="No session updates provided")

    db = DatabaseOperations()
    updated = await db.update_conversation_session(
        tenant_id=settings.tenant_id,
        user_id=current_user.username,
        session_id=session_id,
        updates=update_payload,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Conversation session not found")
    return _serialize_conversation_session(updated)
