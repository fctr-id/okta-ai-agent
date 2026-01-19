"""
Multi-Agent Orchestrator - Coordinates SQL, API, and Synthesis Agents

Responsibilities:
- Determine which agents to run (skip logic)
- Route between agents with programmatic handoff
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
from src.core.agents.router_agent import route_query, RouterDecision
from src.core.agents.sql_discovery_agent import (
    execute_sql_discovery,
    SQLDiscoveryDeps,
    SQLDiscoveryResult
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
from src.core.agents.special_tools_handler import handle_special_query

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
        
        # Phase results
        self.router_decision: Optional[RouterDecision] = None
        self.sql_result: Optional[SQLDiscoveryResult] = None
        self.api_result: Optional[APIDiscoveryResult] = None
        self.synthesis_result: Optional[SynthesisResult] = None
        
        # Phases executed
        self.phases_executed: List[str] = []
        
        # Token usage tracking
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_tokens: int = 0
        self.total_requests: int = 0


# ============================================================================
# Decision Functions (REMOVED - Now using Router Agent LLM)
# ============================================================================

# Old keyword-based functions removed - replaced with LLM classification


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


# ============================================================================
# Main Orchestrator Function
# ============================================================================

async def execute_multi_agent_query(
    user_query: str,
    correlation_id: str,
    artifacts_file: Path,
    okta_client: Any,  # OktaClient instance
    cancellation_check: callable,
    event_callback: Optional[callable] = None
) -> OrchestratorResult:
    """
    Execute multi-agent query workflow.
    
    Workflow:
    0. Route query using Router Agent (LLM classification)
    1. Execute based on router decision:
       - SQL: Run SQL Discovery only
       - API: Run API Discovery only
       - SQL+API: Run both (SQL then API)
       - SPECIAL: Return error (not yet implemented)
       - NOT_RELEVANT: Return error
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
    logger.info(f"[{correlation_id}] Starting multi-agent orchestrator")
    logger.info(f"[{correlation_id}] Query: {user_query}")
    
    result = OrchestratorResult()
    
    # Initialize global tool call limits from environment
    max_tool_calls = int(os.getenv('MAX_TOOL_CALLS', '30'))
    global_tool_calls_counter = 0  # Shared across all agents
    logger.info(f"[{correlation_id}] Tool call limits: {max_tool_calls} total, 3 per tool type")
    
    # Load API endpoints data (needed for API discovery agent)
    endpoints_file = Path("src/data/schemas/Okta_API_entitity_endpoint_reference_GET_ONLY.json")
    endpoints_list = []
    try:
        with open(endpoints_file, 'r', encoding='utf-8') as f:
            endpoints_data = json.load(f)
            endpoints_list = endpoints_data.get('endpoints', [])
            logger.debug(f"[{correlation_id}] Loaded {len(endpoints_list)} API endpoints")
    except Exception as e:
        logger.warning(f"[{correlation_id}] Failed to load endpoints file: {e}")
    
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
        # PHASE 0: Route Query (LLM Classification)
        # ====================================================================
        logger.info(f"[{correlation_id}] Running Router Agent")
        result.router_decision, router_usage = await route_query(
            user_query, 
            correlation_id, 
            progress_callback=aggregator.progress,
            step_start_callback=aggregator.step_start
        )
        
        # Track token usage
        if router_usage:
            result.total_input_tokens += router_usage.input_tokens
            result.total_output_tokens += router_usage.output_tokens
            result.total_tokens += router_usage.total_tokens
            result.total_requests += router_usage.requests
        
        phase = result.router_decision.phase
        reasoning = result.router_decision.reasoning
        
        logger.info(f"[{correlation_id}] Router decision: {phase}")
        logger.info(f"[{correlation_id}] Router reasoning: {reasoning}")
        
        # Handle special cases
        if phase == "NOT_RELEVANT":
            result.error = "NOT-OKTA-RELATED"
            return result
        
        if phase == "SPECIAL":
            # Execute special tools
            logger.info(f"[{correlation_id}] Executing special tool handler")
            result.phases_executed.append('special')
            
            success, result_text, display_type, error = await handle_special_query(
                user_query=user_query,
                okta_client=okta_client,
                correlation_id=correlation_id,
                progress_callback=aggregator.progress
            )
            
            if success:
                # Special tools return pre-formatted results
                result.success = True
                result.script_code = result_text  # The llm_summary text
                result.display_type = display_type or "markdown"
                logger.info(f"[{correlation_id}] Special tool execution successful")
            else:
                result.error = error or "Special tool execution failed"
                logger.error(f"[{correlation_id}] Special tool failed: {result.error}")
            
            return result
        
        # ====================================================================
        # PHASE 1: SQL Discovery (always run unless user forced API-only)
        # ====================================================================
        should_run_sql = phase in ["PROCEED", "SQL"]
        
        if should_run_sql:
            logger.info(f"[{correlation_id}] Running SQL Discovery Agent")
            aggregator.set_phase('sql')
            result.phases_executed.append('sql')
            
            sql_deps = SQLDiscoveryDeps(
                correlation_id=correlation_id,
                artifacts_file=artifacts_file,
                okta_client=okta_client,
                cancellation_check=cancellation_check,
                step_start_callback=aggregator.step_start,
                step_end_callback=aggregator.step_end,
                tool_call_callback=aggregator.tool_call,
                progress_callback=aggregator.progress,
                # Tool call limits
                global_tool_calls=global_tool_calls_counter,
                max_global_tool_calls=max_tool_calls
            )
            
            result.sql_result, sql_usage = await execute_sql_discovery(user_query, sql_deps)
            
            # Update global counter after SQL phase
            global_tool_calls_counter = sql_deps.global_tool_calls
            logger.info(f"[{correlation_id}] Tool calls after SQL: {global_tool_calls_counter}/{max_tool_calls}")
            
            # Track token usage
            if sql_usage:
                result.total_input_tokens += sql_usage.input_tokens
                result.total_output_tokens += sql_usage.output_tokens
                result.total_tokens += sql_usage.total_tokens
                result.total_requests += sql_usage.requests
            
            if not result.sql_result.success:
                error_msg = result.sql_result.error or "SQL phase failed"
                logger.error(f"[{correlation_id}] SQL phase failed: {error_msg}")
                
                # Check if it's a hard limit error
                if "limit exceeded" in error_msg.lower():
                    # Hard stop - notify frontend and return
                    await aggregator.step_end({
                        "title": "Execution Stopped",
                        "text": f"❌ {error_msg}",
                        "timestamp": time.time()
                    })
                    result.error = error_msg
                    return result
                
                # Other SQL errors - continue anyway, API might still work
                logger.info(f"[{correlation_id}] Continuing to API phase despite SQL error")
        else:
            logger.info(f"[{correlation_id}] Skipped SQL Discovery (Router decision: {phase})")
        
        # ====================================================================
        # PHASE 2: API Discovery (if SQL says we need it, or user forced API-only)
        # ====================================================================
        should_run_api = False
        
        # User forced API-only
        if phase == "API":
            should_run_api = True
            logger.info(f"[{correlation_id}] User forced API-only mode")
        
        # PROCEED or SQL mode: Check if SQL found all data
        elif phase in ["PROCEED", "SQL"] and result.sql_result:
            if result.sql_result.needs_api and len(result.sql_result.needs_api) > 0:
                should_run_api = True
                logger.info(f"[{correlation_id}] SQL says we need API data: {result.sql_result.needs_api}")
            else:
                logger.info(f"[{correlation_id}] SQL found all data, skipping API")
        
        if should_run_api:
            logger.info(f"[{correlation_id}] Running API Discovery Agent")
            aggregator.set_phase('api')
            result.phases_executed.append('api')
            
            # Get SQL reasoning and data for API agent (only if SQL phase ran)
            sql_reasoning = None
            sql_discovered_data = None
            sql_needs_api = None
            sql_found_data = None
            
            if result.sql_result and result.sql_result.success:
                # SQL phase ran and succeeded - pass reasoning and structured data
                sql_reasoning = result.sql_result.reasoning
                sql_needs_api = result.sql_result.needs_api
                sql_found_data = result.sql_result.found_data
                
                # Load SQL artifacts and extract content
                if artifacts_file.exists():
                    try:
                        with open(artifacts_file, 'r', encoding='utf-8') as f:
                            artifacts = json.load(f)
                        
                        # Extract content from sql_results artifacts
                        sql_contents = []
                        for artifact in artifacts:
                            if artifact.get('category') == 'sql_results':
                                sql_contents.append(artifact.get('content', ''))
                        
                        # Combine all SQL result contents
                        if sql_contents:
                            sql_discovered_data = '\n'.join(sql_contents)
                            logger.info(f"[{correlation_id}] Passing SQL discovered data to API agent ({len(sql_discovered_data)} chars)")
                    except Exception as e:
                        logger.warning(f"[{correlation_id}] Failed to load SQL artifacts: {e}")
            elif result.sql_result and not result.sql_result.success:
                # SQL phase ran but failed - pass error message only
                sql_reasoning = f"SQL phase failed: {result.sql_result.error}"
            # else: SQL phase skipped (API-only mode) - both remain None
            
            api_deps = APIDiscoveryDeps(
                correlation_id=correlation_id,
                artifacts_file=artifacts_file,
                endpoints=endpoints_list,
                sql_reasoning=sql_reasoning,
                sql_discovered_data=sql_discovered_data,  # Pass SQL content
                sql_needs_api=sql_needs_api,  # Pass structured list
                sql_found_data=sql_found_data,  # Pass structured list
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
            logger.info(f"[{correlation_id}] Tool calls after API: {global_tool_calls_counter}/{max_tool_calls}")
            
            # Track token usage
            if api_usage:
                result.total_input_tokens += api_usage.input_tokens
                result.total_output_tokens += api_usage.output_tokens
                result.total_tokens += api_usage.total_tokens
                result.total_requests += api_usage.requests
            
            # Check for API limit errors and stop execution
            if not result.api_result.success:
                error_msg = result.api_result.error or "API phase failed"
                logger.error(f"[{correlation_id}] API phase failed: {error_msg}")
                
                # Check if it's a hard limit error
                if "limit exceeded" in error_msg.lower():
                    # Hard stop - notify frontend and return
                    await aggregator.step_end({
                        "title": "Execution Stopped",
                        "text": f"❌ {error_msg}",
                        "timestamp": time.time()
                    })
                    result.error = error_msg
                    return result
                
                # Other API errors - continue to synthesis
                logger.info(f"[{correlation_id}] Continuing to synthesis despite API error")
        else:
            logger.info(f"[{correlation_id}] Skipped API Discovery (Router decision: {phase} or SQL found all data)")
        
        # ====================================================================
        # PHASE 3: Synthesis
        # ====================================================================
        logger.info(f"[{correlation_id}] Running Synthesis Agent")
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
            progress_callback=aggregator.progress
        )
        
        result.synthesis_result, synthesis_usage = await execute_synthesis(user_query, synthesis_deps)
        
        # Track token usage
        if synthesis_usage:
            result.total_input_tokens += synthesis_usage.input_tokens
            result.total_output_tokens += synthesis_usage.output_tokens
            result.total_tokens += synthesis_usage.total_tokens
            result.total_requests += synthesis_usage.requests
        
        if not result.synthesis_result.success:
            logger.error(f"[{correlation_id}] Synthesis failed: {result.synthesis_result.error}")
            result.error = result.synthesis_result.error
            return result
        
        # ====================================================================
        # SUCCESS: Return Script
        # ====================================================================
        result.success = True
        result.script_code = result.synthesis_result.script_code
        result.display_type = result.synthesis_result.display_type
        
        logger.info(f"[{correlation_id}] Multi-agent workflow complete")
        logger.info(f"[{correlation_id}] Phases executed: {', '.join(result.phases_executed)}")
        
        # Log cumulative token usage
        if result.total_tokens > 0:
            avg_per_call = result.total_input_tokens / result.total_requests if result.total_requests > 0 else 0
            logger.info(
                f"[{correlation_id}] 📊 TOTAL Token Usage: "
                f"{result.total_input_tokens:,} input, {result.total_output_tokens:,} output, "
                f"{result.total_tokens:,} total (across {result.total_requests} API calls, "
                f"avg {avg_per_call:,.0f} input/call)"
            )
        
        return result
        
    except asyncio.CancelledError:
        logger.warning(f"[{correlation_id}] Multi-agent workflow cancelled by user")
        result.error = "Cancelled by user"
        # Notify frontend of cancellation
        await aggregator.step_end({
            "title": "Workflow Cancelled",
            "text": "❌ Execution cancelled by user",
            "timestamp": time.time()
        })
        return result
        
    except RuntimeError as e:
        # Tool call limit exceeded or other hard stop
        error_msg = str(e)
        logger.error(f"[{correlation_id}] Hard stop triggered: {error_msg}")
        result.error = error_msg
        # Notify frontend with proper error format
        await aggregator.step_end({
            "title": "Execution Stopped",
            "text": f"❌ {error_msg}",
            "timestamp": time.time()
        })
        return result
        
    except Exception as e:
        logger.error(f"[{correlation_id}] Orchestrator error: {e}", exc_info=True)
        result.error = str(e)
        # Notify frontend of unexpected error
        await aggregator.step_end({
            "title": "Unexpected Error",
            "text": f"❌ An error occurred: {str(e)}",
            "timestamp": time.time()
        })
        return result
