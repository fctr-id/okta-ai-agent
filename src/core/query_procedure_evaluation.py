"""Optional CLI evaluation report. No additional model requests or result rows."""
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from src.config.settings import settings
from src.core.okta.sync.operations import DatabaseOperations
from src.data.schemas.query_procedure import executed_fields


class ProcedureEvaluation:
    def __init__(self, path, query):
        from src.core.agents.synthesis_agent import synthesis_agent
        from src.core.agents.supervisor_agent import supervisor_agent
        self.path = Path(path)
        if self.path.exists():
            raise ValueError('Evaluation report already exists; use a new filename to preserve the baseline')
        self.started = time.monotonic()
        self.report = {
            'question': query, 'started_at': datetime.now(timezone.utc).isoformat(),
            'synthesis_prompt_sha256': hashlib.sha256(
                (Path(__file__).parent / 'agents/prompts/synthesis_prompt.txt').read_bytes()).hexdigest(),
            'configured_models': {
                'reasoning': supervisor_agent.model.model_name,
                'coding': synthesis_agent.model.model_name,
            },
        }

    def observe(self, result):
        synthesis = getattr(result, 'synthesis_result', None)
        classification = getattr(synthesis, 'procedure_metadata', None)
        self.report.update(
            outcome=result.outcome, error=result.error, phases=result.phases_executed,
            data_source=result.data_source_type, total_requests=result.total_requests,
            response_models=getattr(synthesis, '_response_models', []),
            classification=classification.model_dump() if classification else None,
            script_sha256=hashlib.sha256((result.script_code or '').encode()).hexdigest(),
            procedure_reuse=getattr(result, 'procedure_reuse', None),
            supervisor_decisions=[decision for decision in result.supervisor_decisions],
        )
        if (getattr(result, 'reusable_procedure', None)
                and getattr(result, 'procedure_reuse', None) != 'adapted'):
            self.report['classification'] = result.reusable_procedure['classification']

    def output(self, event):
        metadata = event.get('metadata') or {}
        self.report.update(
            result_count=len(event.get('data', event.get('results', []))),
            output_fields=executed_fields(event),
            result_summary=event.get('summary') or metadata.get('summary'),
            procedure_id=metadata.get('procedure_id'),
        )

    def finish(self, exit_code):
        self.report.update(exit_code=exit_code, execution_status='success' if exit_code == 0 else 'failed',
                           elapsed_seconds=round(time.monotonic() - self.started, 2))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.report, indent=2), encoding='utf-8')
        print(f'Evaluation report: {self.path.resolve()}')


async def register_cli_turn(paths, query):
    """Use the same server-owned actor/turn mapping as the other transports."""
    db = DatabaseOperations()
    await db.init_db()
    session = await db.create_conversation_session(
        tenant_id=settings.tenant_id, user_id=paths.user_id, session_id=paths.session_id,
        source='cli', title=query[:120],
    )
    if session is None:
        raise ValueError('Could not register CLI session')
    turn = await db.create_conversation_turn(
        tenant_id=settings.tenant_id, user_id=paths.user_id, session_id=paths.session_id,
        run_id=paths.run_id, query_text=query, source='cli',
        turn_dir=str(paths.turn_dir), artifact_file=str(paths.artifacts_file),
    )
    if turn is None:
        raise ValueError('Could not register CLI turn')
