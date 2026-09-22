"""Offline control-flow tests for bounded, generic execution recovery."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from src.core.agents.orchestrator import OrchestratorResult, _discovery_assignment
from src.core.execution_recovery import recover_failed_execution, recovery_instructions
from src.core.retrieval_outcomes import RetrievalFailure


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.result = OrchestratorResult()
        self.result.success = True
        self.result.script_code = 'original script'
        self.result.total_tokens = 12
        self.failure = RetrievalFailure({'request'}, [{'endpoint': '/api/v1/widgets/fixture/links',
            'http_status': 400, 'message': 'Unsupported relationship'}])
        self.kwargs = dict(result=self.result, failure=self.failure, user_query='Inventory widgets',
            correlation_id='test', artifacts_file=Path(self.tmp.name)/'artifacts.json',
            okta_client=object(), cancellation_check=lambda: False)

    def repaired(self):
        result = OrchestratorResult()
        result.success = True
        result.outcome = 'success'
        result.script_code = 'repaired script'
        result.total_tokens = 8
        return result

    async def test_actual_failure_reaches_discovery_and_repaired_script_executes_once(self):
        route = AsyncMock(return_value=self.repaired())
        execute = AsyncMock(return_value={'display_type': 'table', 'results': [{'id': 'fixture'}], 'count': 1})
        events = AsyncMock()
        with patch('src.core.execution_recovery.execute_script', execute):
            payload = await recover_failed_execution(**self.kwargs, orchestrate=route, event_callback=events)
        route.assert_awaited_once()
        sent = route.call_args.kwargs
        self.assertFalse(sent['allow_procedure_reuse'])
        self.assertEqual(sent['user_query'], 'Inventory widgets')
        self.assertEqual(sent['execution_failure']['failures'], self.failure.details)
        self.assertEqual(sent['execution_failure']['failed_script'], 'original script')
        execute.assert_awaited_once()
        self.assertEqual(execute.call_args.args[0], 'repaired script')
        self.assertEqual(self.result.total_tokens, 20)
        self.assertTrue(payload['metadata']['execution_repair_attempted'])
        self.assertEqual(events.call_args.args[0], 'step_start')

    async def test_nonrecoverable_and_consumed_budget_never_call_model(self):
        route = AsyncMock()
        for failure in (RetrievalFailure({'access'}), RetrievalFailure({'transient'})):
            with self.assertRaises(RetrievalFailure):
                await recover_failed_execution(**{**self.kwargs, 'failure': failure}, orchestrate=route)
        self.result.execution_repair_attempted = True
        with self.assertRaises(RetrievalFailure):
            await recover_failed_execution(**self.kwargs, orchestrate=route)
        route.assert_not_awaited()

    async def test_second_failure_stops_without_recursive_repair(self):
        route = AsyncMock(return_value=self.repaired())
        with patch('src.core.execution_recovery.execute_script', AsyncMock(side_effect=self.failure)) as execute:
            with self.assertRaises(RetrievalFailure):
                await recover_failed_execution(**self.kwargs, orchestrate=route)
        route.assert_awaited_once()
        execute.assert_awaited_once()
        self.assertTrue(self.result.execution_repair_attempted)
        self.assertFalse(self.result.success)
        self.assertEqual(self.result.outcome, 'fail')

    async def test_supervisor_failure_preserves_explanation_and_does_not_execute(self):
        repaired = self.repaired()
        repaired.success = False
        repaired.outcome = 'fail'
        repaired.user_message = 'The available service cannot provide that relationship.'
        with patch('src.core.execution_recovery.execute_script', AsyncMock()) as execute:
            with self.assertRaisesRegex(RetrievalFailure, 'cannot provide that relationship'):
                await recover_failed_execution(**self.kwargs, orchestrate=AsyncMock(return_value=repaired))
        execute.assert_not_awaited()
        self.assertFalse(self.result.success)

    async def test_clarification_is_returned_without_executing_script(self):
        repaired = self.repaired()
        repaired.success = False
        repaired.outcome = 'clarify'
        repaired.user_message = 'The relationship is unavailable. Would you like the remaining details?'
        with patch('src.core.execution_recovery.execute_script', AsyncMock()) as execute:
            response = await recover_failed_execution(**self.kwargs, orchestrate=AsyncMock(return_value=repaired))
        execute.assert_not_awaited()
        self.assertEqual(response['content'], repaired.user_message)
        self.assertEqual(response['metadata']['outcome'], 'clarify')

    async def test_cancellation_prevents_replanning(self):
        route = AsyncMock()
        with self.assertRaises(asyncio.CancelledError):
            await recover_failed_execution(**{**self.kwargs, 'cancellation_check': lambda: True}, orchestrate=route)
        route.assert_not_awaited()

    async def test_repaired_script_still_passes_security_validation(self):
        repaired = self.repaired()
        repaired.script_code = 'eval("blocked")'
        with patch('asyncio.create_subprocess_exec', AsyncMock()) as launch:
            with self.assertRaisesRegex(ValueError, 'security validation'):
                await recover_failed_execution(**self.kwargs, orchestrate=AsyncMock(return_value=repaired))
        launch.assert_not_awaited()

    def test_discovery_gets_failure_even_with_narrow_supervisor_assignment(self):
        self.result.execution_recovery_context = {'failures': self.failure.details}
        self.result.supervisor_decisions = [{'mode': 'delegate', 'target': 'API', 'requested_data': ['relationships']}]
        context = _discovery_assignment(self.result, 'Inventory widgets', 'API')
        self.assertIn('/api/v1/widgets/fixture/links', context)
        self.assertIn('Unsupported relationship', context)
        self.assertEqual(recovery_instructions(None), '')


if __name__ == '__main__':
    unittest.main()
