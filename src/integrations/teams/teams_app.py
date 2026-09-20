"""Microsoft SDK authentication/send layer and Tako's bounded request workers."""
import asyncio
import json
import time
from pathlib import Path
from uuid import UUID

import httpx
from fastapi import FastAPI
from microsoft_teams.api import MessageActivityInput, InvokeResponse, TypingActivityInput
from microsoft_teams.api.auth.cloud_environment import PUBLIC
from microsoft_teams.apps import App
from microsoft_teams.apps.http import FastAPIAdapter
from microsoft_teams.cards import AdaptiveCard
from microsoft_teams.common.http import ClientOptions
from src.utils.logging import get_logger

from .auth import AccessUnavailable, GroupAuthorizer, authenticated_sender
from .config import TeamsConfig
from .diagnostics import failure_details
from .formatters import HELP, result_card
from .message_text import clean_message_text
from .runtime import run_query, sync_status
from .retention import remove_expired_sessions
from .store import InboxFull, RequestStore
from . import files, sessions

logger = get_logger(__name__)


class TeamsBot:
    def __init__(self, config: TeamsConfig, db_dir: Path, *, authorizer=None, runner=run_query):
        self.config = config
        self.http_app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
        self.sdk = App(
            client_id=config.client_id, client_secret=config.client_secret.get_secret_value(),
            tenant_id=config.tenant_id, messaging_endpoint="/messages",
            http_server_adapter=FastAPIAdapter(app=self.http_app),
            dangerously_allow_unauthenticated_requests=False,
            cloud=PUBLIC, service_url="https://smba.trafficmanager.net/teams",
            client=ClientOptions(timeout=15),
        )
        self.authorizer = authorizer
        self.store = RequestStore(db_dir / "teams_requests.db")
        self.runner = runner
        self.tasks = []
        self.running = {}
        self.closing = False

    async def start(self):
        await self.store.start()
        try:
            if self.authorizer is None:
                self.authorizer = GroupAuthorizer(self.config)
            await self.sdk.initialize()
            # Public SDK hook: the SDK verifies JWTs before invoking this callback.
            # No alternate raw HTTP route, unsigned claim decoding or anonymous mode.
            self.sdk.server.on_request = self.receive
            self.tasks = [asyncio.create_task(self.worker(command=False)) for _ in range(2)]
            self.tasks.append(asyncio.create_task(self.worker(command=True)))
            self.tasks.append(asyncio.create_task(self.cleanup_sessions()))
        except BaseException:
            await self.sdk.http_client.http.aclose()
            await self.sdk.api.http.http.aclose()
            if self.authorizer:
                await self.authorizer.close()
            await self.store.close()
            raise

    async def cleanup_sessions(self):
        from src.data.schemas.runtime_storage import RUNTIME_ROOT

        # Run immediately on startup, then even while the bot is otherwise idle.
        while not self.closing:
            try:
                # Serialize session binding with the sweep so an old thread cannot
                # become active between taking the protection snapshot and deleting.
                async with self.store.lock:
                    rows = await (await self.store.db.execute("""SELECT r.*, c.session_id AS current_session
                        FROM teams_requests r LEFT JOIN teams_conversations c
                        ON r.tenant=c.tenant AND r.user=c.user AND r.conversation=c.conversation
                        WHERE r.status IN ('queued','running')""")).fetchall()
                    protected = {f"{sessions.owner_id(row)}-{sid}" for row in rows
                                 for sid in (row["session_id"], row["current_session"]) if sid}
                    cutoff = time.time() - self.config.session_retention_hours * 3600
                    removed = await asyncio.to_thread(
                        remove_expired_sessions, RUNTIME_ROOT, cutoff=cutoff,
                        active_run_ids={row["id"] for row in rows}, protected_sessions=protected,
                    )
                    await sessions.purge_missing_session_records(cutoff, protected)
                    await self.store.db.execute("""DELETE FROM teams_conversations WHERE updated < ? AND NOT EXISTS (
                        SELECT 1 FROM teams_requests r WHERE r.tenant=teams_conversations.tenant
                        AND r.user=teams_conversations.user AND r.conversation=teams_conversations.conversation
                        AND r.status IN ('queued','running'))""", (cutoff,))
                    await self.store.db.commit()
                if removed:
                    logger.info("Teams session cleanup removed %s expired folders", removed)
            except Exception as exc:
                logger.warning("Teams session cleanup failed: %s", failure_details(exc))
            await asyncio.sleep(3600)

    async def receive(self, event):
        body = event.body.model_dump(by_alias=True, exclude_none=True)
        attachments = body.get("attachments") or []
        # Teams includes an HTML rendering of ordinary text as an attachment.
        # Use only Activity.text; never render/fetch attachment content or URLs.
        html_count = sum(
            isinstance(item, dict) and item.get("contentType") == "text/html"
            for item in attachments
        )

        def reject(status, reason):
            # Log shape and a fixed reason, never message/attachment contents or tokens.
            logger.warning(
                "Teams incoming rejected: status=%s reason=%s text_chars=%s "
                "attachments=%s html_attachments=%s has_value=%s",
                status, reason, len(body.get("text") or ""),
                len(attachments), html_count, bool(body.get("value")),
            )
            return InvokeResponse(status=status)

        try:
            if getattr(event.token, "audience", None) != self.config.client_id:
                return reject(403, "invalid_audience")
            if not getattr(event.token, "expiration", None) or event.token.is_expired(buffer_ms=0):
                return reject(403, "expired_token")
            sender = authenticated_sender(body, getattr(event.token, "issuer", None), self.config)
        except (ValueError, TypeError, AttributeError):
            return reject(403, "invalid_sender_envelope")
        action = reference = payload = None
        if body.get("type") == "invoke" and body.get("name") == "fileConsent/invoke":
            try:
                value = body.get("value") or {}
                if value.get("type") != "fileUpload" or value.get("action") not in {"accept", "decline"}:
                    raise ValueError("Invalid file consent")
                reference = str(UUID(value["context"]["download_id"]))
                action = "file_" + value["action"]
                payload = files.validate_upload_info(value.get("uploadInfo")) if action == "file_accept" else None
            except (ValueError, KeyError, TypeError, AttributeError):
                return reject(400, "invalid_file_consent")
        elif body.get("type") != "message":
            # Unsupported actions must not fall through to an LLM request.
            if body.get("type") == "invoke":
                return reject(400, "unsupported_invoke")
            return InvokeResponse(status=200)
        elif body.get("value"):
            try:
                value = body["value"]
                action = value.get("tako_action")
                if action not in {"new_query", "download"}:
                    return reject(400, "unsupported_card_action")
                if action == "download":
                    sid, number = value["reference"].split(":")
                    if not 0 < int(number) < 1000000:
                        raise ValueError("Invalid turn")
                    reference = f"{UUID(sid).hex}:{int(number)}"
            except (ValueError, KeyError, TypeError, AttributeError):
                return reject(400, "invalid_card_action")
        if len(attachments) != html_count:
            return reject(400, "unsupported_attachment")
        try:
            query = action.replace("_", " ").title() if action else clean_message_text(body.get("text") or "")
        except ValueError as exc:
            return reject(400, str(exc))
        timezone = None
        # The hint is optional; unknown Windows zones are not guessed or treated as UTC.
        for entity in body.get("entities") or []:
            if entity.get("type") == "clientInfo" and entity.get("timezone"):
                from src.utils.timezone_context import normalize_user_timezone
                try:
                    timezone = normalize_user_timezone(entity["timezone"])
                except (ValueError, TypeError, AttributeError):
                    pass
        try:
            job_id = await self.store.enqueue(sender, query, timezone, action=action, reference=reference, payload=payload)
        except InboxFull:
            return reject(429, "inbox_full")
        logger.info("Teams incoming accepted: job=%s text_chars=%s html_attachments=%s", job_id, len(query), html_count)
        return InvokeResponse(status=200)

    async def send(self, job: dict, response: dict, *, activity_id=None):
        card = AdaptiveCard.model_validate(result_card(job["query"], response))
        # Text plus a card is split by Teams, invalidating the returned update ID.
        activity = MessageActivityInput(id=activity_id).add_card(card)
        for attempt in range(3):
            try:
                return await self.sdk.send(job["conversation"], activity, service_url=job["service_url"])
            except httpx.HTTPStatusError as exc:
                # Retry only explicit throttling. An uncertain send must not rerun the query.
                delay = exc.response.headers.get("Retry-After", "2")
                if exc.response.status_code != 429 or attempt == 2 or not delay.isdigit() or int(delay) > 15:
                    raise
                await asyncio.sleep(max(1, int(delay)))

    async def typing_indicator(self, job: dict):
        """Best-effort native dots; failures must never interrupt the actual query."""
        while not self.closing:
            try:
                await asyncio.wait_for(self.sdk.send(
                    job["conversation"], TypingActivityInput(), service_url=job["service_url"],
                ), timeout=3)
            except Exception as exc:
                # Stop on throttling or errors instead of retrying a cosmetic signal.
                logger.warning("Teams typing indicator %s stopped: %s", job["id"], failure_details(exc))
                return
            await asyncio.sleep(4)

    async def send_final(self, job: dict, response: dict):
        # Editing the progress card may leave native typing dots visible in Teams.
        # Send a new message after typing stops, then remove our temporary card.
        sent = await self.send(job, response)
        progress_id = job.pop("progress_id", None)
        if progress_id:
            try:
                await asyncio.wait_for(self.sdk.api.conversations.delete_activity(
                    job["conversation"], progress_id, service_url=job["service_url"],
                ), timeout=5)
            except Exception as exc:
                # The result is already delivered. Never resend it for a cleanup failure.
                logger.warning("Teams progress cleanup %s failed: %s", job["id"], failure_details(exc))
        return sent

    async def process(self, job: dict):
        job["stage"] = "check_access"
        if not await self.authorizer.allowed(job["user"]):
            job["stage"] = "send_access_denied"
            await self.send(job, {"outcome": "fail", "content": "You don't have access to Tako. Contact your administrator."})
            await self.store.finish(job["id"], "denied", "sent")
            return
        command = job["query"].lower()
        action = job.get("action")
        if action in {"download", "file_accept", "file_decline"}:
            await self.handle_file(job)
            return
        if action == "new_query" or command == "new":
            await self.store.bind_session(job, self.config.session_retention_hours, reset=True)
            response = {"outcome": "new_query", "content": "Previous questions and results are no longer part of this session. Type your next question below."}
        elif command == "help":
            response = {"content": HELP}
        elif command == "status":
            job["stage"] = "read_sync_status"
            response = await sync_status()
        elif command == "cancel":
            count = await self.store.cancel_queued(job["tenant"], job["user"])
            for active, task in list(self.running.values()):
                if active["tenant"] == job["tenant"] and active["user"] == job["user"] and not active["command"]:
                    task.cancel()
                    count += 1
            response = {"content": "Your active request was cancelled." if count else "You have no active request to cancel."}
        else:
            await self.store.bind_session(job, self.config.session_retention_hours)
            # A temporary progress card; the final message replaces it after typing stops.
            job["stage"] = "send_progress"
            sent = await self.send(job, {"content": "Working on your question…", "outcome": "working"})
            job["progress_id"] = sent.id
            job["stage"] = "run_query"
            typing = asyncio.create_task(self.typing_indicator(job))
            try:
                response = await self.runner(job)
            finally:
                typing.cancel()
                await asyncio.gather(typing, return_exceptions=True)
                await self.store.touch_session(job)
        # Membership may have been revoked while the model/Okta request was running.
        job["stage"] = "recheck_access"
        if not await self.authorizer.allowed(job["user"]):
            await self.store.finish(job["id"], "denied", "withheld")
            return
        job["stage"] = "send_result"
        await self.send_final(job, response)
        await self.store.finish(job["id"], response.get("outcome", "completed"), "sent")

    async def send_attachment(self, job, attachment):
        activity = MessageActivityInput.model_validate({"type": "message", "attachments": [attachment]})
        return await self.sdk.send(job["conversation"], activity, service_url=job["service_url"])

    async def handle_file(self, job):
        job["stage"] = "prepare_download"
        reference = job.get("reference")
        if job["action"] != "download":
            reference = await self.store.consume_download(job)
            if job["action"] == "file_decline" and reference:
                await self.send(job, {"content": "CSV download cancelled."})
                await self.store.finish(job["id"], "cancelled", "sent")
                return
        path = await files.export_path(job, reference, self.config.session_retention_hours) if reference else None
        if path is None:
            await self.send(job, {"outcome": "fail", "content": "These results have expired or are unavailable. Please start a new query."})
            await self.store.finish(job["id"], "expired", "sent")
            return
        if not await self.authorizer.allowed(job["user"]):
            await self.store.finish(job["id"], "denied", "withheld")
            return
        if job["action"] == "download":
            token = await self.store.create_download(job, reference)
            await self.send_attachment(job, files.consent_attachment(token, path.stat().st_size))
        else:
            job["stage"] = "upload_csv"
            info = await files.upload_csv(path, json.loads(job["payload"]))
            job["stage"] = "send_file_card"
            await self.send_attachment(job, files.file_attachment(info))
        await self.store.finish(job["id"], "completed", "sent")

    async def worker(self, *, command: bool):
        while not self.closing:
            job = await self.store.claim(command=command)
            if job is None:
                await asyncio.sleep(0.25)
                continue
            task = asyncio.create_task(self.process(job))
            self.running[job["id"]] = (job, task)
            try:
                await asyncio.wait_for(task, timeout=max(1, job["created"] + 900 - time.time()))
            except asyncio.CancelledError:
                await self.store.finish(job["id"], "interrupted" if self.closing else "cancelled")
                if self.closing:
                    raise
                await self.report_failure(job, "The request was cancelled.", outcome="cancelled")
            except Exception as exc:
                # Do not log Graph/bot credentials, full activities or response payloads.
                logger.error("Teams request %s failed: stage=%s %s", job["id"], job.get("stage", "unknown"), failure_details(exc))
                await self.store.finish(job["id"], "failed", "failed_or_unknown")
                if isinstance(exc, httpx.HTTPError) and job.get("stage") != "upload_csv":
                    # Delivery outcome is uncertain; do not blindly send a duplicate.
                    continue
                message = ("The CSV could not be saved to OneDrive. Select Download CSV again to try a new upload." if job.get("stage") == "upload_csv"
                           else "I couldn't verify access right now. Please try again later." if isinstance(exc, AccessUnavailable)
                           else "This request took too long. Please narrow your question and try again." if isinstance(exc, TimeoutError)
                           else "I couldn't complete this request. Please try again. Your administrator can check the server log.")
                await self.report_failure(job, message)
            finally:
                self.running.pop(job["id"], None)

    async def report_failure(self, job, message, *, outcome="fail"):
        try:
            # Error cards contain no query data beyond the sender's own question.
            await self.send_final(job, {"content": message, "outcome": outcome})
        except Exception as exc:
            logger.error("Teams error notification %s failed: %s", job["id"], failure_details(exc))

    async def close(self):
        self.closing = True
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.sdk.stop()
        await self.sdk.http_client.http.aclose()
        await self.sdk.api.http.http.aclose()
        if self.authorizer:
            await self.authorizer.close()
        await self.store.close()
