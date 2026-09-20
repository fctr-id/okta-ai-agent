"""User-owned Teams conversations using the existing agent context database."""
from datetime import datetime, timezone
import hashlib
import base64
import json
import time
from uuid import UUID

from sqlalchemy import select

from src.config.settings import settings
from src.core.okta.sync.models import ConversationSession
from src.core.okta.sync.operations import DatabaseOperations
from src.data.schemas.runtime_storage import RUNTIME_ROOT


def owner_id(job):
    digest = hashlib.sha256(f"{job['tenant']}:{job['user']}".encode()).digest()[:12]
    # 96-bit owner key, with a fixed suffix so path sanitization cannot trim it.
    return "teams-" + base64.urlsafe_b64encode(digest).decode("ascii") + "u"


async def begin_turn(job):
    from src.data.schemas.runtime_storage import create_runtime_turn_paths
    db = DatabaseOperations()
    await db.init_db()
    owner = owner_id(job)
    session_id = UUID(job["session_id"]).hex
    session = await db.create_conversation_session(
        tenant_id=settings.tenant_id, user_id=owner, session_id=session_id,
        source="teams", title=job["query"][:120], schedule_retention=False,
    )
    if session is None:
        raise RuntimeError("Teams conversation could not be created")
    turn = await db.create_conversation_turn(
        tenant_id=settings.tenant_id, user_id=owner, session_id=session_id,
        run_id=job["id"], query_text=job["query"], source="teams", status="executing",
        started_at=datetime.now(timezone.utc),
    )
    if turn is None:
        raise RuntimeError("Teams turn could not be created")
    return create_runtime_turn_paths(user_id=owner, session_id=session_id, run_id=job["id"], turn_number=turn.turn_number)


async def saved_turn(job, reference: str, retention_hours: int):
    try:
        session_id, number = reference.split(":")
        session_id, number = UUID(session_id).hex, int(number)
    except (AttributeError, ValueError):
        return None
    turn = await DatabaseOperations().get_conversation_turn(
        tenant_id=settings.tenant_id, user_id=owner_id(job), session_id=session_id, turn_number=number,
    )
    if not turn:
        return None
    root = RUNTIME_ROOT.resolve() / "sessions"
    folder = root / f"{owner_id(job)}-{session_id}"
    path = folder / "turns" / f"{number:04d}-{turn.run_id}"
    try:
        if folder.resolve().parent != root or not path.resolve().is_relative_to(folder):
            return None
        metadata = json.loads((path / "turn_metadata.json").read_text(encoding="utf-8"))
        if metadata.get("conversation") != job["conversation"]:
            return None
        latest = max([folder.stat().st_mtime, *(p.stat().st_mtime for p in folder.rglob("*") if p.is_file())])
        if latest < time.time() - retention_hours * 3600:
            return None
        return path
    except (OSError, ValueError):
        return None


async def purge_missing_session_records(cutoff: float, protected: set[str]):
    """Purge DB context after safe filesystem cleanup, including interrupted sessions."""
    db = DatabaseOperations()
    await db.init_db()
    async with db.get_session() as connection:
        rows = await connection.execute(select(ConversationSession).where(
            ConversationSession.tenant_id == settings.tenant_id,
            ConversationSession.source == "teams",
            ConversationSession.last_activity_at < datetime.fromtimestamp(cutoff, timezone.utc),
        ))
        for row in rows.scalars():
            name = f"{row.user_id}-{row.session_id}"
            from src.integrations.session_retention import _SESSION_NAME
            if name in protected or not _SESSION_NAME.fullmatch(name):
                continue
            folder = RUNTIME_ROOT / "sessions" / name
            if not folder.exists() and not folder.is_symlink():
                await connection.delete(row)
        await connection.commit()
