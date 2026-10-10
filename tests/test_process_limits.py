"""Small offline process controls and legitimate worker compatibility checks."""
from tests.security_support import CHECKS, ROOT
import asyncio
import json
import sqlite3
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from src.core.process_runner import run_process, run_worker


class ProcessLimitsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.children = []
        original = asyncio.create_subprocess_exec

        async def launch(*args, **kwargs):
            child = await original(*args, **kwargs)
            self.children.append(child)
            return child

        self.patcher = patch('asyncio.create_subprocess_exec', side_effect=launch)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    async def asyncTearDown(self):
        for child in self.children:
            if child.returncode is None:
                child.kill()
                await child.wait()
                self.fail('Runner left a child alive')

    async def child(self, code, **kwargs):
        return await run_process([sys.executable, '-u', '-c', code], cwd=ROOT, **kwargs)

    async def test_complete_output_and_live_progress(self):
        seen = []

        async def progress(line):
            seen.append(line)

        result = await self.child('import sys; print("ready", file=sys.stderr); print("done")',
                                  on_stderr=progress)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), b'done')
        self.assertEqual(seen, ['ready'])

    async def test_stdout_and_stderr_caps_reject_instead_of_truncating(self):
        for pipe in ('stdout', 'stderr'):
            with self.subTest(pipe=pipe):
                # Small finite output with deliberately tiny test caps.
                with self.assertRaisesRegex(ValueError, 'output exceeds'):
                    await self.child(f'import sys; print("x" * 2048, file=sys.{pipe})',
                                     stdout_limit=512, stderr_limit=512)

    async def test_silent_slow_child_times_out_and_is_reaped(self):
        with self.assertRaises(TimeoutError):
            await self.child('import time; time.sleep(2)', timeout=0.2)
        self.assertIsNotNone(self.children[-1].returncode)

    async def test_silent_child_observes_cancellation_flag(self):
        checks = 0

        def cancelled():
            nonlocal checks
            checks += 1
            return checks >= 3

        with self.assertRaises(asyncio.CancelledError):
            await self.child('import time; time.sleep(2)', cancellation_check=cancelled)
        self.assertIsNotNone(self.children[-1].returncode)

    async def test_task_cancellation_reaps_child(self):
        task = asyncio.create_task(self.child('import time; time.sleep(2)'))
        while not self.children:
            await asyncio.sleep(0.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNotNone(self.children[-1].returncode)

    async def test_worker_analysis_round_trip(self):
        sidecar = CHECKS / 'worker-analysis.json'
        sidecar.write_text(json.dumps({'data': {'results': [{'name': 'Sample'}]}}), encoding='utf-8')
        result = await run_worker('analysis', {
            'user_query': 'Count rows',
            'python_code': "analysis_result = {'summary': str(len(result_sets['sample']))}",
            'selected_candidates': {'sample': {'storage_path': str(sidecar)}},
            'selected_result_set_ids': ['sample'],
        })
        self.assertEqual(result['summary'], '1')
        self.assertNotIn('rows', result)  # Preserve unset vs explicitly empty rows.

    async def test_worker_sql_round_trip(self):
        database = CHECKS / 'worker-sql.db'
        with sqlite3.connect(database) as connection:
            connection.execute('CREATE TABLE users (id TEXT)')
            connection.execute('INSERT INTO users VALUES (?)', ('sample',))
        # Only the child loads these synthetic settings; no real configuration.
        with patch.dict('os.environ', {'DB_DIR': str(database.parent), 'DB_FILENAME': database.name}):
            result = await run_worker('sql', {'query': 'SELECT id FROM users LIMIT 3'})
        self.assertEqual(result['rows'], [{'id': 'sample'}])

    async def test_api_worker_invocation_shapes_make_one_request(self):
        from src.core.execution_worker import execute_api_code

        class FakeClient:
            calls = 0

            async def make_request(self, endpoint):
                self.calls += 1
                return {'status': 'success', 'data': [{'id': 'sample'}], 'complete': True}

        base = "async def read_users():\n    return await client.make_request('/api/v1/users')\n"
        for suffix in ('', 'answer = await read_users()\n', 'await read_users()\n'):
            client = FakeClient()
            result = await execute_api_code(base + suffix, client)
            self.assertEqual(client.calls, 1)
            self.assertEqual(result['data'], [{'id': 'sample'}])

    async def test_discovery_progress_failure_does_not_change_result(self):
        from src.core.agents.api_discovery_agent import APIDiscoveryDeps, create_api_toolset
        from src.core.process_runner import WORKER_EVENT

        async def disconnected(event):
            raise RuntimeError('Synthetic disconnected consumer')

        async def worker(mode, payload, **kwargs):
            await kwargs['on_stderr'](WORKER_EVENT + json.dumps({'kind': 'progress', 'data': {}}))
            return [{'id': 'sample'}]

        deps = APIDiscoveryDeps(correlation_id='offline', artifacts_file=CHECKS / 'unused.json',
                                endpoints=[], progress_callback=disconnected)
        tool = create_api_toolset(deps).tools['execute_test_query']
        with patch('src.core.process_runner.run_worker', side_effect=worker):
            result = await tool.function('async def sample():\n    return []')
        self.addCleanup(deps.test_results.cleanup)
        self.assertTrue(result.metadata['success'])
        self.assertIn('sample', result.content)

    async def test_web_progress_and_shared_retrieval_results(self):
        from src.api.routers.react_stream import _execute_script
        from src.core.process_runner import ProcessResult
        from src.core.script_execution import execute_script

        payload = {'data': [{'id': 'sample'}], 'count': 1, 'headers': []}
        stdout = 'QUERY RESULTS\n' + json.dumps(payload) + '\n====\n'

        async def completed(args, **kwargs):
            if kwargs.get('on_stderr'):
                await kwargs['on_stderr']('__PROGRESS__' + json.dumps({'entity': 'sample'}))
            return ProcessResult(0, stdout.encode(), b'')

        script = ROOT / 'generated_scripts' / f'offline-process-{uuid4().hex}.py'
        script.parent.mkdir(exist_ok=True)
        script.write_text('print(1)', encoding='utf-8')
        self.addCleanup(script.unlink, missing_ok=True)
        with patch('src.core.process_runner.run_process', side_effect=completed):
            events = [event async for event in _execute_script('offline', str(script), lambda: False)]
            result = await execute_script('print(1)', CHECKS / 'retrieval')
        self.assertEqual([event['type'] for event in events], ['STEP-PROGRESS', 'COMPLETE'])
        self.assertEqual(events[-1]['results'], payload['data'])
        self.assertEqual(result['results'], payload['data'])
        self.assertFalse(script.exists())

    async def test_slack_uses_shared_bounds_and_cleans_staging_on_cancellation(self):
        from src.integrations.slack.slack_app import _execute_script_for_slack
        from src.core.agents.orchestrator import OrchestratorResult
        from src.core.process_runner import ProcessResult

        query_id = 'offline-' + uuid4().hex
        staged = ROOT / 'generated_scripts' / f'slack_execution_{query_id}.py'
        self.addCleanup(staged.unlink, missing_ok=True)
        cancelled = lambda: False
        payload = b'QUERY RESULTS\n{"data":[{"id":"sample"}],"count":1}\n====\n'
        with patch('src.core.process_runner.run_process', return_value=ProcessResult(0, payload, b'')) as run:
            result = await _execute_script_for_slack(query_id, 'print(1)', OrchestratorResult(),
                                                     cancellation_check=cancelled)
        self.assertEqual(result['results'], [{'id': 'sample'}])
        self.assertIs(run.call_args.kwargs['cancellation_check'], cancelled)
        self.assertEqual(run.call_args.kwargs['timeout'], 120)
        self.assertFalse(staged.exists())
        with patch('src.core.process_runner.run_process', side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await _execute_script_for_slack(query_id, 'print(1)', OrchestratorResult())
        self.assertFalse(staged.exists())
