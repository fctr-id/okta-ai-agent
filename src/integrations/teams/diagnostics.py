"""Failure locations and HTTP statuses without exception bodies or credentials."""
import traceback
from pathlib import Path

import httpx


def failure_details(exc: BaseException) -> str:
    parts = []
    seen = set()
    while exc is not None and id(exc) not in seen and len(seen) < 5:
        seen.add(id(exc))
        parts.append(type(exc).__name__)
        if isinstance(exc, httpx.HTTPStatusError):
            parts.append(f"http_status={exc.response.status_code}")
            # Never include URL paths, query strings, response bodies or headers.
            parts.append(f"http_host={exc.request.url.host}")
        if isinstance(exc, FileNotFoundError) and exc.filename:
            parts.append(f"missing_file={Path(exc.filename).name!r}")
        frames = traceback.walk_tb(exc.__traceback__)
        parts.append("frames=" + " > ".join(
            f"{Path(frame.f_code.co_filename).name}:{line}:{frame.f_code.co_name}"
            for frame, line in frames
        ))
        exc = exc.__cause__ or (None if exc.__suppress_context__ else exc.__context__)
    return " | ".join(parts)
