"""Special tools specialist for typed special-tool routing and execution."""

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional, Tuple

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext, UsageLimits

from src.utils.logging import get_logger
from src.core.agents import build_agent
from src.core.tools.special_tools import discover_special_tools, get_special_tool_endpoints
from src.core.models.model_picker import ModelType
from src.data.schemas.artifact_manifest import DelegationResult

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
    response_text: Optional[str] = None
    display_type: Literal["markdown", "table"] = "markdown"
    response_mode: Literal["direct", "synthesis_ready"] = "direct"
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
            summary=result.response_text or "Special tool completed successfully.",
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
        error=result.error,
        metadata={
            "tool_operation": result.tool_operation,
            "tool_name": result.tool_name,
            "parameters": result.parameters,
        },
    )


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
        logger.info(f"Extracted tool: {selection.tool_operation}")
        logger.info(f"Extracted parameters: {selection.parameters}")
        logger.info(f"Selection reasoning: {selection.reasoning}")

        return selection.tool_operation, selection.parameters, None
        
    except Exception as e:
        error_msg = f"Failed to extract tool parameters: {str(e)}"
        logger.error(f"{error_msg}")
        return None, None, error_msg


async def execute_special_tool(
    tool_operation: str,
    parameters: Dict[str, Any],
    okta_client: Any,
    correlation_id: str,
    progress_callback: Optional[callable] = None
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
        
        logger.info(f"Executing tool with parameters: {list(parameters.keys())}")
        
        # Execute the tool function
        result = await tool_function(**execution_params)
        response_text = result.get("llm_summary") if isinstance(result, dict) else None
        
        # Check if execution was successful
        if result.get("status") == "success":
            logger.info(f"Special tool execution successful")
            if not response_text:
                response_text = json.dumps(result, indent=2, default=str)

            return SpecialToolResult(
                success=True,
                tool_operation=tool_operation,
                tool_name=tool_name,
                parameters=parameters,
                raw_result=result,
                response_text=response_text,
                display_type="markdown",
                response_mode="direct",
            )
        else:
            error = result.get("error", "Unknown error")
            logger.error(f"Special tool execution failed: {error}")
            return SpecialToolResult(
                success=False,
                tool_operation=tool_operation,
                tool_name=tool_name,
                parameters=parameters,
                raw_result=result,
                response_text=response_text,
                display_type="markdown",
                response_mode="direct",
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
    progress_callback: Optional[callable] = None
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
            progress_callback
        )

        if special_result.success:
            logger.info("Returning typed special tool result")
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
