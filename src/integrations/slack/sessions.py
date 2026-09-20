"""Slack thread identity, saved results, and local conversation retention."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select

from src.config.settings import settings
from src.core.okta.sync.models import ConversationSession
from src.core.okta.sync.operations import DatabaseOperations
from src.data.schemas.runtime_storage import RUNTIME_ROOT, create_runtime_turn_paths
from src.integrations.session_retention import remove_expired_sessions
from src.utils.logging import get_logger

logger = get_logger("slack_sessions")
_GUID = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
# Legacy folders used Slack timestamps; new ones use scoped conversation UUIDs.
SESSION_PATTERN = re.compile(rf"slack-[UW][A-Z0-9]+-(?:[0-9]+\.[0-9]+|{_GUID})\Z")
_lock = asyncio.Lock()
_active_threads: set[tuple] = set()
_active_folders: set[str] = set()


def session_identity(user_id: str, channel_id: str, thread_ts: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"tako/slack/{settings.tenant_id}/{channel_id}/{user_id}/{thread_ts}"))


@asynccontextmanager
async def reserve_thread(user_id, channel_id, thread_ts):
    """Prevent overlapping turns and cleanup while a thread is in use."""
    key = (user_id, channel_id, thread_ts)
    folder = f"slack-{user_id}-{session_identity(*key)}"
    async with _lock:
        accepted = key not in _active_threads
        if accepted:
            _active_threads.add(key)
            _active_folders.add(folder)
    try:
        yield accepted
    finally:
        if accepted:
            async with _lock:
                _active_threads.discard(key)
                _active_folders.discard(folder)


async def begin_turn(user_id, channel_id, thread_ts, run_id, query):
    db = DatabaseOperations()
    await db.init_db()
    session_id = session_identity(user_id, channel_id, thread_ts)
    owner = f"slack-{user_id}"
    conversation = await db.create_conversation_session(
        tenant_id=settings.tenant_id, user_id=owner, session_id=session_id,
        source="slack", title=query[:120], schedule_retention=False,
    )
    if conversation is None:
        raise RuntimeError("Slack conversation could not be created")
    turn = await db.create_conversation_turn(
        tenant_id=settings.tenant_id, user_id=owner, session_id=session_id,
        run_id=run_id, query_text=query, source="slack", status="executing",
        started_at=datetime.now(timezone.utc),
    )
    if turn is None:
        raise RuntimeError("Slack turn could not be created")
    return create_runtime_turn_paths(
        user_id=owner, session_id=session_id, run_id=run_id, turn_number=turn.turn_number,
    )


def has_thread(user_id, channel_id, thread_ts):
    folder = RUNTIME_ROOT / "sessions" / f"slack-{user_id}-{session_identity(user_id, channel_id, thread_ts)}"
    return folder.is_dir()


def save_result(paths, event_data):
    from src.integrations.conversation_results import save_result as persist
    persist(paths, event_data, filename="slack_response.json")


async def get_saved_turn(user_id, reference, channel_id=None):
    """Resolve an opaque button reference through user ownership, never a supplied path."""
    try:
        session_id, turn_number = reference.split(":")
        session_id = str(UUID(session_id))
        turn_number = int(turn_number)
    except (ValueError, AttributeError):
        return None
    turn = await DatabaseOperations().get_conversation_turn(
        tenant_id=settings.tenant_id, user_id=f"slack-{user_id}",
        session_id=session_id, turn_number=turn_number,
    )
    if turn is None:
        return None
    root = RUNTIME_ROOT.resolve() / "sessions"
    folder = root / f"slack-{user_id}-{session_id}"
    path = folder / "turns" / f"{turn_number:04d}-{turn.run_id}"
    try:
        if path.resolve().is_relative_to(folder) and folder.resolve().parent == root:
            metadata = json.loads((path / "turn_metadata.json").read_text(encoding="utf-8"))
            stored_channel = metadata.get("channel_id")
            stored_thread = metadata.get("thread_ts")
            if not stored_channel or not stored_thread:
                return None
            if channel_id is not None and stored_channel != channel_id:
                return None
            if session_identity(user_id, stored_channel, stored_thread) != session_id:
                return None
            # A stopped cleanup loop must not make expired downloads available forever.
            if time.time() - folder.stat().st_mtime > settings.SLACK_SESSION_RETENTION_HOURS * 3600:
                latest = max(p.stat().st_mtime for p in folder.rglob("*") if p.is_file())
                if time.time() - latest > settings.SLACK_SESSION_RETENTION_HOURS * 3600:
                    return None
            return path, metadata
    except (OSError, ValueError):
        pass
    return None


async def cleanup_once():
    cutoff = time.time() - settings.SLACK_SESSION_RETENTION_HOURS * 3600
    db = DatabaseOperations()
    async with _lock:
        removed = await asyncio.to_thread(
            remove_expired_sessions, RUNTIME_ROOT, cutoff=cutoff, active_run_ids=set(),
            session_pattern=SESSION_PATTERN, protected_sessions=set(_active_folders),
        )
        # Delete associated conversation rows only after their local folder is gone.
        # Database foreign-key cascades remove turns, refs, and lineage; query history stays.
        async with db.get_session() as connection:
            rows = await connection.execute(select(ConversationSession).where(
                ConversationSession.tenant_id == settings.tenant_id,
                ConversationSession.source == "slack",
                ConversationSession.last_activity_at < datetime.fromtimestamp(cutoff, timezone.utc),
            ))
            for row in rows.scalars():
                name = f"{row.user_id}-{row.session_id}"
                if name in _active_folders or not SESSION_PATTERN.fullmatch(name):
                    continue
                folder = RUNTIME_ROOT / "sessions" / name
                if not folder.exists() and not folder.is_symlink():
                    await connection.delete(row)
            await connection.commit()
    return removed


async def cleanup_sessions():
    while True:
        try:
            await DatabaseOperations().init_db()
            removed = await cleanup_once()
            if removed:
                logger.info("Slack cleanup removed %s expired session folders", removed)
        except Exception:
            logger.exception("Slack session cleanup failed; will retry next hour")
        await asyncio.sleep(3600)
