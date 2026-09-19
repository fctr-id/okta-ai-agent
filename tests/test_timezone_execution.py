"""Offline timezone/runtime and SSE contracts; no app configuration or tenant access."""
import ast
import asyncio
import builtins
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
import unittest
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator, ValidationError
from src.utils.security_config import SECURITY_VALIDATION_USER_MESSAGE, validate_result_analysis_code, validate_generated_code
from src.utils.timezone_context import normalize_user_timezone
from src.data.schemas.artifact_manifest import DerivationKind, append_artifacts_with_result_sets


def definitions(path, names, namespace):
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in names]
    assert len(nodes) == len(names), names
    for node in nodes:
        node.decorator_list = []
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), path, 'exec'), namespace)
    return namespace


class TimezoneExecutionTests(unittest.TestCase):
    def execute(self, code, zone='America/New_York'):
        validation = validate_result_analysis_code(code)
        self.assertTrue(validation.is_valid, validation.violations)
        ns = definitions('src/core/agents/result_analysis_agent.py', {'_execute_analysis_code', 'ResultAnalysisExecutionOutput'}, dict(globals()))
        ns['_load_result_records'] = lambda _: [{'value': 'fixture'}]
        return ns['_execute_analysis_code'](user_query='fixture', python_code=code,
            selected_candidates={'saved': {'storage_path': 'unused'}}, selected_result_set_ids=['saved'], user_timezone=zone)

    def test_helpers_comprehensions_and_inputs_share_namespace(self):
        output = self.execute('''
def helper():
    return result_sets[selected_result_set_ids[0]][0]['value']
def convert():
    return helper() + user_query
analysis_result = {'summary': 'done', 'rows': [{'value': convert()} for i in range(2)]}
''')
        self.assertEqual(output.rows, [{'value': 'fixturefixture'}] * 2)

    def test_conversion_dst_boundaries_naive_utc_and_nulls(self):
        output = self.execute('''
def convert(value):
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(ZoneInfo(user_timezone)).isoformat()
values = ['2026-01-01T12:00:00Z', '2026-07-01T12:00:00Z',
          '2026-03-08T06:59:00Z', '2026-03-08T07:00:00Z',
          '2026-11-01T05:30:00Z', '2026-11-01T06:30:00Z',
          '2026-07-01 12:00:00', None]
analysis_result = {'summary': 'done', 'rows': [{'value': convert(v)} for v in values]}
''')
        self.assertEqual([r['value'] for r in output.rows], [
            '2026-01-01T07:00:00-05:00', '2026-07-01T08:00:00-04:00',
            '2026-03-08T01:59:00-05:00', '2026-03-08T03:00:00-04:00',
            '2026-11-01T01:30:00-04:00', '2026-11-01T01:30:00-05:00',
            '2026-07-01T08:00:00-04:00', None])

    def test_fractional_offset_and_existing_offset(self):
        output = self.execute("analysis_result = {'summary': datetime.fromisoformat('2026-07-01T08:00:00-04:00').astimezone(ZoneInfo(user_timezone)).isoformat()}", 'Asia/Kathmandu')
        self.assertEqual(output.summary, '2026-07-01T17:45:00+05:45')

    def test_execution_namespace_is_not_reused(self):
        self.execute("marker = 1\nanalysis_result = {'summary': 'done'}")
        with self.assertRaises(NameError):
            self.execute("analysis_result = {'summary': str(marker)}")

    def test_restricted_code_still_blocks_imports_io_and_introspection(self):
        for code in ['import zoneinfo', "open('secret')", 'ZoneInfo.from_file(None)', 'datetime.__mro__', "__import__('os')"]:
            with self.subTest(code=code):
                self.assertFalse(validate_result_analysis_code(code).is_valid)
        self.assertTrue(validate_generated_code('from zoneinfo import ZoneInfo').is_valid)

    def test_query_timezone_validation_and_older_clients(self):
        ns = definitions('src/api/routers/react_stream.py', {'QueryRequest'}, dict(globals()))
        request = ns['QueryRequest']
        # Resolve postponed annotations without importing the application.
        from typing import Optional
        request.model_rebuild(_types_namespace={'Optional': Optional})
        self.assertIsNone(request(query='fixture').user_timezone)
        self.assertEqual(request(query='fixture', user_timezone=' Asia/Kathmandu ').user_timezone, 'Asia/Kathmandu')
        for invalid in ['not/a-zone', '../../etc/passwd', '/etc/passwd', 'x' * 129]:
            with self.subTest(zone=invalid), self.assertRaises(ValidationError):
                request(query='fixture', user_timezone=invalid)


class StreamOutcomeTests(unittest.IsolatedAsyncioTestCase):
    async def test_clarification_persists_and_runtime_failure_stays_error(self):
        tree = ast.parse(Path('src/api/routers/react_stream.py').read_text(encoding='utf-8'))
        route = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'stream_react_updates')
        generator = next(n for n in route.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'event_generator')
        for outcome in ['clarify', 'fail', 'analysis', 'validation_failure']:
            with self.subTest(outcome=outcome), TemporaryDirectory() as tmp:
                root = Path(tmp)
                paths = SimpleNamespace(artifacts_file=root/'artifacts.json', turn_metadata_file=root/'metadata.json',
                    turn_summary_file=root/'summary.json', user_id='fixture', session_id='fixture', run_id='fixture', turn_number=1)
                process = {'query': 'fixture', 'source': 'web', 'user_timezone': 'Asia/Kathmandu'}
                result = SimpleNamespace(success=outcome in {'analysis', 'validation_failure'}, no_data_found=False, outcome=outcome,
                    user_message='Which timezone?' if outcome == 'clarify' else None, error='fixture failure')
                if outcome == 'validation_failure':
                    result.completed_result = None
                    result.script_code = 'exec("print(1)")'
                    result.is_special_tool = False
                if outcome == 'analysis':
                    result.completed_result = {'type': 'COMPLETE', 'display_type': 'table', 'count': 320,
                        'headers': ['email'], 'results': [{'email': f'user{i}@example.test'} for i in range(320)]}
                    result.completed_result_event = lambda: result.completed_result
                    result.total_input_tokens = result.total_output_tokens = result.total_tokens = result.total_requests = 0
                result.outcome_metadata = lambda: {'outcome': outcome, 'result_mode': 'needs_clarification' if outcome == 'clarify' else 'failed'}
                ns = dict(globals(), process=process, process_id='fixture', active_processes={'fixture': process},
                    logger=logging.getLogger('fixture'), settings=SimpleNamespace(tenant_id='fixture'),
                    OktaClient=Mock(), DatabaseOperations=Mock(return_value=SimpleNamespace(mirror_runtime_turn_state=AsyncMock(return_value=True))),
                    _create_runtime_turn_paths=AsyncMock(return_value=paths), execute_multi_agent_query=AsyncMock(return_value=result))
                definitions('src/data/schemas/runtime_storage.py', {'update_turn_metadata', 'write_turn_summary', '_load_json_object', '_write_json'}, ns)
                definitions('src/api/routers/react_stream.py', {'_persist_turn_output_artifact', '_build_turn_output_summary', '_build_turn_output_artifact_payload'}, ns)
                module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), generator], type_ignores=[])
                exec(compile(ast.fix_missing_locations(module), 'stream', 'exec'), ns)
                if outcome == 'validation_failure':
                    with self.assertLogs('fixture', level='ERROR') as logs:
                        events = [json.loads(chunk.removeprefix('data: ')) async for chunk in ns['event_generator']()]
                    self.assertIn('Unauthorized function call: exec', '\n'.join(logs.output))
                else:
                    events = [json.loads(chunk.removeprefix('data: ')) async for chunk in ns['event_generator']()]
                ns['execute_multi_agent_query'].assert_awaited_once()
                self.assertEqual(ns['execute_multi_agent_query'].call_args.kwargs['user_timezone'], 'Asia/Kathmandu')
                metadata = json.loads(paths.turn_metadata_file.read_text())
                if outcome == 'clarify':
                    self.assertEqual([e['type'] for e in events], ['COMPLETE', 'DONE'])
                    self.assertEqual(events[0]['content'], 'Which timezone?')
                    self.assertEqual(events[0]['metadata']['result_mode'], 'needs_clarification')
                    summary = json.loads(paths.turn_summary_file.read_text())
                    self.assertEqual(summary['final_response_summary'], 'Which timezone?')
                    self.assertEqual(metadata['status'], 'completed')
                    self.assertNotIn('error', metadata)
                    definitions('src/core/okta/sync/operations.py', {'_derive_completion_mode'}, ns)
                    self.assertEqual(ns['_derive_completion_mode'](metadata['status'], summary), 'clarify')
                    saved = json.loads(paths.artifacts_file.read_text())
                    ns['_load_turn_output_artifact'] = lambda _: saved[-1]
                    ns['ConversationTurnResultPreviewResponse'] = SimpleNamespace
                    definitions('src/api/routers/history.py', {'_build_markdown_turn_preview'}, ns)
                    preview = ns['_build_markdown_turn_preview'](SimpleNamespace(completion_mode='clarify'))
                    self.assertTrue(preview.available)
                    self.assertEqual(preview.content, 'Which timezone?')
                elif outcome == 'analysis':
                    self.assertEqual([e['type'] for e in events], ['COMPLETE', 'DONE'])
                    self.assertEqual(len(events[0]['results']), 320)
                    self.assertEqual(events[0]['headers'], ['email'])
                    self.assertEqual(metadata['status'], 'completed')
                    summary = json.loads(paths.turn_summary_file.read_text())
                    self.assertEqual(summary['result_count'], 320)
                elif outcome == 'validation_failure':
                    self.assertEqual(events[-1]['type'], 'ERROR')
                    self.assertEqual(events[-1]['error'], SECURITY_VALIDATION_USER_MESSAGE)
                    self.assertEqual(events[-2]['text'], SECURITY_VALIDATION_USER_MESSAGE)
                    self.assertNotIn('Unauthorized function call', json.dumps(events))
                    self.assertEqual(metadata['status'], 'error')
                else:
                    self.assertEqual(events[0]['type'], 'ERROR')
                    self.assertEqual(events[0]['error'], 'fixture failure')
                    self.assertEqual(metadata['status'], 'error')


if __name__ == '__main__':
    unittest.main()
