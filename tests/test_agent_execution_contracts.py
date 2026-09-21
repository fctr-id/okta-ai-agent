"""Offline execution contracts retained during prompt simplification."""
import ast
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
import warnings
from unittest.mock import AsyncMock, patch

from pydantic_ai.usage import RunUsage
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.models.test import TestModel


class AgentExecutionContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Agent construction must not depend on a developer's selected provider.
        provider_config = patch('src.core.models.model_picker.ModelConfig.get_model', return_value=TestModel())
        provider_config.start()
        self.addCleanup(provider_config.stop)
        self.warning_context = warnings.catch_warnings()
        self.warning_context.__enter__()
        self.addCleanup(self.warning_context.__exit__, None, None, None)
        warnings.filterwarnings('error', message=r'.*AgentRunResult\.usage.*', category=UserWarning)

    async def test_sql_discovery_returns_usage_property(self):
        from src.core.agents import sql_discovery_agent as sql
        expected = sql.SQLDiscoveryResult(success=True, found_data=['fixture'], reasoning='Fixture evidence')
        usage = RunUsage(input_tokens=123, output_tokens=45, requests=2)
        run = AsyncMock(return_value=SimpleNamespace(output=expected, usage=usage))
        with TemporaryDirectory() as tmp, patch.object(sql, 'sql_discovery_agent', SimpleNamespace(run=run)):
            deps = sql.SQLDiscoveryDeps(correlation_id='contract', artifacts_file=Path(tmp) / 'artifacts.json',
                                       okta_client=None, cancellation_check=lambda: False)
            output, actual_usage = await sql.execute_sql_discovery('Fixture query', deps)
        self.assertIs(output, expected)
        self.assertIs(actual_usage, usage)

    async def test_both_supervisor_phases_return_usage_property(self):
        from src.core.agents import supervisor_agent as supervisor
        from src.data.schemas.artifact_manifest import DelegationResult
        usage = RunUsage(input_tokens=123, output_tokens=45, requests=2)
        initial = supervisor.SupervisorDecision(mode='delegate', target='SQL', reasoning='Fixture discovery')
        complete = supervisor.SupervisorDecision(mode='complete', target='SYNTHESIS', reasoning='Fixture complete')
        latest = DelegationResult(success=True, source_specialist='sql', summary='Fixture evidence',
                                  result_mode='synthesis_ready', artifact_keys=['fixture'])
        run = AsyncMock(side_effect=[SimpleNamespace(output=initial, usage=usage),
                                    SimpleNamespace(output=complete, usage=usage)])
        with TemporaryDirectory() as tmp, \
             patch.object(supervisor, '_load_supervisor_conversation_context', AsyncMock(return_value={})), \
             patch.object(supervisor, 'supervisor_agent', SimpleNamespace(run=run)):
            decision, actual_usage = await supervisor.supervise_query('Fixture query', correlation_id='contract')
            self.assertEqual(decision.mode, 'delegate')
            self.assertIs(actual_usage, usage)
            decision, actual_usage = await supervisor.supervise_next_step(
                'Fixture query', correlation_id='contract', artifacts_file=Path(tmp) / 'artifacts.json',
                delegation_results=[], latest_delegation_result=latest)
            self.assertEqual(decision.mode, 'complete')
            self.assertIs(actual_usage, usage)

    async def test_result_analysis_returns_usage_property(self):
        from src.core.agents import result_analysis_agent as analysis
        usage = RunUsage(input_tokens=123, output_tokens=45, requests=2)
        plan = analysis.ResultAnalysisPlan(mode='request_specialist', reasoning='Fixture needs evidence',
                                            needs_specialists=['sql'])
        run = AsyncMock(return_value=SimpleNamespace(output=plan, usage=usage))
        with TemporaryDirectory() as tmp, \
             patch.object(analysis, '_load_candidate_result_sets', return_value=[{'result_set_id': 'fixture'}]), \
             patch.object(analysis, '_load_conversation_context', AsyncMock(return_value={})), \
             patch.object(analysis, 'result_analysis_agent', SimpleNamespace(run=run)):
            result, actual_usage = await analysis.execute_result_analysis(
                'Fixture follow-up', correlation_id='contract', artifacts_file=Path(tmp) / 'artifacts.json')
        self.assertTrue(result.success)
        self.assertEqual(result.needs_specialists, ['sql'])
        self.assertIs(actual_usage, usage)

    async def test_discovery_preserves_usage_limit_exception_type(self):
        from src.core.agents import api_discovery_agent as api
        from src.core.agents import sql_discovery_agent as sql
        for module, agent_name, execute, deps_type in (
            (sql, "sql_discovery_agent", sql.execute_sql_discovery, sql.SQLDiscoveryDeps),
            (api, "api_discovery_agent", api.execute_api_discovery, api.APIDiscoveryDeps),
        ):
            with self.subTest(agent=agent_name), TemporaryDirectory() as tmp:
                error = UsageLimitExceeded("Fixture budget exhausted without legacy wording")
                run = AsyncMock(side_effect=error)
                with patch.object(module, agent_name, SimpleNamespace(run=run)):
                    deps = deps_type(
                        correlation_id="contract", artifacts_file=Path(tmp) / "artifacts.json",
                        okta_client=None, cancellation_check=lambda: False,
                    )
                    with self.assertRaises(UsageLimitExceeded) as raised:
                        await execute("Fixture request", deps)
                self.assertIs(raised.exception, error)

    async def test_multistep_discovery_receives_each_current_assignment(self):
        from src.core.agents import orchestrator as orch

        def delegate(target, task):
            return orch.SupervisorDecision(mode="delegate", target=target, requested_data=[task], reasoning=task)

        steps = [delegate("API", "Fetch the starting population"),
                 delegate("SQL", "Select matching records from the starting population"),
                 delegate("API", "Enrich only the database selection")]
        api_results = [(orch.APIDiscoveryResult(success=True, found_data=["population"], needs_sql=["selection"]), RunUsage()),
                       (orch.APIDiscoveryResult(success=True, found_data=["enrichment"]), RunUsage())]
        sql_result = orch.SQLDiscoveryResult(success=True, found_data=["selection"], needs_api=["enrichment"], reasoning="Selection saved")
        next_steps = [(step, RunUsage()) for step in steps[1:]] + [
            (orch.SupervisorDecision(mode="complete", target="SYNTHESIS", reasoning="All steps done"), RunUsage())]
        query = "Retrieve a population, select it in the database, then enrich that selection."
        with TemporaryDirectory() as tmp, \
             patch.object(orch, "execute_api_discovery", AsyncMock(side_effect=api_results)) as api, \
             patch.object(orch, "execute_sql_discovery", AsyncMock(return_value=(sql_result, RunUsage()))) as sql, \
             patch.object(orch, "supervise_next_step", AsyncMock(side_effect=next_steps)):
            result = orch.OrchestratorResult()
            result.supervisor_decisions.append(steps[0].model_dump())
            await orch._run_discovery_loop(
                result=result, phase="API", initial_sql_usage=None, user_query=query,
                correlation_id="contract", artifacts_file=Path(tmp) / "artifacts.json",
                okta_client=None, cancellation_check=lambda: False,
                aggregator=orch.EventAggregator(None), endpoints_list=[],
                db_runtime_summary={"usable_for_sql": True}, special_tool_capabilities={},
                global_tool_calls_counter=0, max_tool_calls=30)
        self.assertEqual(result.phases_executed, ["api", "sql", "api"])
        for call, step in zip([api.await_args_list[0], sql.await_args, api.await_args_list[1]], steps):
            prompt = call.args[0]
            self.assertIn(query, prompt)
            assignment = prompt.split("Current supervisor assignment:\n", 1)[1]
            self.assertIn(step.requested_data[0], assignment)
            for other in steps:
                if other is not step:
                    self.assertNotIn(other.requested_data[0], assignment)

    async def test_sql_budget_exhaustion_stops_without_api_fallback(self):
        from src.core.agents import orchestrator as orch
        from src.core.agents import sql_discovery_agent as sql
        error = UsageLimitExceeded(
            "The next tool call(s) would exceed the tool_calls_limit of 8 (tool_calls=9)."
        )
        decision = orch.SupervisorDecision(mode="delegate", target="SQL", reasoning="Fixture SQL request")
        events = AsyncMock()
        with TemporaryDirectory() as tmp, \
             patch.object(orch, "_load_api_endpoints", return_value=[]), \
             patch.object(orch, "get_database_runtime_summary", return_value={"usable_for_sql": True}), \
             patch.object(orch, "get_special_tool_capability_summary", return_value={}), \
             patch.object(orch, "_hydrate_session_result_set_context", AsyncMock(return_value=0)), \
             patch.object(orch, "supervise_query", AsyncMock(return_value=(decision, RunUsage()))), \
             patch.object(sql, "sql_discovery_agent", SimpleNamespace(run=AsyncMock(side_effect=error))), \
             patch.object(orch, "execute_api_discovery", AsyncMock()) as api, \
             patch.object(orch, "supervise_next_step", AsyncMock()) as supervisor, \
             patch.object(orch, "_run_synthesis_phase", AsyncMock()) as synthesis:
            result = await orch.execute_multi_agent_query(
                "Fixture request", "contract", Path(tmp) / "artifacts.json",
                okta_client=None, cancellation_check=lambda: False, event_callback=events,
            )
        self.assertFalse(result.success)
        self.assertEqual(result.error, str(error))
        self.assertEqual(result.outcome, "fail")
        self.assertEqual(result.user_message, orch.BUDGET_EXHAUSTED_USER_MESSAGE)
        self.assertNotIn("tool_calls_limit", result.user_message)
        api.assert_not_awaited()
        supervisor.assert_not_awaited()
        synthesis.assert_not_awaited()
        self.assertTrue(any(
            call.args[0] == "step_end" and call.args[1]["title"] == "Execution Stopped"
            and call.args[1]["text"] == orch.BUDGET_EXHAUSTED_USER_MESSAGE
            for call in events.await_args_list
        ))

    async def test_supervisor_budget_is_not_hidden_by_fallback_or_previous_error(self):
        from src.core.agents import supervisor_agent as supervisor
        from src.data.schemas.artifact_manifest import DelegationResult

        error = UsageLimitExceeded("The next request would exceed the request_limit of 2")
        latest = DelegationResult(success=False, source_specialist="analysis", result_mode="failed",
                                  summary="Analysis failed", error="Invalid derivation_kind: projection")
        with TemporaryDirectory() as tmp, \
             patch.object(supervisor, "_load_supervisor_conversation_context", AsyncMock(return_value={})), \
             patch.object(supervisor, "supervisor_agent", SimpleNamespace(run=AsyncMock(side_effect=error))), \
             patch.object(supervisor, "_fallback_after_delegation_decision") as fallback:
            with self.assertRaises(UsageLimitExceeded) as initial:
                await supervisor.supervise_query("List users", correlation_id="contract")
            with self.assertRaises(UsageLimitExceeded) as followup:
                await supervisor.supervise_next_step(
                    "Show emails", correlation_id="contract", artifacts_file=Path(tmp) / "artifacts.json",
                    delegation_results=[], latest_delegation_result=latest)
        self.assertIs(initial.exception, error)
        self.assertIs(followup.exception, error)
        fallback.assert_not_called()

    async def test_analysis_and_synthesis_preserve_budget_exhaustion(self):
        from src.core.agents import result_analysis_agent as analysis
        from src.core.agents import synthesis_agent as synthesis

        error = UsageLimitExceeded("The next request would exceed the request_limit of 2")
        with TemporaryDirectory() as tmp:
            artifact_file = Path(tmp) / "artifacts.json"
            artifact_file.write_text("[]", encoding="utf-8")
            with patch.object(analysis, "_load_candidate_result_sets", return_value=[{"result_set_id": "fixture"}]), \
                 patch.object(analysis, "_load_conversation_context", AsyncMock(return_value={})), \
                 patch.object(analysis, "result_analysis_agent", SimpleNamespace(run=AsyncMock(side_effect=error))):
                with self.assertRaises(UsageLimitExceeded) as raised:
                    await analysis.execute_result_analysis("Show emails", correlation_id="contract",
                                                           artifacts_file=artifact_file)
                self.assertIs(raised.exception, error)
            with patch.object(synthesis, "synthesis_agent", SimpleNamespace(run=AsyncMock(side_effect=error))):
                with self.assertRaises(UsageLimitExceeded) as raised:
                    await synthesis.execute_synthesis("Show emails", synthesis.SynthesisDeps(
                        correlation_id="contract", artifacts_file=artifact_file))
                self.assertIs(raised.exception, error)

    async def test_initial_supervisor_budget_returns_clear_error_without_discovery(self):
        from src.core.agents import orchestrator as orch
        from src.core.agents import supervisor_agent as supervisor

        error = UsageLimitExceeded("The next request would exceed the request_limit of 2")
        events = AsyncMock()
        with TemporaryDirectory() as tmp, \
             patch.object(orch, "_load_api_endpoints", return_value=[]), \
             patch.object(orch, "get_database_runtime_summary", return_value={"usable_for_sql": True}), \
             patch.object(orch, "get_special_tool_capability_summary", return_value={}), \
             patch.object(orch, "_hydrate_session_result_set_context", AsyncMock(return_value=0)), \
             patch.object(supervisor, "_load_supervisor_conversation_context", AsyncMock(return_value={})), \
             patch.object(supervisor, "supervisor_agent", SimpleNamespace(run=AsyncMock(side_effect=error))), \
             patch.object(orch, "execute_sql_discovery", AsyncMock()) as sql:
            result = await orch.execute_multi_agent_query(
                "List users", "contract", Path(tmp) / "artifacts.json", okta_client=None,
                cancellation_check=lambda: False, event_callback=events)
        self.assertFalse(result.success)
        self.assertEqual(result.error, str(error))
        self.assertEqual(result.user_message, orch.BUDGET_EXHAUSTED_USER_MESSAGE)
        sql.assert_not_awaited()
        self.assertTrue(any(call.args[0] == "step_end"
                            and call.args[1]["text"] == orch.BUDGET_EXHAUSTED_USER_MESSAGE
                            for call in events.await_args_list))

    def test_processing_limits_do_not_mislabel_provider_rate_limits(self):
        from src.core.agents.orchestrator import _is_processing_limit

        for error in (UsageLimitExceeded("Token allowance exhausted"),
                      RuntimeError("Global tool call limit exceeded (30/30)."),
                      "SQL test query limit exceeded (10/10).",
                      "API test query limit exceeded (10/10)."):
            self.assertTrue(_is_processing_limit(error))
        self.assertFalse(_is_processing_limit(RuntimeError("Okta rate limit exceeded (429)")))
        self.assertFalse(_is_processing_limit("Provider rate limit exceeded"))

    async def test_api_discovery_returns_model_output_and_usage(self):
        from src.core.agents import api_discovery_agent as api
        expected = api.APIDiscoveryResult(success=False, error="Fixture permission denied")
        usage = RunUsage(input_tokens=123, output_tokens=12, requests=1)
        run = AsyncMock(return_value=SimpleNamespace(output=expected, usage=usage))
        with TemporaryDirectory() as tmp, patch.object(api, "api_discovery_agent", SimpleNamespace(run=run)):
            deps = api.APIDiscoveryDeps(correlation_id="contract", artifacts_file=Path(tmp) / "artifacts.json")
            output, actual_usage = await api.execute_api_discovery("List users using API only", deps)
        self.assertIs(output, expected)
        self.assertEqual(actual_usage, usage)
        run.assert_awaited_once()

    async def test_api_discovery_reports_provider_failure(self):
        from src.core.agents import api_discovery_agent as api
        run = AsyncMock(side_effect=RuntimeError("Fixture provider unavailable"))
        with TemporaryDirectory() as tmp, patch.object(api, "api_discovery_agent", SimpleNamespace(run=run)):
            deps = api.APIDiscoveryDeps(correlation_id="contract", artifacts_file=Path(tmp) / "artifacts.json")
            output, usage = await api.execute_api_discovery("List users", deps)
        self.assertFalse(output.success)
        self.assertIn("Fixture provider unavailable", output.error)
        self.assertIsNone(usage)

    async def test_synthesis_preserves_valid_filter_string_escapes(self):
        from src.core.agents import synthesis_agent as synthesis
        code = 'params = {"filter": "signOnMode eq \\"SAML_2_0\\""}\nprint("QUERY RESULTS")\n'
        ast.parse(code)
        output = synthesis.SynthesisResult(success=True, script_code=code)
        synthesis.validate_synthesis_output(output)
        run = AsyncMock(return_value=SimpleNamespace(output=output, usage=RunUsage(requests=1)))
        with TemporaryDirectory() as tmp, patch.object(synthesis, "synthesis_agent", SimpleNamespace(run=run)):
            artifact_file = Path(tmp) / "artifacts.json"
            artifact_file.write_text("[]", encoding="utf-8")
            actual, _ = await synthesis.execute_synthesis("Find SAML apps", synthesis.SynthesisDeps(
                correlation_id="contract", artifacts_file=artifact_file))
        self.assertEqual(actual.script_code, code)
        tree = ast.parse(actual.script_code)
        self.assertEqual(ast.literal_eval(tree.body[0].value), {"filter": 'signOnMode eq "SAML_2_0"'})

    def test_sql_allows_reads_and_rejects_writes(self):
        from src.core.security.sql_security_validator import validate_user_sql
        for query in ("SELECT okta_id FROM users", "WITH u AS (SELECT okta_id FROM users) SELECT * FROM u"):
            with self.subTest(query=query):
                self.assertTrue(validate_user_sql(query)[0])
        for query in (
            "DELETE FROM users", "UPDATE users SET status = 'ACTIVE'", "DROP TABLE users",
            "INSERT INTO users(okta_id) VALUES ('fake')", "PRAGMA writable_schema = ON",
            "SELECT * FROM users; DELETE FROM users", "ATTACH DATABASE 'other.db' AS other",
        ):
            with self.subTest(query=query):
                self.assertFalse(validate_user_sql(query)[0])

    def test_synthesis_rejects_dynamic_import_and_accepts_normal_stderr(self):
        from pydantic_ai import ModelRetry
        from src.core.agents import synthesis_agent as synthesis

        bad_code = "print('QUERY RESULTS')\nprint('Error', file=__import__('sys').stderr)\n"
        with self.assertRaisesRegex(ModelRetry, "failed security validation") as raised:
            synthesis.validate_synthesis_output(synthesis.SynthesisResult(success=True, script_code=bad_code))
        self.assertIn("__import__", str(raised.exception))
        self.assertIn("file=sys.stderr", str(raised.exception))

        good_code = "import sys\nprint('QUERY RESULTS')\nprint('Error', file=sys.stderr)\n"
        output = synthesis.SynthesisResult(success=True, script_code=good_code)
        self.assertIs(synthesis.validate_synthesis_output(output), output)

    async def test_synthesis_security_feedback_retries_once_and_accepts_correction(self):
        from pydantic_ai.messages import ModelResponse, RetryPromptPart, ToolCallPart
        from pydantic_ai.models.function import FunctionModel
        from src.core.agents import synthesis_agent as synthesis

        bad_code = "print('QUERY RESULTS')\nprint('Error', file=__import__('sys').stderr)\n"
        good_code = "import sys\nprint('QUERY RESULTS')\nprint('Error', file=sys.stderr)\n"
        calls = []

        def model(messages, info):
            calls.append(messages)
            if len(calls) == 2:
                feedback = [part.content for message in messages for part in message.parts
                            if isinstance(part, RetryPromptPart)]
                self.assertTrue(any("failed security validation" in str(item) for item in feedback))
            code = bad_code if len(calls) == 1 else good_code
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,
                                                    {"success": True, "script_code": code})])

        with synthesis.synthesis_agent.override(model=FunctionModel(model)):
            result = await synthesis.synthesis_agent.run("Generate a fixture script",
                                                        usage_limits=synthesis.SYNTHESIS_USAGE_LIMITS)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result.output.script_code, good_code)

    async def test_synthesis_stops_when_security_correction_still_fails(self):
        from pydantic_ai.exceptions import UnexpectedModelBehavior
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        from pydantic_ai.models.function import FunctionModel
        from src.core.agents import synthesis_agent as synthesis

        calls = []

        def model(messages, info):
            calls.append(messages)
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
                "success": True,
                "script_code": "print('QUERY RESULTS')\n__import__('sys')\n",
            })])

        with synthesis.synthesis_agent.override(model=FunctionModel(model)):
            with self.assertRaises(UnexpectedModelBehavior):
                await synthesis.synthesis_agent.run("Generate a fixture script",
                                                    usage_limits=synthesis.SYNTHESIS_USAGE_LIMITS)
        self.assertEqual(len(calls), 2)

    def test_generated_script_security_rejects_commands_and_unlisted_clients(self):
        from src.utils.security_config import validate_generated_code
        for code in (
            'import subprocess\nsubprocess.run(["whoami"])',
            'import requests\nrequests.get("https://untrusted.invalid")',
            'eval("1+1")', 'open("secrets.txt").read()',
        ):
            with self.subTest(code=code):
                self.assertFalse(validate_generated_code(code).is_valid)

    def test_generated_script_reraises_fatal_errors_and_runs_cleanup(self):
        from src.utils.security_config import validate_generated_code
        code = '''import sys
try:
    1 / 0
except Exception as error:
    print(str(error), file=sys.stderr)
    raise
finally:
    print("cleanup finished", file=sys.stderr)
'''
        self.assertTrue(validate_generated_code(code).is_valid)
        result = subprocess.run([sys.executable, '-I', '-c', code],
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('ZeroDivisionError', result.stderr)
        self.assertIn('cleanup finished', result.stderr)
        self.assertFalse(validate_generated_code('raise SystemExit(1)').is_valid)


if __name__ == "__main__":
    unittest.main()
