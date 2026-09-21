"""Exercise the synthesis output contract with an offline Pydantic AI model."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pydantic_ai.models.test import TestModel


class SynthesisMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def test_metadata_uses_existing_synthesis_response_and_records_model(self):
        with patch('src.core.models.model_picker.ModelConfig.get_model', return_value=TestModel()):
            from src.core.agents.synthesis_agent import synthesis_agent, execute_synthesis, SynthesisDeps
        output = {
            'success': True, 'script_code': "print('QUERY RESULTS')\nprint('[]')",
            'display_type': 'table',
            'procedure_metadata': {
                'purpose': 'List user emails', 'entities': ['user'], 'scope': 'All statuses',
                'parameters': [], 'classification': 'generic', 'contains_sensitive_literals': False,
            },
        }
        with TemporaryDirectory() as tmp:
            artifact = Path(tmp) / 'artifacts.json'
            artifact.write_text(json.dumps([{'sql_query': 'SELECT email FROM users'}]))
            with synthesis_agent.override(model=TestModel(custom_output_args=output)):
                result, usage = await execute_synthesis('List user emails', SynthesisDeps('fixture', artifact))
        self.assertTrue(result.success)
        self.assertEqual(result.procedure_metadata.entities, ['user'])
        self.assertEqual(usage.requests, 1)
        self.assertEqual(result._response_models, ['test'])
        self.assertNotIn('_response_models', result.model_dump())


if __name__ == '__main__':
    unittest.main()
