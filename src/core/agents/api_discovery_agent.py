"""
API Discovery Agent - Phase 2 of Multi-Agent Architecture

Responsibilities:
- Load API endpoints and filter by operations needed
- Generate and test API code
- Save API results to artifacts
- Enrich data from SQL phase

Input: SQLDiscoveryResult reasoning + artifacts from SQL phase
Output: APIDiscoveryResult with success status
"""

from pydantic_ai import Agent, RunContext, FunctionToolset, ToolReturn
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from pathlib import Path
import json
import time
import asyncio
import re

from src.utils.logging import get_logger
from src.utils.security_config import validate_generated_code
from src.core.security.network_security import validate_request
from src.core.agents.agent_callbacks import (
    notify_progress_to_user,
    notify_step_start_to_user,
    notify_step_end_to_user
)

logger = get_logger("okta_ai_agent")

# ============================================================================
# Output Models
# ============================================================================

class APIDiscoveryResult(BaseModel):
    """Output from API Discovery Agent"""
    success: bool
    api_data_retrieved: bool = False
    error: Optional[str] = None


# ============================================================================
# Dependencies
# ============================================================================

@dataclass
class APIDiscoveryDeps:
    """Dependencies for API Discovery Agent"""
    correlation_id: str
    artifacts_file: Path
    sql_reasoning: str  # Feedback from SQL agent
    okta_client: Any  # OktaClient instance
    cancellation_check: callable
    endpoints: List[Dict[str, Any]]  # Full endpoint details (injected like one_react_agent)
    
    # Streaming callbacks
    step_start_callback: Optional[callable] = None
    step_end_callback: Optional[callable] = None
    tool_call_callback: Optional[callable] = None  # For tool call notifications
    progress_callback: Optional[callable] = None  # For intermediate progress updates
    
    # State tracking
    api_tests_executed: int = 0
    current_step: int = 5  # Starts after SQL (steps 1-5)
    current_tools: List[Dict[str, str]] = None  # Track tools used in current step
    artifacts: List[Dict] = None  # Artifact storage (shared with orchestrator)
    
    def __post_init__(self):
        """Initialize mutable defaults"""
        if self.current_tools is None:
            self.current_tools = []
        if self.artifacts is None:
            self.artifacts = []


# ============================================================================
# Helper Functions
# ============================================================================

def generate_lightweight_onereact_json(force_regenerate: bool = False) -> Dict[str, Any]:
    """
    Generate a minimal lightweight JSON structure for API endpoints.
    Uses simple dot notation: entity.operation (e.g., "application.list")
    
    Args:
        force_regenerate: If True, regenerate even if file exists
        
    Returns:
        Dict with 'operations' (list of strings)
    """
    schemas_dir = Path("src/data/schemas")
    lightweight_path = schemas_dir / "lightweight_onereact.json"
    source_path = schemas_dir / "Okta_API_entitity_endpoint_reference_GET_ONLY.json"
    
    # Load existing file if it exists and regeneration not forced
    if lightweight_path.exists() and not force_regenerate:
        logger.info(f"Loading existing lightweight_onereact.json from {lightweight_path}")
        try:
            with open(lightweight_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load existing file: {e}. Regenerating...")
    
    # Generate new lightweight structure
    logger.info("Generating new lightweight_onereact.json...")
    
    # Load source endpoint data
    if not source_path.exists():
        logger.error(f"Source file not found: {source_path}")
        return {"operations": []}
    
    try:
        with open(source_path, 'r', encoding='utf-8') as f:
            source_data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load source file: {e}")
        return {"operations": []}
    
    # Extract operations in dot notation format
    operations = []
    seen_operations = set()  # Deduplicate
    
    endpoints = source_data.get('endpoints', [])
    for endpoint in endpoints:
        entity = endpoint.get('entity', '')
        operation = endpoint.get('operation', '')
        
        if entity and operation:
            # Create dot notation: entity.operation
            op_string = f"{entity}.{operation}"
            if op_string not in seen_operations:
                operations.append(op_string)
                seen_operations.add(op_string)
    
    # Sort for consistency
    operations.sort()
    
    # Create minimal structure
    lightweight_data = {
        "operations": operations
    }
    
    # Save to file
    try:
        schemas_dir.mkdir(parents=True, exist_ok=True)
        with open(lightweight_path, 'w', encoding='utf-8') as f:
            json.dump(lightweight_data, f, indent=2)
        logger.info(f"Generated lightweight_onereact.json with {len(operations)} operations")
    except Exception as e:
        logger.error(f"Failed to save lightweight_onereact.json: {e}")
    
    return lightweight_data


def load_lightweight_endpoints() -> Dict[str, Any]:
    """Load lightweight endpoint structure"""
    return generate_lightweight_onereact_json()


async def dump_artifacts_to_file(artifacts_file: Path, artifacts: List[dict]):
    """Append to existing artifacts file"""
    try:
        # Load existing
        if artifacts_file.exists():
            with open(artifacts_file, 'r', encoding='utf-8') as f:
                existing = json.load(f)
                # Handle both list and dict formats (SQL agent might save dict)
                if isinstance(existing, dict):
                    existing = [existing]
                elif not isinstance(existing, list):
                    existing = []
        else:
            existing = []
        
        # Append new
        existing.extend(artifacts)
        
        # Save
        with open(artifacts_file, 'w', encoding='utf-8') as f:
            json.dump(existing, f, indent=2, default=str)
        
        logger.debug(f"Artifacts updated: {artifacts_file}")
    except Exception as e:
        logger.error(f"Failed to update artifacts: {e}")


# ============================================================================
# API Discovery Agent Definition
# ============================================================================

# Load system prompt
PROMPT_FILE = Path(__file__).parent / "prompts" / "api_discovery_prompt.txt"
try:
    with open(PROMPT_FILE, 'r', encoding='utf-8') as f:
        BASE_SYSTEM_PROMPT = f.read()
except FileNotFoundError:
    logger.error(f"API discovery prompt not found: {PROMPT_FILE}")
    BASE_SYSTEM_PROMPT = """You are an API discovery specialist.
Filter endpoints, generate API code, test calls, save results."""


# Model selection
try:
    from src.core.models.model_picker import ModelConfig, ModelType
    model = ModelConfig.get_model(ModelType.CODING)
except ImportError:
    import os
    model = os.getenv('LLM_MODEL', 'openai:gpt-4o-mini')


# Create agent
api_discovery_agent = Agent(
    model,
    instructions=BASE_SYSTEM_PROMPT,
    output_type=APIDiscoveryResult,
    deps_type=APIDiscoveryDeps,
    retries=0
)


# ============================================================================
# Tool Implementations
# ============================================================================

def create_api_toolset(deps: APIDiscoveryDeps) -> FunctionToolset:
    """Create API discovery tools"""
    toolset = FunctionToolset()
    
    # Track artifacts
    if not hasattr(deps, 'artifacts'):
        deps.artifacts = []
    
    def check_cancellation():
        if deps.cancellation_check and deps.cancellation_check():
            raise asyncio.CancelledError("User cancelled execution")
    
    async def notify_tool_call(tool_name: str, description: str):
        """Emit tool call event to frontend"""
        if deps.tool_call_callback:
            await deps.tool_call_callback({
                "tool_name": tool_name,
                "description": description,
                "timestamp": time.time()
            })
    
    async def notify_step_start(title: str, reasoning: str, tool_name: Optional[str] = None):
        if deps.step_start_callback:
            deps.current_step += 1
            
            # Track tool if provided
            if tool_name:
                deps.current_tools.append({"name": tool_name})
            
            await deps.step_start_callback({
                "step": deps.current_step,
                "title": title,
                "text": reasoning,
                "tools": deps.current_tools.copy(),
                "timestamp": time.time()
            })
    
    async def notify_step_end(title: str, result: str):
        if deps.step_end_callback:
            await deps.step_end_callback({
                "step": deps.current_step,
                "title": title,
                "text": result,
                "timestamp": time.time()
            })
        # Clear tools for next step
        deps.current_tools.clear()
    
    # ========================================================================
    # Tool 1: Load API Endpoints
    # ========================================================================
    
    async def load_comprehensive_api_endpoints() -> ToolReturn:
        """
        Load all available API operations.
        
        Returns dot notation operations: "user.list", "role.list_by_user"
        CALL THIS ONCE at start.
        """
        check_cancellation()
        await notify_tool_call("load_comprehensive_api_endpoints", "Loading API endpoints catalog")
        
        logger.info(f"[{deps.correlation_id}] Loading API endpoints")
        
        try:
            data = load_lightweight_endpoints()
            operations = data.get('operations', [])
            
            await notify_step_end(
                "Endpoints Loaded",
                f"Loaded {len(operations)} operations"
            )
            
            return ToolReturn(
                return_value=f"✅ Loaded {len(operations)} operations",
                content=json.dumps(operations, indent=2),
                metadata={'operation_count': len(operations)}
            )
        except Exception as e:
            logger.error(f"[{deps.correlation_id}] Failed to load endpoints: {e}")
            return ToolReturn(
                return_value=f"❌ Failed to load endpoints: {e}",
                content=str(e),
                metadata={'error': True}
            )
    
    # ========================================================================
    # Tool 2: Filter Endpoints by Operations
    # ========================================================================
    
    async def filter_endpoints_by_operations(operations: List[str]) -> ToolReturn:
        """
        Filter endpoints for specific operations.
        
        Args:
            operations: List like ["user.list_assigned_roles", "group.list"]
        
        Returns:
            Filtered endpoint details with paths, methods, parameters
        """
        check_cancellation()
        await notify_tool_call("filter_endpoints_by_operations", f"Filtering endpoints for: {', '.join(operations[:3])}{'...' if len(operations) > 3 else ''}")
        
        logger.info(f"[{deps.correlation_id}] Filtering operations: {operations}")
        
        try:
            # Use injected endpoints (same pattern as one_react_agent)
            filtered = []
            for op in operations:
                # Split operation (e.g., "user.list" → entity="user", operation="list")
                if '.' in op:
                    parts = op.split('.', 1)
                    search_entity = parts[0]
                    search_operation = parts[1]
                else:
                    search_entity = None
                    search_operation = op
                
                # Find matching endpoint
                for endpoint in deps.endpoints:
                    endpoint_entity = endpoint.get('entity', '')
                    endpoint_operation = endpoint.get('operation', '')
                    
                    if search_entity:
                        # Match both entity and operation
                        if endpoint_entity == search_entity and endpoint_operation == search_operation:
                            filtered.append(endpoint)
                            break
                    else:
                        # Match operation only
                        if endpoint_operation == search_operation:
                            filtered.append(endpoint)
                            break
            
            await notify_step_end(
                "Endpoints Filtered",
                f"Found {len(filtered)} matching endpoints"
            )
            
            return ToolReturn(
                return_value=f"✅ Filtered {len(filtered)} endpoints",
                content=json.dumps(filtered, indent=2),
                metadata={'filtered_count': len(filtered)}
            )
        except Exception as e:
            logger.error(f"[{deps.correlation_id}] Filtering failed: {e}")
            return ToolReturn(
                return_value=f"❌ Filtering failed: {e}",
                content=str(e),
                metadata={'error': True}
            )
    
    # ========================================================================
    # Tool 3: Execute API Test
    # ========================================================================
    
    async def execute_test_query(code: str) -> ToolReturn:
        """
        Execute API code (Python using OktaSDKClientManager).
        Auto-limited to 3 results during testing.
        
        Args:
            code: Python code using okta_client
        """
        check_cancellation()
        
        await notify_tool_call("execute_test_query_api", f"Testing API call (test #{deps.api_tests_executed + 1})")
        
        deps.api_tests_executed += 1
        if deps.api_tests_executed > 5:
            return ToolReturn(
                return_value="❌ Test limit exceeded (5 tests max)",
                content="Stop testing. Finalize with success/failure.",
                metadata={'error': True}
            )
        
        # Notify tool call start
        await notify_tool_call("execute_test_query_api", f"Testing API code (attempt #{deps.api_tests_executed})")
        
        logger.info(f"[{deps.correlation_id}] Executing API test #{deps.api_tests_executed}")
        
        # Log the generated API code
        logger.info(f"[{deps.correlation_id}] 📝 Generated API code:\n{code}")
        
        # SECURITY VALIDATION: Check Python code for dangerous patterns
        validation_result = validate_generated_code(code)
        if not validation_result.is_valid:
            logger.warning(f"[{deps.correlation_id}] Code validation failed: {validation_result.violations}")
            await notify_step_end(
                "Validation Failed",
                f"Security: {', '.join(validation_result.violations)}"
            )
            return ToolReturn(
                return_value=f"❌ Security validation failed",
                content=f"Violations: {', '.join(validation_result.violations)}",
                metadata={'success': False, 'security_error': True}
            )
        
        # SECURITY VALIDATION: Check network requests for unauthorized domains
        endpoint_match = re.search(r'endpoint\s*=\s*["\']([^"\']+)["\']', code)
        if endpoint_match:
            endpoint = endpoint_match.group(1)
            # Skip validation for special tools (they have their own security)
            if not endpoint.startswith("/special-tools/"):
                # Build full URL for validation
                full_url = f"{deps.okta_client.base_url}{endpoint}"
                network_validation = validate_request('GET', full_url)
                if not network_validation.is_allowed:
                    logger.warning(f"[{deps.correlation_id}] Network security validation failed: {network_validation.blocked_reason}")
                    await notify_step_end(
                        "Network Security Failed",
                        f"Blocked: {network_validation.blocked_reason}"
                    )
                    return ToolReturn(
                        return_value=f"❌ Network security validation failed",
                        content=f"❌ NETWORK SECURITY FAILED: {network_validation.blocked_reason}",
                        metadata={'success': False, 'security_error': True, 'violations': network_validation.violations}
                    )
        
        # QUALITY CONTROL: Enforce Test Mode for API client (forces max_results=3)
        if hasattr(deps, 'okta_client') and hasattr(deps.okta_client, 'test_mode'):
            deps.okta_client.test_mode = True
            logger.debug(f"[{deps.correlation_id}] Enabled test_mode on okta_client (enforces max_results=3)")
        
        # Execute code
        try:
            # Create namespace with okta_client available (matching one_react_agent)
            namespace = {
                'client': deps.okta_client,
                'okta_client': deps.okta_client,
                'asyncio': asyncio
            }
            
            # Detect function name from generated code
            func_match = re.search(r'async\s+def\s+(\w+)\s*\(', code)
            if not func_match:
                logger.error(f"[{deps.correlation_id}] Generated code must define an async function")
                raise ValueError("Generated code must define an async function starting with 'async def function_name():'")
            
            func_name = func_match.group(1)
            
            # Check if the code already assigns results
            has_results_assignment = 'results = await' in code or 'results=await' in code
            
            if has_results_assignment:
                # Code already calls the function and assigns to 'results'
                wrapped_code = f"""async def __exec_wrapper__():
{chr(10).join('    ' + line for line in code.split(chr(10)))}
    return results
"""
            else:
                # Code only defines the function, so call it
                wrapped_code = f"""async def __exec_wrapper__():
{chr(10).join('    ' + line for line in code.split(chr(10)))}
    return await {func_name}()
"""
            
            # Execute to define the wrapper function
            exec(wrapped_code, namespace)
            
            # Now await the wrapper coroutine (we're already in an async context)
            result = await namespace['__exec_wrapper__']()
            
            # IMPORTANT: Do NOT auto-save here
            # LLM will explicitly call save_artifact() tool when results are validated
            # This allows LLM to test multiple times and only save final validated code+results
            
            result_summary = f"API call successful, returned data"
            await notify_step_end(
                f"API Test #{deps.api_tests_executed} Complete",
                result_summary
            )
            
            return ToolReturn(
                return_value=f"✅ API executed successfully",
                content=json.dumps(result, indent=2, default=str)[:1000],
                metadata={'success': True}
            )
            
        except Exception as e:
            logger.error(f"[{deps.correlation_id}] API execution failed: {e}")
            await notify_step_end(
                "API Execution Failed",
                f"Error: {str(e)}"
            )
            return ToolReturn(
                return_value=f"❌ API error: {str(e)}",
                content=f"Execution failed: {str(e)}",
                metadata={'success': False, 'error': str(e)}
            )
    
    # ========================================================================
    # Tool 4: Save Artifact
    # ========================================================================
    
    async def save_artifact(
        key: str,
        category: str,
        content: str,
        api_code: Optional[str] = None,
        notes: Optional[str] = None
    ) -> ToolReturn:
        """Save API results to artifacts"""
        check_cancellation()
        
        artifact = {
            "key": key,
            "category": category,
            "content": content,
            "notes": notes or f"Saved by API agent at test #{deps.api_tests_executed}",
            "timestamp": time.time()
        }
        
        # Add API code if provided (CRITICAL for synthesis agent)
        if api_code:
            artifact["api_code"] = api_code
        
        deps.artifacts.append(artifact)
        await dump_artifacts_to_file(deps.artifacts_file, [artifact])
        
        logger.info(f"[{deps.correlation_id}] Saved artifact: {key}")
        
        return ToolReturn(
            return_value=f"✅ Saved artifact: {key}",
            content=f"Artifact saved",
            metadata={'artifact_count': len(deps.artifacts)}
        )
    
    # ========================================================================
    # Tool 5: Notify Progress (for LLM to report progress to user)
    # ========================================================================
    
    async def notify_progress_to_user(
        ctx: RunContext[APIDiscoveryDeps],
        message: str,
        details: str = ""
    ) -> str:
        """
        Report progress to the user. Call this to keep users informed of what you're doing.
        Use this for intermediate updates like "Fetched 10 users", "Testing endpoint X", etc.
        
        Args:
            message: Progress message (e.g., "Testing API endpoint")
            details: Optional additional details
        
        Returns:
            Confirmation that progress was logged
        """
        check_cancellation()
        
        # Log to server with full details
        logger.info(f"[{deps.correlation_id}] 📊 Progress: {message}")
        if details:
            logger.info(f"[{deps.correlation_id}] 📊 Details: {details}")
        
        # Send to frontend via step_start callback (creates STEP-START events)
        if deps.step_start_callback:
            await deps.step_start_callback({
                "title": "",
                "text": message,  # Frontend displays text field
                "timestamp": time.time()
            })
        
        return f"✅ Progress logged: {message}"
    
    # Register tools
    toolset.tool(load_comprehensive_api_endpoints)
    toolset.tool(filter_endpoints_by_operations)
    toolset.tool(execute_test_query)
    toolset.tool(save_artifact)
    toolset.tool(notify_progress_to_user)
    
    return toolset


# ============================================================================
# Main Execution Function
# ============================================================================

async def execute_api_discovery(
    user_query: str,
    deps: APIDiscoveryDeps
) -> APIDiscoveryResult:
    """
    Execute API discovery phase.
    
    Args:
        user_query: Original user query
        deps: API discovery dependencies with SQL reasoning
    
    Returns:
        APIDiscoveryResult with success status
    """
    logger.info(f"[{deps.correlation_id}] Starting API discovery phase")
    logger.info(f"[{deps.correlation_id}] SQL feedback: {deps.sql_reasoning}")
    
    # Helper functions for step notifications
    async def notify_step_start(title: str, reasoning: str):
        """Notify orchestrator of step start"""
        if deps.step_start_callback:
            deps.current_step += 1
            await deps.step_start_callback({
                "step": deps.current_step,
                "title": title,
                "text": reasoning,
                "timestamp": time.time()
            })
    
    async def notify_step_end(title: str, result: str):
        """Notify orchestrator of step end"""
        if deps.step_end_callback:
            await deps.step_end_callback({
                "step": deps.current_step,
                "title": title,
                "text": result,
                "timestamp": time.time()
            })
    
    # Create toolset for this run (following one_react_agent pattern)
    toolset = create_api_toolset(deps)
    
    try:
        result = await api_discovery_agent.run(
            f"{user_query}\n\nSQL Phase Results: {deps.sql_reasoning}",
            deps=deps,
            toolsets=[toolset]  # Pass toolset to run()
        )
        
        logger.info(f"[{deps.correlation_id}] API discovery complete: success={result.output.success}")
        
        # Notify frontend of completion
        await notify_step_end(
            "API Discovery Complete",
            f"API data retrieval {'successful' if result.output.success else 'failed'}. Ready for synthesis phase."
        )
        
        # Log token usage
        if result.usage():
            usage = result.usage()
            avg_per_call = usage.input_tokens / usage.requests if usage.requests > 0 else 0
            logger.info(
                f"[{deps.correlation_id}] 📊 API Agent Token Usage: "
                f"{usage.input_tokens:,} input, {usage.output_tokens:,} output, "
                f"{usage.total_tokens:,} total (across {usage.requests} API calls, "
                f"avg {avg_per_call:,.0f} input/call)"
            )
        
        return result.output, result.usage()
        
    except Exception as e:
        logger.error(f"[{deps.correlation_id}] API discovery failed: {e}", exc_info=True)
        return APIDiscoveryResult(
            success=False,
            api_data_retrieved=False,
            error=str(e)
        ), None
