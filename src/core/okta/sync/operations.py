"""
Database operations for Okta entity synchronization.
Provides async SQLAlchemy operations for managing Okta entities and relationships.

Key features:
- Async database operations
- Bulk upsert with relationship handling
- Soft delete support
- Sync history tracking
"""

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, and_, not_, or_, update, func, text, delete, desc, event
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import List, Type, TypeVar, Optional, Dict, Any, AsyncGenerator, Union

from .models import Base, User, UserFactor, group_application_assignments, AuthUser, UserRole, SyncHistory, SyncStatus, Device, UserDevice, QueryHistory, ConversationSession, ConversationTurn, ConversationResultSet, ConversationResultSetParent
from src.core.security.password_hasher import hash_password, verify_password, check_password_needs_rehash, calculate_lockout_time
from src.config.settings import settings
from src.data.schemas.runtime_storage import RUNTIME_ROOT, sanitize_path_part
from src.utils.logging import logger
import asyncio


ModelType = TypeVar('ModelType', bound=Base)
_HYDRATED_SESSION_RESULT_REF_MARKER = "hydrated_session_result_ref"
_DEFAULT_COMPACT_KEEP_RECENT_TURNS = 10
_DEFAULT_COMPACT_SUMMARY_TURNS = 12
_DEFAULT_UNPINNED_SESSION_LIMIT = 10
_COMPACTED_TURN_SUMMARY_PREFIX = "Compacted earlier turns ("


def _build_async_engine(database_url: str):
    engine = create_async_engine(
        database_url,
        connect_args={
            "timeout": 30,
            "check_same_thread": False,
        },
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    return engine


def _load_json_file(path: Optional[Union[str, Path]], default: Any) -> Any:
    if not path:
        return default

    file_path = Path(path)
    if not file_path.exists():
        return default

    try:
        with open(file_path, "r", encoding="utf-8") as file_handle:
            return json.load(file_handle)
    except (OSError, json.JSONDecodeError):
        return default


def _write_json_file(path: Union[str, Path], payload: Any) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as file_handle:
        json.dump(payload, file_handle, indent=2, default=str)


def _resolve_result_index_file(artifacts_file: Union[str, Path]) -> Path:
    artifacts_path = Path(artifacts_file)
    if artifacts_path.parent.name == "artifacts":
        return artifacts_path.parent.parent / "results" / "index.json"
    return artifacts_path.parent / "results" / "index.json"


def _result_set_status(result_set_row: Any) -> str:
    if getattr(result_set_row, "is_empty", False):
        return "empty"
    if getattr(result_set_row, "is_partial", False):
        return "partial"
    return "available"


def _result_set_summary(result_set_row: Any) -> str:
    entity_type = str(getattr(result_set_row, "entity_type", None) or "records")
    row_count = getattr(result_set_row, "row_count", None)
    key_columns = list(getattr(result_set_row, "key_columns_json", None) or [])
    user_facing_label = getattr(result_set_row, "user_facing_label", None)
    turn_number = getattr(result_set_row, "turn_number", None)
    filter_summary = getattr(result_set_row, "filter_summary", None)

    prefix = f"{user_facing_label}: " if user_facing_label else ""
    if row_count is None:
        summary = f"{prefix}Saved prior-session {entity_type} result set"
    else:
        summary = f"{prefix}Saved prior-session result set with {row_count} {entity_type}"

    if turn_number:
        summary += f" from turn {turn_number}"
    summary += "."

    if key_columns:
        summary += f" Key columns: {', '.join(key_columns[:6])}."
    if filter_summary:
        summary += f" Filter: {filter_summary}."
    return summary


def _hydrated_result_set_metadata(result_set_row: Any) -> Dict[str, Any]:
    metadata = dict(getattr(result_set_row, "metadata_json", None) or {})
    metadata[_HYDRATED_SESSION_RESULT_REF_MARKER] = True
    metadata["source_turn_number"] = getattr(result_set_row, "turn_number", None)
    metadata["source_run_id"] = getattr(result_set_row, "run_id", None)
    metadata["source_session_id"] = getattr(result_set_row, "session_id", None)
    return metadata


def _result_set_artifact_category(metadata: Any) -> Optional[str]:
    if not isinstance(metadata, dict):
        return None
    category = str(metadata.get("artifact_category") or "").strip().lower()
    return category or None


def _is_cross_turn_referenceable_result_ref(result_ref: Dict[str, Any]) -> bool:
    metadata = result_ref.get("metadata") if isinstance(result_ref.get("metadata"), dict) else {}
    return _result_set_artifact_category(metadata) == "turn_output"


def _is_cross_turn_referenceable_result_set_row(result_set_row: Any) -> bool:
    metadata = getattr(result_set_row, "metadata_json", None)
    return _result_set_artifact_category(metadata) == "turn_output"


def _load_hydrated_result_set_inspection(result_set_row: Any) -> Dict[str, Any]:
    row_count = int(getattr(result_set_row, "row_count", None) or 0)
    key_columns = list(getattr(result_set_row, "key_columns_json", None) or [])
    fallback_inspection = {
        "summary": _result_set_summary(result_set_row),
        "row_count": row_count,
        "key_columns": key_columns,
        "sample_rows": [],
        "entity_type": str(getattr(result_set_row, "entity_type", None) or "records"),
    }

    stored_payload = _load_json_file(getattr(result_set_row, "storage_path", None), {})
    if not isinstance(stored_payload, dict):
        return fallback_inspection

    stored_inspection = stored_payload.get("inspection")
    if not isinstance(stored_inspection, dict):
        return fallback_inspection

    merged_inspection = dict(stored_inspection)
    merged_inspection.setdefault("summary", fallback_inspection["summary"])
    merged_inspection.setdefault("row_count", fallback_inspection["row_count"])
    merged_inspection.setdefault("key_columns", fallback_inspection["key_columns"])
    merged_inspection.setdefault("sample_rows", fallback_inspection["sample_rows"])
    merged_inspection.setdefault("entity_type", fallback_inspection["entity_type"])
    return merged_inspection


def _build_hydrated_result_set_ref(result_set_row: Any) -> Dict[str, Any]:
    key_columns = list(getattr(result_set_row, "key_columns_json", None) or [])
    created_at = getattr(result_set_row, "created_at", None)
    created_at_value = created_at.timestamp() if isinstance(created_at, datetime) else None

    return {
        "result_set_id": str(result_set_row.result_set_id),
        "storage_path": str(result_set_row.storage_path),
        "row_count": int(result_set_row.row_count or 0),
        "entity_type": str(result_set_row.entity_type or "records"),
        "key_columns": key_columns,
        "source_specialist": str(result_set_row.source_specialist or "unknown"),
        "derivation_kind": str(result_set_row.derivation_kind or "initial"),
        "status": _result_set_status(result_set_row),
        "parent_result_set_ids": [],
        "artifact_keys": [f"session_result_ref_{result_set_row.result_set_id}"],
        "user_facing_label": result_set_row.user_facing_label,
        "session_id": result_set_row.session_id,
        "run_id": result_set_row.run_id,
        "turn_number": result_set_row.turn_number,
        "sequence_in_turn": result_set_row.sequence_in_turn,
        "filter_summary": result_set_row.filter_summary,
        "created_at": created_at_value,
        "metadata": _hydrated_result_set_metadata(result_set_row),
    }


def _build_hydrated_result_set_artifact(result_set_row: Any) -> Dict[str, Any]:
    artifact_key = f"session_result_ref_{result_set_row.result_set_id}"
    key_columns = list(getattr(result_set_row, "key_columns_json", None) or [])
    summary = _result_set_summary(result_set_row)
    created_at = getattr(result_set_row, "created_at", None)
    created_at_value = created_at.timestamp() if isinstance(created_at, datetime) else None
    metadata = _hydrated_result_set_metadata(result_set_row)
    inspection = _load_hydrated_result_set_inspection(result_set_row)

    return {
        "key": artifact_key,
        "category": "session_result_refs",
        "notes": summary,
        "result_set_refs": [str(result_set_row.result_set_id)],
        "result_set_inspection": inspection,
        "artifact_manifest": {
            "artifact_key": artifact_key,
            "category": "session_result_refs",
            "storage_path": str(result_set_row.storage_path),
            "summary": summary,
            "source_specialist": str(result_set_row.source_specialist or "unknown"),
            "row_count": getattr(result_set_row, "row_count", None),
            "entity_type": str(result_set_row.entity_type or "records"),
            "key_columns": key_columns,
            "result_set_refs": [str(result_set_row.result_set_id)],
            "created_at": created_at_value,
            "metadata": metadata,
        },
    }


def _is_hydrated_session_result_artifact(artifact: Dict[str, Any]) -> bool:
    artifact_manifest = artifact.get("artifact_manifest") if isinstance(artifact.get("artifact_manifest"), dict) else {}
    metadata = artifact_manifest.get("metadata") if isinstance(artifact_manifest.get("metadata"), dict) else {}
    return bool(metadata.get(_HYDRATED_SESSION_RESULT_REF_MARKER))


def _is_hydrated_session_result_ref(result_ref: Dict[str, Any]) -> bool:
    metadata = result_ref.get("metadata") if isinstance(result_ref.get("metadata"), dict) else {}
    return bool(metadata.get(_HYDRATED_SESSION_RESULT_REF_MARKER))


def _to_utc_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)

    return None


def _derive_completion_mode(status: Optional[str], summary: Dict[str, Any]) -> Optional[str]:
    outcome = summary.get("outcome") if isinstance(summary.get("outcome"), dict) else {}
    result_mode = str(outcome.get("result_mode") or "").strip().lower()

    if status == "error":
        return "fail"
    if summary.get("is_special_tool"):
        return "direct_answer"
    if result_mode == "empty":
        return "empty"
    if result_mode == "degraded_success":
        return "degraded_success"
    if result_mode == "needs_clarification":
        return "clarify"
    if status == "completed":
        return "script"
    return None


def _truncate_compaction_text(value: Any, max_length: int) -> Optional[str]:
    if value is None:
        return None

    text = " ".join(str(value).split()).strip()
    if not text:
        return None
    if len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip() + "..."


def _build_turn_compaction_summary(turn: ConversationTurn) -> Optional[str]:
    query_text = _truncate_compaction_text(turn.query_text, 120)
    response_summary = _truncate_compaction_text(turn.final_response_summary, 180)
    parts = [f"Turn {turn.turn_number}"]

    if query_text:
        parts.append(f"query={query_text}")
    if turn.status:
        parts.append(f"status={turn.status}")
    if turn.completion_mode:
        parts.append(f"mode={turn.completion_mode}")
    if turn.result_count is not None:
        parts.append(f"results={turn.result_count}")
    if response_summary:
        parts.append(f"summary={response_summary}")

    return "; ".join(parts) if len(parts) > 1 else None


def _serialize_recent_turn_summary(turn: ConversationTurn) -> Dict[str, Any]:
    return {
        "turn_number": turn.turn_number,
        "query_text": _truncate_compaction_text(turn.query_text, 160),
        "status": turn.status,
        "completion_mode": turn.completion_mode,
        "display_type": turn.display_type,
        "final_response_summary": _truncate_compaction_text(turn.final_response_summary, 220),
        "result_count": turn.result_count,
        "is_partial_result": turn.is_partial_result,
        "started_at": turn.started_at.isoformat() if isinstance(turn.started_at, datetime) else None,
        "completed_at": turn.completed_at.isoformat() if isinstance(turn.completed_at, datetime) else None,
    }


def _extract_base_session_summary(session_summary: Optional[str]) -> Optional[str]:
    summary_text = _truncate_compaction_text(session_summary, 600)
    if not summary_text:
        return None

    if summary_text.startswith(_COMPACTED_TURN_SUMMARY_PREFIX):
        return None

    split_marker = f"\n\n{_COMPACTED_TURN_SUMMARY_PREFIX}"
    if split_marker in summary_text:
        summary_text = summary_text.split(split_marker, 1)[0].rstrip()

    return summary_text or None


def _build_session_compaction_summary(
    session_summary: Optional[str],
    older_turns: List[ConversationTurn],
    *,
    max_summary_turns: int,
) -> Optional[str]:
    summary_parts: List[str] = []
    base_summary = _extract_base_session_summary(session_summary)
    if base_summary:
        summary_parts.append(base_summary)

    older_turn_summaries = [
        turn_summary
        for turn_summary in (
            _build_turn_compaction_summary(turn)
            for turn in older_turns[-max_summary_turns:]
        )
        if turn_summary
    ]
    if older_turn_summaries:
        summary_parts.append(
            f"{_COMPACTED_TURN_SUMMARY_PREFIX}{len(older_turns)} total): " + " | ".join(older_turn_summaries)
        )

    if not summary_parts:
        return None

    return "\n\n".join(summary_parts)


def _conversation_runtime_session_dir(user_id: str, session_id: str) -> Path:
    safe_user_id = sanitize_path_part(user_id, fallback="user")
    safe_session_id = sanitize_path_part(session_id, fallback="session")
    return RUNTIME_ROOT / "sessions" / f"{safe_user_id}-{safe_session_id}"

class DatabaseOperations:
    """Singleton database operations class with shared engine and connection pool."""
    _init_lock = asyncio.Lock()  # Class-level lock for thread-safe initialization
    _initialized = False  # Class-level flag (shared across all instances)
    _engine = None  # Shared engine (expensive resource)
    _SessionLocal = None  # Shared session factory
    _retention_cleanup_tasks: set[asyncio.Task] = set()
    _retention_cleanup_inflight_keys: set[tuple[str, str]] = set()
    
    def __init__(self):
        """Initialize async database engine with WAL mode (reuses existing engine if available)."""
        if DatabaseOperations._engine is None:
            DatabaseOperations._engine = _build_async_engine(settings.DATABASE_URL)
            DatabaseOperations._SessionLocal = async_sessionmaker(
                DatabaseOperations._engine,
                expire_on_commit=False
            )
        
        # Use class-level attributes
        self.engine = DatabaseOperations._engine
        self.SessionLocal = DatabaseOperations._SessionLocal

    def _discover_db_path(self) -> Optional[str]:
        """Find the existing database file in common locations"""
        try:
            from pathlib import Path
            import os
            
            # Project root is 4 levels up from this file
            project_root = Path(__file__).parent.parent.parent.parent
            
            possible_paths = [
                Path("/app/sqlite_db/okta_sync.db"),
                project_root / "sqlite_db" / "okta_sync.db",
                Path(os.getcwd()) / "sqlite_db" / "okta_sync.db",
                Path(settings.SQLITE_PATH) if hasattr(settings, 'SQLITE_PATH') else None
            ]
            
            # Filter None and duplicates
            possible_paths = [p for p in possible_paths if p is not None]
            
            for p in possible_paths:
                if p.exists():
                    logger.debug(f"Discovered existing database at: {p}")
                    return str(p)
            return None
        except Exception as e:
            logger.error(f"Error during DB discovery: {e}")
            return None

    async def init_db(self):
        """Initialize database with WAL mode and optimized settings (thread-safe)"""
        async with DatabaseOperations._init_lock:
            if not DatabaseOperations._initialized:
                # Try to discover existing DB before initializing
                db_path = self._discover_db_path()
                if db_path and settings.SQLITE_PATH != db_path:
                    logger.info(f"Re-centering database to discovered path: {db_path}")
                    settings.SQLITE_PATH = db_path
                    settings.DATABASE_URL = f"sqlite+aiosqlite:///{db_path}"
                    
                    # Re-create engine if path changed
                    await self.close()
                    self.engine = _build_async_engine(settings.DATABASE_URL)
                    self.SessionLocal = async_sessionmaker(self.engine, expire_on_commit=False)

            async with self.engine.begin() as conn:
                # Enable WAL mode
                await conn.execute(text("PRAGMA journal_mode=WAL"))
                await conn.execute(text("PRAGMA foreign_keys=ON"))
                # Set synchronous mode for better performance
                await conn.execute(text("PRAGMA synchronous=NORMAL"))
                # Create tables
                await conn.run_sync(Base.metadata.create_all)
                
                # Ensure query_history table exists (for existing databases)
                from sqlalchemy import inspect
                def get_tables(connection):
                    inspector = inspect(connection)
                    return inspector.get_table_names()
                
                tables = await conn.run_sync(get_tables)

                if 'query_history' not in tables:
                    logger.info("Creating query_history table...")
                    from sqlalchemy.schema import CreateTable
                    await conn.execute(CreateTable(QueryHistory.__table__))
                    logger.info("Query history table created successfully")
                else:
                    # Check for missing columns (migration)
                    def get_columns(connection):
                        inspector = inspect(connection)
                        return [c['name'] for c in inspector.get_columns('query_history')]
                    
                    columns = await conn.run_sync(get_columns)
                    if 'last_run_at' not in columns:
                        logger.info("Migrating query_history: adding last_run_at column")
                        await conn.execute(text("ALTER TABLE query_history ADD COLUMN last_run_at DATETIME"))
                        # Set default for existing records
                        await conn.execute(text("UPDATE query_history SET last_run_at = created_at"))
                    
                    if 'user_id' not in columns:
                        logger.info("Migrating query_history: adding user_id column")
                        await conn.execute(text("ALTER TABLE query_history ADD COLUMN user_id VARCHAR(255) NOT NULL DEFAULT 'localadmin'"))
                        # Create index for user_id
                        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_query_history_user_id ON query_history(user_id)"))
                    
                    # Slack integration columns (added in PR #17)
                    if 'source' not in columns:
                        logger.info("Migrating query_history: adding source column")
                        await conn.execute(text("ALTER TABLE query_history ADD COLUMN source VARCHAR(20) NOT NULL DEFAULT 'web'"))
                        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_query_history_source ON query_history(source)"))
                    
                    if 'slack_user_id' not in columns:
                        logger.info("Migrating query_history: adding slack_user_id column")
                        await conn.execute(text("ALTER TABLE query_history ADD COLUMN slack_user_id VARCHAR(255)"))
                    
                    if 'slack_channel_id' not in columns:
                        logger.info("Migrating query_history: adding slack_channel_id column")
                        await conn.execute(text("ALTER TABLE query_history ADD COLUMN slack_channel_id VARCHAR(255)"))
                    
                    if 'slack_thread_ts' not in columns:
                        logger.info("Migrating query_history: adding slack_thread_ts column")
                        await conn.execute(text("ALTER TABLE query_history ADD COLUMN slack_thread_ts VARCHAR(255)"))
                
                DatabaseOperations._initialized = True
            
    async def close(self):
        """Close database connection"""
        if self.engine:
            await self.engine.dispose()            

    @asynccontextmanager    
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Get async database session with automatic commit/rollback.
        
        Yields:
            AsyncSession: Database session
            
        Raises:
            Exception: On database errors, session is rolled back
            
        Usage:
            async with db.get_session() as session:
                await session.execute(stmt)
        """    
        async with self.SessionLocal() as session:
            try:
                yield session
                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.error(f"Database session error: {str(e)}")
                raise
    
    async def bulk_upsert(
        self,
        session: AsyncSession,
        model: Type[ModelType],
        records: List[dict],
        tenant_id: str
    ) -> bool:
        """
        Bulk upsert records with support for nested relationships.
        
        Args:
            session: Active database session
            model: SQLAlchemy model class (User, Group etc)
            records: List of record dictionaries from Okta
            tenant_id: Tenant identifier
            
        Returns:
            bool: True if successful
            
        Raises:
            Exception: On database errors
            
        Notes:
            - Handles nested user factors for User model
            - Updates existing records
            - Creates new records
            - Sets sync timestamps
            - Handles custom_attributes JSON column for User model
        """
        try:
            total_factors = 0
            total_user_devices = 0
            
            for record in records:
                # Extract factors if present (User model)
                factors = record.pop('factors', []) if model == User else None
                if model == User:
                    total_factors += len(factors) if factors else 0
                
                # Extract user_devices if present (Device model) 
                user_devices = record.pop('user_devices', []) if model == Device else None
                if model == Device:
                    total_user_devices += len(user_devices) if user_devices else 0
                
                # Process main record
                stmt = select(model).where(
                    and_(
                        model.okta_id == record['okta_id'],
                        model.tenant_id == tenant_id
                    )
                )
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()
    
                if existing:
                    for key, value in record.items():
                        if hasattr(existing, key):
                            # Handle JSON column properly
                            if key == 'custom_attributes' and isinstance(value, dict):
                                setattr(existing, key, value)
                            else:
                                setattr(existing, key, value)
                    existing.last_synced_at = datetime.utcnow()
                else:
                    record['tenant_id'] = tenant_id
                    record['last_synced_at'] = datetime.utcnow()
                    # Ensure custom_attributes is properly set for new records
                    if model == User and 'custom_attributes' not in record:
                        record['custom_attributes'] = {}
                    existing = model(**record)
                    session.add(existing)
                
                # Process factors if present
                if factors:
                    await self._process_user_factors(session, existing, factors, tenant_id)
                    
                # Process user-device relationships if present (Device model)
                if user_devices:
                    await self._process_device_user_relationships(session, existing, user_devices, tenant_id)                    
    
            # Logging
            if model == User:
                logger.debug(f"Processed {len(records)} users with {total_factors} factors")
            elif model == Device:
                logger.debug(f"Processed {len(records)} devices with {total_user_devices} user relationships")
            else:
                logger.info(f"Processed {len(records)} {model.__name__} records")
            return True
        except Exception as e:
            logger.error(f"Bulk upsert error for {model.__name__}: {str(e)}")
            raise
    
    async def mark_deleted(
        self,
        session: AsyncSession,
        model: Type[ModelType],
        okta_ids: List[str],
        tenant_id: str
    ) -> bool:
        """
        Soft delete records not present in Okta anymore.
        
        Args:
            session: Active database session
            model: SQLAlchemy model class
            okta_ids: List of active Okta IDs
            tenant_id: Tenant identifier
            
        Returns:
            bool: True if successful
            
        Notes:
            Sets is_deleted=True for records not in okta_ids
        """        
            
        try:
            stmt = select(model).where(
                and_(
                    model.tenant_id == tenant_id,
                    not_(model.okta_id.in_(okta_ids))
                )
            )
            result = await session.execute(stmt)
            records = result.scalars().all()
            
            for record in records:
                record.is_deleted = True
                record.last_synced_at = datetime.utcnow()
            
            return True
        except Exception as e:
            logger.error(f"Mark deleted error for {model.__name__}: {str(e)}")
            raise

        # Fix the get_last_sync_time method to use end_time instead of sync_end_time
    async def get_last_sync_time(
        self,
        session: AsyncSession,
        model: Type[ModelType],
        tenant_id: str
    ) -> Optional[datetime]:
        """
        Get timestamp of last successful sync for incremental updates.
        """
        try:
            from .models import SyncHistory, SyncStatus
            
            # Handle both SUCCESS and COMPLETED status values
            stmt = select(SyncHistory.end_time)\
                .where(
                    and_(
                        SyncHistory.tenant_id == tenant_id,
                        SyncHistory.entity_type == model.__name__,
                        SyncHistory.status.in_([SyncStatus.SUCCESS, SyncStatus.COMPLETED]),
                        SyncHistory.records_processed > 0
                    )
                )\
                .order_by(SyncHistory.end_time.desc())
                
            result = await session.execute(stmt)
            return result.scalar()
            
        except Exception as e:
            logger.error(f"Get last sync time error for {model.__name__}: {str(e)}")
            return None
        
    async def _process_user_factors(
        self,
        session: AsyncSession,
        user: User,
        factors: List[Dict[str, Any]],
        tenant_id: str
    ) -> None:
        """
        Process MFA factors for a user.
        
        Args:
            session: Active database session
            user: User model instance
            factors: List of factor dictionaries from Okta
            tenant_id: Tenant identifier
            
        Raises:
            Exception: On database errors
            
        Notes:
            - Creates/updates user factors
            - Marks removed factors as deleted
            - Maintains factor sync timestamps
        """        
        try:
            logger.debug(f"Processing {len(factors)} factors for user {user.okta_id}")
            factor_ids = []
            logger.debug(f"factor data: {factors}")
            for factor in factors:
                # Add tenant context
                factor['tenant_id'] = tenant_id
                factor['user_okta_id'] = user.okta_id
                
                # Find existing factor
                stmt = select(UserFactor).where(
                    and_(
                        UserFactor.okta_id == factor['okta_id'],
                        UserFactor.tenant_id == tenant_id,
                        UserFactor.user_okta_id == user.okta_id
                    )
                )
                result = await session.execute(stmt)
                existing_factor = result.scalar_one_or_none()
    
                if existing_factor:
                    # Update existing factor
                    for key, value in factor.items():
                        if hasattr(existing_factor, key):
                            setattr(existing_factor, key, value)
                    existing_factor.last_synced_at = datetime.utcnow()
                else:
                    # Create new factor
                    new_factor = UserFactor(**factor)
                    session.add(new_factor)
                
                factor_ids.append(factor['okta_id'])
    
            # Mark deleted factors
            stmt = select(UserFactor).where(
                and_(
                    UserFactor.user_okta_id == user.okta_id,
                    UserFactor.tenant_id == tenant_id,
                    not_(UserFactor.okta_id.in_(factor_ids))
                )
            )
            result = await session.execute(stmt)
            deleted_factors = result.scalars().all()
            
            for factor in deleted_factors:
                factor.is_deleted = True
                factor.last_synced_at = datetime.utcnow()
    
            await session.commit()
    
        except Exception as e:
            logger.error(f"Error processing factors for user {user.okta_id}: {str(e)}")
            raise  
               
    async def _process_group_relationships(
        self,
        session: AsyncSession,
        group_data: Dict,
        tenant_id: str  # Added tenant_id parameter
    ) -> None:
        """
        Process group application assignments.
        
        Args:
            session: Active database session
            group_data: Group data with relationships
            tenant_id: Tenant identifier
            
        Raises:
            Exception: On database errors
            
        Notes:
            - Handles group-application assignments
            - Updates assignment metadata
            - Maintains sync timestamps
        """ 
        try:
            # Process application assignments
            app_assignments = group_data.pop('applications', [])
            if app_assignments:
                for assignment in app_assignments:
                    stmt = group_application_assignments.insert().values(
                        tenant_id=tenant_id,  # Using the passed tenant_id parameter
                        group_okta_id=assignment['group_okta_id'],
                        application_okta_id=assignment['application_okta_id'],
                        assignment_id=assignment['assignment_id']
                    ).on_conflict_do_update(
                        index_elements=['tenant_id', 'group_okta_id', 'application_okta_id'],
                        set_=dict(
                            assignment_id=assignment['assignment_id'],
                            updated_at=datetime.utcnow()
                        )
                    )
                    await session.execute(stmt)
            
        except Exception as e:
            logger.error(f"Error processing group relationships: {str(e)}")
            raise     
        
    async def _process_device_user_relationships(
        self,
        session: AsyncSession,
        device: Device,
        user_devices: List[Dict[str, Any]],
        tenant_id: str
    ) -> None:
        """
        Process user-device relationships for a device.
        
        Args:
            session: Active database session
            device: Device model instance
            user_devices: List of user-device relationship dictionaries
            tenant_id: Tenant identifier
            
        Raises:
            Exception: On database errors
            
        Notes:
            - Creates/updates user-device relationships
            - Validates that users exist before creating relationships
            - Marks removed relationships as deleted
            - Maintains relationship sync timestamps
        """        
        try:
            logger.debug(f"Processing {len(user_devices)} user relationships for device {device.okta_id}")
            relationship_keys = []
            
            for user_device_data in user_devices:
                user_okta_id = user_device_data['user_okta_id']
                
                # Validate that user exists before creating relationship
                user_exists_stmt = select(User).where(
                    and_(
                        User.okta_id == user_okta_id,
                        User.tenant_id == tenant_id,
                        User.is_deleted == False
                    )
                )
                user_result = await session.execute(user_exists_stmt)
                if not user_result.scalar_one_or_none():
                    logger.warning(f"Skipping device-user relationship: user {user_okta_id} not found for device {device.okta_id}")
                    continue
                
                # Add context
                user_device_data['tenant_id'] = tenant_id
                user_device_data['device_okta_id'] = device.okta_id
                
                # Find existing relationship
                stmt = select(UserDevice).where(
                    and_(
                        UserDevice.user_okta_id == user_okta_id,
                        UserDevice.device_okta_id == device.okta_id,
                        UserDevice.tenant_id == tenant_id
                    )
                )
                result = await session.execute(stmt)
                existing_relationship = result.scalar_one_or_none()
    
                if existing_relationship:
                    # Update existing relationship
                    for key, value in user_device_data.items():
                        if hasattr(existing_relationship, key):
                            setattr(existing_relationship, key, value)
                    existing_relationship.last_synced_at = datetime.utcnow()
                else:
                    # Create new relationship
                    new_relationship = UserDevice(**user_device_data)
                    session.add(new_relationship)
                
                relationship_keys.append((user_okta_id, device.okta_id))
    
            # Mark deleted relationships (soft delete)
            if relationship_keys:
                # Build the condition for relationships that should remain active
                active_conditions = [
                    and_(
                        UserDevice.user_okta_id == user_id,
                        UserDevice.device_okta_id == device_id
                    )
                    for user_id, device_id in relationship_keys
                ]
                
                # Find relationships to mark as deleted
                stmt = select(UserDevice).where(
                    and_(
                        UserDevice.device_okta_id == device.okta_id,
                        UserDevice.tenant_id == tenant_id,
                        not_(or_(*active_conditions))
                    )
                )
            else:
                # No active relationships - mark all as deleted
                stmt = select(UserDevice).where(
                    and_(
                        UserDevice.device_okta_id == device.okta_id,
                        UserDevice.tenant_id == tenant_id
                    )
                )
            
            result = await session.execute(stmt)
            deleted_relationships = result.scalars().all()
            
            for relationship in deleted_relationships:
                relationship.is_deleted = True
                relationship.last_synced_at = datetime.utcnow()
    
            await session.commit()
    
        except Exception as e:
            logger.error(f"Error processing user relationships for device {device.okta_id}: {str(e)}")
            raise                  
        
    #Authentication methods:

    async def get_auth_user(self, session: AsyncSession, username: str) -> Optional[AuthUser]:
        """Get a user by username"""
        result = await session.execute(select(AuthUser).where(AuthUser.username == username))
        return result.scalars().first()

    async def create_auth_user(self, session: AsyncSession, username: str, password: str, 
                            role: UserRole = UserRole.ADMIN) -> AuthUser:
        """Create a new authentication user"""
        password_hash = hash_password(password)
        
        user = AuthUser(
            username=username,
            password_hash=password_hash,
            role=role,
            setup_completed=True
        )
        
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user

    async def check_setup_completed(self, session: AsyncSession) -> bool:
        """Check if the initial setup has been completed"""
        result = await session.execute(select(func.count(AuthUser.id)).where(AuthUser.setup_completed == True))
        count = result.scalar()
        return count > 0

    async def update_password(self, session: AsyncSession, username: str, new_password: str) -> bool:
        """Update a user's password"""
        password_hash = hash_password(new_password)
        
        stmt = (
            update(AuthUser)
            .where(AuthUser.username == username)
            .values(
                password_hash=password_hash,
                updated_at=datetime.now(timezone.utc)
            )
        )
        
        result = await session.execute(stmt)
        await session.commit()
        
        return result.rowcount > 0

    async def verify_user_credentials(self, session: AsyncSession, username: str, 
                                    password: str) -> Union[AuthUser, None]:
        """Verify user credentials and handle login attempts"""
        user = await self.get_auth_user(session, username)
        
        if not user:
            logger.warning(f"Login attempt for non-existent user: {username}")
            return None
        
        if not user.is_active:
            logger.warning(f"Login attempt for inactive user: {username}")
            return None
            
        # Check if the account is temporarily locked
        now = datetime.now(timezone.utc)
        if user.locked_until and user.locked_until > now:
            logger.warning(f"Login attempt for locked account: {username}")
            return None
        
        # Verify password
        if verify_password(user.password_hash, password):
            # Successful login - reset attempts and update last login
            user.login_attempts = 0
            user.last_login = now
            user.locked_until = None
            
            # Check if password needs rehashing
            if check_password_needs_rehash(user.password_hash):
                user.password_hash = hash_password(password)
                
            await session.commit()
            return user
        else:
            # Failed login - increment attempts and possibly lock account
            user.login_attempts += 1
            
            # After 5 failed attempts, lock the account temporarily
            if user.login_attempts >= 5:
                user.locked_until = calculate_lockout_time(user.login_attempts)
                logger.warning(f"Account locked due to failed attempts: {username}")
                
            await session.commit()
            return None        
        
    # Fixed sync history methods to take session and tenant_id as parameters

    async def get_active_sync(self, session: AsyncSession, tenant_id: str) -> Optional[SyncHistory]:
        """
        Get currently running sync if any
        Returns SyncHistory object or None
        
        Args:
            session: Active database session
            tenant_id: Tenant identifier
        """
        query = select(SyncHistory).where(
            and_(
                SyncHistory.tenant_id == tenant_id,
                SyncHistory.status.in_([SyncStatus.RUNNING, SyncStatus.IDLE])
            )
        ).order_by(SyncHistory.start_time.desc()).limit(1)
        
        result = await session.execute(query)
        return result.scalars().first()

    async def get_last_completed_sync(self, session: AsyncSession, tenant_id: str) -> Optional[SyncHistory]:
        """
        Get the most recently completed sync
        Returns SyncHistory object or None
        
        Args:
            session: Active database session
            tenant_id: Tenant identifier
        """
        query = select(SyncHistory).where(
            and_(
                SyncHistory.tenant_id == tenant_id,
                SyncHistory.status.in_([SyncStatus.COMPLETED, SyncStatus.FAILED, SyncStatus.CANCELED])
            )
        ).order_by(SyncHistory.end_time.desc()).limit(1)
        
        result = await session.execute(query)
        return result.scalars().first()

    async def create_sync_history(self, session: AsyncSession, tenant_id: str) -> SyncHistory:
        """
        Create a new sync history entry
        Returns the created SyncHistory object
        
        Args:
            session: Active database session
            tenant_id: Tenant identifier
        """
        sync_history = SyncHistory(
            tenant_id=tenant_id,
            status=SyncStatus.IDLE,
            start_time=datetime.utcnow()
        )
        
        session.add(sync_history)
        await session.commit()
        await session.refresh(sync_history)
        return sync_history

    async def update_sync_history(self, session: AsyncSession, sync_id: int, tenant_id: str, data: Dict) -> Optional[SyncHistory]:
        """
        Update an existing sync history entry
        Returns the updated SyncHistory object
        
        Args:
            session: Active database session
            sync_id: ID of the sync history entry
            tenant_id: Tenant identifier
            data: Dictionary of fields to update
        """
        query = select(SyncHistory).where(
            and_(
                SyncHistory.id == sync_id,
                SyncHistory.tenant_id == tenant_id
            )
        )
        
        result = await session.execute(query)
        sync_history = result.scalars().first()
        
        if not sync_history:
            logger.error(f"Sync history with ID {sync_id} not found for tenant {tenant_id}")
            return None
            
        for key, value in data.items():
            if hasattr(sync_history, key):
                setattr(sync_history, key, value)
        
        await session.commit()
        await session.refresh(sync_history)
        return sync_history

    async def get_sync_history(self, session: AsyncSession, tenant_id: str, limit: int = 5) -> List[SyncHistory]:
        """
        Get recent sync history entries
        Returns a list of SyncHistory objects
        
        Args:
            session: Active database session
            tenant_id: Tenant identifier
            limit: Maximum number of entries to return
        """
        query = select(SyncHistory).where(
            SyncHistory.tenant_id == tenant_id
        ).order_by(SyncHistory.start_time.desc()).limit(limit)
        
        result = await session.execute(query)
        return result.scalars().all()        
    
    # Clean up sync history table
    async def cleanup_sync_history(self, tenant_id: str, keep_count: int = 30):
        """
        Keep only the most recent sync history entries per tenant.
        Groups by day and entity_type to maintain a complete picture of recent syncs.
        
        Args:
            tenant_id: The tenant ID to clean up
            keep_count: Number of days of history to keep per entity type
        """
        async with self.get_session() as session:
            # First, identify the dates we want to keep (most recent N days with sync activity)
            from sqlalchemy import func, select, delete, distinct
            
            # Get the distinct dates (truncated to day) with sync activity, ordered by most recent
            date_query = select(
                distinct(func.date(SyncHistory.start_time)).label("sync_date")
            ).where(
                SyncHistory.tenant_id == tenant_id
            ).order_by(
                text("sync_date DESC")
            ).limit(keep_count)
            
            result = await session.execute(date_query)
            dates_to_keep = [row[0] for row in result]
            
            if not dates_to_keep:
                return  # No sync history to clean up
            
            # Get the cutoff date (oldest date we want to keep)
            cutoff_date = min(dates_to_keep)
            
            # Delete all records older than the cutoff date
            delete_stmt = delete(SyncHistory).where(
                SyncHistory.tenant_id == tenant_id,
                func.date(SyncHistory.start_time) < cutoff_date
            )
            
            await session.execute(delete_stmt)
            await session.commit()
            
            logger.info(f"Cleaned up sync history for tenant {tenant_id}, keeping records since {cutoff_date}")

    async def save_query_history(
        self,
        tenant_id: str,
        user_id: str,
        query_text: str,
        final_script: str,
        results_summary: str = "",
        source: str = "web",
        slack_user_id: Optional[str] = None,
        slack_channel_id: Optional[str] = None,
        slack_thread_ts: Optional[str] = None,
    ) -> Optional[QueryHistory]:
        """
        Save a successful query execution to history with rolling 15-entry limit per user.
        
        Limit Rules:
        - Max 10 favorites (protected from deletion)
        - Max 5 non-favorites (rolling window - oldest deleted when limit reached)
        - Total max: 15 entries per user (not global)
        
        UPSERT Logic:
        - If exact query + script exists for this user, updates timestamp (prevents duplicates)
        - If new query, checks limit and deletes oldest non-favorite if needed
        
        NOTE: Creates its own database session for use in background tasks.
        For synchronous operations within request context, use router endpoints.
        """
        try:
            async with self.get_session() as session:
                # Ensure table exists
                await self.init_db()
                
                # Check for existing entry by normalized query text only (UPSERT per-user)
                # Normalize: case-insensitive and trimmed
                normalized_query = query_text.strip().lower()
                
                stmt = select(QueryHistory).where(
                    and_(
                        QueryHistory.tenant_id == tenant_id,
                        QueryHistory.user_id == user_id,
                        func.lower(func.trim(QueryHistory.query_text)) == normalized_query
                    )
                ).order_by(QueryHistory.last_run_at.desc())  # Get most recent if multiple exist
                
                result = await session.execute(stmt)
                existing = result.scalars().first()  # Use first() instead of scalar_one_or_none() to handle duplicates

                if existing:
                    # Update existing record
                    existing.last_run_at = datetime.now(timezone.utc)
                    existing.results_summary = results_summary
                    existing.execution_count = existing.execution_count + 1  # Increment counter
                    existing.source = source
                    if slack_user_id:
                        existing.slack_user_id = slack_user_id
                    if slack_channel_id:
                        existing.slack_channel_id = slack_channel_id
                    if slack_thread_ts:
                        existing.slack_thread_ts = slack_thread_ts

                    # If NOT favorited, update the script with new one
                    # If favorited, preserve the starred script
                    if not existing.is_favorite:
                        existing.final_script = final_script
                        logger.debug(f"Updated query history (id={existing.id}) with new script, execution_count={existing.execution_count}")
                    else:
                        logger.debug(f"Updated query history (id={existing.id}), preserved favorite script, execution_count={existing.execution_count}")
                    
                    await session.commit()
                    await session.refresh(existing)
                    return existing
                
                # NEW ENTRY - Enforce rolling 15-entry limit per user
                # Count non-favorites for this user
                count_stmt = select(func.count(QueryHistory.id)).where(
                    and_(
                        QueryHistory.tenant_id == tenant_id,
                        QueryHistory.user_id == user_id,
                        QueryHistory.is_favorite == False
                    )
                )
                count_result = await session.execute(count_stmt)
                non_fav_count = count_result.scalar()
                
                # If we have 5+ non-favorites, delete the oldest one to make room
                MAX_NON_FAVORITES = 5  # 15 total - 10 max favorites = 5 non-favorites
                if non_fav_count >= MAX_NON_FAVORITES:
                    # Find oldest non-favorite by last_run_at for this user
                    oldest_stmt = select(QueryHistory).where(
                        and_(
                            QueryHistory.tenant_id == tenant_id,
                            QueryHistory.user_id == user_id,
                            QueryHistory.is_favorite == False
                        )
                    ).order_by(QueryHistory.last_run_at.asc()).limit(1)
                    
                    oldest_result = await session.execute(oldest_stmt)
                    oldest = oldest_result.scalar_one_or_none()
                    
                    if oldest:
                        await session.delete(oldest)
                        logger.info(f"Deleted oldest non-favorite history (id={oldest.id}) to maintain 15-entry limit")
                
                # Create new entry
                new_history = QueryHistory(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    query_text=query_text,
                    final_script=final_script,
                    results_summary=results_summary,
                    is_favorite=False,
                    last_run_at=datetime.now(timezone.utc),
                    source=source,
                    slack_user_id=slack_user_id,
                    slack_channel_id=slack_channel_id,
                    slack_thread_ts=slack_thread_ts,
                )
                
                session.add(new_history)
                await session.commit()
                await session.refresh(new_history)
                logger.debug(f"Created new query history (id={new_history.id})")
                return new_history
                
        except Exception as e:
            logger.error(f"Failed to save query history: {e}", exc_info=True)
            return None

    async def create_conversation_session(
        self,
        *,
        tenant_id: str,
        user_id: str,
        session_id: str,
        source: str = "web",
        title: Optional[str] = None,
        summary: Optional[str] = None,
        status: str = "active",
        parent_session_id: Optional[str] = None,
        handoff_reason: Optional[str] = None,
        started_from_query_history_id: Optional[int] = None,
    ) -> Optional[ConversationSession]:
        """Create or return an existing conversation session for a user."""
        try:
            async with self.get_session() as session:
                stmt = select(ConversationSession).where(
                    and_(
                        ConversationSession.tenant_id == tenant_id,
                        ConversationSession.session_id == session_id,
                        func.lower(ConversationSession.user_id) == func.lower(user_id),
                    )
                )
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()
                if existing:
                    return existing

                new_session = ConversationSession(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    session_id=session_id,
                    source=source,
                    title=title,
                    summary=summary,
                    status=status,
                    last_activity_at=datetime.now(timezone.utc),
                    parent_session_id=parent_session_id,
                    handoff_reason=handoff_reason,
                    started_from_query_history_id=started_from_query_history_id,
                )
                session.add(new_session)
                await session.commit()
                await session.refresh(new_session)
                await self._schedule_conversation_retention_cleanup_if_needed(
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
                return new_session
        except Exception as e:
            logger.error(f"Failed to create conversation session {session_id}: {e}", exc_info=True)
            return None

    async def _schedule_conversation_retention_cleanup_if_needed(
        self,
        *,
        tenant_id: str,
        user_id: str,
        unpinned_session_limit: int = _DEFAULT_UNPINNED_SESSION_LIMIT,
    ) -> bool:
        """Schedule a best-effort cleanup task after session creation when the threshold is exceeded."""
        try:
            async with self.get_session() as session:
                count_stmt = select(func.count(ConversationSession.id)).where(
                    and_(
                        ConversationSession.tenant_id == tenant_id,
                        func.lower(ConversationSession.user_id) == func.lower(user_id),
                        ConversationSession.is_pinned == False,
                    )
                )
                count_result = await session.execute(count_stmt)
                unpinned_session_count = int(count_result.scalar_one() or 0)
        except Exception as error:
            logger.warning(f"Failed to count sessions for retention cleanup scheduling: {error}")
            return False

        if unpinned_session_count <= unpinned_session_limit:
            return False

        cleanup_key = (tenant_id, user_id.lower())
        if cleanup_key in DatabaseOperations._retention_cleanup_inflight_keys:
            return False

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return False

        async def _run_cleanup() -> None:
            await self.enforce_conversation_retention(
                tenant_id=tenant_id,
                user_id=user_id,
                unpinned_session_limit=unpinned_session_limit,
            )

        task = loop.create_task(_run_cleanup())
        DatabaseOperations._retention_cleanup_inflight_keys.add(cleanup_key)
        DatabaseOperations._retention_cleanup_tasks.add(task)

        def _cleanup_done(completed_task: asyncio.Task) -> None:
            DatabaseOperations._retention_cleanup_tasks.discard(completed_task)
            DatabaseOperations._retention_cleanup_inflight_keys.discard(cleanup_key)
            try:
                completed_task.result()
            except Exception as cleanup_error:
                logger.error(
                    f"Retention cleanup task failed for {user_id}: {cleanup_error}",
                    exc_info=True,
                )

        task.add_done_callback(_cleanup_done)
        return True

    async def _conversation_session_has_blocking_turn_state(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        session_id: str,
    ) -> bool:
        blocking_turn_stmt = select(func.count(ConversationTurn.id)).where(
            and_(
                ConversationTurn.tenant_id == tenant_id,
                ConversationTurn.session_id == session_id,
                or_(
                    ConversationTurn.status.in_(["created", "executing", "running"]),
                    ConversationTurn.approval_state == "pending",
                    ConversationTurn.deferred_execution_state == "deferred",
                ),
            )
        )
        blocking_turn_result = await session.execute(blocking_turn_stmt)
        return bool(blocking_turn_result.scalar_one() or 0)

    async def enforce_conversation_retention(
        self,
        *,
        tenant_id: str,
        user_id: str,
        unpinned_session_limit: int = _DEFAULT_UNPINNED_SESSION_LIMIT,
    ) -> Dict[str, int]:
        """Keep only the newest unpinned conversation sessions for a user."""
        retention_stats = {
            "checked_unpinned_sessions": 0,
            "purged_sessions": 0,
            "overflow_target_sessions": 0,
            "overflow_purged_sessions": 0,
            "skipped_sessions": 0,
            "unpinned_session_limit": unpinned_session_limit,
        }

        try:
            async with self.get_session() as session:
                unpinned_count_stmt = select(func.count(ConversationSession.id)).where(
                    and_(
                        ConversationSession.tenant_id == tenant_id,
                        func.lower(ConversationSession.user_id) == func.lower(user_id),
                        ConversationSession.is_pinned == False,
                    )
                )
                unpinned_count_result = await session.execute(unpinned_count_stmt)
                retention_stats["checked_unpinned_sessions"] = int(unpinned_count_result.scalar_one() or 0)

                overflow_sessions_to_purge = max(
                    0,
                    retention_stats["checked_unpinned_sessions"] - unpinned_session_limit,
                )
                retention_stats["overflow_target_sessions"] = overflow_sessions_to_purge
                runtime_session_dirs: List[tuple[str, Path]] = []

                if overflow_sessions_to_purge > 0:
                    overflow_candidates_stmt = (
                        select(ConversationSession)
                        .where(
                            and_(
                                ConversationSession.tenant_id == tenant_id,
                                func.lower(ConversationSession.user_id) == func.lower(user_id),
                                ConversationSession.is_pinned == False,
                            )
                        )
                        .order_by(ConversationSession.last_activity_at.asc())
                    )
                    overflow_candidates_result = await session.execute(overflow_candidates_stmt)
                    overflow_candidates = list(overflow_candidates_result.scalars().all())

                    for overflow_candidate in overflow_candidates:
                        if overflow_sessions_to_purge <= 0:
                            break

                        if await self._conversation_session_has_blocking_turn_state(
                            session,
                            tenant_id=tenant_id,
                            session_id=overflow_candidate.session_id,
                        ):
                            retention_stats["skipped_sessions"] += 1
                            logger.info(
                                "Skipping overflow purge for conversation session %s because it still has blocking turn state",
                                overflow_candidate.session_id,
                            )
                            continue

                        logger.info(
                            "Purging overflow conversation session %s to enforce unpinned session limit %s",
                            overflow_candidate.session_id,
                            unpinned_session_limit,
                        )
                        runtime_session_dirs.append(
                            (
                                overflow_candidate.session_id,
                                _conversation_runtime_session_dir(
                                    overflow_candidate.user_id,
                                    overflow_candidate.session_id,
                                ),
                            )
                        )
                        await session.delete(overflow_candidate)
                        retention_stats["purged_sessions"] += 1
                        retention_stats["overflow_purged_sessions"] += 1
                        overflow_sessions_to_purge -= 1

                    if retention_stats["overflow_purged_sessions"] > 0:
                        await session.flush()

                    if overflow_sessions_to_purge > 0:
                        logger.warning(
                            "Conversation retention could not purge %s overflow sessions for user %s because remaining candidates were blocked",
                            overflow_sessions_to_purge,
                            user_id,
                        )

                await session.commit()

            for purged_session_id, runtime_session_dir in runtime_session_dirs:
                try:
                    if runtime_session_dir.exists():
                        shutil.rmtree(runtime_session_dir, ignore_errors=True)
                        logger.info(
                            "Removed runtime session directory for purged conversation session %s at %s",
                            purged_session_id,
                            runtime_session_dir,
                        )
                    else:
                        logger.info(
                            "No runtime session directory found for purged conversation session %s at %s",
                            purged_session_id,
                            runtime_session_dir,
                        )
                except Exception as runtime_delete_error:
                    logger.warning(f"Failed to remove runtime session directory {runtime_session_dir}: {runtime_delete_error}")

            if retention_stats["overflow_purged_sessions"] or retention_stats["purged_sessions"]:
                logger.info(
                    "Conversation retention summary for %s: %s",
                    user_id,
                    retention_stats,
                )

            return retention_stats
        except Exception as error:
            logger.error(f"Failed to enforce conversation retention for {user_id}: {error}", exc_info=True)
            return retention_stats

    async def rebuild_session_index(
        self,
        *,
        tenant_id: str,
        session_id: str,
    ) -> Dict[str, int]:
        """Rebuild lightweight SQL indexes for a session from runtime files."""
        rebuild_stats = {
            "discovered_turns": 0,
            "recovered_turn_rows": 0,
            "mirrored_turns": 0,
            "skipped_turns": 0,
        }

        try:
            async with self.get_session() as session:
                session_stmt = select(ConversationSession).where(
                    and_(
                        ConversationSession.tenant_id == tenant_id,
                        ConversationSession.session_id == session_id,
                    )
                )
                session_result = await session.execute(session_stmt)
                conversation_session = session_result.scalar_one_or_none()
                if not conversation_session:
                    return rebuild_stats

                runtime_session_dir = _conversation_runtime_session_dir(
                    conversation_session.user_id,
                    conversation_session.session_id,
                )
                conversation_index_file = runtime_session_dir / "conversation_index.json"
                conversation_index = _load_json_file(conversation_index_file, [])
                if not isinstance(conversation_index, list):
                    conversation_index = []

                turns_stmt = (
                    select(ConversationTurn)
                    .where(
                        and_(
                            ConversationTurn.tenant_id == tenant_id,
                            ConversationTurn.session_id == session_id,
                        )
                    )
                    .order_by(ConversationTurn.turn_number.asc())
                )
                turns_result = await session.execute(turns_stmt)
                existing_turns = list(turns_result.scalars().all())
                turns_by_run_id = {turn.run_id: turn for turn in existing_turns}
                turns_by_number = {turn.turn_number: turn for turn in existing_turns}

                existing_result_ids_stmt = select(ConversationResultSet.result_set_id).where(
                    and_(
                        ConversationResultSet.tenant_id == tenant_id,
                        ConversationResultSet.session_id == session_id,
                    )
                )
                existing_result_ids_result = await session.execute(existing_result_ids_stmt)
                existing_result_ids = [row[0] for row in existing_result_ids_result.all()]
                if existing_result_ids:
                    await session.execute(
                        delete(ConversationResultSetParent).where(
                            or_(
                                ConversationResultSetParent.child_result_set_id.in_(existing_result_ids),
                                ConversationResultSetParent.parent_result_set_id.in_(existing_result_ids),
                            )
                        )
                    )
                await session.execute(
                    delete(ConversationResultSet).where(
                        and_(
                            ConversationResultSet.tenant_id == tenant_id,
                            ConversationResultSet.session_id == session_id,
                        )
                    )
                )

                runtime_path_entries: List[tuple[str, Any]] = []
                latest_activity_at = _to_utc_datetime(conversation_session.last_activity_at) or datetime.now(timezone.utc)
                normalized_entries = sorted(
                    [entry for entry in conversation_index if isinstance(entry, dict)],
                    key=lambda entry: int(entry.get("turn_number") or 0),
                )
                rebuild_stats["discovered_turns"] = len(normalized_entries)

                for entry in normalized_entries:
                    turn_number = int(entry.get("turn_number") or 0)
                    if turn_number <= 0:
                        rebuild_stats["skipped_turns"] += 1
                        continue

                    turn_dir = Path(entry.get("turn_dir") or runtime_session_dir / "turns" / f"{turn_number:04d}")
                    turn_metadata_file = Path(entry.get("turn_metadata_file") or (turn_dir / "turn_metadata.json"))
                    turn_summary_file = Path(entry.get("turn_summary_file") or (turn_dir / "turn_summary.json"))
                    artifacts_file = turn_dir / "artifacts" / "artifacts.json"
                    result_index_file = turn_dir / "results" / "index.json"

                    turn_metadata = _load_json_file(turn_metadata_file, {})
                    if not isinstance(turn_metadata, dict):
                        turn_metadata = {}
                    turn_summary = _load_json_file(turn_summary_file, {})
                    if not isinstance(turn_summary, dict):
                        turn_summary = {}

                    run_id = str(turn_metadata.get("run_id") or entry.get("run_id") or "").strip()
                    if not run_id:
                        rebuild_stats["skipped_turns"] += 1
                        continue

                    conversation_turn = turns_by_run_id.get(run_id) or turns_by_number.get(turn_number)
                    if not conversation_turn:
                        conversation_turn = ConversationTurn(
                            tenant_id=tenant_id,
                            session_id=session_id,
                            run_id=run_id,
                            turn_number=turn_number,
                            query_text=str(turn_summary.get("user_query") or f"Recovered turn {turn_number}"),
                            source=str(turn_summary.get("source") or "user"),
                            status=str(turn_metadata.get("status") or turn_summary.get("status") or "created"),
                            display_type=turn_summary.get("display_type"),
                            final_response_summary=turn_summary.get("final_response_summary"),
                            result_count=turn_summary.get("result_count"),
                            token_usage_json=turn_summary.get("token_usage"),
                            turn_dir=turn_dir.as_posix(),
                            artifact_file=str(turn_summary.get("artifact_file") or artifacts_file.as_posix()),
                            started_at=_to_utc_datetime(turn_metadata.get("created_at")),
                            completed_at=_to_utc_datetime(turn_metadata.get("completed_at")),
                            created_at=_to_utc_datetime(turn_metadata.get("created_at")) or datetime.now(timezone.utc),
                            updated_at=datetime.now(timezone.utc),
                        )
                        session.add(conversation_turn)
                        rebuild_stats["recovered_turn_rows"] += 1
                    else:
                        conversation_turn.turn_number = turn_number
                        conversation_turn.query_text = str(turn_summary.get("user_query") or conversation_turn.query_text)
                        conversation_turn.status = str(turn_metadata.get("status") or turn_summary.get("status") or conversation_turn.status)
                        conversation_turn.display_type = turn_summary.get("display_type") or conversation_turn.display_type
                        conversation_turn.final_response_summary = (
                            turn_summary.get("final_response_summary") or conversation_turn.final_response_summary
                        )
                        conversation_turn.result_count = turn_summary.get("result_count") if turn_summary.get("result_count") is not None else conversation_turn.result_count
                        conversation_turn.token_usage_json = turn_summary.get("token_usage") or conversation_turn.token_usage_json
                        conversation_turn.turn_dir = turn_dir.as_posix()
                        conversation_turn.artifact_file = str(turn_summary.get("artifact_file") or artifacts_file.as_posix())
                        conversation_turn.started_at = _to_utc_datetime(turn_metadata.get("created_at")) or conversation_turn.started_at
                        conversation_turn.completed_at = _to_utc_datetime(turn_metadata.get("completed_at")) or conversation_turn.completed_at
                        conversation_turn.updated_at = datetime.now(timezone.utc)

                    turns_by_run_id[run_id] = conversation_turn
                    turns_by_number[turn_number] = conversation_turn
                    candidate_activity_at = (
                        _to_utc_datetime(turn_metadata.get("completed_at"))
                        or _to_utc_datetime(turn_metadata.get("created_at"))
                        or latest_activity_at
                    )
                    if candidate_activity_at > latest_activity_at:
                        latest_activity_at = candidate_activity_at

                    runtime_path_entries.append(
                        (
                            run_id,
                            SimpleNamespace(
                                turn_dir=turn_dir,
                                turn_metadata_file=turn_metadata_file,
                                turn_summary_file=turn_summary_file,
                                artifacts_file=artifacts_file,
                                result_index_file=result_index_file,
                            ),
                        )
                    )

                conversation_session.last_activity_at = latest_activity_at
                conversation_session.updated_at = datetime.now(timezone.utc)
                await session.commit()

            for run_id, runtime_paths in runtime_path_entries:
                mirrored = await self.mirror_runtime_turn_state(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    runtime_paths=runtime_paths,
                )
                if mirrored:
                    rebuild_stats["mirrored_turns"] += 1
                else:
                    rebuild_stats["skipped_turns"] += 1

            return rebuild_stats
        except Exception as error:
            logger.error(f"Failed to rebuild session index for {session_id}: {error}", exc_info=True)
            return rebuild_stats

    async def get_conversation_session(
        self,
        *,
        tenant_id: str,
        user_id: str,
        session_id: str,
    ) -> Optional[ConversationSession]:
        """Fetch a conversation session owned by a user."""
        try:
            async with self.get_session() as session:
                stmt = select(ConversationSession).where(
                    and_(
                        ConversationSession.tenant_id == tenant_id,
                        ConversationSession.session_id == session_id,
                        func.lower(ConversationSession.user_id) == func.lower(user_id),
                    )
                )
                result = await session.execute(stmt)
                return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Failed to get conversation session {session_id}: {e}", exc_info=True)
            return None

    async def list_conversation_sessions(
        self,
        *,
        tenant_id: str,
        user_id: str,
        limit: int = 10,
        include_archived: bool = False,
    ) -> List[ConversationSession]:
        """List recent conversation sessions for a user."""
        try:
            async with self.get_session() as session:
                conditions = [
                    ConversationSession.tenant_id == tenant_id,
                    func.lower(ConversationSession.user_id) == func.lower(user_id),
                ]
                if not include_archived:
                    conditions.append(ConversationSession.is_archived == False)

                stmt = select(ConversationSession).where(
                    and_(*conditions)
                ).order_by(
                    desc(ConversationSession.is_pinned),
                    desc(ConversationSession.last_activity_at),
                ).limit(limit)

                result = await session.execute(stmt)
                return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Failed to list conversation sessions for {user_id}: {e}", exc_info=True)
            return []

    async def update_conversation_session(
        self,
        *,
        tenant_id: str,
        user_id: str,
        session_id: str,
        updates: Dict[str, Any],
    ) -> Optional[ConversationSession]:
        """Update mutable fields on a conversation session owned by a user."""
        allowed_fields = {
            "title",
            "summary",
            "status",
            "last_activity_at",
            "parent_session_id",
            "handoff_reason",
            "is_pinned",
            "is_archived",
            "archived_at",
        }
        safe_updates = {key: value for key, value in updates.items() if key in allowed_fields}

        try:
            async with self.get_session() as session:
                stmt = select(ConversationSession).where(
                    and_(
                        ConversationSession.tenant_id == tenant_id,
                        ConversationSession.session_id == session_id,
                        func.lower(ConversationSession.user_id) == func.lower(user_id),
                    )
                )
                result = await session.execute(stmt)
                conversation_session = result.scalar_one_or_none()
                if not conversation_session:
                    return None

                for key, value in safe_updates.items():
                    setattr(conversation_session, key, value)

                conversation_session.updated_at = datetime.now(timezone.utc)
                await session.commit()
                await session.refresh(conversation_session)
                return conversation_session
        except Exception as e:
            logger.error(f"Failed to update conversation session {session_id}: {e}", exc_info=True)
            return None

    async def create_conversation_turn(
        self,
        *,
        tenant_id: str,
        user_id: str,
        session_id: str,
        run_id: str,
        query_text: str,
        source: str = "user",
        query_history_id: Optional[int] = None,
        status: str = "created",
        completion_mode: Optional[str] = None,
        approval_state: Optional[str] = None,
        deferred_execution_state: Optional[str] = None,
        display_type: Optional[str] = None,
        final_response_summary: Optional[str] = None,
        result_count: Optional[int] = None,
        is_partial_result: bool = False,
        token_usage_json: Optional[Dict[str, Any]] = None,
        turn_dir: Optional[str] = None,
        artifact_file: Optional[str] = None,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
    ) -> Optional[ConversationTurn]:
        """Create or return a persisted turn placeholder for a conversation session."""
        try:
            async with self.get_session() as session:
                existing_stmt = select(ConversationTurn).where(
                    and_(
                        ConversationTurn.tenant_id == tenant_id,
                        ConversationTurn.run_id == run_id,
                    )
                )
                existing_result = await session.execute(existing_stmt)
                existing_turn = existing_result.scalar_one_or_none()
                if existing_turn:
                    return existing_turn

                session_stmt = select(ConversationSession).where(
                    and_(
                        ConversationSession.tenant_id == tenant_id,
                        ConversationSession.session_id == session_id,
                        func.lower(ConversationSession.user_id) == func.lower(user_id),
                    )
                )
                session_result = await session.execute(session_stmt)
                conversation_session = session_result.scalar_one_or_none()
                if not conversation_session:
                    return None

                max_turn_stmt = select(func.max(ConversationTurn.turn_number)).where(
                    and_(
                        ConversationTurn.tenant_id == tenant_id,
                        ConversationTurn.session_id == session_id,
                    )
                )
                max_turn_result = await session.execute(max_turn_stmt)
                next_turn_number = (max_turn_result.scalar() or 0) + 1

                new_turn = ConversationTurn(
                    tenant_id=tenant_id,
                    session_id=session_id,
                    run_id=run_id,
                    turn_number=next_turn_number,
                    query_text=query_text,
                    source=source,
                    query_history_id=query_history_id,
                    status=status,
                    completion_mode=completion_mode,
                    approval_state=approval_state,
                    deferred_execution_state=deferred_execution_state,
                    display_type=display_type,
                    final_response_summary=final_response_summary,
                    result_count=result_count,
                    is_partial_result=is_partial_result,
                    token_usage_json=token_usage_json,
                    turn_dir=turn_dir,
                    artifact_file=artifact_file,
                    started_at=started_at,
                    completed_at=completed_at,
                )
                session.add(new_turn)
                conversation_session.last_activity_at = datetime.now(timezone.utc)
                conversation_session.updated_at = datetime.now(timezone.utc)
                await session.commit()
                await session.refresh(new_turn)
                return new_turn
        except Exception as e:
            logger.error(f"Failed to create conversation turn for session {session_id}: {e}", exc_info=True)
            return None

    async def get_conversation_turn(
        self,
        *,
        tenant_id: str,
        user_id: str,
        session_id: str,
        turn_number: int,
    ) -> Optional[ConversationTurn]:
        """Fetch a turn that belongs to a user-owned conversation session."""
        try:
            async with self.get_session() as session:
                stmt = select(ConversationTurn).join(
                    ConversationSession,
                    ConversationTurn.session_id == ConversationSession.session_id,
                ).where(
                    and_(
                        ConversationTurn.tenant_id == tenant_id,
                        ConversationTurn.session_id == session_id,
                        ConversationTurn.turn_number == turn_number,
                        func.lower(ConversationSession.user_id) == func.lower(user_id),
                    )
                )
                result = await session.execute(stmt)
                return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Failed to get conversation turn {session_id}/{turn_number}: {e}", exc_info=True)
            return None

    async def list_conversation_turns(
        self,
        *,
        tenant_id: str,
        user_id: str,
        session_id: str,
        limit: int = 100,
    ) -> List[ConversationTurn]:
        """List turns for a user-owned conversation session in turn order."""
        try:
            async with self.get_session() as session:
                stmt = select(ConversationTurn).join(
                    ConversationSession,
                    ConversationTurn.session_id == ConversationSession.session_id,
                ).where(
                    and_(
                        ConversationTurn.tenant_id == tenant_id,
                        ConversationTurn.session_id == session_id,
                        func.lower(ConversationSession.user_id) == func.lower(user_id),
                    )
                ).order_by(
                    ConversationTurn.turn_number.asc()
                ).limit(limit)
                result = await session.execute(stmt)
                return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Failed to list conversation turns for session {session_id}: {e}", exc_info=True)
            return []

    async def update_conversation_turn_by_run_id(
        self,
        *,
        tenant_id: str,
        run_id: str,
        updates: Dict[str, Any],
    ) -> Optional[ConversationTurn]:
        """Update mutable fields on a conversation turn identified by run id."""
        allowed_fields = {
            "status",
            "completion_mode",
            "approval_state",
            "deferred_execution_state",
            "display_type",
            "final_response_summary",
            "result_count",
            "is_partial_result",
            "token_usage_json",
            "turn_dir",
            "artifact_file",
            "started_at",
            "completed_at",
        }
        safe_updates = {key: value for key, value in updates.items() if key in allowed_fields}

        try:
            async with self.get_session() as session:
                stmt = select(ConversationTurn).where(
                    and_(
                        ConversationTurn.tenant_id == tenant_id,
                        ConversationTurn.run_id == run_id,
                    )
                )
                result = await session.execute(stmt)
                conversation_turn = result.scalar_one_or_none()
                if not conversation_turn:
                    return None

                for key, value in safe_updates.items():
                    setattr(conversation_turn, key, value)

                conversation_turn.updated_at = datetime.now(timezone.utc)

                session_stmt = select(ConversationSession).where(
                    and_(
                        ConversationSession.tenant_id == tenant_id,
                        ConversationSession.session_id == conversation_turn.session_id,
                    )
                )
                session_result = await session.execute(session_stmt)
                conversation_session = session_result.scalar_one_or_none()
                if conversation_session:
                    conversation_session.last_activity_at = datetime.now(timezone.utc)
                    conversation_session.updated_at = datetime.now(timezone.utc)

                await session.commit()
                await session.refresh(conversation_turn)
                return conversation_turn
        except Exception as e:
            logger.error(f"Failed to update conversation turn {run_id}: {e}", exc_info=True)
            return None

    async def mirror_runtime_turn_state(
        self,
        *,
        tenant_id: str,
        run_id: str,
        runtime_paths: Any,
    ) -> bool:
        """Mirror runtime turn metadata, artifacts, and result-set refs into SQL rows."""
        try:
            async with self.get_session() as session:
                turn_stmt = select(ConversationTurn).where(
                    and_(
                        ConversationTurn.tenant_id == tenant_id,
                        ConversationTurn.run_id == run_id,
                    )
                )
                turn_result = await session.execute(turn_stmt)
                conversation_turn = turn_result.scalar_one_or_none()
                if not conversation_turn:
                    return False

                session_stmt = select(ConversationSession).where(
                    and_(
                        ConversationSession.tenant_id == tenant_id,
                        ConversationSession.session_id == conversation_turn.session_id,
                    )
                )
                session_result = await session.execute(session_stmt)
                conversation_session = session_result.scalar_one_or_none()

                turn_metadata = _load_json_file(runtime_paths.turn_metadata_file, {})
                turn_summary = _load_json_file(runtime_paths.turn_summary_file, {})
                artifacts = _load_json_file(runtime_paths.artifacts_file, [])
                result_refs = _load_json_file(runtime_paths.result_index_file, [])

                if not isinstance(turn_metadata, dict):
                    turn_metadata = {}
                if not isinstance(turn_summary, dict):
                    turn_summary = {}
                if not isinstance(artifacts, list):
                    artifacts = []
                if not isinstance(result_refs, list):
                    result_refs = []

                current_status = str(turn_metadata.get("status") or conversation_turn.status or "created")
                completion_mode = _derive_completion_mode(current_status, turn_summary)
                completed_at = _to_utc_datetime(turn_metadata.get("completed_at"))
                started_at = _to_utc_datetime(turn_metadata.get("created_at"))
                token_usage = turn_summary.get("token_usage")
                result_count = turn_summary.get("result_count")
                outcome = turn_summary.get("outcome") if isinstance(turn_summary.get("outcome"), dict) else {}

                conversation_turn.status = current_status
                if completion_mode:
                    conversation_turn.completion_mode = completion_mode
                if turn_summary.get("display_type"):
                    conversation_turn.display_type = str(turn_summary.get("display_type"))
                if turn_summary.get("final_response_summary"):
                    conversation_turn.final_response_summary = str(turn_summary.get("final_response_summary"))
                if result_count is not None:
                    conversation_turn.result_count = int(result_count)
                if token_usage is not None:
                    conversation_turn.token_usage_json = token_usage
                conversation_turn.turn_dir = runtime_paths.turn_dir.as_posix()
                conversation_turn.artifact_file = str(
                    turn_summary.get("artifact_file") or runtime_paths.artifacts_file.as_posix()
                )
                if started_at:
                    conversation_turn.started_at = started_at
                if completed_at:
                    conversation_turn.completed_at = completed_at
                conversation_turn.is_partial_result = bool(
                    outcome.get("is_degraded_success")
                    or any(isinstance(ref, dict) and ref.get("status") == "partial" for ref in result_refs)
                )
                conversation_turn.updated_at = datetime.now(timezone.utc)

                if conversation_session:
                    conversation_session.last_activity_at = conversation_turn.completed_at or datetime.now(timezone.utc)
                    if conversation_turn.status == "error":
                        conversation_session.status = "error"
                    elif not conversation_session.is_archived:
                        conversation_session.status = "active"
                    conversation_session.updated_at = datetime.now(timezone.utc)

                existing_result_sets_stmt = select(ConversationResultSet).where(
                    and_(
                        ConversationResultSet.tenant_id == tenant_id,
                        ConversationResultSet.session_id == conversation_turn.session_id,
                        ConversationResultSet.turn_number == conversation_turn.turn_number,
                    )
                )
                existing_result_sets_result = await session.execute(existing_result_sets_stmt)
                existing_result_sets = {
                    row.result_set_id: row for row in existing_result_sets_result.scalars().all()
                }

                result_set_ids_to_refresh: List[str] = []
                parent_rows: List[ConversationResultSetParent] = []
                for index, result_ref in enumerate(result_refs, start=1):
                    if not isinstance(result_ref, dict):
                        continue
                    result_set_id = result_ref.get("result_set_id")
                    storage_path = result_ref.get("storage_path")
                    if not result_set_id or not storage_path:
                        continue
                    if _is_hydrated_session_result_ref(result_ref):
                        continue
                    if not _is_cross_turn_referenceable_result_ref(result_ref):
                        continue
                    status_value = str(result_ref.get("status") or "available")
                    row_count = result_ref.get("row_count")
                    created_at = _to_utc_datetime(result_ref.get("created_at")) or datetime.now(timezone.utc)
                    metadata_json = result_ref.get("metadata") if isinstance(result_ref.get("metadata"), dict) else {}

                    result_set_id_str = str(result_set_id)
                    result_set_row = existing_result_sets.get(result_set_id_str)
                    if not result_set_row:
                        result_set_row = ConversationResultSet(
                            tenant_id=tenant_id,
                            session_id=conversation_turn.session_id,
                            run_id=str(result_ref.get("run_id") or conversation_turn.run_id),
                            turn_number=int(result_ref.get("turn_number") or conversation_turn.turn_number),
                            sequence_in_turn=int(result_ref.get("sequence_in_turn") or index),
                            result_set_id=result_set_id_str,
                            storage_path=str(storage_path),
                            source_specialist=str(result_ref.get("source_specialist") or "unknown"),
                            entity_type=str(result_ref.get("entity_type") or "records"),
                            derivation_kind=str(result_ref.get("derivation_kind") or "initial"),
                            user_facing_label=result_ref.get("user_facing_label"),
                            filter_summary=result_ref.get("filter_summary"),
                            row_count=int(row_count) if row_count is not None else None,
                            is_empty=bool(status_value == "empty" or row_count == 0),
                            is_partial=bool(status_value == "partial" or result_ref.get("is_partial")),
                            key_columns_json=result_ref.get("key_columns"),
                            metadata_json=metadata_json,
                            created_at=created_at,
                        )
                        session.add(result_set_row)
                    else:
                        result_set_row.run_id = str(result_ref.get("run_id") or conversation_turn.run_id)
                        result_set_row.turn_number = int(result_ref.get("turn_number") or conversation_turn.turn_number)
                        result_set_row.sequence_in_turn = int(result_ref.get("sequence_in_turn") or index)
                        result_set_row.storage_path = str(storage_path)
                        result_set_row.source_specialist = str(result_ref.get("source_specialist") or "unknown")
                        result_set_row.entity_type = str(result_ref.get("entity_type") or "records")
                        result_set_row.derivation_kind = str(result_ref.get("derivation_kind") or "initial")
                        result_set_row.user_facing_label = result_ref.get("user_facing_label")
                        result_set_row.filter_summary = result_ref.get("filter_summary")
                        result_set_row.row_count = int(row_count) if row_count is not None else None
                        result_set_row.is_empty = bool(status_value == "empty" or row_count == 0)
                        result_set_row.is_partial = bool(status_value == "partial" or result_ref.get("is_partial"))
                        result_set_row.key_columns_json = result_ref.get("key_columns")
                        result_set_row.metadata_json = metadata_json
                        result_set_row.created_at = created_at

                    result_set_ids_to_refresh.append(result_set_id_str)

                    for parent_result_set_id in result_ref.get("parent_result_set_ids") or []:
                        parent_rows.append(
                            ConversationResultSetParent(
                                child_result_set_id=result_set_id_str,
                                parent_result_set_id=str(parent_result_set_id),
                            )
                        )

                if result_set_ids_to_refresh:
                    await session.execute(
                        delete(ConversationResultSetParent).where(
                            ConversationResultSetParent.child_result_set_id.in_(result_set_ids_to_refresh)
                        )
                    )
                if parent_rows:
                    session.add_all(parent_rows)

                await session.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to mirror runtime turn state for {run_id}: {e}", exc_info=True)
            return False

    async def hydrate_session_result_set_context_for_run(
        self,
        *,
        tenant_id: str,
        run_id: str,
        artifacts_file: Union[str, Path],
        max_result_sets: int = 12,
    ) -> int:
        """Seed a new turn runtime folder with prior session result-set refs for follow-up processing."""
        try:
            runtime_artifacts_file = Path(artifacts_file)
            result_index_file = _resolve_result_index_file(runtime_artifacts_file)

            async with self.get_session() as session:
                turn_stmt = select(ConversationTurn).where(
                    and_(
                        ConversationTurn.tenant_id == tenant_id,
                        ConversationTurn.run_id == run_id,
                    )
                )
                turn_result = await session.execute(turn_stmt)
                conversation_turn = turn_result.scalar_one_or_none()
                if not conversation_turn:
                    return 0

                result_sets_stmt = (
                    select(ConversationResultSet)
                    .where(
                        and_(
                            ConversationResultSet.tenant_id == tenant_id,
                            ConversationResultSet.session_id == conversation_turn.session_id,
                            ConversationResultSet.turn_number < conversation_turn.turn_number,
                            ConversationResultSet.is_empty.is_(False),
                        )
                    )
                    .order_by(
                        desc(ConversationResultSet.turn_number),
                        desc(ConversationResultSet.sequence_in_turn),
                    )
                    .limit(max_result_sets)
                )
                result_sets_result = await session.execute(result_sets_stmt)
                prior_result_sets = [
                    result_set_row
                    for result_set_row in result_sets_result.scalars().all()
                    if _is_cross_turn_referenceable_result_set_row(result_set_row)
                ][:max_result_sets]

            if not prior_result_sets:
                return 0

            existing_artifacts = _load_json_file(runtime_artifacts_file, [])
            if not isinstance(existing_artifacts, list):
                existing_artifacts = []

            existing_result_index = _load_json_file(result_index_file, [])
            if not isinstance(existing_result_index, list):
                existing_result_index = []

            existing_artifact_keys = {
                str(artifact.get("key") or artifact.get("artifact_key"))
                for artifact in existing_artifacts
                if isinstance(artifact, dict) and (artifact.get("key") or artifact.get("artifact_key"))
            }
            existing_result_set_ids = {
                str(entry.get("result_set_id"))
                for entry in existing_result_index
                if isinstance(entry, dict) and entry.get("result_set_id")
            }

            hydrated_artifacts: List[Dict[str, Any]] = []
            hydrated_result_refs: List[Dict[str, Any]] = []

            for result_set_row in prior_result_sets:
                if not result_set_row.storage_path or not Path(result_set_row.storage_path).exists():
                    continue

                artifact_key = f"session_result_ref_{result_set_row.result_set_id}"
                if artifact_key not in existing_artifact_keys:
                    hydrated_artifacts.append(_build_hydrated_result_set_artifact(result_set_row))
                    existing_artifact_keys.add(artifact_key)

                if str(result_set_row.result_set_id) not in existing_result_set_ids:
                    hydrated_result_refs.append(_build_hydrated_result_set_ref(result_set_row))
                    existing_result_set_ids.add(str(result_set_row.result_set_id))

            if hydrated_artifacts:
                existing_artifacts.extend(hydrated_artifacts)
                _write_json_file(runtime_artifacts_file, existing_artifacts)

            if hydrated_result_refs:
                existing_result_index.extend(hydrated_result_refs)
                _write_json_file(result_index_file, existing_result_index)

            return len(hydrated_result_refs)
        except Exception as e:
            logger.error(f"Failed to hydrate session result-set context for run {run_id}: {e}", exc_info=True)
            return 0

    async def get_compacted_conversation_context_for_run(
        self,
        *,
        tenant_id: str,
        run_id: str,
        keep_recent_turns: int = _DEFAULT_COMPACT_KEEP_RECENT_TURNS,
        max_summary_turns: int = _DEFAULT_COMPACT_SUMMARY_TURNS,
    ) -> Dict[str, Any]:
        """Load structured conversation context without replaying raw LLM transcript history."""
        try:
            async with self.get_session() as session:
                turn_stmt = select(ConversationTurn).where(
                    and_(
                        ConversationTurn.tenant_id == tenant_id,
                        ConversationTurn.run_id == run_id,
                    )
                )
                turn_result = await session.execute(turn_stmt)
                conversation_turn = turn_result.scalar_one_or_none()
                if not conversation_turn:
                    return {
                        "message_history": [],
                        "session_summary": None,
                        "recent_turn_summaries": [],
                        "compaction_applied": False,
                        "trimmed_turn_count": 0,
                    }

                session_stmt = select(ConversationSession).where(
                    and_(
                        ConversationSession.tenant_id == tenant_id,
                        ConversationSession.session_id == conversation_turn.session_id,
                    )
                )
                session_result = await session.execute(session_stmt)
                conversation_session = session_result.scalar_one_or_none()

                turns_stmt = (
                    select(ConversationTurn)
                    .where(
                        and_(
                            ConversationTurn.tenant_id == tenant_id,
                            ConversationTurn.session_id == conversation_turn.session_id,
                            ConversationTurn.turn_number <= conversation_turn.turn_number,
                        )
                    )
                    .order_by(ConversationTurn.turn_number.asc())
                )
                turns_result = await session.execute(turns_stmt)
                session_turns = list(turns_result.scalars().all())

                keep_recent_count = max(0, keep_recent_turns)
                recent_turns = session_turns[-keep_recent_count:] if keep_recent_count else []
                older_turns = session_turns[:-keep_recent_count] if keep_recent_count else session_turns

                compacted_session_summary = _build_session_compaction_summary(
                    conversation_session.summary if conversation_session else None,
                    older_turns,
                    max_summary_turns=max_summary_turns,
                )
                if conversation_session and conversation_session.summary != compacted_session_summary:
                    conversation_session.summary = compacted_session_summary
                    conversation_session.updated_at = datetime.now(timezone.utc)
                    await session.commit()

                return {
                    "message_history": [],
                    "session_summary": compacted_session_summary,
                    "recent_turn_summaries": [
                        _serialize_recent_turn_summary(turn)
                        for turn in recent_turns
                    ],
                    "compaction_applied": bool(older_turns),
                    "trimmed_turn_count": len(older_turns),
                }
        except Exception as e:
            logger.error(f"Failed to load compacted conversation context for run {run_id}: {e}", exc_info=True)
            return {
                "message_history": [],
                "session_summary": None,
                "recent_turn_summaries": [],
                "compaction_applied": False,
                "trimmed_turn_count": 0,
            }

    async def get_slack_query_history(
        self,
        slack_user_id: str,
        limit: int = 5,
        favorites_only: bool = False,
    ) -> List[QueryHistory]:
        """Get recent query history for a Slack user."""
        try:
            async with self.get_session() as session:
                db_user_id = f"slack:{slack_user_id}"
                conditions = [
                    QueryHistory.tenant_id == settings.tenant_id,
                    QueryHistory.user_id == db_user_id,
                ]
                if favorites_only:
                    conditions.append(QueryHistory.is_favorite == True)
                stmt = (
                    select(QueryHistory)
                    .where(and_(*conditions))
                    .order_by(desc(QueryHistory.last_run_at))
                    .limit(limit)
                )
                result = await session.execute(stmt)
                return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Failed to get Slack query history for {slack_user_id}: {e}")
            return []

    async def get_slack_history_item(
        self,
        history_id: int,
        slack_user_id: str,
    ) -> Optional[QueryHistory]:
        """Fetch a single history item owned by a Slack user."""
        try:
            async with self.get_session() as session:
                db_user_id = f"slack:{slack_user_id}"
                stmt = select(QueryHistory).where(
                    and_(
                        QueryHistory.id == history_id,
                        QueryHistory.tenant_id == settings.tenant_id,
                        QueryHistory.user_id == db_user_id,
                    )
                )
                result = await session.execute(stmt)
                return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Failed to get Slack history item {history_id}: {e}")
            return None

    async def toggle_slack_query_favorite(
        self,
        history_id: int,
        slack_user_id: str,
        is_favorite: bool,
    ) -> Optional[QueryHistory]:
        """Toggle favorite status for a history item owned by a Slack user."""
        try:
            async with self.get_session() as session:
                db_user_id = f"slack:{slack_user_id}"

                if is_favorite:
                    # Enforce max 10 favorites per user
                    count_stmt = select(func.count(QueryHistory.id)).where(
                        and_(
                            QueryHistory.tenant_id == settings.tenant_id,
                            QueryHistory.user_id == db_user_id,
                            QueryHistory.is_favorite == True,
                        )
                    )
                    count_result = await session.execute(count_stmt)
                    if (count_result.scalar() or 0) >= 10:
                        logger.warning(f"Slack user {slack_user_id} hit 10-favorite limit")
                        return None

                stmt = select(QueryHistory).where(
                    and_(
                        QueryHistory.id == history_id,
                        QueryHistory.tenant_id == settings.tenant_id,
                        QueryHistory.user_id == db_user_id,
                    )
                )
                result = await session.execute(stmt)
                item = result.scalar_one_or_none()
                if not item:
                    return None

                item.is_favorite = is_favorite
                await session.commit()
                await session.refresh(item)
                return item
        except Exception as e:
            logger.error(f"Failed to toggle favorite for history {history_id}: {e}")
            return None
