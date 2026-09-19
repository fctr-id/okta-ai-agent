"""Relationship reconciliation and status regressions against isolated SQLite files."""
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.okta.client.client import OktaClientWrapper
from src.core.okta.sync.engine import SyncOrchestrator
from src.core.okta.sync.models import (
    Base, Application, Device, Group, Policy, User, UserDevice,
    SyncHistory, SyncStatus, group_application_assignments,
)
from src.core.okta.sync.operations import DatabaseOperations, _build_async_engine


class SyncRelationshipTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = _build_async_engine('sqlite+aiosqlite:///' +
                                          str(Path(self.temp.name) / 'sync.db'))
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.db = DatabaseOperations.__new__(DatabaseOperations)
        self.db.engine = self.engine
        self.db.SessionLocal = async_sessionmaker(self.engine, expire_on_commit=False)
        self.sync = SyncOrchestrator('fixture', self.db, asyncio.Event())
        async with self.db.get_session() as session:
            session.add_all([
                User(tenant_id='fixture', okta_id='u1'),
                User(tenant_id='fixture', okta_id='u2'),
                Group(tenant_id='fixture', okta_id='g1'),
                Policy(tenant_id='fixture', okta_id='p1'),
                Device(tenant_id='fixture', okta_id='d1'),
                User(tenant_id='other', okta_id='other-user'),
                Device(tenant_id='other', okta_id='other-device'),
            ])
            await session.flush()
            session.add_all([
                Application(tenant_id='fixture', okta_id='a1', policy_id='p1'),
                Application(tenant_id='fixture', okta_id='a2'),
                UserDevice(tenant_id='fixture', user_okta_id='u1', device_okta_id='d1'),
                UserDevice(tenant_id='other', user_okta_id='other-user', device_okta_id='other-device'),
            ])
            await session.flush()
            await session.execute(group_application_assignments.insert().values(
                tenant_id='fixture', group_okta_id='g1', application_okta_id='a1', assignment_id='old'))

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temp.cleanup()

    async def group_apps(self):
        async with self.db.get_session() as session:
            return (await session.scalars(select(group_application_assignments.c.application_okta_id))).all()

    async def device_users(self, device='d1'):
        async with self.db.get_session() as session:
            return (await session.scalars(select(UserDevice.user_okta_id).where(
                UserDevice.device_okta_id == device))).all()

    async def app_policy(self):
        async with self.db.get_session() as session:
            return await session.scalar(select(Application.policy_id).where(Application.okta_id == 'a1'))

    async def group_batch(self, row):
        async with self.db.get_session() as session:
            await self.sync._process_batch_to_db(session, Group, [row])
        await self.sync._flush_group_relationships()

    async def test_unfetched_group_assignments_are_preserved(self):
        rows = OktaClientWrapper._transform_groups_batch(None, [{'id': 'g1', 'profile': {'name': 'Group'}}])
        await self.group_batch(rows[0])
        self.assertEqual(await self.group_apps(), ['a1'])
        async with self.db.get_session() as session:
            await self.sync._process_group_relationships(session, {'okta_id': 'g1'})
        self.assertEqual(await self.group_apps(), ['a1'])

    async def test_confirmed_group_assignments_replace_and_clear(self):
        await self.group_batch({'okta_id': 'g1', 'applications': [{
            'group_okta_id': 'g1', 'application_okta_id': 'a2', 'assignment_id': 'new'}]})
        self.assertEqual(await self.group_apps(), ['a2'])
        await self.group_batch({'okta_id': 'g1', 'applications': []})
        self.assertEqual(await self.group_apps(), [])

    async def test_device_transform_distinguishes_unfetched_and_empty(self):
        rows = OktaClientWrapper._transform_device_with_embedded_users(None, [
            {'id': 'd1'}, {'id': 'd2', '_embedded': {'users': []}}])
        self.assertNotIn('user_devices', rows[0])
        self.assertEqual(rows[1]['user_devices'], [])

    async def test_device_transform_rejects_incomplete_relationships(self):
        rows = OktaClientWrapper._transform_device_with_embedded_users(None, [
            {'id': 'd1', '_embedded': {'users': [{'user': {}}]}}])
        # The caller's cardinality check rejects this batch instead of treating it as empty.
        self.assertEqual(rows, [])

    async def test_device_snapshot_reconciles_removed_users_and_preserves_other_tenant(self):
        async with self.db.get_session() as session:
            await self.db.bulk_upsert(session, Device, [{'okta_id': 'd1'}], 'fixture')
        self.assertEqual(await self.device_users(), ['u1'])
        async with self.db.get_session() as session:
            await self.db.bulk_upsert(session, Device, [{'okta_id': 'd1', 'user_devices': [
                {'user_okta_id': 'u2', 'management_status': 'MANAGED'}]}], 'fixture')
        self.assertEqual(await self.device_users(), ['u2'])
        async with self.db.get_session() as session:
            await self.db.bulk_upsert(session, Device, [{'okta_id': 'd1', 'user_devices': []}], 'fixture')
        self.assertEqual(await self.device_users(), [])
        self.assertEqual(await self.device_users('other-device'), ['other-user'])

    async def test_failed_device_batch_rolls_back_rows_relationships_and_progress(self):
        async with self.db.get_session() as session:
            session.add(SyncHistory(tenant_id='fixture', status=SyncStatus.RUNNING,
                                    start_time=datetime.now()))

        async def fetch(processor_func):
            await processor_func([
                {'okta_id': 'd1', 'user_devices': []},
                {'okta_id': 'new-device', 'user_devices': [{'user_okta_id': 'u2'}]},
                {'okta_id': 'bad-device', 'invalid_column': True},
            ])

        with self.assertRaises(TypeError):
            await self.sync.sync_model_streaming(Device, fetch)
        self.assertEqual(await self.device_users(), ['u1'])
        async with self.db.get_session() as session:
            self.assertIsNone(await session.scalar(select(Device).where(Device.okta_id == 'new-device')))
            self.assertEqual((await session.scalar(select(SyncHistory))).devices_count, 0)
            self.assertEqual((await session.execute(text('PRAGMA foreign_key_check'))).all(), [])

    async def policy_batch(self, row):
        async with self.db.get_session() as session:
            await self.sync._process_batch_to_db(session, Application, [row])
        await self.sync._flush_application_policy_links()

    async def test_application_policy_missing_preserves_but_explicit_null_clears(self):
        await self.policy_batch({'okta_id': 'a1'})
        self.assertEqual(await self.app_policy(), 'p1')
        await self.policy_batch({'okta_id': 'a1', 'policy_id': None})
        self.assertIsNone(await self.app_policy())
        await self.policy_batch({'okta_id': 'a1', 'policy_id': 'p1'})
        self.assertEqual(await self.app_policy(), 'p1')

    async def test_unresolved_policy_fails_and_rolls_back_staged_changes(self):
        async with self.db.get_session() as session:
            await self.sync._process_batch_to_db(session, Application, [
                {'okta_id': 'a1', 'policy_id': None},
                {'okta_id': 'a2', 'policy_id': 'not-fetched'},
            ])
        with self.assertRaisesRegex(RuntimeError, 'missing'):
            await self.sync._flush_application_policy_links()
        self.assertEqual(await self.app_policy(), 'p1')

    async def status(self):
        from src.api.routers import sync as router
        with patch.object(router, 'get_tenant_id', return_value='fixture'), \
             patch.object(router, 'get_db_ops', AsyncMock(return_value=self.db)):
            async with self.db.get_session() as session:
                return await router.get_sync_status(session=session, current_user='fixture')

    async def test_first_failed_sync_is_visible_without_prior_success(self):
        async with self.db.get_session() as session:
            session.add(SyncHistory(tenant_id='fixture', status=SyncStatus.FAILED,
                                    start_time=datetime.now(), error_details='fetch failed'))
        status = await self.status()
        self.assertEqual(status.status, 'failed')
        self.assertEqual(status.error_details, 'fetch failed')
        self.assertIsNone(status.last_successful_sync_time)

    async def test_attempt_status_and_last_successful_snapshot_are_independent(self):
        now = datetime.now()
        async with self.db.get_session() as session:
            session.add(SyncHistory(tenant_id='fixture', status=SyncStatus.COMPLETED,
                start_time=now - timedelta(minutes=2), end_time=now - timedelta(minutes=1), users_count=320))
            attempt = SyncHistory(tenant_id='fixture', status=SyncStatus.FAILED,
                start_time=now, end_time=now, error_details='fetch failed', users_count=0)
            session.add(attempt)
            session.add(SyncHistory(tenant_id='other', status=SyncStatus.COMPLETED,
                start_time=now + timedelta(minutes=1), users_count=999))
        for state in (SyncStatus.FAILED, SyncStatus.CANCELED, SyncStatus.RUNNING, SyncStatus.COMPLETED):
            async with self.db.get_session() as session:
                row = await session.get(SyncHistory, attempt.id)
                row.status = state
                row.error_details = 'fetch failed' if state == SyncStatus.FAILED else None
                row.users_count = 42
            status = await self.status()
            self.assertEqual(status.status, state.value)
            self.assertEqual(status.sync_id, attempt.id)
            self.assertEqual(status.entity_counts['users'],
                             42 if state in (SyncStatus.RUNNING, SyncStatus.COMPLETED) else 320)
            self.assertEqual(status.last_successful_sync_time,
                             now if state == SyncStatus.COMPLETED else now - timedelta(minutes=1))
            self.assertEqual(status.error_details, 'fetch failed' if state == SyncStatus.FAILED else None)


if __name__ == '__main__':
    unittest.main()
