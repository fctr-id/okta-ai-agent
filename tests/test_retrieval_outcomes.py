"""Offline API fault injection: model-produced tables cannot conceal failures."""
import asyncio
from contextlib import redirect_stderr
import io
import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

from src.core.okta.client.base_okta_api_client import OktaAPIClient
from src.core.retrieval_outcomes import check_retrieval_outcomes, RetrievalFailure, SENTINEL


def client_fixture():
    # No credentials, tenant calls, or configuration needed for this fixture.
    client = object.__new__(OktaAPIClient)
    client.base_url = 'https://fixture.invalid'
    client.test_mode = False
    client.max_pages = 100
    client.timeout = 1
    client.logger = logging.getLogger('retrieval-fixture')
    client._optimize_params = lambda endpoint, params: params
    return client


class OutcomeTests(unittest.IsolatedAsyncioTestCase):
    async def test_failure_classification_survives_swallowed_exceptions(self):
        for response, category, rediscover in [
            ({'http_status': 401}, 'access', False),
            ({'http_status': 403}, 'access', False),
            ({'error_code': 'E0000006'}, 'access', False),
            ({'http_status': 429}, 'transient', False),
            ({'http_status': 503}, 'transient', False),
            ({'error_code': 'TIMEOUT'}, 'transient', False),
            ({'error_code': 'NETWORK_ERROR'}, 'transient', False),
            ({'http_status': 400}, 'request', True),
            ({'http_status': 404}, 'missing', True),
            ({'http_status': 422}, 'request', True),
            ({'error_code': 'PARSE_FAILED'}, 'unknown', True),
        ]:
            with self.subTest(response=response):
                client = client_fixture()
                client._single_request = AsyncMock(return_value={'status': 'error', **response})
                stderr = io.StringIO()
                with redirect_stderr(stderr):
                    try:
                        await client.make_request('/api/v1/users/private-id', params={'filter': 'private-email'})
                    except RuntimeError:
                        pass  # Mimic a generated script ignoring the error.
                with self.assertRaises(RetrievalFailure) as caught:
                    check_retrieval_outcomes(stderr.getvalue())
                self.assertEqual(caught.exception.categories, {category})
                self.assertEqual(caught.exception.rediscover, rediscover)
                diagnostics = [line for line in stderr.getvalue().splitlines() if line.startswith(SENTINEL)]
                self.assertEqual(caught.exception.details[0]['endpoint'], '/api/v1/users/private-id')
                self.assertNotIn('private-email', ''.join(diagnostics))

    async def test_recovery_evidence_excludes_parameters_and_redacts_error_credentials(self):
        client = client_fixture()
        client._make_request = AsyncMock(return_value={'status': 'error', 'http_status': 400,
            'error_code': 'INVALID', 'error': 'Unsupported. Bearer sensitive-token secret=hidden a@example.test https://example.test/?token=x'})
        with redirect_stderr(io.StringIO()) as stderr:
            with self.assertRaises(RuntimeError):
                await client.make_request('/api/v1/things/id?token=query-secret', params={'secret': 'parameter-secret'})
        with self.assertRaises(RetrievalFailure) as caught:
            check_retrieval_outcomes(stderr.getvalue())
        evidence = json.dumps(caught.exception.details)
        for secret in ('sensitive-token', 'hidden', 'a@example.test', 'query-secret', 'parameter-secret'):
            self.assertNotIn(secret, evidence)
        self.assertEqual(caught.exception.details[0]['http_status'], 400)

    async def test_only_identical_success_resolves_a_previous_failure(self):
        for params, resolves in [({'filter': 'status eq "ACTIVE"'}, True),
                                 ({'filter': 'status eq "STAGED"'}, False)]:
            client = client_fixture()
            client._single_request = AsyncMock(side_effect=[
                {'status': 'error', 'http_status': 503}, {'status': 'success', 'data': []}])
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                await client.make_request('/api/v1/users', params={'filter': 'status eq "ACTIVE"'})
                await client.make_request('/api/v1/users', params=params)
            if resolves:
                check_retrieval_outcomes(stderr.getvalue())
            else:
                with self.assertRaises(RetrievalFailure):
                    check_retrieval_outcomes(stderr.getvalue())

    async def test_pagination_failure_and_safety_cap_are_not_success(self):
        first = {'status': 'success', 'data': [{'id': 'one'}],
                 'link_header': '<https://fixture.invalid/api/v1/users?after=one>; rel="next"'}
        for max_pages, following in [(100, {'status': 'error', 'http_status': 503}), (1, None)]:
            client = client_fixture()
            client.max_pages = max_pages
            client._single_request = AsyncMock(side_effect=[first, following])
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                result = await client.make_request('/api/v1/users')
            self.assertEqual(result['status'], 'error')
            with self.assertRaises(RetrievalFailure):
                check_retrieval_outcomes(stderr.getvalue())

    async def test_empty_success_and_explicit_limit_are_valid(self):
        for result, limit in [({'status': 'success', 'data': []}, None),
                              ({'status': 'success', 'data': [1, 2],
                                'link_header': '<https://fixture.invalid/next>; rel="next"'}, 1)]:
            client = client_fixture()
            client._single_request = AsyncMock(return_value=result)
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                response = await client.make_request('/api/v1/users', max_results=limit)
            self.assertEqual(response['status'], 'success')
            check_retrieval_outcomes(stderr.getvalue())

    async def test_system_log_empty_poll_page_is_caught_up_not_truncated(self):
        client = client_fixture()
        client._single_request = AsyncMock(side_effect=[
            {'status': 'success', 'data': [{'id': 'event'}],
             'link_header': '<https://fixture.invalid/api/v1/logs?after=one>; rel="next"'},
            {'status': 'success', 'data': [],
             'link_header': '<https://fixture.invalid/api/v1/logs?after=two>; rel="next"'},
        ])
        with redirect_stderr(io.StringIO()) as stderr:
            result = await client.make_request('/api/v1/logs')
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['data'], [{'id': 'event'}])
        check_retrieval_outcomes(stderr.getvalue())

    async def test_get_retries_are_bounded_and_do_not_retry_writes(self):
        for failure in [503, asyncio.TimeoutError(), aiohttp.ClientConnectionError()]:
            for recovers in [True, False]:
                client = client_fixture()
                client._get_auth_headers = AsyncMock(return_value={})
                client._process_response = AsyncMock(side_effect=lambda response: {
                    'status': 'success' if response.status == 200 else 'error', 'data': []})
                session = MagicMock()
                responses = []
                for attempt in range(3):
                    outcome = 200 if recovers and attempt == 2 else failure
                    manager = MagicMock()
                    if isinstance(outcome, Exception):
                        manager.__aenter__ = AsyncMock(side_effect=outcome)
                    else:
                        headers = MagicMock()
                        headers.get.return_value = None
                        headers.getall.return_value = []
                        manager.__aenter__ = AsyncMock(return_value=SimpleNamespace(status=outcome, headers=headers))
                    responses.append(manager)
                session.request.side_effect = responses
                session_manager = MagicMock()
                session_manager.__aenter__ = AsyncMock(return_value=session)
                with patch('aiohttp.ClientSession', return_value=session_manager), \
                     patch('asyncio.sleep', AsyncMock()) as sleep, redirect_stderr(io.StringIO()) as stderr:
                    response = await client.make_request('/api/v1/users')
                self.assertEqual(session.request.call_count, 3)
                self.assertEqual(sleep.await_count, 2)
                self.assertEqual(response['status'], 'success' if recovers else 'error')
                if recovers:
                    check_retrieval_outcomes(stderr.getvalue())
                else:
                    with self.assertRaises(RetrievalFailure) as caught:
                        check_retrieval_outcomes(stderr.getvalue())
                    self.assertFalse(caught.exception.rediscover)

        client = client_fixture()
        client._get_auth_headers = AsyncMock(return_value={})
        client._process_response = AsyncMock(return_value={'status': 'error'})
        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=SimpleNamespace(status=503, headers={}))
        session.request.side_effect = None
        session.request.return_value = manager
        session.request.reset_mock()
        with patch('aiohttp.ClientSession', return_value=session_manager), patch('asyncio.sleep', AsyncMock()) as sleep:
            await client._single_request('/fixture', 'POST')
        session.request.assert_called_once()
        sleep.assert_not_awaited()

    async def test_real_subprocess_rejects_unflagged_partial_table(self):
        from src.core.script_execution import execute_script
        code = '''import asyncio, json, logging
from base_okta_api_client import OktaAPIClient
async def main():
    client = object.__new__(OktaAPIClient)
    client.base_url = 'https://fixture.invalid'
    client.max_pages = 100
    client.test_mode = False
    client.logger = logging.getLogger('fixture')
    async def request(endpoint, method, params):
        if endpoint.endswith('/good'):
            return {'status': 'success', 'data': [{'key': 'expired'}]}
        return {'status': 'error', 'http_status': 503}
    client._single_request = request
    rows = []
    for app in ('good', 'bad'):
        result = await client.make_request('/api/v1/apps/' + app)
        if result['status'] == 'success':
            rows.extend(result['data'])
    print('QUERY RESULTS')
    print(json.dumps({'display_type': 'table', 'data': rows, 'summary': 'Found one key. One app failed.'}))
asyncio.run(main())
'''
        # This trusted test fixture injects a fake transport with private attributes;
        # generated-code validation has its own existing regression suite.
        with TemporaryDirectory() as tmp, patch('src.utils.security_config.validate_generated_code',
                                                return_value=SimpleNamespace(is_valid=True)):
            with self.assertRaises(RetrievalFailure) as caught:
                await execute_script(code, Path(tmp))
            self.assertEqual(caught.exception.categories, {'transient'})

    def test_unfinished_or_malformed_records_fail_closed(self):
        for event in [{'request': 'a' * 64, 'state': 'started'}, {'unexpected': True}, []]:
            with self.assertRaises(RetrievalFailure):
                check_retrieval_outcomes(SENTINEL + json.dumps(event))


if __name__ == '__main__':
    unittest.main()
