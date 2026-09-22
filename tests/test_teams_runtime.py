"""Offline execution, cancellation, isolation and app package tests."""
import asyncio
import functools
import json
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4
from zipfile import ZipFile
import zlib

from src.integrations.teams import runtime
from scripts.build_teams_package import build_package


def result(**overrides):
    values = dict(outcome="success", success=True, no_data_found=False, completed_result=None,
                  is_special_tool=False, script_code=None, user_message=None, error=None)
    return SimpleNamespace(**{**values, **overrides})


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        async def begin(job):
            from src.data.schemas import runtime_storage
            job.setdefault("conversation", "fixture-conversation")
            return runtime_storage.create_runtime_turn_paths(
                user_id=runtime.sessions.owner_id(job), session_id=job.get("session_id", uuid4().hex),
                run_id=job["id"], turn_number=1,
            )
        self.begin_patch = patch.object(runtime.sessions, "begin_turn", side_effect=begin)
        self.db_patch = patch.object(runtime, "DatabaseOperations", return_value=SimpleNamespace(mirror_runtime_turn_state=AsyncMock()))
        self.begin_patch.start()
        self.db_patch.start()

    async def asyncTearDown(self):
        self.begin_patch.stop()
        self.db_patch.stop()
        self.tmp.cleanup()

    async def test_valid_script_runs_in_current_python_and_cleans_up(self):
        code = 'import json\nprint("QUERY RESULTS")\nprint(json.dumps({"data": [{"email": "fixture@example.test"}]}))\n'
        output = await runtime.execute_script(code, self.root / "execution")
        self.assertEqual(output["results"][0]["email"], "fixture@example.test")
        self.assertFalse((self.root / "execution/execution.py").exists())
        self.assertFalse((self.root / "execution/base_okta_api_client.py").exists())

    async def test_timeout_and_cancellation_kill_and_reap_subprocess(self):
        for cancel in (False, True):
            started = asyncio.Event()
            async def communicate():
                started.set()
                await asyncio.Event().wait()
            proc = SimpleNamespace(returncode=None, communicate=communicate, kill=Mock(), wait=AsyncMock())
            with patch.object(asyncio, "create_subprocess_exec", AsyncMock(return_value=proc)):
                task = asyncio.create_task(runtime.execute_script('print("QUERY RESULTS")\nprint("[]")', self.root / str(cancel), timeout=0.03 if not cancel else 60))
                await started.wait()
                if cancel:
                    task.cancel()
                with self.assertRaises(asyncio.CancelledError if cancel else TimeoutError):
                    await task
            proc.kill.assert_called_once()
            proc.wait.assert_awaited_once()

    async def test_invalid_generated_code_never_launches_process(self):
        with patch.object(asyncio, "create_subprocess_exec", AsyncMock()) as launch:
            with self.assertRaises(ValueError):
                await runtime.execute_script('eval("danger")', self.root)
            launch.assert_not_awaited()

    async def test_each_query_has_fresh_session_and_completed_result_bypasses_script(self):
        from src.data.schemas import runtime_storage
        output = {"display_type": "table", "results": [{"email": "fixture@example.test"}], "count": 1}
        orchestrate = AsyncMock(return_value=result(completed_result=output, completed_result_event=Mock(return_value=output.copy())))
        client = SimpleNamespace(close_session=AsyncMock())
        with patch.object(runtime_storage, "create_runtime_turn_paths", functools.partial(runtime_storage.create_runtime_turn_paths, root=self.root)), \
             patch("src.core.okta.client.OktaClient", return_value=client), \
             patch.object(runtime, "execute_script", AsyncMock()) as execute:
            for _ in range(2):
                answer = await runtime.run_query({"id": str(uuid4()), "tenant": "tenant", "user": "user", "query": "all users", "timezone": "America/New_York"}, orchestrate=orchestrate)
                self.assertEqual(answer["count"], 1)
            execute.assert_not_awaited()
        calls = orchestrate.call_args_list
        self.assertNotEqual(calls[0].kwargs["artifacts_file"].parents[3], calls[1].kwargs["artifacts_file"].parents[3])
        self.assertEqual(calls[0].kwargs["user_timezone"], "America/New_York")
        self.assertEqual(client.close_session.await_count, 2)

    async def test_clarification_is_not_an_error_and_never_executes(self):
        from src.data.schemas import runtime_storage
        orchestrate = AsyncMock(return_value=result(success=False, outcome="clarify", user_message="Which timezone?", error="internal detail"))
        with patch.object(runtime_storage, "create_runtime_turn_paths", functools.partial(runtime_storage.create_runtime_turn_paths, root=self.root)), \
             patch("src.core.okta.client.OktaClient", return_value=SimpleNamespace(close_session=AsyncMock())), \
             patch.object(runtime, "execute_script", AsyncMock()) as execute:
            answer = await runtime.run_query({"id": str(uuid4()), "tenant": "tenant", "user": "user", "query": "local time"}, orchestrate=orchestrate)
            self.assertEqual(answer["content"], "Which timezone?")
            self.assertEqual(answer["outcome"], "clarify")
            self.assertIn("result_reference", answer)
            execute.assert_not_awaited()

    async def test_incomplete_api_retrieval_returns_failure_without_table(self):
        from src.core.retrieval_outcomes import RetrievalFailure
        from src.data.schemas import runtime_storage
        failed_result = result(script_code='fixture')
        with patch.object(runtime_storage, "create_runtime_turn_paths", functools.partial(runtime_storage.create_runtime_turn_paths, root=self.root)), \
             patch("src.core.okta.client.OktaClient", return_value=SimpleNamespace(close_session=AsyncMock())), \
             patch.object(runtime, "execute_script", AsyncMock(side_effect=RetrievalFailure({'transient'}))), \
             patch('src.core.query_procedures.save_successful_procedure', AsyncMock()) as admission:
            answer = await runtime.run_query({'id': str(uuid4()), 'tenant': 'tenant', 'user': 'user', 'query': 'fixture'},
                                             orchestrate=AsyncMock(return_value=failed_result))
        self.assertEqual(answer['outcome'], 'fail')
        self.assertFalse(answer['success'])
        self.assertNotIn('results', answer)
        self.assertIn('Please try again later', answer['content'])
        self.assertFalse(admission.call_args.kwargs['result'].success)
        self.assertEqual(admission.call_args.kwargs['result'].result_mode, 'failed')

    async def test_recoverable_execution_routes_again_and_saves_only_repaired_answer(self):
        from src.core.agents.orchestrator import OrchestratorResult
        from src.data.schemas import runtime_storage
        from src.core.retrieval_outcomes import RetrievalFailure
        initial, repaired = OrchestratorResult(), OrchestratorResult()
        for item in (initial, repaired):
            item.success = True
            item.outcome = 'success'
            item.script_code = 'fixture'
        repaired.script_code = 'repaired fixture'
        route = AsyncMock(side_effect=[initial, repaired])
        with patch.object(runtime_storage, 'create_runtime_turn_paths', functools.partial(runtime_storage.create_runtime_turn_paths, root=self.root)), \
             patch('src.core.okta.client.OktaClient', return_value=SimpleNamespace(close_session=AsyncMock())), \
             patch.object(runtime, 'execute_script', AsyncMock(side_effect=RetrievalFailure({'request'}))), \
             patch('src.core.execution_recovery.execute_script', AsyncMock(return_value={'display_type': 'table', 'results': [{'id': 'fixed'}], 'count': 1})), \
             patch('src.core.query_procedures.save_successful_procedure', AsyncMock()) as admission:
            answer = await runtime.run_query({'id': str(uuid4()), 'tenant': 'tenant', 'user': 'user', 'query': 'fixture'}, orchestrate=route)
        self.assertEqual(route.await_count, 2)
        self.assertEqual(answer['outcome'], 'success')
        self.assertEqual(answer['results'], [{'id': 'fixed'}])
        self.assertTrue(answer['metadata']['execution_repair_attempted'])
        admission.assert_awaited_once()
        self.assertEqual(admission.call_args.kwargs['result'].script_code, 'repaired fixture')

    async def test_real_guid_owners_keep_portable_paths_and_tenant_isolation(self):
        from src.data.schemas import runtime_storage
        # Match a realistic checkout-root length without a machine-specific path.
        root = self.root / ("nested-" + "x" * max(1, 90 - len(str(self.root))))
        orchestrate = AsyncMock(return_value=result(completed_result={}, completed_result_event=lambda: {"results": []}))
        user, tenant = str(uuid4()), str(uuid4())
        with patch.object(runtime_storage, "create_runtime_turn_paths", functools.partial(runtime_storage.create_runtime_turn_paths, root=root)), \
             patch("src.core.okta.client.OktaClient", return_value=SimpleNamespace(close_session=AsyncMock())):
            for owner in (tenant, tenant, str(uuid4())):
                await runtime.run_query({"id": str(uuid4()), "tenant": owner, "user": user, "query": "hello"}, orchestrate=orchestrate)
        owners = []
        for call in orchestrate.call_args_list:
            artifacts = call.kwargs["artifacts_file"]
            self.assertTrue(artifacts.is_file())
            self.assertTrue(artifacts.is_relative_to(root.resolve()))
            self.assertLess(len(str(artifacts)), 260)
            metadata = json.loads((artifacts.parent.parent / "turn_metadata.json").read_text(encoding="utf-8"))
            owners.append(metadata["user_id"])
        self.assertEqual(owners[0], owners[1])
        self.assertNotEqual(owners[0], owners[2])


def png(size):
    # Tiny synthetic PNG fixture; no user artwork is generated or modified.
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress((b"\0" + b"\0" * size * 4) * size)) + chunk(b"IEND", b"")


class PackageTests(unittest.TestCase):
    def test_installation_package_has_stable_id_and_no_extra_permissions(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "color.png").write_bytes(png(192))
            (root / "outline.png").write_bytes(png(32))
            args = dict(bot_id="11111111-1111-1111-1111-111111111111", website="https://example.test",
                        privacy="https://example.test/privacy", terms="https://example.test/terms",
                        color_icon=root / "color.png", outline_icon=root / "outline.png", output=root / "app.zip")
            ids = []
            for _ in range(2):
                output = build_package(**args)
                with ZipFile(output) as archive:
                    self.assertEqual(set(archive.namelist()), {"manifest.json", "color.png", "outline.png"})
                    manifest = json.loads(archive.read("manifest.json"))
                    ids.append(manifest["id"])
                    self.assertEqual(manifest["bots"][0]["scopes"], ["personal"])
                    self.assertTrue(manifest["bots"][0]["supportsFiles"])
                    self.assertNotIn("webApplicationInfo", manifest)
                    self.assertNotIn("authorization", manifest)
            self.assertEqual(ids[0], ids[1])
            (root / "outline.png").write_bytes(png(192))
            with self.assertRaises(ValueError):
                build_package(**args)


if __name__ == "__main__":
    unittest.main()
