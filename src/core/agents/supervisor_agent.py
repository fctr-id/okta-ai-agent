"""
Supervisor Agent - Phase 2C control-plane decisions.

The supervisor owns routing and follow-up delegation decisions while specialists
continue to own domain execution and validation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator
from pydantic_ai import RunContext, UsageLimits

from src.core.agents import build_agent
from src.core.models.model_picker import ModelType
from src.data.schemas.artifact_manifest import DelegationResult, build_artifact_prompt_context
from src.data.schemas.shared_schema import get_okta_database_schema
from src.utils.logging import get_logger

logger = get_logger("okta_ai_agent")


SupervisorMode = Literal["delegate", "complete", "empty", "degraded_success", "clarify", "fail"]
SupervisorTarget = Literal["SQL", "API", "SPECIAL", "SYNTHESIS", "NONE"]
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

    @model_validator(mode="after")
    def validate_decision(self) -> "SupervisorDecision":
        if self.mode == "delegate" and self.target not in {"SQL", "API", "SPECIAL"}:
            raise ValueError("Delegate decisions must target SQL, API, or SPECIAL")

        if self.mode == "delegate":
            self.result_mode = "continue"

        if self.mode == "complete" and self.target not in {"SYNTHESIS", "NONE"}:
            raise ValueError("Complete decisions must target SYNTHESIS or NONE")

        if self.mode == "empty":
            self.target = "NONE"
            self.result_mode = "empty"

        if self.mode == "degraded_success":
            if self.target not in {"SYNTHESIS", "NONE"}:
                raise ValueError("Degraded success decisions must target SYNTHESIS or NONE")
            self.result_mode = "degraded_success"

        if self.mode in {"clarify", "fail"} and self.target != "NONE":
            raise ValueError("Clarify/fail decisions cannot target a specialist")

        if self.mode == "clarify":
            self.result_mode = "needs_clarification"

        if self.mode == "fail":
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
    delegation_results: List[Dict[str, Any]] = field(default_factory=list)
    latest_delegation_result: Optional[Dict[str, Any]] = None
    step_start_callback: Optional[callable] = None


BASE_SUPERVISOR_PROMPT = """
You are the Tako supervisor and control plane for Okta data requests.

Your job is to decide the next control-plane step. You do not fetch data and you
do not execute SQL, API calls, or generated scripts. Specialists and the runtime
shell own execution and validation.

Decision modes:
- delegate: choose exactly one next specialist target: SQL, API, or SPECIAL.
- complete: enough validated evidence exists; use target SYNTHESIS for normal script answers.
- empty: validated evidence proves there are no matching results and that fully answers the request.
- degraded_success: usable evidence exists, but one or more non-critical gaps remain.
- clarify: the request cannot be routed safely without more user detail.
- fail: the request is unrelated to Okta or outside supported capabilities.

Routing rules:
- Start with SQL when the base entity set can be filtered locally: users, groups,
  apps, memberships, assignments, profile fields, and local status.
- Before choosing SQL, consider the DB runtime summary. If the database is not
    usable for SQL, prefer API unless the request is a strict special-tool match.
- Start with API for system logs, login events, roles, real-time data, device trust,
  or explicit API-only requests.
- Use SPECIAL only for strict matches against the injected special-tool capabilities.
- Treat specialist DelegationResult.needs_specialists as evidence of unresolved gaps,
    not as an automatic route. You own the next routing decision.
- If the latest successful specialist has no unresolved requirements or needed
  specialists, complete with SYNTHESIS.
- Use empty only for validated zero-result outcomes that answer the user's request.
- Use degraded_success only when available evidence can answer partially with clear caveats.
- Reason over summaries, artifact keys, result-set refs, statuses, and tiny samples.
  Do not require full raw payloads in context.
- Keep runtime concerns outside your decision. The runtime shell owns SSE,
  validation, subprocess execution, and transport formatting.
"""


supervisor_agent = build_agent(
    ModelType.CODING,
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

LATEST SPECIALIST RESULT:
{json.dumps(deps.latest_delegation_result or {}, indent=2, default=str)}

ALL SPECIALIST RESULTS SO FAR:
{json.dumps(deps.delegation_results, indent=2, default=str)}

COMPACT ARTIFACT CONTEXT:
{artifact_context}
"""


async def supervise_query(
    user_query: str,
    *,
    correlation_id: str,
    artifacts_file: Optional[Path] = None,
    db_runtime_summary: Optional[Dict[str, Any]] = None,
    special_tool_capabilities: Optional[Dict[str, Any]] = None,
    step_start_callback: Optional[callable] = None,
) -> tuple[SupervisorDecision, Any]:
    """Choose the first specialist or completion mode for a user request."""
    logger.info(f"Running supervisor initial decision for query: {user_query}")
    deps = SupervisorDeps(
        correlation_id=correlation_id,
        phase="initial",
        artifacts_file=artifacts_file,
        db_runtime_summary=db_runtime_summary or {},
        special_tool_capabilities=special_tool_capabilities or {},
        step_start_callback=step_start_callback,
    )
    try:
        run_result = await supervisor_agent.run(
            f"Decide the first step for this Okta request: {user_query}",
            deps=deps,
            usage_limits=SUPERVISOR_USAGE_LIMITS,
        )
        decision = run_result.output
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
    step_start_callback: Optional[callable] = None,
) -> tuple[SupervisorDecision, Any]:
    """Choose the next step after a specialist returns a DelegationResult."""
    latest = latest_delegation_result.model_dump()
    deps = SupervisorDeps(
        correlation_id=correlation_id,
        phase="after_delegation",
        artifacts_file=artifacts_file,
        db_runtime_summary=db_runtime_summary or {},
        special_tool_capabilities=special_tool_capabilities or {},
        delegation_results=delegation_results,
        latest_delegation_result=latest,
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
    if latest_delegation_result.needs_specialists and decision.mode == "complete":
        target = _specialist_to_target(latest_delegation_result.needs_specialists[0])
        if target:
            return SupervisorDecision(
                mode="delegate",
                target=target,
                reasoning=(
                    "Latest specialist reported unresolved requirements, so runtime safety "
                    f"prevents early completion and delegates to {target}."
                ),
                requested_data=latest_delegation_result.unresolved_requirements,
            )

    if latest_delegation_result.success and not latest_delegation_result.needs_specialists:
        if latest_delegation_result.result_mode == "empty" and decision.mode == "delegate":
            return SupervisorDecision(
                mode="empty",
                target="NONE",
                result_mode="empty",
                reasoning="Latest specialist returned a validated empty result with no further specialist needs.",
                evidence_artifact_keys=latest_delegation_result.artifact_keys,
                evidence_result_set_refs=latest_delegation_result.result_set_refs,
            )

        if decision.mode == "delegate" and decision.target in {"SQL", "API"}:
            return SupervisorDecision(
                mode="complete",
                target="SYNTHESIS",
                result_mode="synthesis_ready",
                reasoning="Latest specialist produced sufficient evidence with no further specialist needs.",
                evidence_artifact_keys=latest_delegation_result.artifact_keys,
                evidence_result_set_refs=latest_delegation_result.result_set_refs,
            )

    return decision


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
        "synthesis": "SYNTHESIS",
    }
    return mapping.get(str(specialist).lower())


__all__ = [
    "SupervisorDecision",
    "SupervisorDeps",
    "supervise_next_step",
    "supervise_query",
]