"""Offline conversation, consent, and download lifecycle tests."""
import asyncio
import functools
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import httpx
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.okta.sync.models import Base, ConversationSession, ConversationTurn
from src.core.okta.sync.operations import DatabaseOperations, _build_async_engine
from src.data.schemas import runtime_storage
from src.integrations.teams import sessions, runtime, files
from src.integrations.teams.auth import Sender
from src.integrations.teams.store import RequestStore, InboxFull
from src.integrations.teams.formatters import result_card

TENANT, USER = str(uuid4()), str(uuid4())


def job(**kwargs):
    return {"id": str(uuid4()), "tenant": TENANT, "user": USER, "conversation": "chat-one",
            "service_url": "https://smba.trafficmanager.net/amer/", "query": "List fixtures",
            "session_id": uuid4().hex, "command": 0, "created": time.time(), **kwargs}


def answer(**kwargs):
    output = {"display_type": "table", "results": [{"email": "one@example.test"}], "headers": ["email"], "count": 1}
    return SimpleNamespace(success=True, outcome="success", no_data_found=False, is_special_tool=False,
                           completed_result=output, completed_result_event=lambda: output.copy(), **kwargs)


class ConversationTests(unittest.IsolatedAsyncioTestCase):
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
            patch.object(runtime, "DatabaseOperations", return_value=self.db),
            patch.object(sessions, "RUNTIME_ROOT", self.root),
            patch.object(runtime_storage, "create_runtime_turn_paths", functools.partial(runtime_storage.create_runtime_turn_paths, root=self.root)),
            patch("src.core.okta.client.OktaClient", return_value=SimpleNamespace(close_session=AsyncMock())),
        ]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        for p in reversed(self.patches):
            p.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    async def test_clarification_then_followup_sees_prior_context_and_results(self):
        first = job(query="Show local times")
        clarify = SimpleNamespace(success=False, outcome="clarify", user_message="Which timezone?")
        response = await runtime.run_query(first, orchestrate=AsyncMock(return_value=clarify))
        self.assertEqual(response["outcome"], "clarify")
        second = job(session_id=first["session_id"], query="New York")
        seen = []
        async def orchestrate(**kwargs):
            seen.append(await self.db.get_compacted_conversation_context_for_run(
                tenant_id=sessions.settings.tenant_id, run_id=kwargs["correlation_id"]))
            return answer()
        second_response = await runtime.run_query(second, orchestrate=orchestrate)
        self.assertIn("Which timezone?", json.dumps(seen[0], default=str))
        third = job(session_id=first["session_id"], query="Only the first row")
        third_paths = await sessions.begin_turn(third)
        count = await self.db.hydrate_session_result_set_context_for_run(
            tenant_id=sessions.settings.tenant_id, run_id=third["id"], artifacts_file=third_paths.artifacts_file)
        self.assertGreater(count, 0)
        self.assertEqual(third_paths.turn_number, 3)
        self.assertEqual(second_response["result_reference"], f"{first['session_id']}:2")
        fresh = await sessions.begin_turn(job(query="New question"))
        self.assertEqual(await self.db.hydrate_session_result_set_context_for_run(
            tenant_id=sessions.settings.tenant_id, run_id=fresh.run_id, artifacts_file=fresh.artifacts_file), 0)

    async def test_narrative_followup_hydrates_complete_evidence_with_bounded_preview(self):
        from src.data.schemas.artifact_manifest import append_artifacts_with_result_sets, build_artifact_prompt_context

        first = job(query="Assess the saved evidence")
        evidence = {"observations": ["fixture" * 100] * 20 + ["late evidence"], "limit": "Sample only"}
        narrative = "Assessment. " * 500

        async def orchestrate(**kwargs):
            append_artifacts_with_result_sets(kwargs["artifacts_file"], [{
                "key": "assessment_evidence", "category": "special_results", "content": json.dumps(evidence),
            }], source_specialist="special")
            result = answer()
            result.completed_result_event = lambda: {"display_type": "markdown", "content": narrative}
            return result

        await runtime.run_query(first, orchestrate=orchestrate)
        second = job(session_id=first["session_id"], query="Explain the evidence without retrieving again")
        paths = await sessions.begin_turn(second)
        count = await self.db.hydrate_session_result_set_context_for_run(
            tenant_id=sessions.settings.tenant_id, run_id=second["id"], artifacts_file=paths.artifacts_file)
        self.assertEqual(count, 1)
        refs = json.loads((paths.results_dir / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(refs[0]["entity_type"], "narrative")
        saved = json.loads(Path(refs[0]["storage_path"]).read_text(encoding="utf-8"))
        self.assertEqual(saved["data"]["answer"], narrative)
        self.assertEqual(saved["data"]["supporting_evidence"][0]["data"], evidence)
        preview = build_artifact_prompt_context(paths.artifacts_file)
        self.assertNotIn("late evidence", preview)
        self.assertLess(len(preview), 9000)
        self.assertTrue(saved["inspection"]["sample_rows"][0]["answer_truncated"])
        from pydantic_ai.models.test import TestModel
        with patch("src.core.models.model_picker.ModelConfig.get_model", return_value=TestModel()):
            from src.core.agents.result_analysis_agent import _execute_analysis_code, validate_result_analysis_code
        code = ("saved = result_sets[selected_result_set_ids[0]][0]\n"
                "analysis_result = {'summary': 'Saved evidence', "
                "'answer': saved['supporting_evidence'][0]['data']['observations'][-1]}")
        self.assertTrue(validate_result_analysis_code(code).is_valid)
        output = _execute_analysis_code(
            user_query=second["query"], python_code=code,
            selected_candidates={refs[0]["result_set_id"]: refs[0]},
            selected_result_set_ids=[refs[0]["result_set_id"]])
        self.assertEqual(output.answer, "late evidence")

    async def test_failed_and_clarifying_narratives_are_not_saved_evidence(self):
        for outcome in ("fail", "clarify", "empty"):
            with self.subTest(outcome=outcome):
                first = job()
                result = SimpleNamespace(success=outcome == "empty", outcome=outcome,
                                         no_data_found=outcome == "empty", error="fixture",
                                         user_message="Not a completed assessment")
                await runtime.run_query(first, orchestrate=AsyncMock(return_value=result))
                second = job(session_id=first["session_id"])
                paths = await sessions.begin_turn(second)
                self.assertEqual(await self.db.hydrate_session_result_set_context_for_run(
                    tenant_id=sessions.settings.tenant_id, run_id=second["id"], artifacts_file=paths.artifacts_file), 0)

    async def test_saved_download_is_scoped_and_contains_all_rows(self):
        request = job()
        rows = [{"email": f"person{i}@example.test"} for i in range(25)]
        result = answer()
        result.completed_result_event = lambda: {"display_type": "table", "results": rows, "headers": [{"value": "email", "text": "Email"}], "count": 25}
        response = await runtime.run_query(request, orchestrate=AsyncMock(return_value=result))
        reference = response["result_reference"]
        self.assertIsNone(await sessions.saved_turn({**request, "user": str(uuid4())}, reference, 24))
        self.assertIsNone(await sessions.saved_turn({**request, "tenant": str(uuid4())}, reference, 24))
        self.assertIsNone(await sessions.saved_turn({**request, "conversation": "another-chat"}, reference, 24))
        self.assertIsNone(await sessions.saved_turn(request, "../../outside:1", 24))
        path = await files.export_path(request, reference, 24)
        content = path.read_text(encoding="utf-8-sig")
        self.assertEqual(len(content.splitlines()), 26)
        self.assertIn("person24@example.test", content)
        # A new session does not change what an old result's download contains.
        self.assertEqual(await files.export_path({**request, "session_id": uuid4().hex}, reference, 24), path)

    async def test_expired_files_and_database_are_removed_together(self):
        from src.integrations.session_retention import remove_expired_sessions
        from datetime import datetime, timezone
        request = job()
        response = await runtime.run_query(request, orchestrate=AsyncMock(return_value=answer()))
        path = await sessions.saved_turn(request, response["result_reference"], 24)
        folder = path.parent.parent
        old = time.time() - 90000
        for p in [*folder.rglob("*"), folder]:
            os.utime(p, (old, old))
        async with self.db.get_session() as connection:
            row = (await connection.execute(select(ConversationSession))).scalar_one()
            row.last_activity_at = datetime.fromtimestamp(old, timezone.utc)
            await connection.commit()
        self.assertIsNone(await sessions.saved_turn(request, response["result_reference"], 24))
        cutoff = time.time() - 86400
        self.assertEqual(remove_expired_sessions(self.root, cutoff=cutoff, active_run_ids={request["id"]}), 0)
        self.assertEqual(remove_expired_sessions(self.root, cutoff=cutoff, active_run_ids=set()), 1)
        await sessions.purge_missing_session_records(cutoff, set())
        async with self.db.get_session() as connection:
            self.assertEqual((await connection.execute(select(func.count()).select_from(ConversationTurn))).scalar_one(), 0)


class StoreSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_restart_resume_reset_and_expiry(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "requests.db"
            store = RequestStore(path)
            await store.start()
            first = job()
            original = await store.bind_session(first, 24)
            await store.close()
            store = RequestStore(path)
            await store.start()
            try:
                self.assertEqual(await store.bind_session(job(), 24), original)
                reset = await store.bind_session(job(), 24, reset=True)
                self.assertNotEqual(reset, original)
                self.assertEqual(await store.bind_session(job(), 24), reset)
                await store.db.execute("UPDATE teams_conversations SET updated=?", (time.time() - 90000,))
                await store.db.commit()
                self.assertNotEqual(await store.bind_session(job(), 24), reset)
            finally:
                await store.close()

    async def test_consent_is_single_use_owned_and_clears_url_after_finish(self):
        with TemporaryDirectory() as tmp:
            store = RequestStore(Path(tmp) / "requests.db")
            await store.start()
            try:
                request = job()
                reference = f"{request['session_id']}:1"
                token = await store.create_download(request, reference)
                self.assertIsNone(await store.consume_download({**request, "user": str(uuid4()), "reference": token}))
                sender = Sender(request["tenant"], request["user"], request["conversation"], "event1", request["service_url"])
                job_id = await store.enqueue(sender, "Accept", None, action="file_accept", reference=token, payload={"uploadUrl": "sensitive-capability"})
                self.assertEqual(await store.enqueue(sender, "Accept", None, action="file_accept", reference=token), job_id)
                queued = await store.claim(command=True)
                self.assertEqual(await store.consume_download(queued), reference)
                self.assertIsNone(await store.consume_download(queued))
                await store.finish(job_id, "completed")
                row = await (await store.db.execute("SELECT payload FROM teams_requests WHERE id=?", (job_id,))).fetchone()
                self.assertIsNone(row["payload"])
            finally:
                await store.close()


class FileTests(unittest.IsolatedAsyncioTestCase):
    def test_card_and_native_attachments_validate(self):
        from microsoft_teams.cards import AdaptiveCard
        from microsoft_teams.api import MessageActivityInput
        card = result_card("query", {"display_type": "table", "results": [{"id": 1}], "result_reference": f"{uuid4()}:1"})
        AdaptiveCard.model_validate(card)
        self.assertEqual([action["title"] for action in card["actions"]], ["New Query", "Download CSV"])
        for attachment in (files.consent_attachment(str(uuid4()), 30), files.file_attachment({"contentUrl": "https://fixture.sharepoint.com/file.csv", "uniqueId": "item"})):
            MessageActivityInput.model_validate({"type": "message", "attachments": [attachment]})

    async def test_upload_uses_bounded_ranges_no_credentials_and_no_redirects(self):
        requests = []
        def respond(request):
            requests.append(request)
            self.assertNotIn("authorization", request.headers)
            return httpx.Response(202 if len(requests) == 1 else 201)
        info = {"uploadUrl": "https://example.up.1drv.com/upload?capability=fixture", "contentUrl": "https://fixture.sharepoint.com/file.csv", "uniqueId": "item"}
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "export.csv"
            path.write_bytes(b"x" * (files.CHUNK_BYTES + 7))
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                await files.upload_csv(path, info, http=client)
            self.assertEqual(len(requests), 2)
            self.assertEqual(len(requests[0].content), files.CHUNK_BYTES)
            self.assertEqual(len(requests[1].content), 7)
        for url in ("http://example.up.1drv.com/u", "https://localhost/u", "https://127.0.0.1/u", "https://x.sharepoint.com.evil.test/u", "https://user:pass@x.sharepoint.com/u"):
            with self.assertRaises(ValueError):
                files.cloud_url(url)


if __name__ == "__main__":
    unittest.main()
