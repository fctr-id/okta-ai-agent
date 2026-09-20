"""Small durable inbox. One process owns workers; SQLite deduplicates deliveries."""
import asyncio
import json
import time
from pathlib import Path
from uuid import UUID, uuid4

import aiosqlite

from .auth import Sender


class InboxFull(Exception):
    pass


class RequestStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = asyncio.Lock()

    async def start(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Fail startup with multiple API workers rather than corrupting job ownership.
        self._lease = self.path.with_suffix(".lock").open("a+b")
        try:
            import os
            if os.name == "nt":
                import msvcrt
                self._lease.seek(0)
                if not self._lease.read(1):
                    self._lease.write(b"0")
                    self._lease.flush()
                self._lease.seek(0)
                msvcrt.locking(self._lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._lease.close()
            raise RuntimeError("Teams requires a single API worker sharing this database directory") from exc
        self.db = await aiosqlite.connect(self.path)
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.execute("""CREATE TABLE IF NOT EXISTS teams_requests (
            id TEXT PRIMARY KEY, tenant TEXT NOT NULL, user TEXT NOT NULL,
            conversation TEXT NOT NULL, activity TEXT NOT NULL, service_url TEXT NOT NULL,
            query TEXT NOT NULL, timezone TEXT, command INTEGER NOT NULL,
            status TEXT NOT NULL, created REAL NOT NULL, delivery TEXT,
            UNIQUE(tenant, conversation, activity))""")
        columns = {row[1] for row in await (await self.db.execute("PRAGMA table_info(teams_requests)")).fetchall()}
        for column in ("action", "reference", "payload", "session_id"):
            if column not in columns:
                await self.db.execute(f"ALTER TABLE teams_requests ADD COLUMN {column} TEXT")
        await self.db.execute("""CREATE TABLE IF NOT EXISTS teams_conversations (
            tenant TEXT NOT NULL, user TEXT NOT NULL, conversation TEXT NOT NULL,
            session_id TEXT NOT NULL, updated REAL NOT NULL,
            PRIMARY KEY (tenant, user, conversation))""")
        await self.db.execute("""CREATE TABLE IF NOT EXISTS teams_downloads (
            id TEXT PRIMARY KEY, tenant TEXT NOT NULL, user TEXT NOT NULL,
            conversation TEXT NOT NULL, reference TEXT NOT NULL, created REAL NOT NULL,
            status TEXT NOT NULL)""")
        # A previous process may have executed side effects. Never automatically replay it.
        await self.db.execute("UPDATE teams_requests SET status='interrupted', payload=NULL WHERE status='running'")
        await self.db.commit()

    async def enqueue(self, sender: Sender, query: str, timezone: str | None, *, action=None, reference=None, payload=None) -> str:
        command = action in {"download", "file_accept", "file_decline"} or (not action and query.lower() in {"help", "status", "cancel"})
        async with self.lock:
            existing = await (await self.db.execute(
                "SELECT id FROM teams_requests WHERE tenant=? AND conversation=? AND activity=?",
                (sender.tenant, sender.conversation, sender.activity),
            )).fetchone()
            if existing:
                return existing["id"]
            active = await (await self.db.execute(
                "SELECT user, command FROM teams_requests WHERE status IN ('queued', 'running')"
            )).fetchall()
            if len(active) >= 20 or sum(r["command"] == int(command) for r in active) >= (4 if command else 16):
                raise InboxFull("Teams request queue is full")
            if any(r["user"] == sender.user and r["command"] == int(command) for r in active):
                raise InboxFull("A request of this kind is already active for this user")
            job_id = str(uuid4())
            await self.db.execute(
                """INSERT INTO teams_requests
                (id, tenant, user, conversation, activity, service_url, query, timezone, command, status, created, action, reference, payload, session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)""",
                (job_id, sender.tenant, sender.user, sender.conversation, sender.activity,
                 sender.service_url, query, timezone, int(command), time.time(), action, reference,
                 json.dumps(payload) if payload else None, reference.split(":")[0] if reference and ":" in reference else None),
            )
            await self.db.commit()
            return job_id

    async def claim(self, *, command: bool) -> dict | None:
        async with self.lock:
            await self.db.execute("DELETE FROM teams_requests WHERE created < ? AND status NOT IN ('queued','running')", (time.time() - 86400,))
            await self.db.execute("UPDATE teams_requests SET status='expired', payload=NULL WHERE status='queued' AND created < ?", (time.time() - 900,))
            await self.db.execute("DELETE FROM teams_downloads WHERE created < ?", (time.time() - 3600,))
            row = await (await self.db.execute(
                "SELECT * FROM teams_requests WHERE status='queued' AND command=? ORDER BY created LIMIT 1",
                (int(command),),
            )).fetchone()
            if row:
                await self.db.execute("UPDATE teams_requests SET status='running' WHERE id=?", (row["id"],))
            await self.db.commit()
            return dict(row) if row else None

    async def finish(self, job_id: str, status: str, delivery: str | None = None):
        async with self.lock:
            await self.db.execute("UPDATE teams_requests SET status=?, delivery=?, payload=NULL WHERE id=?", (status, delivery, job_id))
            await self.db.commit()

    async def active_run_ids(self) -> set[str]:
        async with self.lock:
            rows = await (await self.db.execute(
                "SELECT id FROM teams_requests WHERE status IN ('queued','running')"
            )).fetchall()
            return {row["id"] for row in rows}

    async def bind_session(self, job: dict, retention_hours: int, *, reset=False):
        async with self.lock:
            key = (job["tenant"], job["user"], job["conversation"])
            row = await (await self.db.execute(
                "SELECT session_id, updated FROM teams_conversations WHERE tenant=? AND user=? AND conversation=?", key,
            )).fetchone()
            session_id = row["session_id"] if row and not reset and row["updated"] >= time.time() - retention_hours * 3600 else UUID(job["id"]).hex
            await self.db.execute("INSERT OR REPLACE INTO teams_conversations VALUES (?, ?, ?, ?, ?)", (*key, session_id, time.time()))
            await self.db.execute("UPDATE teams_requests SET session_id=? WHERE id=?", (session_id, job["id"]))
            await self.db.commit()
            job["session_id"] = session_id
            return session_id

    async def touch_session(self, job: dict):
        async with self.lock:
            await self.db.execute("UPDATE teams_conversations SET updated=? WHERE tenant=? AND user=? AND conversation=? AND session_id=?",
                                  (time.time(), job["tenant"], job["user"], job["conversation"], job.get("session_id")))
            await self.db.commit()

    async def create_download(self, job: dict, reference: str):
        token = str(uuid4())
        async with self.lock:
            await self.db.execute("INSERT INTO teams_downloads VALUES (?, ?, ?, ?, ?, ?, 'pending')",
                                  (token, job["tenant"], job["user"], job["conversation"], reference, time.time()))
            await self.db.commit()
        return token

    async def consume_download(self, job: dict):
        """Single-use consent bound to the authenticated user and personal chat."""
        async with self.lock:
            row = await (await self.db.execute(
                "SELECT reference FROM teams_downloads WHERE id=? AND tenant=? AND user=? AND conversation=? AND status='pending' AND created>=?",
                (job["reference"], job["tenant"], job["user"], job["conversation"], time.time() - 3600),
            )).fetchone()
            if row:
                await self.db.execute("UPDATE teams_downloads SET status='consumed' WHERE id=?", (job["reference"],))
                await self.db.execute("UPDATE teams_requests SET session_id=? WHERE id=?", (row["reference"].split(":")[0], job["id"]))
                await self.db.commit()
                job["session_id"] = row["reference"].split(":")[0]
                return row["reference"]
            return None

    async def cancel_queued(self, tenant: str, user: str) -> int:
        async with self.lock:
            result = await self.db.execute(
                "UPDATE teams_requests SET status='cancelled' WHERE tenant=? AND user=? AND command=0 AND status='queued'",
                (tenant, user),
            )
            await self.db.commit()
            return result.rowcount

    async def close(self):
        await self.db.close()
        self._lease.close()
