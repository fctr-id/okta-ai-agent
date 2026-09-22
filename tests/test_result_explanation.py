"""Result explanations survive execution and saved history without model calls."""
import asyncio
import ast
import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from src.data.schemas.artifact_manifest import append_artifacts_with_result_sets


def load_functions(path, names, namespace):
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    assert len(nodes) == len(names)
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), path, 'exec'), namespace)


class ResultExplanationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ns = dict(globals(), logger=logging.getLogger('result-explanation'),
                       __file__=str(Path('src/api/routers/react_stream.py').resolve()))
        load_functions('src/api/routers/react_stream.py', {
            '_parse_script_output', '_execute_script', '_persist_turn_output_artifact',
            '_build_turn_output_summary', '_build_turn_output_artifact_payload',
        }, self.ns)

    async def execute(self, root, rows, summary=None):
        output = {'display_type': 'table', 'data': rows, 'count': 999, 'summary': summary}
        stdout = ('QUERY RESULTS\n====\n' + json.dumps(output) + '\n====\n').encode()
        process = SimpleNamespace(returncode=0, wait=AsyncMock(),
                                  stdout=asyncio.StreamReader(), stderr=asyncio.StreamReader())
        process.stdout.feed_data(stdout)
        process.stdout.feed_eof()
        process.stderr.feed_eof()
        script = root / 'execution.py'
        script.touch()
        self.ns['_resolve_path_within_directory'] = lambda *a, **kw: script
        result = SimpleNamespace(data_source_type='api', last_sync_time=None,
                                 outcome_metadata=lambda: {'outcome': 'success'})
        with patch.object(asyncio, 'create_subprocess_exec', AsyncMock(return_value=process)):
            events = [event async for event in self.ns['_execute_script']('fixture', str(script), lambda: False, result)]
        return events[-1]

    async def test_executed_count_and_scope_survive_saved_result_compaction(self):
        summary = 'Live API records excluding deprovisioned accounts.'
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            event = await self.execute(root, [{'email': 'a@example.test'}, {'email': 'b@example.test'}], summary)
            self.assertEqual(event['count'], 2)  # Do not trust the generated count=999.
            self.assertEqual(event['metadata']['summary'], summary)
            self.assertEqual(event['metadata']['data_source_type'], 'api')
            artifacts = root / 'artifacts' / 'artifacts.json'
            self.ns['_persist_turn_output_artifact'](artifacts_file=artifacts, complete_event=event)
            saved = json.loads(artifacts.read_text())[-1]
            self.assertEqual(saved['metadata']['summary'], summary)
            payload = json.loads(saved['content'])
            self.assertEqual(payload['metadata']['summary'], summary)
            self.assertEqual(payload['count'], 2)
            self.assertTrue(payload['content_omitted'])

    async def test_empty_explanation_survives_markdown_history_reload(self):
        summary = 'No saved records matched the requested filter.'
        with TemporaryDirectory() as tmp:
            event = await self.execute(Path(tmp), [], summary)
        self.assertEqual(event['metadata']['summary'], summary)
        self.assertEqual(event['metadata']['outcome'], 'empty')
        artifact = {'content': event['content'], 'display_type': 'markdown', 'metadata': event['metadata']}
        self.ns.update(_load_turn_output_artifact=lambda turn: artifact,
                       ConversationTurnResultPreviewResponse=lambda **kw: SimpleNamespace(**kw))
        load_functions('src/api/routers/history.py', {'_build_markdown_turn_preview'}, self.ns)
        restored = self.ns['_build_markdown_turn_preview'](SimpleNamespace())
        self.assertEqual(restored.metadata['summary'], summary)
        self.assertEqual(restored.metadata['outcome'], 'empty')

    def test_legacy_missing_and_non_text_summaries_do_not_break_results(self):
        for summary in [None, '', {'unexpected': 'object'}, 123]:
            output = {'display_type': 'table', 'data': [{'value': 1}], 'summary': summary}
            parsed = self.ns['_parse_script_output']('QUERY RESULTS\n' + json.dumps(output) + '\n====')
            self.assertEqual(parsed['count'], 1)
            self.assertNotIn('summary', parsed['metadata'])

    def test_restored_tables_use_answer_summary_and_never_inspection_summary(self):
        from src.data.schemas.artifact_manifest import extract_records

        load_functions('src/api/routers/history.py', {
            '_build_table_turn_preview', '_build_turn_full_result',
        }, self.ns)
        with TemporaryDirectory() as tmp:
            sidecar_path = Path(tmp) / 'results.json'
            sidecar_path.touch()
            self.ns.update(
                PREVIEW_ROW_LIMIT=25,
                extract_records=extract_records,
                _list_matching_result_entries=lambda turn: [{'storage_path': str(sidecar_path), 'row_count': 1}],
                _resolve_safe_runtime_path=lambda path: Path(path),
                _load_json_payload=lambda *args: {
                    'data': [{'email': 'a@example.test'}],
                    'inspection': {'summary': 'Found 1 records. Key columns: email.'},
                },
                _load_turn_output_json_payload=lambda turn: None,
                _coerce_int=lambda value: int(value) if value is not None else None,
                _build_preview_headers=lambda rows: ['email'],
                _normalize_headers=lambda headers, rows: ['email'],
                ConversationTurnResultPreviewResponse=lambda **kw: SimpleNamespace(**kw),
            )
            for summary in ['One user matched your email filter.', None, '', '   ']:
                turn = SimpleNamespace(display_type='table', completion_mode='completed',
                                       final_response_summary=summary)
                for builder in ['_build_table_turn_preview', '_build_turn_full_result']:
                    with self.subTest(summary=summary, builder=builder):
                        restored = self.ns[builder](turn)
                        self.assertEqual(restored.metadata['summary'], (summary or '').strip() or None)
                        self.assertEqual(restored.content, [{'email': 'a@example.test'}])


if __name__ == '__main__':
    unittest.main()
