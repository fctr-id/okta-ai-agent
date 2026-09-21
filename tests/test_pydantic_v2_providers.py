"""Offline provider and HTTP retry contracts for the Pydantic AI v2 migration."""
import json
import os
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx2
from google.oauth2.credentials import Credentials
from pydantic_ai import Agent
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.google_cloud import GoogleCloudProvider
from pydantic_ai.retries import AsyncHTTPX2TenacityTransport
from tenacity import wait_none

from tests.test_azure_model_config import load_model_picker


class ProviderV2Tests(unittest.IsolatedAsyncioTestCase):
    async def test_google_and_vertex_keep_distinct_authentication_and_endpoints(self):
        picker = load_model_picker()
        for provider_name, provider_type, target in (
            ("google", GoogleProvider, "GoogleProvider"),
            ("vertex_ai", GoogleCloudProvider, "GoogleCloudProvider"),
        ):
            with self.subTest(provider=provider_name):
                requests = []

                def respond(request):
                    requests.append(request)
                    return httpx2.Response(200, json={
                        "candidates": [{"content": {"role": "model", "parts": [{"text": "fixture answer"}]},
                                        "finishReason": "STOP"}],
                        "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1,
                                          "totalTokenCount": 2},
                    })

                settings = {
                    "AI_PROVIDER": provider_name, "GOOGLE_API_KEY": "fixture-key",
                    "VERTEX_AI_SERVICE_ACCOUNT_FILE": "fixture-service-account.json",
                    "VERTEX_AI_PROJECT": "fixture-project", "VERTEX_AI_LOCATION": "us-central1",
                }
                async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
                    def provider(**kwargs):
                        return provider_type(**kwargs, http_client=client)

                    with patch.dict(os.environ, settings, clear=True), \
                         patch.object(picker, target, side_effect=provider), \
                         patch.object(picker.os.path, "isfile", return_value=True), \
                         patch("google.oauth2.service_account.Credentials.from_service_account_file",
                               return_value=Credentials(token="fixture-access-token")) as credentials:
                        models = picker.ModelConfig.get_models()
                        for model in models.values():
                            result = await Agent(model).run("fixture request")
                            self.assertEqual(result.output, "fixture answer")
                        if provider_name == "vertex_ai":
                            credentials.assert_called_once_with("fixture-service-account.json",
                                scopes=["https://www.googleapis.com/auth/cloud-platform"])
                        else:
                            credentials.assert_not_called()
                self.assertEqual(len(requests), 2)
                for request in requests:
                    if provider_name == "google":
                        self.assertEqual(request.url.host, "generativelanguage.googleapis.com")
                        self.assertEqual(request.headers["x-goog-api-key"], "fixture-key")
                    else:
                        self.assertEqual(request.url.host, "us-central1-aiplatform.googleapis.com")
                        self.assertIn("projects/fixture-project/locations/us-central1", request.url.path)
                        self.assertNotIn("x-goog-api-key", request.headers)
                        self.assertEqual(request.headers["authorization"], "Bearer fixture-access-token")

    async def test_compatible_models_keep_chat_endpoint_and_custom_headers(self):
        picker = load_model_picker()
        requests = []

        def respond(request):
            requests.append(request)
            return httpx2.Response(200, json={
                "id": "fixture", "object": "chat.completion", "created": 0,
                "model": json.loads(request.content)["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "fixture answer"},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            })

        settings = {"AI_PROVIDER": "openai_compatible", "OPENAI_COMPATIBLE_BASE_URL": "https://fixture.invalid/v1",
                    "OPENAI_COMPATIBLE_TOKEN": "fixture-key", "OPENAI_COMPATIBLE_REASONING_MODEL": "fixture-reason",
                    "OPENAI_COMPATIBLE_CODING_MODEL": "fixture-code", "CUSTOM_HTTP_HEADERS": '{"X-Fixture":"test"}'}
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
            with patch.dict(os.environ, settings, clear=True), \
                 patch.object(picker, "create_http_client_with_ssl_config", return_value=client):
                for model in picker.ModelConfig.get_models().values():
                    self.assertEqual((await Agent(model).run("fixture request")).output, "fixture answer")
        self.assertEqual([json.loads(request.content)["model"] for request in requests],
                         ["fixture-reason", "fixture-code"])
        for request in requests:
            self.assertEqual(str(request.url), "https://fixture.invalid/v1/chat/completions")
            self.assertEqual(request.headers["x-fixture"], "test")
            self.assertEqual(request.headers["authorization"], "Bearer fixture-key")

    async def test_anthropic_sdk_upgrade_executes_a_request(self):
        picker = load_model_picker()
        requests = []

        def respond(request):
            requests.append(request)
            return httpx2.Response(200, json={
                "id": "msg_fixture", "type": "message", "role": "assistant",
                "model": json.loads(request.content)["model"], "content": [{"type": "text", "text": "fixture answer"}],
                "stop_reason": "end_turn", "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1},
            })

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
            def provider(**kwargs):
                return AnthropicProvider(**kwargs, http_client=client)

            with TemporaryDirectory() as home, \
                 patch.dict(os.environ, {"AI_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "fixture-key",
                                         "USERPROFILE": home, "HOME": home}, clear=True), \
                 patch.object(picker, "AnthropicProvider", side_effect=provider):
                for model in picker.ModelConfig.get_models().values():
                    self.assertEqual((await Agent(model).run("fixture request")).output, "fixture answer")
        self.assertEqual(len(requests), 2)
        self.assertTrue(all(request.url.path == "/v1/messages" for request in requests))

    async def test_ssl_client_uses_httpx2_and_retains_timeout(self):
        picker = load_model_picker()
        for verify in ("true", "false"):
            with self.subTest(verify=verify), patch.dict(os.environ, {"VERIFY_SSL": verify}, clear=True):
                async with picker.create_http_client_with_ssl_config() as client:
                    self.assertIsInstance(client, httpx2.AsyncClient)
                    self.assertEqual(client.timeout.read, 60.0)

    async def test_http_retry_transport_retries_429_but_stops_at_budget(self):
        from src.utils import pydantic_retry_transport as retry_module
        for statuses in ([429, 200], [429, 429], [400]):
            with self.subTest(statuses=statuses):
                calls = []

                def respond(request):
                    status = statuses[len(calls)]
                    calls.append(request)
                    return httpx2.Response(status, headers={"Retry-After": "0"})

                def transport(**kwargs):
                    return AsyncHTTPX2TenacityTransport(**kwargs, wrapped=httpx2.MockTransport(respond))

                with patch.object(retry_module, "AsyncHTTPX2TenacityTransport", side_effect=transport), \
                     patch.object(retry_module, "wait_retry_after", return_value=wait_none()):
                    async with retry_module.create_retrying_http_client(max_attempts=2) as client:
                        if statuses == [429, 429]:
                            with self.assertRaises(httpx2.HTTPStatusError):
                                await client.get("https://fixture.invalid/")
                        else:
                            result = await client.get("https://fixture.invalid/")
                            self.assertEqual(result.status_code, statuses[-1])
                self.assertEqual(len(calls), len(statuses))


if __name__ == "__main__":
    unittest.main()
