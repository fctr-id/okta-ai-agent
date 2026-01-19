"""
Special Tools Handler - Lightweight execution of special tools

Minimal handler that:
1. Discovers available special tools
2. Extracts parameters using LLM
3. Executes the matched tool
4. Returns results

Designed to scale automatically as new special tools are added.
"""

import json
from typing import Dict, Any, Optional, Tuple
from pathlib import Path
from pydantic_ai import Agent
from pydantic import BaseModel

from src.utils.logging import get_logger
from src.core.tools.special_tools import discover_special_tools, get_special_tool_endpoints
from src.core.models.model_picker import ModelConfig, ModelType

logger = get_logger("okta_ai_agent")


class ToolParametersExtraction(BaseModel):
    """Extracted parameters for special tool execution"""
    tool_operation: str
    parameters: Dict[str, Any]
    reasoning: str


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
        # Get available special tool endpoints
        endpoints = get_special_tool_endpoints()
        
        if not endpoints:
            return None, None, "No special tools available"
        
        # Build endpoint descriptions for LLM
        endpoint_descriptions = []
        for endpoint in endpoints:
            params_desc = []
            for param_name, param_info in endpoint.get("parameters", {}).items():
                required = "REQUIRED" if param_info.get("required", False) else "OPTIONAL"
                params_desc.append(f"  - {param_name} ({required}): {param_info.get('description', '')}")
            
            endpoint_descriptions.append(
                f"Operation: {endpoint['operation']}\n"
                f"Description: {endpoint['description']}\n"
                f"Parameters:\n" + "\n".join(params_desc)
            )
        
        # Create prompt for parameter extraction
        prompt = f"""You are analyzing a user query to determine which special tool to use and extract its parameters.

AVAILABLE SPECIAL TOOLS:
{chr(10).join(endpoint_descriptions)}

USER QUERY: "{user_query}"

TASK:
1. Identify which tool operation matches the user's intent
2. Extract all parameter values from the query (user identifiers, app names, group names, etc.)
3. For identifiers: Use the EXACT text from the query (email addresses, app names as written)

Return a JSON object with:
- tool_operation: The operation name (e.g., "special_tool_analyze_user_app_access")
- parameters: Dict of parameter names to their values extracted from the query
- reasoning: Brief explanation of your choice

Example:
User query: "Can aiden.garcia@fctr.io access the Fctr Portal application?"
Response:
{{
  "tool_operation": "special_tool_analyze_user_app_access",
  "parameters": {{
    "user_identifier": "aiden.garcia@fctr.io",
    "app_identifier": "Fctr Portal"
  }},
  "reasoning": "User asking about access permissions for specific user and app"
}}
"""
        
        # Use fast model for extraction
        model = ModelConfig.get_model(ModelType.REASONING)
        agent = Agent(model, result_type=ToolParametersExtraction)
        
        logger.info(f"[{correlation_id}] Extracting parameters from query")
        result = await agent.run(prompt)
        
        extraction = result.data
        logger.info(f"[{correlation_id}] Extracted tool: {extraction.tool_operation}")
        logger.info(f"[{correlation_id}] Extracted parameters: {extraction.parameters}")
        
        return extraction.tool_operation, extraction.parameters, None
        
    except Exception as e:
        error_msg = f"Failed to extract tool parameters: {str(e)}"
        logger.error(f"[{correlation_id}] {error_msg}")
        return None, None, error_msg


async def execute_special_tool(
    tool_operation: str,
    parameters: Dict[str, Any],
    okta_client: Any,
    correlation_id: str,
    progress_callback: Optional[callable] = None
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    Execute a special tool with given parameters.
    
    Args:
        tool_operation: Tool operation name (e.g., "special_tool_analyze_user_app_access")
        parameters: Parameters dict for the tool
        okta_client: Okta client instance
        correlation_id: Request tracking ID
        progress_callback: Optional callback for progress updates
        
    Returns:
        Tuple of (success, result_data, error_message)
    """
    try:
        # Discover available tools
        tools_registry = discover_special_tools()
        
        # Find the matching tool
        tool_info = None
        for entity_name, tool_data in tools_registry.items():
            metadata = tool_data.get("metadata", {})
            lightweight_ref = metadata.get("lightweight_reference", {})
            
            # Check if this tool handles the requested operation
            for entity_info in lightweight_ref.get("entities", {}).values():
                if tool_operation in entity_info.get("operations", []):
                    tool_info = tool_data
                    break
            
            if tool_info:
                break
        
        if not tool_info:
            return False, None, f"Special tool operation '{tool_operation}' not found"
        
        logger.info(f"[{correlation_id}] Found special tool: {tool_info['module_name']}")
        
        # Send progress update
        if progress_callback:
            await progress_callback({
                "action": f"Executing special tool: {tool_info['module_name']}",
                "reasoning": f"Running comprehensive analysis: {tool_operation}",
                "status": "starting"
            })
        
        # Get the tool function
        tool_function = tool_info.get("function")
        if not tool_function:
            return False, None, "Tool function not available"
        
        # Add okta_client to parameters (special tools expect 'client' parameter)
        execution_params = {
            "client": okta_client,
            **parameters
        }
        
        logger.info(f"[{correlation_id}] Executing tool with parameters: {list(parameters.keys())}")
        
        # Execute the tool function
        result = await tool_function(**execution_params)
        
        # Check if execution was successful
        if result.get("status") == "success":
            logger.info(f"[{correlation_id}] Special tool execution successful")
            
            if progress_callback:
                await progress_callback({
                    "action": "Special tool execution complete",
                    "reasoning": "Analysis complete, preparing results",
                    "status": "completed"
                })
            
            return True, result, None
        else:
            error = result.get("error", "Unknown error")
            logger.error(f"[{correlation_id}] Special tool execution failed: {error}")
            return False, None, error
            
    except Exception as e:
        error_msg = f"Exception during special tool execution: {str(e)}"
        logger.error(f"[{correlation_id}] {error_msg}", exc_info=True)
        return False, None, error_msg


async def handle_special_query(
    user_query: str,
    okta_client: Any,
    correlation_id: str,
    progress_callback: Optional[callable] = None
) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
    """
    Main handler for special tool queries.
    
    This is the entry point called by the orchestrator when phase == "SPECIAL".
    
    Args:
        user_query: User's natural language query
        okta_client: Okta client instance
        correlation_id: Request tracking ID
        progress_callback: Optional callback for progress updates
        
    Returns:
        Tuple of (success, result_text, display_type, error_message)
        - result_text: The formatted result to show to user (typically llm_summary)
        - display_type: "markdown" or "table"
    """
    logger.info(f"[{correlation_id}] Handling special tool query")
    
    try:
        # Step 1: Extract tool operation and parameters
        if progress_callback:
            await progress_callback({
                "action": "Analyzing query",
                "reasoning": "Identifying special tool and extracting parameters",
                "status": "starting"
            })
        
        tool_operation, parameters, error = await extract_tool_parameters(
            user_query, 
            correlation_id
        )
        
        if error or not tool_operation:
            return False, None, None, error or "Failed to identify special tool"
        
        # Step 2: Execute the tool
        success, result_data, error = await execute_special_tool(
            tool_operation,
            parameters,
            okta_client,
            correlation_id,
            progress_callback
        )
        
        if not success:
            return False, None, None, error or "Special tool execution failed"
        
        # Step 3: Extract the LLM summary (the formatted result)
        llm_summary = result_data.get("llm_summary")
        
        if llm_summary:
            # Success! Return the pre-formatted summary
            logger.info(f"[{correlation_id}] Returning LLM-generated summary")
            return True, llm_summary, "markdown", None
        else:
            # Fallback: return raw data as JSON if no summary available
            logger.warning(f"[{correlation_id}] No llm_summary found, returning raw data")
            return True, json.dumps(result_data, indent=2), "markdown", None
            
    except Exception as e:
        error_msg = f"Exception in special tools handler: {str(e)}"
        logger.error(f"[{correlation_id}] {error_msg}", exc_info=True)
        return False, None, None, error_msg
