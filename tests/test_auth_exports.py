"""Small offline regressions for local login, logout, and CSV output."""
import csv
import io
import runpy
import unittest
from datetime import datetime, timedelta, timezone

from tests.security_support import CHECKS, ROOT
import httpx
from fastapi import FastAPI, Request, Response
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from src.core.okta.sync.models import AuthUser
from src.core.okta.sync.operations import DatabaseOperations
from src.core.security.password_hasher import hash_password
from src.core.security.cookies import set_auth_cookie, get_auth_cookie


class AuthChecks(unittest.IsolatedAsyncioTestCase):
    async def test_persisted_lockout_expires_and_success_resets_attempts(self):
        engine = create_async_engine(f"sqlite+aiosqlite:///{(CHECKS / 'lockouts.db').as_posix()}")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        operations = object.__new__(DatabaseOperations)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(AuthUser.__table__.create)
            async with sessions() as session:
                session.add(AuthUser(username='fixture', password_hash=hash_password('fixture-password'),
                    login_attempts=5, locked_until=datetime.now(timezone.utc) + timedelta(minutes=5)))
                await session.commit()
            async with sessions() as session:
                user = await operations.get_auth_user(session, 'fixture')
                self.assertIsNone(user.locked_until.tzinfo)  # SQLite DateTime round-trip.
                self.assertIsNone(await operations.verify_user_credentials(session, 'fixture', 'fixture-password'))
                user.locked_until = datetime.now(timezone.utc) - timedelta(minutes=5)
                user.login_attempts = 0
                await session.commit()
            async with sessions() as session:
                self.assertIsNone(await operations.verify_user_credentials(session, 'fixture', 'incorrect'))
                user = await operations.get_auth_user(session, 'fixture')
                self.assertEqual(user.login_attempts, 1)
            async with sessions() as session:
                user = await operations.verify_user_credentials(session, 'fixture', 'fixture-password')
                self.assertIsNotNone(user)
                self.assertEqual(user.login_attempts, 0)
                self.assertIsNone(user.locked_until)
        finally:
            await engine.dispose()

    async def test_post_logout_removes_cookie_and_is_idempotent(self):
        from src.api.routers.auth import router
        app = FastAPI()
        app.include_router(router)

        @app.get('/fixture-cookie')
        async def fixture_cookie(response: Response):
            set_auth_cookie(response, 'synthetic-cookie')
            return {'ok': True}

        @app.get('/fixture-cookie-status')
        async def cookie_status(request: Request):
            return {'present': get_auth_cookie(request) is not None}

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://fixture.test') as client:
            await client.get('/fixture-cookie')
            self.assertTrue((await client.get('/fixture-cookie-status')).json()['present'])
            response = await client.post('/api/auth/logout')
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()['success'])
            self.assertIn('Max-Age=0', response.headers['set-cookie'])
            self.assertFalse((await client.get('/fixture-cookie-status')).json()['present'])
            self.assertEqual((await client.post('/api/auth/logout')).status_code, 200)


class CsvChecks(unittest.TestCase):
    def test_slack_exports_headers_and_values_as_literals(self):
        from src.integrations.slack.formatters import results_to_csv_string
        result = results_to_csv_string([{'value': ' =literal', 'number': -4}],
                                       [{'value': 'value', 'text': '=heading'}, 'number'])
        rows = list(csv.reader(io.StringIO(result)))
        self.assertEqual(rows, [["'=heading", 'number'], ["' =literal", '-4']])

    def test_headers_dict_values_and_positional_rows_remain_literal(self):
        save = runpy.run_path(str(ROOT / 'scripts' / 'tako-cli.py'))['save_results_to_csv']
        values = ['=literal', ' +literal', '\t@literal', '-literal', -4, None, 'ordinary,"text"\nline']
        headers = ['=heading', 'b', 'c', 'd', 'e', 'f', 'g']
        row = dict(zip(headers, values))
        expected = ["'=literal", "' +literal", "'\t@literal", "'-literal", '-4', '', 'ordinary,"text"\nline']
        for name, data in [('dict', [row]), ('rows', [values])]:
            path = save({'data': data}, name, CHECKS / 'csv')
            self.assertIsNotNone(path)
            with path.open(newline='', encoding='utf-8') as source:
                rows = list(csv.reader(source))
            self.assertEqual(rows[-1], expected)
            if name == 'dict':
                self.assertEqual(rows[0], ["'=heading", *headers[1:]])
        self.assertEqual(row, dict(zip(headers, values)))
