"""Bridge to existing agent orchestration without importing the Slack or web UI."""
import asyncio
import json
from pathlib import Path
import shutil
import sys
import time
from src.utils.logging import get_logger
from . import sessions
from src.integrations.conversation_results import save_result
from src.core.okta.sync.operations import DatabaseOperations
from src.config.settings import settings

logger = get_logger(__name__)


from src.core.script_execution import parse_output, execute_script
from src.core.retrieval_outcomes import RetrievalFailure


async def run_query(job: dict, *, orchestrate=None) -> dict:
    from src.core.okta.client import OktaClient
    from src.data.schemas.runtime_storage import create_runtime_turn_paths, update_turn_metadata, write_turn_summary
    if orchestrate is None:
        from src.core.agents.orchestrator import execute_multi_agent_query
        orchestrate = execute_multi_agent_query

    paths = await sessions.begin_turn(job)
    update_turn_metadata(paths, source="teams", status="executing", user_query=job["query"],
                         conversation=job["conversation"])
    client = OktaClient()
    try:
        result = await orchestrate(
            user_query=job["query"], correlation_id=job["id"], artifacts_file=paths.artifacts_file,
            okta_client=client, cancellation_check=lambda: False, user_timezone=job.get("timezone"),
        )
        outcome = result.outcome
        if outcome == "clarify":
            response = {"display_type": "markdown", "content": result.user_message or "Please add more detail to your question."}
        elif not result.success:
            logger.error("Teams request %s failed: %s", job["id"], result.error)
            response = {"display_type": "markdown", "content": result.user_message or "I couldn't complete this request. Please try again."}
            outcome = "fail"
        elif result.no_data_found:
            response = {"display_type": "markdown", "content": result.user_message or "No matching records found."}
        elif result.completed_result is not None:
            response = result.completed_result_event()
        elif result.is_special_tool:
            response = {"display_type": "markdown", "content": result.script_code or result.user_message or "Completed."}
        elif result.script_code:
            try:
                response = await execute_script(result.script_code, paths.turn_dir / "execution")
            except RetrievalFailure as exc:
                from src.core.execution_recovery import recover_failed_execution
                try:
                    response = await recover_failed_execution(
                        result=result, failure=exc, user_query=job['query'], correlation_id=job['id'],
                        artifacts_file=paths.artifacts_file, okta_client=client,
                        cancellation_check=lambda: False, user_timezone=job.get('timezone'),
                        orchestrate=orchestrate,
                    )
                    outcome = result.outcome
                except RetrievalFailure as final_failure:
                    exc = final_failure
                    response = None
                if response is None:
                    result.success = False
                    result.outcome = outcome = 'fail'
                    result.result_mode = 'failed'
                    result.is_degraded_success = False
                    result.error = result.outcome_reason = str(exc)
                    result.user_message = str(exc)
                    response = {'display_type': 'markdown', 'content': str(exc), 'success': False}
        else:
            raise ValueError("Successful orchestration returned no result or script")
        response["outcome"] = outcome
        if hasattr(result, "outcome_metadata"):
            response["metadata"] = {**(response.get("metadata") or {}), **result.outcome_metadata()}
        from src.core.query_procedures import save_successful_procedure
        await save_successful_procedure(
            run_id=job['id'], result=result, event=response, artifacts_file=paths.artifacts_file,
        )
        save_result(paths, response)
        write_turn_summary(paths, {
            "source": "teams", "status": outcome, "user_query": job["query"],
            "final_response_summary": response.get("content") or f"Returned {response.get('count', 0)} records",
            "display_type": response.get("display_type"), "result_count": response.get("count", 0),
            "outcome": response.get("metadata", {}),
        })
        update_turn_metadata(paths, status=outcome, completed_at=time.time())
        response["result_reference"] = f"{paths.session_id}:{paths.turn_number}"

        return response
    except asyncio.CancelledError:
        update_turn_metadata(paths, status="interrupted")
        raise
    except Exception:
        update_turn_metadata(paths, status="error")
        raise
    finally:
        try:
            await DatabaseOperations().mirror_runtime_turn_state(
                tenant_id=settings.tenant_id, run_id=job["id"], runtime_paths=paths,
            )
        finally:
            await client.close_session()


async def sync_status() -> dict:
    from src.config.settings import settings
    from src.core.okta.sync.operations import DatabaseOperations

    db = DatabaseOperations()
    async with db.get_session() as session:
        sync = await db.get_last_completed_sync(session, settings.tenant_id)
        if not sync:
            return {"content": "No completed data sync yet. Start a sync in the Tako web app."}
        return {"content": f"Last completed sync: {sync.end_time}. Users: {sync.users_count or 0}; "
                           f"groups: {sync.groups_count or 0}; apps: {sync.apps_count or 0}."}
