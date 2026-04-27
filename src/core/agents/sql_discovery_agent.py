"""
SQL Discovery Agent - Phase 1 of Multi-Agent Architecture

Responsibilities:
- Load database schema and SQL generation guidance
- Generate and test SQL queries
- Save SQL results to artifacts
- Report what data was found and what needs API fetching

Output: SQLDiscoveryResult with found_data, needs_api, reasoning
"""

from pydantic_ai import RunContext, FunctionToolset, ModelRetry, ToolReturn, UsageLimits
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
from src.core.agents import DEFAULT_LOCAL_TOOL_CALL_TIMEOUT_SECONDS, build_agent
from src.core.models.model_picker import ModelType
from src.data.schemas.artifact_manifest import append_artifacts_with_result_sets

logger = get_logger("okta_ai_agent")

SQL_USAGE_LIMITS = UsageLimits(
    request_limit=10,
    tool_calls_limit=8,
)

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
    needs_api: Optional[List[str]] = Field(
        default=None,
        description="Data missing from DB: ['roles', 'mfa_factors']. Set to None to stop handoff."
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
    
    # API context (if API agent ran first)
    api_reasoning: Optional[str] = None  # Feedback from API agent (None if API phase skipped)
    api_discovered_data: Optional[str] = None  # JSON string of data API found (None if API phase skipped)
    api_needs_sql: Optional[List[str]] = None  # Structured list of entities to fetch via SQL
    api_found_data: Optional[List[str]] = None  # Structured list of entities already found via API
    
    # Streaming callbacks
    step_start_callback: Optional[callable] = None
    step_end_callback: Optional[callable] = None
    tool_call_callback: Optional[callable] = None  # For tool call notifications
    progress_callback: Optional[callable] = None  # For intermediate progress updates
    
    # Tool call limits (shared across all agents)
    global_tool_calls: int = 0  # Current count across all agents
    max_global_tool_calls: int = 30  # From env variable MAX_TOOL_CALLS
    
    # Per-tool limits (prevent infinite testing loops)
    sql_tests_executed: int = 0  # Max 3
    
    # State tracking
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


def find_sqlite_db_path() -> Optional[Path]:
    """Return the first available Okta SQLite database path."""
    for db_path in (
        Path("sqlite_db/okta_sync.db"),
        Path("okta_sync.db"),
        Path("../sqlite_db/okta_sync.db"),
        Path("/app/sqlite_db/okta_sync.db"),
    ):
        if db_path.exists():
            return db_path
    return None


def get_last_sync_timestamp() -> Optional[str]:
    """Get the last successful sync timestamp from the SQL database."""
    try:
        db_path = find_sqlite_db_path()
        if not db_path:
            return None

        with sqlite3.connect(db_path, timeout=5) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sync_history'")
            if not cursor.fetchone():
                return None

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

            timestamp_str = row[0]
            if "T" not in timestamp_str:
                timestamp_str = timestamp_str.replace(" ", "T") + "Z"
            return timestamp_str
    except Exception as e:
        logger.debug(f"Could not retrieve last sync timestamp: {e}")
        return None


def get_database_runtime_summary() -> Dict[str, Any]:
    """Return compact DB availability and population details for supervisor routing."""
    summary: Dict[str, Any] = {
        "available": False,
        "usable_for_sql": False,
        "db_path": None,
        "table_counts": {},
        "missing_key_tables": [],
        "last_sync_time": None,
        "reason": None,
    }

    key_tables = (
        "users",
        "groups",
        "applications",
        "user_group_memberships",
        "user_application_assignments",
        "group_application_assignments",
    )

    try:
        db_path = find_sqlite_db_path()
        if not db_path:
            summary["reason"] = "Database file not found in expected locations."
            return summary

        summary["available"] = True
        summary["db_path"] = str(db_path)
        with sqlite3.connect(db_path, timeout=5) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            existing_tables = {row[0] for row in cursor.fetchall()}

            table_counts: Dict[str, int] = {}
            missing_tables: List[str] = []
            for table_name in key_tables:
                if table_name not in existing_tables:
                    missing_tables.append(table_name)
                    continue
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                table_counts[table_name] = int(cursor.fetchone()[0])

            summary["table_counts"] = table_counts
            summary["missing_key_tables"] = missing_tables
            summary["usable_for_sql"] = table_counts.get("users", 0) > 0
            summary["last_sync_time"] = get_last_sync_timestamp()
            if not summary["usable_for_sql"]:
                summary["reason"] = "Users table is missing or empty."
            else:
                summary["reason"] = "Database has populated local Okta entities."

            return summary
    except Exception as e:
        summary["reason"] = f"Database summary failed: {e}"
        return summary


def check_database_health() -> bool:
    """Return True when the local SQL database is usable for discovery."""
    try:
        db_path = find_sqlite_db_path()
        if not db_path:
            logger.warning("Database file not found in any expected location - Skipping SQL phase")
            return False

        with sqlite3.connect(db_path, timeout=5) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
            if not cursor.fetchone():
                logger.warning("Users table not found in database - Skipping SQL phase")
                return False

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


async def dump_artifacts_to_file(artifacts_file: Path, artifacts: List[dict]):
    """Append artifacts to JSON file (not overwrite)"""
    try:
        append_artifacts_with_result_sets(artifacts_file, artifacts, source_specialist="sql")
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


# Create agent
sql_discovery_agent = build_agent(
    ModelType.CODING,
    name="sql_discovery_agent",
    instructions=BASE_SYSTEM_PROMPT,
    output_type=SQLDiscoveryResult,
    deps_type=SQLDiscoveryDeps,
)


@sql_discovery_agent.output_validator
def validate_sql_discovery_output(
    ctx: RunContext[SQLDiscoveryDeps],
    result: SQLDiscoveryResult,
) -> SQLDiscoveryResult:
    """Reject contradictory outputs and require saved artifacts for successful discovery."""
    artifacts = getattr(ctx.deps, "artifacts", []) or []

    if result.needs_api == []:
        result.needs_api = None

    if result.success:
        if result.error:
            raise ModelRetry("Successful SQL discovery output cannot include an error")
        if not artifacts:
            raise ModelRetry(
                "Successful SQL discovery must save at least one artifact with save_artifact before finishing"
            )
        return result

    if not result.error:
        raise ModelRetry("Failed SQL discovery output must include an error message")

    if result.found_data:
        raise ModelRetry("Failed SQL discovery output cannot claim found_data")

    if result.needs_api:
        raise ModelRetry("Failed SQL discovery output cannot request API handoff")

    return result


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
        
        # Enforce global tool call limit
        deps.global_tool_calls += 1
        if deps.global_tool_calls > deps.max_global_tool_calls:
            raise RuntimeError(
                f"Global tool call limit exceeded ({deps.global_tool_calls}/{deps.max_global_tool_calls}). "
                f"Cannot execute further tools. Adjust MAX_TOOL_CALLS environment variable if needed."
            )
        
        await notify_tool_call("get_sql_context", f"Loading SQL schema for: {query_description}")
        
        logger.info(f"[{deps.correlation_id}] Tool 1: Loading SQL context (global: {deps.global_tool_calls}/{deps.max_global_tool_calls})")
        
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
    
    async def execute_test_query(code: str, description: str = "Testing SQL query") -> ToolReturn:
        """
        Execute SQL query against database (auto-limited to 3 results).
        
        Args:
            code: Pure SQL query (no Python wrapper)
            description: Brief description of what this query tests (e.g., "Find users in group X")
        
        Returns:
            Sample results (3 rows max) with execution details
        """
        check_cancellation()
        
        # Enforce tool call limits
        deps.global_tool_calls += 1
        deps.sql_tests_executed += 1
        
        # Check global limit
        if deps.global_tool_calls > deps.max_global_tool_calls:
            raise RuntimeError(
                f"Global tool call limit exceeded ({deps.global_tool_calls}/{deps.max_global_tool_calls}). "
                f"Cannot execute further tools. Adjust MAX_TOOL_CALLS environment variable if needed."
            )
        
        # Check per-tool limit
        if deps.sql_tests_executed > 10:
            raise RuntimeError(
                f"SQL test query limit exceeded ({deps.sql_tests_executed}/10). "
                f"Stop testing and finalize your conclusion with found_data and needs_api."
            )
        
        await notify_tool_call("execute_test_query_sql", description)
        
        logger.info(f"[{deps.correlation_id}] Executing SQL test query #{deps.sql_tests_executed} (global: {deps.global_tool_calls}/{deps.max_global_tool_calls}, sql_tests: {deps.sql_tests_executed}/10)")
        
        # Log the generated SQL query
        sql_query = code.strip()
        logger.info(f"[{deps.correlation_id}] Generated SQL:\n{sql_query}")
        
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
            
            db_path = find_sqlite_db_path()

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
            # NOTE: Don't call notify_step_end here - this is a recoverable error
            # The LLM will see the error in ToolReturn and can retry or adjust
            # Only call notify_step_end for successful operations or terminating failures
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
        
        # Truncate content if it's JSON with long text fields
        # This prevents artifacts from bloating with 100+ concatenated group names, etc.
        truncated_content = content
        if category == "sql_results":
            try:
                data = json.loads(content)
                if isinstance(data, list):
                    truncated_data = truncate_sql_results(data, max_text_length=100)
                    truncated_content = json.dumps(truncated_data, indent=2, default=str)
            except (json.JSONDecodeError, TypeError):
                # Not JSON or can't parse - save as-is
                pass
        
        artifact = {
            "key": key,
            "category": category,
            "content": truncated_content,
            "notes": notes or f"Saved by SQL agent at test #{deps.sql_tests_executed}",
            "timestamp": time.time()
        }
        
        # Add SQL query if provided (CRITICAL for synthesis agent)
        if sql_query:
            artifact["sql_query"] = sql_query
        
        deps.artifacts.append(artifact)
        await dump_artifacts_to_file(deps.artifacts_file, [artifact])
        
        logger.info(f"[{deps.correlation_id}] Saved artifact: {key} ({len(content)} chars)")
        
        return ToolReturn(
            return_value=f"✅ Saved artifact: {key}",
            content=f"Artifact saved to {deps.artifacts_file}",
            metadata={'artifact_count': len(deps.artifacts)}
        )
    
    # Register tools
    toolset.add_function(
        get_sql_context,
        timeout=DEFAULT_LOCAL_TOOL_CALL_TIMEOUT_SECONDS,
    )
    toolset.add_function(
        execute_test_query,
        timeout=DEFAULT_LOCAL_TOOL_CALL_TIMEOUT_SECONDS,
    )
    toolset.add_function(
        save_artifact,
        retries=1,
        timeout=DEFAULT_LOCAL_TOOL_CALL_TIMEOUT_SECONDS,
    )
    
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
        # Build dynamic prompt: base query + optional API context
        # Following same pattern as API agent: clean static prompt + dynamic extension
        full_prompt = user_query
        
        # Dynamically extend prompt ONLY if API phase ran first and found data
        # If API phase ran, inject its discovered data as context
        if deps.api_reasoning and deps.api_discovered_data:
            # Format structured lists
            needs_sql_str = str(deps.api_needs_sql) if deps.api_needs_sql else "[]"
            found_data_str = str(deps.api_found_data) if deps.api_found_data else "[]"
            
            full_prompt = f"""{user_query}

─────────────────────────────────────────
📊 DATA ALREADY RETRIEVED FROM API
─────────────────────────────────────────

🎯 YOUR SCOPE - FETCH ONLY:
{needs_sql_str}

✅ ALREADY FOUND (DO NOT QUERY):
{found_data_str}

API Agent Analysis:
{deps.api_reasoning}

Compact API Artifact Context (manifests, result refs, tiny samples):
```json
{deps.api_discovered_data}
```

🚨 CRITICAL RULES:
1. **ONLY query for entities listed in YOUR SCOPE** - If it says ['users'], query ONLY users
2. **DO NOT query for anything in ALREADY FOUND list** - No need to fetch what API already got
3. **Use JOINs if needed** - If scope needs related data, use proper JOINs
4. **One test per entity type** - If scope says ['users'], make 1 test for users
─────────────────────────────────────────
"""
        # else: SQL-only mode - prompt stays clean with just the user query
        
        result = await sql_discovery_agent.run(
            full_prompt,
            deps=deps,
            toolsets=[toolset],
            usage_limits=SQL_USAGE_LIMITS,
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
                f"[{deps.correlation_id}] SQL Agent Token Usage: "
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
        ), None  # Return tuple with None usage
