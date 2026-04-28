"""Deterministic Phase 2E outcome validation.

Run from the repository root with:
    python src/core/data/testing/validate_phase2e_outcomes.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.agents.api_discovery_agent import APIDiscoveryResult
from src.core.agents.orchestrator import (
    OrchestratorResult,
    _api_delegation_result,
    _delegation_requirements,
    _discovery_degraded_reasons,
    _record_requirement_step,
    _set_result_outcome,
    _sql_delegation_result,
)
from src.core.agents.special_tools_handler import (
    SpecialToolResult,
    build_special_tool_delegation_result,
)
from src.core.agents.sql_discovery_agent import SQLDiscoveryResult
from src.core.agents.supervisor_agent import (
    SupervisorDecision,
    _normalize_after_delegation_decision,
)
from src.data.schemas.artifact_manifest import DelegationResult


_TEMP_DIRS: list[TemporaryDirectory[str]] = []


def _artifacts_file() -> Path:
    temp_dir = TemporaryDirectory()
    _TEMP_DIRS.append(temp_dir)
    return Path(temp_dir.name) / "artifacts.json"


def test_sql_only_outcome() -> None:
    artifacts_file = _artifacts_file()
    sql_result = SQLDiscoveryResult(
        success=True,
        found_data=["users"],
        needs_api=None,
        reasoning="Found users in SQL.",
    )

    delegation = _sql_delegation_result(sql_result, artifacts_file, usage=None)

    assert delegation.success is True
    assert delegation.source_specialist == "sql"
    assert delegation.result_mode == "synthesis_ready"
    assert delegation.status == "success"
    assert delegation.needs_specialists == []


def test_api_only_outcome() -> None:
    artifacts_file = _artifacts_file()
    api_result = APIDiscoveryResult(
        success=True,
        api_data_retrieved=True,
        found_data=["logs"],
        needs_sql=None,
        reasoning="Fetched logs from API.",
    )

    delegation = _api_delegation_result(api_result, artifacts_file, usage=None)

    assert delegation.success is True
    assert delegation.source_specialist == "api"
    assert delegation.result_mode == "synthesis_ready"
    assert delegation.status == "success"
    assert delegation.needs_specialists == []


def test_sql_to_api_outcome() -> None:
    artifacts_file = _artifacts_file()
    sql_result = SQLDiscoveryResult(
        success=True,
        found_data=["users"],
        needs_api=["roles"],
        reasoning="Found users; roles require API.",
    )

    delegation = _sql_delegation_result(sql_result, artifacts_file, usage=None)

    assert delegation.result_mode == "continue"
    assert delegation.status == "partial"
    assert delegation.needs_specialists == ["api"]
    assert _delegation_requirements(delegation, "api") == ["roles"]


def test_api_to_sql_outcome() -> None:
    artifacts_file = _artifacts_file()
    api_result = APIDiscoveryResult(
        success=True,
        api_data_retrieved=True,
        found_data=["roles"],
        needs_sql=["users"],
        reasoning="Roles require user base entities.",
    )

    delegation = _api_delegation_result(api_result, artifacts_file, usage=None)

    assert delegation.result_mode == "continue"
    assert delegation.status == "partial"
    assert delegation.needs_specialists == ["sql"]
    assert _delegation_requirements(delegation, "sql") == ["users"]


def test_zero_result_outcome() -> None:
    artifacts_file = _artifacts_file()
    sql_result = SQLDiscoveryResult(
        success=True,
        found_data=[],
        needs_api=None,
        reasoning="No matching users found.",
    )

    delegation = _sql_delegation_result(sql_result, artifacts_file, usage=None)
    orchestrator_result = OrchestratorResult()
    _set_result_outcome(
        orchestrator_result,
        "empty",
        reason=delegation.summary,
        user_message="No matching data was found for this request.",
    )

    assert delegation.result_mode == "empty"
    assert delegation.status == "empty"
    assert orchestrator_result.success is False
    assert orchestrator_result.no_data_found is True
    assert orchestrator_result.result_mode == "empty"
    assert orchestrator_result.outcome_metadata()["outcome"] == "empty"


def test_special_tool_direct_answer_outcome() -> None:
    special_result = SpecialToolResult(
        success=True,
        tool_operation="explain_assignment",
        tool_name="assignment_explainer",
        response_text="Assignment summary",
        response_mode="direct",
    )

    delegation = build_special_tool_delegation_result(special_result)

    assert delegation.success is True
    assert delegation.source_specialist == "special"
    assert delegation.result_mode == "direct_answer"
    assert delegation.status == "success"
    assert delegation.direct_answer == "Assignment summary"


def test_clarify_and_failure_decisions() -> None:
    clarify_decision = SupervisorDecision(
        mode="clarification",
        target="SQL",
        reasoning="Need an app name.",
    )
    failure_decision = SupervisorDecision(
        mode="error",
        target="API",
        reasoning="Not an Okta request.",
    )

    assert clarify_decision.mode == "clarify"
    assert clarify_decision.target == "NONE"
    assert clarify_decision.result_mode == "needs_clarification"
    assert failure_decision.mode == "fail"
    assert failure_decision.target == "NONE"
    assert failure_decision.result_mode == "failed"


def test_degraded_completion_outcome() -> None:
    latest_delegation = DelegationResult(
        success=True,
        source_specialist="api",
        status="partial",
        result_mode="continue",
        summary="Fetched roles but MFA factors are unavailable.",
        artifact_keys=["api_roles"],
        evidence_found=["roles"],
        capability_gaps=["mfa_factors"],
    )
    decision = SupervisorDecision(
        mode="complete",
        target="SYNTHESIS",
        reasoning="Enough evidence exists.",
        evidence_artifact_keys=["api_roles"],
    )

    normalized = _normalize_after_delegation_decision(decision, latest_delegation)
    orchestrator_result = OrchestratorResult()
    _set_result_outcome(
        orchestrator_result,
        normalized.mode,
        result_mode=normalized.result_mode,
        reason=normalized.reasoning,
    )

    assert normalized.mode == "degraded_success"
    assert normalized.result_mode == "degraded_success"
    assert orchestrator_result.is_degraded_success is True
    assert orchestrator_result.outcome_metadata()["result_mode"] == "degraded_success"


def test_failure_outcome_and_loop_guard() -> None:
    orchestrator_result = OrchestratorResult()
    _set_result_outcome(
        orchestrator_result,
        "fail",
        reason="Discovery failed.",
        user_message="No discovery phases succeeded.",
    )
    seen_steps: set[tuple[str, tuple[str, ...]]] = set()

    assert orchestrator_result.result_mode == "failed"
    assert orchestrator_result.outcome_metadata()["outcome"] == "fail"
    assert _record_requirement_step(seen_steps, "api", ["roles", "users"]) is True
    assert _record_requirement_step(seen_steps, "api", ["users", "roles"]) is False


def test_runtime_degraded_reason_detection() -> None:
    orchestrator_result = OrchestratorResult()
    orchestrator_result.sql_result = SQLDiscoveryResult(
        success=True,
        found_data=["users"],
        reasoning="Found users.",
    )
    orchestrator_result.api_result = APIDiscoveryResult(
        success=False,
        reasoning="API failed.",
        error="Roles endpoint unavailable.",
    )

    reasons = _discovery_degraded_reasons(orchestrator_result, processor_delegation=None)

    assert reasons == ["API: Roles endpoint unavailable."]


def main() -> None:
    tests = [
        test_sql_only_outcome,
        test_api_only_outcome,
        test_sql_to_api_outcome,
        test_api_to_sql_outcome,
        test_zero_result_outcome,
        test_special_tool_direct_answer_outcome,
        test_clarify_and_failure_decisions,
        test_degraded_completion_outcome,
        test_failure_outcome_and_loop_guard,
        test_runtime_degraded_reason_detection,
    ]

    for test in tests:
        test()
        print(f"PASS {test.__name__}")

    print(f"Validated {len(tests)} Phase 2E outcome checks.")


if __name__ == "__main__":
    main()