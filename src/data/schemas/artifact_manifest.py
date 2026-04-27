"""Artifact and result-set contracts for supervisor-safe data exchange.

These models are intentionally lightweight. Large payloads stay on disk while
agents and the future supervisor pass around summaries, manifests, and refs.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


SourceSpecialist = Literal["sql", "api", "special", "processor", "synthesis", "unknown"]
DerivationKind = Literal["initial", "filter", "enrichment", "join", "aggregation", "subset", "unknown"]
ResultSetStatus = Literal["available", "empty", "partial", "error"]
DelegationResultMode = Literal["continue", "synthesis_ready", "direct_answer", "failed", "needs_clarification"]


@dataclass
class ConversationDeps:
    """Shared dependency envelope for future supervisor and specialist runs."""

    request: str
    user_id: str
    run_id: str
    correlation_id: str
    artifacts_file: Path
    session_id: Optional[str] = None
    turn_number: Optional[int] = None
    artifact_keys: List[str] = field(default_factory=list)
    result_set_refs: List[str] = field(default_factory=list)
    runtime_paths: Optional[Any] = None
    okta_client: Optional[Any] = None
    cancellation_check: Optional[Callable[[], bool]] = None

    def check_cancelled(self) -> bool:
        if not self.cancellation_check:
            return False
        return bool(self.cancellation_check())


class ResultSetInspection(BaseModel):
    """Small inspection result safe to put in supervisor or history context."""

    summary: str
    row_count: int = Field(ge=0)
    key_columns: List[str] = Field(default_factory=list)
    sample_rows: List[Dict[str, Any]] = Field(default_factory=list)
    entity_type: Optional[str] = None


class ArtifactManifest(BaseModel):
    """Pointer and summary for a saved artifact payload."""

    artifact_key: str
    category: str
    storage_path: str
    summary: str
    source_specialist: SourceSpecialist = "unknown"
    content_type: str = "application/json"
    row_count: Optional[int] = Field(default=None, ge=0)
    entity_type: Optional[str] = None
    key_columns: List[str] = Field(default_factory=list)
    result_set_refs: List[str] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ResultSetRef(BaseModel):
    """Stable reference to a reusable result set stored outside model context."""

    result_set_id: str
    storage_path: str
    row_count: int = Field(ge=0)
    entity_type: str
    key_columns: List[str] = Field(default_factory=list)
    source_specialist: SourceSpecialist = "unknown"
    derivation_kind: DerivationKind = "initial"
    status: ResultSetStatus = "available"
    parent_result_set_ids: List[str] = Field(default_factory=list)
    artifact_keys: List[str] = Field(default_factory=list)
    user_facing_label: Optional[str] = None
    session_id: Optional[str] = None
    run_id: Optional[str] = None
    turn_number: Optional[int] = Field(default=None, ge=1)
    sequence_in_turn: Optional[int] = Field(default=None, ge=1)
    filter_summary: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DelegationResult(BaseModel):
    """Lightweight specialist result returned to the future supervisor."""

    success: bool
    source_specialist: SourceSpecialist
    result_mode: DelegationResultMode = "continue"
    summary: str
    artifact_keys: List[str] = Field(default_factory=list)
    result_set_refs: List[str] = Field(default_factory=list)
    needs_specialists: List[SourceSpecialist] = Field(default_factory=list)
    unresolved_requirements: List[str] = Field(default_factory=list)
    direct_answer: Optional[str] = None
    error: Optional[str] = None
    token_usage: Dict[str, int] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


def inspect_records(
    records: List[Dict[str, Any]],
    *,
    entity_type: Optional[str] = None,
    max_sample_rows: int = 3,
    max_key_columns: int = 8,
) -> ResultSetInspection:
    """Return a compact, context-safe summary for tabular records."""
    row_count = len(records)
    key_columns = infer_key_columns(records, max_columns=max_key_columns)
    sample_rows = records[: max(0, max_sample_rows)]
    entity_label = entity_type or "records"
    summary = f"Found {row_count} {entity_label}."
    if key_columns:
        summary += f" Key columns: {', '.join(key_columns)}."

    return ResultSetInspection(
        summary=summary,
        row_count=row_count,
        key_columns=key_columns,
        sample_rows=sample_rows,
        entity_type=entity_type,
    )


def load_artifacts_file(artifacts_file: Path) -> List[Dict[str, Any]]:
    """Load an artifact JSON file as a list, tolerating legacy dict payloads."""
    if not artifacts_file.exists():
        return []

    try:
        with open(artifacts_file, "r", encoding="utf-8") as file_handle:
            existing = json.load(file_handle)
    except json.JSONDecodeError:
        return []

    if isinstance(existing, dict):
        return [existing]
    if isinstance(existing, list):
        return [artifact for artifact in existing if isinstance(artifact, dict)]
    return []


def append_artifacts_to_file(
    artifacts_file: Path,
    artifacts: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Append artifacts to a JSON file and return the complete saved list."""
    artifacts_file.parent.mkdir(parents=True, exist_ok=True)
    existing = load_artifacts_file(artifacts_file)
    existing.extend(artifacts)

    with open(artifacts_file, "w", encoding="utf-8") as file_handle:
        json.dump(existing, file_handle, indent=2, default=str)

    return existing


def append_artifacts_with_result_sets(
    artifacts_file: Path,
    artifacts: List[Dict[str, Any]],
    *,
    source_specialist: SourceSpecialist = "unknown",
) -> tuple[List[Dict[str, Any]], List[ResultSetRef]]:
    """Append artifacts and create lightweight result-set sidecars when possible."""
    artifacts_file.parent.mkdir(parents=True, exist_ok=True)
    existing = load_artifacts_file(artifacts_file)
    result_index_file = _resolve_result_index_file(artifacts_file)
    result_index = _load_json_list(result_index_file)

    saved_artifacts: List[Dict[str, Any]] = []
    result_refs: List[ResultSetRef] = []
    sequence = len(result_index)

    for artifact in artifacts:
        enriched_artifact = dict(artifact)
        materialized = _materialize_result_set(
            result_index_file.parent,
            enriched_artifact,
            source_specialist=source_specialist,
            sequence_in_turn=sequence + 1,
        )
        if materialized:
            result_ref, inspection, manifest = materialized
            sequence += 1
            result_refs.append(result_ref)
            result_index.append(result_ref.model_dump())
            enriched_artifact["result_set_refs"] = [result_ref.result_set_id]
            enriched_artifact["result_set_inspection"] = inspection.model_dump()
            enriched_artifact["artifact_manifest"] = manifest.model_dump()

        saved_artifacts.append(enriched_artifact)

    existing.extend(saved_artifacts)
    _write_json(artifacts_file, existing)
    if result_refs:
        _write_json(result_index_file, result_index)

    return existing, result_refs


def find_artifact_by_key(
    artifacts: List[Dict[str, Any]],
    key: str,
) -> Optional[Dict[str, Any]]:
    """Find the newest artifact with a matching key from an artifact list."""
    for artifact in reversed(artifacts):
        if artifact.get("key") == key or artifact.get("artifact_key") == key:
            return artifact
    return None


def read_artifact_by_key(artifacts_file: Path, key: str) -> Optional[Dict[str, Any]]:
    """Read the newest matching artifact from a JSON artifact file."""
    return find_artifact_by_key(load_artifacts_file(artifacts_file), key)


def build_artifact_prompt_context(
    artifacts_file: Path,
    *,
    categories: Optional[List[str]] = None,
    max_preview_chars: int = 500,
) -> str:
    """Return compact artifact context for agent prompts without full payloads."""
    category_filter = set(categories or [])
    compact_artifacts: List[Dict[str, Any]] = []

    for artifact in load_artifacts_file(artifacts_file):
        category = str(artifact.get("category") or "unknown")
        if category_filter and category not in category_filter:
            continue

        compact = _compact_artifact_for_prompt(
            artifact,
            max_preview_chars=max_preview_chars,
        )
        compact_artifacts.append(compact)

    return json.dumps(compact_artifacts, indent=2, default=str)


def _compact_artifact_for_prompt(
    artifact: Dict[str, Any],
    *,
    max_preview_chars: int,
) -> Dict[str, Any]:
    compact: Dict[str, Any] = {
        "key": artifact.get("key") or artifact.get("artifact_key"),
        "category": artifact.get("category"),
        "notes": artifact.get("notes"),
        "result_set_refs": artifact.get("result_set_refs", []),
    }

    if artifact.get("sql_query"):
        compact["sql_query"] = artifact.get("sql_query")
    if artifact.get("api_code"):
        compact["api_code"] = artifact.get("api_code")
    if artifact.get("result_set_inspection"):
        compact["result_set_inspection"] = artifact.get("result_set_inspection")
    if artifact.get("artifact_manifest"):
        compact["artifact_manifest"] = artifact.get("artifact_manifest")

    if not compact.get("result_set_inspection") and isinstance(artifact.get("content"), str):
        content = artifact["content"]
        compact["content_preview"] = content[:max_preview_chars]
        compact["content_omitted"] = len(content) > max_preview_chars

    return {key: value for key, value in compact.items() if value not in (None, [], {})}


def inspect_json_content(
    content: str,
    *,
    entity_type: Optional[str] = None,
    max_sample_rows: int = 3,
    max_key_columns: int = 8,
) -> ResultSetInspection:
    """Inspect JSON content without returning the full payload to model context."""
    payload = json.loads(content)
    records = extract_records(payload)
    return inspect_records(
        records,
        entity_type=entity_type,
        max_sample_rows=max_sample_rows,
        max_key_columns=max_key_columns,
    )


def extract_records(payload: Any) -> List[Dict[str, Any]]:
    """Best-effort extraction of a list of records from common JSON shapes."""
    if isinstance(payload, list):
        return [record for record in payload if isinstance(record, dict)]

    if isinstance(payload, dict):
        for key in ("results", "data", "items", "records", "rows"):
            value = payload.get(key)
            if isinstance(value, list):
                return [record for record in value if isinstance(record, dict)]
        return [payload]

    return []


def infer_key_columns(records: List[Dict[str, Any]], *, max_columns: int = 8) -> List[str]:
    """Infer useful key columns for refs, joins, and follow-up resolution."""
    if not records:
        return []

    columns = list(records[0].keys())
    priority_tokens = ("id", "login", "email", "name", "status", "type")
    prioritized = [
        column
        for column in columns
        if any(token in column.lower() for token in priority_tokens)
    ]
    selected = prioritized or columns
    return selected[: max(0, max_columns)]


def _materialize_result_set(
    results_dir: Path,
    artifact: Dict[str, Any],
    *,
    source_specialist: SourceSpecialist,
    sequence_in_turn: int,
) -> Optional[tuple[ResultSetRef, ResultSetInspection, ArtifactManifest]]:
    content = artifact.get("content")
    if not isinstance(content, str):
        return None

    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None

    artifact_key = str(artifact.get("key") or artifact.get("artifact_key") or "artifact")
    entity_type = _infer_entity_type(artifact)
    records = extract_records(payload)
    inspection = inspect_records(records, entity_type=entity_type)
    result_set_id = f"rs_{source_specialist}_{sequence_in_turn:04d}_{_safe_id_part(artifact_key)}"
    storage_path = results_dir / f"{result_set_id}.json"
    turn_number, run_id, session_id = _infer_runtime_identity(storage_path)

    result_ref = ResultSetRef(
        result_set_id=result_set_id,
        storage_path=storage_path.as_posix(),
        row_count=inspection.row_count,
        entity_type=entity_type or "records",
        key_columns=inspection.key_columns,
        source_specialist=source_specialist,
        status="empty" if inspection.row_count == 0 else "available",
        artifact_keys=[artifact_key],
        session_id=session_id,
        run_id=run_id,
        turn_number=turn_number,
        sequence_in_turn=sequence_in_turn,
        metadata={"artifact_category": artifact.get("category")},
    )
    manifest = ArtifactManifest(
        artifact_key=artifact_key,
        category=str(artifact.get("category") or "unknown"),
        storage_path=storage_path.as_posix(),
        summary=inspection.summary,
        source_specialist=source_specialist,
        row_count=inspection.row_count,
        entity_type=entity_type,
        key_columns=inspection.key_columns,
        result_set_refs=[result_ref.result_set_id],
    )

    _write_json(
        storage_path,
        {
            "result_set": result_ref.model_dump(),
            "inspection": inspection.model_dump(),
            "data": payload,
        },
    )
    return result_ref, inspection, manifest


def _resolve_result_index_file(artifacts_file: Path) -> Path:
    if artifacts_file.parent.name == "artifacts":
        return artifacts_file.parent.parent / "results" / "index.json"
    return artifacts_file.parent / "results" / "index.json"


def _load_json_list(path: Path) -> List[Dict[str, Any]]:
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


def _safe_id_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned.strip("._-")[:64] or "artifact"


def _infer_entity_type(artifact: Dict[str, Any]) -> Optional[str]:
    text = " ".join(
        str(artifact.get(key) or "")
        for key in ("entity_type", "key", "artifact_key", "category", "notes")
    ).lower()
    for entity_type in ("users", "groups", "apps", "applications", "roles", "events", "logs", "factors"):
        if entity_type in text:
            return "apps" if entity_type == "applications" else entity_type
    return None


def _infer_runtime_identity(storage_path: Path) -> tuple[Optional[int], Optional[str], Optional[str]]:
    parts = storage_path.parts
    turn_number = None
    run_id = None
    session_id = None

    for index, part in enumerate(parts):
        if part == "sessions" and index + 1 < len(parts):
            session_id = parts[index + 1]
        if part == "turns" and index + 1 < len(parts):
            turn_dir_name = parts[index + 1]
            prefix, _, suffix = turn_dir_name.partition("-")
            if prefix.isdigit():
                turn_number = int(prefix)
            run_id = suffix or None
    return turn_number, run_id, session_id


__all__ = [
    "ArtifactManifest",
    "ConversationDeps",
    "DelegationResult",
    "DelegationResultMode",
    "DerivationKind",
    "ResultSetInspection",
    "ResultSetRef",
    "ResultSetStatus",
    "SourceSpecialist",
    "append_artifacts_to_file",
    "append_artifacts_with_result_sets",
    "build_artifact_prompt_context",
    "extract_records",
    "find_artifact_by_key",
    "infer_key_columns",
    "inspect_json_content",
    "inspect_records",
    "load_artifacts_file",
    "read_artifact_by_key",
]
