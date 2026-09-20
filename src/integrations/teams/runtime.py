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


def parse_output(stdout: str) -> dict:
    marker = "QUERY RESULTS"
    lines = stdout.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == marker) + 1
    except StopIteration as exc:
        raise ValueError("Script produced no results envelope") from exc
    payload = []
    for line in lines[start:]:
        if line.strip().startswith("===="):
            if payload:
                break
            continue
        if line.strip():
            payload.append(line)
    result = json.loads("\n".join(payload))
    if isinstance(result, list):
        result = {"display_type": "table", "data": result}
    if not isinstance(result, dict):
        raise ValueError("Invalid script result")
    if result.get("display_type") == "markdown" and isinstance(result.get("content"), str):
        return result
    rows = result.get("data", result.get("results"))
    if not isinstance(rows, list):
        raise ValueError("Script result is missing rows")
    return {**result, "display_type": "table", "results": rows, "count": len(rows)}


async def execute_script(code: str, directory: Path, *, timeout=120) -> dict:
    from src.data.schemas.runtime_storage import prepare_runtime_script_code
    from src.utils.security_config import validate_generated_code

    validation = validate_generated_code(code)
    if not validation.is_valid:
        logger.error("Teams generated script rejected: %s", validation.violations)
        raise ValueError("Generated script failed security validation")
    project_root = Path(__file__).resolve().parents[3]
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "execution.py"
    helper = directory / "base_okta_api_client.py"
    proc = None
    try:
        shutil.copy2(project_root / "src/core/okta/client/base_okta_api_client.py", helper)
        script.write_text(prepare_runtime_script_code(code), encoding="utf-8")
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-u", str(script.resolve()), cwd=project_root,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
        if proc.returncode:
            logger.error("Teams script failed (exit %s): %s", proc.returncode, stderr.decode("utf-8", errors="replace")[-2000:])
            raise ValueError("Script execution failed")
        return parse_output(stdout.decode("utf-8", errors="replace"))
    finally:
        if proc is not None and proc.returncode is None:
            proc.kill()
            await proc.wait()
        script.unlink(missing_ok=True)
        helper.unlink(missing_ok=True)


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
            response = await execute_script(result.script_code, paths.turn_dir / "execution")
        else:
            raise ValueError("Successful orchestration returned no result or script")
        response["outcome"] = outcome
        if hasattr(result, "outcome_metadata"):
            response["metadata"] = {**(response.get("metadata") or {}), **result.outcome_metadata()}
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
