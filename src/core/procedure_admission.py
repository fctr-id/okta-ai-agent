"""Asynchronous, durable admission to the reusable-query library."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import select, text

from src.core.okta.sync.models import QueryProcedure, QueryProcedureAdmission
from src.core.query_procedures import _store
from src.utils.logging import get_logger
from src.utils.security_config import validate_generated_code

logger = get_logger(__name__)
PROMPT = (Path(__file__).parent / 'agents/prompts/procedure_admission_prompt.txt').read_text(encoding='utf-8')
MODEL_TIMEOUT = 60
LEASE_SECONDS = 120


class AdmissionDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    decision: Literal['duplicate', 'useful_variant', 'distinct']
    duplicate_id: str | None = None

    @model_validator(mode='after')
    def duplicate_target(self):
        if (self.decision == 'duplicate') != bool(self.duplicate_id):
            raise ValueError('Only duplicate decisions require an existing procedure ID')
        return self


def comparison_metadata(values):
    """Explicit allowlist: never send code, evidence, summaries, or result rows."""
    metadata = values['classification_json']
    return dict(question=values['query_text'], purpose=values['description'],
                scope=metadata['scope'], entities=metadata['entities'],
                parameters=metadata['parameters'], classification=metadata['classification'],
                data_source=values['data_source'], output_fields=values['output_fields_json'])


async def compare_candidate(candidate, existing):
    # Lazy model creation: startup and empty libraries need no model call.
    from pydantic_ai.usage import UsageLimits
    from src.core.agents import build_agent
    from src.core.models.model_picker import ModelType
    agent = build_agent(ModelType.REASONING, name='procedure_admission',
                        output_type=AdmissionDecision, instructions=PROMPT)
    result = await agent.run(json.dumps({'new_query': candidate, 'existing_queries': existing}),
                             usage_limits=UsageLimits(request_limit=2))
    logger.info('Procedure admission model=%s requests=%s input_tokens=%s output_tokens=%s',
                agent.model.model_name, result.usage.requests,
                result.usage.input_tokens, result.usage.output_tokens)
    return result.output


class AdmissionQueue:
    def __init__(self, store, compare=compare_candidate):
        self.store, self.compare = store, compare
        self.last_outcome = None

    async def claim(self):
        """One leased comparison per tenant, including across API worker processes."""
        now = datetime.now(timezone.utc)
        async with self.store.db.get_session() as session:
            await session.execute(text('BEGIN IMMEDIATE'))
            tenant = QueryProcedureAdmission.tenant_id == self.store.tenant_id
            busy = (await session.execute(select(QueryProcedureAdmission.admission_id)
                .where(tenant, QueryProcedureAdmission.lease_until > now).limit(1))).scalar_one_or_none()
            if busy:
                return None
            item = (await session.execute(select(QueryProcedureAdmission).where(
                tenant, QueryProcedureAdmission.next_attempt_at <= now)
                .order_by(QueryProcedureAdmission.created_at, QueryProcedureAdmission.admission_id)
                .limit(1))).scalar_one_or_none()
            if item is None:
                return None
            item.lease_token = str(uuid4())
            item.lease_until = now + timedelta(seconds=LEASE_SECONDS)
            item.attempts += 1
            claim = (item.admission_id, item.lease_token, item.payload_json)
            await session.commit()
            return claim

    async def candidates(self, values):
        """Compare only accessible entries of the same sharing classification."""
        # No conversation lookup: the verified owner was snapshotted at enqueue.
        async with self.store.db.get_session() as session:
            records = (await session.execute(select(QueryProcedure).where(
                *self.store.eligible(values['owner_id']),
                QueryProcedure.classification_json['classification'].as_string()
                    == values['classification_json']['classification'])
                .order_by(QueryProcedure.last_used_at.desc(), QueryProcedure.procedure_id)
                .limit(self.store.limit))).scalars().all()
            entities = set(values['classification_json']['entities'])
            records = [row for row in records if entities.intersection(row.classification_json.get('entities', []))]
            records.sort(key=lambda row: -len(entities.intersection(row.classification_json['entities'])))
            output = []
            for row in records:
                if not validate_generated_code(row.script_code).is_valid:
                    continue
                entry = comparison_metadata({column.name: getattr(row, column.name)
                                             for column in QueryProcedure.__table__.columns})
                entry['procedure_id'] = row.procedure_id
                proposed = output + [entry]
                if len(json.dumps(proposed)) <= self.store.catalog_chars:
                    output = proposed
                if len(output) >= 32:
                    break
            return output

    async def retry(self, admission_id, token, *, immediate=False):
        async with self.store.db.get_session() as session:
            await session.execute(text('BEGIN IMMEDIATE'))
            item = await session.get(QueryProcedureAdmission, admission_id)
            if item is None or item.lease_token != token:
                return
            delay = 0 if immediate else min(3600, 300 * 2 ** min(item.attempts - 1, 4))
            item.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
            item.lease_until = item.lease_token = None
            await session.commit()

    async def process_one(self):
        claim = await self.claim()
        if claim is None:
            return False
        admission_id, token, values = claim
        try:
            # Changed execution contracts must go through a new successful execution.
            if (values['compatibility_key'] != self.store.compatibility
                    or not validate_generated_code(values['script_code']).is_valid):
                await self.finish(admission_id, token, values, None, [])
                return True
            candidates = await self.candidates(values)
            decision = (await asyncio.wait_for(self.compare(comparison_metadata(values), candidates),
                        timeout=MODEL_TIMEOUT)) if candidates else AdmissionDecision(decision='distinct')
            decision = AdmissionDecision.model_validate(decision)
            if decision.decision == 'duplicate':
                existing = next((item for item in candidates if item['procedure_id'] == decision.duplicate_id), None)
                if existing is None:
                    raise ValueError('Admission selected an ID outside the supplied candidates')
                # Different required fields/source/entities cannot be silently discarded.
                if (set(existing['output_fields']) != set(values['output_fields_json'])
                        or existing['data_source'] != values['data_source']
                        or set(existing['entities']) != set(values['classification_json']['entities'])):
                    decision = AdmissionDecision(decision='useful_variant')
            await self.finish(admission_id, token, values, decision, candidates)
        except asyncio.CancelledError:
            await self.retry(admission_id, token, immediate=True)
            raise
        except Exception as exc:
            # Log type/ID only: provider exception text may contain query metadata.
            logger.warning('Procedure admission pending: id=%s error=%s', admission_id, type(exc).__name__)
            await self.retry(admission_id, token)
        return True

    async def finish(self, admission_id, token, values, decision, candidates):
        async with self.store.db.get_session() as session:
            await session.execute(text('BEGIN IMMEDIATE'))
            item = await session.get(QueryProcedureAdmission, admission_id)
            if item is None or item.lease_token != token:
                return  # Another worker recovered an expired lease.
            if decision is not None and decision.decision == 'duplicate':
                existing = (await session.execute(select(QueryProcedure).where(
                    *self.store.eligible(values['owner_id']),
                    QueryProcedure.procedure_id == decision.duplicate_id))).scalar_one_or_none()
                snapshot = next(row for row in candidates if row['procedure_id'] == decision.duplicate_id)
                current = comparison_metadata({column.name: getattr(existing, column.name)
                    for column in QueryProcedure.__table__.columns}) if existing else None
                if (current != {key: value for key, value in snapshot.items() if key != 'procedure_id'}
                        or not validate_generated_code(existing.script_code).is_valid):
                    # Library changed during the remote call. Compare again without dropping the candidate.
                    item.lease_until = item.lease_token = None
                    await session.commit()
                    return
                existing.execution_count += 1
                existing.last_used_at = datetime.now(timezone.utc)
                # Do not change the existing script, owner, evidence or successful-reuse counter.
                procedure_id = existing.procedure_id
            elif decision is not None:
                values = dict(values)
                for key in ('created_at', 'last_used_at'):
                    values[key] = datetime.fromisoformat(values[key])
                procedure_id = await self.store._persist(session, values)
            else:
                procedure_id = None
            await session.delete(item)
            await session.commit()
        logger.info('Procedure admission: id=%s decision=%s procedure=%s', admission_id,
                    decision.decision if decision else 'invalid_candidate', procedure_id)
        self.last_outcome = (admission_id, decision.decision if decision else 'invalid_candidate', procedure_id)


async def run_admission_worker():
    """Startup resumes pending checks, including work interrupted by container restarts."""
    queue = None
    while True:
        try:
            if queue is None:
                queue = AdmissionQueue(await _store())
            while await queue.process_one():
                pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning('Procedure admission worker retrying: error=%s', type(exc).__name__)
        await asyncio.sleep(5)


async def finish_cli_admission(event):
    """CLI has no resident worker; try admission after displaying/exporting the answer."""
    metadata = event.get('metadata') or {}
    admission_id = metadata.get('procedure_admission_id')
    if not admission_id:
        return
    try:
        queue = AdmissionQueue(await _store())
    except Exception as exc:
        logger.warning('CLI admission remains pending: error=%s', type(exc).__name__)
        return

    async def drain():
        while True:
            async with queue.store.db.get_session() as session:
                item = await session.get(QueryProcedureAdmission, admission_id)
                if item is None:
                    metadata['procedure_admission'] = 'processed'
                    return
                # A failed comparison remains durable for the server/next CLI run.
                due = item.next_attempt_at.replace(tzinfo=timezone.utc)
                if due > datetime.now(timezone.utc):
                    return
            if await queue.process_one():
                if queue.last_outcome and queue.last_outcome[0] == admission_id:
                    _, decision, procedure_id = queue.last_outcome
                    metadata['procedure_admission'] = decision
                    if procedure_id:
                        metadata['procedure_id'] = procedure_id
                    return
            else:
                await asyncio.sleep(0.2)
    try:
        await asyncio.wait_for(drain(), timeout=65)
    except TimeoutError:
        logger.info('Procedure admission remains pending for a later worker: id=%s', admission_id)
    except Exception as exc:
        logger.warning('CLI admission remains pending: error=%s', type(exc).__name__)
