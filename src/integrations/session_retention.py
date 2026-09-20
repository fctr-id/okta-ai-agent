"""Remove expired integration runtime folders within a configured root."""
import os
from pathlib import Path
import re
import shutil

_GUID = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
# Include the earlier tenant/user GUID format so interrupted old folders expire.
_SESSION_NAME = re.compile(rf"teams-(?:[A-Za-z0-9_-]{{16}}u|[0-9a-f]{{32}}|{_GUID}-{_GUID})-(?:{_GUID}|[0-9a-f]{{32}})\Z")


def _is_link(path: Path) -> bool:
    # Windows junctions/reparse points must not redirect a recursive deletion.
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _raise_scan_error(error: OSError) -> None:
    raise error


def _expired(session: Path, cutoff: float, active_run_ids: set[str]) -> bool:
    if _is_link(session) or session.stat().st_mtime >= cutoff:
        return False
    for directory, directories, files in os.walk(session, followlinks=False, onerror=_raise_scan_error):
        for name in directories + files:
            path = Path(directory) / name
            if _is_link(path) or path.stat().st_mtime >= cutoff:
                return False
            if name[5:] in active_run_ids:  # Turn folder: 0001-<run UUID>.
                return False
    return True


def remove_expired_sessions(runtime_root: Path, *, cutoff: float, active_run_ids: set[str],
                            session_pattern: re.Pattern = _SESSION_NAME,
                            protected_sessions: set[str] | None = None) -> int:
    sessions_root = runtime_root.resolve() / "sessions"
    if not sessions_root.exists() or _is_link(sessions_root):
        return 0
    removed = 0
    for candidate in sessions_root.iterdir():
        if candidate.name in (protected_sessions or set()):
            continue
        if not session_pattern.fullmatch(candidate.name) or not candidate.is_dir():
            continue
        # Check the absolute target against the intended root before any deletion.
        if _is_link(candidate) or candidate.resolve().parent != sessions_root:
            continue
        try:
            if _expired(candidate, cutoff, active_run_ids):
                shutil.rmtree(candidate)
                removed += 1
        except FileNotFoundError:
            continue  # A concurrent/manual cleanup may already have removed it.
    return removed
