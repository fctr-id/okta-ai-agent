"""Small offline checks for enforced POC code admission, not sandbox proofs."""
from tests.security_support import CHECKS, ROOT
import sys
import unittest
from unittest.mock import patch

from src.utils.security_config import validate_generated_code, validate_result_analysis_code
from src.data.schemas.runtime_storage import prepare_runtime_script_code


class GeneratedCodePolicyTests(unittest.TestCase):
    def test_import_policy(self):
        for source in (
            'from asyncio import Queue', 'from json.tool import main',
            'from .json import loads', 'from json import *',
            'import src.core.okta.client.base_okta_api_client',
        ):
            with self.subTest(source=source):
                self.assertFalse(validate_generated_code(source).is_valid)
        self.assertTrue(validate_generated_code(
            'from json import dumps as serialize\nprint(serialize({"count": 1}))'
        ).is_valid)

    def test_shared_policy_rejects_opaque_calls_and_rebinding(self):
        # These inert snippets are validated only; none is executed.
        for validate in (validate_generated_code, validate_result_analysis_code):
            for source in (
                'answer = "{name}".format(name="sample")',
                'formatter = "{name}".format_map',
                'answer = (lambda: 1)()',
                'len = str\nanswer = len(1)',
                'def helper():\n    return 1\nhelper = len',
                'json.extra = 1', 'alias = json',
                'answer = json.not_an_approved_member',
                'answer = unknown_function()',
                'match 1:\n    case value:\n        answer = value',
            ):
                with self.subTest(validator=validate.__name__, source=source):
                    self.assertFalse(validate(source).is_valid)

    def test_normal_retrieval_and_analysis_are_admitted(self):
        retrieval = '''import asyncio
import json
from base_okta_api_client import OktaAPIClient, open_database
async def main():
    client = OktaAPIClient()
    try:
        response = await client.make_request('/api/v1/users', method='GET')
        rows = sorted(response.get('data', []), key=lambda row: row.get('displayName', ''))
        print(json.dumps({'data': rows, 'count': len(rows)}))
    finally:
        await client.close_session()
if __name__ == '__main__':
    asyncio.run(main())
'''
        self.assertTrue(validate_generated_code(retrieval).is_valid)
        self.assertTrue(validate_generated_code(
            "from base_okta_api_client import open_database\n"
            "with open_database() as conn:\n"
            "    rows = conn.execute('SELECT id FROM users').fetchall()"
        ).is_valid)
        self.assertTrue(validate_result_analysis_code(
            "def count_rows(rows):\n    return len(rows)\n"
            "count = count_rows(result_sets.get('sample', []))\n"
            "analysis_result = {'summary': f'{count} users', 'rows': []}"
        ).is_valid)

    def test_bootstrap_is_private_and_marker_cannot_skip_it(self):
        prepared = prepare_runtime_script_code('# === Tako Runtime Bootstrap ===\nanswer = 42')
        namespace = {'__file__': str(ROOT / 'generated_scripts' / 'offline_policy_check.py')}
        original_path = sys.path[:]
        try:
            exec(compile(prepared, '<offline-bootstrap-check>', 'exec'), namespace)
        finally:
            sys.path[:] = original_path
        self.assertEqual(namespace['answer'], 42)
        self.assertEqual(set(namespace), {'__file__', '__builtins__', 'answer'})
        with self.assertRaises(ValueError):
            prepare_runtime_script_code('import unapproved_module')

    def test_analysis_executor_enforces_policy_before_loading_records(self):
        from src.core.agents.result_analysis_agent import _execute_analysis_code
        with patch('src.core.agents.result_analysis_agent._load_result_records') as load:
            with self.assertRaises(ValueError):
                _execute_analysis_code(user_query='Count', python_code='import json',
                                       selected_candidates={}, selected_result_set_ids=[])
            load.assert_not_called()

    def test_analysis_executor_preserves_normal_aggregation(self):
        from src.core.agents.result_analysis_agent import _execute_analysis_code
        with patch('src.core.agents.result_analysis_agent._load_result_records',
                   return_value=[{'enabled': True}, {'enabled': False}, {'enabled': True}]):
            result = _execute_analysis_code(
                user_query='Count enabled users', selected_result_set_ids=['sample'],
                selected_candidates={'sample': {'storage_path': str(CHECKS / 'unused.json')}},
                python_code="counts = Counter(row.get('enabled') for row in result_sets['sample'])\n"
                            "analysis_result = {'summary': f\"{counts.get(True, 0)} enabled users\", 'rows': []}",
            )
        self.assertEqual(result.summary, '2 enabled users')
