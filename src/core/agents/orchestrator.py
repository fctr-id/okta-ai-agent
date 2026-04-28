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
from typing import Optional, Dict, Any, List
import asyncio
import time
import json
import os

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


def _load_artifacts_by_category(artifacts_file: Path, category: str) -> Optional[str]:
    """Load compact artifact context for a category without full payloads."""
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
        context = build_artifact_prompt_context(artifacts_file, categories=[category])
        return context if context != "[]" else None
    except Exception as error:
        logger.warning(f"Failed to load {category} artifacts: {error}")
        return None


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

    if decision.mode == "complete":
        result.error = decision.user_message or "Supervisor completed before any data specialist ran"
        _set_result_outcome(
            result,
            "fail",
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

    if decision.mode == "degraded_success":
        result.error = decision.user_message or "Supervisor reported degraded success before any data specialist ran"
        _set_result_outcome(
            result,
            "fail",
            reason=decision.reasoning,
            user_message=result.error,
        )
        return True

    return False


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


def _discovery_degraded_reasons(
    result: OrchestratorResult,
    processor_delegation: Optional[DelegationResult],
) -> List[str]:
    has_success = bool(
        (result.sql_result and result.sql_result.success)
        or (result.api_result and result.api_result.success)
        or (processor_delegation and processor_delegation.success)
    )
    if not has_success:
        return []

    reasons: List[str] = []
    if result.sql_result and not result.sql_result.success:
        reasons.append(f"SQL: {result.sql_result.error or result.sql_result.reasoning or 'failed'}")
    if result.api_result and not result.api_result.success:
        reasons.append(f"API: {result.api_result.error or result.api_result.reasoning or 'failed'}")
    if processor_delegation and not processor_delegation.success:
        reasons.append(f"PROCESSOR: {processor_delegation.error or processor_delegation.summary}")
    return reasons


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


def _delegation_requirements(delegation: DelegationResult, fallback: str) -> List[str]:
    """Return neutral unresolved requirements for the next specialist run."""
    return list(delegation.unresolved_requirements or [fallback])


def _delegation_evidence(delegation: Optional[DelegationResult], fallback: Optional[List[str]]) -> List[str]:
    """Return neutral evidence labels, preserving legacy specialist compatibility."""
    if delegation and delegation.evidence_found:
        return list(delegation.evidence_found)
    return list(fallback or [])


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


def _processor_requirements(delegation: DelegationResult) -> List[str]:
    return list(delegation.result_set_refs or delegation.artifact_keys or ["processor"])


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
    needs_api = list(sql_result.needs_api or [])
    found_data = list(sql_result.found_data or [])
    if sql_result.success and not needs_api and not found_data and not artifact_keys and not result_set_refs:
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
) -> Dict[str, Any]:
    context = {
        "sql_reasoning": None,
        "sql_discovered_data": None,
        "sql_needs_api": None,
        "sql_found_data": None,
    }

    if result.sql_result and result.sql_result.success:
        context["sql_reasoning"] = result.sql_result.reasoning
        context["sql_needs_api"] = (
            _delegation_requirements(latest_sql_delegation, "api")
            if latest_sql_delegation
            else result.sql_result.needs_api
        )
        context["sql_found_data"] = _delegation_evidence(latest_sql_delegation, result.sql_result.found_data)
        context["sql_discovered_data"] = _load_artifacts_by_category(artifacts_file, "sql_results")
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
) -> Dict[str, Any]:
    api_found_data = _delegation_evidence(
        latest_api_delegation,
        result.api_result.found_data if result.api_result else [],
    )
    if result.api_result and result.api_result.success and result.api_result.reasoning:
        api_reasoning = result.api_result.reasoning
    else:
        api_reasoning = f"API agent needs base entities: {', '.join(pending_sql_request)}"

    api_discovered_data = _load_artifacts_by_category(artifacts_file, "api_results")
    if api_discovered_data:
        logger.info(f"Passing API discovered data to SQL agent ({len(api_discovered_data)} chars)")

    return {
        "api_reasoning": api_reasoning,
        "api_discovered_data": api_discovered_data,
        "api_needs_sql": pending_sql_request,
        "api_found_data": api_found_data,
    }


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
            'synthesis': 10  # Steps 11-12
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
        
        if _apply_initial_terminal_decision(result, result.initial_supervisor_decision):
            return result
        
        if phase == "SPECIAL":
            # Execute special tools
            logger.info(f"Executing special tool handler")
            result.phases_executed.append('special')
            
            # Send initial status to frontend
            await aggregator.step_start({
                "title": "Special Tool",
                "text": "Using specialized tool to fetch your answer. Please wait...",
                "timestamp": time.time()
            })
            
            special_result = await handle_special_query(
                user_query=user_query,
                okta_client=okta_client,
                correlation_id=correlation_id,
                progress_callback=aggregator.progress
            )

            result.special_tool_data = special_result.raw_result
            result.special_tool_operation = special_result.tool_operation
            result.special_tool_response_mode = special_result.response_mode
            if special_result.delegation_result:
                result.delegation_results.append(special_result.delegation_result.model_dump())

            if special_result.success:
                # Special tools return pre-formatted results
                result.success = True
                result.script_code = special_result.response_text
                result.display_type = special_result.display_type or "markdown"
                result.is_special_tool = True  # Flag to skip validation
                special_mode = special_result.delegation_result.result_mode if special_result.delegation_result else "direct_answer"
                _set_result_outcome(
                    result,
                    "direct_answer" if special_mode == "direct_answer" else "success",
                    result_mode=special_mode,
                    reason="Special tool returned a direct response.",
                    user_message=special_result.response_text,
                )
                logger.info(f"Special tool execution successful")
            else:
                result.error = special_result.error or "Special tool execution failed"
                _set_result_outcome(
                    result,
                    "fail",
                    reason="Special tool execution failed.",
                    user_message=result.error,
                )
                logger.error(f"Special tool failed: {result.error}")
            
            return result
        
        async def supervisor_next_target(latest_delegation: DelegationResult) -> Optional[str]:
            """Ask the supervisor whether to continue with SQL/API or finish."""
            supervisor_decision, supervisor_usage = await supervise_next_step(
                user_query,
                correlation_id=correlation_id,
                artifacts_file=artifacts_file,
                delegation_results=result.delegation_results,
                latest_delegation_result=latest_delegation,
                db_runtime_summary=db_runtime_summary,
                special_tool_capabilities=special_tool_capabilities,
                step_start_callback=aggregator.step_start,
            )
            result.supervisor_decisions.append(supervisor_decision.model_dump())
            _add_usage_to_result(result, supervisor_usage)

            return _apply_followup_supervisor_decision(result, supervisor_decision)
        
        # ====================================================================
        # PHASE 1: SQL Discovery (if Supervisor → SQL AND DB is healthy)
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
        
        # ====================================================================
        # PHASE 2 & 2.5: Multi-Step Discovery Loop (API ↔ SQL)
        # ====================================================================
        # Allow up to 6 phase executions (e.g., API→SQL→API→SQL→API→SQL)
        # Each SQL or API execution counts as one iteration
        max_iterations = 6
        iteration_count = 0
        
        # Track unresolved requirements per iteration (cleared after acting on them).
        pending_api_request = None
        pending_sql_request = None
        pending_processor_source: Optional[DelegationResult] = None
        latest_sql_delegation: Optional[DelegationResult] = None
        latest_api_delegation: Optional[DelegationResult] = None
        latest_processor_delegation: Optional[DelegationResult] = None
        seen_requirement_steps: set[tuple[str, tuple[str, ...]]] = set()
        
        # Let the supervisor decide whether the initial SQL result needs another specialist.
        if result.sql_result:
            latest_sql_delegation = _sql_delegation_result(result.sql_result, artifacts_file, initial_sql_usage)
            result.delegation_results.append(latest_sql_delegation.model_dump())
            next_target = await supervisor_next_target(latest_sql_delegation)
            if next_target == "API":
                candidate_request = _delegation_requirements(latest_sql_delegation, "api")
                if not _record_requirement_step(seen_requirement_steps, "api", candidate_request):
                    logger.warning(f"Stopping repeated API requirement loop: {candidate_request}")
                    return result
                pending_api_request = candidate_request
                logger.info(f"Supervisor delegates from SQL to API: {pending_api_request}")
            elif next_target == "SQL":
                candidate_request = _delegation_requirements(latest_sql_delegation, "sql")
                if not _record_requirement_step(seen_requirement_steps, "sql", candidate_request):
                    logger.warning(f"Stopping repeated SQL requirement loop: {candidate_request}")
                    return result
                pending_sql_request = candidate_request
                logger.info(f"Supervisor delegates from SQL back to SQL: {pending_sql_request}")
            elif next_target == "PROCESSOR":
                candidate_request = _processor_requirements(latest_sql_delegation)
                if not _record_requirement_step(seen_requirement_steps, "processor", candidate_request):
                    logger.warning(f"Stopping repeated processor requirement loop: {candidate_request}")
                    return result
                pending_processor_source = latest_sql_delegation
                logger.info(f"Supervisor delegates from SQL to result-set processor: {candidate_request}")
            elif next_target == "STOP":
                return result
        
        logger.info(f"Starting multi-step discovery loop (max {max_iterations} phases)")
        
        while iteration_count < max_iterations:
            # Check if we need to run API phase
            should_run_api = (
                phase == "API"  # Supervisor decided API (first iteration only)
                or pending_api_request is not None  # SQL requested API in previous iteration
            )
            
            # Check if we need to run SQL phase
            should_run_sql = (
                pending_sql_request is not None  # API requested SQL in previous iteration
            )

            should_run_processor = (
                phase == "PROCESSOR"
                or pending_processor_source is not None
            )
            
            # Exit loop if no more phases needed
            if not should_run_api and not should_run_sql and not should_run_processor:
                logger.info(f"Discovery loop complete: No more phases needed (iterations: {iteration_count})")
                break
            
            # Clear pending requests before this iteration
            processor_source = pending_processor_source
            pending_api_request = None
            pending_sql_request = None
            pending_processor_source = None

            # ================================================================
            # Run Result-Set Processor (if needed)
            # ================================================================
            if should_run_processor:
                iteration_count += 1
                source_delegation = processor_source or latest_api_delegation or latest_sql_delegation
                logger.info(f"Running Result-Set Processor (iteration {iteration_count}/{max_iterations})")
                aggregator.set_phase('processor')
                result.phases_executed.append('processor')

                await aggregator.step_start({
                    "title": "Result Processing",
                    "text": "Processing saved result-set references",
                    "timestamp": time.time()
                })

                latest_processor_delegation = _processor_delegation_result(
                    user_query,
                    artifacts_file,
                    source_delegation,
                )
                result.delegation_results.append(latest_processor_delegation.model_dump())
                next_target = await supervisor_next_target(latest_processor_delegation)

                if phase == "PROCESSOR":
                    phase = None

                if next_target == "SQL":
                    candidate_request = _delegation_requirements(latest_processor_delegation, "sql")
                    if not _record_requirement_step(seen_requirement_steps, "sql", candidate_request):
                        logger.warning(f"Stopping repeated SQL requirement loop: {candidate_request}")
                        break
                    pending_sql_request = candidate_request
                    logger.info(f"Supervisor delegates from processor to SQL: {pending_sql_request}")
                elif next_target == "API":
                    candidate_request = _delegation_requirements(latest_processor_delegation, "api")
                    if not _record_requirement_step(seen_requirement_steps, "api", candidate_request):
                        logger.warning(f"Stopping repeated API requirement loop: {candidate_request}")
                        break
                    pending_api_request = candidate_request
                    logger.info(f"Supervisor delegates from processor to API: {pending_api_request}")
                elif next_target == "PROCESSOR":
                    candidate_request = _processor_requirements(latest_processor_delegation)
                    if not _record_requirement_step(seen_requirement_steps, "processor", candidate_request):
                        logger.warning(f"Stopping repeated processor requirement loop: {candidate_request}")
                        break
                    pending_processor_source = latest_processor_delegation
                    logger.info(f"Supervisor delegates from processor back to processor: {candidate_request}")
                elif next_target == "STOP":
                    return result

                await aggregator.step_end({
                    "title": "Result Processing Complete",
                    "text": latest_processor_delegation.summary,
                    "timestamp": time.time()
                })
            
            # ================================================================
            # Run API Discovery (if needed)
            # ================================================================
            if should_run_api:
                iteration_count += 1
                logger.info(f"Running API Discovery Agent (iteration {iteration_count}/{max_iterations})")
                aggregator.set_phase('api')
                result.phases_executed.append('api')
                sql_context = _sql_context_for_api(result, latest_sql_delegation, artifacts_file)
                
                # Send STEP-START for API Discovery phase
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
                    okta_client=okta_client,
                    cancellation_check=cancellation_check,
                    step_start_callback=aggregator.step_start,
                    step_end_callback=aggregator.step_end,
                    tool_call_callback=aggregator.tool_call,
                    progress_callback=aggregator.progress,
                    # Tool call limits (continue from SQL phase)
                    global_tool_calls=global_tool_calls_counter,
                    max_global_tool_calls=max_tool_calls
                )
                
                result.api_result, api_usage = await execute_api_discovery(user_query, api_deps)
                
                # Update global counter after API phase
                global_tool_calls_counter = api_deps.global_tool_calls
                logger.info(f"Tool calls after API: {global_tool_calls_counter}/{max_tool_calls}")
                
                _add_usage_to_result(result, api_usage)
                latest_api_delegation = _api_delegation_result(result.api_result, artifacts_file, api_usage)
                
                # Check for API limit errors and stop execution
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
                        return result
                    
                    # Check if it's a hard limit error
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
                        return result
                    
                    if latest_api_delegation.unresolved_requirements:
                        logger.info(f"API has unresolved requirements for SQL: {latest_api_delegation.unresolved_requirements}")
                    else:
                        logger.info(f"Exiting discovery loop due to API error (no unresolved requirements)")
                        break
                
                # Reset phase flag after first iteration
                if phase == "API":
                    phase = None
                
                result.delegation_results.append(latest_api_delegation.model_dump())
                next_target = await supervisor_next_target(latest_api_delegation)
                if next_target == "SQL":
                    candidate_request = _delegation_requirements(latest_api_delegation, "sql")
                    if not _record_requirement_step(seen_requirement_steps, "sql", candidate_request):
                        logger.warning(f"Stopping repeated SQL requirement loop: {candidate_request}")
                        break
                    pending_sql_request = candidate_request
                    logger.info(f"Supervisor delegates from API to SQL: {pending_sql_request}")
                elif next_target == "API":
                    candidate_request = _delegation_requirements(latest_api_delegation, "api")
                    if not _record_requirement_step(seen_requirement_steps, "api", candidate_request):
                        logger.warning(f"Stopping repeated API requirement loop: {candidate_request}")
                        break
                    pending_api_request = candidate_request
                    logger.info(f"Supervisor delegates from API back to API: {pending_api_request}")
                elif next_target == "PROCESSOR":
                    candidate_request = _processor_requirements(latest_api_delegation)
                    if not _record_requirement_step(seen_requirement_steps, "processor", candidate_request):
                        logger.warning(f"Stopping repeated processor requirement loop: {candidate_request}")
                        break
                    pending_processor_source = latest_api_delegation
                    logger.info(f"Supervisor delegates from API to result-set processor: {candidate_request}")
                elif next_target == "STOP":
                    return result
            
            # ================================================================
            # Run SQL Discovery (if pending request exists)
            # ================================================================
            if pending_sql_request is not None:
                iteration_count += 1
                logger.info(f"API agent requests SQL data: {pending_sql_request}")
                logger.info(f"Running SQL Discovery Agent (iteration {iteration_count}/{max_iterations})")
                
                # Reuse the initial runtime DB summary for supervisor-consistent safety checks.
                db_healthy = bool(db_runtime_summary.get("usable_for_sql"))
                if not db_healthy:
                    logger.warning(f"API needs SQL but DB is unavailable - exiting discovery loop")
                    break
                
                aggregator.set_phase('sql')
                result.phases_executed.append('sql')
                
                await aggregator.step_start({
                    "title": "SQL Discovery",
                    "text": f"Fetching base entities from database: {', '.join(pending_sql_request)}",
                    "timestamp": time.time()
                })
                
                api_context = _api_context_for_sql(result, latest_api_delegation, pending_sql_request, artifacts_file)
                
                sql_deps = SQLDiscoveryDeps(
                    correlation_id=correlation_id,
                    artifacts_file=artifacts_file,
                    okta_client=okta_client,
                    cancellation_check=cancellation_check,
                    api_reasoning=api_context["api_reasoning"],
                    api_discovered_data=api_context["api_discovered_data"],
                    api_needs_sql=api_context["api_needs_sql"],
                    api_found_data=api_context["api_found_data"],
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
                latest_sql_delegation = _sql_delegation_result(result.sql_result, artifacts_file, sql_usage)
                
                # Check for SQL limit errors
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
                        return result
                    if latest_sql_delegation.unresolved_requirements:
                        logger.info(f"SQL has unresolved requirements for API: {latest_sql_delegation.unresolved_requirements}")
                    else:
                        logger.info(f"Exiting discovery loop due to SQL error (no unresolved requirements)")
                        break
                
                result.delegation_results.append(latest_sql_delegation.model_dump())
                next_target = await supervisor_next_target(latest_sql_delegation)
                if next_target == "API":
                    candidate_request = _delegation_requirements(latest_sql_delegation, "api")
                    if not _record_requirement_step(seen_requirement_steps, "api", candidate_request):
                        logger.warning(f"Stopping repeated API requirement loop: {candidate_request}")
                        break
                    pending_api_request = candidate_request
                    logger.info(f"Supervisor delegates from SQL to API: {pending_api_request}")
                elif next_target == "SQL":
                    candidate_request = _delegation_requirements(latest_sql_delegation, "sql")
                    if not _record_requirement_step(seen_requirement_steps, "sql", candidate_request):
                        logger.warning(f"Stopping repeated SQL requirement loop: {candidate_request}")
                        break
                    pending_sql_request = candidate_request
                    logger.info(f"Supervisor delegates from SQL back to SQL: {pending_sql_request}")
                elif next_target == "PROCESSOR":
                    candidate_request = _processor_requirements(latest_sql_delegation)
                    if not _record_requirement_step(seen_requirement_steps, "processor", candidate_request):
                        logger.warning(f"Stopping repeated processor requirement loop: {candidate_request}")
                        break
                    pending_processor_source = latest_sql_delegation
                    logger.info(f"Supervisor delegates from SQL to result-set processor: {candidate_request}")
                elif next_target == "STOP":
                    return result
                
                await aggregator.step_end({
                    "title": "SQL Discovery Complete",
                    "text": f"SQL data retrieved: {result.sql_result.success}",
                    "timestamp": time.time()
                })
        
        # Check if we hit max iterations
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
        
        # ====================================================================
        # Validate Discovery Results Before Synthesis
        # ====================================================================
        # Check if any discovery phase actually succeeded
        sql_succeeded = result.sql_result and result.sql_result.success
        api_succeeded = result.api_result and result.api_result.success
        processor_succeeded = latest_processor_delegation and latest_processor_delegation.success
        
        if not sql_succeeded and not api_succeeded and not processor_succeeded:
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
                return result

            # Both phases failed or didn't run - cannot proceed
            error_details = []
            if result.sql_result and not result.sql_result.success:
                error_details.append(f"SQL: {result.sql_result.error}")
            if result.api_result and not result.api_result.success:
                error_details.append(f"API: {result.api_result.error}")
            
            error_msg = "Discovery failed - no data retrieved. " + " | ".join(error_details) if error_details else "No discovery phases succeeded"
            logger.error(f"{error_msg}")
            
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
            return result
        
        logger.info(f"Discovery validation passed (SQL: {sql_succeeded}, API: {api_succeeded})")
        
        # Check if discovery succeeded but found no data (0 artifacts)
        try:
            artifacts = load_artifacts_file(artifacts_file)
            artifact_count = len(artifacts) if isinstance(artifacts, list) else 0
            
            if artifact_count == 0:
                logger.info(f"Discovery succeeded but found no data (0 artifacts)")
                result.success = True
                _set_result_outcome(
                    result,
                    "empty",
                    reason="Discovery completed with zero artifacts.",
                    user_message="No matching data was found for this request.",
                )
                return result
        except Exception as e:
            logger.warning(f"Failed to check artifact count: {e}")
            # Continue to synthesis anyway
        
        # ====================================================================
        # PHASE 3: Synthesis
        # ====================================================================
        logger.info(f"Running Synthesis Agent")
        aggregator.set_phase('synthesis')
        
        # Notify user synthesis is starting
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
            return result
        
        # ====================================================================
        # SUCCESS: Return Script
        # ====================================================================
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
        
        # Determine data source type based on which agents ran successfully
        sql_succeeded = result.sql_result and result.sql_result.success
        api_succeeded = result.api_result and result.api_result.success
        
        if sql_succeeded and api_succeeded:
            result.data_source_type = "hybrid"
        elif sql_succeeded:
            result.data_source_type = "sql"
        elif api_succeeded:
            result.data_source_type = "api"
        elif processor_succeeded:
            result.data_source_type = "processor"
        
        # Get last sync timestamp if SQL was used
        if result.data_source_type in ["sql", "hybrid"]:
            result.last_sync_time = get_last_sync_timestamp()
        
        logger.info(f"Multi-agent workflow complete")
        logger.info(f"Phases executed: {', '.join(result.phases_executed)}")
        logger.info(f"Data source: {result.data_source_type}")
        logger.info(f"Outcome: {result.outcome} ({result.result_mode})")
        
        # Log cumulative token usage
        if result.total_tokens > 0:
            avg_per_call = result.total_input_tokens / result.total_requests if result.total_requests > 0 else 0
            logger.info(
                f"[{correlation_id}] TOTAL Token Usage: "
                f"{result.total_input_tokens:,} input, {result.total_output_tokens:,} output, "
                f"{result.total_tokens:,} total (across {result.total_requests} API calls, "
                f"avg {avg_per_call:,.0f} input/call)"
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
