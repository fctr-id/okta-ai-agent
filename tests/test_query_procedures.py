"""Offline candidate persistence tests: no application credentials or model calls."""
import asyncio
from datetime import datetime, timedelta, timezone
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
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from src.core.okta.sync.models import Base, QueryProcedure, QueryProcedureAdmission, ConversationSession, ConversationTurn
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

admission_spec = importlib.util.spec_from_file_location('admission_under_test',
    Path(__file__).resolve().parents[1] / 'src/core/procedure_admission.py')
admission = importlib.util.module_from_spec(admission_spec)
with patch.dict(sys.modules, {'src.core.query_procedures': procedures, 'src.utils.logging': logging_stub}):
    admission_spec.loader.exec_module(admission)


class ProcedureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.engine = create_async_engine('sqlite+aiosqlite:///' + (self.root / 'test.db').as_posix())
        async with self.engine.begin() as conn:
            await conn.run_sync(lambda connection: Base.metadata.create_all(connection, tables=[
                ConversationSession.__table__, ConversationTurn.__table__, QueryProcedure.__table__,
                QueryProcedureAdmission.__table__]))
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
            self.assertEqual(row.classification_json.get('_successful_reuses', 0), 0)
            self.assertEqual(row.classification_json['entities'], ['user'])
            self.assertEqual(row.output_fields_json, ['email'])
            self.assertEqual(row.sharing_scope, 'tenant')
            self.assertNotIn('private@example.test', json.dumps(row.evidence_json))

    async def test_owner_tenant_and_compatibility_isolation(self):
        identifier = await self.save(metadata=self.metadata.model_copy(update={
            'classification': 'parameterized', 'contains_sensitive_literals': True}))
        self.assertIsNotNone(await self.store.inspect('run1', identifier))
        self.assertIsNone(await self.store.inspect('run2', identifier))
        self.assertIsNone(await self.store.inspect('run3', identifier))
        other = procedures.ProcedureStore(self.db, tenant_id='tenant', compatibility='changed')
        self.assertIsNone(await other.inspect('run1', identifier))
        self.assertIsNone(await self.save(run='unknown'))

    async def test_explicit_version_keeps_legacy_hashes_until_breaking_bump(self):
        self.store.compatibility = 'a' * 64
        legacy = await self.save()
        self.store = procedures.ProcedureStore(self.db, tenant_id='tenant', limit=10)
        self.assertEqual(self.store.compatibility, 'query-procedures-v1')
        self.assertIsNotNone(await self.store.inspect('run2', legacy))
        self.assertEqual([row['procedure_id'] for row in await self.store.catalog('run2', ['user'])], [legacy])
        # Identical content under a new contract must resolve only its own row.
        current = await self.save()
        self.assertNotEqual(current, legacy)
        self.assertEqual(await self.save(), current)
        with patch.object(procedures, 'PROCEDURE_CONTRACT_VERSION', 'query-procedures-v2'):
            next_version = procedures.ProcedureStore(self.db, tenant_id='tenant')
            self.assertEqual(await next_version.catalog('run1', ['user']), [])
            self.assertIsNone(await next_version.inspect('run1', legacy))
            self.assertIsNone(await next_version.inspect('run1', current))

    def test_contract_version_does_not_read_prompt_or_source_files(self):
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('File hashing is not compatibility')):
            self.assertEqual(procedures.compatibility_key(), 'query-procedures-v1')

    async def test_legacy_entries_still_enforce_validation_and_tenant_boundary(self):
        self.store.compatibility = 'b' * 64
        identifier = await self.save()
        self.store = procedures.ProcedureStore(self.db, tenant_id='tenant')
        other = procedures.ProcedureStore(self.db, tenant_id='other')
        self.assertIsNone(await other.inspect('run3', identifier))
        with patch.object(procedures, 'validate_generated_code', return_value=SimpleNamespace(is_valid=False)):
            self.assertIsNone(await self.store.inspect('run1', identifier))

    async def test_retention_and_rejection(self):
        for n in range(3):
            await self.save(script=f"print('QUERY RESULTS {n}')")
        async with self.factory() as session:
            self.assertEqual(len((await session.execute(select(QueryProcedure))).scalars().all()), 2)
        for changes in ({'classification': 'conversation_dependent'}, {'entities': ['invented_entity']}):
            self.assertIsNone(await self.save(metadata=self.metadata.model_copy(update=changes)))
        self.assertIsNone(await self.save(script="open('chat_sessions/results.json')"))

    async def test_generic_shared_with_same_tenant_and_usage_recorded(self):
        identifier = await self.save()
        self.assertIsNotNone(await self.store.inspect('run2', identifier))
        await self.store.record_reuse('run2', identifier)
        async with self.factory() as session:
            row = await session.get(QueryProcedure, identifier)
            self.assertEqual(row.owner_id, 'alice')
            self.assertEqual(row.classification_json['_successful_reuses'], 1)
        other = procedures.ProcedureStore(self.db, tenant_id='other', compatibility='fixture')
        self.assertEqual(await other.catalog('run3', ['user']), [])
        self.assertIsNone(await other.inspect('run3', identifier))
        await other.record_reuse('run3', identifier, failed=True)
        self.assertIsNotNone(await self.store.inspect('run2', identifier))
        incompatible = procedures.ProcedureStore(self.db, tenant_id='tenant', compatibility='changed')
        self.assertIsNone(await incompatible.inspect('run2', identifier))
        self.assertEqual(await self.store.catalog('unknown', ['user']), [])

    async def test_legacy_generic_shared_but_parameterized_stays_private(self):
        identifier = await self.save()
        async with self.factory() as session:
            await session.execute(update(QueryProcedure).where(QueryProcedure.procedure_id == identifier)
                .values(sharing_scope='private'))
            await session.commit()
        self.assertIsNotNone(await self.store.inspect('run2', identifier))
        private_id = await self.save(metadata=self.metadata.model_copy(update={
            'classification': 'parameterized', 'contains_sensitive_literals': True}))
        self.assertIsNone(await self.store.inspect('run2', private_id))
        self.assertEqual([row['procedure_id'] for row in await self.store.catalog('run2', ['user'])], [identifier])

    async def test_identical_saves_by_different_owners_resolve_their_own_entry(self):
        alice = await self.save()
        bob = await self.save(run='run2')
        self.assertNotEqual(alice, bob)
        self.assertEqual(bob, await self.save(run='run2'))
        self.assertEqual(alice, await self.save())

    async def test_popular_queries_survive_and_new_queries_have_room(self):
        self.store.limit = 100
        ids = [await self.save(script=f"print('query {n}')") for n in range(6)]
        other = procedures.ProcedureStore(self.db, tenant_id='other', compatibility='fixture')
        other_id = await other.save('run3', "print('other tenant')", 'Other', self.evidence, 'sql',
            classification=self.metadata, output_fields=['email'])
        async with self.factory() as session:
            # Five popular old entries; the sixth is recent but has never been reused.
            for n, identifier in enumerate(ids):
                await session.execute(update(QueryProcedure).where(QueryProcedure.procedure_id == identifier)
                    .values(last_used_at=datetime(2025, 1, 1) + timedelta(days=n),
                            classification_json={**self.metadata.model_dump(),
                                                 '_successful_reuses': [10, 8, 6, 4, 2, 0][n]}))
            await session.commit()
        self.store.limit = 5  # Four popular + one recent, equivalent to 80/20 at 100.
        newest = await self.save(script="print('new query')")
        async with self.factory() as session:
            kept = set((await session.execute(select(QueryProcedure.procedure_id))).scalars())
        self.assertEqual(kept, {*ids[:4], newest, other_id})

    async def test_popularity_ties_use_recency_and_failures_are_not_protected(self):
        self.store.limit = 100
        ids = [await self.save(script=f"print('tie {n}')") for n in range(5)]
        async with self.factory() as session:
            for n, identifier in enumerate(ids):
                metadata = {**self.metadata.model_dump(), '_successful_reuses': 2}
                if n == 0:
                    metadata.update(_successful_reuses=999, _reuse_disabled=True)
                await session.execute(update(QueryProcedure).where(QueryProcedure.procedure_id == identifier)
                    .values(last_used_at=datetime(2025, 1, 1) + timedelta(days=n),
                            compatibility_key='outdated' if n == 1 else 'fixture',
                            classification_json=metadata))
            await session.commit()
        self.store.limit = 3  # Two popular + one recent.
        newest = await self.save(script="print('newest')")
        async with self.factory() as session:
            kept = set((await session.execute(select(QueryProcedure.procedure_id))).scalars())
        self.assertEqual(kept, {ids[3], ids[4], newest})

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
        self.assertEqual(event['metadata']['procedure_admission_id'], identifier)
        self.assertNotIn('procedure_id', event['metadata'])
        queue = admission.AdmissionQueue(self.store, AsyncMock())
        self.assertTrue(await queue.process_one())
        queue.compare.assert_not_awaited()  # Empty library needs no comparison call.
        async with self.factory() as session:
            row = (await session.execute(select(QueryProcedure))).scalar_one()
            self.assertEqual(row.result_summary, 'No matches')
            self.assertEqual(row.output_fields_json, ['email'])
            self.assertEqual(row.evidence_json, self.evidence)

    async def test_adapted_success_saves_child_without_overwriting_parent(self):
        parent_id = await self.save()
        parent = await self.store.inspect('run1', parent_id)
        result = SimpleNamespace(success=True, is_degraded_success=False, is_special_tool=False,
            script_code="print('adapted query')", data_source_type='sql', procedure_reuse='adapted',
            completed_result={'display_type': 'table'}, reusable_procedure=parent,
            synthesis_result=SimpleNamespace(procedure_metadata=self.metadata.model_copy(update={'scope': 'Recent users'})))
        event = {'display_type': 'table', 'results': [{'email': 'fixture'}], 'summary': 'Recent users'}
        with patch.object(procedures, '_store', AsyncMock(return_value=self.store)):
            pending_id = await procedures.save_successful_procedure(run_id='run2', result=result, event=event,
                artifacts_file=self.root/'absent.json')
        queue = admission.AdmissionQueue(self.store, AsyncMock(return_value={
            'decision': 'useful_variant'}))
        await queue.process_one()
        self.assertEqual(queue.last_outcome[0], pending_id)
        child_id = queue.last_outcome[2]
        self.assertNotEqual(child_id, parent_id)
        async with self.factory() as session:
            child = await session.get(QueryProcedure, child_id)
            original = await session.get(QueryProcedure, parent_id)
            self.assertEqual(child.parent_procedure_id, parent_id)
            self.assertEqual(child.owner_id, 'bob')
            self.assertEqual(child.classification_json['scope'], 'Recent users')
            self.assertEqual(child.evidence_json, self.evidence)
            self.assertEqual(original.script_code, parent['script_code'])
            self.assertEqual(original.execution_count, 1)

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
        self.assertEqual([entry['procedure_id'] for entry in await self.store.catalog('run2', ['user'])], [user_id])
        self.assertEqual(await self.store.catalog('run1', ['invented']), [])

    async def test_catalog_ranks_all_entities_before_recent_partial_matches(self):
        self.store.limit = 20
        both = await self.save(metadata=self.metadata.model_copy(update={
            'entities': ['user', 'application'], 'purpose': 'List assigned applications'}))
        for n in range(9):
            await self.save(script=f"print('partial {n}')", metadata=self.metadata.model_copy(update={
                'entities': ['user'] if n % 2 else ['application']}))
        unrelated = await self.save(metadata=self.metadata.model_copy(update={'entities': ['group']}))
        async with self.factory() as session:
            await session.execute(update(QueryProcedure).where(QueryProcedure.procedure_id == both)
                .values(last_used_at=datetime(2025, 1, 1)))
            await session.commit()
        catalog = await self.store.catalog('run1', ['application', 'user', 'user'])
        self.assertEqual(len(catalog), 8)
        self.assertEqual(catalog[0]['procedure_id'], both)
        self.assertNotIn(unrelated, [entry['procedure_id'] for entry in catalog])
        self.assertTrue(all(len(entry['classification_json']['entities']) == 1 for entry in catalog[1:]))
        # Without a complete match, still provide partial candidates for assessment.
        partial = await self.store.catalog('run1', ['application', 'device'])
        self.assertTrue(partial)
        self.assertTrue(all('application' in entry['classification_json']['entities'] for entry in partial))

    async def test_failed_attempt_preserves_candidate_and_success_counters(self):
        identifier = await self.save(metadata=self.metadata.model_copy(update={
            'classification': 'parameterized', 'contains_sensitive_literals': True}))
        await self.store.record_reuse('run2', identifier, failed=True)
        self.assertIsNotNone(await self.store.inspect('run1', identifier))
        await self.store.record_reuse('run1', identifier)
        await self.store.record_reuse('run1', identifier, failed=True)
        self.assertEqual([row['procedure_id'] for row in await self.store.catalog('run1', ['user'])], [identifier])
        self.assertIsNotNone(await self.store.inspect('run1', identifier))
        async with self.factory() as session:
            row = (await session.execute(select(QueryProcedure))).scalar_one()
            self.assertEqual(row.execution_count, 2)
            self.assertEqual(row.classification_json['_successful_reuses'], 1)
            self.assertNotIn('_reuse_disabled', row.classification_json)
            self.assertEqual(len((await session.execute(select(ConversationTurn))).scalars().all()), 3)

    async def test_successful_resave_restores_previously_disabled_entry(self):
        identifier = await self.save()
        async with self.factory() as session:
            await session.execute(update(QueryProcedure).where(QueryProcedure.procedure_id == identifier)
                .values(classification_json={**self.metadata.model_dump(), '_reuse_disabled': True,
                                             '_successful_reuses': 3}))
            await session.commit()
        self.assertIsNone(await self.store.inspect('run1', identifier))
        self.assertEqual(await self.save(), identifier)
        self.assertIsNotNone(await self.store.inspect('run2', identifier))
        async with self.factory() as session:
            row = await session.get(QueryProcedure, identifier)
            self.assertEqual(row.classification_json['_successful_reuses'], 3)
            self.assertNotIn('_reuse_disabled', row.classification_json)

    async def test_invalid_code_cannot_be_saved_or_inspected(self):
        with patch.object(procedures, 'validate_generated_code', return_value=SimpleNamespace(is_valid=False)):
            self.assertIsNone(await self.save())
        identifier = await self.save()
        with patch.object(procedures, 'validate_generated_code', return_value=SimpleNamespace(is_valid=False)):
            self.assertIsNone(await self.store.inspect('run1', identifier))

    async def enqueue(self, run='run1', metadata=None, fields=None, script="print('new implementation')", source='sql'):
        return await self.store.save(run, script, 'Summary not sent to admission', self.evidence, source,
            classification=metadata or self.metadata, output_fields=fields or ['email'], enqueue=True)

    async def test_admission_is_durable_hidden_and_idempotent(self):
        identifier = await self.enqueue()
        self.assertEqual(identifier, await self.enqueue())
        self.assertEqual(await self.store.catalog('run1', ['user']), [])
        async with self.factory() as session:
            item = (await session.execute(select(QueryProcedureAdmission))).scalar_one()
            self.assertEqual(item.payload_json['owner_id'], 'alice')
            self.assertNotIn('private@example.test', json.dumps(item.payload_json))
            # Cleanup of conversations must not lose a successfully executed candidate.
            from sqlalchemy import delete
            await session.execute(delete(ConversationTurn))
            await session.execute(delete(ConversationSession))
            await session.commit()
        queue = admission.AdmissionQueue(self.store, AsyncMock())
        self.assertTrue(await queue.process_one())
        async with self.factory() as session:
            self.assertIsNone(await session.get(QueryProcedureAdmission, identifier))
            record = (await session.execute(select(QueryProcedure))).scalar_one()
            self.assertEqual(record.owner_id, 'alice')

    async def test_semantic_duplicate_omits_payloads_and_keeps_original(self):
        original = await self.save()
        pending = await self.enqueue('run2')  # Different user, generic query.
        compare = AsyncMock(return_value={'decision': 'duplicate', 'duplicate_id': original})
        queue = admission.AdmissionQueue(self.store, compare)
        await queue.process_one()
        new, existing = compare.call_args.args
        self.assertEqual(new['output_fields'], ['email'])
        self.assertEqual(existing[0]['output_fields'], ['email'])
        self.assertEqual(new['question'], 'List users')
        self.assertEqual(new['scope'], 'All statuses')
        encoded = json.dumps(compare.call_args.args)
        for omitted in ('script_code', 'evidence', 'print(', 'SELECT ', 'Summary not sent', 'private@example.test'):
            self.assertNotIn(omitted, encoded)
        self.assertEqual(queue.last_outcome, (pending, 'duplicate', original))
        async with self.factory() as session:
            row = (await session.execute(select(QueryProcedure))).scalar_one()
            self.assertEqual(row.owner_id, 'alice')
            self.assertEqual(row.script_code, "print('QUERY RESULTS')")
            self.assertEqual(row.execution_count, 2)
            self.assertEqual(row.classification_json.get('_successful_reuses', 0), 0)

    async def test_admission_preserves_distinct_fields_source_and_entities_even_if_model_says_duplicate(self):
        for overrides in ({'fields': ['email', 'status']}, {'source': 'api'},
                          {'metadata': self.metadata.model_copy(update={'entities': ['user', 'group']})}):
            original = await self.save()
            await self.enqueue(**overrides)
            queue = admission.AdmissionQueue(self.store, AsyncMock(return_value={
                'decision': 'duplicate', 'duplicate_id': original}))
            await queue.process_one()
            self.assertEqual(queue.last_outcome[1], 'useful_variant')
            self.assertNotEqual(queue.last_outcome[2], original)

    async def test_admission_failure_and_invalid_id_remain_pending_and_retry(self):
        await self.save()
        pending = await self.enqueue()
        compare = AsyncMock(side_effect=RuntimeError('Provider unavailable'))
        queue = admission.AdmissionQueue(self.store, compare)
        await queue.process_one()
        self.assertFalse(await queue.process_one())  # Backoff, no hot retry loop.
        async with self.factory() as session:
            row = await session.get(QueryProcedureAdmission, pending)
            self.assertEqual(row.attempts, 1)
            self.assertIsNone(row.lease_token)
            row.next_attempt_at = datetime.now(timezone.utc)
            await session.commit()
        queue.compare = AsyncMock(return_value={'decision': 'duplicate', 'duplicate_id': 'invented'})
        await queue.process_one()
        async with self.factory() as session:
            row = await session.get(QueryProcedureAdmission, pending)
            self.assertEqual(row.attempts, 2)
            row.next_attempt_at = datetime.now(timezone.utc)
            await session.commit()
        queue.compare = AsyncMock(return_value={'decision': 'distinct'})
        await queue.process_one()
        self.assertEqual(queue.last_outcome[1], 'distinct')

    async def test_pending_bound_does_not_evict_existing_work(self):
        self.store.limit = 1
        first = await self.enqueue()
        self.assertIsNone(await self.enqueue('run2'))
        async with self.factory() as session:
            self.assertIsNotNone(await session.get(QueryProcedureAdmission, first))

    async def test_concurrent_workers_serialize_per_tenant_and_compare_latest_admission(self):
        await self.enqueue('run1')
        await self.enqueue('run2')
        first, second = admission.AdmissionQueue(self.store), admission.AdmissionQueue(self.store)
        claims = await asyncio.gather(first.claim(), second.claim())
        self.assertEqual(sum(claim is not None for claim in claims), 1)
        identifier, token, values = next(claim for claim in claims if claim)
        await first.finish(identifier, token, values, admission.AdmissionDecision(decision='distinct'), [])
        original = first.last_outcome[2]
        second.compare = AsyncMock(return_value={'decision': 'duplicate', 'duplicate_id': original})
        await second.process_one()
        self.assertEqual(second.last_outcome[1], 'duplicate')
        self.assertEqual(second.compare.call_args.args[1][0]['procedure_id'], original)

    async def test_expired_lease_recovery_and_stale_worker_cannot_finish(self):
        identifier = await self.enqueue()
        queue = admission.AdmissionQueue(self.store)
        _, old_token, values = await queue.claim()
        async with self.factory() as session:
            await session.execute(update(QueryProcedureAdmission).where(QueryProcedureAdmission.admission_id == identifier)
                .values(lease_until=datetime.now(timezone.utc) - timedelta(seconds=1)))
            await session.commit()
        _, new_token, _ = await queue.claim()
        self.assertNotEqual(old_token, new_token)
        await queue.finish(identifier, old_token, values, admission.AdmissionDecision(decision='distinct'), [])
        self.assertIsNone(queue.last_outcome)
        await queue.finish(identifier, new_token, values, admission.AdmissionDecision(decision='distinct'), [])
        self.assertEqual(queue.last_outcome[0], identifier)

    async def test_cancellation_releases_lease_for_restart(self):
        await self.save()
        identifier = await self.enqueue()
        queue = admission.AdmissionQueue(self.store, AsyncMock(side_effect=asyncio.CancelledError))
        with self.assertRaises(asyncio.CancelledError):
            await queue.process_one()
        async with self.factory() as session:
            row = await session.get(QueryProcedureAdmission, identifier)
            self.assertIsNone(row.lease_token)
        restarted = admission.AdmissionQueue(self.store, AsyncMock(return_value={'decision': 'useful_variant'}))
        await restarted.process_one()
        self.assertEqual(restarted.last_outcome[0], identifier)

    async def test_admission_never_sends_other_owner_private_candidates_or_other_tenant(self):
        private = self.metadata.model_copy(update={'classification': 'parameterized', 'contains_sensitive_literals': True})
        await self.save(metadata=private)
        await self.enqueue('run2', metadata=private)
        queue = admission.AdmissionQueue(self.store, AsyncMock())
        _, _, values = await queue.claim()
        self.assertEqual(await queue.candidates(values), [])
        other = procedures.ProcedureStore(self.db, tenant_id='other', compatibility='fixture')
        self.assertEqual(await admission.AdmissionQueue(other).candidates(values), [])

    async def test_admission_revalidates_script_and_contract(self):
        pending = await self.enqueue()
        queue = admission.AdmissionQueue(self.store, AsyncMock())
        with patch.object(admission, 'validate_generated_code', return_value=SimpleNamespace(is_valid=False)):
            await queue.process_one()
        self.assertEqual(queue.last_outcome, (pending, 'invalid_candidate', None))
        queue.compare.assert_not_awaited()
        await self.enqueue()
        self.store.compatibility = 'next-contract'
        await queue.process_one()
        self.assertEqual(queue.last_outcome[1], 'invalid_candidate')

    async def test_duplicate_deleted_during_comparison_is_retried_not_discarded(self):
        from sqlalchemy import delete
        original = await self.save()
        pending = await self.enqueue()
        async def compare(*args):
            async with self.factory() as session:
                await session.execute(delete(QueryProcedure).where(QueryProcedure.procedure_id == original))
                await session.commit()
            return {'decision': 'duplicate', 'duplicate_id': original}
        queue = admission.AdmissionQueue(self.store, compare)
        await queue.process_one()
        self.assertIsNone(queue.last_outcome)
        await queue.process_one()
        self.assertEqual(queue.last_outcome[0:2], (pending, 'distinct'))

    async def test_cli_finishes_pending_admission(self):
        pending = await self.enqueue()
        event = {'metadata': {'procedure_admission_id': pending, 'procedure_admission': 'pending'}}
        with patch.object(admission, '_store', AsyncMock(return_value=self.store)):
            await admission.finish_cli_admission(event)
        self.assertEqual(event['metadata']['procedure_admission'], 'distinct')
        self.assertTrue(event['metadata']['procedure_id'])

    async def test_model_timeout_preserves_pending_candidate(self):
        await self.save()
        pending = await self.enqueue()
        async def stalled(*args):
            await asyncio.Event().wait()
        queue = admission.AdmissionQueue(self.store, stalled)
        with patch.object(admission, 'MODEL_TIMEOUT', 0.01):
            await queue.process_one()
        async with self.factory() as session:
            item = await session.get(QueryProcedureAdmission, pending)
            self.assertIsNotNone(item)
            self.assertIsNone(item.lease_token)
            self.assertEqual(item.attempts, 1)

    async def test_structured_admission_call_includes_comparison_prompt_and_metadata(self):
        from pydantic_ai import Agent
        from pydantic_ai.models.test import TestModel
        agents_stub = ModuleType('src.core.agents')
        picker_stub = ModuleType('src.core.models.model_picker')
        picker_stub.ModelType = SimpleNamespace(REASONING='reasoning')
        original = await self.save()
        await self.enqueue()
        queue = admission.AdmissionQueue(self.store)
        _, _, values = await queue.claim()
        candidate = admission.comparison_metadata(values)
        existing = await queue.candidates(values)
        for output in ({'decision': 'duplicate', 'duplicate_id': original},
                       {'decision': 'useful_variant'}, {'decision': 'distinct'}):
            captured = {}
            def build(model_type, **kwargs):
                captured.update(kwargs)
                self.assertEqual(model_type, 'reasoning')
                agent = Agent(TestModel(custom_output_args=output), **kwargs)
                captured['run'] = AsyncMock(wraps=agent.run)
                agent.run = captured['run']
                return agent
            agents_stub.build_agent = build
            with patch.dict(sys.modules, {'src.core.agents': agents_stub,
                                         'src.core.models.model_picker': picker_stub}):
                decision = await admission.compare_candidate(candidate, existing)
            self.assertEqual(decision.decision, output['decision'])
            self.assertIn('database of successful retrieval queries for future reuse', captured['instructions'])
            sent = json.loads(captured['run'].call_args.args[0])
            self.assertEqual(sent['new_query']['output_fields'], ['email'])
            self.assertEqual(sent['existing_queries'][0]['question'], 'List users')
            self.assertNotIn('script_code', json.dumps(sent))


if __name__ == '__main__':
    unittest.main()
