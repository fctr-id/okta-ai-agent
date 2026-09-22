"""Shared validated retrieval-script execution for bot and saved-procedure runs."""
import asyncio
import json
from pathlib import Path
import shutil
import sys
from src.utils.logging import get_logger

logger = get_logger(__name__)


def execution_evidence(code: str) -> dict:
    """Bounded source evidence of a successful run, scoped to its conversation."""
    return {'script': code[:16000], 'script_truncated': len(code) > 16000,
            'description': 'Source executed successfully for this saved result; not proof of completeness or current data.'}


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


async def execute_script(code: str, directory: Path, *, timeout=120, cancellation_check=None) -> dict:
    from src.data.schemas.runtime_storage import prepare_runtime_script_code
    from src.utils.security_config import validate_generated_code

    validation = validate_generated_code(code)
    if not validation.is_valid:
        logger.error("Generated script rejected: %s", validation.violations)
        raise ValueError("Generated script failed security validation")
    project_root = Path(__file__).resolve().parents[2]
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "execution.py"
    helper = directory / "base_okta_api_client.py"
    proc = None
    communication = None
    try:
        if cancellation_check and cancellation_check():
            raise asyncio.CancelledError()
        shutil.copy2(project_root / "src/core/okta/client/base_okta_api_client.py", helper)
        script.write_text(prepare_runtime_script_code(code), encoding="utf-8")
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-u", str(script.resolve()), cwd=project_root,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        communication = asyncio.create_task(proc.communicate())
        deadline = asyncio.get_running_loop().time() + timeout
        while not communication.done():
            if cancellation_check and cancellation_check():
                raise asyncio.CancelledError()
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError('Retrieval script timed out')
            await asyncio.wait({communication}, timeout=min(0.2, remaining))
        stdout, stderr = communication.result()
        from src.core.retrieval_outcomes import check_retrieval_outcomes
        check_retrieval_outcomes(stderr.decode("utf-8", errors="replace"))
        if proc.returncode:
            logger.error("Retrieval script failed (exit %s): %s", proc.returncode, stderr.decode("utf-8", errors="replace")[-2000:])
            raise ValueError("Script execution failed")
        payload = parse_output(stdout.decode("utf-8", errors="replace"))
        payload['metadata'] = {**(payload.get('metadata') or {}), 'execution_evidence': execution_evidence(code)}
        return payload
    finally:
        if proc is not None and proc.returncode is None:
            proc.kill()
            await proc.wait()
        if communication is not None and not communication.done():
            communication.cancel()
            await asyncio.gather(communication, return_exceptions=True)
        script.unlink(missing_ok=True)
        helper.unlink(missing_ok=True)
