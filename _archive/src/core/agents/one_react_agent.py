"""
ReAct Agent for Okta Query Execution
Single agent with 7 tools for reasoning and acting on hybrid SQLite + API queries

This agent follows the ReAct (Reasoning + Acting) pattern:
1. Reason about what data is needed
2. Act by calling tools to gather information
3. Observe results and decide next steps
4. Repeat until query is answered or max retries exceeded
"""

from pydantic_ai import Agent, RunContext, FunctionToolset, ModelMessage, ToolReturn, UsageLimits
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Literal
from dataclasses import dataclass
import json
import os
import time
import asyncio
import re
from pathlib import Path

from src.utils.logging import get_logger, get_default_log_dir

# Security validators
from src.utils.security_config import validate_generated_code
from src.core.security.sql_security_validator import validate_user_sql
from src.core.security.network_security import validate_request

# Setup centralized logging
logger = get_logger("okta_ai_agent", log_dir=get_default_log_dir())

# Use the model picker approach for consistent model configuration
try:
    from src.core.models.model_picker import ModelConfig, ModelType
    model = ModelConfig.get_model(ModelType.CODING)
except ImportError:
    # Fallback to simple model configuration
    logger.warning("Could not import model_picker, using fallback model configuration")
    model = os.getenv('LLM_MODEL', 'openai:gpt-4o-mini')

# ============================================================================
# Lightweight JSON Generation for One React Agent
# ============================================================================

def generate_lightweight_onereact_json(force_regenerate: bool = False) -> Dict[str, Any]:
    """
    Generate a minimal lightweight JSON structure for one_react_agent.
    Uses simple dot notation: entity.operation (e.g., "application.list")
    
    This structure is optimized for small LLMs:
    - Flat array of strings with dot notation
    - No nested objects to parse
    - Minimal token count
    - Easy to filter by splitting on '.'
    
    Args:
        force_regenerate: If True, regenerate even if file exists
        
    Returns:
        Dict with 'operations' (list of strings) and 'sql_tables' (list of strings)
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
        return {"operations": [], "sql_tables": []}
    
    try:
        with open(source_path, 'r', encoding='utf-8') as f:
            source_data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load source file: {e}")
        return {"operations": [], "sql_tables": []}
    
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
    
    # Create minimal structure (API operations only - SQL schema is separate in shared_schema.py)
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

# ============================================================================
# Database Health Check
# ============================================================================

def check_database_health() -> bool:
    """
    Check if the SQLite database exists and is populated with users.
    
    Returns:
        bool: True if database exists and has users (>= 1), False otherwise
    """
    import sqlite3
    
    try:
        # Try multiple possible database locations
        possible_db_paths = [
            os.path.join(os.getcwd(), 'sqlite_db', 'okta_sync.db'),
            os.path.join(Path(__file__).parent.parent.parent.parent, 'sqlite_db', 'okta_sync.db'),
            'sqlite_db/okta_sync.db'
        ]
        
        db_path = None
        for path in possible_db_paths:
            if os.path.exists(path):
                db_path = path
                break
        
        if not db_path:
            logger.warning("Database file not found in any expected location - API-only mode will be used")
            return False
        
        # Check if database is accessible and has users
        with sqlite3.connect(db_path, timeout=5) as conn:
            cursor = conn.cursor()
            
            # Check if users table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
            if not cursor.fetchone():
                logger.warning("Users table not found in database - API-only mode will be used")
                return False
            
            # Check if users table has at least 1 record
            cursor.execute("SELECT COUNT(*) FROM users")
            user_count = cursor.fetchone()[0]
            
            logger.info(f"Database health check: Found {user_count} users in database")
            return user_count >= 1
            
    except Exception as e:
        logger.warning(f"Database health check failed: {e} - API-only mode will be used")
        return False

def should_force_api_only_mode(query: str, force_api_only: bool = False) -> tuple[bool, str]:
    """
    Determine if query should use API-only mode and modify query if needed.
    
    Args:
        query: Original user query
        force_api_only: Flag from frontend to force API-only mode
        
    Returns:
        tuple: (should_use_api_only, modified_query)
    """
    # Check for explicit API-only requests in query
    api_only_phrases = [
        "do not use sql",
        "don't use sql", 
        "no sql",
        "api only",
        "apis only",
        "api calls only",
        "without using sql"
    ]
    
    query_lower = query.lower()
    explicit_api_only = any(phrase in query_lower for phrase in api_only_phrases)
    
    # Check database health
    db_healthy = check_database_health()
    
    # Decision logic
    should_force_api = force_api_only or explicit_api_only or not db_healthy
    
    # Modify query if forcing API-only mode
    modified_query = query
    if should_force_api and not explicit_api_only:
        # Add API-only instruction to query
        modified_query = f"{query}. IMPORTANT: Do NOT use SQL - ONLY use API calls to gather data."
        
    # Log decision
    if should_force_api:
        reasons = []
        if force_api_only:
            reasons.append("frontend flag")
        if explicit_api_only:
            reasons.append("explicit user request")
        if not db_healthy:
            reasons.append("database unavailable/empty")
        
        logger.info(f"[ReAct] API-only mode activated: {', '.join(reasons)}")
        if modified_query != query:
            logger.info(f"[ReAct] Modified query to enforce API-only mode")
    else:
        logger.info("[ReAct] SQL and API modes both available")
        
    return should_force_api, modified_query

# ============================================================================
# Schema Helper Function
# ============================================================================

def get_sqlite_schema_description() -> str:
    """
    Generate a comprehensive LLM-optimized description of the SQLite database schema.
    Uses the centralized shared schema definition.
    
    Returns:
        Formatted schema description string with complete table details
    """
    from src.data.schemas.shared_schema import get_okta_database_schema
    return get_okta_database_schema()

# ============================================================================
# Knowledge Artifact Model (must be defined before ReactAgentDependencies)
# ============================================================================

class KnowledgeArtifact(BaseModel):
    """Represents verified knowledge saved during agent execution"""
    key: str = Field(..., description="Unique identifier (e.g., 'fetch_groups_code')")
    category: Literal["code_logic", "schema_definition", "discovered_data", "error_pattern", "user_intent"] = Field(
        ..., description="Type of knowledge"
    )
    content: str = Field(..., description="The actual content (code snippet, JSON sample, ID list)")
    notes: Optional[str] = Field(None, description="Contextual notes for the agent")
    timestamp: float = Field(default_factory=time.time)

# ============================================================================
# Dependencies (Dataclass for PydanticAI)
# ============================================================================

@dataclass
class ReactAgentDependencies:
    """Dependencies injected into ReAct agent"""
    correlation_id: str
    endpoints: List[Dict[str, Any]]  # Full endpoint details (for Tool 3)
    lightweight_entities: Dict[str, Any]  # Lightweight entity-operation mapping (for Tool 2)
    okta_client: Any  # OktaClient instance
    sqlite_connection: Any  # SQLite connection
    operation_mapping: Dict[str, Any]
    user_query: str  # Original user query for context
    progress_callback: Optional[Any] = None  # Optional callback for progress updates
    
    # NEW: SSE streaming callbacks for real-time UI updates
    step_start_callback: Optional[callable] = None  # Called when a discovery step starts
    step_end_callback: Optional[callable] = None    # Called when a discovery step completes
    step_tokens_callback: Optional[callable] = None # Called to report token usage per step
    tool_call_callback: Optional[callable] = None   # Called when a tool is invoked
    
    # NEW: Cancellation check callback
    cancellation_check: Optional[callable] = None   # Called to check if execution should stop
    
    # Circuit breaker counters for tool execution limits (execution only, not discovery)
    sql_execution_count: int = 0
    api_execution_count: int = 0
    
    # Circuit breaker limits (configurable via environment variables)
    MAX_SQL_EXECUTIONS: int = int(os.getenv('REACT_AGENT_MAX_SQL_EXECUTIONS', '5'))
    MAX_API_EXECUTIONS: int = int(os.getenv('REACT_AGENT_MAX_API_EXECUTIONS', '20'))
    
    # Knowledge artifacts storage (for LLM-generated summaries)
    artifacts: List[Dict] = None  # Initialized on first save
    session_id: str = ""  # Session ID for artifact file naming

# ============================================================================
# Structured Outputs
# ============================================================================

class ExecutionResult(BaseModel):
    """Final execution result from ReAct agent"""
    success: bool
    results: Optional[Any] = None
    display_type: Literal["table", "markdown", "json"] = Field(
        default="markdown", 
        description="Format to display results: 'table' for list of records, 'markdown' for text/summary"
    )
    execution_plan: str
    steps_taken: List[str]
    error: Optional[str] = None
    complete_production_code: str = ""  # REQUIRED: The final, complete, runnable Python script to reproduce results

# ============================================================================
# History Compression (Phase 2 - Token Optimization)
# ============================================================================

async def compress_history(ctx: RunContext[ReactAgentDependencies], messages: list[ModelMessage]) -> list[ModelMessage]:
    """
    History Processor: Smart compression using Utilization Trigger + Deduplication.
    
    Key principles:
    1. Utilization Trigger: Only compress after LLM has USED the data (executed test queries)
    2. Deduplication: Keep only the LAST occurrence of each heavy tool
    3. Artifact-Based Phase Detection: Delete SQL tools after sql_results saved
    4. Safety: Never compress the last message
    """
    deps = ctx.deps
    
    # Track tokens per call (using cumulative usage from context)
    if not hasattr(compress_history, '_last_tokens'):
        compress_history._last_tokens = 0
    if not hasattr(compress_history, '_call_count'):
        compress_history._call_count = 0
    
    current_total = ctx.usage.input_tokens if ctx.usage else 0
    current_calls = ctx.usage.requests if ctx.usage else 0
    
    # Log token usage per call
    if current_calls > compress_history._call_count:
        incremental = current_total - compress_history._last_tokens
        if incremental > 0:
            logger.info(
                f"[{deps.correlation_id}] 📊 Call #{current_calls}: "
                f"+{incremental:,} tokens (cumulative: {current_total:,} input)"
            )
        compress_history._last_tokens = current_total
        compress_history._call_count = current_calls
    
    # PHASE 1: Check completion status from artifacts
    sql_phase_complete = any(a['category'] == 'sql_results' for a in (deps.artifacts or []))
    api_endpoints_loaded = any(a['category'] == 'api_endpoints' for a in (deps.artifacts or []))
    api_phase_complete = any(a['category'] == 'api_response' for a in (deps.artifacts or []))
    
    # PHASE 2: Utilization Trigger - has LLM executed test queries?
    has_executed_query = False
    for msg in messages:
        if hasattr(msg, 'parts'):
            for part in msg.parts:
                if hasattr(part, 'tool_name') and part.tool_name == "execute_test_query":
                    has_executed_query = True
                    break
        if has_executed_query:
            break
    
    if not has_executed_query:
        return messages  # Don't compress until LLM has used the data
    
    # PHASE 3: Track tool call/result pairs for deletion
    # Structure: {tool_name: [(call_idx, result_idx), ...]}
    tool_pairs = {
        'get_sql_context': [],
        'load_comprehensive_api_endpoints': [],
        'filter_endpoints_by_operations': [],
        'get_api_code_generation_prompt': [],
        'execute_test_query_sql': [],
        'execute_test_query_api': []
    }
    
    # Build map of tool_call_id -> (call_idx, tool_name)
    # Tool CALLS have ToolCallPart with tool_name and tool_call_id
    call_id_to_info = {}
    for i, msg in enumerate(messages[:-1]):  # Exclude last message (safety)
        if hasattr(msg, 'parts'):
            for part in msg.parts:
                # ToolCallPart has: tool_name, args, tool_call_id
                if hasattr(part, 'tool_name') and hasattr(part, 'tool_call_id') and hasattr(part, 'args'):
                    call_id_to_info[part.tool_call_id] = (i, part.tool_name, part.args)
    
    # Now find tool RESULTS and pair them with their calls
    # Tool RESULTS have ToolReturnPart with tool_call_id (but no tool_name)
    for i, msg in enumerate(messages[:-1]):
        if hasattr(msg, 'parts'):
            for part in msg.parts:
                # ToolReturnPart has: tool_call_id, content, timestamp
                # It does NOT have tool_name - we get that from the call
                if hasattr(part, 'tool_call_id') and hasattr(part, 'content'):
                    tool_call_id = part.tool_call_id
                    
                    # Find the corresponding call message
                    call_info = call_id_to_info.get(tool_call_id)
                    if call_info is None:
                        continue  # Call not found, skip
                    
                    call_idx, tool_name, args = call_info
                    result_idx = i
                    
                    # Track by tool type
                    if tool_name in tool_pairs:
                        tool_pairs[tool_name].append((call_idx, result_idx))
                    
                    # Special handling for execute_test_query
                    elif tool_name == 'execute_test_query':
                        # Check args to distinguish SQL vs API
                        args_str = str(args)
                        
                        if 'sqlite' in args_str.lower() or 'sql' in args_str.lower():
                            tool_pairs['execute_test_query_sql'].append((call_idx, result_idx))
                        else:
                            tool_pairs['execute_test_query_api'].append((call_idx, result_idx))
    
    # PHASE 4: Determine what to delete based on completion status
    deletable_indices = set()
    
    # Helper to add both call and result indices
    def delete_pairs(pairs):
        for call_idx, result_idx in pairs:
            deletable_indices.add(call_idx)
            deletable_indices.add(result_idx)
    
    # CRITICAL RULE: Only delete data after SUCCESSFUL artifact save
    # Failed attempts mean LLM still needs the data to retry!
    
    # Delete SQL schema ONLY after SQL phase successfully complete (artifact saved)
    if sql_phase_complete and tool_pairs['get_sql_context']:
        delete_pairs(tool_pairs['get_sql_context'])
    
    # Delete SQL test executions ONLY after successful SQL artifact saved
    if sql_phase_complete and tool_pairs['execute_test_query_sql']:
        delete_pairs(tool_pairs['execute_test_query_sql'])
    
    # Delete API endpoints ONLY after endpoints loaded and successfully filtered
    if api_endpoints_loaded and tool_pairs['load_comprehensive_api_endpoints']:
        delete_pairs(tool_pairs['load_comprehensive_api_endpoints'])
    
    # Delete endpoint filters (keep only last if multiple successful calls)
    if len(tool_pairs['filter_endpoints_by_operations']) > 1:
        delete_pairs(tool_pairs['filter_endpoints_by_operations'][:-1])
    
    # Delete API code prompt ONLY after API phase complete (artifact saved)
    if api_phase_complete and tool_pairs['get_api_code_generation_prompt']:
        delete_pairs(tool_pairs['get_api_code_generation_prompt'])
    
    # PHASE 5: Filter messages (remove deletable indices)
    compressed = [msg for i, msg in enumerate(messages) if i not in deletable_indices]
    
    # Log compression results
    if len(compressed) < len(messages):
        deleted_count = len(messages) - len(compressed)
        logger.info(f"[{deps.correlation_id}] 🗑️ Compressed {deleted_count} messages: {len(messages)} → {len(compressed)}")
        logger.info(f"[{deps.correlation_id}] 📦 Phases: SQL={'✅' if sql_phase_complete else '⏳'}, API={'✅' if api_phase_complete else '⏳'}")
    
    return compressed

# ============================================================================
# Artifact Helper Function
# ============================================================================

async def dump_artifacts_to_file(session_id: str, artifacts: List[Dict]):
    """
    Persist artifacts to disk for crash recovery and debugging.
    
    Args:
        session_id: Correlation ID for the session
        artifacts: List of artifact dictionaries to save
    """
    try:
        artifacts_dir = Path("logs")
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        
        artifacts_file = artifacts_dir / f"artifacts_{session_id}.json"
        
        with open(artifacts_file, 'w', encoding='utf-8') as f:
            json.dump(artifacts, f, indent=2)
        
        logger.debug(f"[{session_id}] Artifacts persisted to {artifacts_file}")
    except Exception as e:
        logger.warning(f"[{session_id}] Failed to persist artifacts: {e}")

# ============================================================================
# Tool Implementations
# ============================================================================

def create_react_toolset(deps: ReactAgentDependencies) -> FunctionToolset:
    """Create function toolset with all 9 tools for the ReAct agent"""
    
    toolset = FunctionToolset()
    
    # Helper to notify frontend of tool calls
    async def notify_tool_call(tool_name: str, tool_description: str):
        """Send tool call notification via SSE callback"""
        if hasattr(deps, 'tool_call_callback') and deps.tool_call_callback:
            await deps.tool_call_callback({
                "tool_name": tool_name,
                "description": tool_description,
                "timestamp": time.time()
            })
    
    # ========================================================================
    # Helper: Check Cancellation
    # ========================================================================
    
    def check_cancellation():
        """Check if execution should be cancelled"""
        if deps.cancellation_check and deps.cancellation_check():
            logger.warning(f"[{deps.correlation_id}] 🛑 Execution cancelled by user during tool execution")
            raise asyncio.CancelledError("Execution cancelled by user")

    # ========================================================================
    # Tool 1: Get SQL Context (Combined Schema + Code Generation Guidance)
    # ========================================================================
    
    async def get_sql_context(
        ctx: RunContext[ReactAgentDependencies],
        query_description: str,
        limit: int = 3
    ) -> ToolReturn:
        """
        Get complete SQL context: database schema + code generation guidance.
        This combines schema and generation rules in one call.
        
        Call this when you need to write SQL queries. It provides:
        1. Database schema (tables, columns, relationships)
        2. SQL code generation rules and best practices
        
        Args:
            query_description: Natural language description of what to query
            limit: Number of records to return (default 3 for testing)
        
        Returns:
            ToolReturn with schema + guidance combined
        """
        check_cancellation()
        await notify_tool_call("get_sql_context", "Loading SQL schema and generation guidance")
        logger.info(f"[{deps.correlation_id}] Tool 1: Loading SQL context (schema + guidance)")
        
        try:
            # 1. Get database schema
            schema_text = get_sqlite_schema_description()
            
            # 2. Load SQL generation prompt from file
            sql_prompt_file = Path(__file__).parent / "prompts" / "sql_code_gen_react_agent_system_prompt.txt"
            try:
                with open(sql_prompt_file, 'r', encoding='utf-8') as f:
                    sql_prompt = f.read()
            except FileNotFoundError:
                sql_prompt = """Generate a SQLite-compatible SQL query.
            
Rules:
- Use proper SELECT, FROM, JOIN syntax
- Always include LIMIT clause for safety
- Use proper table names from the schema below
- Use proper column names from the schema below
- Return only the data requested
"""
            
            # 3. Combine schema + guidance into single context
            combined_context = f"""
=== DATABASE SCHEMA ===
{schema_text}

=== SQL CODE GENERATION GUIDANCE ===
{sql_prompt}

=== YOUR TASK ===
Query Description: {query_description}
Test Limit: {limit} rows

Now write your SQL query using the schema above.
"""
            
            return ToolReturn(
                return_value=f"✅ SQL context loaded: schema + guidance (limit: {limit})",
                content=combined_context,
                metadata={
                    'schema_loaded': True,
                    'guidance_loaded': True,
                    'limit': limit,
                    'query_description': query_description,
                    'timestamp': time.time()
                }
            )
        except Exception as e:
            logger.error(f"[{deps.correlation_id}] Failed to load SQL context: {e}", exc_info=True)
            return ToolReturn(
                return_value=f"❌ SQL context load failed: {str(e)}",
                content=f"Error loading SQL context: {str(e)}",
                metadata={'schema_loaded': False, 'error': str(e)}
            )
    
    # ========================================================================
    # Tool 2: Load Comprehensive API Endpoints
    # ========================================================================
    
    async def load_comprehensive_api_endpoints(ctx: RunContext[ReactAgentDependencies]) -> Dict[str, Any]:
        """
        Load lightweight summary of all API entities and operations.
        Returns operations in simple dot notation (e.g., "application.list", "user.get").
        
        Returns:
            Dictionary with operations list (in entity.operation format)
        """
        check_cancellation()
        await notify_tool_call("load_comprehensive_api_endpoints", "Loading API endpoints catalog")
        logger.info(f"[{deps.correlation_id}] Tool 2: Loading comprehensive API endpoints (lightweight)")
        
        # Handle both old format (entity-grouped dict) and new format (operations list)
        if isinstance(deps.lightweight_entities, dict):
            # Check if it's the new format with "operations" key
            if 'operations' in deps.lightweight_entities:
                # New minimal format: {"operations": ["entity.operation", ...], "sql_tables": [...]}
                operations = deps.lightweight_entities.get('operations', [])
                
                # Group by entity for easier browsing
                entities_grouped = {}
                for op in operations:
                    if '.' in op:
                        entity, operation = op.split('.', 1)
                        if entity not in entities_grouped:
                            entities_grouped[entity] = []
                        entities_grouped[entity].append(operation)
                
                result = {
                    "operations": operations,  # Full list in dot notation
                    "entities": entities_grouped,  # Grouped by entity for easier browsing
                    "total_entities": len(entities_grouped),
                    "total_operations": len(operations),
                    "format": "dot_notation"
                }
            else:
                # Old format: {"entity_name": {"operations": [...], "methods": [...]}}
                result_entities = {}
                for entity_name, entity_data in deps.lightweight_entities.items():
                    result_entities[entity_name] = {
                        'operations': entity_data.get('operations', []),
                        'methods': entity_data.get('methods', ['GET']),
                        'operation_count': len(entity_data.get('operations', []))
                    }
                
                result = {
                    "entities": result_entities,
                    "total_entities": len(result_entities),
                    "total_operations": sum(e['operation_count'] for e in result_entities.values()),
                    "format": "entity_grouped"
                }
        else:
            # Fallback for unexpected format
            result = {
                "entities": {},
                "total_entities": 0,
                "total_operations": 0,
                "format": "unknown",
                "error": "Unexpected lightweight_entities format"
            }
        
        logger.info(f"[{deps.correlation_id}] Loaded {result['total_entities']} entities with {result['total_operations']} operations (format: {result.get('format')})")
        
        return ToolReturn(
            return_value=f"✅ API endpoints loaded: {result['total_entities']} entities, {result['total_operations']} operations",
            content=json.dumps(result, separators=(',', ':')),
            metadata={'endpoints_loaded': True, 'total_operations': result['total_operations']}
        )
    
    # ========================================================================
    # Tool 3: Filter Endpoints by Operations
    # ========================================================================
    
    async def filter_endpoints_by_operations(
        operation_names: List[str]
    ) -> Dict[str, Any]:
        """
        Get full details for specific operations (e.g., ["application.list", "user.get"]).
        Call this AFTER Tool 2 to get the exact URL, method, and parameters for the operations you need.
        
        Args:
            operation_names: List of operation strings (e.g., ["application.list"])
        
        Returns:
            Detailed endpoint definitions for the requested operations
        """
        check_cancellation()
        await notify_tool_call("filter_endpoints_by_operations", f"Filtering endpoints: {operation_names}")
        
        logger.info(f"[{deps.correlation_id}] Tool 3: Filtering endpoints for operations: {operation_names}")
        
        selected_endpoints = []
        
        # Parse operation_names to extract entity and operation pairs
        # Supports: "entity.operation", "operation", or "entity_operation"
        search_pairs = []
        for op_name in operation_names:
            if '.' in op_name:
                # Dot notation: "application_credential.list_keys"
                parts = op_name.split('.', 1)
                if len(parts) == 2:
                    search_pairs.append((parts[0], parts[1]))
            else:
                # Plain operation or compound format - search by operation only
                search_pairs.append((None, op_name))
        
        # Match endpoints by entity + operation
        for endpoint in deps.endpoints:
            endpoint_entity = endpoint.get('entity', '')
            endpoint_operation = endpoint.get('operation', '')
            
            # Check if this endpoint matches any search pair
            for search_entity, search_operation in search_pairs:
                if search_entity:
                    # Entity specified - must match both
                    if endpoint_entity == search_entity and endpoint_operation == search_operation:
                        # Security validation
                        from src.core.security import validate_api_endpoint
                        security_result = validate_api_endpoint(endpoint)
                        if security_result.is_valid:
                            selected_endpoints.append(endpoint)
                        else:
                            logger.warning(f"Endpoint filtered for security: {endpoint.get('id', 'unknown')} - {'; '.join(security_result.violations)}")
                        break  # Found match, move to next endpoint
                else:
                    # No entity specified - match by operation only
                    if endpoint_operation == search_operation:
                        # Security validation
                        from src.core.security import validate_api_endpoint
                        security_result = validate_api_endpoint(endpoint)
                        if security_result.is_valid:
                            selected_endpoints.append(endpoint)
                        else:
                            logger.warning(f"Endpoint filtered for security: {endpoint.get('id', 'unknown')} - {'; '.join(security_result.violations)}")
                        break  # Found match, move to next endpoint
        
        operations_found = [f"{ep.get('entity')}.{ep.get('operation')}" for ep in selected_endpoints]
        
        logger.info(f"[{deps.correlation_id}] Found {len(selected_endpoints)} endpoints for {len(operation_names)} operation queries")
        
        return ToolReturn(
            return_value=f"✅ Filtered {len(selected_endpoints)} endpoints for {len(operation_names)} operations",
            content=json.dumps(selected_endpoints, separators=(',', ':')),
            metadata={'filtered_count': len(selected_endpoints), 'operations_found': operations_found}
        )
    
    # ========================================================================
    # Tool 4: Get API Code Generation Prompt (NOT a code generator!)
    # ========================================================================
    
    async def get_api_code_generation_prompt(
        query_description: str,
        endpoints: List[str],
        max_results: int = 3
    ) -> ToolReturn:
        """
        Get the prompt template for generating Python API code.
        The ReAct agent itself will generate the code using this guidance.
        
        Args:
            query_description: Natural language description of what to fetch
            endpoints: List of operation names (e.g., ["group.list", "user.get"])
            max_results: Maximum number of records to return (default 3 for testing)
        
        Returns:
            ToolReturn with code generation prompt and guidelines
        """
        check_cancellation()
        await notify_tool_call("get_api_code_generation_prompt", "Getting API code generation guidance")
        logger.info(f"[{deps.correlation_id}] Tool 5: Getting API code generation prompt")
        
        # Load API code generation prompt from file (ReAct agent specific)
        api_prompt_file = Path(__file__).parent / "prompts" / "api_code_gen_react_agent_system_prompt.txt"
        try:
            with open(api_prompt_file, 'r', encoding='utf-8') as f:
                api_prompt = f.read()
        except FileNotFoundError:
            api_prompt = """Generate Python code using the Okta SDK to fetch data from the API.
            
Rules:
- Use the OktaAPIClient available as deps.okta_client
- Always add max_results={max_results} to paginated calls for testing
- Use async/await for API calls
- Handle errors gracefully
- Return structured data (list of dicts)
"""
        
        guidance = {
            "code_generation_prompt": api_prompt,
            "query_task": query_description,
            "max_results": max_results,
            "target_operations": endpoints,
            "okta_client_available": "YES - Variable 'client' is pre-injected (see prompt for details)"
        }
        
        return ToolReturn(
            return_value=f"✅ API code generation guidance loaded for {len(endpoints)} operations",
            content=json.dumps(guidance, separators=(',', ':')),
            metadata={'guidance_loaded': True, 'operations_count': len(endpoints)}
        )
    
    # ========================================================================
    # Tool 6: Execute Test Query (executes code generated by the agent)
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
            Output: {"groups": "Group1,Group2,Group3,Group4,Group5,Group6,Group7,Group8,Group9,Group10,Group11,Group12,Grou..."} (100 chars)
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
    
    async def execute_test_query(
        code: str,
        code_type: Literal["sql", "python_sdk"]
    ) -> Dict[str, Any]:
        """
        Execute test query and return sample results.
        
        For python_sdk type:
        - Generate ONLY the async function with Okta API logic
        - We will wrap it with client setup and execution boilerplate
        - Use 'client' variable for OktaAPIClient calls
        - Store final data in 'results' variable
        
        Example - You generate this:
        ```python
        async def fetch_data():
            response = await client.make_request(
                endpoint="/api/v1/users",
                method="GET",
                params={"limit": 3}
            )
            return response.get('data', [])
        
        results = await fetch_data()
        ```
        
        Args:
            code: Generated code from Tool 4 or Tool 5
            code_type: Type of code to execute
        
        Returns:
            Dictionary with execution results and metadata
        """
        check_cancellation()
        await notify_tool_call("execute_test_query", f"Executing {code_type} test query")
        
        # Circuit breaker checks BEFORE execution
        if code_type == "sql":
            if deps.sql_execution_count >= deps.MAX_SQL_EXECUTIONS:
                logger.warning(f"[{deps.correlation_id}] SQL circuit breaker triggered: {deps.sql_execution_count}/{deps.MAX_SQL_EXECUTIONS}")
                return ToolReturn(
                    return_value=f"⚠️ CIRCUIT BREAKER: SQL execution limit ({deps.MAX_SQL_EXECUTIONS}) exceeded",
                    content=f"⚠️ CIRCUIT BREAKER: {deps.sql_execution_count} SQL queries attempted (max: {deps.MAX_SQL_EXECUTIONS}). You MUST call stop_execution() tool now.",
                    metadata={
                        'success': False,
                        'circuit_breaker': True,
                        'execution_count': deps.sql_execution_count,
                        'max_executions': deps.MAX_SQL_EXECUTIONS,
                        'error': 'SQL execution limit exceeded'
                    }
                )
            deps.sql_execution_count += 1
            logger.info(f"[{deps.correlation_id}] Tool 6: Executing SQL test query (execution #{deps.sql_execution_count}/{deps.MAX_SQL_EXECUTIONS})")
            
        elif code_type == "python_sdk":
            if deps.api_execution_count >= deps.MAX_API_EXECUTIONS:
                logger.warning(f"[{deps.correlation_id}] API circuit breaker triggered: {deps.api_execution_count}/{deps.MAX_API_EXECUTIONS}")
                return ToolReturn(
                    return_value=f"⚠️ CIRCUIT BREAKER: API execution limit ({deps.MAX_API_EXECUTIONS}) exceeded",
                    content=f"⚠️ CIRCUIT BREAKER: {deps.api_execution_count} API calls attempted (max: {deps.MAX_API_EXECUTIONS}). You MUST call stop_execution() tool now.",
                    metadata={
                        'success': False,
                        'circuit_breaker': True,
                        'execution_count': deps.api_execution_count,
                        'max_executions': deps.MAX_API_EXECUTIONS,
                        'error': 'API execution limit exceeded'
                    }
                )
            deps.api_execution_count += 1
            logger.info(f"[{deps.correlation_id}] Tool 6: Executing API test query (execution #{deps.api_execution_count}/{deps.MAX_API_EXECUTIONS})")
        
        # Log the generated code for debugging
        logger.debug(f"[{deps.correlation_id}] Generated code to execute:\n{code}")
        
        start_time = time.time()
        
        # QUALITY CONTROL: Enforce Test Limits System-Wide
        # Verify and set test mode to catch any missing limits in generated code
        if hasattr(deps, 'okta_client'):
            deps.okta_client.test_mode = True
        
        try:
            if code_type == "sql":
                # LLM generates pure SQL query (no Python wrapper)
                sql_query = code.strip()
                
                # SECURITY VALIDATION: Check SQL for injection attacks
                logger.info(f"[{deps.correlation_id}] Running SQL security validation on query: {sql_query[:100]}...")
                is_valid, error_msg = validate_user_sql(sql_query, deps.correlation_id)
                if not is_valid:
                    logger.error(f"[{deps.correlation_id}] SQL security validation failed: {error_msg}")
                    return ToolReturn(
                        return_value=f"❌ SQL security validation failed",
                        content=f"❌ SECURITY VALIDATION FAILED: {error_msg}",
                        metadata={'success': False, 'security_error': True, 'error': error_msg}
                    )
                
                logger.info(f"[{deps.correlation_id}] ✅ SQL security validation passed")
                
                # SYSTEM-LEVEL ENFORCEMENT: Auto-inject LIMIT 3
                # We do this proactively instead of failing validation
                # Remove existing limit if present to avoid syntax errors (e.g. LIMIT 10 LIMIT 3)
                if "LIMIT" in sql_query.upper():
                     sql_query = re.sub(r'\s+LIMIT\s+\d+', '', sql_query, flags=re.IGNORECASE)
                
                # Remove trailing semicolon if present to prevent multi-statement error
                sql_query = sql_query.strip().rstrip(';')

                # Append mandatory safety limit
                sql_query = f"{sql_query} LIMIT 3"
                logger.info(f"[{deps.correlation_id}] Enforcing LIMIT 3 on SQL query: {sql_query}")
                
                # Execute SQL query against SQLite (now validated)
                cursor = deps.sqlite_connection.cursor()
                cursor.execute(sql_query)
                results = cursor.fetchall()
                
                # Get column names from cursor description
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                
                # Convert to list of dicts
                if results:
                    full_results = [dict(zip(columns, row)) for row in results]
                else:
                    full_results = []
                
                # TRUNCATE RESULTS: Reduce token usage by capping long text fields
                # Example: Column with 250 group names → truncated to 100 chars
                # LLM sees truncated data, saves it to artifacts
                # Full data preserved in metadata for app use (0 tokens to LLM)
                truncated_results = truncate_sql_results(full_results, max_text_length=100)
                
                execution_time_ms = int((time.time() - start_time) * 1000)
                
                # Compact JSON to save tokens (28-39% reduction)
                truncated_results_compact = json.dumps(truncated_results, separators=(',', ':'))
                
                # Calculate truncation stats
                truncation_applied = any(
                    any(isinstance(v, str) and len(str(full_results[i].get(k, ''))) > 100 
                        for k, v in row.items()) 
                    for i, row in enumerate(truncated_results)
                ) if full_results else False
                
                # Store full results in metadata (0 tokens, accessible to app)
                return ToolReturn(
                    return_value=f"✅ Query successful: {len(full_results)} rows returned (text fields truncated to 100 chars for efficiency)",
                    content=f"Sample results (truncated): {truncated_results_compact}",
                    metadata={
                        'success': True,
                        'sql_code': code,
                        'full_results': full_results,
                        'truncated_results': truncated_results,
                        'sample_schema': full_results[0] if full_results else None,
                        'total_records': len(full_results),
                        'execution_time_ms': execution_time_ms,
                        'columns': columns,
                        'truncation_applied': truncation_applied
                    }
                )
            
            elif code_type == "python_sdk":
                # SECURITY VALIDATION: Check Python code for dangerous patterns
                validation_result = validate_generated_code(code)
                if not validation_result.is_valid:
                    logger.warning(f"[{deps.correlation_id}] Python code security validation failed: {validation_result.violations}")
                    return ToolReturn(
                        return_value=f"❌ Python security validation failed",
                        content=f"❌ SECURITY VALIDATION FAILED: {', '.join(validation_result.violations)}",
                        metadata={'success': False, 'security_error': True, 'violations': validation_result.violations}
                    )
                
                # SECURITY VALIDATION: Check network requests for unauthorized domains
                # Extract endpoint from code to validate URL
                endpoint_match = re.search(r'make_request\s*\(\s*["\']([^"\']+)["\']', code)
                if endpoint_match:
                    endpoint = endpoint_match.group(1)
                    # Skip validation for special tools (they have their own security)
                    if not endpoint.startswith("/special-tools/"):
                        # Build full URL for validation
                        full_url = f"{deps.okta_client.base_url}{endpoint}"
                        network_validation = validate_request('GET', full_url)
                        if not network_validation.is_allowed:
                            logger.warning(f"[{deps.correlation_id}] Network security validation failed: {network_validation.blocked_reason}")
                            return ToolReturn(
                                return_value=f"❌ Network security validation failed",
                                content=f"❌ NETWORK SECURITY FAILED: {network_validation.blocked_reason}",
                                metadata={'success': False, 'security_error': True, 'violations': network_validation.violations}
                            )
                
                # NOTE: Validation for max_results is now handled systematically by client.test_mode
                # We no longer fail if the LLM forgets it, we just enforce it at the adapter level.
                
                # Execute Python SDK code
                # We're already in an async context
                
                # Create namespace with okta_client available
                namespace = {
                    'client': deps.okta_client,
                    'okta_client': deps.okta_client,
                    'asyncio': asyncio
                }
                
                # Special Tool Handling: Intercept /special-tools/ calls
                if "/special-tools/" in code:
                    logger.info(f"[{deps.correlation_id}] Special Tool detected in code - Using SpecialToolInterceptor")
                    
                    # Define interceptor class
                    class SpecialToolInterceptor:
                        def __init__(self, real_client):
                            self.real_client = real_client
                            
                        def __getattr__(self, name):
                            return getattr(self.real_client, name)
                            
                        async def make_request(self, endpoint, **kwargs):
                            if endpoint.startswith("/special-tools/"):
                                logger.info(f"[{deps.correlation_id}] Intercepting Special Tool request: {endpoint}")
                                try:
                                    tool_path = endpoint.replace("/special-tools/", "")
                                    tool_name = None
                                    if tool_path == "access-analysis":
                                        tool_name = "access_analysis"
                                    elif tool_path == "login-risk" or tool_path == "login-risk-analysis":
                                        tool_name = "login_risk_analysis"
                                    
                                    if not tool_name:
                                        return {"status": "error", "error": f"Unknown special tool: {tool_path}"}
                                    
                                    from src.core.tools.special_tools import execute_special_tool
                                    
                                    # Prepare tool arguments
                                    tool_kwargs = {}
                                    
                                    # Extract params if present (client.make_request passes params=...)
                                    if 'params' in kwargs:
                                        tool_kwargs.update(kwargs['params'])
                                    
                                    # Add any other kwargs that aren't 'method' or 'params'
                                    for k, v in kwargs.items():
                                        if k not in ['method', 'params', 'endpoint']:
                                            tool_kwargs[k] = v
                                            
                                    # Pass client to tool
                                    tool_kwargs['client'] = self.real_client
                                    
                                    # Execute tool
                                    tool_result = await execute_special_tool(tool_name, **tool_kwargs)
                                    
                                    return {
                                        "status": "success", 
                                        "data": tool_result,
                                        "source": "special_tool"
                                    }
                                except Exception as e:
                                    logger.error(f"Special tool execution failed: {e}")
                                    return {"status": "error", "error": str(e)}
                            else:
                                return await self.real_client.make_request(endpoint, **kwargs)
                    
                    # Replace client in namespace with interceptor
                    namespace['client'] = SpecialToolInterceptor(deps.okta_client)
                    namespace['okta_client'] = namespace['client']
                
                # Wrap code in async function to handle await statements
                # API/SDK code - extract function name and call it
                func_match = re.search(r'async\s+def\s+(\w+)\s*\(', code)
                if not func_match:
                    return ExecutionResult(
                        success=False,
                        error_message="Generated code must define an async function starting with 'async def function_name():'",
                        execution_time=0.0,
                        complete_production_code=""
                    )
                
                func_name = func_match.group(1)
                
                # Check if the code already assigns results (to avoid double execution)
                has_results_assignment = 'results = await' in code or 'results=await' in code
                
                if has_results_assignment:
                    # Code already calls the function and assigns to 'results'
                    # Just wrap it and return results
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
                
                # Log the wrapped code for debugging
                logger.debug(f"[{deps.correlation_id}] Wrapped code:\n{wrapped_code}")
                
                # Execute to define the wrapper function in namespace
                exec(wrapped_code, namespace)
                
                # Now await the wrapper coroutine (we're in an async context)
                results = await namespace['__exec_wrapper__']()
                
                # Convert to list if needed
                if not isinstance(results, list):
                    results = [results]
                
                execution_time_ms = int((time.time() - start_time) * 1000)
                
                # Compact JSON for LLM efficiency (removes whitespace, saves ~30% tokens)
                sample_results = results[:3]  # Limit to 3 for testing
                sample_results_compact = json.dumps(sample_results, separators=(',', ':'))
                
                # Store full results in metadata (0 tokens, accessible to app)
                return ToolReturn(
                    return_value=f"✅ API query successful: {len(results)} records returned",
                    content=f"Sample results: {sample_results_compact}",
                    metadata={
                        'success': True,
                        'python_code': code,
                        'full_results': results,
                        'sample_schema': results[0] if results else None,
                        'total_records': len(results),
                        'execution_time_ms': execution_time_ms,
                        'columns': list(results[0].keys()) if results and isinstance(results[0], dict) else []
                    }
                )
            
            else:
                return ToolReturn(
                    return_value=f"❌ Unknown code_type: {code_type}",
                    content=f"Error: Unknown code_type '{code_type}'",
                    metadata={'success': False, 'error': f"Unknown code_type: {code_type}"}
                )
        
        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            logger.error(f"[{deps.correlation_id}] Test execution failed: {e}", exc_info=True)
            
            return ToolReturn(
                return_value=f"❌ Execution failed: {str(e)[:100]}",
                content=f"Error: {str(e)}",
                metadata={
                    'success': False,
                    'execution_time_ms': execution_time_ms,
                    'error': str(e)
                }
            )
        
        finally:
            # ALWAYS RESET TEST MODE
            # Critical cleanup to ensure later production queries are not limited
            if hasattr(deps, 'okta_client'):
                deps.okta_client.test_mode = False
    
    # ========================================================================
    # Tool 7: Log Progress (NEW - for user feedback)
    # ========================================================================
    
    async def log_progress(
        action: str,
        reasoning: str,
        status: Literal["starting", "completed", "thinking"] = "starting"
    ) -> Dict[str, Any]:
        """
        Log your current action and reasoning to keep users informed of progress.
        Call this before and after major steps to provide visibility into your thought process.
        
        Args:
            action: What you're doing (e.g., "Loading database schema", "Testing SQL query")
            reasoning: Why you're taking this action (e.g., "Need to understand available tables")
            status: Whether you're starting an action, completed it, or just thinking
        
        Returns:
            Acknowledgment that progress was logged
        """
        check_cancellation()
        logger.info(f"[{deps.correlation_id}] 🎯 {status.upper()}: {action}")
        logger.info(f"[{deps.correlation_id}] 💭 Reasoning: {reasoning}")
        
        # If progress callback is provided, send event to frontend (legacy)
        if hasattr(deps, 'progress_callback') and deps.progress_callback:
            await deps.progress_callback({
                "type": "agent_progress",
                "action": action,
                "reasoning": reasoning,
                "status": status,
                "timestamp": time.time()
            })
        
        # NEW: SSE streaming callbacks for real-time UI
        if status == "starting" and hasattr(deps, 'step_start_callback') and deps.step_start_callback:
            await deps.step_start_callback({
                "title": action,
                "text": reasoning,
                "timestamp": time.time()
            })
        elif status == "completed" and hasattr(deps, 'step_end_callback') and deps.step_end_callback:
            await deps.step_end_callback({
                "title": action,
                "text": reasoning,
                "timestamp": time.time()
            })
        
        return {
            "logged": True,
            "message": f"Progress logged: {action}",
            "status": status
        }
    
    # ========================================================================
    # Tool 8: Generate Production Code
    # ========================================================================
    
    async def generate_production_code(
        test_code: str,
        test_results: Dict[str, Any],
        code_type: Literal["cypher", "python_sdk"]
    ) -> Dict[str, Any]:
        """
        Generate production-ready code based on validated test code.
        
        Args:
            test_code: Validated test code from Tool 4 or Tool 5
            test_results: Results from Tool 6 execution
            code_type: Type of code to generate
        
        Returns:
            Dictionary with production code and optimizations applied
        """
        logger.info(f"[{deps.correlation_id}] Tool 7: Generating production code (type: {code_type})")
        
        production_code = test_code
        optimizations_applied = []
        
        if code_type == "cypher":
            # Remove LIMIT clause for full dataset
            limit_pattern = r'\s+LIMIT\s+\d+\s*$'
            if re.search(limit_pattern, production_code, re.IGNORECASE):
                production_code = re.sub(limit_pattern, '', production_code, flags=re.IGNORECASE)
                optimizations_applied.append("Removed LIMIT clause for full dataset")
        
        elif code_type == "python_sdk":
            # Remove max_results parameter from API calls for production (fetch all)
            max_results_pattern = r'max_results\s*=\s*\d+'
            if re.search(max_results_pattern, production_code):
                production_code = re.sub(max_results_pattern, '', production_code)
                # Clean up any trailing comma/whitespace issues
                production_code = re.sub(r',\s*\)', ')', production_code)
                optimizations_applied.append("Removed max_results limit for production (fetch all data)")
        
        return {
            "production_code": production_code,
            "code_explanation": f"Production version of test code with optimizations",
            "optimizations_applied": optimizations_applied,
            "original_test_code": test_code
        }
    
    # ========================================================================
    # Tool 8: STOP Execution (NEW - for graceful termination)
    # ========================================================================
    
    async def stop_execution(
        reason: str,
        user_message: str,
        attempted_steps: List[str]
    ) -> Dict[str, Any]:
        """
        STOP execution and return a final result when unable to proceed.
        
        Call this tool when you've hit a circuit breaker limit, exhausted all approaches,
        or determined that the query cannot be answered with available data.
        
        This gracefully terminates the agent run and returns a clear message to the user.
        
        Args:
            reason: Internal reason for stopping (e.g., "SQL circuit breaker hit", "Data not available")
            user_message: Clear message to show the user explaining why we couldn't answer
            attempted_steps: List of steps you tried before stopping
        
        Returns:
            Stop signal that will terminate the agent
        """
        logger.warning(f"[{deps.correlation_id}] 🛑 STOP_EXECUTION called: {reason}")
        logger.info(f"[{deps.correlation_id}] User message: {user_message}")
        logger.info(f"[{deps.correlation_id}] Attempted steps: {attempted_steps}")
        
        # If progress callback is provided, send stop event to frontend
        if hasattr(deps, 'progress_callback') and deps.progress_callback:
            await deps.progress_callback({
                "type": "agent_stopped",
                "reason": reason,
                "user_message": user_message,
                "attempted_steps": attempted_steps,
                "timestamp": time.time()
            })
        
        return {
            "stop": True,
            "reason": reason,
            "user_message": user_message,
            "attempted_steps": attempted_steps,
            "final_result": ExecutionResult(
                success=False,
                results=None,
                execution_plan=f"Attempted: {', '.join(attempted_steps)}",
                steps_taken=attempted_steps,
                error=user_message,
                complete_production_code=""
            )
        }
    
    # ========================================================================
    # Tool 9: Save Knowledge Artifact
    # ========================================================================
    
    async def save_knowledge_artifact(
        ctx: RunContext[ReactAgentDependencies],
        category: Literal["sql_results", "api_endpoints", "api_response"],
        content: str,
        notes: str = ""
    ) -> ToolReturn:
        """
        Save important context while you have data visible.
        Call IMMEDIATELY after seeing results from execute_test_query() or filter_endpoints_by_operations().
        
        ⚠️ IMPORTANT: Save exactly what you SEE, not what you imagine the full data looks like.
        - SQL results are TRUNCATED (text fields capped at 100 chars) - save the truncated version
        - API responses may be truncated - save what you received
        - This ensures artifacts match your analysis
        
        Args:
            category: Type of data being saved
            content: The ACTUAL data you received (paste the JSON/text as-is, don't summarize)
            notes: Additional context for later reference
        
        Returns:
            Confirmation that artifact was saved
        """
        check_cancellation()
        await notify_tool_call("save_knowledge_artifact", f"Saving {category} artifact")
        
        # Initialize artifacts list if not exists
        if deps.artifacts is None:
            deps.artifacts = []
        
        # Create artifact
        artifact = {
            "key": f"{category}_{len(deps.artifacts) + 1}",
            "category": category,
            "content": content,
            "notes": notes,
            "timestamp": time.time()
        }
        
        deps.artifacts.append(artifact)
        
        # Persist to disk
        await dump_artifacts_to_file(deps.correlation_id, deps.artifacts)
        
        logger.info(f"[{deps.correlation_id}] 💾 Saved artifact: {artifact['key']} ({len(content)} chars)")
        
        return ToolReturn(
            return_value=f"✅ Saved {category} artifact",
            content=f"Artifact saved as {artifact['key']}",
            metadata={'artifact_key': artifact['key'], 'category': category, 'timestamp': time.time()}
        )
    
    # ========================================================================
    # Tool 10: Get Knowledge Artifacts
    # ========================================================================
    
    async def get_knowledge_artifacts(
        ctx: RunContext[ReactAgentDependencies]
    ) -> ToolReturn:
        """
        Retrieve all saved artifacts for final script generation.
        Call this before generating the final production script to recall earlier discoveries.
        
        Smart retrieval: Only returns artifacts if cumulative usage exceeds 800k tokens.
        Below that threshold, your conversation history contains all needed information.
        
        Returns:
            All saved artifacts with field names, endpoint paths, and response structures
            OR a message indicating you have all info in context
        """
        check_cancellation()
        await notify_tool_call("get_knowledge_artifacts", "Checking if artifacts needed")
        
        # Check if any artifacts exist
        if not deps.artifacts or len(deps.artifacts) == 0:
            return ToolReturn(
                return_value="No artifacts saved yet",
                content="[]",
                metadata={'artifact_count': 0}
            )
        
        # Check cumulative usage to decide if artifacts are needed
        cumulative_tokens = ctx.usage.input_tokens if ctx.usage else 0
        
        # If usage is still low, LLM has all context - no need for artifacts
        if cumulative_tokens < 800_000:  # 80% of 1M context window
            logger.info(f"[{deps.correlation_id}] ✅ Context still small ({cumulative_tokens:,} tokens) - artifacts not needed")
            return ToolReturn(
                return_value="✅ You have all information in context - proceed with synthesis",
                content="No artifacts needed - your conversation history contains all data from previous steps",
                metadata={'skipped_reason': 'low_usage', 'cumulative_tokens': cumulative_tokens}
            )
        
        # High usage - send artifacts to reduce context dependency
        logger.info(f"[{deps.correlation_id}] 📦 High usage ({cumulative_tokens:,} tokens) - returning {len(deps.artifacts)} artifacts")
        
        # Use compact JSON (no indents) to save tokens
        artifacts_json = json.dumps(deps.artifacts, separators=(',', ':'))
        categories = [a['category'] for a in deps.artifacts]
        
        return ToolReturn(
            return_value=f"✅ Retrieved {len(deps.artifacts)} artifacts (context exceeds 800k): {', '.join(categories)}",
            content=artifacts_json,
            metadata={'artifact_count': len(deps.artifacts), 'categories': categories, 'cumulative_tokens': cumulative_tokens}
        )
    
    # ========================================================================
    # Tool 11: Get Final Script Synthesis Prompt
    # ========================================================================
    
    async def get_final_script_synthesis_prompt() -> ToolReturn:
        """
        Load the complete script blueprint for final code generation.
        
        This guidance includes:
        - Complete script template with all imports
        - Database connection patterns
        - API client usage with concurrent batching
        - Progress tracking examples
        - Output formatting (table headers)
        - Performance requirements
        
        Call this BEFORE generating the final production script.
        
        Returns:
            Complete synthesis guidance with script template
        """
        check_cancellation()
        await notify_tool_call("get_final_script_synthesis_prompt", "Loading final script synthesis guidance")
        logger.info(f"[{deps.correlation_id}] Tool 11: Loading final script synthesis prompt")
        
        # Load synthesis prompt from file
        synthesis_prompt_file = Path(__file__).parent / "prompts" / "final_script_synthesis_prompt.txt"
        try:
            with open(synthesis_prompt_file, 'r', encoding='utf-8') as f:
                synthesis_prompt = f.read()
        except FileNotFoundError:
            logger.error(f"[{deps.correlation_id}] Synthesis prompt file not found: {synthesis_prompt_file}")
            synthesis_prompt = """Generate a complete Python script following best practices.
            
Include:
- Database connection with error handling
- API client initialization  
- Concurrent batching for multiple API calls
- Progress tracking
- Table-formatted JSON output
- Proper cleanup
"""
        
        return ToolReturn(
            return_value="✅ Final script synthesis guidance loaded",
            content=synthesis_prompt,
            metadata={'guidance_loaded': True, 'file': str(synthesis_prompt_file)}
        )
    
    # Add all tools to the toolset (10 tools total)
    toolset.tool(log_progress)  # Tool 7: Progress logging
    toolset.tool(stop_execution)  # Tool 8: Stop execution
    toolset.tool(save_knowledge_artifact)  # Tool 9: Save context summaries
    toolset.tool(get_knowledge_artifacts)  # Tool 10: Retrieve saved summaries
    toolset.tool(get_final_script_synthesis_prompt)  # Tool 11: Final script template
    toolset.tool(get_sql_context)  # Tool 1: Combined SQL schema + guidance
    toolset.tool(load_comprehensive_api_endpoints)  # Tool 2
    toolset.tool(filter_endpoints_by_operations)  # Tool 3
    toolset.tool(get_api_code_generation_prompt)  # Tool 4
    toolset.tool(execute_test_query)  # Tool 5
    
    return toolset

# ============================================================================
# ReAct Agent Definition
# ============================================================================

# Load system prompt from file
PROMPT_FILE = Path(__file__).parent / "prompts" / "one_react_agent_prompt.txt"

try:
    with open(PROMPT_FILE, 'r', encoding='utf-8') as f:
        BASE_SYSTEM_PROMPT = f.read()
except FileNotFoundError:
    logger.warning(f"Prompt file not found: {PROMPT_FILE}. Using default prompt.")
    BASE_SYSTEM_PROMPT = "You are a ReAct agent for Okta query execution."

# Create the ReAct agent with history compression
react_agent = Agent(
    model,  # Use model from model_picker
    instructions=BASE_SYSTEM_PROMPT,  # Static base instructions
    output_type=ExecutionResult,
    deps_type=ReactAgentDependencies,
    retries=0,  # No retries to avoid wasting money on failed attempts
    history_processors=[compress_history]  # Phase 2: Compress heavy responses after artifact save
)

@react_agent.instructions  
def create_dynamic_instructions(ctx: RunContext[ReactAgentDependencies]) -> str:
    """Create dynamic instructions with context from dependencies"""
    deps = ctx.deps
    
    # Build dynamic context without duplicating schema (loaded on-demand via get_sql_context)
    dynamic_context = f"""

DYNAMIC CONTEXT FOR THIS REQUEST:
- User Query: {deps.user_query}
- Correlation ID: {deps.correlation_id}
- Available API Endpoints: {len(deps.endpoints)} total

⚠️ IMPORTANT REMINDER - CODE GENERATION WORKFLOW (Phase 2 Optimized):
1. When you need database data:
   - FIRST: Call get_sql_context(query_description, limit=3) to get schema + SQL rules in one call
   - SECOND: READ the returned context carefully (includes tables, columns, and generation rules)
   - THIRD: WRITE your SQL code using the schema and rules provided
   - FOURTH: Call execute_test_query(your_code, "sql")

2. When you need to generate Python SDK code:
   - FIRST: Call get_api_code_generation_prompt(query_description, endpoints, max_results=3)
     (NOTE: Do NOT use max_results for Special Tools starting with /special-tools/)
   - SECOND: READ the returned data carefully
   - THIRD: WRITE your Python code based on that guidance
   - FOURTH: Call execute_test_query(your_code, "python_sdk")

NOTE: The SQL context shows you EXACTLY what tables (users, groups, applications, etc.) and 
columns exist in each table. DO NOT invent names - use only what you see in the context.

Remember the optimized workflow:
1. Call get_sql_context() for database queries (combines schema + guidance)
2. Determine if data is in SQLite database or needs API
3. Load comprehensive API endpoints if needed
4. Filter to specific entities
5. Get code generation prompt (Tool 4 or 5)
6. Generate YOUR code using the prompt guidance
7. Execute and inspect results
8. Generate production code
9. Return ExecutionResult
"""
    
    return dynamic_context

# ============================================================================
# Main Execution Function
# ============================================================================

async def execute_react_query(
    user_query: str,
    deps: ReactAgentDependencies
) -> ExecutionResult:
    """
    Execute user query using ReAct agent with 7 tools.
    
    Args:
        user_query: Natural language query from user
        deps: Dependencies for agent (endpoints, schema, clients, etc.)
    
    Returns:
        ExecutionResult with success status and results
    """
    logger.info(f"[{deps.correlation_id}] Starting ReAct agent execution for query: {user_query}")
    
    # Create toolset with dependencies
    toolset = create_react_toolset(deps)
    
    # Create UsageLimits for safety (loop control and token caps)
    usage_limits = UsageLimits(
        request_limit=30,  # Maximum 30 LLM calls per query
        tool_calls_limit=30,  # Maximum 30 tool invocations
        response_tokens_limit=100000  # Maximum 100k output tokens
    )
    
    # Run agent with toolset and usage limits
    result = await react_agent.run(
        user_query,
        deps=deps,
        toolsets=[toolset],
        usage_limits=usage_limits
    )
    
    # Access the output from the result (PydanticAI returns output, not data)
    execution_result = result.output
    
    # Log synthesis phase completion
    if execution_result.complete_production_code:
        logger.info(f"[{deps.correlation_id}] ✅ SYNTHESIS COMPLETE: Generated final production code ({len(execution_result.complete_production_code)} chars)")
        
        # Save final script to artifacts
        if deps.artifacts is None:
            deps.artifacts = []
        
        final_script_artifact = {
            "key": "final_production_script",
            "category": "code_generation",
            "content": execution_result.complete_production_code,
            "notes": f"Final production script generated after {result.usage().requests if result.usage() else 0} LLM calls",
            "timestamp": time.time()
        }
        
        deps.artifacts.append(final_script_artifact)
        await dump_artifacts_to_file(deps.correlation_id, deps.artifacts)
        logger.info(f"[{deps.correlation_id}] 💾 Saved final production script to artifacts ({len(execution_result.complete_production_code)} chars)")
    else:
        logger.warning(f"[{deps.correlation_id}] ⚠️ SYNTHESIS INCOMPLETE: No production code generated")
    
    # Log final token usage summary (accumulated across all LLM calls)
    if result.usage():
        usage = result.usage()
        avg_per_call = usage.input_tokens / usage.requests if usage.requests > 0 else 0
        logger.info(
            f"[{deps.correlation_id}] 📊 FINAL Token Usage: "
            f"{usage.input_tokens:,} input, {usage.output_tokens:,} output, "
            f"{usage.total_tokens:,} total (across {usage.requests} API calls, "
            f"avg {avg_per_call:,.0f} input/call)"
        )
        
        # NEW: Report token usage via SSE callback
        if hasattr(deps, 'step_tokens_callback') and deps.step_tokens_callback:
            await deps.step_tokens_callback({
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "total_tokens": usage.total_tokens,
                "requests": usage.requests
            })
    
    logger.info(f"[{deps.correlation_id}] ReAct agent completed: success={execution_result.success}")
    
    # Return both execution result and usage info
    return execution_result, result.usage()
