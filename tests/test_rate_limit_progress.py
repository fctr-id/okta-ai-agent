"""Offline provider retry and public progress checks; no tenant/model calls."""
from tests.security_support import CHECKS
import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx2
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from src.core.models.rate_limit_progress import ProviderProgressModel
from src.core.models.rate_limit_progress import (
    model_request_progress, observe_http_client, observe_http_provider, observe_bedrock_client, progress_callback,
)
from src.core.models.rate_limit_progress import public_model_progress
from src.core.retry_status import retry_after_seconds


class RateLimitChecks(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.events = []

        async def collect(kind, event):
            self.events.append(public_model_progress(event.get('details')))

        self.token = progress_callback.set(collect)

    async def asyncTearDown(self):
        progress_callback.reset(self.token)

    async def call_openai(self, succeed):
        attempts = []

        def respond(request):
            attempts.append(request)
            if len(attempts) == 1 or not succeed:
                return httpx2.Response(429, headers={'retry-after': '0.01'},
                    json={'error': {'message': 'PRIVATE_ERROR', 'type': 'rate_limit_error'}})
            return httpx2.Response(200, json={'id': 'fixture', 'object': 'chat.completion',
                'created': 0, 'model': 'fixture', 'choices': [
                    {'index': 0, 'message': {'role': 'assistant', 'content': 'ok'}, 'finish_reason': 'stop'}]})

        async with observe_http_client(httpx2.AsyncClient(transport=httpx2.MockTransport(respond))) as client:
            provider = OpenAIProvider(base_url='https://models.invalid/v1', api_key='PRIVATE_KEY', http_client=client)
            model = ProviderProgressModel(OpenAIChatModel('fixture', provider=provider))
            await model.request([ModelRequest(parts=[UserPromptPart('PRIVATE_PROMPT')])], None, ModelRequestParameters())
        return attempts

    async def test_sdk_retry_is_visible_and_success_clears_wait(self):
        attempts = await self.call_openai(True)
        self.assertEqual(len(attempts), 2)
        self.assertEqual([e['details']['status'] for e in self.events], ['retry_wait', 'retrying', 'success'])
        self.assertEqual(self.events[0]['details']['retry_after_seconds'], 1)
        self.assertEqual(self.events[0]['details']['label'], 'AI provider')
        self.assertNotIn('PRIVATE', json.dumps(self.events))

    async def test_application_model_factory_observes_agent_requests(self):
        from pydantic_ai import Agent
        from src.core.models.model_picker import ModelConfig, ModelType
        calls = []
        def respond(request):
            calls.append(request)
            if len(calls) == 1:
                return httpx2.Response(429, headers={'retry-after': '0.01'},
                    json={'error': {'message': 'PRIVATE', 'type': 'rate_limit_error'}})
            return httpx2.Response(200, json={'id': 'fixture', 'object': 'chat.completion',
                'created': 0, 'model': 'fixture', 'choices': [
                    {'index': 0, 'message': {'role': 'assistant', 'content': 'ok'}, 'finish_reason': 'stop'}]})
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
            with patch.dict('os.environ', {'AI_PROVIDER': 'openai_compatible',
                    'OPENAI_COMPATIBLE_BASE_URL': 'https://models.invalid/v1',
                    'OPENAI_COMPATIBLE_TOKEN': 'fixture', 'OPENAI_COMPATIBLE_REASONING_MODEL': 'fixture'}), \
                 patch('src.core.models.model_picker.create_http_client_with_ssl_config', return_value=client):
                model = ModelConfig.get_model(ModelType.REASONING)
                answer = await Agent(model).run('Synthetic question')
        self.assertEqual(answer.output, 'ok')
        self.assertEqual(len(calls), 2)
        self.assertEqual([event['details']['status'] for event in self.events], ['retry_wait', 'retrying', 'success'])

    async def test_broken_progress_consumer_does_not_change_the_model_result(self):
        async def disconnected(*args):
            raise RuntimeError('Synthetic closed consumer')
        token = progress_callback.set(disconnected)
        try:
            calls = await self.call_openai(True)
            self.assertEqual(len(calls), 2)
        finally:
            progress_callback.reset(token)

    async def test_exhausted_sdk_retries_finish_failed(self):
        with self.assertRaises(Exception):
            await self.call_openai(False)
        self.assertEqual(self.events[-1]['details']['status'], 'failed')
        self.assertEqual(sum(e['details']['status'] == 'retrying' for e in self.events), 2)

    async def test_google_sdk_retry_uses_same_progress_contract(self):
        from google.genai.types import HttpRetryOptions
        from pydantic_ai.models.google import GoogleModel
        from pydantic_ai.providers.google import GoogleProvider
        attempts = []
        def respond(request):
            attempts.append(request)
            if len(attempts) == 1:
                return httpx2.Response(429, json={'error': {'code': 429, 'message': 'PRIVATE', 'status': 'RESOURCE_EXHAUSTED'}})
            return httpx2.Response(200, json={'candidates': [
                {'content': {'parts': [{'text': 'ok'}], 'role': 'model'}, 'finishReason': 'STOP'}]})
        async with observe_http_client(httpx2.AsyncClient(transport=httpx2.MockTransport(respond))) as client:
            provider = GoogleProvider(api_key='fixture', http_client=client,
                retry_options=HttpRetryOptions(attempts=2, initial_delay=0.01, max_delay=0.02))
            model = ProviderProgressModel(GoogleModel('gemini-2.5-flash', provider=provider))
            await model.request([ModelRequest(parts=[UserPromptPart('test')])], None, ModelRequestParameters())
        self.assertEqual([e['details']['status'] for e in self.events], ['retry_wait', 'retrying', 'success'])
        self.assertNotIn('retry_after_seconds', self.events[0]['details'])

    async def test_native_provider_hooks_survive_client_close_and_reopen(self):
        from pydantic_ai.providers.google import GoogleProvider
        from pydantic_ai.providers.google_cloud import GoogleCloudProvider
        from pydantic_ai.providers.azure import AzureProvider
        from pydantic_ai.providers.anthropic import AnthropicProvider
        from google.auth.credentials import AnonymousCredentials
        providers = [OpenAIProvider(api_key='fixture'), GoogleProvider(api_key='fixture'),
            GoogleCloudProvider(credentials=AnonymousCredentials(), project='fixture', location='global'),
            AzureProvider(api_key='fixture', azure_endpoint='https://fixture.openai.azure.com/openai/v1/'),
            AnthropicProvider(api_key='fixture')]
        for provider in providers:
            client = provider._own_http_client
            timeout = client.timeout
            observe_http_provider(provider)
            async with provider:
                self.assertIs(provider._own_http_client, client)
                self.assertEqual(client.timeout, timeout)
                self.assertEqual(len(client.event_hooks['response']), 1)
            self.assertTrue(client.is_closed)
            async with provider:
                self.assertIsNot(provider._own_http_client, client)
                self.assertEqual(len(provider._own_http_client.event_hooks['response']), 1)

    async def test_cancelled_wait_finishes_and_other_query_has_no_events(self):
        from src.core.models.rate_limit_progress import _on_response
        with self.assertRaises(asyncio.CancelledError):
            async with model_request_progress():
                await _on_response(httpx2.Response(429))
                raise asyncio.CancelledError()
        self.assertEqual([e['details']['status'] for e in self.events], ['retry_wait', 'cancelled'])
        self.assertNotIn('retry_after_seconds', self.events[0]['details'])
        async with model_request_progress():
            await _on_response(httpx2.Response(200))
        self.assertEqual(len(self.events), 2)

    async def test_bedrock_throttling_is_reported_from_sdk_thread(self):
        from botocore.hooks import HierarchicalEmitter
        emitter = HierarchicalEmitter()
        observe_bedrock_client(SimpleNamespace(meta=SimpleNamespace(events=emitter)))
        async with model_request_progress():
            await asyncio.to_thread(emitter.emit, 'needs-retry.bedrock-runtime.Converse',
                response=(SimpleNamespace(status_code=400, headers={}),
                          {'Error': {'Code': 'ThrottlingException', 'Message': 'PRIVATE'}}))
            decisions = await asyncio.to_thread(emitter.emit, 'before-send.bedrock-runtime.Converse')
            self.assertTrue(all(result is None for _, result in decisions))
        self.assertEqual([e['details']['status'] for e in self.events], ['retry_wait', 'retrying', 'success'])
        self.assertNotIn('PRIVATE', json.dumps(self.events))

    def test_retry_hints_are_bounded_and_support_http_dates(self):
        self.assertEqual(retry_after_seconds({'retry-after-ms': '1500'}), 2)
        self.assertIsNone(retry_after_seconds({'retry-after': 'NaN'}))
        self.assertIsNone(retry_after_seconds({'retry-after': 'PRIVATE'}))
        self.assertIsNone(retry_after_seconds({'retry-after': '99999999'}))
        future = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=20))
        self.assertIn(retry_after_seconds({'retry-after': future}), (19, 20))

    async def test_parallel_requests_have_separate_progress_ids(self):
        from src.core.models.rate_limit_progress import _on_response
        async def call():
            async with model_request_progress():
                await _on_response(httpx2.Response(429))
                await asyncio.sleep(0)
        await asyncio.gather(call(), call())
        ids = {e['details']['request_id'] for e in self.events}
        self.assertEqual(len(ids), 2)
        for request_id in ids:
            self.assertEqual([e['details']['status'] for e in self.events
                              if e['details']['request_id'] == request_id], ['retry_wait', 'success'])
