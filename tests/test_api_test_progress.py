"""Offline request observation: no model, credentials, or tenant requests."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from src.core.agents.api_test_progress import DiscoveryTestClient

CATALOG = json.loads(Path("src/data/schemas/Okta_API_entitity_endpoint_reference_GET_ONLY.json")
                     .read_text(encoding="utf-8"))["endpoints"]


class RequestProgressTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.events = []
        self.callback = AsyncMock(side_effect=self.events.append)
        self.client = SimpleNamespace(test_mode=True, make_request=AsyncMock(
            return_value={"status": "success", "data": [{"id": "private-id"}]}))
        self.observed = DiscoveryTestClient(self.client, CATALOG, "test-a", self.callback)

    async def test_request_is_unchanged_and_only_catalog_name_is_streamed(self):
        params = {"q": "private-value"}
        result = await self.observed.make_request("/api/v1/apps/private-id/credentials/keys",
                                                  "GET", params=params, max_results=3)
        self.client.make_request.assert_awaited_once_with(
            "/api/v1/apps/private-id/credentials/keys", "GET", params=params, max_results=3)
        self.assertIs(result, self.client.make_request.return_value)
        self.assertTrue(self.observed.test_mode)
        self.assertEqual([e["details"]["status"] for e in self.events], ["running", "success"])
        self.assertEqual(self.events[0]["details"]["operation"], "application_credential.list_keys")
        expected_label = next(e["name"] for e in CATALOG
                              if e["entity"] == "application_credential" and e["operation"] == "list_keys")
        self.assertEqual(self.events[0]["details"]["label"], expected_label)
        self.assertEqual(self.events[1]["details"]["label"], expected_label)
        self.assertNotIn("private", json.dumps(self.events))

    async def test_concurrent_repeated_calls_keep_individual_status(self):
        gate = asyncio.Event()

        async def request(endpoint):
            if endpoint.endswith("one"):
                await gate.wait()
                return {"status": "error", "error": "private-error"}
            gate.set()
            return {"status": "success", "data": []}

        self.client.make_request.side_effect = request
        await asyncio.gather(self.observed.make_request("/api/v1/users/one"),
                             self.observed.make_request("/api/v1/users/two"))
        events = [e["details"] for e in self.events]
        self.assertEqual([e["request_id"] for e in events],
                         ["test-a-request-1", "test-a-request-2", "test-a-request-2", "test-a-request-1"])
        self.assertEqual([e["status"] for e in events], ["running", "running", "empty", "failed"])
        self.assertNotIn("private-error", json.dumps(events))

    async def test_exceptions_and_cancellation_propagate(self):
        for error, status in [(ValueError("private-error"), "failed"),
                              (asyncio.CancelledError(), "cancelled")]:
            with self.subTest(status=status):
                self.events.clear()
                self.client.make_request.side_effect = error
                with self.assertRaises(type(error)):
                    await self.observed.make_request(endpoint="/api/v1/users")
                self.assertEqual(self.events[-1]["details"]["status"], status)
                self.assertNotIn("private-error", json.dumps(self.events))

    async def test_unmatched_path_is_redacted_and_unknown_response_not_success(self):
        self.client.make_request.return_value = {"unexpected": "payload"}
        await self.observed.make_request("/unknown/private-id?q=private-value")
        self.assertEqual(self.events[0]["details"]["operation"], "Uncatalogued endpoint")
        self.assertEqual(self.events[0]["details"]["label"], "Other API request")
        self.assertEqual(self.events[-1]["details"]["status"], "unknown")
        self.assertNotIn("private", json.dumps(self.events))

    async def test_callback_failure_does_not_change_client_result(self):
        self.callback.side_effect = RuntimeError("disconnected")
        result = await self.observed.make_request("/api/v1/users")
        self.assertIs(result, self.client.make_request.return_value)

    async def test_diagnostics_capture_failure_without_payload_or_request_values(self):
        diagnostics = []
        self.observed._diagnostic_callback = diagnostics.append
        response = {"status": "error", "http_status": 403, "error_code": "E0000006",
                    "error": "private-error", "error_id": "private-id"}
        self.client.make_request.return_value = response
        result = await self.observed.make_request("/api/v1/groups/private-id", params={"q": "private-value"})
        self.assertIs(result, response)
        self.assertEqual(diagnostics[0]["outcome"], "failed")
        self.assertEqual(diagnostics[0]["http_status"], 403)
        self.assertEqual(diagnostics[0]["error_code"], "E0000006")
        self.assertEqual(diagnostics[0]["response_chars"], len(json.dumps(response, separators=(',', ':'))))
        self.assertNotIn("private", json.dumps(diagnostics))

    async def test_diagnostic_failure_does_not_change_result(self):
        def fail(_):
            raise RuntimeError("fixture logging failure")
        self.observed._diagnostic_callback = fail
        result = await self.observed.make_request("/api/v1/users")
        self.assertIs(result, self.client.make_request.return_value)


if __name__ == "__main__":
    unittest.main()
