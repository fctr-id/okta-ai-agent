"""One bounded saved-script attempt; errors return control to normal discovery."""
import asyncio
from pathlib import Path

from src.core.query_procedures import inspect_procedure, record_procedure_reuse
from src.core.script_execution import execute_script
from src.data.schemas.query_procedure import executed_fields
from src.utils.logging import get_logger

logger = get_logger(__name__)


async def execute_selected_procedure(*, run_id, procedure_id, artifacts_file, cancellation_check):
    candidate = await inspect_procedure(run_id, procedure_id)
    if candidate is None:
        return None
    try:
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
        if rows and set(fields) != set(candidate['output_fields']):
            raise ValueError('Reused script output fields changed; rediscovery required')
        payload['metadata'] = {
            'summary': payload.get('summary', ''),
            'procedure_id': procedure_id, 'procedure_reuse': 'used',
        }
        await record_procedure_reuse(run_id, procedure_id)
        logger.info('[%s] Procedure reused: %s rows=%d', run_id, procedure_id, len(rows))
        return candidate, payload
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception('[%s] Procedure execution failed; using normal discovery once: %s', run_id, procedure_id)
        await record_procedure_reuse(run_id, procedure_id, failed=True)
        return None
