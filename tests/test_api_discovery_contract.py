"""Offline checks for the execution and output contracts retained by the prompt."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from pydantic_ai import ModelRetry


CODE = '''async def fetch_users():
    response = await okta_client.make_request(
        endpoint="/api/v1/users", method="GET", max_results=3
    )
    if response["status"] != "success":
        return response
    data = response["data"]
    return data[:3] if isinstance(data, list) else data
'''


class APIDiscoveryContractTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {"AI_PROVIDER": "openai", "OPENAI_API_KEY": "test-only",
                                    "OKTA_API_TOKEN": "test-only", "OKTA_CLIENT_ORGURL": "https://fixture.okta.com"}):
            from src.core.agents import api_discovery_agent as module
            from src.core.security.network_security import NetworkSecurityValidator
        # Application imports can reload .env; set the fixture domain afterwards.
        with patch.dict(os.environ, {"OKTA_CLIENT_ORGURL": "https://fixture.okta.com"}):
            cls.network = NetworkSecurityValidator()
        cls.module = module

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.client = SimpleNamespace(base_url="https://fixture.okta.com", test_mode=False,
            make_request=AsyncMock(return_value={"status": "success", "data": [
                {"id": "fixture-user", "profile": {"login": "fixture@fixture.invalid"}}
            ]}))
        self.deps = self.module.APIDiscoveryDeps(
            correlation_id="contract-test", artifacts_file=Path(self.tmp.name) / "artifacts.json",
            okta_client=self.client, endpoints=[],
        )
        self.tools = self.module.create_api_toolset(self.deps).tools
        network = patch.object(self.module, "validate_request", self.network.validate_request_data)
        network.start()
        self.addCleanup(network.stop)

    async def test_validated_get_preserves_data_and_saves_exact_code(self):
        result = await self.tools["execute_test_query"].function(CODE, "Fetch users")
        self.assertTrue(result.metadata["success"])
        self.assertTrue(self.client.test_mode)
        self.assertEqual(json.loads(result.content), self.client.make_request.return_value["data"])
        self.assertFalse(self.deps.artifacts, "Execution must not silently replace explicit saving")
        await self.tools["save_artifact"].function(
            "users_sample", "api_results", result.content, api_code=CODE, notes="Synthetic discovery sample"
        )
        self.assertEqual(self.deps.artifacts[0]["api_code"], CODE)
        self.assertTrue(self.deps.artifacts_file.exists())
        output = self.module.APIDiscoveryResult(success=True, api_data_retrieved=True, found_data=["users"])
        self.module.validate_api_discovery_output(SimpleNamespace(deps=self.deps), output)

    async def test_truncation_is_logged_without_changing_tool_content(self):
        data = [{"id": "private-id", "description": "private-value" * 500}]
        self.client.make_request.return_value = {"status": "success", "data": data}
        with patch.object(self.module.logger, "info") as log:
            result = await self.tools["execute_test_query"].function(CODE, "Fixture truncation")
        serialized = json.dumps(data, separators=(',', ':'))
        self.assertEqual(result.content, serialized[:4000])
        messages = [c.args[0] for c in log.call_args_list if "API test diagnostic: " in c.args[0]]
        diagnostic = json.loads(messages[0].split("API test diagnostic: ", 1)[1])
        self.assertTrue(diagnostic["truncated"])
        self.assertEqual(diagnostic["response_chars"], len(serialized))
        self.assertEqual(diagnostic["returned_chars"], 4000)
        self.assertNotIn("private", messages[0])

    async def test_explicit_function_call_is_executed_once_regardless_of_result_name(self):
        for ending in (
            "", "results = await fetch_users()", "result = await fetch_users()",
            "payload = await fetch_users()", "payload: list = await fetch_users()",
            "await fetch_users()",
        ):
            with self.subTest(ending=ending):
                self.client.make_request.reset_mock()
                result = await self.tools["execute_test_query"].function(CODE + "\n" + ending, "Fixture")
                self.assertTrue(result.metadata["success"], result.content)
                self.client.make_request.assert_awaited_once()
                self.assertEqual(json.loads(result.content), self.client.make_request.return_value["data"])

    async def test_nested_result_assignment_does_not_suppress_function_execution(self):
        code = CODE.replace("response = await", "results = await").replace('response[', 'results[')
        result = await self.tools["execute_test_query"].function(code, "Fixture")
        self.assertTrue(result.metadata["success"], result.content)
        self.client.make_request.assert_awaited_once()

    async def test_unsupported_top_level_await_is_rejected_before_requests(self):
        code = CODE + "\nif True:\n    payload = await fetch_users()\n"
        result = await self.tools["execute_test_query"].function(code, "Fixture")
        self.assertFalse(result.metadata["success"])
        self.client.make_request.assert_not_awaited()

    async def test_dangerous_code_is_rejected_before_client_execution(self):
        for code in (
            'import subprocess\nasync def fetch():\n    return subprocess.run(["whoami"])',
            'async def fetch():\n    return open("secrets.txt").read()',
            'async def fetch():\n    return eval("1 + 1")',
            'import requests\nasync def fetch():\n    return requests.get("https://untrusted.invalid")',
        ):
            with self.subTest(code=code):
                result = await self.tools["execute_test_query"].function(code, "Blocked operation")
                self.assertFalse(result.metadata["success"])
                self.assertTrue(result.metadata["security_error"])
        self.client.make_request.assert_not_awaited()
        self.assertFalse(self.deps.artifacts)

    async def test_api_error_payload_is_not_converted_to_empty_data(self):
        error = {"status": "error", "status_code": 403, "error": "Access forbidden"}
        self.client.make_request.return_value = error
        result = await self.tools["execute_test_query"].function(CODE, "Fetch users")
        self.assertEqual(json.loads(result.content), error)
        self.assertFalse(self.deps.artifacts)

    async def test_discovery_streams_actual_calls_and_keeps_retries_separate(self):
        tool_events, progress_events = [], []
        self.deps.tool_call_callback = AsyncMock(side_effect=tool_events.append)
        self.deps.progress_callback = AsyncMock(side_effect=progress_events.append)
        self.deps.endpoints = [{"method": "GET", "url_pattern": "/api/v1/users",
                                "entity": "user", "operation": "list"}]
        for _ in range(2):
            await self.tools["execute_test_query"].function(CODE, "Fetch users")
        self.assertNotEqual(tool_events[0]["test_id"], tool_events[1]["test_id"])
        for index, tool_event in enumerate(tool_events):
            events = [event["details"] for event in progress_events[index * 2:index * 2 + 2]]
            self.assertEqual([e["status"] for e in events], ["running", "success"])
            self.assertTrue(all(e["test_id"] == tool_event["test_id"] for e in events))
            self.assertTrue(all(e["operation"] == "user.list" for e in events))

    async def test_blocked_code_does_not_report_endpoint_execution(self):
        self.deps.progress_callback = AsyncMock()
        await self.tools["execute_test_query"].function(
            'async def fetch():\n    return open("secrets.txt").read()', "Blocked")
        self.deps.progress_callback.assert_not_awaited()

    def test_success_requires_saved_evidence_and_failure_requires_explanation(self):
        for output in (
            self.module.APIDiscoveryResult(success=True, api_data_retrieved=True, found_data=["users"]),
            self.module.APIDiscoveryResult(success=True),
            self.module.APIDiscoveryResult(success=False),
        ):
            with self.subTest(output=output), self.assertRaises(ModelRetry):
                self.module.validate_api_discovery_output(SimpleNamespace(deps=self.deps), output)

    def test_network_validator_keeps_get_only_and_tenant_boundaries(self):
        url = "https://fixture.okta.com/api/v1/users"
        self.assertTrue(self.network.validate_request_data("GET", url).is_allowed)
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                self.assertFalse(self.network.validate_request_data(method, url).is_allowed)
        for url in ("https://untrusted.invalid/api/v1/users", "http://fixture.okta.com/api/v1/users"):
            with self.subTest(url=url):
                self.assertFalse(self.network.validate_request_data("GET", url).is_allowed)

    def test_result_analysis_retains_its_stricter_restrictions(self):
        from src.utils.security_config import validate_result_analysis_code
        self.assertTrue(validate_result_analysis_code('analysis_result = {"summary": "No rows", "rows": []}').is_valid)
        for code in (
            'import json\nanalysis_result = {"summary": "test"}',
            'analysis_result = {"answer": open("secrets.txt").read()}',
            'analysis_result = {"answer": client.make_request("/api/v1/users")}',
        ):
            with self.subTest(code=code):
                self.assertFalse(validate_result_analysis_code(code).is_valid)


if __name__ == "__main__":
    unittest.main()
