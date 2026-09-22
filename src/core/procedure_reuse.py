"""One bounded saved-script attempt; errors return control to normal discovery."""
import asyncio
from pathlib import Path
from pydantic_ai.exceptions import UsageLimitExceeded

from src.core.query_procedures import inspect_procedure, record_procedure_reuse
from src.core.script_execution import execute_script
from src.core.retrieval_outcomes import RetrievalFailure
from src.data.schemas.query_procedure import executed_fields
from src.utils.logging import get_logger

logger = get_logger(__name__)


async def execute_selected_procedure(*, run_id, procedure_id, artifacts_file, cancellation_check, adapt_script=None,
                                     on_retrieval_failure=None):
    candidate = await inspect_procedure(run_id, procedure_id)
    if candidate is None:
        return None
    try:
        if adapt_script is not None:
            code = await adapt_script(candidate)
            if not code:
                raise ValueError('Saved script adaptation could not answer the request')
            candidate = {**candidate, 'script_code': code}
        payload = await execute_script(candidate['script_code'], Path(artifacts_file).parent / 'reuse-execution',
                                       cancellation_check=cancellation_check)
        if (payload.get('display_type') != 'table' or payload.get('success') is False
                or payload.get('is_partial') or payload.get('is_degraded_success')
                or payload.get('outcome') in {'fail', 'clarify', 'degraded_success'}
                or payload.get('metadata', {}).get('is_partial')
                or payload.get('metadata', {}).get('is_degraded_success')
                or payload.get('metadata', {}).get('outcome') in {'fail', 'clarify', 'degraded_success'}):
            raise ValueError('Reused script did not produce a complete table envelope')
        rows = payload.get('results', [])
        fields = executed_fields(payload)
        if adapt_script is None and rows and set(fields) != set(candidate['output_fields']):
            raise ValueError('Reused script output fields changed; rediscovery required')
        payload['metadata'] = {
            **({'execution_evidence': payload['metadata']['execution_evidence']}
               if payload.get('metadata', {}).get('execution_evidence') else {}),
            'summary': payload.get('summary', ''),
            ('parent_procedure_id' if adapt_script else 'procedure_id'): procedure_id,
            'procedure_reuse': 'adapted' if adapt_script else 'used',
        }
        if adapt_script is None:
            await record_procedure_reuse(run_id, procedure_id)
        logger.info('[%s] Procedure %s: %s rows=%d', run_id, 'adapted' if adapt_script else 'reused', procedure_id, len(rows))
        return candidate, payload
    except asyncio.CancelledError:
        raise
    except UsageLimitExceeded:
        raise
    except RetrievalFailure as exc:
        await record_procedure_reuse(run_id, procedure_id, failed=True)
        if not exc.rediscover:
            # Replanning cannot fix credentials, throttling, or an outage.
            raise
        if on_retrieval_failure:
            on_retrieval_failure(candidate['script_code'], exc)
        logger.warning('[%s] Saved retrieval failed (%s); using normal discovery once',
                       run_id, ', '.join(sorted(exc.categories)))
        return None
    except Exception:
        logger.exception('[%s] Procedure execution failed; using normal discovery once: %s', run_id, procedure_id)
        await record_procedure_reuse(run_id, procedure_id, failed=True)
        return None
