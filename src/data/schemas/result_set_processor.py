"""Deterministic off-context processing for saved result-set refs."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from src.data.schemas.artifact_manifest import (
    DelegationResult,
    ResultSetRef,
    build_result_set_id,
    extract_records,
    inspect_records,
)


ResultSetOperation = Literal["inspect", "count", "filter", "select"]


class ResultSetProcessingRequest(BaseModel):
    """A deterministic operation over one saved result-set ref."""

    result_set_id: str
    operation: ResultSetOperation = "inspect"
    filters: Dict[str, Any] = Field(default_factory=dict)
    columns: List[str] = Field(default_factory=list)
    limit: int = Field(default=25, ge=0, le=1000)
    persist_result: bool = True


def process_result_set_ref(
    artifacts_file: Path,
    request: ResultSetProcessingRequest,
) -> DelegationResult:
    """Process a saved result set and return only refs, summaries, and tiny samples."""
    try:
        result_index_file = _resolve_result_index_file(artifacts_file)
        source_ref = _find_result_ref(result_index_file, request.result_set_id)
        if not source_ref:
            return DelegationResult(
                success=False,
                source_specialist="processor",
                result_mode="failed",
                summary=f"Result set '{request.result_set_id}' was not found.",
                error=f"Result set '{request.result_set_id}' was not found",
            )

        records = _load_result_records(source_ref.storage_path)
        processed_records = _apply_operation(records, request)
        inspection = inspect_records(processed_records, entity_type=source_ref.entity_type)
        result_refs: List[str] = []

        if request.persist_result and request.operation in {"filter", "select"}:
            derived_ref = _write_derived_result_set(
                result_index_file,
                source_ref,
                processed_records,
                request,
                inspection.summary,
            )
            result_refs.append(derived_ref.result_set_id)

        if request.operation == "count":
            summary = f"Counted {len(processed_records)} {source_ref.entity_type}."
        else:
            summary = inspection.summary

        return DelegationResult(
            success=True,
            source_specialist="processor",
            result_mode="synthesis_ready",
            summary=summary,
            result_set_refs=result_refs or [source_ref.result_set_id],
            metadata={
                "operation": request.operation,
                "source_result_set_id": source_ref.result_set_id,
                "row_count": inspection.row_count,
                "key_columns": inspection.key_columns,
                "sample_rows": inspection.sample_rows,
            },
        )
    except Exception as exc:
        return DelegationResult(
            success=False,
            source_specialist="processor",
            result_mode="failed",
            summary="Result-set processing failed.",
            error=str(exc),
        )


def _apply_operation(
    records: List[Dict[str, Any]],
    request: ResultSetProcessingRequest,
) -> List[Dict[str, Any]]:
    filtered_records = _filter_records(records, request.filters)

    if request.operation == "count":
        return filtered_records

    if request.columns:
        selected_records = [
            {column: record.get(column) for column in request.columns if column in record}
            for record in filtered_records
        ]
    else:
        selected_records = filtered_records

    if request.operation == "inspect":
        return selected_records[: request.limit]
    return selected_records


def _filter_records(records: List[Dict[str, Any]], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not filters:
        return records

    filtered = []
    for record in records:
        if all(_matches_filter(record.get(key), expected) for key, expected in filters.items()):
            filtered.append(record)
    return filtered


def _matches_filter(actual: Any, expected: Any) -> bool:
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.lower() in actual.lower()
    return actual == expected


def _find_result_ref(index_file: Path, result_set_id: str) -> Optional[ResultSetRef]:
    for entry in _load_json_list(index_file):
        if entry.get("result_set_id") == result_set_id:
            return ResultSetRef.model_validate(entry)
    return None


def _load_result_records(storage_path: str) -> List[Dict[str, Any]]:
    with open(Path(storage_path), "r", encoding="utf-8") as file_handle:
        sidecar = json.load(file_handle)
    payload = sidecar.get("data") if isinstance(sidecar, dict) else sidecar
    return extract_records(payload)


def _write_derived_result_set(
    index_file: Path,
    source_ref: ResultSetRef,
    records: List[Dict[str, Any]],
    request: ResultSetProcessingRequest,
    summary: str,
) -> ResultSetRef:
    index = _load_json_list(index_file)
    result_set_id = build_result_set_id(
        prefix="rs_processor",
        sequence_in_turn=len(index) + 1,
        artifact_key=request.operation,
        session_id=source_ref.session_id,
        turn_number=source_ref.turn_number,
        run_id=source_ref.run_id,
    )
    storage_path = index_file.parent / f"{result_set_id}.json"
    derived_ref = ResultSetRef(
        result_set_id=result_set_id,
        storage_path=storage_path.as_posix(),
        row_count=len(records),
        entity_type=source_ref.entity_type,
        key_columns=source_ref.key_columns,
        source_specialist="processor",
        derivation_kind="filter" if request.filters else "subset",
        parent_result_set_ids=[source_ref.result_set_id],
        artifact_keys=source_ref.artifact_keys,
        session_id=source_ref.session_id,
        run_id=source_ref.run_id,
        turn_number=source_ref.turn_number,
        sequence_in_turn=len(index) + 1,
        filter_summary=_filter_summary(request),
        metadata={"operation": request.operation},
    )

    _write_json(
        storage_path,
        {
            "result_set": derived_ref.model_dump(),
            "inspection": inspect_records(records, entity_type=source_ref.entity_type).model_dump(),
            "summary": summary,
            "data": records,
        },
    )
    index.append(derived_ref.model_dump())
    _write_json(index_file, index)
    return derived_ref


def _filter_summary(request: ResultSetProcessingRequest) -> Optional[str]:
    parts = []
    if request.filters:
        parts.append(f"filters={request.filters}")
    if request.columns:
        parts.append(f"columns={request.columns}")
    return "; ".join(parts) if parts else None


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
    import hashlib

    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("._-") or "result"
    digest = hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned[:24]}_{digest}"


__all__ = [
    "ResultSetOperation",
    "ResultSetProcessingRequest",
    "process_result_set_ref",
]