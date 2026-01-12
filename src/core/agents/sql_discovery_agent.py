"""
SQL Discovery Agent - Phase 1 of Multi-Agent Architecture

Responsibilities:
- Load database schema and SQL generation guidance
- Generate and test SQL queries
- Save SQL results to artifacts
- Report what data was found and what needs API fetching

Output: SQLDiscoveryResult with found_data, needs_api, reasoning
"""

from pydantic_ai import Agent, RunContext, FunctionToolset, ToolReturn
from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Any, Dict
from dataclasses import dataclass
from pathlib import Path
import json
import time
import sqlite3
import asyncio

from src.utils.logging import get_logger
from src.core.security.sql_security_validator import validate_user_sql

logger = get_logger("okta_ai_agent")

# ============================================================================
# Output Models
# ============================================================================

class SQLDiscoveryResult(BaseModel):
    """Output from SQL Discovery Agent"""
    success: bool
    found_data: List[str] = Field(
        default_factory=list,
        description="Data found in DB: ['users', 'groups', 'apps']"
    )
    needs_api: List[str] = Field(
        default_factory=list,
        description="Data missing from DB: ['roles', 'mfa_factors']"
    )
    reasoning: str = Field(
        ...,
        description="Plain English: 'Found 3 users with apps/groups in DB. Roles not in schema - fetch via API.'"
    )
    error: Optional[str] = None


# ============================================================================
# Dependencies
# ============================================================================

@dataclass
class SQLDiscoveryDeps:
    """Dependencies for SQL Discovery Agent"""
    correlation_id: str
    artifacts_file: Path
    okta_client: Any  # OktaClient instance
    cancellation_check: callable
    
    # Streaming callbacks
    step_start_callback: Optional[callable] = None
    step_end_callback: Optional[callable] = None
    tool_call_callback: Optional[callable] = None  # For tool call notifications
    progress_callback: Optional[callable] = None  # For intermediate progress updates
    
    # State tracking
    sql_tests_executed: int = 0
    current_step: int = 0
    current_tools: List[Dict[str, str]] = None  # Track tools used in current step
    
    def __post_init__(self):
        """Initialize mutable default"""
        if self.current_tools is None:
            self.current_tools = []


# ============================================================================
# Helper Functions
# ============================================================================

def get_sqlite_schema_description() -> str:
    """Load database schema from centralized location"""
    from src.data.schemas.shared_schema import get_okta_database_schema
    return get_okta_database_schema()


async def dump_artifacts_to_file(artifacts_file: Path, artifacts: List[dict]):
    """Append artifacts to JSON file (not overwrite)"""
    try:
        # Load existing artifacts
        existing = []
        if artifacts_file.exists():
            try:
                with open(artifacts_file, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
                    # Handle case where file contains dict instead of list
                    if isinstance(existing, dict):
                        existing = [existing]
                    elif not isinstance(existing, list):
                        existing = []
            except json.JSONDecodeError:
                logger.warning(f"Could not parse existing artifacts, starting fresh")
                existing = []
        
        # Append new artifacts
        existing.extend(artifacts)
        
        # Save combined list
        with open(artifacts_file, 'w', encoding='utf-8') as f:
            json.dump(existing, f, indent=2, default=str)
        logger.debug(f"Artifacts appended to {artifacts_file}")
    except Exception as e:
        logger.error(f"Failed to save artifacts: {e}")


# ============================================================================
# SQL Discovery Agent Definition
# ============================================================================

# Load system prompt
PROMPT_FILE = Path(__file__).parent / "prompts" / "sql_discovery_prompt.txt"
try:
    with open(PROMPT_FILE, 'r', encoding='utf-8') as f:
        BASE_SYSTEM_PROMPT = f.read()
except FileNotFoundError:
    logger.error(f"SQL discovery prompt not found: {PROMPT_FILE}")
    BASE_SYSTEM_PROMPT = """You are a SQL query specialist for SQLite databases.
Generate queries to find data in the database, test them, and report findings."""


# Model selection (use coding model)
try:
    from src.core.models.model_picker import ModelConfig, ModelType
    model = ModelConfig.get_model(ModelType.CODING)
except ImportError:
    import os
    model = os.getenv('LLM_MODEL', 'openai:gpt-4o-mini')


# Create agent
sql_discovery_agent = Agent(
    model,
    instructions=BASE_SYSTEM_PROMPT,
    output_type=SQLDiscoveryResult,
    deps_type=SQLDiscoveryDeps,
    retries=0
)


# ============================================================================
# Tool Implementations
# ============================================================================

def create_sql_toolset(deps: SQLDiscoveryDeps) -> FunctionToolset:
    """Create SQL discovery tools"""
    toolset = FunctionToolset()
    
    # Track artifacts in memory
    if not hasattr(deps, 'artifacts'):
        deps.artifacts = []
    
    def check_cancellation():
        """Check if user cancelled execution"""
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
        """Notify orchestrator of step start with optional tool tracking"""
        if deps.step_start_callback:
            deps.current_step += 1
            
            # Track tool if provided
            if tool_name:
                deps.current_tools.append({"name": tool_name})
            
            await deps.step_start_callback({
                "step": deps.current_step,
                "title": title,
                "text": reasoning,
                "tools": deps.current_tools.copy(),  # Send copy of current tools
                "timestamp": time.time()
            })
    
    async def notify_step_end(title: str, result: str):
        """Notify orchestrator of step end and reset tools"""
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
    # Tool 1: Get SQL Context (Schema + Guidance)
    # ========================================================================
    
    async def get_sql_context(query_description: str) -> ToolReturn:
        """
        Load database schema and SQL generation guidance.
        
        CALL THIS ONCE at the start. Provides:
        - Complete table/column structure
        - Valid field values (status, factor types)
        - SQL query patterns (JOIN examples, filtering rules)
        
        Args:
            query_description: Brief description of what you need to query
        
        Returns:
            Schema + SQL patterns for query generation
        """
        check_cancellation()
        await notify_tool_call("get_sql_context", f"Loading SQL schema for: {query_description}")
        
        logger.info(f"[{deps.correlation_id}] Tool 1: Loading SQL context")
        
        # Load schema ONLY - the agent prompt already has SQL patterns
        schema_description = get_sqlite_schema_description()
        
        await notify_step_end(
            "Schema Loaded",
            f"Loaded {len(schema_description)} chars of database schema"
        )
        
        return ToolReturn(
            return_value="✅ SQL context loaded (schema)",
            content=schema_description
        )
    
    # ========================================================================
    # Helper: Truncate SQL Results (Token Optimization)
    # ========================================================================
    
    def truncate_sql_results(results: list, max_text_length: int = 100) -> list:
        """
        Truncate SQL results before sending to LLM to reduce token usage.
        
        Handles long CSV columns (e.g., 250 group names concatenated).
        Truncates text fields beyond max_text_length while preserving structure.
        
        Args:
            results: List of dict results from SQL query
            max_text_length: Maximum characters per text field (default 100)
        
        Returns:
            List of dicts with truncated text fields
        
        Example:
            Input: {"groups": "Group1,Group2,Group3,...,Group250"} (1000 chars)
            Output: {"groups": "Group1,Group2,Group3,Group4,Group5..."} (100 chars)
        """
        if not results:
            return results
        
        truncated = []
        for row in results:
            truncated_row = {}
            for key, value in row.items():
                if isinstance(value, str) and len(value) > max_text_length:
                    # Truncate and add ellipsis
                    truncated_row[key] = value[:max_text_length] + "..."
                else:
                    # Keep as-is
                    truncated_row[key] = value
            truncated.append(truncated_row)
        
        return truncated
    
    # ========================================================================
    # Tool 2: Execute SQL Test Query
    # ========================================================================
    
    async def execute_test_query(code: str) -> ToolReturn:
        """
        Execute SQL query against database (auto-limited to 3 results).
        
        Args:
            code: Pure SQL query (no Python wrapper)
        
        Returns:
            Sample results (3 rows max) with execution details
        """
        check_cancellation()
        
        await notify_tool_call("execute_test_query_sql", f"Testing SQL query on database (test #{deps.sql_tests_executed + 1})")
        
        deps.sql_tests_executed += 1
        if deps.sql_tests_executed > 5:
            return ToolReturn(
                return_value="❌ Test limit exceeded (5 tests max)",
                content="Stop testing. Finalize your conclusion with found_data and needs_api.",
                metadata={'error': True}
            )
        
        logger.info(f"[{deps.correlation_id}] Executing SQL test query #{deps.sql_tests_executed}")
        
        # Log the generated SQL query
        sql_query = code.strip()
        logger.info(f"[{deps.correlation_id}] 📝 Generated SQL:\n{sql_query}")
        
        # Security validation
        is_valid, error_msg = validate_user_sql(sql_query, deps.correlation_id)
        if not is_valid:
            logger.error(f"[{deps.correlation_id}] SQL validation failed: {error_msg}")
            await notify_step_end(
                "SQL Validation Failed",
                f"Security error: {error_msg}"
            )
            return ToolReturn(
                return_value=f"❌ SQL validation failed: {error_msg}",
                content=f"Security error: {error_msg}",
                metadata={'success': False, 'security_error': True}
            )
        
        # Auto-inject LIMIT 3
        import re
        if "LIMIT" in sql_query.upper():
            sql_query = re.sub(r'\s+LIMIT\s+\d+', '', sql_query, flags=re.IGNORECASE)
        sql_query = sql_query.strip().rstrip(';') + ' LIMIT 3'
        
        # Execute query
        try:
            import sqlite3
            from pathlib import Path
            
            db_paths = [
                Path("/app/sqlite_db/okta_sync.db"),
                Path("sqlite_db/okta_sync.db")
            ]
            db_path = next((p for p in db_paths if p.exists()), None)
            
            if not db_path:
                return ToolReturn(
                    return_value="❌ Database not found",
                    content="Database file not accessible",
                    metadata={'success': False, 'db_error': True}
                )
            
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            
            start_time = time.time()
            cursor.execute(sql_query)
            rows = cursor.fetchall()
            execution_time_ms = int((time.time() - start_time) * 1000)
            
            # Get column names
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            
            # Convert to dicts
            results = []
            for row in rows:
                results.append(dict(zip(columns, row)))
            
            conn.close()
            
            # Truncate long text fields to reduce token usage
            truncated_results = truncate_sql_results(results, max_text_length=100)
            
            # IMPORTANT: Do NOT auto-save here
            # LLM will explicitly call save_artifact() tool when results are validated
            # This allows testing multiple times without polluting artifacts with intermediate attempts
            
            result_summary = f"Found {len(results)} rows with {len(columns)} columns: {', '.join(columns)}"
            await notify_step_end(
                f"SQL Test #{deps.sql_tests_executed} Complete",
                result_summary
            )
            
            return ToolReturn(
                return_value=f"✅ SQL executed: {len(results)} rows",
                content=json.dumps(truncated_results, indent=2, default=str),
                metadata={
                    'success': True,
                    'row_count': len(results),
                    'columns': columns,
                    'execution_time_ms': execution_time_ms
                }
            )
            
        except Exception as e:
            logger.error(f"[{deps.correlation_id}] SQL execution failed: {e}")
            await notify_step_end(
                "SQL Execution Failed",
                f"Error: {str(e)}"
            )
            return ToolReturn(
                return_value=f"❌ SQL error: {str(e)}",
                content=f"Query failed: {str(e)}",
                metadata={'success': False, 'error': str(e)}
            )
    
    # ========================================================================
    # Tool 3: Save Artifact
    # ========================================================================
    
    async def save_artifact(
        key: str,
        category: Literal["sql_results", "schema_info", "discovered_data"],
        content: str,
        sql_query: Optional[str] = None,
        notes: Optional[str] = None
    ) -> ToolReturn:
        """
        Save important data to artifacts file.
        
        Use this to preserve:
        - SQL query results structure
        - The actual SQL query used (IMPORTANT: include sql_query parameter)
        - Field names discovered
        - Key findings for next agent
        """
        check_cancellation()
        
        artifact = {
            "key": key,
            "category": category,
            "content": content,
            "notes": notes or f"Saved by SQL agent at test #{deps.sql_tests_executed}",
            "timestamp": time.time()
        }
        
        # Add SQL query if provided (CRITICAL for synthesis agent)
        if sql_query:
            artifact["sql_query"] = sql_query
        
        deps.artifacts.append(artifact)
        await dump_artifacts_to_file(deps.artifacts_file, deps.artifacts)
        
        logger.info(f"[{deps.correlation_id}] Saved artifact: {key} ({len(content)} chars)")
        
        return ToolReturn(
            return_value=f"✅ Saved artifact: {key}",
            content=f"Artifact saved to {deps.artifacts_file}",
            metadata={'artifact_count': len(deps.artifacts)}
        )
    
    # ========================================================================
    # Tool 4: Notify Progress (for LLM to report progress to user)
    # ========================================================================
    
    async def notify_progress_to_user(
        ctx: RunContext[SQLDiscoveryDeps],
        message: str,
        details: str = ""
    ) -> str:
        """
        Report progress to the user. Call this to keep users informed of what you're doing.
        Use this for intermediate updates like "Executed query", "Found 10 users", etc.
        
        Args:
            message: Progress message (e.g., "Analyzing database schema")
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
    toolset.tool(get_sql_context)
    toolset.tool(execute_test_query)
    toolset.tool(save_artifact)
    toolset.tool(notify_progress_to_user)
    
    return toolset


# ============================================================================
# Main Execution Function
# ============================================================================

async def execute_sql_discovery(
    user_query: str,
    deps: SQLDiscoveryDeps
) -> SQLDiscoveryResult:
    """
    Execute SQL discovery phase.
    
    Args:
        user_query: Original user query
        deps: SQL discovery dependencies
    
    Returns:
        SQLDiscoveryResult with findings and API needs
    """
    logger.info(f"[{deps.correlation_id}] Starting SQL discovery phase")
    
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
    toolset = create_sql_toolset(deps)
    
    try:
        result = await sql_discovery_agent.run(
            user_query,
            deps=deps,
            toolsets=[toolset]  # Pass toolset to run()
        )
        
        logger.info(f"[{deps.correlation_id}] SQL discovery complete: found={result.output.found_data}, needs_api={result.output.needs_api}")
        
        # Notify frontend of completion
        await notify_step_end(
            "SQL Discovery Complete",
            f"Found data: {', '.join(result.output.found_data) if result.output.found_data else 'none'}. "
            f"Needs API: {', '.join(result.output.needs_api) if result.output.needs_api else 'none'}"
        )
        
        # Log token usage
        if result.usage():
            usage = result.usage()
            avg_per_call = usage.input_tokens / usage.requests if usage.requests > 0 else 0
            logger.info(
                f"[{deps.correlation_id}] 📊 SQL Agent Token Usage: "
                f"{usage.input_tokens:,} input, {usage.output_tokens:,} output, "
                f"{usage.total_tokens:,} total (across {usage.requests} API calls, "
                f"avg {avg_per_call:,.0f} input/call)"
            )
        
        return result.output, result.usage()
        
    except Exception as e:
        logger.error(f"[{deps.correlation_id}] SQL discovery failed: {e}", exc_info=True)
        return SQLDiscoveryResult(
            success=False,
            found_data=[],
            needs_api=[],
            reasoning=f"SQL discovery failed: {str(e)}",
            error=str(e)
        )
