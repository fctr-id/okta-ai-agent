"""Deterministic Phase 2E outcome validation.

Run from the repository root with:
    python src/core/data/testing/validate_phase2e_outcomes.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.agents.api_discovery_agent import APIDiscoveryResult
from src.core.agents.orchestrator import (
    OrchestratorResult,
    _api_context_for_sql,
    _api_delegation_result,
    _apply_followup_supervisor_decision,
    _apply_initial_terminal_decision,
    _build_workflow_state,
    _delegation_requirements,
    _discovery_degraded_reasons,
    _has_successful_delegation,
    _next_target_transition,
    _record_requirement_step,
    _run_initial_sql_discovery,
    _set_result_outcome,
    _should_run_initial_synthesis_direct,
    _sql_context_for_api,
    _sql_delegation_result,
    _validate_discovery_before_synthesis,
)
from src.core.agents.special_tools_handler import (
    SpecialToolResult,
    _deterministic_special_tool_fallback,
    _resolve_special_tool_response_text,
    _resolve_special_tool_summary,
    build_special_tool_delegation_result,
)
from src.core.agents.sql_discovery_agent import SQLDiscoveryResult
from src.core.agents.supervisor_agent import (
    SupervisorDecision,
    _build_followup_workflow_state,
    _is_referential_followup_query,
    _normalize_initial_decision,
    _normalize_after_delegation_decision,
)
from src.data.schemas.artifact_manifest import (
    DelegationResult,
    append_artifacts_to_file,
    append_artifacts_with_result_sets,
)


_TEMP_DIRS: list[TemporaryDirectory[str]] = []


class _DummyAggregator:
    def __init__(self) -> None:
        self.phase = None
        self.events: list[tuple[str, dict]] = []

    def set_phase(self, phase: str) -> None:
        self.phase = phase

    async def step_start(self, event: dict) -> None:
        self.events.append(("step_start", event))

    async def step_end(self, event: dict) -> None:
        self.events.append(("step_end", event))

    async def tool_call(self, event: dict) -> None:
        self.events.append(("tool_call", event))

    async def progress(self, event: dict) -> None:
        self.events.append(("progress", event))


def _artifacts_file() -> Path:
    logs_dir = PROJECT_ROOT / "logs"
    logs_dir.mkdir(exist_ok=True)
    temp_dir = TemporaryDirectory(dir=logs_dir)
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


def test_zero_result_sql_artifact_outcome() -> None:
    artifacts_file = _artifacts_file()
    append_artifacts_with_result_sets(
        artifacts_file,
        [
            {
                "key": "applications_starting_with_x",
                "category": "sql_results",
                "content": "[]",
                "sql_query": 'SELECT okta_id, name FROM applications WHERE name LIKE "x%"',
                "notes": "No matching applications found.",
            }
        ],
        source_specialist="sql",
    )

    sql_result = SQLDiscoveryResult(
        success=True,
        found_data=[],
        needs_api=None,
        reasoning="No matching applications found.",
    )

    delegation = _sql_delegation_result(sql_result, artifacts_file, usage=None)
    normalized = _normalize_after_delegation_decision(
        SupervisorDecision(
            mode="complete",
            target="SYNTHESIS",
            result_mode="synthesis_ready",
            reasoning="Evidence exists.",
        ),
        delegation,
    )

    assert delegation.result_mode == "empty"
    assert delegation.status == "empty"
    assert delegation.artifact_keys == ["applications_starting_with_x"]
    assert len(delegation.result_set_refs) == 1
    assert normalized.mode == "empty"
    assert normalized.result_mode == "empty"


def test_special_tool_flow_outcome() -> None:
    special_result = SpecialToolResult(
        success=True,
        tool_operation="explain_assignment",
        tool_name="assignment_explainer",
        summary_text="Assignment evidence collected for synthesis.",
        response_mode="synthesis_ready",
        artifact_keys=["special_assignment"],
        result_set_refs=["rs_special_assignment"],
    )

    delegation = build_special_tool_delegation_result(special_result)

    assert delegation.success is True
    assert delegation.source_specialist == "special"
    assert delegation.result_mode == "synthesis_ready"
    assert delegation.status == "success"
    assert delegation.direct_answer is None
    assert delegation.summary == "Assignment evidence collected for synthesis."
    assert delegation.artifact_keys == ["special_assignment"]
    assert delegation.result_set_refs == ["rs_special_assignment"]


def test_special_tool_response_text_skips_inline_summary_for_synthesis() -> None:
    tool_result = {
        "status": "success",
        "message": "Collected login evidence.",
        "llm_summary": "## Inline Summary\n\nThis should not be used in synthesis mode.",
    }

    response_text = _resolve_special_tool_response_text(
        tool_result,
        success=True,
        response_mode="synthesis_ready",
    )
    summary_text = _resolve_special_tool_summary(
        "special_tool_analyze_login_risk",
        "login_risk_analysis",
        tool_result,
        success=True,
        response_mode="synthesis_ready",
    )

    assert response_text is None
    assert summary_text == "Collected login evidence."


def test_special_tool_response_text_keeps_inline_summary_for_direct_mode() -> None:
    tool_result = {
        "status": "success",
        "message": "Collected login evidence.",
        "llm_summary": "## Inline Summary\n\nUse this for direct answers.",
    }

    response_text = _resolve_special_tool_response_text(
        tool_result,
        success=True,
        response_mode="direct",
    )

    assert response_text == "## Inline Summary\n\nUse this for direct answers."


def test_special_tool_validation_path() -> None:
    artifacts_file = _artifacts_file()
    append_artifacts_to_file(
        artifacts_file,
        [
            {
                "key": "special_assignment",
                "category": "special_results",
                "content": '{"response_text": "Assignment summary"}',
                "notes": "Assignment summary",
            }
        ],
    )
    orchestrator_result = OrchestratorResult()
    special_delegation = DelegationResult(
        success=True,
        source_specialist="special",
        result_mode="synthesis_ready",
        summary="Assignment summary",
        artifact_keys=["special_assignment"],
    )
    orchestrator_result.delegation_results.append(special_delegation.model_dump())

    validation = asyncio.run(
        _validate_discovery_before_synthesis(
            result=orchestrator_result,
            artifacts_file=artifacts_file,
            latest_processor_delegation=None,
            aggregator=_DummyAggregator(),
        )
    )

    assert validation.should_stop is False
    assert _has_successful_delegation(orchestrator_result, "special") is True


def test_special_tool_followup_can_route_directly_to_synthesis() -> None:
    artifacts_file = _artifacts_file()
    append_artifacts_to_file(
        artifacts_file,
        [
            {
                "key": "special_login_risk",
                "category": "special_results",
                "content": '{"response_text": "Login Risk Analysis: dan@fctr.io", "confidence": "high"}',
                "notes": "Login risk evidence collected for synthesis.",
                "result_set_refs": ["rs_special_login_risk"],
            }
        ],
    )

    special_delegation = build_special_tool_delegation_result(
        SpecialToolResult(
            success=True,
            tool_operation="analyze_login_risk",
            tool_name="login_risk_analyzer",
            summary_text="Login risk evidence collected for synthesis.",
            response_mode="synthesis_ready",
            artifact_keys=["special_login_risk"],
            result_set_refs=["rs_special_login_risk"],
        )
    )

    orchestrator_result = OrchestratorResult()
    orchestrator_result.delegation_results.append(special_delegation.model_dump())

    validation = asyncio.run(
        _validate_discovery_before_synthesis(
            result=orchestrator_result,
            artifacts_file=artifacts_file,
            latest_processor_delegation=None,
            aggregator=_DummyAggregator(),
        )
    )

    followup_decision = SupervisorDecision(
        mode="complete",
        target="SYNTHESIS",
        reasoning="Prior special-tool evidence is sufficient to answer the follow-up.",
        evidence_artifact_keys=["special_login_risk"],
        evidence_result_set_refs=["rs_special_login_risk"],
    )

    handled = _apply_initial_terminal_decision(orchestrator_result, followup_decision)

    assert validation.should_stop is False
    assert _has_successful_delegation(orchestrator_result, "special") is True
    assert _should_run_initial_synthesis_direct(followup_decision) is True
    assert handled is False
    assert orchestrator_result.outcome == "pending"


def test_special_tool_fallback_selection_for_login_risk_query() -> None:
    operation_parameters = {
        "special_tool_analyze_login_risk": ("user_identifier",),
        "special_tool_analyze_user_app_access": ("user_identifier", "group_identifier", "app_identifier"),
    }

    operation, parameters, reason = _deterministic_special_tool_fallback(
        "Analyse riks for the user dan@fctr.io and fecth their enrolled factors using API calls only",
        tuple(operation_parameters.keys()),
        operation_parameters,
    )

    assert operation == "special_tool_analyze_login_risk"
    assert parameters == {"user_identifier": "dan@fctr.io"}
    assert reason is not None


def test_special_tool_fallback_selection_for_access_query() -> None:
    operation_parameters = {
        "special_tool_analyze_login_risk": ("user_identifier",),
        "special_tool_analyze_user_app_access": ("user_identifier", "group_identifier", "app_identifier"),
    }

    operation, parameters, reason = _deterministic_special_tool_fallback(
        "Can user dan@fctr.io access application 'Slack'?",
        tuple(operation_parameters.keys()),
        operation_parameters,
    )

    assert operation == "special_tool_analyze_user_app_access"
    assert parameters == {"user_identifier": "dan@fctr.io", "app_identifier": "Slack"}
    assert reason is not None


def test_special_tool_fallback_stays_out_without_required_params() -> None:
    operation_parameters = {
        "special_tool_analyze_login_risk": ("user_identifier",),
        "special_tool_analyze_user_app_access": ("user_identifier", "group_identifier", "app_identifier"),
    }

    operation, parameters, reason = _deterministic_special_tool_fallback(
        "Analyze something",
        tuple(operation_parameters.keys()),
        operation_parameters,
    )

    assert operation is None
    assert parameters == {}
    assert reason is None


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


def test_generic_followup_reference_heuristic() -> None:
    assert _is_referential_followup_query("fetch their app labels") is True
    assert _is_referential_followup_query("what about group names") is True
    assert _is_referential_followup_query("and role assignments too") is True
    assert _is_referential_followup_query("same devices but include compliance state") is True
    assert _is_referential_followup_query("show all system log events") is False
    assert _is_referential_followup_query("and list all groups") is False
    assert _is_referential_followup_query("now show all applications") is False


def test_followup_workflow_state_prefers_analysis_for_entity_agnostic_followups() -> None:
    workflow_state = _build_followup_workflow_state(
        {"hydrated_session_result_set_count": 2},
        [
            {
                "turn_number": 1,
                "query_text": "List all applications",
                "status": "completed",
                "result_count": 42,
                "completion_mode": "success",
            },
            {
                "turn_number": 2,
                "query_text": "also include profile.login",
                "status": "created",
            },
        ],
        {"trimmed_turn_count": 0},
        "also include profile.login",
    )

    assert workflow_state["is_initial_turn"] is False
    assert workflow_state["previous_turn_had_results"] is True
    assert workflow_state["has_prior_result_context"] is True
    assert workflow_state["referential_followup_query"] is True
    assert workflow_state["prefer_result_analysis_for_followup"] is True


def test_initial_followup_redirects_sql_or_api_to_result_analysis() -> None:
    workflow_state = {
        "prefer_result_analysis_for_followup": True,
        "hydrated_session_result_set_count": 2,
    }
    decision = SupervisorDecision(
        mode="delegate",
        target="SQL",
        reasoning="Fetch fresh data.",
        requested_data=["users"],
    )

    normalized = _normalize_initial_decision(decision, workflow_state)

    assert normalized.mode == "delegate"
    assert normalized.target == "RESULT_ANALYSIS"
    assert normalized.result_mode == "continue"
    assert normalized.requested_data == ["users"]


def test_initial_terminal_decision_helper() -> None:
    empty_result = OrchestratorResult()
    empty_decision = SupervisorDecision(
        mode="empty",
        reasoning="Validated zero results.",
        user_message="No data found.",
    )
    handled_empty = _apply_initial_terminal_decision(empty_result, empty_decision)

    complete_result = OrchestratorResult()
    complete_decision = SupervisorDecision(
        mode="complete",
        target="SYNTHESIS",
        reasoning="Conversation context is sufficient for synthesis.",
    )
    handled_complete = _apply_initial_terminal_decision(complete_result, complete_decision)

    delegate_result = OrchestratorResult()
    delegate_decision = SupervisorDecision(
        mode="delegate",
        target="SQL",
        reasoning="Run SQL first.",
    )
    handled_delegate = _apply_initial_terminal_decision(delegate_result, delegate_decision)

    assert handled_empty is True
    assert empty_result.success is True
    assert empty_result.no_data_found is True
    assert empty_result.outcome == "empty"
    assert handled_complete is False
    assert complete_result.outcome == "pending"
    assert handled_delegate is False
    assert delegate_result.outcome == "pending"


def test_initial_direct_synthesis_decision_helper() -> None:
    complete_decision = SupervisorDecision(
        mode="complete",
        target="SYNTHESIS",
        reasoning="Prior artifacts answer the follow-up.",
    )
    degraded_decision = SupervisorDecision(
        mode="degraded_success",
        target="SYNTHESIS",
        reasoning="Prior artifacts partially answer the follow-up.",
    )
    delegate_decision = SupervisorDecision(
        mode="delegate",
        target="RESULT_ANALYSIS",
        reasoning="Analyze prior result sets first.",
    )
    direct_answer_decision = SupervisorDecision(
        mode="complete",
        target="NONE",
        result_mode="direct_answer",
        reasoning="Answer directly without a synthesis artifact.",
        user_message="Direct answer.",
    )

    assert _should_run_initial_synthesis_direct(complete_decision) is True
    assert _should_run_initial_synthesis_direct(degraded_decision) is True
    assert _should_run_initial_synthesis_direct(delegate_decision) is False
    assert _should_run_initial_synthesis_direct(direct_answer_decision) is False


def test_followup_supervisor_decision_helper() -> None:
    delegate_result = OrchestratorResult()
    delegate_decision = SupervisorDecision(
        mode="delegate",
        target="API",
        reasoning="Fetch enrichment.",
    )
    empty_result = OrchestratorResult()
    empty_decision = SupervisorDecision(
        mode="empty",
        reasoning="Validated no matches.",
    )
    degraded_result = OrchestratorResult()
    degraded_decision = SupervisorDecision(
        mode="degraded_success",
        target="SYNTHESIS",
        reasoning="Usable partial evidence exists.",
    )

    assert _apply_followup_supervisor_decision(delegate_result, delegate_decision) == "API"
    assert delegate_result.outcome == "pending"
    assert _apply_followup_supervisor_decision(empty_result, empty_decision) == "STOP"
    assert empty_result.success is True
    assert empty_result.outcome == "empty"
    assert _apply_followup_supervisor_decision(degraded_result, degraded_decision) is None
    assert degraded_result.is_degraded_success is True


def test_after_delegation_safety_conversions() -> None:
    clarify_delegation = DelegationResult(
        success=False,
        source_specialist="analysis",
        result_mode="needs_clarification",
        summary="Which previous result set should I use?",
        direct_answer="Please pick a previous result set.",
    )
    clarify_decision = _normalize_after_delegation_decision(
        SupervisorDecision(
            mode="complete",
            target="SYNTHESIS",
            reasoning="Try to finish.",
        ),
        clarify_delegation,
    )

    failed_delegation = DelegationResult(
        success=False,
        source_specialist="api",
        result_mode="failed",
        summary="API failed.",
        error="401 Unauthorized",
    )
    failed_decision = _normalize_after_delegation_decision(
        SupervisorDecision(
            mode="complete",
            target="SYNTHESIS",
            reasoning="Try to finish.",
            evidence_artifact_keys=["api_users"],
        ),
        failed_delegation,
    )

    no_evidence_delegation = DelegationResult(
        success=True,
        source_specialist="sql",
        result_mode="synthesis_ready",
        summary="SQL completed but did not persist evidence.",
    )
    no_evidence_decision = _normalize_after_delegation_decision(
        SupervisorDecision(
            mode="complete",
            target="SYNTHESIS",
            reasoning="Try to finish.",
        ),
        no_evidence_delegation,
    )

    empty_with_evidence_delegation = DelegationResult(
        success=True,
        source_specialist="sql",
        result_mode="synthesis_ready",
        summary="Evidence was found.",
        artifact_keys=["sql_users"],
    )
    empty_with_evidence_decision = _normalize_after_delegation_decision(
        SupervisorDecision(
            mode="empty",
            target="NONE",
            reasoning="No data found.",
        ),
        empty_with_evidence_delegation,
    )

    assert clarify_decision.mode == "clarify"
    assert clarify_decision.result_mode == "needs_clarification"
    assert clarify_decision.user_message == "Please pick a previous result set."
    assert failed_decision.mode == "fail"
    assert failed_decision.result_mode == "failed"
    assert failed_decision.user_message == "401 Unauthorized"
    assert no_evidence_decision.mode == "fail"
    assert no_evidence_decision.result_mode == "failed"
    assert empty_with_evidence_decision.mode == "complete"
    assert empty_with_evidence_decision.result_mode == "synthesis_ready"
    assert empty_with_evidence_decision.evidence_artifact_keys == ["sql_users"]


def test_initial_sql_fallback_helper() -> None:
    result = OrchestratorResult()
    phase, tool_calls, usage, should_stop = asyncio.run(
        _run_initial_sql_discovery(
            result=result,
            phase="SQL",
            db_runtime_summary={"usable_for_sql": False},
            user_query="list users",
            correlation_id="phase2e-test",
            artifacts_file=_artifacts_file(),
            okta_client=None,
            cancellation_check=lambda: False,
            aggregator=_DummyAggregator(),
            global_tool_calls_counter=3,
            max_tool_calls=30,
        )
    )

    assert phase == "API"
    assert tool_calls == 3
    assert usage is None
    assert should_stop is False
    assert result.sql_result is None


def test_specialist_context_helpers() -> None:
    artifacts_file = _artifacts_file()

    sql_result = OrchestratorResult()
    sql_result.sql_result = SQLDiscoveryResult(
        success=True,
        found_data=["users"],
        needs_api=["roles"],
        reasoning="Found users in SQL.",
    )
    sql_delegation = _sql_delegation_result(sql_result.sql_result, artifacts_file, usage=None)
    sql_context = _sql_context_for_api(sql_result, sql_delegation, artifacts_file)

    api_result = OrchestratorResult()
    api_result.api_result = APIDiscoveryResult(
        success=True,
        api_data_retrieved=True,
        found_data=["roles"],
        needs_sql=["users"],
        reasoning="Fetched roles from API.",
    )
    api_delegation = _api_delegation_result(api_result.api_result, artifacts_file, usage=None)
    api_context = _api_context_for_sql(api_result, api_delegation, ["users"], artifacts_file)

    assert sql_context["sql_reasoning"] == "Found users in SQL."
    assert sql_context["sql_needs_api"] == ["roles"]
    assert sql_context["sql_found_data"] == ["users"]
    assert sql_context["sql_discovered_data"] is None
    assert api_context["api_reasoning"] == "Fetched roles from API."
    assert api_context["api_needs_sql"] == ["users"]
    assert api_context["api_found_data"] == ["roles"]
    assert api_context["api_discovered_data"] is None


def test_next_target_transition_helper() -> None:
    delegation = DelegationResult(
        success=True,
        source_specialist="sql",
        result_mode="continue",
        summary="Need API enrichment.",
        unresolved_requirements=["roles"],
        result_set_refs=["rs_sql_0001_users"],
    )
    seen_steps: set[tuple[str, tuple[str, ...]]] = set()

    api_transition = _next_target_transition(
        next_target="API",
        source_label="SQL",
        source_delegation=delegation,
        seen_requirement_steps=seen_steps,
    )
    repeated_api_transition = _next_target_transition(
        next_target="API",
        source_label="SQL",
        source_delegation=delegation,
        seen_requirement_steps=seen_steps,
    )
    processor_transition = _next_target_transition(
        next_target="PROCESSOR",
        source_label="SQL",
        source_delegation=delegation,
        seen_requirement_steps=set(),
    )
    special_transition = _next_target_transition(
        next_target="SPECIAL",
        source_label="SQL",
        source_delegation=delegation,
        seen_requirement_steps=set(),
    )
    stop_transition = _next_target_transition(
        next_target="STOP",
        source_label="SQL",
        source_delegation=delegation,
        seen_requirement_steps=set(),
    )

    assert api_transition.pending_api_request == ["roles"]
    assert api_transition.repeated is False
    assert repeated_api_transition.repeated is True
    assert processor_transition.pending_processor_source is delegation
    assert processor_transition.repeated is False
    assert special_transition.pending_special_request is True
    assert special_transition.repeated is False
    analysis_transition = _next_target_transition(
        next_target="RESULT_ANALYSIS",
        source_label="SQL",
        source_delegation=delegation,
        seen_requirement_steps=set(),
    )
    assert analysis_transition.pending_analysis_source is delegation
    assert analysis_transition.repeated is False
    assert stop_transition.should_stop is True


def test_delegation_status_normalization_outputs() -> None:
    direct_answer = DelegationResult(
        success=True,
        source_specialist="special",
        result_mode="direct_answer",
        summary="Inline special-tool answer.",
        direct_answer="Inline answer.",
    )
    clarification = DelegationResult(
        success=False,
        source_specialist="analysis",
        result_mode="needs_clarification",
        summary="Need a result-set choice.",
    )
    degraded = DelegationResult(
        success=True,
        source_specialist="api",
        result_mode="degraded_success",
        summary="Partial evidence is available.",
    )
    continuation = DelegationResult(
        success=True,
        source_specialist="sql",
        result_mode="continue",
        summary="Need API enrichment.",
        needs_specialists=["api"],
    )
    failure = DelegationResult(
        success=False,
        source_specialist="api",
        result_mode="failed",
        summary="API failed.",
    )

    assert direct_answer.status == "success"
    assert clarification.status == "clarify_needed"
    assert degraded.status == "partial"
    assert continuation.status == "partial"
    assert failure.status == "error"


def test_workflow_state_summary_helper() -> None:
    orchestrator_result = OrchestratorResult()
    orchestrator_result.phases_executed = ["sql", "api"]
    successful_delegation = DelegationResult(
        success=True,
        source_specialist="sql",
        result_mode="continue",
        summary="Found users and needs roles.",
        artifact_keys=["sql_users"],
        result_set_refs=["rs_sql_users"],
        unresolved_requirements=["roles"],
        capability_gaps=["roles"],
    )
    failed_delegation = DelegationResult(
        success=False,
        source_specialist="api",
        result_mode="failed",
        summary="Roles endpoint failed.",
        error="Roles endpoint unavailable.",
    )
    orchestrator_result.delegation_results = [
        successful_delegation.model_dump(),
        failed_delegation.model_dump(),
    ]
    seen_steps: set[tuple[str, tuple[str, ...]]] = set()
    _record_requirement_step(seen_steps, "api", ["roles"])

    workflow_state = _build_workflow_state(
        result=orchestrator_result,
        latest_delegation=failed_delegation,
        seen_requirement_steps=seen_steps,
        iteration_count=2,
        max_iterations=6,
        global_tool_calls_counter=7,
        max_tool_calls=30,
    )

    assert workflow_state["completed_steps"] == ["sql", "api"]
    assert workflow_state["latest_specialist"] == "api"
    assert workflow_state["latest_status"] == "error"
    assert workflow_state["evidence_artifact_keys"] == ["sql_users"]
    assert workflow_state["evidence_result_set_refs"] == ["rs_sql_users"]
    assert workflow_state["unresolved_requirements"] == ["roles"]
    assert workflow_state["failed_specialists"] == ["api"]
    assert workflow_state["remaining_hops"] == 4
    assert workflow_state["remaining_tool_calls"] == 23
    assert workflow_state["seen_requirement_signatures"] == ["api:roles"]


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

    reasons = _discovery_degraded_reasons(orchestrator_result, post_processing_delegation=None)

    assert reasons == ["API: Roles endpoint unavailable."]


def main() -> None:
    tests = [
        test_sql_only_outcome,
        test_api_only_outcome,
        test_sql_to_api_outcome,
        test_api_to_sql_outcome,
        test_zero_result_outcome,
        test_zero_result_sql_artifact_outcome,
        test_special_tool_flow_outcome,
        test_special_tool_response_text_skips_inline_summary_for_synthesis,
        test_special_tool_response_text_keeps_inline_summary_for_direct_mode,
        test_special_tool_validation_path,
        test_special_tool_followup_can_route_directly_to_synthesis,
        test_special_tool_fallback_selection_for_login_risk_query,
        test_special_tool_fallback_selection_for_access_query,
        test_special_tool_fallback_stays_out_without_required_params,
        test_clarify_and_failure_decisions,
        test_generic_followup_reference_heuristic,
        test_followup_workflow_state_prefers_analysis_for_entity_agnostic_followups,
        test_initial_followup_redirects_sql_or_api_to_result_analysis,
        test_initial_terminal_decision_helper,
        test_initial_direct_synthesis_decision_helper,
        test_followup_supervisor_decision_helper,
        test_after_delegation_safety_conversions,
        test_initial_sql_fallback_helper,
        test_specialist_context_helpers,
        test_next_target_transition_helper,
        test_delegation_status_normalization_outputs,
        test_workflow_state_summary_helper,
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