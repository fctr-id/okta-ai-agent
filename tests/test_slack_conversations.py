import asyncio
from datetime import datetime, timezone
import functools
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.okta.sync.models import Base, ConversationSession, ConversationTurn, ConversationResultSet
from src.core.okta.sync.operations import DatabaseOperations, _build_async_engine
from src.data.schemas.runtime_storage import create_runtime_turn_paths, update_turn_metadata, write_turn_summary
from src.integrations.slack import sessions
from src.integrations.slack.interactions import register_conversation_handlers, result_actions


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.engine = _build_async_engine(f"sqlite+aiosqlite:///{self.root / 'test.db'}")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.db = object.__new__(DatabaseOperations)
        self.db.engine = self.engine
        self.db.SessionLocal = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db.init_db = AsyncMock()
        self.patches = [
            patch.object(sessions, "DatabaseOperations", return_value=self.db),
            patch.object(sessions, "RUNTIME_ROOT", self.root),
            patch.object(sessions, "create_runtime_turn_paths", functools.partial(create_runtime_turn_paths, root=self.root)),
            patch.object(sessions, "_lock", asyncio.Lock()),
            patch.object(sessions, "_active_threads", set()),
            patch.object(sessions, "_active_folders", set()),
        ]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        for p in reversed(self.patches):
            p.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    async def turn(self, thread="100.001", user="U123", channel="C123"):
        paths = await sessions.begin_turn(user, channel, thread, str(uuid4()), "List fixtures")
        update_turn_metadata(paths, channel_id=channel, thread_ts=thread, status="completed")
        write_turn_summary(paths, {"status": "completed", "user_query": "List fixtures",
                                  "final_response_summary": "Returned two fixtures", "result_count": 2})
        sessions.save_result(paths, {"display_type": "table", "results": [{"email": "one@example.test"}, {"email": "two@example.test"}],
                                    "headers": [{"text": "Email", "value": "email"}], "count": 2})
        self.assertTrue(await self.db.mirror_runtime_turn_state(tenant_id=sessions.settings.tenant_id, run_id=paths.run_id, runtime_paths=paths))
        return paths

    async def test_followup_hydrates_prior_results_and_new_thread_is_isolated(self):
        first = await self.turn()
        second = await sessions.begin_turn("U123", "C123", "100.001", str(uuid4()), "Only the second one")
        self.assertEqual(second.turn_number, 2)
        self.assertEqual(first.session_id, second.session_id)
        hydrated = await self.db.hydrate_session_result_set_context_for_run(
            tenant_id=sessions.settings.tenant_id, run_id=second.run_id, artifacts_file=second.artifacts_file)
        self.assertGreater(hydrated, 0)
        context = await self.db.get_compacted_conversation_context_for_run(tenant_id=sessions.settings.tenant_id, run_id=second.run_id)
        self.assertIn("Returned two fixtures", json.dumps(context, default=str))
        for user, channel, thread in [("U123", "C123", "200.001"), ("U456", "C123", "100.001"), ("U123", "C456", "100.001")]:
            fresh = await sessions.begin_turn(user, channel, thread, str(uuid4()), "new")
            self.assertNotEqual(first.session_id, fresh.session_id)
            self.assertEqual(await self.db.hydrate_session_result_set_context_for_run(
                tenant_id=sessions.settings.tenant_id, run_id=fresh.run_id, artifacts_file=fresh.artifacts_file), 0)

    async def test_buttons_are_bound_to_owner_and_channel_and_survive_reload(self):
        first = await self.turn()
        reference = f"{first.session_id}:1"
        saved = await sessions.get_saved_turn("U123", reference, "C123")
        self.assertEqual(saved[0], first.turn_dir)
        self.assertIsNone(await sessions.get_saved_turn("U456", reference, "C123"))
        self.assertIsNone(await sessions.get_saved_turn("U123", reference, "C456"))
        self.assertIsNone(await sessions.get_saved_turn("U123", "../../elsewhere:1", "C123"))

    async def test_cleanup_expired_files_and_database_cascades_but_protects_active(self):
        paths = await self.turn()
        old = time.time() - 90000
        for p in [*paths.session_dir.rglob("*"), paths.session_dir]:
            os.utime(p, (old, old))
        async with self.db.get_session() as connection:
            row = (await connection.execute(select(ConversationSession))).scalar_one()
            row.last_activity_at = datetime.fromtimestamp(old, timezone.utc)
            await connection.commit()
        # A concurrent sweep must not delete a request using an old thread.
        async with sessions.reserve_thread("U123", "C123", "100.001") as acquired:
            self.assertTrue(acquired)
            self.assertEqual(await sessions.cleanup_once(), 0)
        self.assertEqual(await sessions.cleanup_once(), 1)
        self.assertFalse(paths.session_dir.exists())
        async with self.db.get_session() as connection:
            for model in (ConversationSession, ConversationTurn, ConversationResultSet):
                self.assertEqual((await connection.execute(select(func.count()).select_from(model))).scalar_one(), 0)
        self.assertIsNone(await sessions.get_saved_turn("U123", f"{paths.session_id}:1", "C123"))

    async def test_reservation_released_on_cancellation_and_duplicate_rejected(self):
        async with sessions.reserve_thread("U123", "C123", "100.001") as accepted:
            self.assertTrue(accepted)
            async with sessions.reserve_thread("U123", "C123", "100.001") as duplicate:
                self.assertFalse(duplicate)
        with self.assertRaises(asyncio.CancelledError):
            async with sessions.reserve_thread("U123", "C123", "100.001"):
                raise asyncio.CancelledError()
        async with sessions.reserve_thread("U123", "C123", "100.001") as accepted:
            self.assertTrue(accepted)

    async def test_slack_query_path_persists_clarification_then_resumes(self):
        from src.integrations.slack import slack_app
        from src.core.agents.orchestrator import OrchestratorResult
        client = SimpleNamespace(chat_postMessage=AsyncMock(return_value={"ts": "100.001"}), chat_update=AsyncMock())
        okta = SimpleNamespace(close_session=AsyncMock())
        clarification = OrchestratorResult()
        clarification.outcome = "clarify"
        clarification.user_message = "Which timezone should I use?"
        completed = OrchestratorResult()
        completed.success = True
        completed.outcome = "success"
        completed.completed_result = {"display_type": "table", "results": [{"email": "fixture@example.test"}], "headers": ["email"], "count": 1}
        context_seen = []

        async def orchestrate(**kwargs):
            context_seen.append(await self.db.get_compacted_conversation_context_for_run(
                tenant_id=sessions.settings.tenant_id, run_id=kwargs["correlation_id"]))
            return clarification if len(context_seen) == 1 else completed

        with patch.object(slack_app, "DatabaseOperations", return_value=self.db), \
             patch.object(slack_app, "OktaClient", return_value=okta), \
             patch.object(slack_app, "check_database_health", return_value=True), \
             patch.object(slack_app, "execute_multi_agent_query", side_effect=orchestrate), \
             patch.object(slack_app, "_save_history", AsyncMock()):
            await slack_app._process_query(client, "C123", "U123", "Show local dates", None)
            client.chat_postMessage.return_value = {"ts": "100.003"}
            await slack_app._process_query(client, "C123", "U123", "New York", "100.001")
        self.assertEqual(len(context_seen), 2)
        self.assertIn("Which timezone should I use?", json.dumps(context_seen[1], default=str))
        self.assertEqual(okta.close_session.await_count, 2)
        final_blocks = [call.kwargs["blocks"] for call in client.chat_postMessage.call_args_list if "blocks" in call.kwargs]
        self.assertTrue(any(b.get("type") == "actions" for b in final_blocks[-1]))
        self.assertNotIn("Query failed", str(client.chat_update.call_args_list))

    async def test_hourly_task_runs_at_startup_and_can_be_cancelled(self):
        reached = asyncio.Event()

        async def sleep(seconds):
            self.assertEqual(seconds, 3600)
            reached.set()
            await asyncio.Future()

        with patch.object(sessions, "cleanup_once", AsyncMock(return_value=0)) as cleanup, \
             patch.object(sessions.asyncio, "sleep", side_effect=sleep):
            task = asyncio.create_task(sessions.cleanup_sessions())
            await asyncio.wait_for(reached.wait(), timeout=2)
            cleanup.assert_awaited_once()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task


class FakeApp:
    def __init__(self):
        self.handlers = {}
    def register(self, name):
        def decorator(fn):
            self.handlers[name] = fn
            return fn
        return decorator
    event = action = view = register


class InteractionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = FakeApp()
        self.tasks = set()
        self.access = AsyncMock(return_value=True)
        self.query = AsyncMock()
        self.client = SimpleNamespace(chat_postEphemeral=AsyncMock(), files_upload_v2=AsyncMock(), views_open=AsyncMock())
        register_conversation_handlers(self.app, check_access=self.access, process_query=self.query, background_tasks=self.tasks)

    async def drain(self):
        if self.tasks:
            await asyncio.gather(*self.tasks)

    async def test_plain_followup_deduplicates_and_ignores_bot_edits_mentions_and_unknown_threads(self):
        event = {"user": "U123", "channel": "C123", "thread_ts": "100.001", "ts": "100.002", "text": "Only active ones"}
        handler = self.app.handlers["message"]
        with patch.object(sessions, "has_thread", return_value=True):
            await handler(event, self.client, {"bot_user_id": "B123"})
            await handler(event, self.client, {"bot_user_id": "B123"})
            await handler({**event, "bot_id": "B123"}, self.client, {})
            await handler({**event, "subtype": "message_changed"}, self.client, {})
            await handler({**event, "text": "<@B123> question"}, self.client, {"bot_user_id": "B123"})
        with patch.object(sessions, "has_thread", return_value=False):
            await handler({**event, "ts": "100.003"}, self.client, {})
        await self.drain()
        self.query.assert_awaited_once()
        self.assertEqual(self.query.call_args.kwargs["thread_ts"], "100.001")

    async def test_new_query_modal_submission_starts_new_thread(self):
        body = {"user": {"id": "U123"}, "channel": {"id": "C123"}, "trigger_id": "trigger"}
        saved = (Path("unused"), {"channel_id": "C123", "thread_ts": "100.001"})
        with patch.object(sessions, "get_saved_turn", AsyncMock(return_value=saved)):
            await self.app.handlers["tako_new_query"](AsyncMock(), {"value": "ref"}, self.client, body)
            self.client.views_open.assert_awaited_once()
            # Slack rejects the entire modal if its input limit exceeds 3000.
            modal = self.client.views_open.call_args.kwargs["view"]
            self.assertLessEqual(modal["blocks"][0]["element"]["max_length"], 3000)
            await self.app.handlers["tako_new_query_submit"](AsyncMock(), body, {
                "private_metadata": "ref", "state": {"values": {"question": {"text": {"value": "New question"}}}}}, self.client)
            await self.drain()
        self.assertIsNone(self.query.call_args.kwargs["thread_ts"])

    async def test_download_uses_saved_rows_and_never_runs_query(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "results").mkdir()
            (path / "results" / "slack_response.json").write_text(json.dumps({"results": [{"email": "one@example.test"}], "headers": ["email"]}))
            body = {"user": {"id": "U123"}, "channel": {"id": "C123"}}
            with patch.object(sessions, "get_saved_turn", AsyncMock(return_value=(path, {"thread_ts": "100.001"}))):
                await self.app.handlers["tako_download_csv"](AsyncMock(), {"value": "ref"}, self.client, body)
                await self.drain()
            self.client.files_upload_v2.assert_awaited_once()
            self.assertIn("one@example.test", self.client.files_upload_v2.call_args.kwargs["content"])
            self.query.assert_not_awaited()

    async def test_access_denied_and_expired_download_do_not_upload(self):
        body = {"user": {"id": "U123"}, "channel": {"id": "C123"}}
        self.access.return_value = False
        await self.app.handlers["tako_download_csv"](AsyncMock(), {"value": "ref"}, self.client, body)
        await self.drain()
        self.access.return_value = True
        with patch.object(sessions, "get_saved_turn", AsyncMock(return_value=None)):
            await self.app.handlers["tako_download_csv"](AsyncMock(), {"value": "ref"}, self.client, body)
            await self.drain()
        self.client.files_upload_v2.assert_not_awaited()
        self.assertEqual(self.client.chat_postEphemeral.await_count, 2)

    def test_buttons_match_available_data(self):
        self.assertEqual(len(result_actions("ref", has_csv=True)[0]["elements"]), 2)
        self.assertEqual(len(result_actions("ref", has_csv=False)[0]["elements"]), 1)


if __name__ == "__main__":
    unittest.main()
