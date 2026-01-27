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
import sqlite3

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
# Database Health Check
# ============================================================================

def get_last_sync_timestamp() -> Optional[str]:
    """
    Get the last successful sync timestamp from the database.
    Returns ISO 8601 timestamp string or None if unavailable.
    """
    try:
        # Check multiple possible database locations
        possible_paths = [
            Path("sqlite_db/okta_sync.db"),
            Path("okta_sync.db"),
            Path("../sqlite_db/okta_sync.db")
        ]
        
        db_path = None
        for path in possible_paths:
            if path.exists():
                db_path = path
                break
        
        if not db_path:
            return None
        
        with sqlite3.connect(db_path, timeout=5) as conn:
            cursor = conn.cursor()
            
            # Check if sync_history table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sync_history'")
            if not cursor.fetchone():
                return None
            
            # Get most recent SUCCESSFUL sync time
            cursor.execute("""
                SELECT end_time 
                FROM sync_history 
                WHERE success = 1 AND end_time IS NOT NULL 
                ORDER BY end_time DESC 
                LIMIT 1
            """)
            row = cursor.fetchone()
            
            if not row or not row[0]:
                return None
            
            # Convert to ISO 8601 format for JavaScript Date parsing
            # Database stores: '2026-01-22 14:51:57.424133'
            # Return: '2026-01-22T14:51:57.424133Z' (assume UTC)
            timestamp_str = row[0]
            if 'T' not in timestamp_str:
                # Replace space with T for ISO format
                timestamp_str = timestamp_str.replace(' ', 'T') + 'Z'
            
            return timestamp_str
            
    except Exception as e:
        logger.debug(f"Could not retrieve last sync timestamp: {e}")
        return None


def check_database_health() -> bool:
    """
    Check if database exists and has data.
    Returns False if database is unavailable or empty (no users).
    """
    try:
        # Check multiple possible database locations
        possible_paths = [
            Path("sqlite_db/okta_sync.db"),
            Path("okta_sync.db"),
            Path("../sqlite_db/okta_sync.db")
        ]
        
        db_path = None
        for path in possible_paths:
            if path.exists():
                db_path = path
                break
        
        if not db_path:
            logger.warning("Database file not found in any expected location - Skipping SQL phase")
            return False
        
        # Check if database is accessible and has users
        with sqlite3.connect(db_path, timeout=5) as conn:
            cursor = conn.cursor()
            
            # Check if users table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
            if not cursor.fetchone():
                logger.warning("Users table not found in database - Skipping SQL phase")
                return False
            
            # Check if users table has at least 1 record
            cursor.execute("SELECT COUNT(*) FROM users")
            user_count = cursor.fetchone()[0]
            
            if user_count < 1:
                logger.warning("Database has no users - Skipping SQL phase")
                return False
            
            logger.info(f"Database health check passed: Found {user_count} users")
            return True
            
    except Exception as e:
        logger.warning(f"Database health check failed: {e} - Skipping SQL phase")
        return False


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
        self.is_special_tool: bool = False  # Flag to skip validation for special tools
        
        # Phase results
        self.router_decision: Optional[RouterDecision] = None
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
                result.is_special_tool = True  # Flag to skip validation
                logger.info(f"[{correlation_id}] Special tool execution successful")
            else:
                result.error = error or "Special tool execution failed"
                logger.error(f"[{correlation_id}] Special tool failed: {result.error}")
            
            return result
        
        # ====================================================================
        # Helper: Load artifacts from file (DRY principle)
        # ====================================================================
        def load_artifacts_by_category(category: str) -> Optional[str]:
            """Load and combine artifacts of specified category"""
            # Validate artifacts_file is within logs directory to prevent path traversal
            try:
                artifacts_file.resolve().relative_to(Path("logs").resolve())
            except ValueError:
                logger.error(f"[{correlation_id}] Unsafe artifacts file path: {artifacts_file}")
                return None
            
            # Only proceed if the artifacts path points to an actual file
            if not artifacts_file.is_file():
                return None
            try:
                with open(artifacts_file, 'r', encoding='utf-8') as f:
                    artifacts = json.load(f)
                contents = [a.get('content', '') for a in artifacts if a.get('category') == category]
                return '\n'.join(contents) if contents else None
            except Exception as e:
                logger.warning(f"[{correlation_id}] Failed to load {category} artifacts: {e}")
                return None
        
        # ====================================================================
        # PHASE 1: SQL Discovery (if Router → SQL AND DB is healthy)
        # ====================================================================
        should_run_sql = phase == "SQL"
        
        # Check database health before attempting SQL phase
        if should_run_sql:
            db_healthy = check_database_health()
            if not db_healthy:
                logger.info(f"[{correlation_id}] Database unavailable or empty - Falling back to API")
                should_run_sql = False
                # Force API mode since DB is unavailable
                phase = "API"
        
        if should_run_sql:
            logger.info(f"[{correlation_id}] Running SQL Discovery Agent")
            aggregator.set_phase('sql')
            result.phases_executed.append('sql')
            
            # Send STEP-START for SQL Discovery phase
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
        # PHASE 2 & 2.5: Multi-Step Discovery Loop (API ↔ SQL)
        # ====================================================================
        # Allow up to 6 phase executions (e.g., API→SQL→API→SQL→API→SQL)
        # Each SQL or API execution counts as one iteration
        max_iterations = 6
        iteration_count = 0
        
        # Track handoff requests per iteration (cleared after acting on them)
        pending_api_request = None  # Set when SQL requests API
        pending_sql_request = None  # Set when API requests SQL
        
        # CRITICAL: Capture initial SQL phase handoff request (if any)
        if result.sql_result and result.sql_result.needs_api and len(result.sql_result.needs_api) > 0:
            pending_api_request = result.sql_result.needs_api
            logger.info(f"[{correlation_id}] SQL agent requests API data: {pending_api_request}")
        
        logger.info(f"[{correlation_id}] Starting multi-step discovery loop (max {max_iterations} phases)")
        
        while iteration_count < max_iterations:
            # Check if we need to run API phase
            should_run_api = (
                phase == "API"  # Router decided API (first iteration only)
                or pending_api_request is not None  # SQL requested API in previous iteration
            )
            
            # Check if we need to run SQL phase
            should_run_sql = (
                pending_sql_request is not None  # API requested SQL in previous iteration
            )
            
            # Exit loop if no more phases needed
            if not should_run_api and not should_run_sql:
                logger.info(f"[{correlation_id}] Discovery loop complete: No more phases needed (iterations: {iteration_count})")
                break
            
            # Clear pending requests before this iteration
            pending_api_request = None
            pending_sql_request = None
            
            # ================================================================
            # Run API Discovery (if needed)
            # ================================================================
            if should_run_api:
                iteration_count += 1
                logger.info(f"[{correlation_id}] Running API Discovery Agent (iteration {iteration_count}/{max_iterations})")
                aggregator.set_phase('api')
                result.phases_executed.append('api')
                
                # Get SQL context for API agent
                sql_reasoning = None
                sql_discovered_data = None
                sql_needs_api = None
                sql_found_data = None
                
                if result.sql_result and result.sql_result.success:
                    sql_reasoning = result.sql_result.reasoning
                    sql_needs_api = result.sql_result.needs_api
                    sql_found_data = result.sql_result.found_data
                    sql_discovered_data = load_artifacts_by_category('sql_results')
                    if sql_discovered_data:
                        logger.info(f"[{correlation_id}] Passing SQL discovered data to API agent ({len(sql_discovered_data)} chars)")
                elif result.sql_result:
                    sql_reasoning = f"SQL phase failed: {result.sql_result.error}"
                
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
                        await aggregator.step_end({
                            "title": "Execution Stopped",
                            "text": f"❌ {error_msg}",
                            "timestamp": time.time()
                        })
                        result.error = error_msg
                        return result
                    
                    # Check if agent is requesting SQL help (handoff)
                    if result.api_result.needs_sql and len(result.api_result.needs_sql) > 0:
                        logger.info(f"[{correlation_id}] API needs SQL help: {result.api_result.needs_sql} - continuing to SQL phase")
                    else:
                        logger.info(f"[{correlation_id}] Exiting discovery loop due to API error (no handoff requested)")
                        break
                
                # Reset phase flag after first iteration
                if phase == "API":
                    phase = None
                
                # Capture this iteration's SQL request (if any)
                if result.api_result.needs_sql and len(result.api_result.needs_sql) > 0:
                    pending_sql_request = result.api_result.needs_sql
                    logger.info(f"[{correlation_id}] API requests SQL for next iteration: {pending_sql_request}")
            
            # ================================================================
            # Run SQL Discovery (if pending request exists)
            # ================================================================
            if pending_sql_request is not None:
                iteration_count += 1
                logger.info(f"[{correlation_id}] API agent requests SQL data: {pending_sql_request}")
                logger.info(f"[{correlation_id}] Running SQL Discovery Agent (iteration {iteration_count}/{max_iterations})")
                
                # Check DB health using same method as Phase 1
                db_healthy = check_database_health()
                if not db_healthy:
                    logger.warning(f"[{correlation_id}] API needs SQL but DB is unavailable - exiting discovery loop")
                    break
                
                aggregator.set_phase('sql')
                result.phases_executed.append('sql')
                
                await aggregator.step_start({
                    "title": "SQL Discovery",
                    "text": f"Fetching base entities from database: {', '.join(pending_sql_request)}",
                    "timestamp": time.time()
                })
                
                # Get API reasoning and data for SQL agent
                api_needs_sql = pending_sql_request
                api_found_data = result.api_result.found_data if result.api_result.found_data else []
                
                # Use API agent's reasoning output or provide default
                if result.api_result.success and result.api_result.reasoning:
                    api_reasoning = result.api_result.reasoning
                else:
                    api_reasoning = f"API agent needs base entities: {', '.join(pending_sql_request)}"
                
                # Load API artifacts
                api_discovered_data = load_artifacts_by_category('api_results')
                if api_discovered_data:
                    logger.info(f"[{correlation_id}] Passing API discovered data to SQL agent ({len(api_discovered_data)} chars)")
                
                sql_deps = SQLDiscoveryDeps(
                    correlation_id=correlation_id,
                    artifacts_file=artifacts_file,
                    okta_client=okta_client,
                    cancellation_check=cancellation_check,
                    api_reasoning=api_reasoning,
                    api_discovered_data=api_discovered_data,
                    api_needs_sql=api_needs_sql,
                    api_found_data=api_found_data,
                    step_start_callback=aggregator.step_start,
                    step_end_callback=aggregator.step_end,
                    tool_call_callback=aggregator.tool_call,
                    progress_callback=aggregator.progress,
                    global_tool_calls=global_tool_calls_counter,
                    max_global_tool_calls=max_tool_calls
                )
                
                result.sql_result, sql_usage = await execute_sql_discovery(user_query, sql_deps)
                
                global_tool_calls_counter = sql_deps.global_tool_calls
                logger.info(f"[{correlation_id}] Tool calls after SQL: {global_tool_calls_counter}/{max_tool_calls}")
                
                if sql_usage:
                    result.total_input_tokens += sql_usage.input_tokens
                    result.total_output_tokens += sql_usage.output_tokens
                    result.total_tokens += sql_usage.total_tokens
                    result.total_requests += sql_usage.requests
                
                # Check for SQL limit errors
                if not result.sql_result.success:
                    error_msg = result.sql_result.error or "SQL phase failed"
                    if "limit exceeded" in error_msg.lower():
                        await aggregator.step_end({
                            "title": "Execution Stopped",
                            "text": f"❌ {error_msg}",
                            "timestamp": time.time()
                        })
                        result.error = error_msg
                        return result
                    # Check if agent is requesting API help (handoff)
                    if result.sql_result.needs_api and len(result.sql_result.needs_api) > 0:
                        logger.info(f"[{correlation_id}] SQL needs API help: {result.sql_result.needs_api} - continuing to API phase")
                    else:
                        logger.info(f"[{correlation_id}] Exiting discovery loop due to SQL error (no handoff requested)")
                        break
                
                # Capture this iteration's API request (if any)
                if result.sql_result.needs_api and len(result.sql_result.needs_api) > 0:
                    pending_api_request = result.sql_result.needs_api
                    logger.info(f"[{correlation_id}] SQL requests API for next iteration: {pending_api_request}")
                
                await aggregator.step_end({
                    "title": "SQL Discovery Complete",
                    "text": f"SQL data retrieved: {result.sql_result.success}",
                    "timestamp": time.time()
                })
        
        # Check if we hit max iterations
        if iteration_count >= max_iterations:
            logger.warning(f"[{correlation_id}] Discovery loop hit maximum iterations ({max_iterations})")
            await aggregator.progress({
                "message": f"⚠️ Reached maximum discovery phases ({max_iterations}), proceeding with available data"
            })
        
        # ====================================================================
        # Validate Discovery Results Before Synthesis
        # ====================================================================
        # Check if any discovery phase actually succeeded
        sql_succeeded = result.sql_result and result.sql_result.success
        api_succeeded = result.api_result and result.api_result.success
        
        if not sql_succeeded and not api_succeeded:
            # Both phases failed or didn't run - cannot proceed
            error_details = []
            if result.sql_result and not result.sql_result.success:
                error_details.append(f"SQL: {result.sql_result.error}")
            if result.api_result and not result.api_result.success:
                error_details.append(f"API: {result.api_result.error}")
            
            error_msg = "Discovery failed - no data retrieved. " + " | ".join(error_details) if error_details else "No discovery phases succeeded"
            logger.error(f"[{correlation_id}] {error_msg}")
            
            await aggregator.step_end({
                "title": "Discovery Failed",
                "text": f"❌ {error_msg}",
                "timestamp": time.time()
            })
            
            result.error = error_msg
            return result
        
        logger.info(f"[{correlation_id}] Discovery validation passed (SQL: {sql_succeeded}, API: {api_succeeded})")
        
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
            tool_call_callback=aggregator.tool_call,
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
        
        # Determine data source type based on which agents ran successfully
        sql_succeeded = result.sql_result and result.sql_result.success
        api_succeeded = result.api_result and result.api_result.success
        
        if sql_succeeded and api_succeeded:
            result.data_source_type = "hybrid"
        elif sql_succeeded:
            result.data_source_type = "sql"
        elif api_succeeded:
            result.data_source_type = "api"
        
        # Get last sync timestamp if SQL was used
        if result.data_source_type in ["sql", "hybrid"]:
            result.last_sync_time = get_last_sync_timestamp()
        
        logger.info(f"[{correlation_id}] Multi-agent workflow complete")
        logger.info(f"[{correlation_id}] Phases executed: {', '.join(result.phases_executed)}")
        logger.info(f"[{correlation_id}] Data source: {result.data_source_type}")
        
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
