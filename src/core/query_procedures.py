"""Bounded, caller-owned retrieval evidence. No result payloads or direct replay."""
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select, delete, text, func, update
from sqlalchemy.dialects.sqlite import insert

from src.config.settings import settings
from src.core.okta.sync.models import QueryProcedure, ConversationSession, ConversationTurn
from src.core.okta.sync.operations import DatabaseOperations
from src.data.schemas.artifact_manifest import load_artifacts_file
from src.data.schemas.query_procedure import ProcedureMetadata, entity_catalog, executed_fields
from src.utils.logging import get_logger
from src.utils.security_config import validate_generated_code

logger = get_logger(__name__)
MAX_SCRIPT_CHARS = 40000
MAX_EVIDENCE_CHARS = 24000


@lru_cache(maxsize=1)
def compatibility_key():
    """Invalidate old procedures when the source/schema/validation contract changes."""
    root = Path(__file__).resolve().parents[2]
    digest = hashlib.sha256(b'query-procedures-v1')
    for relative in (
        'src/core/okta/sync/models.py', 'src/utils/security_config.py',
        'src/data/schemas/Okta_API_entitity_endpoint_reference_GET_ONLY.json',
        'src/core/agents/prompts/synthesis_prompt.txt',
        'src/core/okta/client/base_okta_api_client.py',
    ):
        digest.update((root / relative).read_bytes())
    return digest.hexdigest()


def retrieval_evidence(artifacts_file, previous=None):
    """Keep retrieval patterns, never samples, stored rows, or sidecar references."""
    evidence = []
    for artifact in load_artifacts_file(artifacts_file):
        item = {key: artifact[key] for key in ('sql_query', 'api_code', 'entity_type', 'key_columns') if artifact.get(key)}
        if item.get('sql_query') or item.get('api_code'):
            evidence.append(item)
    return evidence or (previous or {}).get('evidence', [])


class ProcedureStore:
    def __init__(self, db, *, tenant_id, limit=100, catalog_chars=32000, compatibility=None):
        self.db, self.tenant_id = db, tenant_id
        self.limit, self.catalog_chars = limit, catalog_chars
        self.compatibility = compatibility or compatibility_key()

    async def actor(self, session, run_id):
        row = (await session.execute(select(ConversationSession.user_id, ConversationSession.source,
                                           ConversationTurn.query_text)
            .join(ConversationTurn, ConversationTurn.session_id == ConversationSession.session_id)
            .where(ConversationSession.tenant_id == self.tenant_id,
                   ConversationTurn.tenant_id == self.tenant_id,
                   ConversationTurn.run_id == run_id))).first()
        return row

    def eligible(self, owner):
        # Shared scope is reserved for a later explicit promotion/access policy.
        return (QueryProcedure.tenant_id == self.tenant_id, QueryProcedure.owner_id == owner,
                QueryProcedure.sharing_scope == 'private', QueryProcedure.compatibility_key == self.compatibility,
                QueryProcedure.classification_json['_reuse_disabled'].as_boolean().is_not(True))

    async def catalog(self, run_id, entities):
        entities = sorted(set(entities) & entity_catalog())
        if not entities:
            return []
        async with self.db.get_session() as session:
            actor = await self.actor(session, run_id)
            if not actor:
                return []
            names = func.json_each(QueryProcedure.classification_json['entities']).table_valued('value')
            matching_entity = select(1).select_from(names).where(names.c.value.in_(entities)).exists()
            records = (await session.execute(select(QueryProcedure.procedure_id, QueryProcedure.query_text,
                QueryProcedure.description, QueryProcedure.data_source, QueryProcedure.classification_json,
                QueryProcedure.output_fields_json)
                .where(*self.eligible(actor.user_id), matching_entity).order_by(QueryProcedure.last_used_at.desc())
                .limit(min(self.limit, 8)))).mappings().all()
            catalog = [dict(row) for row in records]
            while catalog and len(json.dumps(catalog)) > self.catalog_chars:
                catalog.pop()
            return catalog

    async def inspect(self, run_id, procedure_id):
        async with self.db.get_session() as session:
            actor = await self.actor(session, run_id)
            if not actor:
                return None
            record = (await session.execute(select(QueryProcedure).where(
                *self.eligible(actor.user_id), QueryProcedure.procedure_id == procedure_id))).scalar_one_or_none()
            if record is None or not validate_generated_code(record.script_code).is_valid:
                return None
            return {'procedure_id': record.procedure_id, 'query_text': record.query_text,
                    'description': record.description, 'script_code': record.script_code,
                    'evidence': record.evidence_json, 'data_source': record.data_source,
                    'classification': record.classification_json, 'output_fields': record.output_fields_json}

    async def record_reuse(self, run_id, procedure_id, *, failed=False):
        async with self.db.get_session() as session:
            actor = await self.actor(session, run_id)
            if not actor:
                return
            conditions = (*self.eligible(actor.user_id), QueryProcedure.procedure_id == procedure_id)
            if failed:
                # Runtime-owned quarantine marker; the classifier cannot authorize or clear it.
                values = {'classification_json': func.json_set(QueryProcedure.classification_json, '$._reuse_disabled', 1)}
            else:
                values = {'last_used_at': datetime.now(timezone.utc), 'execution_count': QueryProcedure.execution_count + 1}
            await session.execute(update(QueryProcedure).where(*conditions).values(**values))
            await session.commit()

    async def save(self, run_id, script, description, evidence, data_source, *, classification, output_fields, parent_id=None):
        classification = ProcedureMetadata.model_validate(classification)
        if (classification.classification == 'conversation_dependent'
                or not classification.entities or not set(classification.entities).issubset(entity_catalog())):
            return None
        if not script or len(script) > MAX_SCRIPT_CHARS or not validate_generated_code(script).is_valid:
            return None
        if not evidence or len(json.dumps(evidence)) > MAX_EVIDENCE_CHARS or data_source not in {'sql', 'api', 'hybrid'}:
            return None
        # A procedure must not rely on expiring conversation payloads.
        if any(marker in script for marker in ('chat_sessions', 'result_sets/', 'result_sets\\', 'artifacts.json')):
            return None
        async with self.db.get_session() as session:
            # Serialize SQLite save/evict transactions, including concurrent workers.
            await session.execute(text('BEGIN IMMEDIATE'))
            actor = await self.actor(session, run_id)
            if not actor or len(actor.query_text) > 2000:
                return None
            description = description.strip()[:600] if isinstance(description, str) else ''
            identity = json.dumps([actor.query_text, script, classification.model_dump(), output_fields, evidence, data_source], sort_keys=True)
            content_hash = hashlib.sha256(identity.encode()).hexdigest()
            values = dict(procedure_id=str(uuid4()), tenant_id=self.tenant_id, owner_id=actor.user_id,
                          sharing_scope='private', query_text=actor.query_text, description=classification.purpose,
                          script_code=script, content_hash=content_hash, compatibility_key=self.compatibility,
                          evidence_json=evidence, classification_json=classification.model_dump(),
                          output_fields_json=output_fields, result_summary=description,
                          data_source=data_source, source=actor.source,
                          originating_run_id=run_id, parent_procedure_id=parent_id,
                          created_at=datetime.now(timezone.utc), last_used_at=datetime.now(timezone.utc), execution_count=1)
            stmt = insert(QueryProcedure).values(**values).on_conflict_do_update(
                index_elements=['tenant_id', 'owner_id', 'sharing_scope', 'compatibility_key', 'content_hash'],
                set_={'last_used_at': values['last_used_at'], 'result_summary': description,
                      'execution_count': QueryProcedure.execution_count + 1})
            await session.execute(stmt)
            procedure_id = (await session.execute(select(QueryProcedure.procedure_id).where(
                *self.eligible(actor.user_id), QueryProcedure.content_hash == content_hash))).scalar_one()
            expired = select(QueryProcedure.procedure_id).where(QueryProcedure.tenant_id == self.tenant_id).order_by(
                QueryProcedure.last_used_at.desc(), QueryProcedure.procedure_id).offset(self.limit)
            await session.execute(delete(QueryProcedure).where(QueryProcedure.procedure_id.in_(expired)))
            await session.commit()
            return procedure_id


async def _store():
    db = DatabaseOperations()
    await db.init_db()
    return ProcedureStore(db, tenant_id=settings.tenant_id, limit=settings.QUERY_PROCEDURES_MAX_PER_TENANT,
                          catalog_chars=settings.QUERY_PROCEDURES_CATALOG_CHARS)


async def procedure_catalog(run_id, entities):
    if not settings.QUERY_PROCEDURES_ENABLED:
        return []
    try:
        return await (await _store()).catalog(run_id, entities)
    except Exception:
        logger.exception('Procedure catalog unavailable; using normal discovery')
        return []


async def inspect_procedure(run_id, procedure_id):
    if not settings.QUERY_PROCEDURES_ENABLED:
        return None
    try:
        return await (await _store()).inspect(run_id, procedure_id)
    except Exception:
        logger.exception('Procedure inspection unavailable; using normal discovery')
        return None


async def record_procedure_reuse(run_id, procedure_id, *, failed=False):
    try:
        await (await _store()).record_reuse(run_id, procedure_id, failed=failed)
    except Exception:
        logger.exception('Could not record procedure reuse outcome')


async def save_successful_procedure(*, run_id, result, event, artifacts_file):
    """One post-execution hook shared by web, Slack, and Teams; best effort only."""
    if not settings.QUERY_PROCEDURES_ENABLED:
        return None
    try:
        if getattr(result, 'reusable_procedure', None) and getattr(result, 'completed_result', None) is not None:
            return result.reusable_procedure['procedure_id']  # Already recorded by the shared executor.
        if (not result.success or result.is_degraded_success or result.is_special_tool
                or not result.script_code or event.get('success') is False):
            return None
        metadata = event.get('metadata') or {}
        if event.get('display_type') != 'table' and metadata.get('outcome') != 'empty':
            return None
        if (metadata.get('is_degraded_success') or metadata.get('is_partial')
                or metadata.get('outcome') in {'fail', 'degraded_success', 'clarify'}):
            return None
        synthesis = getattr(result, 'synthesis_result', None)
        classification = getattr(synthesis, 'procedure_metadata', None)
        if classification is None:
            return None
        previous = getattr(result, 'reusable_procedure', None)
        evidence = retrieval_evidence(artifacts_file, previous)
        procedure_id = await (await _store()).save(run_id, result.script_code,
            event.get('summary') or metadata.get('summary') or '', evidence, result.data_source_type,
            classification=classification, output_fields=executed_fields(event),
            parent_id=(previous or {}).get('procedure_id'))
        if procedure_id:
            event.setdefault('metadata', {})['procedure_id'] = procedure_id
        return procedure_id
    except Exception:
        logger.exception('Could not save reusable procedure; query result remains available')
        return None
