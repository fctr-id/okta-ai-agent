"""Offline Azure v1 request checks; never load application secrets or call Azure."""

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpx
from pydantic_ai import Agent
from pydantic_ai.providers.azure import AzureProvider


def load_model_picker():
    path = Path(__file__).resolve().parents[1] / 'src/core/models/model_picker.py'
    spec = importlib.util.spec_from_file_location('azure_model_picker_test', path)
    module = importlib.util.module_from_spec(spec)
    # Avoid application logging initialization and dotenv reads during import.
    with patch('dotenv.load_dotenv'), patch.dict(
        'sys.modules', {'src.utils.logging': SimpleNamespace(logger=Mock())}
    ):
        spec.loader.exec_module(module)
    return module


class AzureModelConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_roles_use_v1_and_configured_deployments(self):
        picker = load_model_picker()
        requests = []

        def respond(request):
            requests.append(request)
            body = json.loads(request.content)
            return httpx.Response(200, json={
                'id': 'resp_fixture', 'object': 'response', 'created_at': 0,
                'model': body['model'], 'status': 'completed',
                'output': [{
                    'id': 'msg_fixture', 'type': 'message', 'role': 'assistant',
                    'status': 'completed',
                    'content': [{'type': 'output_text', 'text': 'fixture answer',
                                 'annotations': []}],
                }],
                'parallel_tool_calls': True, 'tool_choice': 'auto', 'tools': [],
                'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2},
            })

        settings = {
            'AI_PROVIDER': 'azure_openai',
            'AZURE_OPENAI_ENDPOINT': 'https://fixture.openai.azure.com/openai/v1/',
            'AZURE_OPENAI_KEY': 'fixture-key',
            'AZURE_OPENAI_REASONING_MODEL': 'reasoning-deployment',
            'AZURE_OPENAI_CODING_MODEL': 'coding-deployment',
            # Existing installations may still have this obsolete setting.
            'AZURE_OPENAI_VERSION': '2024-07-08',
        }
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            def provider(**kwargs):
                return AzureProvider(**kwargs, http_client=client)

            with patch.dict(os.environ, settings, clear=True), patch.object(
                picker, 'AzureProvider', side_effect=provider
            ):
                models = picker.ModelConfig.get_models()
                for role in (picker.ModelType.REASONING, picker.ModelType.CODING):
                    result = await Agent(models[role]).run('Synthetic question')
                    self.assertEqual(result.output, 'fixture answer')

        self.assertEqual(len(requests), 2)
        self.assertEqual(
            [json.loads(request.content)['model'] for request in requests],
            ['reasoning-deployment', 'coding-deployment'],
        )
        for request in requests:
            self.assertEqual(request.method, 'POST')
            self.assertEqual(str(request.url),
                             'https://fixture.openai.azure.com/openai/v1/responses')
            self.assertEqual(request.headers['authorization'], 'Bearer fixture-key')


if __name__ == '__main__':
    unittest.main()
