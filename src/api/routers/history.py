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
from typing import List, Optional, Any, Dict
from datetime import datetime, timezone
import uuid
import json

from src.config.settings import settings
from src.core.security.dependencies import get_current_user, get_db_session
from src.core.okta.sync.models import QueryHistory, AuthUser, ConversationSession, ConversationTurn
from src.core.okta.sync.operations import DatabaseOperations
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, func
from src.utils.logging import get_logger
from pathlib import Path
from src.data.schemas.artifact_manifest import extract_records
from src.data.schemas.runtime_storage import RUNTIME_ROOT

logger = get_logger(__name__)

router = APIRouter(prefix="/history", tags=["history"])
sessions_router = APIRouter(prefix="/sessions", tags=["sessions"])

PREVIEW_ROW_LIMIT = 25

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


class ConversationTurnResultPreviewResponse(BaseModel):
    available: bool
    display_type: Optional[str] = None
    content: Optional[Any] = None
    metadata: Optional[Dict[str, Any]] = None


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


def _resolve_safe_runtime_path(raw_path: Optional[str]) -> Optional[Path]:
    if not raw_path:
        return None

    try:
        resolved_path = Path(raw_path).resolve()
        allowed_roots = [Path("logs").resolve(), RUNTIME_ROOT.resolve()]
        if any(resolved_path.is_relative_to(root) for root in allowed_roots):
            return resolved_path
    except (OSError, ValueError):
        logger.warning(f"Rejected unsafe runtime path: {raw_path}")

    return None


def _resolve_result_index_file(artifacts_file: Path) -> Path:
    if artifacts_file.parent.name == "artifacts":
        return artifacts_file.parent.parent / "results" / "index.json"
    return artifacts_file.parent / "results" / "index.json"


def _load_json_payload(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    try:
        with open(path, "r", encoding="utf-8") as file_handle:
            payload = json.load(file_handle)
    except (OSError, json.JSONDecodeError):
        return default

    return payload


def _coerce_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_preview_headers(rows: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    if not rows:
        return []

    return [
        {
            "text": str(key).replace("_", " ").title(),
            "value": str(key),
        }
        for key in rows[0].keys()
    ]


def _normalize_headers(headers_like: Any, rows: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    if isinstance(headers_like, list):
        normalized_headers: List[Dict[str, str]] = []
        for header in headers_like:
            if isinstance(header, dict):
                value = header.get("value") or header.get("key") or header.get("field") or header.get("text")
                if not value:
                    continue
                normalized_headers.append(
                    {
                        "text": str(header.get("text") or str(value).replace("_", " ").title()),
                        "value": str(value),
                    }
                )
            elif isinstance(header, str):
                normalized_headers.append(
                    {
                        "text": header.replace("_", " ").title(),
                        "value": header,
                    }
                )
        if normalized_headers:
            return normalized_headers

    return _build_preview_headers(rows)


def _load_turn_output_artifact(turn: ConversationTurn) -> Optional[Dict[str, Any]]:
    artifacts_file = _resolve_safe_runtime_path(turn.artifact_file)
    if not artifacts_file or not artifacts_file.is_file():
        return None

    artifacts = _load_json_payload(artifacts_file, [])
    if not isinstance(artifacts, list):
        return None

    for artifact in reversed(artifacts):
        if not isinstance(artifact, dict):
            continue
        if str(artifact.get("category") or "") != "turn_output":
            continue
        return artifact

    return None


def _load_turn_output_json_payload(turn: ConversationTurn) -> Optional[Dict[str, Any]]:
    artifact = _load_turn_output_artifact(turn)
    if not artifact:
        return None

    content = artifact.get("content")
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        return None

    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None

    return payload if isinstance(payload, dict) else None


def _list_matching_result_entries(turn: ConversationTurn) -> List[Dict[str, Any]]:
    artifacts_file = _resolve_safe_runtime_path(turn.artifact_file)
    if not artifacts_file or not artifacts_file.is_file():
        return []

    result_index_file = _resolve_result_index_file(artifacts_file)
    index_entries = _load_json_payload(result_index_file, [])
    if not isinstance(index_entries, list):
        return []

    matching_entries = [
        entry
        for entry in index_entries
        if isinstance(entry, dict)
        and str(entry.get("session_id") or "") == str(turn.session_id)
        and _coerce_int(entry.get("turn_number")) == turn.turn_number
    ]

    if not matching_entries and turn.run_id:
        matching_entries = [
            entry
            for entry in index_entries
            if isinstance(entry, dict)
            and str(entry.get("run_id") or "") == str(turn.run_id)
        ]

    matching_entries.sort(
        key=lambda entry: (
            float(entry.get("created_at") or 0),
            _coerce_int(entry.get("sequence_in_turn")) or 0,
        ),
        reverse=True,
    )
    return matching_entries


def _build_markdown_turn_preview(turn: ConversationTurn) -> Optional[ConversationTurnResultPreviewResponse]:
    turn_output_artifact = _load_turn_output_artifact(turn)
    if turn_output_artifact and str(turn_output_artifact.get("display_type") or "") == "markdown":
        artifact_content = turn_output_artifact.get("content")
        if isinstance(artifact_content, str) and artifact_content.strip():
            return ConversationTurnResultPreviewResponse(
                available=True,
                display_type="markdown",
                content=artifact_content,
                metadata={
                    "source": "saved_turn_output",
                    "isPreview": False,
                },
            )

    summary_text = str(turn.final_response_summary or "").strip()

    if not summary_text and turn.result_count == 0:
        summary_text = "No matching data was found for this turn."

    if not summary_text:
        return None

    if turn.completion_mode == "empty" or turn.result_count == 0:
        lower_summary = summary_text.lower()
        if "no results" not in lower_summary and "no matching data" not in lower_summary:
            summary_text = f"## No Results Found\n\n{summary_text}"

    return ConversationTurnResultPreviewResponse(
        available=True,
        display_type="markdown",
        content=summary_text,
        metadata={
            "source": "saved_turn_summary",
            "isPreview": False,
        },
    )


def _build_analysis_artifact_preview(turn: ConversationTurn) -> Optional[ConversationTurnResultPreviewResponse]:
    artifacts_file = _resolve_safe_runtime_path(turn.artifact_file)
    if not artifacts_file or not artifacts_file.is_file():
        return None

    artifacts = _load_json_payload(artifacts_file, [])
    if not isinstance(artifacts, list):
        return None

    for artifact in reversed(artifacts):
        if not isinstance(artifact, dict):
            continue
        if str(artifact.get("category") or "") != "analysis_results":
            continue

        artifact_content = artifact.get("content")
        payload: Dict[str, Any] = {}
        if isinstance(artifact_content, str):
            try:
                parsed_payload = json.loads(artifact_content)
                if isinstance(parsed_payload, dict):
                    payload = parsed_payload
            except json.JSONDecodeError:
                payload = {}
        elif isinstance(artifact_content, dict):
            payload = artifact_content

        sample_rows = payload.get("sample_rows") if isinstance(payload.get("sample_rows"), list) else []
        sample_rows = [row for row in sample_rows if isinstance(row, dict)]
        answer_text = str(
            payload.get("answer")
            or artifact.get("notes")
            or payload.get("summary")
            or turn.final_response_summary
            or ""
        ).strip()
        summary_text = str(payload.get("summary") or artifact.get("notes") or answer_text).strip()

        if sample_rows:
            metadata = {
                "headers": _build_preview_headers(sample_rows),
                "count": len(sample_rows),
                "isPreview": True,
                "isStreaming": False,
                "previewRowCount": len(sample_rows),
                "isTruncated": False,
                "summary": summary_text or answer_text,
                "answer": answer_text or None,
                "data_source_type": "saved_session",
            }

            return ConversationTurnResultPreviewResponse(
                available=True,
                display_type="table",
                content=sample_rows,
                metadata=metadata,
            )

        if answer_text:
            return ConversationTurnResultPreviewResponse(
                available=True,
                display_type="markdown",
                content=answer_text,
                metadata={
                    "source": "saved_analysis_artifact",
                    "isPreview": True,
                    "summary": summary_text,
                },
            )

    return None


def _build_table_turn_preview(turn: ConversationTurn) -> Optional[ConversationTurnResultPreviewResponse]:
    for entry in _list_matching_result_entries(turn):
        storage_path = _resolve_safe_runtime_path(str(entry.get("storage_path") or ""))
        if not storage_path or not storage_path.is_file():
            continue

        sidecar = _load_json_payload(storage_path, {})
        if not isinstance(sidecar, dict):
            continue

        inspection = sidecar.get("inspection") if isinstance(sidecar.get("inspection"), dict) else {}
        payload = sidecar.get("data", sidecar)
        preview_rows = extract_records(payload)[:PREVIEW_ROW_LIMIT]
        if not preview_rows:
            sample_rows = inspection.get("sample_rows") if isinstance(inspection.get("sample_rows"), list) else []
            preview_rows = [row for row in sample_rows if isinstance(row, dict)]

        row_count = _coerce_int(entry.get("row_count"))
        if row_count is None:
            row_count = _coerce_int(inspection.get("row_count"))
        if row_count is None and preview_rows:
            row_count = len(preview_rows)

        if row_count == 0 and not preview_rows:
            summary_text = str(
                inspection.get("summary")
                or turn.final_response_summary
                or "No matching data was found for this turn."
            ).strip()
            return ConversationTurnResultPreviewResponse(
                available=True,
                display_type="markdown",
                content=f"## No Results Found\n\n{summary_text}",
                metadata={
                    "source": "saved_result_preview",
                    "isPreview": True,
                },
            )

        if not preview_rows:
            continue

        metadata = {
            "headers": _build_preview_headers(preview_rows),
            "count": row_count if row_count is not None else len(preview_rows),
            "isPreview": True,
            "isStreaming": False,
            "previewRowCount": len(preview_rows),
            "isTruncated": bool(row_count is not None and row_count > len(preview_rows)),
            "summary": inspection.get("summary") or turn.final_response_summary,
            "entity_type": entry.get("entity_type") or inspection.get("entity_type"),
            "key_columns": list(entry.get("key_columns") or inspection.get("key_columns") or []),
            "data_source_type": "saved_session",
        }

        return ConversationTurnResultPreviewResponse(
            available=True,
            display_type="table",
            content=preview_rows,
            metadata=metadata,
        )

    return None


def _build_turn_full_result(
    turn: ConversationTurn,
) -> ConversationTurnResultPreviewResponse:
    if turn.display_type == "markdown" or turn.completion_mode == "direct_answer":
        markdown_result = _build_markdown_turn_preview(turn)
        if markdown_result:
            return markdown_result

    turn_output_payload = _load_turn_output_json_payload(turn)
    if isinstance(turn_output_payload, dict):
        full_rows = extract_records(turn_output_payload)
        payload_metadata = turn_output_payload.get("metadata") if isinstance(turn_output_payload.get("metadata"), dict) else {}
        row_count = _coerce_int(turn_output_payload.get("count"))
        if row_count is None and full_rows:
            row_count = len(full_rows)

        if full_rows:
            total_count = max(row_count or 0, len(full_rows))
            metadata = {
                **payload_metadata,
                "headers": _normalize_headers(turn_output_payload.get("headers"), full_rows),
                "count": total_count,
                "isPreview": False,
                "isStreaming": False,
                "data_source_type": payload_metadata.get("data_source_type") or "saved_session",
                "loadedCount": total_count,
                "allRecordsLoaded": True,
            }
            return ConversationTurnResultPreviewResponse(
                available=True,
                display_type=str(turn_output_payload.get("display_type") or turn.display_type or "table"),
                content=full_rows,
                metadata=metadata,
            )

    for entry in _list_matching_result_entries(turn):
        storage_path = _resolve_safe_runtime_path(str(entry.get("storage_path") or ""))
        if not storage_path or not storage_path.is_file():
            continue

        sidecar = _load_json_payload(storage_path, {})
        if not isinstance(sidecar, dict):
            continue

        inspection = sidecar.get("inspection") if isinstance(sidecar.get("inspection"), dict) else {}
        payload = sidecar.get("data", sidecar)
        full_rows = extract_records(payload)
        if not full_rows:
            sample_rows = inspection.get("sample_rows") if isinstance(inspection.get("sample_rows"), list) else []
            full_rows = [row for row in sample_rows if isinstance(row, dict)]

        row_count = _coerce_int(entry.get("row_count"))
        if row_count is None:
            row_count = _coerce_int(inspection.get("row_count"))
        if row_count is None and full_rows:
            row_count = len(full_rows)

        if row_count == 0 and not full_rows:
            summary_text = str(
                inspection.get("summary")
                or turn.final_response_summary
                or "No matching data was found for this turn."
            ).strip()
            return ConversationTurnResultPreviewResponse(
                available=True,
                display_type="markdown",
                content=f"## No Results Found\n\n{summary_text}",
                metadata={
                    "source": "saved_result_full",
                    "isPreview": False,
                },
            )

        if not full_rows:
            continue

        payload_metadata = payload.get("metadata") if isinstance(payload, dict) and isinstance(payload.get("metadata"), dict) else {}
        total_count = max(row_count or 0, len(full_rows))
        metadata = {
            **payload_metadata,
            "headers": _normalize_headers(payload.get("headers") if isinstance(payload, dict) else None, full_rows),
            "count": total_count,
            "isPreview": False,
            "isStreaming": False,
            "summary": inspection.get("summary") or turn.final_response_summary,
            "entity_type": entry.get("entity_type") or inspection.get("entity_type"),
            "key_columns": list(entry.get("key_columns") or inspection.get("key_columns") or []),
            "data_source_type": payload_metadata.get("data_source_type") or "saved_session",
            "loadedCount": total_count,
            "allRecordsLoaded": True,
        }
        return ConversationTurnResultPreviewResponse(
            available=True,
            display_type=str(payload.get("display_type") or turn.display_type or "table") if isinstance(payload, dict) else (turn.display_type or "table"),
            content=full_rows,
            metadata=metadata,
        )

    analysis_preview = _build_analysis_artifact_preview(turn)
    if analysis_preview:
        analysis_preview.metadata = {
            **(analysis_preview.metadata or {}),
            "isPreview": False,
        }
        return analysis_preview

    markdown_preview = _build_markdown_turn_preview(turn)
    if markdown_preview:
        return markdown_preview

    return ConversationTurnResultPreviewResponse(
        available=False,
        display_type=turn.display_type,
        content=None,
        metadata={
            "source": "saved_turn_full_unavailable",
            "isPreview": False,
        },
    )


def _build_turn_result_preview(turn: ConversationTurn) -> ConversationTurnResultPreviewResponse:
    if turn.display_type == "markdown" or turn.completion_mode == "direct_answer":
        markdown_preview = _build_markdown_turn_preview(turn)
        if markdown_preview:
            return markdown_preview

    if turn.completion_mode == "empty" or turn.result_count == 0:
        markdown_preview = _build_markdown_turn_preview(turn)
        if markdown_preview:
            return markdown_preview

    table_preview = _build_table_turn_preview(turn)
    if table_preview:
        return table_preview

    analysis_preview = _build_analysis_artifact_preview(turn)
    if analysis_preview:
        return analysis_preview

    markdown_preview = _build_markdown_turn_preview(turn)
    if markdown_preview:
        return markdown_preview

    return ConversationTurnResultPreviewResponse(
        available=False,
        display_type=turn.display_type,
        content=None,
        metadata={
            "source": "saved_turn_unavailable",
            "isPreview": True,
        },
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


@sessions_router.get("/{session_id}/turns/{turn_number}/result-preview", response_model=ConversationTurnResultPreviewResponse)
async def get_conversation_turn_result_preview(
    session_id: str,
    turn_number: int,
    current_user: AuthUser = Depends(get_current_user)
):
    """Get a renderable saved-result preview for one persisted conversation turn."""
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

    return _build_turn_result_preview(conversation_turn)


@sessions_router.get("/{session_id}/turns/{turn_number}/result-full", response_model=ConversationTurnResultPreviewResponse)
async def get_conversation_turn_full_result(
    session_id: str,
    turn_number: int,
    current_user: AuthUser = Depends(get_current_user)
):
    """Get the full saved result payload for one persisted conversation turn."""
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

    return _build_turn_full_result(conversation_turn)


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
