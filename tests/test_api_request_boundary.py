"""Offline trusted-client checks; no real network or credentials."""
from tests import security_support
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

from tests.test_retrieval_outcomes import client_fixture


class APIRequestBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_disallowed_requests_stop_before_authentication_and_transport(self):
        cases = [
            ('/api/v1/users', 'POST', None),
            ('/api/v1/users', 'GET', {}),
            ('https://other.invalid/api/v1/users', 'GET', None),
            ('http://fixture.invalid/api/v1/users', 'GET', None),
            ('https://fixture.invalid:444/api/v1/users', 'GET', None),
            ('//other.invalid/api/v1/users', 'GET', None),
            ('https://user@fixture.invalid/api/v1/users', 'GET', None),
            ('/api/v1/users#fragment', 'GET', None),
        ]
        for endpoint, method, body in cases:
            with self.subTest(endpoint=endpoint, method=method):
                client = client_fixture()
                client._get_auth_headers = AsyncMock()
                with patch('aiohttp.ClientSession') as session:
                    with self.assertRaises(ValueError):
                        await client._single_request(endpoint, method, body=body)
                client._get_auth_headers.assert_not_awaited()
                session.assert_not_called()

    async def test_same_tenant_urls_and_pagination_remain_readable_without_redirects(self):
        for endpoint in ('/api/v1/users', 'api/v1/users',
                         'https://fixture.invalid/api/v1/users?after=sample'):
            client = client_fixture()
            client._get_auth_headers = AsyncMock(return_value={'Authorization': 'synthetic'})
            headers = MagicMock()
            headers.get.return_value = None
            headers.getall.return_value = []
            response = SimpleNamespace(status=200, headers=headers)
            client._process_response = AsyncMock(return_value={'status': 'success', 'data': []})
            session = MagicMock()
            session.request.return_value.__aenter__ = AsyncMock(return_value=response)
            manager = MagicMock()
            manager.__aenter__ = AsyncMock(return_value=session)
            with patch('aiohttp.ClientSession', return_value=manager):
                result = await client._single_request(endpoint, 'GET', params={'limit': 3})
            self.assertEqual(result['status'], 'success')
            kwargs = session.request.call_args.kwargs
            self.assertFalse(kwargs['allow_redirects'])
            self.assertEqual(kwargs['method'], 'GET')
            self.assertTrue(kwargs['url'].startswith('https://fixture.invalid/api/v1/users?'))
            self.assertTrue(kwargs['url'].endswith('limit=3'))
