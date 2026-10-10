"""Offline evidence retention, bounded previews, and temporary-file cleanup."""
from tests.security_support import CHECKS
import asyncio
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from pydantic_ai import ModelRetry
from src.core.agents.api_discovery_agent import (
    APIDiscoveryDeps, APIDiscoveryResult, create_api_toolset, execute_api_discovery,
)
from src.data.schemas.artifact_manifest import load_artifacts_file
from src.data.schemas.discovery_results import DiscoveryResults, result_preview
from src.data.schemas.runtime_storage import create_runtime_turn_paths

CODE = 'async def sample():\n    return []'


class DiscoveryResultChecks(unittest.IsolatedAsyncioTestCase):
    def deps(self):
        return APIDiscoveryDeps(correlation_id='offline',
            artifacts_file=CHECKS / uuid4().hex / 'artifacts' / 'artifacts.json')

    async def test_large_result_saved_exactly_and_inspected_without_another_read(self):
        deps = self.deps()
        tools = create_api_toolset(deps).tools
        payload = {name: {'status': 'success', 'data': [
            {'id': f'{name}-{i}', 'displayName': 'Example', 'nested': {'detail': 'x' * 5000}}
            for i in range(3)]} for name in ('signins', 'signin_detail', 'audits', 'audit_detail')}
        with patch('src.core.process_runner.run_worker', new=AsyncMock(return_value=payload)) as worker:
            response = await tools['execute_test_query'].function(CODE)
            self.addCleanup(deps.test_results.cleanup)
            preview = json.loads(response.content)
            self.assertTrue(preview['truncated'])
            self.assertLess(len(response.content), 4200)
            self.assertEqual(set(preview['data']['fields']), set(payload))
            test_id = preview['test_id']
            inspected = await tools['inspect_test_result'].function(test_id, ['audits', 'data', '2', 'id'])
            self.assertEqual(json.loads(inspected.content)['data'], 'audits-2')
            with self.assertRaises(ModelRetry):
                await tools['save_artifact'].function('foreign', '../another-test')
            await tools['save_artifact'].function('evidence', test_id, 'Combined sample')
            await tools['save_artifact'].function('evidence', test_id)
            worker.assert_awaited_once()
        saved = load_artifacts_file(deps.artifacts_file)
        self.assertEqual(len(saved), 1)
        self.assertEqual(json.loads(saved[0]['content']), payload)
        self.assertEqual(saved[0]['api_code'], CODE)
        sidecar = Path(saved[0]['artifact_manifest']['storage_path'])
        self.assertEqual(json.loads(sidecar.read_text())['data'], payload)
        directory = deps.test_results.directory
        deps.test_results.cleanup()
        self.assertFalse(directory.exists())
        self.assertTrue(sidecar.exists())
        self.assertFalse(result_preview({'ok': True})['truncated'])

    async def test_failed_save_does_not_claim_evidence_was_retained(self):
        deps = self.deps()
        tools = create_api_toolset(deps).tools
        with patch('src.core.process_runner.run_worker', new=AsyncMock(return_value=[{'id': 'sample'}])):
            response = await tools['execute_test_query'].function(CODE)
        self.addCleanup(deps.test_results.cleanup)
        test_id = response.metadata['test_id']
        with patch('src.core.agents.api_discovery_agent.dump_artifacts_to_file', new=AsyncMock(side_effect=OSError('disk unavailable'))):
            with self.assertRaises(OSError):
                await tools['save_artifact'].function('evidence', test_id)
        self.assertEqual(deps.artifacts, [])
        self.assertEqual(deps.test_results.saved, {})
        self.assertEqual(deps.test_results.get(test_id)['result'], [{'id': 'sample'}])

    async def test_discovery_cleans_temporary_results_on_return_failure_and_cancel(self):
        for outcome in ('success', 'failure', 'cancel'):
            with self.subTest(outcome=outcome):
                deps = self.deps()
                directories = []
                async def run(*args, **kwargs):
                    tools = kwargs['toolsets'][0].tools
                    response = await tools['execute_test_query'].function(CODE)
                    directories.append(deps.test_results.directory)
                    if outcome == 'cancel':
                        raise asyncio.CancelledError()
                    if outcome == 'failure':
                        raise RuntimeError('Synthetic model failure')
                    await tools['save_artifact'].function('evidence', response.metadata['test_id'])
                    return SimpleNamespace(output=APIDiscoveryResult(success=True, api_data_retrieved=True), usage=None)
                with patch('src.core.process_runner.run_worker', new=AsyncMock(return_value=[{'id': 'sample'}])), \
                     patch('src.core.agents.api_discovery_agent.api_discovery_agent.run', new=AsyncMock(side_effect=run)):
                    if outcome == 'cancel':
                        with self.assertRaises(asyncio.CancelledError):
                            await execute_api_discovery('Offline check', deps)
                    else:
                        result, _ = await execute_api_discovery('Offline check', deps)
                        self.assertEqual(result.success, outcome == 'success')
                self.assertEqual(len(directories), 1)
                self.assertFalse(directories[0].exists())
                self.assertIsNone(deps.test_results)
                if outcome == 'success':
                    self.assertEqual(len(load_artifacts_file(deps.artifacts_file)), 1)

    def test_next_query_removes_only_stale_temporary_results(self):
        root = CHECKS / uuid4().hex
        paths = create_runtime_turn_paths(user_id='fixture', run_id='first', root=root)
        stale = DiscoveryResults(paths.artifacts_file)
        fresh = DiscoveryResults(paths.artifacts_file)
        self.addCleanup(stale.cleanup)
        self.addCleanup(fresh.cleanup)
        stale.put('api-test-' + 'a' * 32, CODE, {'id': 'stale'})
        fresh.put('api-test-' + 'b' * 32, CODE, {'id': 'fresh'})
        preserved = paths.results_dir / 'durable.json'
        preserved.write_text('{"saved":true}')
        old = time.time() - 2 * 86400
        for entry in [*stale.directory.iterdir(), stale.directory, preserved]:
            os.utime(entry, (old, old))
        create_runtime_turn_paths(user_id='fixture', run_id='next', root=root)
        self.assertFalse(stale.directory.exists())
        self.assertTrue(fresh.directory.exists())
        self.assertTrue(preserved.exists())
