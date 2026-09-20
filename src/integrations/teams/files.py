"""Native Teams personal-chat file consent and bounded OneDrive uploads."""
import csv
import json
from urllib.parse import urlsplit

import httpx

from .sessions import saved_turn

CHUNK_BYTES = 10 * 320 * 1024


def cloud_url(value, *, content=False):
    if not isinstance(value, str) or len(value) > 16000:
        raise ValueError("Invalid file URL")
    url = urlsplit(value)
    host = url.hostname or ""
    allowed = host.endswith(".sharepoint.com") or (not content and host.endswith(".up.1drv.com"))
    if (url.scheme != "https" or not allowed or url.port not in (None, 443)
            or url.username or url.password or url.fragment):
        raise ValueError("Unsupported OneDrive file URL")
    return value


def validate_upload_info(value):
    if not isinstance(value, dict):
        raise ValueError("Missing upload information")
    return {
        "uploadUrl": cloud_url(value.get("uploadUrl")),
        "contentUrl": cloud_url(value.get("contentUrl"), content=True),
        "uniqueId": str(value.get("uniqueId") or "")[:255],
    }


def _cell(value):
    value = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
    # Preserve text as text when spreadsheet applications open the export.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


async def export_path(job, reference, retention_hours):
    path = await saved_turn(job, reference, retention_hours)
    if path is None:
        return None
    target = path / "results" / "export.csv"
    if target.exists():
        return target
    import asyncio
    return await asyncio.to_thread(_write_csv, path, target)


def _write_csv(path, target):
    payload = json.loads((path / "results" / "response.json").read_text(encoding="utf-8"))
    rows = payload.get("results", payload.get("data", []))
    if payload.get("display_type") == "markdown" or not isinstance(rows, list) or not rows:
        return None
    headers = payload.get("headers") or (list(rows[0]) if isinstance(rows[0], dict) else [f"Column {i + 1}" for i in range(len(rows[0]))])
    columns = []
    for header in headers:
        if isinstance(header, dict):
            key = header.get("value") or header.get("key") or header.get("text") or header.get("title")
            columns.append((header.get("text") or header.get("title") or key, key))
        else:
            columns.append((header, header))
    temporary = target.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([_cell(label) for label, _ in columns])
        for row in rows:
            writer.writerow([_cell(row.get(key, "") if isinstance(row, dict) else row[i] if i < len(row) else "")
                             for i, (_, key) in enumerate(columns)])
    temporary.replace(target)
    return target


def consent_attachment(token, size):
    return {
        "contentType": "application/vnd.microsoft.teams.card.file.consent",
        "name": "Tako-results.csv",
        "content": {
            "description": "Save these retrieved results to OneDrive. AI can make mistakes; please validate the data.",
            "sizeInBytes": size, "acceptContext": {"download_id": token}, "declineContext": {"download_id": token},
        },
    }


def file_attachment(info):
    return {
        "contentType": "application/vnd.microsoft.teams.card.file.info",
        "contentUrl": info["contentUrl"], "name": "Tako-results.csv",
        "content": {"uniqueId": info["uniqueId"], "fileType": "csv"},
    }


async def upload_csv(path, info, *, http=None):
    info = validate_upload_info(info)
    own_client = http is None
    client = http or httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False)
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            offset = 0
            while chunk := handle.read(CHUNK_BYTES):
                response = await client.put(info["uploadUrl"], content=chunk, headers={
                    "Content-Type": "application/octet-stream",
                    "Content-Range": f"bytes {offset}-{offset + len(chunk) - 1}/{size}",
                })
                response.raise_for_status()
                offset += len(chunk)
                expected = (200, 201) if offset == size else (202,)
                if response.status_code not in expected:
                    raise ValueError("Unexpected OneDrive upload response")
        return info
    finally:
        if own_client:
            await client.aclose()
