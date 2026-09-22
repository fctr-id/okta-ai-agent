"""Completed saved-result answers must not re-enter retrieval synthesis."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage


class CompletedAnalysisTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        models = patch('src.core.models.model_picker.ModelConfig.get_model', return_value=TestModel())
        models.start()
        self.addCleanup(models.stop)

    async def analyze(self, root, code):
        from src.core.agents import result_analysis_agent as analysis
        source = root / 'saved.json'
        source.write_text(json.dumps({'data': {'results': [{'email': f'user{i}@example.test', 'status': 'ACTIVE'} for i in range(320)]}}))
        artifacts = root / 'artifacts' / 'artifacts.json'
        plan = analysis.ResultAnalysisPlan(mode='analyze', reasoning='Project saved rows',
            selected_result_set_ids=['saved'], python_code=code, persist_result=True)
        run = AsyncMock(return_value=SimpleNamespace(output=plan, usage=RunUsage()))
        with patch.object(analysis, 'result_analysis_agent', SimpleNamespace(run=run)), \
             patch.object(analysis, '_load_conversation_context', AsyncMock(return_value={})), \
             patch.object(analysis, '_load_candidate_result_sets', return_value=[{
                 'result_set_id': 'saved', 'storage_path': str(source), 'row_count': 320,
                 'key_columns': ['email', 'status'], 'entity_type': 'records'}]):
            delegation, _ = await analysis.execute_result_analysis(
                'get me just their email IDs', correlation_id='fixture', artifacts_file=artifacts)
        self.assertTrue(delegation.success, delegation.error)
        self.assertNotIn('completed_result', delegation.model_dump())
        return artifacts, delegation

    async def finish(self, artifacts, delegation):
        from src.core.agents import orchestrator as orch
        result = orch.OrchestratorResult()
        aggregator = SimpleNamespace(set_phase=lambda _: None, step_start=AsyncMock(), step_end=AsyncMock())
        with patch.object(orch, 'execute_synthesis', AsyncMock()) as synthesis:
            await orch._run_synthesis_phase(result=result, user_query='fixture', correlation_id='fixture',
                artifacts_file=artifacts, aggregator=aggregator, latest_processor_delegation=delegation,
                post_processing_succeeded=True, cli_mode=False)
            synthesis.assert_not_awaited()
        self.assertTrue(result.success)
        self.assertIsNone(result.script_code)
        self.assertEqual(result.result_mode, 'direct_answer')
        return result.completed_result_event()

    async def test_all_320_rows_survive_projection_completion_and_persistence(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts, delegation = await self.analyze(root, "analysis_result = {'summary': 'Emails', 'rows': [{'email': row['email']} for row in result_sets['saved']]}")
            event = await self.finish(artifacts, delegation)
            self.assertEqual(event['count'], 320)
            self.assertEqual(event['metadata']['summary'], 'Emails')
            self.assertEqual(event['headers'], ['email'])
            self.assertEqual(event['results'], [{'email': f'user{i}@example.test'} for i in range(320)])
            saved = json.loads(artifacts.read_text())[-1]
            self.assertTrue(saved['canonical_turn_output'])
            self.assertEqual(saved['result_set_inspection']['row_count'], 320)
            from src.core.agents.result_analysis_agent import _load_candidate_result_sets, _load_result_records
            candidates = _load_candidate_result_sets(artifacts, preferred_result_set_refs=saved['result_set_refs'])
            canonical = next(c for c in candidates if c['result_set_id'] == saved['result_set_refs'][0])
            self.assertEqual(_load_result_records(canonical['storage_path']), event['results'])

    async def test_empty_projection_and_scalar_answer_return_without_synthesis(self):
        for output, expected in [
            ({'summary': 'No matches', 'rows': []}, 'table'),
            ({'summary': 'Counted saved rows', 'answer': 'There are 320 records.'}, 'markdown'),
        ]:
            with self.subTest(display=expected), TemporaryDirectory() as tmp:
                artifacts, delegation = await self.analyze(Path(tmp), f'analysis_result = {output!r}')
                event = await self.finish(artifacts, delegation)
                self.assertEqual(event['display_type'], expected)
                if expected == 'table':
                    self.assertEqual(event['results'], [])
                    self.assertEqual(event['count'], 0)
                else:
                    self.assertEqual(event['content'], output['answer'])

    async def test_projection_label_preserves_all_emails_and_persists_subset_lineage(self):
        from src.core.agents.result_analysis_agent import _load_candidate_result_sets, _load_result_records

        with TemporaryDirectory() as tmp:
            artifacts, delegation = await self.analyze(Path(tmp), "analysis_result = {'summary': 'Emails', 'derivation_kind': 'projection', 'rows': [{'email': row['email']} for row in result_sets['saved']]}")
            candidates = _load_candidate_result_sets(artifacts, preferred_result_set_refs=delegation.result_set_refs)
            derived = next(c for c in candidates if c['result_set_id'] == delegation.result_set_refs[0])
            self.assertEqual(derived['derivation_kind'], 'subset')
            self.assertEqual(derived['parent_result_set_ids'], ['saved'])
            expected = [{'email': f'user{i}@example.test'} for i in range(320)]
            self.assertEqual(_load_result_records(derived['storage_path']), expected)
            event = await self.finish(artifacts, delegation)
            self.assertEqual(event['count'], 320)
            self.assertEqual(event['results'], expected)

    def test_derivation_labels_remain_strict_except_for_projection_alias(self):
        from pydantic import ValidationError
        from src.core.agents.result_analysis_agent import ResultAnalysisExecutionOutput

        for label in ('initial', 'filter', 'enrichment', 'join', 'aggregation', 'subset', 'unknown', None):
            with self.subTest(label=label):
                result = ResultAnalysisExecutionOutput(summary='Fixture', derivation_kind=label)
                self.assertEqual(result.derivation_kind, label)
        for label in ('invented_operation', '', ['projection']):
            with self.subTest(invalid=label), self.assertRaises(ValidationError):
                ResultAnalysisExecutionOutput(summary='Fixture', derivation_kind=label)

    async def test_supervised_followup_completes_without_sql_api_or_synthesis(self):
        from src.core.agents import orchestrator as orch
        from src.core.agents.supervisor_agent import SupervisorDecision
        with TemporaryDirectory() as tmp:
            artifacts, delegation = await self.analyze(Path(tmp), "analysis_result = {'summary': 'Emails', 'derivation_kind': 'projection', 'rows': [{'email': row['email']} for row in result_sets['saved']]}")
            with patch.object(orch, '_hydrate_session_result_set_context', AsyncMock(return_value=0)), \
                 patch.object(orch, 'get_database_runtime_summary', return_value={}), \
                 patch.object(orch, 'get_special_tool_capability_summary', return_value={}), \
                 patch.object(orch, 'supervise_query', AsyncMock(return_value=(SupervisorDecision(mode='delegate', target='RESULT_ANALYSIS', reasoning='Use saved rows'), None))), \
                 patch.object(orch, 'supervise_next_step', AsyncMock(return_value=(SupervisorDecision(mode='complete', target='NONE', result_mode='direct_answer', reasoning='Analysis answers the request'), None))), \
                 patch.object(orch, 'execute_result_analysis', AsyncMock(return_value=(delegation, None))), \
                 patch.object(orch, 'execute_sql_discovery', AsyncMock()) as sql, \
                 patch.object(orch, 'execute_api_discovery', AsyncMock()) as api, \
                 patch.object(orch, 'execute_synthesis', AsyncMock()) as synthesis:
                result = await orch.execute_multi_agent_query(user_query='get me just their email IDs',
                    correlation_id='fixture', artifacts_file=artifacts, okta_client=None, cancellation_check=lambda: False)
            self.assertTrue(result.success, result.error)
            self.assertEqual(result.completed_result_event()['count'], 320)
            self.assertNotIn('completed_result', result.delegation_results[0])
            sql.assert_not_awaited()
            api.assert_not_awaited()
            synthesis.assert_not_awaited()

    async def test_synthesis_failure_keeps_diagnostics_out_of_user_message(self):
        from src.core.agents import orchestrator as orch
        from src.core.agents.synthesis_agent import SynthesisResult
        for message in (None, 'I could not include every requested record.'):
            result = orch.OrchestratorResult()
            diagnostic = 'Missing sql_query for rs_internal_123 at private/path'
            aggregator = SimpleNamespace(set_phase=lambda _: None, step_start=AsyncMock(), step_end=AsyncMock(),
                                         tool_call=AsyncMock(), progress=AsyncMock())
            with TemporaryDirectory() as tmp, patch.object(orch, 'execute_synthesis', AsyncMock(return_value=(
                    SynthesisResult(success=False, error=diagnostic, user_message=message), None))):
                await orch._run_synthesis_phase(result=result, user_query='fixture', correlation_id='fixture',
                    artifacts_file=Path(tmp)/'artifacts.json', aggregator=aggregator,
                    latest_processor_delegation=None, post_processing_succeeded=False, cli_mode=False)
            self.assertFalse(result.success)
            self.assertEqual(result.error, diagnostic)
            self.assertNotIn('sql_query', result.user_message)
            self.assertNotIn('rs_internal', result.user_message)
            if message:
                self.assertEqual(result.user_message, message)


if __name__ == '__main__':
    unittest.main()
