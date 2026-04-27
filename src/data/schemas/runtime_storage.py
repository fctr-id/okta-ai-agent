"""Runtime session and turn folder helpers.

The durable runtime stores conversation-safe metadata, artifacts, result refs,
and compact summaries. Generated scripts and stdout/stderr are execution details
and should not be part of the long-lived turn contract by default.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional


RUNTIME_ROOT = Path("src/data/runtime")


@dataclass(frozen=True)
class RuntimeTurnPaths:
    user_id: str
    session_id: str
    run_id: str
    turn_number: int
    session_dir: Path
    turn_dir: Path
    artifacts_dir: Path
    results_dir: Path
    session_metadata_file: Path
    conversation_index_file: Path
    turn_metadata_file: Path
    turn_summary_file: Path
    artifacts_file: Path
    result_index_file: Path

    def as_metadata(self) -> Dict[str, Any]:
        metadata = asdict(self)
        for key, value in list(metadata.items()):
            if isinstance(value, Path):
                metadata[key] = value.as_posix()
        return metadata


def sanitize_path_part(value: str, *, fallback: str = "unknown") -> str:
    """Return a filesystem-safe path segment while keeping it recognizable."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    cleaned = cleaned.strip(".-_")
    return cleaned[:96] or fallback


def create_runtime_turn_paths(
    *,
    user_id: str,
    run_id: str,
    session_id: Optional[str] = None,
    root: Path = RUNTIME_ROOT,
) -> RuntimeTurnPaths:
    """Create the runtime folder structure for one user turn/run."""
    safe_user_id = sanitize_path_part(user_id, fallback="user")
    safe_session_id = sanitize_path_part(session_id or run_id, fallback="session")
    safe_run_id = sanitize_path_part(run_id, fallback="run")

    session_dir = root / "sessions" / f"{safe_user_id}-{safe_session_id}"
    turns_dir = session_dir / "turns"
    turn_number = _next_turn_number(turns_dir)
    turn_dir = turns_dir / f"{turn_number:04d}-{safe_run_id}"

    paths = RuntimeTurnPaths(
        user_id=safe_user_id,
        session_id=safe_session_id,
        run_id=safe_run_id,
        turn_number=turn_number,
        session_dir=session_dir,
        turn_dir=turn_dir,
        artifacts_dir=turn_dir / "artifacts",
        results_dir=turn_dir / "results",
        session_metadata_file=session_dir / "session_metadata.json",
        conversation_index_file=session_dir / "conversation_index.json",
        turn_metadata_file=turn_dir / "turn_metadata.json",
        turn_summary_file=turn_dir / "turn_summary.json",
        artifacts_file=turn_dir / "artifacts" / "artifacts.json",
        result_index_file=turn_dir / "results" / "index.json",
    )

    for directory in (
        paths.artifacts_dir,
        paths.results_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    _ensure_json_file(paths.artifacts_file, [])
    _ensure_json_file(paths.result_index_file, [])
    _write_session_metadata(paths)
    _write_turn_metadata(paths, status="created")
    _append_conversation_index(paths)
    return paths


def update_turn_metadata(paths: RuntimeTurnPaths, **updates: Any) -> Dict[str, Any]:
    """Merge updates into turn metadata and persist it."""
    metadata = _load_json_object(paths.turn_metadata_file)
    metadata.update(updates)
    metadata["updated_at"] = time.time()
    _write_json(paths.turn_metadata_file, metadata)
    return metadata


def write_turn_summary(paths: RuntimeTurnPaths, summary: Dict[str, Any]) -> None:
    """Persist lightweight turn summary for future conversation history."""
    payload = {
        "user_id": paths.user_id,
        "session_id": paths.session_id,
        "run_id": paths.run_id,
        "turn_number": paths.turn_number,
        "created_at": time.time(),
        **summary,
    }
    _write_json(paths.turn_summary_file, payload)


def prepare_runtime_script_code(code: str) -> str:
    """Make generated scripts portable regardless of execution staging folder."""
    modified_code = code.replace(
        "from src.core.okta.client.base_okta_api_client import OktaAPIClient",
        "from base_okta_api_client import OktaAPIClient",
    )
    modified_code = modified_code.replace(
        'script_dir.parent / "sqlite_db" / "okta_sync.db"',
        'project_root / "sqlite_db" / "okta_sync.db"',
    )
    modified_code = modified_code.replace(
        "script_dir.parent / 'sqlite_db' / 'okta_sync.db'",
        "project_root / 'sqlite_db' / 'okta_sync.db'",
    )

    if "# === Tako Runtime Bootstrap ===" in modified_code:
        return modified_code

    bootstrap = '''# === Tako Runtime Bootstrap ===
import sys as _tako_sys
from pathlib import Path as _TakoPath

def _tako_find_project_root():
    _path = _TakoPath(__file__).resolve().parent
    while _path != _path.parent:
        if (_path / "requirements.txt").exists() or (_path / ".env").exists():
            return _path
        _path = _path.parent
    return _TakoPath.cwd()

project_root = _tako_find_project_root()
_tako_script_dir = _TakoPath(__file__).resolve().parent
for _tako_path in (_tako_script_dir, project_root):
    if str(_tako_path) not in _tako_sys.path:
        _tako_sys.path.insert(0, str(_tako_path))
# === End Tako Runtime Bootstrap ===

'''
    return bootstrap + modified_code


def _next_turn_number(turns_dir: Path) -> int:
    if not turns_dir.exists():
        return 1

    max_turn = 0
    for child in turns_dir.iterdir():
        if not child.is_dir():
            continue
        prefix = child.name.split("-", 1)[0]
        if prefix.isdigit():
            max_turn = max(max_turn, int(prefix))
    return max_turn + 1


def _write_session_metadata(paths: RuntimeTurnPaths) -> None:
    if paths.session_metadata_file.exists():
        return

    _write_json(
        paths.session_metadata_file,
        {
            "user_id": paths.user_id,
            "session_id": paths.session_id,
            "created_at": time.time(),
            "runtime_version": 1,
        },
    )


def _write_turn_metadata(paths: RuntimeTurnPaths, *, status: str) -> None:
    _write_json(
        paths.turn_metadata_file,
        {
            "user_id": paths.user_id,
            "session_id": paths.session_id,
            "run_id": paths.run_id,
            "turn_number": paths.turn_number,
            "status": status,
            "created_at": time.time(),
            "paths": paths.as_metadata(),
        },
    )


def _append_conversation_index(paths: RuntimeTurnPaths) -> None:
    index = _load_json_list(paths.conversation_index_file)
    turn_entry = {
        "turn_number": paths.turn_number,
        "run_id": paths.run_id,
        "turn_dir": paths.turn_dir.as_posix(),
        "turn_metadata_file": paths.turn_metadata_file.as_posix(),
        "turn_summary_file": paths.turn_summary_file.as_posix(),
        "created_at": time.time(),
    }
    index.append(turn_entry)
    _write_json(paths.conversation_index_file, index)


def _ensure_json_file(path: Path, default_value: Any) -> None:
    if path.exists():
        return
    _write_json(path, default_value)


def _load_json_object(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as file_handle:
            value = json.load(file_handle)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _load_json_list(path: Path) -> list[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as file_handle:
            value = json.load(file_handle)
    except json.JSONDecodeError:
        return []
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file_handle:
        json.dump(payload, file_handle, indent=2, default=str)


__all__ = [
    "RUNTIME_ROOT",
    "RuntimeTurnPaths",
    "create_runtime_turn_paths",
    "prepare_runtime_script_code",
    "sanitize_path_part",
    "update_turn_metadata",
    "write_turn_summary",
]
