"""
Supervisor Agent - Phase 2C control-plane decisions.

The supervisor owns routing and follow-up delegation decisions while specialists
continue to own domain execution and validation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_ai import RunContext, UsageLimits

from src.core.agents import build_agent
from src.core.models.model_picker import ModelType
from src.core.okta.sync.operations import DatabaseOperations
from src.config.settings import settings
from src.data.schemas.artifact_manifest import DelegationResult, build_artifact_prompt_context
from src.data.schemas.shared_schema import get_okta_database_schema
from src.utils.logging import get_logger

logger = get_logger("okta_ai_agent")


SupervisorMode = Literal["delegate", "complete", "empty", "degraded_success", "clarify", "fail"]
SupervisorTarget = Literal["SQL", "API", "SPECIAL", "PROCESSOR", "RESULT_ANALYSIS", "SYNTHESIS", "NONE"]
SupervisorResultMode = Literal[
    "continue",
    "synthesis_ready",
    "direct_answer",
    "empty",
    "degraded_success",
    "failed",
    "needs_clarification",
]
SupervisorConfidence = Literal["low", "medium", "high"]


_DELEGATE_TARGETS = {"SQL", "API", "SPECIAL", "PROCESSOR", "RESULT_ANALYSIS"}
_COMPLETION_TARGETS = {"SYNTHESIS", "NONE"}
_FINAL_MODES = {"complete", "empty", "degraded_success"}
_CONFIDENCE_LEVELS = {"low", "medium", "high"}
_REFERENTIAL_FOLLOWUP_PATTERN = re.compile(
    r"\b(their|them|those|these|same|previous|prior|earlier|returned|above|former)\b",
    re.IGNORECASE,
)
_REFERENTIAL_FOLLOWUP_PHRASES = (
    "that result",
    "that set",
    "that list",
    "same result",
    "same set",
)
_FOLLOWUP_CONTINUATION_PREFIXES = (
    "also ",
    "what about ",
    "how about ",
    "what else ",
    "how else ",
)
_FRESH_DISCOVERY_PREFIXES = (
    "list ",
    "show ",
    "find ",
    "search ",
    "lookup ",
    "get ",
    "fetch ",
    "retrieve ",
)
_FOLLOWUP_TRAILING_MARKERS = (" too", " as well")


def _normalize_label(value: Any, *, uppercase: bool = False) -> Any:
    if value is None:
        return value
    normalized = str(value).strip().replace("-", "_").replace(" ", "_")
    return normalized.upper() if uppercase else normalized.lower()


def _normalize_mode(value: Any) -> Any:
    mode = _normalize_label(value)
    return {
        "partial": "degraded_success",
        "partial_success": "degraded_success",
        "clarification": "clarify",
        "failed": "fail",
        "error": "fail",
    }.get(mode, mode)


def _normalize_target(value: Any) -> Any:
    target = _normalize_label(value, uppercase=True)
    return "NONE" if target in {"", "NULL", "N_A", "N/A"} else target


def _normalize_result_mode(value: Any) -> Any:
    result_mode = _normalize_label(value)
    return {
        "complete": "synthesis_ready",
        "success": "synthesis_ready",
        "ready": "synthesis_ready",
        "partial": "degraded_success",
        "partial_success": "degraded_success",
        "clarification": "needs_clarification",
        "error": "failed",
    }.get(result_mode, result_mode)


def _normalize_confidence(value: Any) -> Any:
    confidence = _normalize_label(value)
    return confidence if confidence in _CONFIDENCE_LEVELS else "medium"


def _clean_string_list(value: Any) -> Any:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, (list, tuple, set)):
        cleaned: List[str] = []
        for item in value:
            if item is None:
                continue
            stripped = str(item).strip()
            if stripped:
                cleaned.append(stripped)
        return cleaned
    return value


def _coerce_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _is_referential_followup_query(user_query: str) -> bool:
    normalized = " ".join(str(user_query or "").split()).strip().lower()
    if not normalized:
        return False

    if _REFERENTIAL_FOLLOWUP_PATTERN.search(normalized):
        return True

    if any(phrase in normalized for phrase in _REFERENTIAL_FOLLOWUP_PHRASES):
        return True

    if normalized.startswith(_FOLLOWUP_CONTINUATION_PREFIXES):
        return True

    return normalized.endswith(_FOLLOWUP_TRAILING_MARKERS) and not normalized.startswith(
        _FRESH_DISCOVERY_PREFIXES
    )


def _build_followup_workflow_state(
    workflow_state: Optional[Dict[str, Any]],
    recent_turn_summaries: List[Dict[str, Any]],
    compaction_details: Optional[Dict[str, Any]],
    user_query: str,
) -> Dict[str, Any]:
    enriched_state = dict(workflow_state or {})
    ordered_turns = sorted(
        (turn for turn in recent_turn_summaries if isinstance(turn, dict)),
        key=lambda turn: (_coerce_int(turn.get("turn_number")) or 0, str(turn.get("started_at") or "")),
    )

    current_turn = ordered_turns[-1] if ordered_turns else None
    previous_turn = ordered_turns[-2] if len(ordered_turns) > 1 else None
    current_turn_number = _coerce_int(current_turn.get("turn_number")) if current_turn else None
    previous_turn_number = _coerce_int(previous_turn.get("turn_number")) if previous_turn else None
    previous_turn_result_count = _coerce_int(previous_turn.get("result_count")) if previous_turn else None

    trimmed_turn_count = _coerce_int((compaction_details or {}).get("trimmed_turn_count")) or 0
    hydrated_result_set_count = enriched_state.get("hydrated_session_result_set_count")
    if hydrated_result_set_count is None:
        hydrated_result_set_count = enriched_state.get("hydrated_session_result_set_refs")
    hydrated_result_set_count = _coerce_int(hydrated_result_set_count) or 0

    is_follow_up_turn = bool(
        (current_turn_number and current_turn_number > 1)
        or previous_turn is not None
        or trimmed_turn_count > 0
    )
    referential_followup_query = _is_referential_followup_query(user_query)
    has_prior_result_context = bool(hydrated_result_set_count > 0)
    previous_turn_had_results = bool(previous_turn_result_count and previous_turn_result_count > 0)

    enriched_state.update(
        {
            "current_turn_number": current_turn_number,
            "current_turn_query_text": current_turn.get("query_text") if current_turn else None,
            "current_turn_status": current_turn.get("status") if current_turn else None,
            "is_initial_turn": not is_follow_up_turn,
            "previous_turn_number": previous_turn_number,
            "previous_turn_query_text": previous_turn.get("query_text") if previous_turn else None,
            "previous_turn_result_count": previous_turn_result_count,
            "previous_turn_completion_mode": previous_turn.get("completion_mode") if previous_turn else None,
            "previous_turn_had_results": previous_turn_had_results,
            "is_follow_up_turn": is_follow_up_turn,
            "referential_followup_query": referential_followup_query,
            "hydrated_session_result_set_count": hydrated_result_set_count,
            "has_prior_result_context": has_prior_result_context,
            "prefer_result_analysis_for_followup": bool(
                is_follow_up_turn and referential_followup_query and has_prior_result_context
            ),
        }
    )
    return enriched_state


def _should_redirect_initial_followup_to_analysis(
    decision: "SupervisorDecision",
    workflow_state: Dict[str, Any],
) -> bool:
    return bool(
        decision.mode == "delegate"
        and decision.target in {"SQL", "API"}
        and workflow_state.get("prefer_result_analysis_for_followup")
    )


def _normalize_initial_decision(
    decision: "SupervisorDecision",
    workflow_state: Dict[str, Any],
) -> "SupervisorDecision":
    if not _should_redirect_initial_followup_to_analysis(decision, workflow_state):
        return decision

    return SupervisorDecision(
        mode="delegate",
        target="RESULT_ANALYSIS",
        reasoning=(
            "Runtime safety redirected this referential follow-up to RESULT_ANALYSIS because "
            "prior session result-set refs are available and the request appears to refer to them."
        ),
        requested_data=decision.requested_data,
        confidence=decision.confidence,
    )


class SupervisorDecision(BaseModel):
    """Typed control-plane decision for the current turn."""

    mode: SupervisorMode
    target: SupervisorTarget = "NONE"
    reasoning: str
    result_mode: SupervisorResultMode = "continue"
    requested_data: List[str] = Field(default_factory=list)
    evidence_artifact_keys: List[str] = Field(default_factory=list)
    evidence_result_set_refs: List[str] = Field(default_factory=list)
    confidence: SupervisorConfidence = "medium"
    user_message: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def normalize_raw_decision(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        if "mode" in normalized:
            normalized["mode"] = _normalize_mode(normalized["mode"])
        if "target" in normalized:
            normalized["target"] = _normalize_target(normalized["target"])
        if "result_mode" in normalized:
            normalized["result_mode"] = _normalize_result_mode(normalized["result_mode"])
        if "confidence" in normalized:
            normalized["confidence"] = _normalize_confidence(normalized["confidence"])
        return normalized

    @field_validator("requested_data", "evidence_artifact_keys", "evidence_result_set_refs", mode="before")
    @classmethod
    def normalize_string_lists(cls, value: Any) -> Any:
        return _clean_string_list(value)

    @model_validator(mode="after")
    def validate_decision(self) -> "SupervisorDecision":
        if self.mode == "delegate" and self.target not in _DELEGATE_TARGETS:
            raise ValueError("Delegate decisions must target SQL, API, SPECIAL, PROCESSOR, or RESULT_ANALYSIS")

        if self.mode == "delegate":
            self.result_mode = "continue"
            return self

        if self.mode == "complete" and self.target not in _COMPLETION_TARGETS:
            raise ValueError("Complete decisions must target SYNTHESIS or NONE")

        if self.mode == "complete":
            if self.result_mode not in {"synthesis_ready", "direct_answer"}:
                self.result_mode = "synthesis_ready"
            if self.target == "NONE" and self.result_mode != "direct_answer":
                self.target = "SYNTHESIS"
            return self

        if self.mode == "empty":
            self.target = "NONE"
            self.result_mode = "empty"
            return self

        if self.mode == "degraded_success":
            if self.target not in _COMPLETION_TARGETS:
                raise ValueError("Degraded success decisions must target SYNTHESIS or NONE")
            if self.target == "NONE":
                self.target = "SYNTHESIS"
            self.result_mode = "degraded_success"
            return self

        if self.mode == "clarify":
            self.target = "NONE"
            self.result_mode = "needs_clarification"
            return self

        if self.mode == "fail":
            self.target = "NONE"
            self.result_mode = "failed"

        return self


@dataclass
class SupervisorDeps:
    """Dependencies for supervisor decisions."""

    correlation_id: str
    phase: Literal["initial", "after_delegation"] = "initial"
    artifacts_file: Optional[Path] = None
    db_runtime_summary: Dict[str, Any] = field(default_factory=dict)
    special_tool_capabilities: Dict[str, Any] = field(default_factory=dict)
    workflow_state: Dict[str, Any] = field(default_factory=dict)
    delegation_results: List[Dict[str, Any]] = field(default_factory=list)
    latest_delegation_result: Optional[Dict[str, Any]] = None
    session_summary: Optional[str] = None
    recent_turn_summaries: List[Dict[str, Any]] = field(default_factory=list)
    compaction_details: Dict[str, Any] = field(default_factory=dict)
    step_start_callback: Optional[callable] = None


BASE_SUPERVISOR_PROMPT = """
"""


# Load system prompt
PROMPT_FILE = Path(__file__).parent / "prompts" / "supervisor_prompt.txt"
try:
        with open(PROMPT_FILE, 'r', encoding='utf-8') as f:
                BASE_SUPERVISOR_PROMPT = f.read()
except FileNotFoundError:
        logger.error(f"Supervisor prompt not found: {PROMPT_FILE}")
        BASE_SUPERVISOR_PROMPT = """You are the Tako supervisor and control plane for Okta data requests.
Decide the next routing step between SQL, API, SPECIAL, PROCESSOR, or SYNTHESIS."""


supervisor_agent = build_agent(
    ModelType.REASONING,
    name="supervisor_agent",
    instructions=BASE_SUPERVISOR_PROMPT,
    output_type=SupervisorDecision,
    deps_type=SupervisorDeps,
)

SUPERVISOR_USAGE_LIMITS = UsageLimits(
    request_limit=2,
    tool_calls_limit=1,
)


@supervisor_agent.tool
async def notify_progress_to_user(
    ctx: RunContext[SupervisorDeps],
    message: str,
) -> str:
    """Report supervisor progress through the runtime callback."""
    deps = ctx.deps
    logger.info(f"[{deps.correlation_id}] Supervisor progress: {message}")
    if deps.step_start_callback:
        await deps.step_start_callback({
            "title": "Supervisor",
            "text": message,
        })
    return f"Supervisor progress reported: {message}"


@supervisor_agent.instructions
def create_dynamic_instructions(ctx: RunContext[SupervisorDeps]) -> str:
    """Inject schema, compact artifact context, and prior specialist outcomes."""
    deps = ctx.deps
    schema_description = get_okta_database_schema()
    artifact_context = "[]"
    if deps.artifacts_file and deps.artifacts_file.exists():
        try:
            artifact_context = build_artifact_prompt_context(deps.artifacts_file)
        except Exception as exc:
            artifact_context = f"Artifact context unavailable: {exc}"

    return f"""
SUPERVISOR PHASE: {deps.phase}
CORRELATION ID: {deps.correlation_id}

DATABASE SCHEMA:
{schema_description}

DB RUNTIME SUMMARY:
{json.dumps(deps.db_runtime_summary or {}, indent=2, default=str)}

SPECIAL TOOL CAPABILITIES:
{json.dumps(deps.special_tool_capabilities or {}, indent=2, default=str)}

WORKFLOW STATE:
{json.dumps(deps.workflow_state or {}, indent=2, default=str)}

SESSION SUMMARY:
{deps.session_summary or "(none)"}

RECENT TURN SUMMARIES:
{json.dumps(deps.recent_turn_summaries or [], indent=2, default=str)}

COMPACTION DETAILS:
{json.dumps(deps.compaction_details or {}, indent=2, default=str)}

LATEST SPECIALIST RESULT:
{json.dumps(deps.latest_delegation_result or {}, indent=2, default=str)}

ALL SPECIALIST RESULTS SO FAR:
{json.dumps(deps.delegation_results, indent=2, default=str)}

COMPACT ARTIFACT CONTEXT:
{artifact_context}
"""


async def _load_supervisor_conversation_context(correlation_id: str) -> Dict[str, Any]:
    try:
        db_ops = DatabaseOperations()
        await db_ops.init_db()
        return await db_ops.get_compacted_conversation_context_for_run(
            tenant_id=settings.tenant_id,
            run_id=correlation_id,
        )
    except Exception as exc:
        logger.warning(f"Failed to load supervisor conversation context for {correlation_id}: {exc}")
        return {
            "message_history": [],
            "session_summary": None,
            "recent_turn_summaries": [],
            "compaction_applied": False,
            "trimmed_turn_count": 0,
        }


async def supervise_query(
    user_query: str,
    *,
    correlation_id: str,
    artifacts_file: Optional[Path] = None,
    db_runtime_summary: Optional[Dict[str, Any]] = None,
    special_tool_capabilities: Optional[Dict[str, Any]] = None,
    workflow_state: Optional[Dict[str, Any]] = None,
    step_start_callback: Optional[callable] = None,
) -> tuple[SupervisorDecision, Any]:
    """Choose the first specialist or completion mode for a user request."""
    logger.info(f"Running supervisor initial decision for query: {user_query}")
    conversation_context = await _load_supervisor_conversation_context(correlation_id)
    enriched_workflow_state = _build_followup_workflow_state(
        workflow_state,
        conversation_context.get("recent_turn_summaries") or [],
        {
            "compaction_applied": bool(conversation_context.get("compaction_applied")),
            "trimmed_turn_count": int(conversation_context.get("trimmed_turn_count") or 0),
        },
        user_query,
    )
    deps = SupervisorDeps(
        correlation_id=correlation_id,
        phase="initial",
        artifacts_file=artifacts_file,
        db_runtime_summary=db_runtime_summary or {},
        special_tool_capabilities=special_tool_capabilities or {},
        workflow_state=enriched_workflow_state,
        session_summary=conversation_context.get("session_summary"),
        recent_turn_summaries=conversation_context.get("recent_turn_summaries") or [],
        compaction_details={
            "compaction_applied": bool(conversation_context.get("compaction_applied")),
            "trimmed_turn_count": int(conversation_context.get("trimmed_turn_count") or 0),
        },
        step_start_callback=step_start_callback,
    )
    try:
        run_result = await supervisor_agent.run(
            f"Decide the first step for this Okta request: {user_query}",
            deps=deps,
            usage_limits=SUPERVISOR_USAGE_LIMITS,
        )
        decision = _normalize_initial_decision(run_result.output, enriched_workflow_state)
        logger.info(
            f"Supervisor initial decision: mode={decision.mode}, target={decision.target} - {decision.reasoning}"
        )
        return decision, run_result.usage()
    except Exception as exc:
        logger.error(f"Supervisor initial decision failed: {exc}", exc_info=True)
        return SupervisorDecision(
            mode="delegate",
            target="SQL",
            reasoning=f"Supervisor failed; falling back to SQL-first discovery: {exc}",
        ), None


async def supervise_next_step(
    user_query: str,
    *,
    correlation_id: str,
    artifacts_file: Path,
    delegation_results: List[Dict[str, Any]],
    latest_delegation_result: DelegationResult,
    db_runtime_summary: Optional[Dict[str, Any]] = None,
    special_tool_capabilities: Optional[Dict[str, Any]] = None,
    workflow_state: Optional[Dict[str, Any]] = None,
    step_start_callback: Optional[callable] = None,
) -> tuple[SupervisorDecision, Any]:
    """Choose the next step after a specialist returns a DelegationResult."""
    latest = latest_delegation_result.model_dump()
    conversation_context = await _load_supervisor_conversation_context(correlation_id)
    enriched_workflow_state = _build_followup_workflow_state(
        workflow_state,
        conversation_context.get("recent_turn_summaries") or [],
        {
            "compaction_applied": bool(conversation_context.get("compaction_applied")),
            "trimmed_turn_count": int(conversation_context.get("trimmed_turn_count") or 0),
        },
        user_query,
    )
    deps = SupervisorDeps(
        correlation_id=correlation_id,
        phase="after_delegation",
        artifacts_file=artifacts_file,
        db_runtime_summary=db_runtime_summary or {},
        special_tool_capabilities=special_tool_capabilities or {},
        workflow_state=enriched_workflow_state,
        delegation_results=delegation_results,
        latest_delegation_result=latest,
        session_summary=conversation_context.get("session_summary"),
        recent_turn_summaries=conversation_context.get("recent_turn_summaries") or [],
        compaction_details={
            "compaction_applied": bool(conversation_context.get("compaction_applied")),
            "trimmed_turn_count": int(conversation_context.get("trimmed_turn_count") or 0),
        },
        step_start_callback=step_start_callback,
    )
    try:
        run_result = await supervisor_agent.run(
            f"Decide the next step for the original request after the latest specialist result: {user_query}",
            deps=deps,
            usage_limits=SUPERVISOR_USAGE_LIMITS,
        )
        decision = _normalize_after_delegation_decision(run_result.output, latest_delegation_result)
        logger.info(
            f"Supervisor next decision: mode={decision.mode}, target={decision.target} - {decision.reasoning}"
        )
        return decision, run_result.usage()
    except Exception as exc:
        logger.error(f"Supervisor next-step decision failed: {exc}", exc_info=True)
        return _fallback_after_delegation_decision(latest_delegation_result, str(exc)), None


def _normalize_after_delegation_decision(
    decision: SupervisorDecision,
    latest_delegation_result: DelegationResult,
) -> SupervisorDecision:
    """Apply runtime safety corrections without replacing supervisor routing."""
    decision = _attach_latest_evidence(decision, latest_delegation_result)

    if latest_delegation_result.needs_specialists and decision.mode in _FINAL_MODES:
        target = _specialist_to_target(latest_delegation_result.needs_specialists[0])
        if target and target != "SYNTHESIS":
            return SupervisorDecision(
                mode="delegate",
                target=target,
                reasoning=(
                    "Latest specialist reported unresolved requirements, so runtime safety "
                    f"prevents early completion and delegates to {target}."
                ),
                requested_data=latest_delegation_result.unresolved_requirements,
            )

    if latest_delegation_result.status == "clarify_needed" and decision.mode not in {"clarify", "fail"}:
        return SupervisorDecision(
            mode="clarify",
            target="NONE",
            reasoning="Latest specialist requires clarification before another specialist can run safely.",
            user_message=latest_delegation_result.direct_answer or latest_delegation_result.summary,
        )

    if latest_delegation_result.success and latest_delegation_result.status == "empty" and decision.mode != "empty":
        return SupervisorDecision(
            mode="empty",
            target="NONE",
            result_mode="empty",
            reasoning="Latest specialist returned a validated empty result with no further specialist needs.",
            evidence_artifact_keys=latest_delegation_result.artifact_keys,
            evidence_result_set_refs=latest_delegation_result.result_set_refs,
        )

    if not latest_delegation_result.success and decision.mode in _FINAL_MODES:
        return SupervisorDecision(
            mode="fail",
            target="NONE",
            result_mode="failed",
            reasoning="Runtime safety rejected a completion decision because the latest specialist did not succeed.",
            user_message=latest_delegation_result.error or latest_delegation_result.summary,
        )

    if decision.mode == "empty" and latest_delegation_result.status != "empty":
        if latest_delegation_result.success and _has_final_evidence(decision, latest_delegation_result):
            return SupervisorDecision(
                mode="complete",
                target="SYNTHESIS",
                result_mode="synthesis_ready",
                reasoning="Runtime safety converted an empty decision to synthesis because evidence was found.",
                evidence_artifact_keys=decision.evidence_artifact_keys,
                evidence_result_set_refs=decision.evidence_result_set_refs,
            )
        return SupervisorDecision(
            mode="fail",
            target="NONE",
            result_mode="failed",
            reasoning="Runtime safety rejected an empty decision because the latest specialist did not validate zero results.",
            user_message=latest_delegation_result.error or latest_delegation_result.summary,
        )

    if decision.mode in {"complete", "degraded_success"} and not _has_final_evidence(decision, latest_delegation_result):
        return SupervisorDecision(
            mode="fail",
            target="NONE",
            result_mode="failed",
            reasoning="Runtime safety rejected completion because no evidence artifact keys or result-set refs were available.",
            user_message=latest_delegation_result.error or latest_delegation_result.summary,
        )

    if decision.mode == "complete" and _has_latest_gaps(latest_delegation_result):
        return SupervisorDecision(
            mode="degraded_success",
            target="SYNTHESIS",
            result_mode="degraded_success",
            reasoning="Runtime safety converted completion to degraded success because unresolved gaps remain.",
            evidence_artifact_keys=decision.evidence_artifact_keys,
            evidence_result_set_refs=decision.evidence_result_set_refs,
            requested_data=latest_delegation_result.unresolved_requirements,
        )

    if decision.mode == "degraded_success" and not _has_latest_gaps(latest_delegation_result):
        return SupervisorDecision(
            mode="complete",
            target="SYNTHESIS",
            result_mode="synthesis_ready",
            reasoning="Runtime safety converted degraded success to normal completion because no gaps remain.",
            evidence_artifact_keys=decision.evidence_artifact_keys,
            evidence_result_set_refs=decision.evidence_result_set_refs,
        )

    if latest_delegation_result.success and not latest_delegation_result.needs_specialists:
        latest_target = _specialist_to_target(latest_delegation_result.source_specialist)

        if latest_delegation_result.result_mode == "empty" and decision.mode == "delegate":
            return SupervisorDecision(
                mode="empty",
                target="NONE",
                result_mode="empty",
                reasoning="Latest specialist returned a validated empty result with no further specialist needs.",
                evidence_artifact_keys=latest_delegation_result.artifact_keys,
                evidence_result_set_refs=latest_delegation_result.result_set_refs,
            )

        if decision.mode == "delegate" and decision.target in _DELEGATE_TARGETS and decision.target != "PROCESSOR":
            # Allow valid cross-specialist follow-up work like SPECIAL -> SQL or SQL -> API.
            # Only collapse the decision when the supervisor is replaying the same specialist
            # without explicit unresolved specialist needs from the latest result.
            if decision.target == latest_target:
                return SupervisorDecision(
                    mode="complete",
                    target="SYNTHESIS",
                    result_mode="synthesis_ready",
                    reasoning="Latest specialist produced sufficient evidence with no further specialist needs.",
                    evidence_artifact_keys=latest_delegation_result.artifact_keys,
                    evidence_result_set_refs=latest_delegation_result.result_set_refs,
                )

    return decision


def _attach_latest_evidence(
    decision: SupervisorDecision,
    latest_delegation_result: DelegationResult,
) -> SupervisorDecision:
    if decision.mode not in _FINAL_MODES:
        return decision

    artifact_keys = decision.evidence_artifact_keys or latest_delegation_result.artifact_keys
    result_set_refs = decision.evidence_result_set_refs or latest_delegation_result.result_set_refs
    if artifact_keys == decision.evidence_artifact_keys and result_set_refs == decision.evidence_result_set_refs:
        return decision

    data = decision.model_dump()
    data["evidence_artifact_keys"] = artifact_keys
    data["evidence_result_set_refs"] = result_set_refs
    return SupervisorDecision(**data)


def _has_final_evidence(
    decision: SupervisorDecision,
    latest_delegation_result: DelegationResult,
) -> bool:
    return bool(
        decision.evidence_artifact_keys
        or decision.evidence_result_set_refs
        or latest_delegation_result.direct_answer
    )


def _has_latest_gaps(latest_delegation_result: DelegationResult) -> bool:
    return bool(
        latest_delegation_result.needs_specialists
        or latest_delegation_result.unresolved_requirements
        or latest_delegation_result.capability_gaps
        or latest_delegation_result.status == "partial"
        or latest_delegation_result.result_mode == "degraded_success"
    )


def _fallback_after_delegation_decision(
    latest_delegation_result: DelegationResult,
    error: str,
) -> SupervisorDecision:
    if latest_delegation_result.needs_specialists:
        target = _specialist_to_target(latest_delegation_result.needs_specialists[0]) or "SYNTHESIS"
        if target != "SYNTHESIS":
            return SupervisorDecision(
                mode="delegate",
                target=target,
                reasoning=f"Supervisor fallback delegated from specialist contract after error: {error}",
                requested_data=latest_delegation_result.unresolved_requirements,
            )

    if latest_delegation_result.success:
        if latest_delegation_result.result_mode == "empty":
            return SupervisorDecision(
                mode="empty",
                target="NONE",
                result_mode="empty",
                reasoning=f"Supervisor fallback completing with an empty result after error: {error}",
                evidence_artifact_keys=latest_delegation_result.artifact_keys,
                evidence_result_set_refs=latest_delegation_result.result_set_refs,
            )

        return SupervisorDecision(
            mode="complete",
            target="SYNTHESIS",
            result_mode="synthesis_ready",
            reasoning=f"Supervisor fallback completing with available evidence after error: {error}",
            evidence_artifact_keys=latest_delegation_result.artifact_keys,
            evidence_result_set_refs=latest_delegation_result.result_set_refs,
        )

    return SupervisorDecision(
        mode="fail",
        target="NONE",
        result_mode="failed",
        reasoning=f"Latest specialist failed and supervisor fallback could not continue: {error}",
        user_message=latest_delegation_result.error or latest_delegation_result.summary,
    )


def _specialist_to_target(specialist: str) -> Optional[SupervisorTarget]:
    mapping: Dict[str, SupervisorTarget] = {
        "sql": "SQL",
        "api": "API",
        "special": "SPECIAL",
        "processor": "PROCESSOR",
        "analysis": "RESULT_ANALYSIS",
        "synthesis": "SYNTHESIS",
    }
    return mapping.get(str(specialist).lower())


__all__ = [
    "SupervisorDecision",
    "SupervisorDeps",
    "supervise_next_step",
    "supervise_query",
]