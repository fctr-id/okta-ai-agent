"""Offline execution contracts retained during prompt simplification."""
import ast
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from pydantic_ai.usage import RunUsage
from pydantic_ai.exceptions import UsageLimitExceeded


class AgentExecutionContractTests(unittest.IsolatedAsyncioTestCase):
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
        api.assert_not_awaited()
        supervisor.assert_not_awaited()
        synthesis.assert_not_awaited()
        self.assertTrue(any(
            call.args[0] == "step_end" and call.args[1]["title"] == "Execution Stopped"
            for call in events.await_args_list
        ))

    async def test_api_discovery_returns_model_output_and_usage(self):
        from src.core.agents import api_discovery_agent as api
        expected = api.APIDiscoveryResult(success=False, error="Fixture permission denied")
        usage = RunUsage(input_tokens=123, output_tokens=12, requests=1)
        run = AsyncMock(return_value=SimpleNamespace(output=expected, usage=lambda: usage))
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
        run = AsyncMock(return_value=SimpleNamespace(output=output, usage=lambda: RunUsage(requests=1)))
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

    def test_generated_script_security_rejects_commands_and_unlisted_clients(self):
        from src.utils.security_config import validate_generated_code
        for code in (
            'import subprocess\nsubprocess.run(["whoami"])',
            'import requests\nrequests.get("https://untrusted.invalid")',
            'eval("1+1")', 'open("secrets.txt").read()',
        ):
            with self.subTest(code=code):
                self.assertFalse(validate_generated_code(code).is_valid)


if __name__ == "__main__":
    unittest.main()
