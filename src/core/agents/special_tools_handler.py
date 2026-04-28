"""Special tools specialist for typed special-tool routing and execution."""

import inspect
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext, UsageLimits

from src.utils.logging import get_logger
from src.core.agents import build_agent
from src.core.tools.special_tools import discover_special_tools, get_special_tool_endpoints
from src.core.models.model_picker import ModelType
from src.data.schemas.artifact_manifest import DelegationResult, append_artifacts_with_result_sets

logger = get_logger("okta_ai_agent")

SPECIAL_TOOL_SELECTION_USAGE_LIMITS = UsageLimits(
    request_limit=2,
)


class SpecialToolSelection(BaseModel):
    """Typed selection output for the special-tools specialist."""
    tool_operation: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    reasoning: str


class SpecialToolResult(BaseModel):
    """Typed execution result for the current special-tool path."""
    success: bool
    tool_operation: Optional[str] = None
    tool_name: Optional[str] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)
    raw_result: Optional[Dict[str, Any]] = None
    summary_text: Optional[str] = None
    response_text: Optional[str] = None
    display_type: Literal["markdown", "table"] = "markdown"
    response_mode: Literal["direct", "synthesis_ready"] = "direct"
    artifact_keys: List[str] = Field(default_factory=list)
    result_set_refs: List[str] = Field(default_factory=list)
    delegation_result: Optional[DelegationResult] = None
    error: Optional[str] = None


@dataclass
class SpecialToolSelectionDeps:
    """Dependencies for the special-tool selection agent."""
    correlation_id: str
    endpoint_descriptions: str
    available_operations: tuple[str, ...]
    operation_parameters: Dict[str, tuple[str, ...]]


SPECIAL_TOOL_SELECTION_INSTRUCTIONS = """You are the Tako special-tools specialist.

Your job is to choose the single best special tool for the user's request and extract the supported parameters.

Rules:
- Choose exactly one tool operation from the available operations.
- Copy identifiers exactly as the user wrote them.
- Only include parameters supported by the selected tool.
- Omit optional parameters when the user did not provide them.
- Do not invent tools, operations, or parameter names.
"""


special_tool_selection_agent = build_agent(
    ModelType.REASONING,
    name="special_tool_selection_agent",
    instructions=SPECIAL_TOOL_SELECTION_INSTRUCTIONS,
    output_type=SpecialToolSelection,
    deps_type=SpecialToolSelectionDeps,
)


@special_tool_selection_agent.instructions
def inject_special_tool_catalog(ctx: RunContext[SpecialToolSelectionDeps]) -> str:
    """Inject the live special-tool catalog for this run."""
    return f"AVAILABLE SPECIAL TOOLS:\n{ctx.deps.endpoint_descriptions}"


@special_tool_selection_agent.output_validator
def validate_special_tool_selection(
    ctx: RunContext[SpecialToolSelectionDeps],
    result: SpecialToolSelection,
) -> SpecialToolSelection:
    """Reject unsupported operations before execution."""
    if result.tool_operation not in ctx.deps.available_operations:
        raise ModelRetry(
            f"Unsupported special tool operation '{result.tool_operation}'. Choose one of: {', '.join(ctx.deps.available_operations)}"
        )

    allowed_parameters = set(ctx.deps.operation_parameters.get(result.tool_operation, ()))
    normalized_parameters = result.parameters or {}

    nested_parameters = normalized_parameters.get("parameters") if isinstance(normalized_parameters, dict) else None
    if isinstance(nested_parameters, str):
        try:
            nested_parameters = json.loads(nested_parameters)
        except json.JSONDecodeError:
            nested_parameters = None

    if isinstance(nested_parameters, dict):
        normalized_parameters = nested_parameters

    if allowed_parameters:
        normalized_parameters = {
            key: value
            for key, value in normalized_parameters.items()
            if key in allowed_parameters
        }

    result.parameters = normalized_parameters
    return result


def build_special_tool_catalog() -> Tuple[str, tuple[str, ...], Dict[str, tuple[str, ...]], Optional[str]]:
    """Build a live catalog of special tools for the selection agent."""
    endpoints = get_special_tool_endpoints()

    if not endpoints:
        return "", (), {}, "No special tools available"

    endpoint_descriptions = []
    available_operations: list[str] = []
    operation_parameters: Dict[str, tuple[str, ...]] = {}
    for endpoint in endpoints:
        available_operations.append(endpoint["operation"])
        operation_parameters[endpoint["operation"]] = tuple(endpoint.get("parameters", {}).keys())
        params_desc = []
        for param_name, param_info in endpoint.get("parameters", {}).items():
            required = "REQUIRED" if param_info.get("required", False) else "OPTIONAL"
            params_desc.append(f"  - {param_name} ({required}): {param_info.get('description', '')}")

        endpoint_descriptions.append(
            f"Operation: {endpoint['operation']}\n"
            f"Description: {endpoint['description']}\n"
            f"Parameters:\n" + "\n".join(params_desc)
        )

    return "\n\n".join(endpoint_descriptions), tuple(sorted(set(available_operations))), operation_parameters, None


def get_special_tool_capability_summary() -> Dict[str, Any]:
    """Return compact special-tool capabilities for supervisor routing."""
    endpoints = get_special_tool_endpoints()
    operations = []
    for endpoint in endpoints:
        required_parameters = []
        optional_parameters = []
        for param_name, param_info in endpoint.get("parameters", {}).items():
            if param_info.get("required", False):
                required_parameters.append(param_name)
            else:
                optional_parameters.append(param_name)

        operations.append({
            "operation": endpoint.get("operation"),
            "description": endpoint.get("description"),
            "required_parameters": required_parameters,
            "optional_parameters": optional_parameters,
        })

    return {
        "available": bool(operations),
        "operations": operations,
    }


def find_special_tool(tool_operation: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Resolve a special-tool operation to the registered module metadata."""
    tools_registry = discover_special_tools()

    for _, tool_data in tools_registry.items():
        metadata = tool_data.get("metadata", {})
        lightweight_ref = metadata.get("lightweight_reference", {})
        for entity_info in lightweight_ref.get("entities", {}).values():
            if tool_operation in entity_info.get("operations", []):
                return tool_data["module_name"], tool_data

    return None, None


def build_special_tool_delegation_result(result: SpecialToolResult) -> DelegationResult:
    """Map the special-tool result into the shared lightweight contract."""
    if result.success:
        return DelegationResult(
            success=True,
            source_specialist="special",
            result_mode="direct_answer" if result.response_mode == "direct" else "synthesis_ready",
            summary=result.summary_text or result.response_text or "Special tool completed successfully.",
            artifact_keys=result.artifact_keys,
            result_set_refs=result.result_set_refs,
            evidence_found=[result.tool_operation] if result.tool_operation else [],
            direct_answer=result.response_text if result.response_mode == "direct" else None,
            metadata={
                "tool_operation": result.tool_operation,
                "tool_name": result.tool_name,
                "parameters": result.parameters,
            },
        )

    return DelegationResult(
        success=False,
        source_specialist="special",
        result_mode="failed",
        summary=result.error or "Special tool failed.",
        capability_gaps=[result.error] if result.error else [],
        error=result.error,
        metadata={
            "tool_operation": result.tool_operation,
            "tool_name": result.tool_name,
            "parameters": result.parameters,
        },
    )


def _special_tool_artifact_key(result: SpecialToolResult) -> str:
    operation = (result.tool_operation or result.tool_name or "special_tool").strip()
    safe_operation = "".join(character if character.isalnum() or character in "_-" else "_" for character in operation)
    return f"special_{safe_operation}_{int(time.time() * 1000)}"


def _persist_special_tool_artifact(result: SpecialToolResult, artifacts_file: Optional[Path]) -> None:
    if not result.success or not artifacts_file:
        return

    artifact_key = _special_tool_artifact_key(result)
    artifact_content = {
        "tool_operation": result.tool_operation,
        "tool_name": result.tool_name,
        "parameters": result.parameters,
        "summary_text": result.summary_text,
        "response_text": result.response_text,
        "display_type": result.display_type,
        "raw_result": result.raw_result,
    }
    saved_artifacts, result_refs = append_artifacts_with_result_sets(
        artifacts_file,
        [
            {
                "key": artifact_key,
                "category": "special_results",
                "content": json.dumps(artifact_content, indent=2, default=str),
                "notes": result.summary_text or result.response_text or f"Special tool {result.tool_operation} completed.",
                "tool_operation": result.tool_operation,
                "tool_name": result.tool_name,
                "summary_text": result.summary_text,
                "response_text": result.response_text,
            }
        ],
        source_specialist="special",
    )
    saved_artifact = saved_artifacts[-1] if saved_artifacts else {}
    result.artifact_keys = [artifact_key]
    result.result_set_refs = list(saved_artifact.get("result_set_refs") or [ref.result_set_id for ref in result_refs])


def _infer_user_identifier_from_query(user_query: str) -> Optional[str]:
    """Infer a user identifier from plain text when the model omits it."""
    email_match = re.search(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", user_query)
    if email_match:
        return email_match.group(1)

    okta_id_match = re.search(r"\b00u[A-Za-z0-9]+\b", user_query)
    if okta_id_match:
        return okta_id_match.group(0)

    return None


def _infer_group_identifier_from_query(user_query: str) -> Optional[str]:
    """Infer a quoted group identifier from the query when available."""
    group_match = re.search(r"group\s+[\"']([^\"']+)[\"']", user_query, flags=re.IGNORECASE)
    if group_match:
        return group_match.group(1).strip()

    return None


def _infer_app_identifier_from_query(user_query: str) -> Optional[str]:
    """Infer a quoted app/application identifier from the query when available."""
    app_match = re.search(r"(?:app|application)\s+[\"']([^\"']+)[\"']", user_query, flags=re.IGNORECASE)
    if app_match:
        return app_match.group(1).strip()

    return None


def _apply_parameter_fallbacks(
    user_query: str,
    tool_operation: str,
    parameters: Optional[Dict[str, Any]],
    operation_parameters: Dict[str, tuple[str, ...]],
) -> Dict[str, Any]:
    """Fill required identifier-style parameters from the query when extraction misses them."""
    normalized_parameters = dict(parameters or {})
    allowed_parameters = set(operation_parameters.get(tool_operation, ()))

    parameter_inferers = {
        "user_identifier": _infer_user_identifier_from_query,
        "group_identifier": _infer_group_identifier_from_query,
        "app_identifier": _infer_app_identifier_from_query,
    }

    for parameter_name, inferer in parameter_inferers.items():
        if parameter_name not in allowed_parameters or normalized_parameters.get(parameter_name):
            continue

        inferred_value = inferer(user_query)
        if inferred_value:
            normalized_parameters[parameter_name] = inferred_value

    return normalized_parameters


def _required_parameters_for_operation(tool_operation: str) -> set[str]:
    """Return the required parameter names for a live special-tool operation."""
    for endpoint in get_special_tool_endpoints():
        if endpoint.get("operation") == tool_operation:
            return {
                name
                for name, info in (endpoint.get("parameters") or {}).items()
                if info.get("required", False)
            }

    return set()


def _deterministic_special_tool_fallback(
    user_query: str,
    available_operations: tuple[str, ...],
    operation_parameters: Dict[str, tuple[str, ...]],
) -> Tuple[Optional[str], Dict[str, Any], Optional[str]]:
    """Choose a special tool only when inferred required parameters make one candidate clearly best."""
    fallback_operation: Optional[str] = None
    fallback_parameters: Dict[str, Any] = {}
    best_specificity: tuple[int, int] = (0, 0)
    matched_candidate_count = 0

    for operation in available_operations:
        inferred_parameters = _apply_parameter_fallbacks(
            user_query,
            operation,
            parameters=None,
            operation_parameters=operation_parameters,
        )
        required_parameters = _required_parameters_for_operation(operation)

        if not required_parameters:
            continue

        if not all(inferred_parameters.get(required_parameter) for required_parameter in required_parameters):
            continue

        inferred_parameter_count = sum(1 for value in inferred_parameters.values() if value)
        specificity = (len(required_parameters), inferred_parameter_count)
        if specificity > best_specificity:
            best_specificity = specificity
            fallback_operation = operation
            fallback_parameters = inferred_parameters
            matched_candidate_count = 1
        elif specificity == best_specificity:
            matched_candidate_count += 1

    if not fallback_operation or best_specificity == (0, 0) or matched_candidate_count != 1:
        return None, {}, None

    reason = (
        f"Deterministic fallback selected '{fallback_operation}' because its required parameters were uniquely inferable from the query."
    )
    return fallback_operation, fallback_parameters, reason


def _non_empty_text(value: Any) -> Optional[str]:
    if isinstance(value, str):
        text = value.strip()
        if text:
            return text
    return None


def _special_tool_label(tool_operation: Optional[str], tool_name: Optional[str]) -> str:
    label = (tool_name or tool_operation or "special tool").replace("_", " ").strip()
    return label or "special tool"


def _supports_response_mode_argument(tool_function: Any) -> bool:
    try:
        return "response_mode" in inspect.signature(tool_function).parameters
    except (TypeError, ValueError):
        return False


def _resolve_special_tool_summary(
    tool_operation: Optional[str],
    tool_name: Optional[str],
    raw_result: Any,
    *,
    success: bool,
    response_mode: Literal["direct", "synthesis_ready"],
) -> str:
    if isinstance(raw_result, dict):
        message = _non_empty_text(raw_result.get("message"))
        if message:
            return message

        summary = _non_empty_text(raw_result.get("summary"))
        if summary:
            return summary

        if not success:
            error_text = _non_empty_text(raw_result.get("error"))
            if error_text:
                return error_text

    label = _special_tool_label(tool_operation, tool_name)
    if success and response_mode == "synthesis_ready":
        return f"{label} collected evidence for synthesis."
    if success:
        return f"{label} completed successfully."
    return f"{label} failed."


def _resolve_special_tool_response_text(
    raw_result: Any,
    *,
    success: bool,
    response_mode: Literal["direct", "synthesis_ready"],
) -> Optional[str]:
    if not isinstance(raw_result, dict):
        return None

    llm_summary = _non_empty_text(raw_result.get("llm_summary"))
    message = _non_empty_text(raw_result.get("message"))

    if response_mode == "direct" or not success:
        return llm_summary or message

    return None


async def extract_tool_parameters(
    user_query: str,
    correlation_id: str
) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[str]]:
    """
    Extract tool operation and parameters from user query using LLM.
    
    Args:
        user_query: User's natural language query
        correlation_id: Request tracking ID
        
    Returns:
        Tuple of (operation_name, parameters_dict, error_message)
    """
    available_operations: tuple[str, ...] = ()
    operation_parameters: Dict[str, tuple[str, ...]] = {}

    try:
        endpoint_descriptions, available_operations, operation_parameters, error = build_special_tool_catalog()
        if error:
            return None, None, error

        deps = SpecialToolSelectionDeps(
            correlation_id=correlation_id,
            endpoint_descriptions=endpoint_descriptions,
            available_operations=available_operations,
            operation_parameters=operation_parameters,
        )

        logger.info("Extracting parameters from query")
        result = await special_tool_selection_agent.run(
            user_query,
            deps=deps,
            usage_limits=SPECIAL_TOOL_SELECTION_USAGE_LIMITS,
        )

        selection = result.output
        selection.parameters = _apply_parameter_fallbacks(
            user_query,
            selection.tool_operation,
            selection.parameters,
            operation_parameters,
        )

        logger.info(f"Extracted tool: {selection.tool_operation}")
        logger.info(f"Extracted parameters: {selection.parameters}")
        logger.info(f"Selection reasoning: {selection.reasoning}")

        return selection.tool_operation, selection.parameters, None
        
    except Exception as e:
        fallback_operation, fallback_parameters, fallback_reason = _deterministic_special_tool_fallback(
            user_query,
            available_operations,
            operation_parameters,
        )
        if fallback_operation:
            logger.warning(
                f"Special-tool extraction failed ({str(e)}). {fallback_reason} Parameters: {fallback_parameters}"
            )
            return fallback_operation, fallback_parameters, None

        error_msg = f"Failed to extract tool parameters: {str(e)}"
        logger.error(f"{error_msg}")
        return None, None, error_msg


async def execute_special_tool(
    tool_operation: str,
    parameters: Dict[str, Any],
    okta_client: Any,
    correlation_id: str,
    progress_callback: Optional[callable] = None,
    response_mode: Literal["direct", "synthesis_ready"] = "synthesis_ready",
) -> SpecialToolResult:
    """
    Execute a special tool with given parameters.
    
    Args:
        tool_operation: Tool operation name (e.g., "special_tool_analyze_user_app_access")
        parameters: Parameters dict for the tool
        okta_client: Okta client instance
        correlation_id: Request tracking ID
        progress_callback: Optional callback for progress updates
        
    Returns:
        Typed special-tool execution result
    """
    try:
        tool_name, tool_info = find_special_tool(tool_operation)

        if not tool_info:
            return SpecialToolResult(
                success=False,
                tool_operation=tool_operation,
                parameters=parameters,
                error=f"Special tool operation '{tool_operation}' not found",
            )

        logger.info(f"Found special tool: {tool_name}")
        
        # Send simple progress with tool name
        if progress_callback:
            await progress_callback({
                "entity": tool_name,
                "current": 1,
                "total": 1,
                "message": f"Running {tool_name.replace('_', ' ')}",
                "timestamp": time.time()
            })
        
        # Get the tool function
        tool_function = tool_info.get("function")
        if not tool_function:
            return SpecialToolResult(
                success=False,
                tool_operation=tool_operation,
                tool_name=tool_name,
                parameters=parameters,
                error="Tool function not available",
            )
        
        # Add okta_client to parameters (special tools expect 'client' parameter)
        execution_params = {
            "client": okta_client,
            **parameters
        }
        if _supports_response_mode_argument(tool_function):
            execution_params["response_mode"] = response_mode
        
        logger.info(f"Executing tool with parameters: {list(parameters.keys())}")
        
        # Execute the tool function
        result = await tool_function(**execution_params)
        if not isinstance(result, dict):
            return SpecialToolResult(
                success=False,
                tool_operation=tool_operation,
                tool_name=tool_name,
                parameters=parameters,
                summary_text=f"{_special_tool_label(tool_operation, tool_name)} returned an unsupported result shape.",
                error="Special tool returned a non-dictionary result",
            )

        success = result.get("status") == "success"
        response_text = _resolve_special_tool_response_text(
            result,
            success=success,
            response_mode=response_mode,
        )
        summary_text = _resolve_special_tool_summary(
            tool_operation,
            tool_name,
            result,
            success=success,
            response_mode=response_mode,
        )
        
        # Check if execution was successful
        if success:
            logger.info(f"Special tool execution successful")
            if response_mode == "direct" and not response_text:
                response_text = json.dumps(result, indent=2, default=str)

            return SpecialToolResult(
                success=True,
                tool_operation=tool_operation,
                tool_name=tool_name,
                parameters=parameters,
                raw_result=result,
                summary_text=summary_text,
                response_text=response_text,
                display_type="markdown",
                response_mode=response_mode,
            )
        else:
            error = result.get("error", "Unknown error")
            logger.error(f"Special tool execution failed: {error}")
            if not response_text:
                response_text = f"## Special Tool Failed\n\n{error}"
            return SpecialToolResult(
                success=False,
                tool_operation=tool_operation,
                tool_name=tool_name,
                parameters=parameters,
                raw_result=result,
                summary_text=summary_text,
                response_text=response_text,
                display_type="markdown",
                response_mode=response_mode,
                error=error,
            )
            
    except Exception as e:
        error_msg = f"Exception during special tool execution: {str(e)}"
        logger.error(f"{error_msg}", exc_info=True)
        return SpecialToolResult(
            success=False,
            tool_operation=tool_operation,
            parameters=parameters,
            error=error_msg,
        )


async def handle_special_query(
    user_query: str,
    okta_client: Any,
    correlation_id: str,
    progress_callback: Optional[callable] = None,
    artifacts_file: Optional[Path] = None,
    response_mode: Literal["direct", "synthesis_ready"] = "synthesis_ready",
) -> SpecialToolResult:
    """
    Main handler for special tool queries.
    
    This is the entry point called by the orchestrator when phase == "SPECIAL".
    
    Args:
        user_query: User's natural language query
        okta_client: Okta client instance
        correlation_id: Request tracking ID
        progress_callback: Optional callback for progress updates
        
    Returns:
        Typed special-tool execution result
    """
    logger.info(f"Handling special tool query")
    
    try:
        # Step 1: Extract tool operation and parameters
        logger.info(f"Extracting parameters from query")
        
        tool_operation, parameters, error = await extract_tool_parameters(
            user_query, 
            correlation_id
        )
        
        if error or not tool_operation:
            special_result = SpecialToolResult(
                success=False,
                error=error or "Failed to identify special tool",
            )
            special_result.delegation_result = build_special_tool_delegation_result(special_result)
            return special_result
        
        # Step 2: Execute the tool
        special_result = await execute_special_tool(
            tool_operation,
            parameters,
            okta_client,
            correlation_id,
            progress_callback,
            response_mode=response_mode,
        )

        if special_result.success:
            logger.info("Returning typed special tool result")
            _persist_special_tool_artifact(special_result, artifacts_file)
        else:
            logger.error(f"Special tool execution failed: {special_result.error}")

        special_result.delegation_result = build_special_tool_delegation_result(special_result)

        return special_result
            
    except Exception as e:
        error_msg = f"Exception in special tools handler: {str(e)}"
        logger.error(f"{error_msg}", exc_info=True)
        special_result = SpecialToolResult(
            success=False,
            error=error_msg,
        )
        special_result.delegation_result = build_special_tool_delegation_result(special_result)
        return special_result
