"""
Multi-Agent Orchestrator - Coordinates SQL, API, and Synthesis Agents

Responsibilities:
- Execute supervisor decisions with runtime guardrails
- Hand off between agents programmatically
- Aggregate event streams from all agents
- Return final script to executor

Pattern: Pydantic AI "Programmatic agent hand-off"
"""

from pathlib import Path
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass
import asyncio
import time
import json
import os

from src.config.settings import settings
from src.utils.logging import get_logger

# Import agents
from src.core.agents.supervisor_agent import (
    supervise_next_step,
    supervise_query,
    SupervisorDecision,
)
from src.core.agents.sql_discovery_agent import (
    execute_sql_discovery,
    SQLDiscoveryDeps,
    SQLDiscoveryResult,
    get_database_runtime_summary,
    get_last_sync_timestamp,
)
from src.core.agents.api_discovery_agent import (
    execute_api_discovery,
    APIDiscoveryDeps,
    APIDiscoveryResult
)
from src.core.agents.synthesis_agent import (
    execute_synthesis,
    SynthesisDeps,
    SynthesisResult
)
from src.core.agents.special_tools_handler import (
    get_special_tool_capability_summary,
    handle_special_query,
)
from src.core.okta.sync.operations import DatabaseOperations
from src.data.schemas.artifact_manifest import (
    DelegationResult,
    append_artifacts_to_file,
    build_artifact_prompt_context,
    load_artifacts_file,
)
from src.data.schemas.result_set_processor import (
    ResultSetOperation,
    ResultSetProcessingRequest,
    process_result_set_ref,
)
from src.core.agents.result_analysis_agent import execute_result_analysis
from src.data.schemas.runtime_storage import RUNTIME_ROOT

logger = get_logger("okta_ai_agent")


# ============================================================================
# Orchestrator Result
# ============================================================================

class OrchestratorResult:
    """Result from orchestrator execution"""
    def __init__(self):
        self.success: bool = False
        self.script_code: Optional[str] = None
        self.display_type: str = "table"
        self.error: Optional[str] = None
        self.outcome: str = "pending"
        self.result_mode: str = "continue"
        self.outcome_reason: Optional[str] = None
        self.user_message: Optional[str] = None
        self.is_degraded_success: bool = False
        self.is_special_tool: bool = False  # Flag to skip validation for special tools
        self.no_data_found: bool = False  # Flag when discovery succeeds but finds no data (0 artifacts)
        self.special_tool_data: Optional[Dict[str, Any]] = None
        self.special_tool_operation: Optional[str] = None
        self.special_tool_response_mode: Optional[str] = None
        self.delegation_results: List[Dict[str, Any]] = []
        
        # Phase results
        self.initial_supervisor_decision: Optional[SupervisorDecision] = None
        self.supervisor_decisions: List[Dict[str, Any]] = []
        self.sql_result: Optional[SQLDiscoveryResult] = None
        self.api_result: Optional[APIDiscoveryResult] = None
        self.synthesis_result: Optional[SynthesisResult] = None
        
        # Phases executed
        self.phases_executed: List[str] = []
        
        # Data source tracking (for frontend display)
        self.data_source_type: Optional[str] = None  # "sql", "api", or "hybrid"
        self.last_sync_time: Optional[str] = None  # ISO timestamp from database
        
        # Token usage tracking
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_tokens: int = 0
        self.total_requests: int = 0

    def outcome_metadata(self) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {
            "outcome": self.outcome,
            "result_mode": self.result_mode,
            "is_degraded_success": self.is_degraded_success,
        }
        if self.outcome_reason:
            metadata["outcome_reason"] = self.outcome_reason
        if self.user_message:
            metadata["user_message"] = self.user_message
        return metadata


@dataclass
class _NextTargetTransition:
    pending_api_request: Optional[List[str]] = None
    pending_sql_request: Optional[List[str]] = None
    pending_api_source: Optional[DelegationResult] = None
    pending_sql_source: Optional[DelegationResult] = None
    pending_processor_source: Optional[DelegationResult] = None
    pending_analysis_source: Optional[DelegationResult] = None
    pending_special_request: bool = False
    should_stop: bool = False
    repeated: bool = False

    def pending_requests(
        self,
    ) -> tuple[
        Optional[List[str]],
        Optional[List[str]],
        Optional[DelegationResult],
        Optional[DelegationResult],
        Optional[DelegationResult],
        Optional[DelegationResult],
        bool,
    ]:
        return (
            self.pending_api_request,
            self.pending_sql_request,
            self.pending_api_source,
            self.pending_sql_source,
            self.pending_processor_source,
            self.pending_analysis_source,
            self.pending_special_request,
        )


@dataclass
class _RuntimeStepResult:
    delegation: Optional[DelegationResult] = None
    next_target: Optional[str] = None
    global_tool_calls_counter: int = 0
    should_stop: bool = False
    should_break: bool = False


@dataclass
class _DiscoveryValidationResult:
    should_stop: bool
    post_processing_succeeded: bool = False


NO_DATA_FAILURE_HINTS = (
    "no data",
    "no matching data",
    "no matching",
    "no results",
    "no result",
    "no records",
    "no events",
    "0 results",
    "0 records",
    "0 items",
    "zero results",
    "zero records",
    "could not find any",
    "returned no data",
    "returned no results",
    "empty result",
)

HARD_FAILURE_HINTS = (
    "limit exceeded",
    "timeout",
    "timed out",
    "unauthorized",
    "forbidden",
    "permission",
    "authentication failed",
    "invalid token",
    "security",
    "syntax error",
    "network error",
    "connection error",
    "rate limit",
)


def _is_no_data_discovery_failure(discovery_result: Any) -> bool:
    """Return True when a failed specialist result really means no matching rows/events."""
    if not discovery_result or getattr(discovery_result, "success", False):
        return False
    if getattr(discovery_result, "needs_sql", None) or getattr(discovery_result, "needs_api", None):
        return False

    message = " ".join(
        str(value)
        for value in (
            getattr(discovery_result, "error", None),
            getattr(discovery_result, "reasoning", None),
        )
        if value
    ).lower()
    if not message:
        return False

    if any(hint in message for hint in HARD_FAILURE_HINTS):
        return False

    return any(hint in message for hint in NO_DATA_FAILURE_HINTS)


def _add_usage_to_result(result: OrchestratorResult, usage: Any) -> None:
    """Roll Pydantic AI usage into the orchestrator total counters."""
    if not usage:
        return
    result.total_input_tokens += usage.input_tokens
    result.total_output_tokens += usage.output_tokens
    result.total_tokens += usage.total_tokens
    result.total_requests += usage.requests


def _usage_token_dict(usage: Any) -> Dict[str, int]:
    if not usage:
        return {}
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "requests": usage.requests,
    }


def _load_api_endpoints() -> List[Dict[str, Any]]:
    endpoints_file = Path("src/data/schemas/Okta_API_entitity_endpoint_reference_GET_ONLY.json")
    try:
        with open(endpoints_file, "r", encoding="utf-8") as file_handle:
            endpoints_data = json.load(file_handle)
    except Exception as error:
        logger.warning(f"Failed to load endpoints file: {error}")
        return []

    endpoints = endpoints_data.get("endpoints", [])
    logger.debug(f"Loaded {len(endpoints)} API endpoints")
    return endpoints


def _load_artifacts_by_category(artifacts_file: Path, category: str | List[str]) -> Optional[str]:
    """Load compact artifact context for one or more categories without full payloads."""
    try:
        resolved_artifacts_file = artifacts_file.resolve()
        allowed_roots = [Path("logs").resolve(), RUNTIME_ROOT.resolve()]
        if not any(resolved_artifacts_file.is_relative_to(root) for root in allowed_roots):
            raise ValueError
    except (OSError, ValueError):
        logger.error(f"Unsafe artifacts file path: {artifacts_file}")
        return None

    if not artifacts_file.is_file():
        return None

    try:
        categories = [category] if isinstance(category, str) else list(category)
        context = build_artifact_prompt_context(artifacts_file, categories=categories)
        return context if context != "[]" else None
    except Exception as error:
        logger.warning(f"Failed to load {category} artifacts: {error}")
        return None


async def _hydrate_session_result_set_context(
    correlation_id: str,
    artifacts_file: Path,
) -> int:
    """Seed prior session result-set refs into the current turn runtime files for follow-up routing."""
    try:
        db_ops = DatabaseOperations()
        await db_ops.init_db()
        return await db_ops.hydrate_session_result_set_context_for_run(
            tenant_id=settings.tenant_id,
            run_id=correlation_id,
            artifacts_file=artifacts_file,
        )
    except Exception as error:
        logger.warning(f"[{correlation_id}] Failed to hydrate prior session result-set context: {error}")
        return 0


def _set_result_outcome(
    result: OrchestratorResult,
    outcome: str,
    *,
    result_mode: Optional[str] = None,
    reason: Optional[str] = None,
    user_message: Optional[str] = None,
) -> None:
    result.outcome = outcome
    result.result_mode = result_mode or {
        "success": "synthesis_ready",
        "direct_answer": "direct_answer",
        "empty": "empty",
        "degraded_success": "degraded_success",
        "clarify": "needs_clarification",
        "fail": "failed",
    }.get(outcome, result.result_mode)
    result.outcome_reason = reason or result.outcome_reason
    result.user_message = user_message or result.user_message
    if outcome == "empty":
        result.no_data_found = True
    result.is_degraded_success = outcome == "degraded_success"


def _apply_initial_terminal_decision(
    result: OrchestratorResult,
    decision: SupervisorDecision,
) -> bool:
    if decision.mode == "delegate":
        return False

    if decision.mode in {"complete", "degraded_success"}:
        return False

    if decision.mode == "fail":
        result.error = decision.user_message or "NOT-OKTA-RELATED"
        _set_result_outcome(
            result,
            "fail",
            reason=decision.reasoning,
            user_message=result.error,
        )
        return True

    if decision.mode == "clarify":
        result.error = decision.user_message or "Clarification required before routing"
        _set_result_outcome(
            result,
            "clarify",
            reason=decision.reasoning,
            user_message=result.error,
        )
        return True

    if decision.mode == "empty":
        result.success = True
        _set_result_outcome(
            result,
            "empty",
            reason=decision.reasoning,
            user_message=decision.user_message,
        )
        return True

    return False


def _should_run_initial_synthesis_direct(decision: SupervisorDecision) -> bool:
    return decision.target == "SYNTHESIS" and decision.mode in {"complete", "degraded_success"}


def _apply_followup_supervisor_decision(
    result: OrchestratorResult,
    decision: SupervisorDecision,
) -> Optional[str]:
    if decision.mode == "delegate":
        return decision.target

    if decision.mode == "complete":
        return None

    if decision.mode == "empty":
        result.success = True
        _set_result_outcome(
            result,
            "empty",
            reason=decision.reasoning,
            user_message=decision.user_message,
        )
        return "STOP"

    if decision.mode == "degraded_success":
        _set_result_outcome(
            result,
            "degraded_success",
            reason=decision.reasoning,
            user_message=decision.user_message,
        )
        return None

    result.error = decision.user_message or decision.reasoning
    _set_result_outcome(
        result,
        "clarify" if decision.mode == "clarify" else "fail",
        result_mode=decision.result_mode,
        reason=decision.reasoning,
        user_message=result.error,
    )
    return "STOP"


def _merge_supervisor_evidence_into_delegation(
    delegation: DelegationResult,
    decision: SupervisorDecision,
) -> None:
    """Preserve supervisor-selected evidence refs for deterministic follow-up steps."""
    if decision.target not in {"PROCESSOR", "RESULT_ANALYSIS"}:
        return

    for artifact_key in decision.evidence_artifact_keys:
        if artifact_key not in delegation.artifact_keys:
            delegation.artifact_keys.append(artifact_key)

    for result_set_ref in decision.evidence_result_set_refs:
        if result_set_ref not in delegation.result_set_refs:
            delegation.result_set_refs.append(result_set_ref)


def _discovery_degraded_reasons(
    result: OrchestratorResult,
    post_processing_delegation: Optional[DelegationResult],
) -> List[str]:
    has_success = bool(
        (result.sql_result and result.sql_result.success)
        or (result.api_result and result.api_result.success)
        or (post_processing_delegation and post_processing_delegation.success)
        or _has_successful_delegation(result, "processor")
        or _has_successful_delegation(result, "analysis")
        or _has_successful_delegation(result, "special")
    )
    if not has_success:
        return []

    reasons: List[str] = []
    if result.sql_result and not result.sql_result.success:
        reasons.append(f"SQL: {result.sql_result.error or result.sql_result.reasoning or 'failed'}")
    if result.api_result and not result.api_result.success:
        reasons.append(f"API: {result.api_result.error or result.api_result.reasoning or 'failed'}")
    if post_processing_delegation and not post_processing_delegation.success:
        source_label = str(post_processing_delegation.source_specialist or "processor").upper()
        reasons.append(f"{source_label}: {post_processing_delegation.error or post_processing_delegation.summary}")
    return reasons


def _has_successful_delegation(result: OrchestratorResult, source_specialist: str) -> bool:
    return any(
        delegation.get("source_specialist") == source_specialist and bool(delegation.get("success"))
        for delegation in result.delegation_results
    )


def _artifact_refs_for_category(artifacts_file: Path, category: str) -> tuple[List[str], List[str]]:
    artifact_keys: List[str] = []
    result_set_refs: List[str] = []
    for artifact in load_artifacts_file(artifacts_file):
        if artifact.get("category") != category:
            continue
        artifact_key = artifact.get("key") or artifact.get("artifact_key")
        if artifact_key:
            artifact_keys.append(str(artifact_key))
        for result_set_ref in artifact.get("result_set_refs") or []:
            result_set_refs.append(str(result_set_ref))
    return artifact_keys, result_set_refs


def _artifact_row_count(artifact: Dict[str, Any]) -> Optional[int]:
    inspection = artifact.get("result_set_inspection")
    if isinstance(inspection, dict) and isinstance(inspection.get("row_count"), int):
        return inspection.get("row_count")

    manifest = artifact.get("artifact_manifest")
    if isinstance(manifest, dict) and isinstance(manifest.get("row_count"), int):
        return manifest.get("row_count")

    return None


def _artifact_category_has_only_empty_results(artifacts_file: Path, category: str) -> bool:
    saw_artifact = False

    for artifact in load_artifacts_file(artifacts_file):
        if artifact.get("category") != category:
            continue

        saw_artifact = True
        row_count = _artifact_row_count(artifact)
        if row_count is None or row_count > 0:
            return False

    return saw_artifact


def _delegation_requirements(delegation: DelegationResult, fallback: str) -> List[str]:
    """Return neutral unresolved requirements for the next specialist run."""
    return list(delegation.unresolved_requirements or [fallback])


def _delegation_evidence(delegation: Optional[DelegationResult], fallback: Optional[List[str]]) -> List[str]:
    """Return neutral evidence labels, preserving legacy specialist compatibility."""
    if delegation and delegation.evidence_found:
        return list(delegation.evidence_found)
    return list(fallback or [])


def _anchored_result_scope_from_delegation(
    delegation: Optional[DelegationResult],
) -> Optional[Dict[str, Any]]:
    if not delegation:
        return None

    metadata = delegation.metadata if isinstance(delegation.metadata, dict) else {}
    anchored_scope = metadata.get("anchored_result_scope") if isinstance(metadata, dict) else None
    if isinstance(anchored_scope, dict):
        scope = dict(anchored_scope)
    else:
        scope = {}

    if delegation.result_set_refs and not scope.get("result_set_ids"):
        scope["result_set_ids"] = list(delegation.result_set_refs)

    if not scope:
        return None

    scope.setdefault("scope_preservation_required", bool(scope.get("result_set_ids")))
    scope.setdefault("source_specialist", delegation.source_specialist)
    return scope


def _followup_scope_prompt_context(
    source_delegation: Optional[DelegationResult],
) -> Dict[str, Any]:
    anchored_scope = _anchored_result_scope_from_delegation(source_delegation)
    if not anchored_scope:
        return {
            "followup_scope_summary": None,
            "followup_scope_context": None,
            "followup_result_set_refs": None,
        }

    return {
        "followup_scope_summary": source_delegation.summary if source_delegation else None,
        "followup_scope_context": json.dumps(anchored_scope, indent=2, default=str),
        "followup_result_set_refs": list(anchored_scope.get("result_set_ids") or []),
    }


def _inherit_anchored_result_scope(
    delegation: DelegationResult,
    source_delegation: Optional[DelegationResult],
) -> DelegationResult:
    anchored_scope = _anchored_result_scope_from_delegation(source_delegation)
    if not anchored_scope:
        return delegation

    metadata = dict(delegation.metadata or {})
    metadata.setdefault("anchored_result_scope", anchored_scope)
    return delegation.model_copy(update={"metadata": metadata})


def _requirement_signature(target: str, requirements: Optional[List[str]]) -> tuple[str, tuple[str, ...]]:
    normalized_requirements = tuple(
        sorted(
            str(requirement).strip().lower()
            for requirement in (requirements or [target])
            if str(requirement).strip()
        )
    )
    return target.lower(), normalized_requirements


def _record_requirement_step(
    seen_steps: set[tuple[str, tuple[str, ...]]],
    target: str,
    requirements: List[str],
) -> bool:
    signature = _requirement_signature(target, requirements)
    if signature in seen_steps:
        return False
    seen_steps.add(signature)
    return True


def _append_unique(target: List[str], values: Any) -> None:
    for value in values or []:
        text = str(value).strip()
        if text and text not in target:
            target.append(text)


def _build_workflow_state(
    *,
    result: OrchestratorResult,
    latest_delegation: Optional[DelegationResult],
    seen_requirement_steps: set[tuple[str, tuple[str, ...]]],
    iteration_count: int,
    max_iterations: int,
    global_tool_calls_counter: int,
    max_tool_calls: int,
) -> Dict[str, Any]:
    evidence_artifact_keys: List[str] = []
    evidence_result_set_refs: List[str] = []
    unresolved_requirements: List[str] = []
    capability_gaps: List[str] = []
    failed_specialists: List[str] = []
    status_counts: Dict[str, int] = {}
    latest_anchored_result_scope = _anchored_result_scope_from_delegation(latest_delegation)

    for delegation in result.delegation_results:
        source = str(delegation.get("source_specialist") or "unknown")
        status = str(delegation.get("status") or delegation.get("result_mode") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        _append_unique(evidence_artifact_keys, delegation.get("artifact_keys"))
        _append_unique(evidence_result_set_refs, delegation.get("result_set_refs"))
        _append_unique(unresolved_requirements, delegation.get("unresolved_requirements"))
        _append_unique(capability_gaps, delegation.get("capability_gaps"))
        if not delegation.get("success"):
            _append_unique(failed_specialists, [source])

    return {
        "completed_steps": list(result.phases_executed),
        "step_count": len(result.phases_executed),
        "latest_specialist": latest_delegation.source_specialist if latest_delegation else None,
        "latest_status": latest_delegation.status if latest_delegation else None,
        "latest_result_mode": latest_delegation.result_mode if latest_delegation else None,
        "latest_anchored_result_scope": latest_anchored_result_scope,
        "evidence_artifact_keys": evidence_artifact_keys,
        "evidence_result_set_refs": evidence_result_set_refs,
        "unresolved_requirements": unresolved_requirements,
        "capability_gaps": capability_gaps,
        "failed_specialists": failed_specialists,
        "status_counts": status_counts,
        "remaining_hops": max(0, max_iterations - iteration_count),
        "max_hops": max_iterations,
        "remaining_tool_calls": max(0, max_tool_calls - global_tool_calls_counter),
        "max_tool_calls": max_tool_calls,
        "seen_requirement_signatures": [
            f"{target}:{','.join(requirements)}"
            for target, requirements in sorted(seen_requirement_steps)
        ],
    }


def _processor_requirements(delegation: DelegationResult) -> List[str]:
    return list(delegation.result_set_refs or delegation.artifact_keys or ["processor"])


def _analysis_requirements(delegation: DelegationResult) -> List[str]:
    return list(delegation.result_set_refs or delegation.artifact_keys or ["analysis"])


def _infer_result_set_operation(user_query: str) -> ResultSetOperation:
    query = user_query.lower()
    if any(term in query for term in ("how many", "count", "number of", "total")):
        return "count"
    return "inspect"


def _processor_delegation_result(
    user_query: str,
    artifacts_file: Path,
    source_delegation: Optional[DelegationResult],
) -> DelegationResult:
    if not source_delegation or not source_delegation.result_set_refs:
        return DelegationResult(
            success=False,
            source_specialist="processor",
            result_mode="failed",
            summary="Result-set processor needs a saved result-set ref before it can run.",
            capability_gaps=["result_set_refs"],
            error="No result-set refs were available for deterministic processing.",
        )

    operation = _infer_result_set_operation(user_query)
    request = ResultSetProcessingRequest(
        result_set_id=source_delegation.result_set_refs[0],
        operation=operation,
        persist_result=False,
    )
    processor_result = process_result_set_ref(artifacts_file, request)
    if processor_result.success:
        artifact_key = f"processor_{operation}_{request.result_set_id}"
        append_artifacts_to_file(
            artifacts_file,
            [
                {
                    "key": artifact_key,
                    "category": "processor_results",
                    "content": json.dumps(
                        {
                            "summary": processor_result.summary,
                            "metadata": processor_result.metadata,
                        },
                        indent=2,
                        default=str,
                    ),
                    "notes": processor_result.summary,
                    "result_set_refs": processor_result.result_set_refs,
                }
            ],
        )
        processor_result.artifact_keys = list(processor_result.artifact_keys or source_delegation.artifact_keys)
        if artifact_key not in processor_result.artifact_keys:
            processor_result.artifact_keys.append(artifact_key)
        processor_result.evidence_found = processor_result.evidence_found or [
            f"{operation}:{request.result_set_id}"
        ]
        processor_result.metadata = {
            **processor_result.metadata,
            "requested_operation": operation,
        }
    return processor_result


def _sql_delegation_result(
    sql_result: SQLDiscoveryResult,
    artifacts_file: Path,
    usage: Any,
) -> DelegationResult:
    artifact_keys, result_set_refs = _artifact_refs_for_category(artifacts_file, "sql_results")
    empty_sql_artifacts = _artifact_category_has_only_empty_results(artifacts_file, "sql_results")
    needs_api = list(sql_result.needs_api or [])
    found_data = list(sql_result.found_data or [])
    if sql_result.success and not needs_api and not found_data and (
        empty_sql_artifacts or (not artifact_keys and not result_set_refs)
    ):
        result_mode = "empty"
    elif sql_result.success and needs_api:
        result_mode = "continue"
    elif sql_result.success:
        result_mode = "synthesis_ready"
    else:
        result_mode = "failed"

    return DelegationResult(
        success=sql_result.success,
        source_specialist="sql",
        result_mode=result_mode,
        summary=sql_result.reasoning or sql_result.error or "SQL specialist completed.",
        artifact_keys=artifact_keys,
        result_set_refs=result_set_refs,
        needs_specialists=["api"] if needs_api else [],
        unresolved_requirements=needs_api,
        evidence_found=found_data,
        capability_gaps=needs_api,
        error=sql_result.error,
        token_usage=_usage_token_dict(usage),
        metadata={
            "found_data": found_data,
            "needs_api": needs_api,
        },
    )


def _api_delegation_result(
    api_result: APIDiscoveryResult,
    artifacts_file: Path,
    usage: Any,
) -> DelegationResult:
    artifact_keys, result_set_refs = _artifact_refs_for_category(artifacts_file, "api_results")
    needs_sql = list(api_result.needs_sql or [])
    found_data = list(api_result.found_data or [])
    if api_result.success and not needs_sql and not found_data and not artifact_keys and not result_set_refs:
        result_mode = "empty"
    elif api_result.success and needs_sql:
        result_mode = "continue"
    elif api_result.success:
        result_mode = "synthesis_ready"
    else:
        result_mode = "failed"

    return DelegationResult(
        success=api_result.success,
        source_specialist="api",
        result_mode=result_mode,
        summary=api_result.reasoning or api_result.error or "API specialist completed.",
        artifact_keys=artifact_keys,
        result_set_refs=result_set_refs,
        needs_specialists=["sql"] if needs_sql else [],
        unresolved_requirements=needs_sql,
        evidence_found=found_data,
        capability_gaps=needs_sql,
        error=api_result.error,
        token_usage=_usage_token_dict(usage),
        metadata={
            "found_data": found_data,
            "needs_sql": needs_sql,
            "api_data_retrieved": api_result.api_data_retrieved,
        },
    )


def _sql_context_for_api(
    result: OrchestratorResult,
    latest_sql_delegation: Optional[DelegationResult],
    artifacts_file: Path,
    source_delegation: Optional[DelegationResult] = None,
) -> Dict[str, Any]:
    context = {
        "sql_reasoning": None,
        "sql_discovered_data": None,
        "sql_needs_api": None,
        "sql_found_data": None,
        "followup_scope_summary": None,
        "followup_scope_context": None,
        "followup_result_set_refs": None,
    }

    context.update(_followup_scope_prompt_context(source_delegation or latest_sql_delegation))

    if result.sql_result and result.sql_result.success:
        context["sql_reasoning"] = result.sql_result.reasoning
        context["sql_needs_api"] = (
            _delegation_requirements(latest_sql_delegation, "api")
            if latest_sql_delegation
            else result.sql_result.needs_api
        )
        context["sql_found_data"] = _delegation_evidence(latest_sql_delegation, result.sql_result.found_data)
        context["sql_discovered_data"] = _load_artifacts_by_category(
            artifacts_file,
            ["sql_results", "session_result_refs"],
        )
        if context["sql_discovered_data"]:
            logger.info(f"Passing SQL discovered data to API agent ({len(context['sql_discovered_data'])} chars)")
    elif result.sql_result:
        context["sql_reasoning"] = f"SQL phase failed: {result.sql_result.error}"

    return context


def _api_context_for_sql(
    result: OrchestratorResult,
    latest_api_delegation: Optional[DelegationResult],
    pending_sql_request: List[str],
    artifacts_file: Path,
    source_delegation: Optional[DelegationResult] = None,
) -> Dict[str, Any]:
    api_found_data = _delegation_evidence(
        latest_api_delegation,
        result.api_result.found_data if result.api_result else [],
    )
    if result.api_result and result.api_result.success and result.api_result.reasoning:
        api_reasoning = result.api_result.reasoning
    else:
        api_reasoning = f"API agent needs base entities: {', '.join(pending_sql_request)}"

    api_discovered_data = _load_artifacts_by_category(
        artifacts_file,
        ["api_results", "session_result_refs"],
    )
    if api_discovered_data:
        logger.info(f"Passing API discovered data to SQL agent ({len(api_discovered_data)} chars)")

    context = {
        "api_reasoning": api_reasoning,
        "api_discovered_data": api_discovered_data,
        "api_needs_sql": pending_sql_request,
        "api_found_data": api_found_data,
    }
    context.update(_followup_scope_prompt_context(source_delegation or latest_api_delegation))
    return context


def _next_target_transition(
    *,
    next_target: Optional[str],
    source_label: str,
    source_delegation: DelegationResult,
    seen_requirement_steps: set[tuple[str, tuple[str, ...]]],
) -> _NextTargetTransition:
    transition = _NextTargetTransition()

    if next_target == "STOP":
        transition.should_stop = True
        return transition

    if next_target == "API":
        candidate_request = _delegation_requirements(source_delegation, "api")
        if not _record_requirement_step(seen_requirement_steps, "api", candidate_request):
            logger.warning(f"Stopping repeated API requirement loop: {candidate_request}")
            transition.repeated = True
            return transition
        transition.pending_api_request = candidate_request
        transition.pending_api_source = source_delegation
        logger.info(f"Supervisor delegates from {source_label} to API: {candidate_request}")
        return transition

    if next_target == "SQL":
        candidate_request = _delegation_requirements(source_delegation, "sql")
        if not _record_requirement_step(seen_requirement_steps, "sql", candidate_request):
            logger.warning(f"Stopping repeated SQL requirement loop: {candidate_request}")
            transition.repeated = True
            return transition
        transition.pending_sql_request = candidate_request
        transition.pending_sql_source = source_delegation
        logger.info(f"Supervisor delegates from {source_label} to SQL: {candidate_request}")
        return transition

    if next_target == "PROCESSOR":
        candidate_request = _processor_requirements(source_delegation)
        if not _record_requirement_step(seen_requirement_steps, "processor", candidate_request):
            logger.warning(f"Stopping repeated processor requirement loop: {candidate_request}")
            transition.repeated = True
            return transition
        transition.pending_processor_source = source_delegation
        logger.info(f"Supervisor delegates from {source_label} to result-set processor: {candidate_request}")

    if next_target == "RESULT_ANALYSIS":
        candidate_request = _analysis_requirements(source_delegation)
        if not _record_requirement_step(seen_requirement_steps, "analysis", candidate_request):
            logger.warning(f"Stopping repeated result analysis requirement loop: {candidate_request}")
            transition.repeated = True
            return transition
        transition.pending_analysis_source = source_delegation
        logger.info(f"Supervisor delegates from {source_label} to result analysis: {candidate_request}")

    if next_target == "SPECIAL":
        candidate_request = _delegation_requirements(source_delegation, "special")
        if not _record_requirement_step(seen_requirement_steps, "special", candidate_request):
            logger.warning(f"Stopping repeated SPECIAL requirement loop: {candidate_request}")
            transition.repeated = True
            return transition
        transition.pending_special_request = True
        logger.info(f"Supervisor delegates from {source_label} to SPECIAL: {candidate_request}")

    return transition


# ============================================================================
# Decision Functions (REMOVED - Now using Supervisor Agent)
# ============================================================================

# Old keyword-based functions removed - replaced with supervisor control-plane decisions.


# ============================================================================
# Event Streaming
# ============================================================================

class EventAggregator:
    """Aggregates events from multiple agents and renumbers steps"""
    
    def __init__(self, event_callback):
        self.event_callback = event_callback
        self.phase_offsets = {
            'sql': 0,     # Steps 1-5
            'api': 5,     # Steps 6-10
            'processor': 10,
            'analysis': 15,
            'synthesis': 20
        }
        self.current_phase = None
    
    def set_phase(self, phase: str):
        """Set current phase for step offset"""
        self.current_phase = phase
        logger.debug(f"Event aggregator: Now in {phase} phase")
    
    async def step_start(self, event: Dict[str, Any]):
        """Forward step_start event with renumbered step"""
        if self.event_callback:
            if self.current_phase:
                offset = self.phase_offsets.get(self.current_phase, 0)
                event['step'] = event.get('step', 1) + offset
            else:
                # No phase set - use step 0 for initial messages
                event['step'] = 0
            await self.event_callback('step_start', event)
    
    async def step_end(self, event: Dict[str, Any]):
        """Forward step_end event with renumbered step"""
        if self.current_phase and self.event_callback:
            offset = self.phase_offsets.get(self.current_phase, 0)
            event['step'] = event.get('step', 1) + offset
            await self.event_callback('step_end', event)
    
    async def tool_call(self, event: Dict[str, Any]):
        """Forward tool_call event (no renumbering needed)"""
        if self.event_callback:
            await self.event_callback('tool_call', event)
    
    async def progress(self, event: Dict[str, Any]):
        """Forward progress event (no renumbering needed)"""
        if self.event_callback:
            await self.event_callback('progress', event)


async def _run_initial_sql_discovery(
    *,
    result: OrchestratorResult,
    phase: str,
    db_runtime_summary: Dict[str, Any],
    user_query: str,
    correlation_id: str,
    artifacts_file: Path,
    okta_client: Any,
    cancellation_check: callable,
    aggregator: EventAggregator,
    global_tool_calls_counter: int,
    max_tool_calls: int,
) -> tuple[str, int, Any, bool]:
    initial_sql_usage = None
    should_run_sql = phase == "SQL"

    if should_run_sql and not bool(db_runtime_summary.get("usable_for_sql")):
        logger.info("Supervisor chose SQL, but database is unavailable or empty - using runtime-safe API fallback")
        return "API", global_tool_calls_counter, initial_sql_usage, False

    if not should_run_sql:
        logger.info(f"Skipped SQL Discovery (Supervisor decision: {phase})")
        return phase, global_tool_calls_counter, initial_sql_usage, False

    logger.info("Running SQL Discovery Agent")
    aggregator.set_phase('sql')
    result.phases_executed.append('sql')

    await aggregator.step_start({
        "title": "SQL Discovery",
        "text": "Analyzing database schema and executing SQL queries",
        "timestamp": time.time()
    })

    sql_deps = SQLDiscoveryDeps(
        correlation_id=correlation_id,
        artifacts_file=artifacts_file,
        okta_client=okta_client,
        cancellation_check=cancellation_check,
        step_start_callback=aggregator.step_start,
        step_end_callback=aggregator.step_end,
        tool_call_callback=aggregator.tool_call,
        progress_callback=aggregator.progress,
        global_tool_calls=global_tool_calls_counter,
        max_global_tool_calls=max_tool_calls,
    )

    result.sql_result, initial_sql_usage = await execute_sql_discovery(user_query, sql_deps)
    global_tool_calls_counter = sql_deps.global_tool_calls
    logger.info(f"Tool calls after SQL: {global_tool_calls_counter}/{max_tool_calls}")
    _add_usage_to_result(result, initial_sql_usage)

    if not result.sql_result.success:
        error_msg = result.sql_result.error or "SQL phase failed"
        logger.error(f"SQL phase failed: {error_msg}")

        if "limit exceeded" in error_msg.lower():
            await aggregator.step_end({
                "title": "Execution Stopped",
                "text": f"Error: {error_msg}",
                "timestamp": time.time()
            })
            result.error = error_msg
            _set_result_outcome(
                result,
                "fail",
                reason="SQL discovery stopped after a deterministic runtime limit.",
                user_message=error_msg,
            )
            return phase, global_tool_calls_counter, initial_sql_usage, True

        logger.info("Continuing to API phase despite SQL error")

    return phase, global_tool_calls_counter, initial_sql_usage, False


async def _ask_supervisor_after_delegation(
    *,
    user_query: str,
    correlation_id: str,
    artifacts_file: Path,
    result: OrchestratorResult,
    latest_delegation: DelegationResult,
    db_runtime_summary: Dict[str, Any],
    special_tool_capabilities: Dict[str, Any],
    workflow_state: Dict[str, Any],
    aggregator: EventAggregator,
) -> Optional[str]:
    supervisor_decision, supervisor_usage = await supervise_next_step(
        user_query,
        correlation_id=correlation_id,
        artifacts_file=artifacts_file,
        delegation_results=result.delegation_results,
        latest_delegation_result=latest_delegation,
        db_runtime_summary=db_runtime_summary,
        special_tool_capabilities=special_tool_capabilities,
        workflow_state=workflow_state,
        step_start_callback=aggregator.step_start,
    )
    result.supervisor_decisions.append(supervisor_decision.model_dump())
    _add_usage_to_result(result, supervisor_usage)

    _merge_supervisor_evidence_into_delegation(latest_delegation, supervisor_decision)

    return _apply_followup_supervisor_decision(result, supervisor_decision)


async def _run_processor_loop_step(
    *,
    result: OrchestratorResult,
    user_query: str,
    artifacts_file: Path,
    aggregator: EventAggregator,
    source_delegation: Optional[DelegationResult],
    iteration_count: int,
    max_iterations: int,
    supervisor_next_target: Callable[[DelegationResult], Any],
) -> tuple[DelegationResult, Optional[str]]:
    logger.info(f"Running Result-Set Processor (iteration {iteration_count}/{max_iterations})")
    aggregator.set_phase('processor')
    result.phases_executed.append('processor')

    await aggregator.step_start({
        "title": "Result Processing",
        "text": "Processing saved result-set references",
        "timestamp": time.time()
    })

    processor_delegation = _processor_delegation_result(
        user_query,
        artifacts_file,
        source_delegation,
    )
    result.delegation_results.append(processor_delegation.model_dump())
    next_target = await supervisor_next_target(processor_delegation)
    return processor_delegation, next_target


async def _run_analysis_loop_step(
    *,
    result: OrchestratorResult,
    user_query: str,
    correlation_id: str,
    artifacts_file: Path,
    aggregator: EventAggregator,
    source_delegation: Optional[DelegationResult],
    iteration_count: int,
    max_iterations: int,
    supervisor_next_target: Callable[[DelegationResult], Any],
) -> tuple[DelegationResult, Optional[str]]:
    logger.info(f"Running Result Analysis Agent (iteration {iteration_count}/{max_iterations})")
    aggregator.set_phase('analysis')
    result.phases_executed.append('analysis')

    await aggregator.step_start({
        "title": "Result Analysis",
        "text": "Analyzing saved result-set references from prior turns",
        "timestamp": time.time()
    })

    analysis_delegation, analysis_usage = await execute_result_analysis(
        user_query,
        correlation_id=correlation_id,
        artifacts_file=artifacts_file,
        preferred_result_set_refs=list(source_delegation.result_set_refs or []) if source_delegation else None,
    )
    _add_usage_to_result(result, analysis_usage)
    result.delegation_results.append(analysis_delegation.model_dump())
    next_target = await supervisor_next_target(analysis_delegation)
    return analysis_delegation, next_target


async def _run_special_loop_step(
    *,
    result: OrchestratorResult,
    user_query: str,
    correlation_id: str,
    artifacts_file: Path,
    okta_client: Any,
    aggregator: EventAggregator,
    iteration_count: int,
    max_iterations: int,
    supervisor_next_target: Callable[[DelegationResult], Any],
) -> _RuntimeStepResult:
    logger.info(f"Running Special Tool specialist (iteration {iteration_count}/{max_iterations})")
    aggregator.set_phase('special')
    result.phases_executed.append('special')

    await aggregator.step_start({
        "title": "Special Tool",
        "text": "Running specialized data collection",
        "timestamp": time.time()
    })

    special_result = await handle_special_query(
        user_query=user_query,
        okta_client=okta_client,
        correlation_id=correlation_id,
        progress_callback=aggregator.progress,
        artifacts_file=artifacts_file,
        response_mode="synthesis_ready",
    )

    result.special_tool_data = special_result.raw_result
    result.special_tool_operation = special_result.tool_operation
    result.special_tool_response_mode = special_result.response_mode
    special_delegation = special_result.delegation_result or DelegationResult(
        success=False,
        source_specialist="special",
        result_mode="failed",
        summary=special_result.error or "Special tool execution failed.",
        error=special_result.error,
    )

    if not special_result.success:
        result.delegation_results.append(special_delegation.model_dump())
        result.error = special_result.error or "Special tool execution failed"
        _set_result_outcome(
            result,
            "fail",
            reason="Special tool execution failed.",
            user_message=result.error,
        )
        logger.error(f"Special tool failed: {result.error}")
        return _RuntimeStepResult(special_delegation, should_stop=True)

    result.delegation_results.append(special_delegation.model_dump())
    next_target = await supervisor_next_target(special_delegation)
    await aggregator.step_end({
        "title": "Special Tool Complete",
        "text": special_delegation.summary,
        "timestamp": time.time()
    })
    return _RuntimeStepResult(special_delegation, next_target)


async def _run_api_loop_step(
    *,
    result: OrchestratorResult,
    user_query: str,
    correlation_id: str,
    artifacts_file: Path,
    endpoints_list: List[Dict[str, Any]],
    okta_client: Any,
    cancellation_check: callable,
    aggregator: EventAggregator,
    latest_sql_delegation: Optional[DelegationResult],
    source_delegation: Optional[DelegationResult],
    global_tool_calls_counter: int,
    max_tool_calls: int,
    iteration_count: int,
    max_iterations: int,
    supervisor_next_target: Callable[[DelegationResult], Any],
) -> _RuntimeStepResult:
    logger.info(f"Running API Discovery Agent (iteration {iteration_count}/{max_iterations})")
    aggregator.set_phase('api')
    result.phases_executed.append('api')
    sql_context = _sql_context_for_api(
        result,
        latest_sql_delegation,
        artifacts_file,
        source_delegation=source_delegation,
    )

    await aggregator.step_start({
        "title": "API Discovery",
        "text": "Generating and testing API code to fetch additional data",
        "timestamp": time.time()
    })

    api_deps = APIDiscoveryDeps(
        correlation_id=correlation_id,
        artifacts_file=artifacts_file,
        endpoints=endpoints_list,
        sql_reasoning=sql_context["sql_reasoning"],
        sql_discovered_data=sql_context["sql_discovered_data"],
        sql_needs_api=sql_context["sql_needs_api"],
        sql_found_data=sql_context["sql_found_data"],
        followup_scope_summary=sql_context["followup_scope_summary"],
        followup_scope_context=sql_context["followup_scope_context"],
        followup_result_set_refs=sql_context["followup_result_set_refs"],
        okta_client=okta_client,
        cancellation_check=cancellation_check,
        step_start_callback=aggregator.step_start,
        step_end_callback=aggregator.step_end,
        tool_call_callback=aggregator.tool_call,
        progress_callback=aggregator.progress,
        global_tool_calls=global_tool_calls_counter,
        max_global_tool_calls=max_tool_calls
    )

    result.api_result, api_usage = await execute_api_discovery(user_query, api_deps)
    global_tool_calls_counter = api_deps.global_tool_calls
    logger.info(f"Tool calls after API: {global_tool_calls_counter}/{max_tool_calls}")

    _add_usage_to_result(result, api_usage)
    api_delegation = _api_delegation_result(result.api_result, artifacts_file, api_usage)
    api_delegation = _inherit_anchored_result_scope(api_delegation, source_delegation)

    if not result.api_result.success:
        error_msg = result.api_result.error or "API phase failed"
        logger.error(f"API phase failed: {error_msg}")
        sql_succeeded_before_api = bool(result.sql_result and result.sql_result.success)

        if _is_no_data_discovery_failure(result.api_result) and not sql_succeeded_before_api:
            logger.info("API discovery completed with no matching data")
            await aggregator.step_end({
                "title": "No Data Found",
                "text": "No matching data was found for this request.",
                "timestamp": time.time()
            })
            result.success = True
            _set_result_outcome(
                result,
                "empty",
                reason=result.api_result.reasoning or result.api_result.error,
                user_message="No matching data was found for this request.",
            )
            return _RuntimeStepResult(api_delegation, global_tool_calls_counter=global_tool_calls_counter, should_stop=True)

        if "limit exceeded" in error_msg.lower():
            await aggregator.step_end({
                "title": "Execution Stopped",
                "text": f"Error: {error_msg}",
                "timestamp": time.time()
            })
            result.error = error_msg
            _set_result_outcome(
                result,
                "fail",
                reason="API discovery stopped after a deterministic runtime limit.",
                user_message=error_msg,
            )
            return _RuntimeStepResult(api_delegation, global_tool_calls_counter=global_tool_calls_counter, should_stop=True)

        if api_delegation.unresolved_requirements:
            logger.info(f"API has unresolved requirements for SQL: {api_delegation.unresolved_requirements}")
        else:
            logger.info("Exiting discovery loop due to API error (no unresolved requirements)")
            return _RuntimeStepResult(api_delegation, global_tool_calls_counter=global_tool_calls_counter, should_break=True)

    result.delegation_results.append(api_delegation.model_dump())
    next_target = await supervisor_next_target(api_delegation)
    return _RuntimeStepResult(api_delegation, next_target, global_tool_calls_counter)


async def _run_sql_followup_loop_step(
    *,
    result: OrchestratorResult,
    user_query: str,
    correlation_id: str,
    artifacts_file: Path,
    okta_client: Any,
    cancellation_check: callable,
    aggregator: EventAggregator,
    pending_sql_request: List[str],
    latest_api_delegation: Optional[DelegationResult],
    source_delegation: Optional[DelegationResult],
    db_runtime_summary: Dict[str, Any],
    global_tool_calls_counter: int,
    max_tool_calls: int,
    iteration_count: int,
    max_iterations: int,
    supervisor_next_target: Callable[[DelegationResult], Any],
) -> _RuntimeStepResult:
    logger.info(f"API agent requests SQL data: {pending_sql_request}")
    logger.info(f"Running SQL Discovery Agent (iteration {iteration_count}/{max_iterations})")

    db_healthy = bool(db_runtime_summary.get("usable_for_sql"))
    if not db_healthy:
        logger.warning("API needs SQL but DB is unavailable - exiting discovery loop")
        return _RuntimeStepResult(global_tool_calls_counter=global_tool_calls_counter, should_break=True)

    aggregator.set_phase('sql')
    result.phases_executed.append('sql')

    await aggregator.step_start({
        "title": "SQL Discovery",
        "text": f"Fetching base entities from database: {', '.join(pending_sql_request)}",
        "timestamp": time.time()
    })

    api_context = _api_context_for_sql(
        result,
        latest_api_delegation,
        pending_sql_request,
        artifacts_file,
        source_delegation=source_delegation,
    )

    sql_deps = SQLDiscoveryDeps(
        correlation_id=correlation_id,
        artifacts_file=artifacts_file,
        okta_client=okta_client,
        cancellation_check=cancellation_check,
        api_reasoning=api_context["api_reasoning"],
        api_discovered_data=api_context["api_discovered_data"],
        api_needs_sql=api_context["api_needs_sql"],
        api_found_data=api_context["api_found_data"],
        followup_scope_summary=api_context["followup_scope_summary"],
        followup_scope_context=api_context["followup_scope_context"],
        followup_result_set_refs=api_context["followup_result_set_refs"],
        step_start_callback=aggregator.step_start,
        step_end_callback=aggregator.step_end,
        tool_call_callback=aggregator.tool_call,
        progress_callback=aggregator.progress,
        global_tool_calls=global_tool_calls_counter,
        max_global_tool_calls=max_tool_calls
    )

    result.sql_result, sql_usage = await execute_sql_discovery(user_query, sql_deps)
    global_tool_calls_counter = sql_deps.global_tool_calls
    logger.info(f"Tool calls after SQL: {global_tool_calls_counter}/{max_tool_calls}")

    _add_usage_to_result(result, sql_usage)
    sql_delegation = _sql_delegation_result(result.sql_result, artifacts_file, sql_usage)
    sql_delegation = _inherit_anchored_result_scope(sql_delegation, source_delegation)

    if not result.sql_result.success:
        error_msg = result.sql_result.error or "SQL phase failed"
        if "limit exceeded" in error_msg.lower():
            await aggregator.step_end({
                "title": "Execution Stopped",
                "text": f"Error: {error_msg}",
                "timestamp": time.time()
            })
            result.error = error_msg
            _set_result_outcome(
                result,
                "fail",
                reason="SQL discovery stopped after a deterministic runtime limit.",
                user_message=error_msg,
            )
            return _RuntimeStepResult(sql_delegation, global_tool_calls_counter=global_tool_calls_counter, should_stop=True)
        if sql_delegation.unresolved_requirements:
            logger.info(f"SQL has unresolved requirements for API: {sql_delegation.unresolved_requirements}")
        else:
            logger.info("Exiting discovery loop due to SQL error (no unresolved requirements)")
            return _RuntimeStepResult(sql_delegation, global_tool_calls_counter=global_tool_calls_counter, should_break=True)

    result.delegation_results.append(sql_delegation.model_dump())
    next_target = await supervisor_next_target(sql_delegation)
    return _RuntimeStepResult(sql_delegation, next_target, global_tool_calls_counter)


async def _run_discovery_loop(
    *,
    result: OrchestratorResult,
    phase: str,
    initial_sql_usage: Any,
    user_query: str,
    correlation_id: str,
    artifacts_file: Path,
    okta_client: Any,
    cancellation_check: callable,
    aggregator: EventAggregator,
    endpoints_list: List[Dict[str, Any]],
    db_runtime_summary: Dict[str, Any],
    special_tool_capabilities: Dict[str, Any],
    global_tool_calls_counter: int,
    max_tool_calls: int,
) -> tuple[Optional[DelegationResult], bool]:
    max_iterations = 6
    iteration_count = 0
    pending_api_request = None
    pending_sql_request = None
    pending_api_source: Optional[DelegationResult] = None
    pending_sql_source: Optional[DelegationResult] = None
    pending_processor_source: Optional[DelegationResult] = None
    pending_analysis_source: Optional[DelegationResult] = None
    pending_special_request = False
    latest_sql_delegation: Optional[DelegationResult] = None
    latest_api_delegation: Optional[DelegationResult] = None
    latest_processor_delegation: Optional[DelegationResult] = None
    latest_special_delegation: Optional[DelegationResult] = None
    seen_requirement_steps: set[tuple[str, tuple[str, ...]]] = set()

    async def supervisor_next_target(latest_delegation: DelegationResult) -> Optional[str]:
        workflow_state = _build_workflow_state(
            result=result,
            latest_delegation=latest_delegation,
            seen_requirement_steps=seen_requirement_steps,
            iteration_count=iteration_count,
            max_iterations=max_iterations,
            global_tool_calls_counter=global_tool_calls_counter,
            max_tool_calls=max_tool_calls,
        )
        return await _ask_supervisor_after_delegation(
            user_query=user_query,
            correlation_id=correlation_id,
            artifacts_file=artifacts_file,
            result=result,
            latest_delegation=latest_delegation,
            db_runtime_summary=db_runtime_summary,
            special_tool_capabilities=special_tool_capabilities,
            workflow_state=workflow_state,
            aggregator=aggregator,
        )

    if result.sql_result:
        latest_sql_delegation = _sql_delegation_result(result.sql_result, artifacts_file, initial_sql_usage)
        result.delegation_results.append(latest_sql_delegation.model_dump())
        next_target = await supervisor_next_target(latest_sql_delegation)
        transition = _next_target_transition(
            next_target=next_target,
            source_label="SQL",
            source_delegation=latest_sql_delegation,
            seen_requirement_steps=seen_requirement_steps,
        )
        if transition.should_stop or transition.repeated:
            return latest_processor_delegation, True
        pending_api_request, pending_sql_request, pending_api_source, pending_sql_source, pending_processor_source, pending_analysis_source, pending_special_request = transition.pending_requests()

    logger.info(f"Starting multi-step discovery loop (max {max_iterations} phases)")

    while iteration_count < max_iterations:
        should_run_api = phase == "API" or pending_api_request is not None
        should_run_sql = pending_sql_request is not None
        should_run_processor = phase == "PROCESSOR" or pending_processor_source is not None
        should_run_analysis = phase == "RESULT_ANALYSIS" or pending_analysis_source is not None
        should_run_special = phase == "SPECIAL" or pending_special_request

        if not should_run_api and not should_run_sql and not should_run_processor and not should_run_analysis and not should_run_special:
            logger.info(f"Discovery loop complete: No more phases needed (iterations: {iteration_count})")
            break

        processor_source = pending_processor_source
        analysis_source = pending_analysis_source
        api_source = pending_api_source
        sql_source = pending_sql_source
        pending_api_request = None
        pending_sql_request = None
        pending_api_source = None
        pending_sql_source = None
        pending_processor_source = None
        pending_analysis_source = None
        pending_special_request = False

        if should_run_special:
            iteration_count += 1
            special_step = await _run_special_loop_step(
                result=result,
                user_query=user_query,
                correlation_id=correlation_id,
                artifacts_file=artifacts_file,
                okta_client=okta_client,
                aggregator=aggregator,
                iteration_count=iteration_count,
                max_iterations=max_iterations,
                supervisor_next_target=supervisor_next_target,
            )
            latest_special_delegation = special_step.delegation or latest_special_delegation
            if special_step.should_stop:
                return latest_processor_delegation, True
            if special_step.should_break:
                break

            if phase == "SPECIAL":
                phase = None

            transition = _next_target_transition(
                next_target=special_step.next_target,
                source_label="SPECIAL",
                source_delegation=latest_special_delegation,
                seen_requirement_steps=seen_requirement_steps,
            )
            if transition.should_stop:
                return latest_processor_delegation, True
            if transition.repeated:
                break
            pending_api_request, pending_sql_request, pending_api_source, pending_sql_source, pending_processor_source, pending_analysis_source, pending_special_request = transition.pending_requests()

        if should_run_processor:
            iteration_count += 1
            source_delegation = processor_source or latest_api_delegation or latest_sql_delegation
            latest_processor_delegation, next_target = await _run_processor_loop_step(
                result=result,
                user_query=user_query,
                artifacts_file=artifacts_file,
                aggregator=aggregator,
                source_delegation=source_delegation,
                iteration_count=iteration_count,
                max_iterations=max_iterations,
                supervisor_next_target=supervisor_next_target,
            )

            if phase == "PROCESSOR":
                phase = None

            transition = _next_target_transition(
                next_target=next_target,
                source_label="processor",
                source_delegation=latest_processor_delegation,
                seen_requirement_steps=seen_requirement_steps,
            )
            if transition.should_stop:
                return latest_processor_delegation, True
            if transition.repeated:
                break
            pending_api_request, pending_sql_request, pending_api_source, pending_sql_source, pending_processor_source, pending_analysis_source, pending_special_request = transition.pending_requests()

            await aggregator.step_end({
                "title": "Result Processing Complete",
                "text": latest_processor_delegation.summary,
                "timestamp": time.time()
            })

        if should_run_analysis:
            iteration_count += 1
            source_delegation = analysis_source or latest_api_delegation or latest_sql_delegation or latest_processor_delegation
            latest_processor_delegation, next_target = await _run_analysis_loop_step(
                result=result,
                user_query=user_query,
                correlation_id=correlation_id,
                artifacts_file=artifacts_file,
                aggregator=aggregator,
                source_delegation=source_delegation,
                iteration_count=iteration_count,
                max_iterations=max_iterations,
                supervisor_next_target=supervisor_next_target,
            )

            if phase == "RESULT_ANALYSIS":
                phase = None

            transition = _next_target_transition(
                next_target=next_target,
                source_label="analysis",
                source_delegation=latest_processor_delegation,
                seen_requirement_steps=seen_requirement_steps,
            )
            if transition.should_stop:
                return latest_processor_delegation, True
            if transition.repeated:
                break
            pending_api_request, pending_sql_request, pending_api_source, pending_sql_source, pending_processor_source, pending_analysis_source, pending_special_request = transition.pending_requests()

            await aggregator.step_end({
                "title": "Result Analysis Complete",
                "text": latest_processor_delegation.summary,
                "timestamp": time.time()
            })

        if should_run_api:
            iteration_count += 1
            api_step = await _run_api_loop_step(
                result=result,
                user_query=user_query,
                correlation_id=correlation_id,
                artifacts_file=artifacts_file,
                endpoints_list=endpoints_list,
                okta_client=okta_client,
                cancellation_check=cancellation_check,
                aggregator=aggregator,
                latest_sql_delegation=latest_sql_delegation,
                source_delegation=api_source or latest_sql_delegation,
                global_tool_calls_counter=global_tool_calls_counter,
                max_tool_calls=max_tool_calls,
                iteration_count=iteration_count,
                max_iterations=max_iterations,
                supervisor_next_target=supervisor_next_target,
            )
            global_tool_calls_counter = api_step.global_tool_calls_counter
            latest_api_delegation = api_step.delegation or latest_api_delegation
            if api_step.should_stop:
                return latest_processor_delegation, True
            if api_step.should_break:
                break

            if phase == "API":
                phase = None

            transition = _next_target_transition(
                next_target=api_step.next_target,
                source_label="API",
                source_delegation=latest_api_delegation,
                seen_requirement_steps=seen_requirement_steps,
            )
            if transition.should_stop:
                return latest_processor_delegation, True
            if transition.repeated:
                break
            pending_api_request, pending_sql_request, pending_api_source, pending_sql_source, pending_processor_source, pending_analysis_source, pending_special_request = transition.pending_requests()

        if pending_sql_request is not None:
            iteration_count += 1
            sql_step = await _run_sql_followup_loop_step(
                result=result,
                user_query=user_query,
                correlation_id=correlation_id,
                artifacts_file=artifacts_file,
                okta_client=okta_client,
                cancellation_check=cancellation_check,
                aggregator=aggregator,
                pending_sql_request=pending_sql_request,
                latest_api_delegation=latest_api_delegation,
                source_delegation=sql_source or latest_api_delegation,
                db_runtime_summary=db_runtime_summary,
                global_tool_calls_counter=global_tool_calls_counter,
                max_tool_calls=max_tool_calls,
                iteration_count=iteration_count,
                max_iterations=max_iterations,
                supervisor_next_target=supervisor_next_target,
            )
            global_tool_calls_counter = sql_step.global_tool_calls_counter
            latest_sql_delegation = sql_step.delegation or latest_sql_delegation
            if sql_step.should_stop:
                return latest_processor_delegation, True
            if sql_step.should_break:
                break

            transition = _next_target_transition(
                next_target=sql_step.next_target,
                source_label="SQL",
                source_delegation=latest_sql_delegation,
                seen_requirement_steps=seen_requirement_steps,
            )
            if transition.should_stop:
                return latest_processor_delegation, True
            if transition.repeated:
                break
            pending_api_request, pending_sql_request, pending_api_source, pending_sql_source, pending_processor_source, pending_analysis_source, pending_special_request = transition.pending_requests()

            await aggregator.step_end({
                "title": "SQL Discovery Complete",
                "text": f"SQL data retrieved: {result.sql_result.success}",
                "timestamp": time.time()
            })

    if iteration_count >= max_iterations:
        logger.warning(f"Discovery loop hit maximum iterations ({max_iterations})")
        await aggregator.progress({
            "message": f"Reached maximum discovery phases ({max_iterations}), proceeding with available data"
        })
        _set_result_outcome(
            result,
            "degraded_success",
            reason=f"Reached maximum discovery phases ({max_iterations}) and continued with available evidence.",
            user_message="The answer uses available evidence because the discovery loop reached its runtime limit.",
        )

    return latest_processor_delegation, False


async def _validate_discovery_before_synthesis(
    *,
    result: OrchestratorResult,
    artifacts_file: Path,
    latest_processor_delegation: Optional[DelegationResult],
    aggregator: EventAggregator,
) -> _DiscoveryValidationResult:
    sql_succeeded = result.sql_result and result.sql_result.success
    api_succeeded = result.api_result and result.api_result.success
    processor_succeeded = _has_successful_delegation(result, "processor")
    analysis_succeeded = _has_successful_delegation(result, "analysis")
    post_processing_succeeded = bool(
        (latest_processor_delegation and latest_processor_delegation.success)
        or processor_succeeded
        or analysis_succeeded
    )
    special_succeeded = _has_successful_delegation(result, "special")

    if not sql_succeeded and not api_succeeded and not post_processing_succeeded and not special_succeeded:
        if _is_no_data_discovery_failure(result.sql_result) or _is_no_data_discovery_failure(result.api_result):
            logger.info("Discovery completed with no matching data")
            result.success = True
            no_data_result = result.sql_result if _is_no_data_discovery_failure(result.sql_result) else result.api_result
            _set_result_outcome(
                result,
                "empty",
                reason=getattr(no_data_result, "reasoning", None) or getattr(no_data_result, "error", None),
                user_message="No matching data was found for this request.",
            )
            return _DiscoveryValidationResult(True, bool(post_processing_succeeded))

        error_details = []
        if result.sql_result and not result.sql_result.success:
            error_details.append(f"SQL: {result.sql_result.error}")
        if result.api_result and not result.api_result.success:
            error_details.append(f"API: {result.api_result.error}")

        error_msg = "Discovery failed - no data retrieved. " + " | ".join(error_details) if error_details else "No discovery phases succeeded"
        logger.error(error_msg)

        await aggregator.step_end({
            "title": "Discovery Failed",
            "text": f"Error: {error_msg}",
            "timestamp": time.time()
        })

        result.error = error_msg
        _set_result_outcome(
            result,
            "fail",
            reason="Discovery failed before any usable evidence was produced.",
            user_message=error_msg,
        )
        return _DiscoveryValidationResult(True, bool(post_processing_succeeded))

    logger.info(f"Discovery validation passed (SQL: {sql_succeeded}, API: {api_succeeded})")

    try:
        artifacts = load_artifacts_file(artifacts_file)
        artifact_count = len(artifacts) if isinstance(artifacts, list) else 0

        if artifact_count == 0:
            logger.info("Discovery succeeded but found no data (0 artifacts)")
            result.success = True
            _set_result_outcome(
                result,
                "empty",
                reason="Discovery completed with zero artifacts.",
                user_message="No matching data was found for this request.",
            )
            return _DiscoveryValidationResult(True, bool(post_processing_succeeded))
    except Exception as error:
        logger.warning(f"Failed to check artifact count: {error}")

    return _DiscoveryValidationResult(False, bool(post_processing_succeeded))


async def _run_synthesis_phase(
    *,
    result: OrchestratorResult,
    user_query: str,
    correlation_id: str,
    artifacts_file: Path,
    aggregator: EventAggregator,
    latest_processor_delegation: Optional[DelegationResult],
    post_processing_succeeded: bool,
    cli_mode: bool,
) -> None:
    logger.info("Running Synthesis Agent")
    aggregator.set_phase('synthesis')

    await aggregator.step_start({
        "title": "Synthesis",
        "text": "Processing collected data and generating final script",
        "timestamp": time.time()
    })
    result.phases_executed.append('synthesis')

    synthesis_deps = SynthesisDeps(
        correlation_id=correlation_id,
        artifacts_file=artifacts_file,
        step_start_callback=aggregator.step_start,
        step_end_callback=aggregator.step_end,
        tool_call_callback=aggregator.tool_call,
        progress_callback=aggregator.progress,
        cli_mode=cli_mode
    )

    result.synthesis_result, synthesis_usage = await execute_synthesis(user_query, synthesis_deps)
    _add_usage_to_result(result, synthesis_usage)

    if not result.synthesis_result.success:
        logger.error(f"Synthesis failed: {result.synthesis_result.error}")
        result.error = result.synthesis_result.error
        _set_result_outcome(
            result,
            "fail",
            reason="Synthesis failed after discovery.",
            user_message=result.error,
        )
        return

    result.success = True
    result.script_code = result.synthesis_result.script_code
    result.display_type = result.synthesis_result.display_type
    degraded_reasons = _discovery_degraded_reasons(result, latest_processor_delegation)
    if degraded_reasons and result.outcome != "degraded_success":
        _set_result_outcome(
            result,
            "degraded_success",
            reason="; ".join(degraded_reasons),
            user_message="The answer uses available evidence, but one or more requested parts could not be fully retrieved.",
        )
    elif result.outcome == "pending":
        _set_result_outcome(
            result,
            "success",
            reason="Synthesis completed with available evidence.",
        )

    sql_succeeded = result.sql_result and result.sql_result.success
    api_succeeded = result.api_result and result.api_result.success
    special_succeeded = _has_successful_delegation(result, "special")
    analysis_succeeded = _has_successful_delegation(result, "analysis")

    if sql_succeeded and api_succeeded:
        result.data_source_type = "hybrid"
    elif sql_succeeded:
        result.data_source_type = "sql"
    elif api_succeeded:
        result.data_source_type = "api"
    elif post_processing_succeeded and latest_processor_delegation:
        result.data_source_type = str(latest_processor_delegation.source_specialist)
    elif analysis_succeeded:
        result.data_source_type = "analysis"
    elif special_succeeded:
        result.data_source_type = "special"

    if result.data_source_type in ["sql", "hybrid"]:
        result.last_sync_time = get_last_sync_timestamp()

    logger.info("Multi-agent workflow complete")
    logger.info(f"Phases executed: {', '.join(result.phases_executed)}")
    logger.info(f"Data source: {result.data_source_type}")
    logger.info(f"Outcome: {result.outcome} ({result.result_mode})")

    if result.total_tokens > 0:
        avg_per_call = result.total_input_tokens / result.total_requests if result.total_requests > 0 else 0
        logger.info(
            f"[{correlation_id}] TOTAL Token Usage: "
            f"{result.total_input_tokens:,} input, {result.total_output_tokens:,} output, "
            f"{result.total_tokens:,} total (across {result.total_requests} API calls, "
            f"avg {avg_per_call:,.0f} input/call)"
        )


# ============================================================================
# Main Orchestrator Function
# ============================================================================

async def execute_multi_agent_query(
    user_query: str,
    correlation_id: str,
    artifacts_file: Path,
    okta_client: Any,  # OktaClient instance
    cancellation_check: callable,
    event_callback: Optional[callable] = None,
    cli_mode: bool = False
) -> OrchestratorResult:
    """
    Execute multi-agent query workflow.
    
    Workflow:
    0. Ask the Supervisor Agent for the initial control-plane decision.
    1. Execute based on the supervisor decision:
         - delegate + SQL: Start in SQL Discovery
         - delegate + API: Start in API Discovery
            - delegate + SPECIAL: Run special tool handling
            - delegate + PROCESSOR: Process an existing result-set ref deterministically
            - delegate + RESULT_ANALYSIS: Analyze saved result-set refs from prior turns
         - clarify: Return a clarification message
         - fail: Return an error message
    2. Run Synthesis Agent (always, for any data workflow)
    3. Return final script
    
    Args:
        user_query: User's question
        correlation_id: Request tracking ID
        artifacts_file: Path to artifacts JSON file
        okta_client: Okta client instance
        cancellation_check: Function to check if cancelled
        event_callback: Callback for streaming events
    
    Returns:
        OrchestratorResult with script code and metadata
    """
    logger.info("Starting multi-agent orchestrator")
    logger.info(f"Query: {user_query}")
    
    result = OrchestratorResult()
    
    # Initialize global tool call limits from environment
    max_tool_calls = int(os.getenv('MAX_TOOL_CALLS', '30'))
    global_tool_calls_counter = 0  # Shared across all agents
    logger.info(f"Tool call limits: {max_tool_calls} total, 3 per tool type")
    
    endpoints_list = _load_api_endpoints()

    db_runtime_summary = get_database_runtime_summary()
    special_tool_capabilities = get_special_tool_capability_summary()
    
    # Event aggregator for streaming
    aggregator = EventAggregator(event_callback)
    
    # Send initial progress message
    await aggregator.step_start({
        "title": "Planning",
        "text": "Analyzing your request and planning data retrieval",
        "step": 0,  # Explicitly set step 0
        "timestamp": __import__('time').time()
    })
    
    try:
        hydrated_session_result_sets = await _hydrate_session_result_set_context(correlation_id, artifacts_file)
        if hydrated_session_result_sets:
            logger.info(
                f"[{correlation_id}] Hydrated {hydrated_session_result_sets} prior session result-set refs for follow-up resolution"
            )

        # ====================================================================
        # PHASE 0: Supervisor Decision (Control Plane)
        # ====================================================================
        logger.info("Running Supervisor Agent")
        result.initial_supervisor_decision, supervisor_usage = await supervise_query(
            user_query,
            correlation_id=correlation_id,
            artifacts_file=artifacts_file,
            db_runtime_summary=db_runtime_summary,
            special_tool_capabilities=special_tool_capabilities,
            workflow_state={
                "completed_steps": [],
                "step_count": 0,
                "has_prior_session_result_sets": hydrated_session_result_sets > 0,
                "hydrated_session_result_set_refs": hydrated_session_result_sets,
                "hydrated_session_result_set_count": hydrated_session_result_sets,
                "remaining_tool_calls": max_tool_calls,
                "max_tool_calls": max_tool_calls,
            },
            step_start_callback=aggregator.step_start,
        )
        result.supervisor_decisions.append(result.initial_supervisor_decision.model_dump())
        _add_usage_to_result(result, supervisor_usage)
        
        decision_mode = result.initial_supervisor_decision.mode
        phase = result.initial_supervisor_decision.target
        reasoning = result.initial_supervisor_decision.reasoning
        
        logger.info(f"Supervisor decision mode: {decision_mode}")
        logger.info(f"Supervisor decision target: {phase}")
        logger.info(f"Supervisor reasoning: {reasoning}")

        if _should_run_initial_synthesis_direct(result.initial_supervisor_decision):
            if decision_mode == "degraded_success":
                _set_result_outcome(
                    result,
                    "degraded_success",
                    reason=reasoning,
                    user_message=result.initial_supervisor_decision.user_message,
                )

            await _run_synthesis_phase(
                result=result,
                user_query=user_query,
                correlation_id=correlation_id,
                artifacts_file=artifacts_file,
                aggregator=aggregator,
                latest_processor_delegation=None,
                post_processing_succeeded=False,
                cli_mode=cli_mode,
            )
            return result
        
        if _apply_initial_terminal_decision(result, result.initial_supervisor_decision):
            return result
        
        # ====================================================================
        # PHASE 1: Initial SQL Discovery (if Supervisor → SQL AND DB is healthy)
        # Other specialist targets, including SPECIAL, enter the shared loop.
        # ====================================================================
        phase, global_tool_calls_counter, initial_sql_usage, should_stop = await _run_initial_sql_discovery(
            result=result,
            phase=phase,
            db_runtime_summary=db_runtime_summary,
            user_query=user_query,
            correlation_id=correlation_id,
            artifacts_file=artifacts_file,
            okta_client=okta_client,
            cancellation_check=cancellation_check,
            aggregator=aggregator,
            global_tool_calls_counter=global_tool_calls_counter,
            max_tool_calls=max_tool_calls,
        )
        if should_stop:
            return result

        latest_processor_delegation, should_stop = await _run_discovery_loop(
            result=result,
            phase=phase,
            initial_sql_usage=initial_sql_usage,
            user_query=user_query,
            correlation_id=correlation_id,
            artifacts_file=artifacts_file,
            okta_client=okta_client,
            cancellation_check=cancellation_check,
            aggregator=aggregator,
            endpoints_list=endpoints_list,
            db_runtime_summary=db_runtime_summary,
            special_tool_capabilities=special_tool_capabilities,
            global_tool_calls_counter=global_tool_calls_counter,
            max_tool_calls=max_tool_calls,
        )
        if should_stop:
            return result
        
        validation = await _validate_discovery_before_synthesis(
            result=result,
            artifacts_file=artifacts_file,
            latest_processor_delegation=latest_processor_delegation,
            aggregator=aggregator,
        )
        if validation.should_stop:
            return result

        await _run_synthesis_phase(
            result=result,
            user_query=user_query,
            correlation_id=correlation_id,
            artifacts_file=artifacts_file,
            aggregator=aggregator,
            latest_processor_delegation=latest_processor_delegation,
            post_processing_succeeded=validation.post_processing_succeeded,
            cli_mode=cli_mode,
        )
        
        return result
        
    except asyncio.CancelledError:
        logger.warning(f"Multi-agent workflow cancelled by user")
        result.error = "Cancelled by user"
        _set_result_outcome(
            result,
            "fail",
            reason="Workflow was cancelled.",
            user_message=result.error,
        )
        # Notify frontend of cancellation
        await aggregator.step_end({
            "title": "Workflow Cancelled",
            "text": "Execution cancelled by user",
            "timestamp": time.time()
        })
        return result
        
    except RuntimeError as e:
        # Tool call limit exceeded or other hard stop
        error_msg = str(e)
        logger.error(f"Hard stop triggered: {error_msg}")
        result.error = error_msg
        _set_result_outcome(
            result,
            "fail",
            reason="Runtime hard stop triggered.",
            user_message=error_msg,
        )
        # Notify frontend with proper error format
        await aggregator.step_end({
            "title": "Execution Stopped",
            "text": f"Error: {error_msg}",
            "timestamp": time.time()
        })
        return result
        
    except Exception as e:
        logger.error(f"Orchestrator error: {e}", exc_info=True)
        result.error = str(e)
        _set_result_outcome(
            result,
            "fail",
            reason="Unexpected orchestrator error.",
            user_message=result.error,
        )
        # Notify frontend of unexpected error
        await aggregator.step_end({
            "title": "Unexpected Error",
            "text": f"Error: {str(e)}",
            "timestamp": time.time()
        })
        return result
