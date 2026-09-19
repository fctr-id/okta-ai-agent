"""Offline compatibility checks for upgraded HTTP, auth, and agent dependencies."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx2
import jwt
from authlib.integrations.httpx_client import AsyncOAuth2Client
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from sse_starlette.sse import EventSourceResponse

from src.core.security import jwt as session_jwt
from src.core.security.oauth2_client import OktaOAuth2Manager
from src.core.security.password_hasher import hash_password, verify_password


class AuthCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    def test_session_jwt_and_password_round_trip(self):
        settings = SimpleNamespace(JWT_SECRET_KEY='fixture-secret-' * 4,
                                   JWT_ALGORITHM='HS256', JWT_AUDIENCE='fixture',
                                   JWT_ISSUER='fixture', JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30)
        with patch.object(session_jwt, 'settings', settings):
            token = session_jwt.create_access_token({'sub': 'fixture-user'})
            self.assertEqual(session_jwt.decode_access_token(token)['sub'], 'fixture-user')
            header, payload, signature = token.split('.')
            tampered = '.'.join((header, payload, ('A' if signature[0] != 'A' else 'B') + signature[1:]))
            self.assertIsNone(session_jwt.decode_access_token(tampered))
        hashed = hash_password('fixture-password')
        self.assertTrue(verify_password(hashed, 'fixture-password'))
        self.assertFalse(verify_password(hashed, 'incorrect'))

    async def test_oauth_manager_signs_valid_assertion_and_caches_token(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
        manager = OktaOAuth2Manager()
        manager.client_id = 'fixture-client'
        manager.token_endpoint = 'https://fixture.okta.com/oauth2/v1/token'
        manager.scopes = 'okta.users.read'
        calls = []

        def respond(request):
            body = parse_qs(request.content.decode())
            claims = jwt.decode(body['client_assertion'][0], key.public_key(),
                                algorithms=['RS256'], audience=manager.token_endpoint)
            self.assertEqual(claims['iss'], manager.client_id)
            self.assertEqual(claims['sub'], manager.client_id)
            self.assertEqual(body['grant_type'], ['client_credentials'])
            calls.append(request)
            return httpx2.Response(200, json={'access_token': 'fixture-token',
                                           'token_type': 'Bearer', 'expires_in': 3600})

        manager.oauth2_client = AsyncOAuth2Client(
            client_id=manager.client_id, client_secret=pem,
            token_endpoint_auth_method='private_key_jwt', transport=httpx2.MockTransport(respond))
        try:
            self.assertEqual(await manager.get_access_token(), 'fixture-token')
            self.assertEqual(await manager.get_access_token(), 'fixture-token')
            self.assertEqual(len(calls), 1)
        finally:
            await manager.oauth2_client.aclose()


class HttpCompatibilityTests(unittest.TestCase):
    def test_forms_uploads_sse_and_static_files(self):
        app = FastAPI()

        @app.post('/form')
        async def form(username: str = Form(), password: str = Form()):
            return {'username': username, 'password_length': len(password)}

        @app.post('/upload')
        async def upload(file: UploadFile = File()):
            return {'size': len(await file.read())}

        @app.get('/events')
        async def events():
            async def generate():
                yield {'event': 'complete', 'data': 'fixture'}
            return EventSourceResponse(generate())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            static = root / 'static'
            static.mkdir()
            (static / 'hello.txt').write_text('fixture')
            (root / 'private.txt').write_text('must-not-be-served')
            app.mount('/static', StaticFiles(directory=static))
            with TestClient(app) as client:
                result = client.post('/form', data={'username': 'fixture', 'password': 'password'})
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json()['username'], 'fixture')
                self.assertEqual(client.post('/form', data={}).status_code, 422)
                self.assertEqual(client.post('/upload', files={'file': ('fixture.txt', b'abc')}).json(), {'size': 3})
                result = client.get('/events')
                self.assertIn('text/event-stream', result.headers['content-type'])
                self.assertIn('event: complete', result.text)
                self.assertEqual(client.get('/static/hello.txt').text, 'fixture')
                for path in ('/static/%2e%2e/private.txt', '/static/..%5cprivate.txt'):
                    self.assertEqual(client.get(path).status_code, 404)


class AgentCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_latest_one_x_executes_tools_and_retains_message_history(self):
        agent = Agent(TestModel(call_tools=['lookup'], custom_output_text='fixture result'))
        calls = []

        @agent.tool_plain
        def lookup() -> str:
            calls.append('lookup')
            return 'fixture evidence'

        result = await agent.run('fixture request')
        self.assertEqual(result.output, 'fixture result')
        self.assertEqual(calls, ['lookup'])
        follow_up = await agent.run('fixture follow-up', message_history=result.all_messages())
        self.assertEqual(follow_up.output, 'fixture result')
        self.assertGreater(len(follow_up.all_messages()), len(result.all_messages()))


if __name__ == '__main__':
    unittest.main()
