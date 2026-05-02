"""LLM-guided analysis specialist for previously saved result sets."""

from __future__ import annotations

import json
import re
import time
import builtins
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_ai import RunContext, UsageLimits

from src.config.settings import settings
from src.core.agents import build_agent
from src.core.models.model_picker import ModelType
from src.core.okta.sync.operations import DatabaseOperations
from src.data.schemas.artifact_manifest import (
    ArtifactManifest,
    DelegationResult,
    DerivationKind,
    ResultSetRef,
    build_result_set_id,
    extract_records,
    inspect_records,
    append_artifacts_to_file,
)
from src.utils.logging import get_logger
from src.utils.security_config import validate_result_analysis_code

logger = get_logger("okta_ai_agent")

ResultAnalysisMode = Literal["analyze", "request_specialist", "clarify"]
AnalysisSpecialist = Literal["sql", "api", "special"]

PROMPT_FILE = Path(__file__).parent / "prompts" / "result_analysis_prompt.txt"

RESULT_ANALYSIS_USAGE_LIMITS = UsageLimits(
    request_limit=2,
)

try:
        BASE_RESULT_ANALYSIS_PROMPT = PROMPT_FILE.read_text(encoding="utf-8")
except FileNotFoundError:
        logger.error(f"Result analysis prompt not found: {PROMPT_FILE}")
        BASE_RESULT_ANALYSIS_PROMPT = """You are the Tako result analysis specialist.

Your job is to analyze previously saved result sets from earlier turns.
You do not fetch new data from SQL or API directly. If prior saved result sets are
not sufficient, ask for another specialist instead of guessing.

When enough prior result data exists:
- choose the minimum set of result_set_ids needed for the question
- when the same prior turn contains both intermediate discovery samples and a canonical turn_output result set, treat the canonical turn_output as the authoritative user-visible cohort
- reason over session summary, recent turn summaries, lineage, metadata, and tiny samples
- write restricted Python code that analyzes the provided result_sets in memory
- correlate across multiple selected result sets when needed
- produce compact derived rows only when a reusable derived result set would help future turns

Code rules:
- no imports
- no file access
- no network access
- use only the provided variables: result_sets, result_metadata, selected_result_set_ids, user_query
- assign the final output to analysis_result
- analysis_result must be a dict with:
    - summary: required short explanation of what was found
    - answer: optional direct human-facing answer
    - rows: optional list[dict] for derived reusable data
    - entity_type: optional entity label for derived rows
    - persist_result: optional boolean
    - derivation_kind: optional one of initial/filter/enrichment/join/aggregation/subset/unknown
    - metadata: optional dict with compact structured facts

If prior results are not enough:
- use mode=request_specialist
- specify needs_specialists and unresolved_requirements
- do not emit code

If the user question is ambiguous relative to the saved results:
- use mode=clarify
- explain what is missing
"""


def _clean_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, (list, tuple, set)):
        cleaned: List[str] = []
        for item in value:
            stripped = str(item).strip()
            if stripped:
                cleaned.append(stripped)
        return cleaned
    return []


def _strip_code_fences(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[A-Za-z0-9_+-]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip() or None


class ResultAnalysisPlan(BaseModel):
    """Structured output from the result-analysis agent."""

    mode: ResultAnalysisMode = "analyze"
    reasoning: str
    selected_result_set_ids: List[str] = Field(default_factory=list)
    python_code: Optional[str] = None
    persist_result: bool = False
    result_entity_type: Optional[str] = None
    result_user_facing_label: Optional[str] = None
    needs_specialists: List[AnalysisSpecialist] = Field(default_factory=list)
    unresolved_requirements: List[str] = Field(default_factory=list)
    user_message: Optional[str] = None

    @field_validator("selected_result_set_ids", "needs_specialists", "unresolved_requirements", mode="before")
    @classmethod
    def normalize_string_lists(cls, value: Any) -> List[str]:
        return _clean_string_list(value)

    @field_validator("python_code", mode="before")
    @classmethod
    def normalize_python_code(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        return _strip_code_fences(str(value))

    @model_validator(mode="after")
    def validate_plan(self) -> "ResultAnalysisPlan":
        if self.mode == "analyze":
            if not self.selected_result_set_ids:
                raise ValueError("Analyze mode requires at least one selected_result_set_id")
            if not self.python_code:
                raise ValueError("Analyze mode requires python_code")
            return self

        if self.mode == "request_specialist":
            if not self.needs_specialists and not self.unresolved_requirements:
                raise ValueError("request_specialist mode requires needs_specialists or unresolved_requirements")
            self.python_code = None
            return self

        self.python_code = None
        return self


class ResultAnalysisExecutionOutput(BaseModel):
    """Validated execution output from restricted analysis code."""

    summary: str
    answer: Optional[str] = None
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    entity_type: Optional[str] = None
    persist_result: bool = False
    derivation_kind: Optional[DerivationKind] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


@dataclass
class ResultAnalysisDeps:
    """Dependencies for result analysis planning."""

    correlation_id: str
    artifacts_file: Path
    session_summary: Optional[str] = None
    recent_turn_summaries: List[Dict[str, Any]] = field(default_factory=list)
    candidate_result_sets: List[Dict[str, Any]] = field(default_factory=list)
    preferred_result_set_refs: List[str] = field(default_factory=list)
    workflow_state: Dict[str, Any] = field(default_factory=dict)


result_analysis_agent = build_agent(
    ModelType.CODING,
    name="result_analysis_agent",
    instructions=BASE_RESULT_ANALYSIS_PROMPT,
    output_type=ResultAnalysisPlan,
    deps_type=ResultAnalysisDeps,
)


@result_analysis_agent.instructions
def create_dynamic_instructions(ctx: RunContext[ResultAnalysisDeps]) -> str:
    deps = ctx.deps
    return f"""
CORRELATION ID: {deps.correlation_id}

SESSION SUMMARY:
{deps.session_summary or "(none)"}

RECENT TURN SUMMARIES:
{json.dumps(deps.recent_turn_summaries or [], indent=2, default=str)}

PREFERRED RESULT SET REFS:
{json.dumps(deps.preferred_result_set_refs or [], indent=2, default=str)}

WORKFLOW STATE:
{json.dumps(deps.workflow_state or {}, indent=2, default=str)}

CANDIDATE RESULT SETS:
{json.dumps(deps.candidate_result_sets or [], indent=2, default=str)}
"""


async def execute_result_analysis(
    user_query: str,
    *,
    correlation_id: str,
    artifacts_file: Path,
    preferred_result_set_refs: Optional[List[str]] = None,
    workflow_state: Optional[Dict[str, Any]] = None,
) -> tuple[DelegationResult, Any]:
    """Run the LLM-guided result-analysis specialist and return a specialist-style delegation result."""
    candidate_result_sets = _load_candidate_result_sets(
        artifacts_file,
        preferred_result_set_refs=preferred_result_set_refs or [],
    )
    if not candidate_result_sets:
        return (
            DelegationResult(
                success=False,
                source_specialist="analysis",
                result_mode="failed",
                summary="Result analysis needs saved result-set refs before it can run.",
                capability_gaps=["result_set_refs"],
                error="No saved result-set refs were available for analysis.",
            ),
            None,
        )

    conversation_context = await _load_conversation_context(correlation_id)
    deps = ResultAnalysisDeps(
        correlation_id=correlation_id,
        artifacts_file=artifacts_file,
        session_summary=conversation_context.get("session_summary"),
        recent_turn_summaries=conversation_context.get("recent_turn_summaries") or [],
        candidate_result_sets=candidate_result_sets,
        preferred_result_set_refs=list(preferred_result_set_refs or []),
        workflow_state=workflow_state or {},
    )

    try:
        run_result = await result_analysis_agent.run(
            f"Analyze previously saved result sets for this Okta follow-up request: {user_query}",
            deps=deps,
            usage_limits=RESULT_ANALYSIS_USAGE_LIMITS,
        )
    except Exception as exc:
        logger.error(f"Result analysis agent failed: {exc}", exc_info=True)
        return (
            DelegationResult(
                success=False,
                source_specialist="analysis",
                result_mode="failed",
                summary="Result analysis planning failed.",
                error=str(exc),
            ),
            None,
        )

    plan = run_result.output
    usage = run_result.usage()
    selected_result_set_ids = list(plan.selected_result_set_ids)
    selected_candidates = _select_candidate_result_sets(candidate_result_sets, selected_result_set_ids)
    anchored_result_scope = _build_anchored_result_scope(selected_candidates)

    if plan.mode == "request_specialist":
        return (
            DelegationResult(
                success=True,
                source_specialist="analysis",
                result_mode="continue",
                summary=plan.reasoning,
                needs_specialists=plan.needs_specialists,
                unresolved_requirements=plan.unresolved_requirements or [plan.reasoning],
                result_set_refs=selected_result_set_ids,
                metadata={
                    "analysis_mode": plan.mode,
                    "selected_result_set_ids": selected_result_set_ids,
                    "llm_selected_result_set_ids": plan.selected_result_set_ids,
                    "anchored_result_scope": anchored_result_scope,
                },
            ),
            usage,
        )

    if plan.mode == "clarify":
        return (
            DelegationResult(
                success=False,
                source_specialist="analysis",
                result_mode="needs_clarification",
                summary=plan.user_message or plan.reasoning,
                error=plan.user_message or plan.reasoning,
                result_set_refs=selected_result_set_ids,
                metadata={
                    "analysis_mode": plan.mode,
                    "selected_result_set_ids": selected_result_set_ids,
                    "llm_selected_result_set_ids": plan.selected_result_set_ids,
                    "anchored_result_scope": anchored_result_scope,
                },
            ),
            usage,
        )

    if len(selected_candidates) != len(selected_result_set_ids):
        return (
            DelegationResult(
                success=False,
                source_specialist="analysis",
                result_mode="failed",
                summary="Result analysis selected invalid result-set refs.",
                error="One or more selected result-set ids were not available in the current turn context.",
                metadata={
                    "selected_result_set_ids": selected_result_set_ids,
                    "llm_selected_result_set_ids": plan.selected_result_set_ids,
                },
            ),
            usage,
        )

    security_result = validate_result_analysis_code(plan.python_code or "")
    if not security_result.is_valid:
        return (
            DelegationResult(
                success=False,
                source_specialist="analysis",
                result_mode="failed",
                summary="Result analysis code failed security validation.",
                error="; ".join(security_result.violations),
                metadata={
                    "selected_result_set_ids": plan.selected_result_set_ids,
                    "security_violations": security_result.violations,
                },
            ),
            usage,
        )

    try:
        execution_output = _execute_analysis_code(
            user_query=user_query,
            python_code=plan.python_code or "",
            selected_candidates=selected_candidates,
            selected_result_set_ids=selected_result_set_ids,
        )
    except Exception as exc:
        logger.error(f"Result analysis execution failed: {exc}", exc_info=True)
        return (
            DelegationResult(
                success=False,
                source_specialist="analysis",
                result_mode="failed",
                summary="Result analysis execution failed.",
                error=str(exc),
                metadata={
                    "selected_result_set_ids": selected_result_set_ids,
                    "llm_selected_result_set_ids": plan.selected_result_set_ids,
                },
            ),
            usage,
        )

    artifact_key, result_set_refs = _persist_analysis_artifacts(
        artifacts_file=artifacts_file,
        user_query=user_query,
        plan=plan,
        execution_output=execution_output,
        selected_candidates=selected_candidates,
        selected_result_set_ids=selected_result_set_ids,
    )

    return (
        DelegationResult(
            success=True,
            source_specialist="analysis",
            result_mode="synthesis_ready",
            summary=execution_output.summary,
            artifact_keys=[artifact_key],
            result_set_refs=result_set_refs,
            evidence_found=[f"analysis:{result_set_id}" for result_set_id in selected_result_set_ids],
            metadata={
                "analysis_mode": plan.mode,
                "selected_result_set_ids": selected_result_set_ids,
                "llm_selected_result_set_ids": plan.selected_result_set_ids,
                "anchored_result_scope": anchored_result_scope,
                "answer": execution_output.answer,
                "result_row_count": len(execution_output.rows),
                **execution_output.metadata,
            },
        ),
        usage,
    )


async def _load_conversation_context(correlation_id: str) -> Dict[str, Any]:
    try:
        db_ops = DatabaseOperations()
        await db_ops.init_db()
        return await db_ops.get_compacted_conversation_context_for_run(
            tenant_id=settings.tenant_id,
            run_id=correlation_id,
        )
    except Exception as exc:
        logger.warning(f"Failed to load conversation context for result analysis {correlation_id}: {exc}")
        return {
            "session_summary": None,
            "recent_turn_summaries": [],
        }


def _execute_analysis_code(
    *,
    user_query: str,
    python_code: str,
    selected_candidates: Dict[str, Dict[str, Any]],
    selected_result_set_ids: List[str],
) -> ResultAnalysisExecutionOutput:
    result_sets = {
        result_set_id: _load_result_records(candidate["storage_path"])
        for result_set_id, candidate in selected_candidates.items()
    }
    result_metadata = {
        result_set_id: candidate
        for result_set_id, candidate in selected_candidates.items()
    }

    safe_builtins = {
        name: getattr(builtins, name)
        for name in (
            "len",
            "str",
            "int",
            "float",
            "bool",
            "list",
            "dict",
            "tuple",
            "set",
            "range",
            "enumerate",
            "zip",
            "sorted",
            "reversed",
            "sum",
            "min",
            "max",
            "abs",
            "round",
            "any",
            "all",
            "iter",
            "next",
            "map",
            "filter",
            "isinstance",
            "type",
            "repr",
            "format",
        )
    }

    globals_dict = {
        "__builtins__": safe_builtins,
        "Counter": Counter,
        "defaultdict": defaultdict,
        "json": json,
        "re": re,
    }
    locals_dict = {
        "result_sets": result_sets,
        "result_metadata": result_metadata,
        "selected_result_set_ids": selected_result_set_ids,
        "user_query": user_query,
        "analysis_result": None,
    }

    compiled = compile(python_code, "<result_analysis>", "exec")
    exec(compiled, globals_dict, locals_dict)
    raw_output = locals_dict.get("analysis_result")

    if raw_output is None:
        raise ValueError("Analysis code must assign a dict to analysis_result")

    if isinstance(raw_output, str):
        return ResultAnalysisExecutionOutput(summary=raw_output, answer=raw_output)

    if not isinstance(raw_output, dict):
        raise ValueError("analysis_result must be a dict or string")

    return ResultAnalysisExecutionOutput.model_validate(raw_output)


def _persist_analysis_artifacts(
    *,
    artifacts_file: Path,
    user_query: str,
    plan: ResultAnalysisPlan,
    execution_output: ResultAnalysisExecutionOutput,
    selected_candidates: Dict[str, Dict[str, Any]],
    selected_result_set_ids: List[str],
) -> tuple[str, List[str]]:
    artifact_key = f"analysis_{_safe_id_part(user_query)}"
    result_set_refs = list(selected_result_set_ids)
    entity_type = (
        execution_output.entity_type
        or plan.result_entity_type
        or _infer_selected_entity_type(selected_candidates)
        or "records"
    )

    result_set_inspection = None
    artifact_manifest = None
    if (plan.persist_result or execution_output.persist_result) and execution_output.rows:
        derived_ref, inspection, manifest = _write_analysis_result_set(
            artifacts_file=artifacts_file,
            artifact_key=artifact_key,
            entity_type=entity_type,
            user_facing_label=plan.result_user_facing_label,
            rows=execution_output.rows,
            summary=execution_output.summary,
            selected_result_set_ids=selected_result_set_ids,
            derivation_kind=execution_output.derivation_kind,
            metadata=execution_output.metadata,
        )
        result_set_refs = [derived_ref.result_set_id]
        result_set_inspection = inspection.model_dump()
        artifact_manifest = manifest.model_dump()

    preview_rows = execution_output.rows[: min(3, len(execution_output.rows))]
    content_payload = {
        "summary": execution_output.summary,
        "answer": execution_output.answer,
        "selected_result_set_ids": selected_result_set_ids,
        "llm_selected_result_set_ids": plan.selected_result_set_ids,
        "sample_rows": preview_rows,
        "metadata": execution_output.metadata,
    }

    artifact = {
        "key": artifact_key,
        "category": "analysis_results",
        "content": json.dumps(content_payload, indent=2, default=str),
        "notes": execution_output.answer or execution_output.summary,
        "entity_type": entity_type,
        "result_set_refs": result_set_refs,
    }
    if result_set_inspection is not None:
        artifact["result_set_inspection"] = result_set_inspection
    if artifact_manifest is not None:
        artifact["artifact_manifest"] = artifact_manifest

    append_artifacts_to_file(artifacts_file, [artifact])
    return artifact_key, result_set_refs


def _write_analysis_result_set(
    *,
    artifacts_file: Path,
    artifact_key: str,
    entity_type: str,
    user_facing_label: Optional[str],
    rows: List[Dict[str, Any]],
    summary: str,
    selected_result_set_ids: List[str],
    derivation_kind: Optional[DerivationKind],
    metadata: Dict[str, Any],
) -> tuple[ResultSetRef, Any, ArtifactManifest]:
    index_file = _resolve_result_index_file(artifacts_file)
    index = _load_json_list(index_file)
    sequence_in_turn = len(index) + 1
    turn_number, run_id, session_id = _infer_runtime_identity(index_file.parent / "placeholder.json")
    result_set_id = build_result_set_id(
        prefix="rs_analysis",
        sequence_in_turn=sequence_in_turn,
        artifact_key=artifact_key,
        session_id=session_id,
        turn_number=turn_number,
        run_id=run_id,
    )
    storage_path = index_file.parent / f"{result_set_id}.json"
    inspection = inspect_records(rows, entity_type=entity_type)

    result_ref = ResultSetRef(
        result_set_id=result_set_id,
        storage_path=storage_path.as_posix(),
        row_count=inspection.row_count,
        entity_type=entity_type,
        key_columns=inspection.key_columns,
        source_specialist="analysis",
        derivation_kind=derivation_kind or ("join" if len(selected_result_set_ids) > 1 else "aggregation"),
        status="empty" if inspection.row_count == 0 else "available",
        parent_result_set_ids=list(selected_result_set_ids),
        artifact_keys=[artifact_key],
        user_facing_label=user_facing_label,
        session_id=session_id,
        run_id=run_id,
        turn_number=turn_number,
        sequence_in_turn=sequence_in_turn,
        metadata={
            **metadata,
            "selected_result_set_ids": list(selected_result_set_ids),
        },
    )
    manifest = ArtifactManifest(
        artifact_key=artifact_key,
        category="analysis_results",
        storage_path=storage_path.as_posix(),
        summary=summary,
        source_specialist="analysis",
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
            "summary": summary,
            "data": {"results": rows},
        },
    )
    index.append(result_ref.model_dump())
    _write_json(index_file, index)
    return result_ref, inspection, manifest


def _select_candidate_result_sets(
    candidate_result_sets: List[Dict[str, Any]],
    selected_result_set_ids: List[str],
) -> Dict[str, Dict[str, Any]]:
    candidate_map = {
        str(candidate.get("result_set_id")): candidate
        for candidate in candidate_result_sets
        if candidate.get("result_set_id")
    }
    return {
        result_set_id: candidate_map[result_set_id]
        for result_set_id in selected_result_set_ids
        if result_set_id in candidate_map
    }


def _infer_selected_entity_type(selected_candidates: Dict[str, Dict[str, Any]]) -> Optional[str]:
    for candidate in selected_candidates.values():
        entity_type = candidate.get("entity_type")
        if entity_type:
            return str(entity_type)
    return None


def _build_anchored_result_scope(selected_candidates: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not selected_candidates:
        return None

    result_sets: List[Dict[str, Any]] = []
    entity_types: List[str] = []
    source_turn_numbers: List[int] = []

    for result_set_id, candidate in selected_candidates.items():
        entity_type = str(candidate.get("entity_type") or "").strip()
        turn_number = candidate.get("turn_number")
        if entity_type and entity_type not in entity_types:
            entity_types.append(entity_type)
        if isinstance(turn_number, int) and turn_number not in source_turn_numbers:
            source_turn_numbers.append(turn_number)

        result_sets.append(
            {
                "result_set_id": result_set_id,
                "entity_type": candidate.get("entity_type"),
                "row_count": candidate.get("row_count"),
                "key_columns": list(candidate.get("key_columns") or []),
                "artifact_category": candidate.get("artifact_category"),
                "is_canonical_turn_output": bool(candidate.get("is_canonical_turn_output")),
                "user_facing_label": candidate.get("user_facing_label"),
                "filter_summary": candidate.get("filter_summary"),
                "source_specialist": candidate.get("source_specialist"),
                "turn_number": candidate.get("turn_number"),
                "run_id": candidate.get("run_id"),
                "session_id": candidate.get("session_id"),
            }
        )

    return {
        "scope_preservation_required": True,
        "result_set_ids": list(selected_candidates.keys()),
        "primary_entity_type": entity_types[0] if len(entity_types) == 1 else None,
        "entity_types": entity_types,
        "source_turn_numbers": source_turn_numbers,
        "result_sets": result_sets,
    }


def _load_candidate_result_sets(
    artifacts_file: Path,
    *,
    preferred_result_set_refs: List[str],
    max_candidates: int = 12,
) -> List[Dict[str, Any]]:
    index_entries = _load_json_list(_resolve_result_index_file(artifacts_file))
    if not index_entries:
        return []

    preferred = {str(result_set_id) for result_set_id in preferred_result_set_refs}
    ranked_entries = []
    for order, entry in enumerate(index_entries):
        result_set_id = str(entry.get("result_set_id") or "")
        if not result_set_id:
            continue
        created_at = float(entry.get("created_at") or 0)
        ranked_entries.append((0 if result_set_id in preferred else 1, -created_at, -order, entry))

    ranked_entries.sort(key=lambda item: (item[0], item[1], item[2]))
    selected_entries = [item[3] for item in ranked_entries[:max_candidates]]
    return [_build_candidate_result_set_context(entry) for entry in selected_entries]


def _build_candidate_result_set_context(entry: Dict[str, Any]) -> Dict[str, Any]:
    result_set_id = str(entry.get("result_set_id"))
    storage_path = str(entry.get("storage_path") or "")
    sidecar = _load_sidecar(Path(storage_path))
    inspection = sidecar.get("inspection") if isinstance(sidecar, dict) else {}
    if not isinstance(inspection, dict):
        inspection = {}

    metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
    artifact_category = str(metadata.get("artifact_category") or "").strip().lower() or None
    return {
        "result_set_id": result_set_id,
        "storage_path": storage_path,
        "entity_type": entry.get("entity_type"),
        "row_count": entry.get("row_count"),
        "key_columns": list(entry.get("key_columns") or []),
        "source_specialist": entry.get("source_specialist"),
        "derivation_kind": entry.get("derivation_kind"),
        "status": entry.get("status"),
        "parent_result_set_ids": list(entry.get("parent_result_set_ids") or []),
        "user_facing_label": entry.get("user_facing_label"),
        "filter_summary": entry.get("filter_summary"),
        "turn_number": entry.get("turn_number"),
        "run_id": entry.get("run_id"),
        "session_id": entry.get("session_id"),
        "created_at": entry.get("created_at"),
        "artifact_category": artifact_category,
        "is_canonical_turn_output": artifact_category == "turn_output",
        "inspection_summary": inspection.get("summary"),
        "sample_rows": inspection.get("sample_rows") or [],
        "metadata": metadata,
    }


def _load_result_records(storage_path: str) -> List[Dict[str, Any]]:
    with open(Path(storage_path), "r", encoding="utf-8") as file_handle:
        sidecar = json.load(file_handle)
    payload = sidecar.get("data") if isinstance(sidecar, dict) else sidecar
    return extract_records(payload)


def _load_sidecar(storage_path: Path) -> Dict[str, Any]:
    if not storage_path.exists():
        return {}
    try:
        with open(storage_path, "r", encoding="utf-8") as file_handle:
            payload = json.load(file_handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve_result_index_file(artifacts_file: Path) -> Path:
    if artifacts_file.parent.name == "artifacts":
        return artifacts_file.parent.parent / "results" / "index.json"
    return artifacts_file.parent / "results" / "index.json"


def _load_json_list(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as file_handle:
            payload = json.load(file_handle)
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file_handle:
        json.dump(payload, file_handle, indent=2, default=str)


def _infer_runtime_identity(storage_path: Path) -> tuple[Optional[int], Optional[str], Optional[str]]:
    turn_metadata_file = storage_path.parent.parent / "turn_metadata.json"
    if turn_metadata_file.exists():
        try:
            with open(turn_metadata_file, "r", encoding="utf-8") as file_handle:
                metadata = json.load(file_handle)
            if isinstance(metadata, dict):
                turn_number = metadata.get("turn_number")
                run_id = metadata.get("run_id")
                session_id = metadata.get("session_id")
                return (
                    int(turn_number) if isinstance(turn_number, (int, str)) and str(turn_number).isdigit() else None,
                    str(run_id) if run_id else None,
                    str(session_id) if session_id else None,
                )
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            pass

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


def _safe_id_part(value: str) -> str:
    import hashlib

    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("._-") or "analysis"
    digest = hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned[:24]}_{digest}"


__all__ = [
    "ResultAnalysisDeps",
    "ResultAnalysisExecutionOutput",
    "ResultAnalysisPlan",
    "execute_result_analysis",
]
