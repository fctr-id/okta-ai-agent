"""Offline sync regression tests: incomplete data, progress visibility and batching."""
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from multidict import CIMultiDict

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.core.okta.client.client import OktaClientWrapper, normalize_okta_response
from src.core.okta.sync.engine import SyncOrchestrator
from src.core.okta.sync.models import Base, Group, User, SyncHistory, SyncStatus
from src.core.okta.sync.operations import DatabaseOperations
from src.utils.pagination_limits import _paginate_direct_api


def wrapper():
    client = OktaClientWrapper.__new__(OktaClientWrapper)
    client.cancellation_flag = asyncio.Event()
    client.api_semaphore = asyncio.Semaphore(3)
    client.RATE_LIMIT_DELAY = 0
    return client


class SyncClientTests(unittest.IsolatedAsyncioTestCase):
    def test_normalization_preserves_exhausted_rate_limit_and_next_page_errors(self):
        error = {'errorCode': 'E0000047'}
        for response in ((None, None, error), (None, error)):
            self.assertIs(normalize_okta_response(response)[1], error)

    async def test_sdk_session_entered_and_closed_on_failure(self):
        client = wrapper()
        client.config = {}
        sdk = SimpleNamespace(__aenter__=AsyncMock(), __aexit__=AsyncMock())
        with patch('src.core.okta.client.client.OktaClient', return_value=sdk):
            with self.assertRaisesRegex(ValueError, 'fixture'):
                async with client:
                    raise ValueError('fixture')
        sdk.__aenter__.assert_awaited_once()
        sdk.__aexit__.assert_awaited_once()
        self.assertIsNone(client.client)

    async def test_initial_failure_does_not_publish_empty_batch(self):
        client = wrapper()
        process = AsyncMock()
        with self.assertRaises(RuntimeError):
            await client._paginate(AsyncMock(return_value=(None, None, '429')),
                                   {}, lambda rows: rows, process)
        process.assert_not_awaited()

    async def test_batches_publish_before_next_page_and_next_page_failure_raises(self):
        client = wrapper()
        sizes = []

        async def process(rows):
            sizes.append(len(rows))

        async def next_page():
            self.assertEqual(sizes, [50, 50, 20])
            return None, 'page failed'

        page = SimpleNamespace(has_next=lambda: True, next=next_page)
        with self.assertRaisesRegex(RuntimeError, 'page failed'):
            await client._paginate(AsyncMock(return_value=(list(range(120)), page, None)),
                                   {}, lambda rows: rows, process)

    async def test_complete_empty_result_is_valid(self):
        self.assertEqual(await wrapper()._paginate(
            AsyncMock(return_value=([], None, None)), {}, lambda rows: rows), [])

    async def test_failed_transform_does_not_publish_partial_batch(self):
        process = AsyncMock()
        for transform, concurrent in ((lambda rows: [], False),
                                       (AsyncMock(side_effect=ValueError('fixture')), True)):
            with self.subTest(concurrent=concurrent):
                with self.assertRaises((RuntimeError, ValueError)):
                    await wrapper()._paginate(AsyncMock(return_value=([1], None, None)),
                                              {}, transform, process, concurrent_transform=concurrent)
        process.assert_not_awaited()

    async def test_cancellation_does_not_return_partial_success(self):
        client = wrapper()

        async def process(rows):
            client.cancellation_flag.set()

        with self.assertRaises(asyncio.CancelledError):
            await client._paginate(AsyncMock(return_value=([1], None, None)),
                                   {}, lambda rows: rows, process)

    async def test_relationship_failures_propagate(self):
        for method, sdk_method in (('get_user_groups', 'list_user_groups'),
                                   ('get_app_users', 'list_application_users'),
                                   ('list_user_factors', 'list_factors')):
            with self.subTest(method=method):
                client = wrapper()
                client.client = SimpleNamespace(**{
                    sdk_method: AsyncMock(return_value=(None, None, '503'))})
                with self.assertRaises(RuntimeError):
                    await getattr(client, method)(['fixture-user'] if method == 'list_user_factors'
                                                  else 'fixture-id')

    async def test_user_enrichment_cannot_hide_relationship_failure(self):
        client = wrapper()
        client.get_user_groups = AsyncMock(side_effect=RuntimeError('groups unavailable'))
        client.list_user_factors = AsyncMock(return_value=[])
        with self.assertRaisesRegex(RuntimeError, 'groups unavailable'):
            await client._process_single_user({'id': 'fixture-user', 'status': 'ACTIVE'})

    async def test_policy_type_failure_prevents_full_reconciliation(self):
        client = wrapper()
        client.client = SimpleNamespace(list_policies=AsyncMock(return_value=(None, None, '403')))
        with self.assertRaises(RuntimeError):
            await client.list_policies(processor_func=AsyncMock())

    async def test_new_authenticator_types_use_sdk_transport_without_enum_coercion(self):
        client = wrapper()
        payload = [{'id': 'auth-a', 'name': 'Fixture', 'type': 'TAC', 'status': 'ACTIVE'},
                   {'id': 'auth-b', 'name': 'Future', 'type': 'FUTURE_TYPE', 'status': 'ACTIVE'}]
        response = SimpleNamespace(get_body=lambda: payload, has_next=lambda: False)
        executor = SimpleNamespace(create_request=AsyncMock(return_value=({}, None)),
                                   execute=AsyncMock(return_value=(response, None)))
        client.client = SimpleNamespace(get_request_executor=lambda: executor)
        rows = await client.list_authenticators()
        self.assertEqual([row['type'] for row in rows], ['TAC', 'FUTURE_TYPE'])
        executor.execute.assert_awaited_once_with({}, None)

    async def test_authenticator_transport_failure_is_not_empty_data(self):
        client = wrapper()
        executor = SimpleNamespace(create_request=AsyncMock(return_value=({}, None)),
                                   execute=AsyncMock(return_value=(None, '429')))
        client.client = SimpleNamespace(get_request_executor=lambda: executor)
        with self.assertRaises(RuntimeError):
            await client.list_authenticators()

    async def test_later_relationship_pages_cannot_return_partial_results(self):
        for method, sdk_method in (('get_user_groups', 'list_user_groups'),
                                   ('get_app_users', 'list_application_users'),
                                   ('list_user_factors', 'list_factors')):
            with self.subTest(method=method):
                client = wrapper()
                page = SimpleNamespace(has_next=lambda: True,
                                       next=AsyncMock(return_value=(None, '429')))
                client.client = SimpleNamespace(**{sdk_method: AsyncMock(return_value=([], page, None))})
                with self.assertRaises(RuntimeError):
                    await getattr(client, method)(['fixture-user'] if method == 'list_user_factors'
                                                  else 'fixture-id')

    async def test_device_fetch_and_processor_failures_propagate(self):
        for status, transform, process in (
            (429, lambda rows: rows, AsyncMock()),
            (200, lambda rows: [], AsyncMock()),
            (200, lambda rows: rows, AsyncMock(side_effect=RuntimeError('write failed'))),
        ):
            with self.subTest(status=status, transform=transform):
                client = wrapper()
                client.config = {'orgUrl': 'https://fixture.okta.com', 'token': 'fixture'}
                response = SimpleNamespace(status=status, text=AsyncMock(return_value='fixture'),
                    json=AsyncMock(return_value=[{'id': 'device'}]), headers=CIMultiDict())
                request_context = MagicMock()
                request_context.__aenter__ = AsyncMock(return_value=response)
                session = MagicMock()
                session.get.return_value = request_context
                session_context = MagicMock()
                session_context.__aenter__ = AsyncMock(return_value=session)
                with patch('aiohttp.ClientSession', return_value=session_context):
                    with self.assertRaises(RuntimeError):
                        await _paginate_direct_api(client, '/api/v1/devices',
                                                   transform_func=transform, processor_func=process)


class SyncDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine('sqlite+aiosqlite:///' +
                                         str(Path(self.temp.name) / 'sync.db'))
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.db = DatabaseOperations.__new__(DatabaseOperations)
        self.db.engine = self.engine
        self.db.SessionLocal = async_sessionmaker(self.engine, expire_on_commit=False)
        self.sync = SyncOrchestrator('fixture', self.db, asyncio.Event())
        async with self.db.get_session() as session:
            session.add(Group(tenant_id='fixture', okta_id='old', name='Old',
                              last_synced_at=datetime(2000, 1, 1)))
            session.add(Group(tenant_id='other', okta_id='other-group', name='Other'))
            session.add(SyncHistory(tenant_id='fixture', status=SyncStatus.RUNNING,
                                    start_time=datetime.now(timezone.utc)))

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temp.cleanup()

    async def ids(self):
        async with self.db.get_session() as session:
            return set((await session.scalars(select(Group.okta_id))).all())

    async def test_committed_progress_visible_and_failure_preserves_stale_rows(self):
        async def fetch(processor_func):
            await processor_func([{'okta_id': 'new', 'name': 'New'}])
            # A separate connection sees rows AND progress before sync finishes.
            async with self.db.get_session() as reader:
                self.assertEqual((await reader.scalar(select(SyncHistory))).groups_count, 1)
                self.assertIn('new', (await reader.scalars(select(Group.okta_id))).all())
            raise RuntimeError('second page failed')

        with self.assertRaisesRegex(RuntimeError, 'second page'):
            await self.sync.sync_model_streaming(Group, fetch)
        self.assertEqual(await self.ids(), {'old', 'new', 'other-group'})

    async def test_complete_fetch_removes_only_stale_rows_for_current_tenant(self):
        async def fetch(processor_func):
            await processor_func([{'okta_id': 'new', 'name': 'New'}])
        await self.sync.sync_model_streaming(Group, fetch)
        self.assertEqual(await self.ids(), {'new', 'other-group'})

    async def test_cancellation_preserves_stale_rows(self):
        async def fetch(processor_func):
            await processor_func([{'okta_id': 'new', 'name': 'New'}])
            self.sync.cancellation_flag.set()
        with self.assertRaises(asyncio.CancelledError):
            await self.sync.sync_model_streaming(Group, fetch)
        self.assertEqual(await self.ids(), {'old', 'new', 'other-group'})

    async def test_batch_upsert_uses_one_lookup_and_keeps_existing_ids(self):
        statements = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith('SELECT'):
                statements.append(statement)
        event.listen(self.engine.sync_engine, 'before_cursor_execute', capture)
        async with self.db.get_session() as session:
            await self.db.bulk_upsert(session, Group,
                [{'okta_id': 'old', 'name': 'Updated'}, {'okta_id': 'new', 'name': 'New'},
                 {'okta_id': 'new', 'name': 'Latest'}], 'fixture')
        event.remove(self.engine.sync_engine, 'before_cursor_execute', capture)
        self.assertEqual(len(statements), 1)
        async with self.db.get_session() as session:
            rows = (await session.scalars(select(Group).where(Group.tenant_id == 'fixture'))).all()
            self.assertEqual({row.okta_id: row.name for row in rows}, {'old': 'Updated', 'new': 'Latest'})

    async def test_relationship_write_failure_rolls_back_entire_current_batch(self):
        async def fetch(processor_func):
            await processor_func([{'okta_id': 'user-a'}, {'okta_id': 'user-b'}])
        with patch.object(self.sync, '_process_user_relationships',
                          AsyncMock(side_effect=[None, RuntimeError('write failed')])):
            with self.assertRaisesRegex(RuntimeError, 'write failed'):
                await self.sync.sync_model_streaming(User, fetch)
        async with self.db.get_session() as session:
            self.assertEqual((await session.scalars(select(User))).all(), [])
            self.assertEqual((await session.scalar(select(SyncHistory))).users_count, 0)


if __name__ == '__main__':
    unittest.main()
