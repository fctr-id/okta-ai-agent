"""Offline shared execution and single-fallback checks using real subprocesses."""
import asyncio
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from pydantic_ai.models.test import TestModel


CODE = '''import json
print("QUERY RESULTS")
print(json.dumps({"display_type": "table", "data": [{"value": "fresh"}], "headers": ["value"], "summary": "Fresh fixture"}))
'''


class ReuseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        models = patch('src.core.models.model_picker.ModelConfig.get_model', return_value=TestModel())
        models.start()
        self.addCleanup(models.stop)

    async def test_adaptation_executes_changed_fields_or_falls_back_once(self):
        from src.core.agents import orchestrator as orch
        from src.core.agents.supervisor_agent import SupervisorDecision
        from src.core.agents.synthesis_agent import SynthesisResult
        from src.core import procedure_reuse as reuse
        candidate = {'script_code': CODE, 'procedure_id': 'fixture', 'output_fields': ['value'],
                     'data_source': 'sql', 'evidence': [{'sql_query': 'SELECT email FROM users'}]}
        for code, expected in ((CODE.replace('value', 'email'), True),
                               ('print(undefined_fixture_name)', False), ('import os', False), (None, False)):
            with self.subTest(code=code), TemporaryDirectory() as tmp, ExitStack() as stack:
                chosen = SupervisorDecision(mode='complete', target='SYNTHESIS', reasoning='Supported change',
                    reuse_procedure_id='fixture', adapt_procedure=True)
                fallback = SupervisorDecision(mode='delegate', target='SQL', reasoning='Discover again')
                async def normal_synthesis(**kwargs):
                    kwargs['result'].success = True
                    kwargs['result'].script_code = CODE
                for name, value in (('_hydrate_session_result_set_context', AsyncMock(return_value=0)),
                                    ('get_database_runtime_summary', lambda: {}), ('get_special_tool_capability_summary', lambda: {}),
                                    ('get_last_sync_timestamp', lambda: None),
                                    ('_run_discovery_loop', AsyncMock(return_value=(None, False))),
                                    ('_validate_discovery_before_synthesis', AsyncMock(return_value=SimpleNamespace(should_stop=False, post_processing_succeeded=False))),
                                    ('_run_synthesis_phase', normal_synthesis)):
                    stack.enter_context(patch.object(orch, name, value))
                supervisor = stack.enter_context(patch.object(orch, 'supervise_query', AsyncMock(side_effect=[(chosen, None), (fallback, None)])))
                discovery = stack.enter_context(patch.object(orch, '_run_initial_sql_discovery', AsyncMock(return_value=('SQL', 0, None, False))))
                synthesis = stack.enter_context(patch.object(orch, 'execute_synthesis', AsyncMock(return_value=(
                    SynthesisResult(success=bool(code), script_code=code, error=None if code else 'Needs discovery'), None))))
                stack.enter_context(patch.object(reuse, 'inspect_procedure', AsyncMock(return_value=candidate)))
                record = stack.enter_context(patch.object(reuse, 'record_procedure_reuse', AsyncMock()))
                result = await orch.execute_multi_agent_query('List only emails', 'run', Path(tmp)/'artifacts.json', None, lambda: False)
                self.assertTrue(result.success)
                synthesis.assert_awaited_once()
                self.assertEqual(synthesis.call_args.args[0], 'List only emails')
                self.assertEqual(synthesis.call_args.args[1].saved_procedure, candidate)
                self.assertEqual(candidate['script_code'], CODE)
                if expected:
                    self.assertEqual(result.procedure_reuse, 'adapted')
                    self.assertEqual(result.completed_result['results'], [{'email': 'fresh'}])
                    self.assertEqual(result.completed_result['metadata']['parent_procedure_id'], 'fixture')
                    self.assertEqual(result.phases_executed, ['reuse_adapt', 'reuse'])
                    discovery.assert_not_awaited()
                    record.assert_not_awaited()
                else:
                    self.assertEqual(result.procedure_reuse, 'fallback')
                    self.assertIsNone(result.completed_result)
                    self.assertIsNone(result.reusable_procedure)
                    self.assertEqual(supervisor.await_count, 2)
                    self.assertTrue(supervisor.call_args_list[1].kwargs['workflow_state']['disable_procedure_reuse'])
                    self.assertTrue(result.execution_repair_attempted)
                    discovery.assert_awaited_once()

    def test_adaptation_requires_selected_procedure(self):
        from src.core.agents.supervisor_agent import SupervisorDecision
        with self.assertRaises(ValueError):
            SupervisorDecision(mode='complete', target='SYNTHESIS', reasoning='No candidate', adapt_procedure=True)

    async def test_api_failure_policy_stops_outages_and_rediscovers_bad_requests_once(self):
        from src.core.agents import orchestrator as orch
        from src.core.agents.supervisor_agent import SupervisorDecision
        from src.core import procedure_reuse as reuse
        from src.core.retrieval_outcomes import RetrievalFailure
        for category in ('request', 'missing', 'pagination_limit', 'access', 'transient'):
            with self.subTest(category=category), TemporaryDirectory() as tmp, ExitStack() as stack:
                chosen = SupervisorDecision(mode='complete', target='SYNTHESIS', reasoning='Match', reuse_procedure_id='fixture')
                fallback = SupervisorDecision(mode='delegate', target='SQL', reasoning='Repair retrieval')
                async def synthesize(**kwargs):
                    kwargs['result'].success = True
                    kwargs['result'].script_code = CODE
                for name, value in (('_hydrate_session_result_set_context', AsyncMock(return_value=0)),
                                    ('get_database_runtime_summary', lambda: {}), ('get_special_tool_capability_summary', lambda: {}),
                                    ('_run_discovery_loop', AsyncMock(return_value=(None, False))),
                                    ('_validate_discovery_before_synthesis', AsyncMock(return_value=SimpleNamespace(should_stop=False, post_processing_succeeded=False))),
                                    ('_run_synthesis_phase', synthesize)):
                    stack.enter_context(patch.object(orch, name, value))
                supervisor = stack.enter_context(patch.object(orch, 'supervise_query', AsyncMock(side_effect=[(chosen, None), (fallback, None)])))
                discovery = stack.enter_context(patch.object(orch, '_run_initial_sql_discovery', AsyncMock(return_value=('SQL', 0, None, False))))
                stack.enter_context(patch.object(reuse, 'inspect_procedure', AsyncMock(return_value={'script_code': CODE})))
                stack.enter_context(patch.object(reuse, 'execute_script', AsyncMock(side_effect=RetrievalFailure({category}))))
                record = stack.enter_context(patch.object(reuse, 'record_procedure_reuse', AsyncMock()))
                result = await orch.execute_multi_agent_query('fixture', 'run', Path(tmp)/'artifacts.json', None, lambda: False)
                record.assert_awaited_once_with('run', 'fixture', failed=True)
                if category in ('access', 'transient'):
                    self.assertFalse(result.success)
                    self.assertEqual(result.outcome, 'fail')
                    self.assertIn('Could not retrieve all required data', result.user_message)
                    supervisor.assert_awaited_once()
                    discovery.assert_not_awaited()
                else:
                    self.assertTrue(result.success)
                    self.assertEqual(result.procedure_reuse, 'fallback')
                    self.assertEqual(supervisor.await_count, 2)
                    self.assertTrue(supervisor.call_args_list[1].kwargs['workflow_state']['disable_procedure_reuse'])
                    self.assertEqual(supervisor.call_args_list[1].kwargs['workflow_state']['execution_failure']['categories'], [category])
                    self.assertTrue(result.execution_repair_attempted)
                    discovery.assert_awaited_once()

    async def test_validated_current_execution_and_failure_fallback(self):
        from src.core import procedure_reuse as reuse
        for code, succeeds in ((CODE, True), ('print(undefined_fixture_name)', False)):
            with self.subTest(succeeds=succeeds), TemporaryDirectory() as tmp:
                candidate = {'script_code': code, 'procedure_id': 'fixture', 'output_fields': ['value']}
                with patch.object(reuse, 'inspect_procedure', AsyncMock(return_value=candidate)), \
                     patch.object(reuse, 'record_procedure_reuse', AsyncMock()) as record:
                    output = await reuse.execute_selected_procedure(run_id='run', procedure_id='fixture',
                        artifacts_file=Path(tmp)/'artifacts.json', cancellation_check=lambda: False)
                if succeeds:
                    self.assertEqual(output[1]['results'], [{'value': 'fresh'}])
                    record.assert_awaited_once_with('run', 'fixture')
                else:
                    self.assertIsNone(output)
                    record.assert_awaited_once_with('run', 'fixture', failed=True)

    async def test_cancel_does_not_trigger_discovery_or_quarantine(self):
        from src.core import procedure_reuse as reuse
        with TemporaryDirectory() as tmp, \
             patch.object(reuse, 'inspect_procedure', AsyncMock(return_value={'script_code': CODE})), \
             patch.object(reuse, 'record_procedure_reuse', AsyncMock()) as record:
            with self.assertRaises(asyncio.CancelledError):
                await reuse.execute_selected_procedure(run_id='run', procedure_id='fixture',
                    artifacts_file=Path(tmp)/'artifacts.json', cancellation_check=lambda: True)
            record.assert_not_awaited()

    async def test_known_partial_output_is_rejected(self):
        from src.core import procedure_reuse as reuse
        candidate = {'script_code': CODE, 'procedure_id': 'fixture', 'output_fields': ['value']}
        with TemporaryDirectory() as tmp, \
             patch.object(reuse, 'inspect_procedure', AsyncMock(return_value=candidate)), \
             patch.object(reuse, 'execute_script', AsyncMock(return_value={'display_type': 'table', 'results': [], 'metadata': {'outcome': 'degraded_success'}})), \
             patch.object(reuse, 'record_procedure_reuse', AsyncMock()) as record:
            self.assertIsNone(await reuse.execute_selected_procedure(run_id='run', procedure_id='fixture',
                artifacts_file=Path(tmp)/'artifacts.json', cancellation_check=lambda: False))
            record.assert_awaited_once_with('run', 'fixture', failed=True)

    async def test_timeout_falls_back_and_later_request_can_succeed(self):
        from src.core import procedure_reuse as reuse
        candidate = {'script_code': CODE, 'procedure_id': 'fixture', 'output_fields': ['value']}
        payload = {'display_type': 'table', 'results': [{'value': 'fresh'}]}
        with TemporaryDirectory() as tmp, \
             patch.object(reuse, 'inspect_procedure', AsyncMock(return_value=candidate)), \
             patch.object(reuse, 'execute_script', AsyncMock(side_effect=[TimeoutError('fixture'), payload])), \
             patch.object(reuse, 'record_procedure_reuse', AsyncMock()) as record:
            kwargs = dict(run_id='run', procedure_id='fixture', artifacts_file=Path(tmp)/'artifacts.json',
                          cancellation_check=lambda: False)
            self.assertIsNone(await reuse.execute_selected_procedure(**kwargs))
            self.assertEqual((await reuse.execute_selected_procedure(**kwargs))[1]['results'], payload['results'])
            self.assertEqual(record.await_args_list[0].kwargs, {'failed': True})
            self.assertEqual(record.await_args_list[1].kwargs, {})

    async def test_supervisor_only_inspects_search_results_once(self):
        from src.core.agents import supervisor_agent as supervisor
        from src.core import query_procedures as store
        progress = AsyncMock()
        ctx = SimpleNamespace(deps=supervisor.SupervisorDeps('run', reuse_enabled=True, step_start_callback=progress))
        candidate = {'procedure_id': 'allowed', 'description': 'Fixture'}
        with patch.object(store, 'procedure_catalog', AsyncMock(return_value=[candidate])) as catalog, \
             patch.object(store, 'inspect_procedure', AsyncMock(return_value={**candidate, 'script_code': CODE})) as inspect:
            self.assertIn('error', await supervisor.inspect_reusable_query(ctx, 'unseen'))
            inspect.assert_not_awaited()
            self.assertEqual((await supervisor.find_reusable_queries(ctx, ['user']))['candidates'], [candidate])
            self.assertEqual((await supervisor.find_reusable_queries(ctx, ['user']))['candidates'], [])
            self.assertIn('script_code', await supervisor.inspect_reusable_query(ctx, 'allowed'))
            self.assertIn('error', await supervisor.inspect_reusable_query(ctx, 'allowed'))
            catalog.assert_awaited_once()
            inspect.assert_awaited_once()
            self.assertEqual([call.args[0]['phase'] for call in progress.await_args_list],
                             ['reuse_search', 'reuse_inspect'])

    async def test_orchestrator_reuse_success_skips_discovery_and_synthesis(self):
        from src.core.agents import orchestrator as orch
        from src.core.agents.supervisor_agent import SupervisorDecision
        from src.core import procedure_reuse as reuse
        decision = SupervisorDecision(mode='complete', target='SYNTHESIS', reasoning='Matching inspected scope', reuse_procedure_id='fixture')
        candidate = {'script_code': CODE, 'procedure_id': 'fixture', 'output_fields': ['value'], 'data_source': 'sql'}
        with TemporaryDirectory() as tmp, ExitStack() as stack:
            for name, value in (('_hydrate_session_result_set_context', AsyncMock(return_value=0)),
                                ('get_database_runtime_summary', lambda: {}),
                                ('get_special_tool_capability_summary', lambda: {}),
                                ('supervise_query', AsyncMock(return_value=(decision, None)))):
                stack.enter_context(patch.object(orch, name, value))
            stack.enter_context(patch.object(reuse, 'inspect_procedure', AsyncMock(return_value=candidate)))
            stack.enter_context(patch.object(reuse, 'record_procedure_reuse', AsyncMock()))
            sql = stack.enter_context(patch.object(orch, '_run_initial_sql_discovery', AsyncMock()))
            synthesis = stack.enter_context(patch.object(orch, '_run_synthesis_phase', AsyncMock()))
            result = await orch.execute_multi_agent_query('fixture', 'run', Path(tmp)/'artifacts.json', None, lambda: False)
        self.assertTrue(result.success, result.error)
        self.assertEqual(result.completed_result_event()['results'], [{'value': 'fresh'}])
        self.assertEqual(result.phases_executed, ['reuse'])
        sql.assert_not_awaited()
        synthesis.assert_not_awaited()

    async def test_real_script_failure_falls_back_once_with_reuse_disabled(self):
        from src.core.agents import orchestrator as orch
        from src.core.agents.supervisor_agent import SupervisorDecision
        from src.core import procedure_reuse as reuse
        chosen = SupervisorDecision(mode='complete', target='SYNTHESIS', reasoning='Inspect fixture', reuse_procedure_id='fixture')
        fallback = SupervisorDecision(mode='delegate', target='SQL', reasoning='Discover again')
        async def synthesize(**kwargs):
            kwargs['result'].success = True
            kwargs['result'].script_code = CODE
        with TemporaryDirectory() as tmp, ExitStack() as stack:
            for name, value in (('_hydrate_session_result_set_context', AsyncMock(return_value=0)),
                                ('get_database_runtime_summary', lambda: {}), ('get_special_tool_capability_summary', lambda: {}),
                                ('_run_discovery_loop', AsyncMock(return_value=(None, False))),
                                ('_validate_discovery_before_synthesis', AsyncMock(return_value=SimpleNamespace(should_stop=False, post_processing_succeeded=False))),
                                ('_run_synthesis_phase', synthesize)):
                stack.enter_context(patch.object(orch, name, value))
            supervisor = stack.enter_context(patch.object(orch, 'supervise_query', AsyncMock(side_effect=[(chosen, None), (fallback, None)])))
            discovery = stack.enter_context(patch.object(orch, '_run_initial_sql_discovery', AsyncMock(return_value=('SQL', 0, None, False))))
            stack.enter_context(patch.object(reuse, 'inspect_procedure', AsyncMock(return_value={'script_code': 'print(undefined_fixture_name)'})))
            record = stack.enter_context(patch.object(reuse, 'record_procedure_reuse', AsyncMock()))
            result = await orch.execute_multi_agent_query('fixture', 'run', Path(tmp)/'artifacts.json', None, lambda: False)
            from src.core.script_execution import execute_script
            final = await execute_script(result.script_code, Path(tmp)/'fresh-execution')
        self.assertTrue(result.success, result.error)
        self.assertEqual(result.procedure_reuse, 'fallback')
        self.assertEqual(final['results'], [{'value': 'fresh'}])
        self.assertEqual(supervisor.await_count, 2)
        self.assertTrue(supervisor.call_args_list[1].kwargs['workflow_state']['disable_procedure_reuse'])
        discovery.assert_awaited_once()
        record.assert_awaited_once_with('run', 'fixture', failed=True)


if __name__ == '__main__':
    unittest.main()
