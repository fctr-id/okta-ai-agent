"""Offline candidate persistence tests: no application credentials or model calls."""
import asyncio
from contextlib import asynccontextmanager
import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from src.core.okta.sync.models import Base, QueryProcedure, ConversationSession, ConversationTurn
from src.data.schemas.query_procedure import ProcedureMetadata, executed_fields

settings_stub = ModuleType('src.config.settings')
settings_stub.settings = SimpleNamespace(QUERY_PROCEDURES_ENABLED=True)
operations_stub = ModuleType('src.core.okta.sync.operations')
operations_stub.DatabaseOperations = object
logging_stub = ModuleType('src.utils.logging')
import logging
logging_stub.get_logger = logging.getLogger
spec = importlib.util.spec_from_file_location('procedure_under_test', Path(__file__).resolve().parents[1] / 'src/core/query_procedures.py')
procedures = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {'src.config.settings': settings_stub,
                             'src.core.okta.sync.operations': operations_stub,
                             'src.utils.logging': logging_stub}):
    spec.loader.exec_module(procedures)


class ProcedureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.engine = create_async_engine('sqlite+aiosqlite:///' + (self.root / 'test.db').as_posix())
        async with self.engine.begin() as conn:
            await conn.run_sync(lambda connection: Base.metadata.create_all(connection, tables=[
                ConversationSession.__table__, ConversationTurn.__table__, QueryProcedure.__table__]))
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = SimpleNamespace(get_session=self.factory)
        self.store = procedures.ProcedureStore(self.db, tenant_id='tenant', compatibility='fixture', limit=2)
        async with self.factory() as session:
            for owner, run, tenant in [('alice', 'run1', 'tenant'), ('bob', 'run2', 'tenant'), ('alice', 'run3', 'other')]:
                session.add(ConversationSession(user_id=owner, session_id=run, tenant_id=tenant, source='cli'))
                session.add(ConversationTurn(session_id=run, run_id=run, query_text='List users',
                    tenant_id=tenant, turn_number=1, source='cli'))
            await session.commit()
        self.metadata = ProcedureMetadata(purpose='List users', entities=['user'], scope='All statuses',
            parameters=[], classification='generic', contains_sensitive_literals=False)
        self.evidence = [{'sql_query': 'SELECT email FROM users', 'entity_type': 'users'}]
        self.artifact = self.root / 'artifacts.json'
        self.artifact.write_text(json.dumps([{**self.evidence[0], 'data': [{'email': 'private@example.test'}]}]))

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmp.cleanup()

    async def save(self, run='run1', script="print('QUERY RESULTS')", metadata=None):
        return await self.store.save(run, script, 'Current user emails', self.evidence, 'sql',
            classification=metadata or self.metadata, output_fields=['email'])

    async def test_persistence_and_exact_duplicate_identity(self):
        first = await self.save()
        self.assertEqual(first, await self.save())
        async with self.factory() as session:
            row = (await session.execute(select(QueryProcedure))).scalar_one()
            self.assertEqual(row.execution_count, 2)
            self.assertEqual(row.classification_json['entities'], ['user'])
            self.assertEqual(row.output_fields_json, ['email'])
            self.assertEqual(row.sharing_scope, 'private')
            self.assertNotIn('private@example.test', json.dumps(row.evidence_json))

    async def test_owner_tenant_and_compatibility_isolation(self):
        identifier = await self.save()
        self.assertIsNotNone(await self.store.inspect('run1', identifier))
        self.assertIsNone(await self.store.inspect('run2', identifier))
        self.assertIsNone(await self.store.inspect('run3', identifier))
        other = procedures.ProcedureStore(self.db, tenant_id='tenant', compatibility='changed')
        self.assertIsNone(await other.inspect('run1', identifier))
        self.assertIsNone(await self.save(run='unknown'))

    async def test_retention_and_rejection(self):
        for n in range(3):
            await self.save(script=f"print('QUERY RESULTS {n}')")
        async with self.factory() as session:
            self.assertEqual(len((await session.execute(select(QueryProcedure))).scalars().all()), 2)
        for changes in ({'classification': 'conversation_dependent'}, {'entities': ['invented_entity']}):
            self.assertIsNone(await self.save(metadata=self.metadata.model_copy(update=changes)))
        self.assertIsNone(await self.save(script="open('chat_sessions/results.json')"))

    async def test_post_execution_hook_skips_failed_partial_and_missing_metadata(self):
        result = SimpleNamespace(success=True, is_degraded_success=False, is_special_tool=False,
            script_code="print('QUERY RESULTS')", data_source_type='sql',
            synthesis_result=SimpleNamespace(procedure_metadata=self.metadata))
        async def run(event):
            return await procedures.save_successful_procedure(run_id='run1', result=result,
                event=event, artifacts_file=self.artifact)
        with patch.object(procedures, '_store', AsyncMock(return_value=self.store)):
            self.assertIsNone(await run({'display_type': 'table', 'success': False}))
            self.assertIsNone(await run({'display_type': 'table', 'metadata': {'is_partial': True}}))
            result.is_degraded_success = True
            self.assertIsNone(await run({'display_type': 'table', 'data': []}))
            result.is_degraded_success = False
            result.synthesis_result.procedure_metadata = None
            self.assertIsNone(await run({'display_type': 'table', 'data': []}))

    async def test_empty_execution_is_saved_and_evidence_excludes_rows(self):
        result = SimpleNamespace(success=True, is_degraded_success=False, is_special_tool=False,
            script_code="print('QUERY RESULTS')", data_source_type='sql',
            synthesis_result=SimpleNamespace(procedure_metadata=self.metadata))
        event = {'display_type': 'table', 'data': [], 'headers': [{'value': 'email', 'text': 'Email'}], 'summary': 'No matches'}
        with patch.object(procedures, '_store', AsyncMock(return_value=self.store)):
            identifier = await procedures.save_successful_procedure(run_id='run1', result=result,
                event=event, artifacts_file=self.artifact)
        self.assertEqual(event['metadata']['procedure_id'], identifier)
        async with self.factory() as session:
            row = (await session.execute(select(QueryProcedure))).scalar_one()
            self.assertEqual(row.result_summary, 'No matches')
            self.assertEqual(row.output_fields_json, ['email'])
            self.assertEqual(row.evidence_json, self.evidence)

    def test_fields_come_from_executed_rows_not_header_predictions(self):
        self.assertEqual(executed_fields({'data': [{'email': 'x'}, {'email': 'y', 'status': 'ACTIVE'}],
            'headers': ['incorrect']}), ['email', 'status'])
        with self.assertRaises(ValueError):
            executed_fields({'data': ['not a row']})

    async def test_legacy_coverage_label_does_not_gate_successful_candidate(self):
        metadata = {**self.metadata.model_dump(), 'coverage': 'partial'}
        self.assertNotIn('coverage', ProcedureMetadata.model_json_schema()['properties'])
        self.assertIsNotNone(await self.save(metadata=metadata))
        async with self.factory() as session:
            row = (await session.execute(select(QueryProcedure))).scalar_one()
            self.assertNotIn('coverage', row.classification_json)

    async def test_catalog_filters_entities_and_omits_scripts_and_evidence(self):
        user_id = await self.save()
        await self.save(metadata=self.metadata.model_copy(update={'entities': ['group'], 'purpose': 'List groups'}))
        catalog = await self.store.catalog('run1', ['user'])
        self.assertEqual([entry['procedure_id'] for entry in catalog], [user_id])
        self.assertNotIn('script_code', catalog[0])
        self.assertNotIn('evidence_json', catalog[0])
        self.assertEqual(await self.store.catalog('run2', ['user']), [])
        self.assertEqual(await self.store.catalog('run1', ['invented']), [])

    async def test_failed_candidate_quarantined_without_changing_history(self):
        identifier = await self.save()
        await self.store.record_reuse('run2', identifier, failed=True)
        self.assertIsNotNone(await self.store.inspect('run1', identifier))
        await self.store.record_reuse('run1', identifier)
        await self.store.record_reuse('run1', identifier, failed=True)
        self.assertEqual(await self.store.catalog('run1', ['user']), [])
        self.assertIsNone(await self.store.inspect('run1', identifier))
        async with self.factory() as session:
            row = (await session.execute(select(QueryProcedure))).scalar_one()
            self.assertEqual(row.execution_count, 2)
            self.assertTrue(row.classification_json['_reuse_disabled'])
            self.assertEqual(len((await session.execute(select(ConversationTurn))).scalars().all()), 3)


if __name__ == '__main__':
    unittest.main()
