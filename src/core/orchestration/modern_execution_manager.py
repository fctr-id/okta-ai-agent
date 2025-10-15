"""
Modern Execution Manager for Okta AI Agent.


"""

from typing import Dict, List, Any, Optional
import asyncio
import os
import sys
import json
import time  # For step timing and formatting
import polars as pl  # High-performance DataFrame operations replacing temp tables
from pydantic import BaseModel

# Add src path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

# Import existing agents from agents directory
from src.core.agents.cypher_code_gen_agent import (
    generate_cypher_query_with_logging, 
    is_safe_cypher,
    cypher_enrichment_agent,
    CypherQueryOutput,
    PolarsOptimizedOutput
)
from src.core.agents.api_code_gen_agent import api_code_gen_agent, ApiCodeGenDependencies, generate_api_code  
from src.core.agents.planning_agent import ExecutionPlan, ExecutionStep, planning_agent, PlanningDependencies
from src.core.agents.results_formatter_agent import format_results as process_results_formatter  # Unified token-based results formatting
from src.core.agents.relationship_analysis_agent import analyze_data_relationships  # Stage 1: Relationship analysis for three-stage pipeline

# Import special tools support
from src.core.tools.special_tools import get_special_tool, execute_special_tool

# Import security validation
from src.core.security import (
    validate_generated_code, 
    validate_http_method, 
    validate_api_endpoint,
    validate_url,
    get_security_headers
)

# Import logging
from src.utils.logging import get_logger, get_default_log_dir

# Configure logging
# Using main "okta_ai_agent" namespace for unified logging across all agents
logger = get_logger("okta_ai_agent", log_dir=get_default_log_dir())

# ================================================================
# TIMEOUT CONFIGURATION - EASY TO MODIFY
# ================================================================
# 
# CURRENT TIMEOUT VALUES:
# - API Operations: 180s (3 min) - Standard API calls with pagination
#
# REASONING FOR VALUES:
# - API calls (including system logs) need 3 minutes for multiple paginated calls
# - Cypher queries execute directly against GraphDB (no timeout needed here)
# ================================================================

# API Execution Timeouts (in seconds) - Read from environment with fallbacks
API_EXECUTION_TIMEOUT = int(os.getenv('API_EXECUTION_TIMEOUT', 180))           # Subprocess timeout for API code execution (3 minutes)

# ================================================================


def _create_api_dataframe(data: List[Dict[str, Any]]) -> pl.DataFrame:
    """
    Create Polars DataFrame from complex nested API responses using native json_normalize.
    
    Optimized for Okta and other REST API responses with deep nesting, mixed types,
    and inconsistent schemas across records.
    
    Args:
        data: List of dictionaries from API response
        
    Returns:
        Flattened Polars DataFrame with nested fields as separate columns
        
    Examples:
        Input: [{"profile": {"email": "user@domain.com"}}]
        Output: DataFrame with column "profile_email"
    """
    if not data:
        return pl.DataFrame()
        
    try:
        # Use Polars native JSON normalization - purpose-built for nested APIs
        return pl.json_normalize(
            data,
            separator='_',           # profile.email becomes profile_email
            max_level=4,            # Capture 95% of useful fields without column explosion
            infer_schema_length=None # Scan all records for consistent schema
        )
    except Exception as e:
        # Fallback: Try basic DataFrame creation with schema inference
        try:
            return pl.DataFrame(data, infer_schema_length=None)
        except Exception:
            # Absolute last resort - empty DataFrame
            return pl.DataFrame()


class StepResult(BaseModel):
    """Result from executing a single step"""
    step_number: int
    step_type: str
    success: bool
    result: Any = None
    error: Optional[str] = None


class SQLExecutionResult:
    """SQL execution result object with query details and data"""
    def __init__(self, sql_text: str, explanation: str, data: List[Dict[str, Any]]):
        self.sql = sql_text
        self.explanation = explanation
        self.data = data


class CypherExecutionResult:
    """Cypher execution result object with query details and data"""
    def __init__(self, cypher_text: str, explanation: str, data: List[Dict[str, Any]]):
        self.cypher = cypher_text
        self.explanation = explanation
        self.data = data


class APIExecutionResult:
    """API execution result object with code details and data"""
    def __init__(self, code: str, explanation: str, data: Any, executed: bool = True, error: str = None):
        self.code = code
        self.explanation = explanation
        self.data = data
        self.executed = executed
        self.error = error


class ExecutionResults(BaseModel):
    """Results from executing all steps"""
    steps: List[StepResult]
    final_result: Any = None
    correlation_id: str
    total_steps: int
    successful_steps: int
    failed_steps: int
    formatted_response: Optional[Dict[str, Any]] = None


class BasicErrorHandler:
    """Simple error handling for SQL and API operations"""
    
    @staticmethod
    def handle_step_error(step: ExecutionStep, error: Exception, correlation_id: str, step_number: int) -> StepResult:
        """Handle individual step errors with simple logging"""
        error_msg = str(error)
        logger.error(f"[{correlation_id}] Step {step_number} ({step.tool_name}) failed: {error_msg}")
        
        return StepResult(
            step_number=step_number,
            step_type=step.tool_name,
            success=False,
            error=error_msg
        )


class ModernExecutionManager:
    """
    Advanced multi-step execution engine for complex Okta AI Agent workflows.
    
    Orchestrates SQL and API operations with intelligent data flow management,
    variable-based storage, and repeatable patterns for adding new tools.
    
    Core philosophy: Trust the agents to do their jobs. Just orchestrate the steps.
    """
    
    def __init__(self):
        """Initialize the modern execution manager"""
        self.error_handler = BasicErrorHandler()
        
        # Import settings to get tenant_id
        from src.config.settings import Settings
        settings = Settings()
        self.tenant_id = settings.tenant_id  # Derived from OKTA_CLIENT_ORGURL
        
        # Load simple reference format
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
        self.simple_ref_path = os.path.join(project_root, "src", "data", "schemas", "lightweight_api_reference.json")
        self.full_api_path = os.path.join(project_root, "src", "data", "schemas", "Okta_API_entitity_endpoint_reference_GET_ONLY.json")
        
        # Load simple reference for planning
        self.simple_ref_data = self._load_simple_reference()
        
        # Load full API data for endpoint filtering during execution
        self.full_api_data = self._load_api_data()
        
        # Extract planning dependencies from simple reference (new entity-grouped format)
        entities_dict = self.simple_ref_data.get('entities', {})
        self.available_entities = list(entities_dict.keys())
        self.entity_summary = {entity_name: {'operations': entity_data['operations'], 'methods': []} 
                              for entity_name, entity_data in entities_dict.items()}
        
        # Build GraphDB schema for planning (instead of SQL tables)
        self.graph_schema = self._build_graph_schema()
        
        self.endpoints = self.full_api_data.get('endpoints', [])  # Load endpoints for filtering
        
        # SPECIAL TOOLS INTEGRATION: Add special tool endpoints to main endpoints list
        try:
            from src.core.tools.special_tools import get_lightweight_references
            special_tools_refs = get_lightweight_references()
            
            for special_tool in special_tools_refs:
                if 'endpoints' in special_tool:
                    # Add special tool endpoints to main endpoints list
                    for endpoint in special_tool['endpoints']:
                        self.endpoints.append(endpoint)
                    logger.debug(f"Added {len(special_tool['endpoints'])} special tool endpoints to main endpoints list")
            
            logger.info(f"Total endpoints available (including special tools): {len(self.endpoints)}")
            
        except Exception as e:
            logger.warning(f"Failed to integrate special tool endpoints: {e}")
        
        # Legacy operation mapping for backwards compatibility (generate from entities)
        self.operation_mapping = {}
        for entity_name, entity_data in entities_dict.items():
            for operation in entity_data['operations']:
                # Extract base operation from entity-first format (e.g., "user_list" -> "list")
                if '_' in operation and operation.startswith(entity_name + '_'):
                    base_operation = operation[len(entity_name) + 1:]
                    self.operation_mapping[operation] = {'entity': entity_name, 'operation': base_operation}
        
        # REPEATABLE DATA FLOW PATTERN: Variable-based data management
        # Based on proven old executor approach - scales with any number of tools/steps
        self.step_metadata = {}       # Step tracking: {"step_1": {"type": "sql", "success": True, "record_count": 1000, "step_context": "query"}}
        
        # POLARS DATAFRAME ENHANCEMENT: Single source of truth - High-performance DataFrame storage
        # MEMORY OPTIMIZED: Removed legacy data_variables to prevent duplication
        self.polars_dataframes: Dict[str, pl.DataFrame] = {}  # {"sql_data_step_1": DataFrame, "api_data_step_2": DataFrame}
        
        # EXECUTION PLAN ACCESS: Store current execution plan for external access (minimal for realtime interface)
        self.current_execution_plan = None
        
        # NEW STANDARDIZED EXECUTION CALLBACKS - Clean implementation without legacy
        self.plan_ready_callback = None  # Optional callback for when plan is ready
        self.planning_phase_callback = None  # Optional callback for planning phases (planning_start, planning_complete)
        self.step_start_callback = None  # Optional callback for step start (step_number, step_type, metadata)
        self.step_end_callback = None    # Optional callback for step end (step_number, step_type, success, metadata)
        self.step_progress_callback = None  # Optional callback for API progress (step_number, step_type, percentage, details)
        self.step_count_callback = None     # Optional callback for record counts (step_number, step_type, count, operation)
        self.step_tokens_callback = None    # Optional callback for token usage (step_number, step_type, input_tokens, output_tokens)
        self.step_error_callback = None     # Optional callback for step errors (step_number, step_type, error_message, retry_possible, technical_details)
        self.plan_generated_callback = None # Optional callback for complete execution plan (plan_json, metadata)
        self.analysis_phase_callback = None # Optional callback for analysis phases (analysis_start, analysis_complete, analysis_error)
        self.subprocess_progress_callback = None # Optional callback for subprocess progress events (real-time API progress)
        
        # STEP SCHEMAS STORAGE: Store schemas generated for Results Formatter to recreate schema-enhanced structure in data injection
        self.current_step_schemas = {}  # Store step schemas for data injection code generation
        
        # MINIMAL CANCELLATION SYSTEM: Aggressive termination on user request
        self.cancelled_queries = set()  # Just store correlation_ids that are cancelled
        
        logger.info(f"Modern Execution Manager initialized: {len(self.available_entities)} API entities, GraphDB schema: {len(self.graph_schema)} characters, {len(self.endpoints)} endpoints")
    
    # DATABASE HEALTH CHECK METHODS
    
    def _check_database_health(self) -> bool:
        """
        Check if the GraphDB database exists and is populated with users.
        
        Returns:
            bool: True if GraphDB exists and has User nodes (>= 1), False otherwise
        """
        try:
            # Import GraphDB sync operations (same class used for queries)
            from src.core.okta.graph_db.sync_operations import GraphDBSyncOperations
            from src.core.okta.graph_db.version_manager import get_version_manager
            
            # Get current database path from version manager
            version_manager = get_version_manager()
            db_path = version_manager.get_current_db_path()
            
            if not db_path or not os.path.exists(db_path):
                logger.warning(f"GraphDB file not found: {db_path}")
                return False
            
            logger.debug(f"Checking GraphDB health: {db_path}")
            
            # Try to connect and check for User nodes
            try:
                graph_db = GraphDBSyncOperations(db_path=db_path)
                
                # Check if there are any User nodes
                result = graph_db.conn.execute(
                    "MATCH (u:User) RETURN count(u) as user_count LIMIT 1"
                )
                
                # Convert result to Polars DataFrame
                results_df = result.get_as_pl()
                
                if results_df is not None and len(results_df) > 0:
                    user_count = results_df[0, 'user_count']  # Get first row's user_count column
                    logger.info(f"GraphDB health check: Found {user_count} User nodes in database")
                    return user_count >= 1
                else:
                    logger.warning("GraphDB query returned no results")
                    return False
                    
            except Exception as db_error:
                logger.warning(f"GraphDB connection/query failed: {db_error}")
                return False
                
        except Exception as e:
            logger.warning(f"GraphDB health check failed: {e}")
            return False
    
    def _sanitize_planning_error(self, error_msg: str) -> str:
        """
        Sanitize planning error messages to prevent sensitive information exposure.
        
        Args:
            error_msg: Raw error message from planning agent
            
        Returns:
            str: User-friendly error message without sensitive details
        """
        # Convert to lowercase for pattern matching
        error_lower = error_msg.lower()
        
        # Handle AI provider/model specific errors
        if "status_code: 404" in error_msg and "model" in error_lower:
            return "AI model configuration error. Please contact your administrator to verify the AI model settings."
        
        if "status_code: 401" in error_msg or "unauthorized" in error_lower:
            return "AI service authentication failed. Please check your API credentials."
        
        if "status_code: 403" in error_msg or "forbidden" in error_lower:
            return "AI service access denied. Please verify your API permissions."
        
        if "status_code: 429" in error_msg or "rate limit" in error_lower:
            return "AI service rate limit exceeded. Please try again in a few moments."
        
        if "vertex" in error_lower and "not found" in error_lower:
            return "Vertex AI model not found or access denied. Please verify your model configuration."
        
        if "openai" in error_lower and ("api" in error_lower or "key" in error_lower):
            return "OpenAI API configuration error. Please check your API key and settings."
        
        if "anthropic" in error_lower and ("api" in error_lower or "key" in error_lower):
            return "Anthropic API configuration error. Please check your API key and settings."
        
        # Handle PydanticAI specific errors
        if "exceeded maximum retries" in error_lower and "output validation" in error_lower:
            return "Planning agent failed to generate a valid execution plan. The AI model may be having difficulty understanding the query structure. Please try rephrasing your request or try again later."
        
        if "validation" in error_lower and "pydantic" in error_lower:
            return "Planning agent encountered a validation error while generating the execution plan. Please try rephrasing your query."
        
        # Handle timeout errors
        if "timeout" in error_lower or "timed out" in error_lower:
            return "Planning request timed out. The AI service may be experiencing high load. Please try again."
        
        # Handle connection errors
        if "connection" in error_lower and ("refused" in error_lower or "failed" in error_lower):
            return "Unable to connect to AI service. Please check your network connection and try again."
        
        # Handle generic HTTP errors
        if "status_code:" in error_msg:
            return "AI service error occurred. Please try again or contact your administrator if the issue persists."
        
        # Handle JSON/parsing errors
        if "json" in error_lower and ("decode" in error_lower or "parse" in error_lower):
            return "AI service returned an invalid response. Please try again."
        
        # Generic fallback for any unmatched errors
        if len(error_msg) > 200:  # Long error messages likely contain sensitive details
            return "Planning agent encountered an unexpected error. Please try rephrasing your query or contact your administrator."
        
        # For short, generic errors, provide a safe version
        return "Planning agent failed to process your request. Please try rephrasing your query or try again later."
    
    def _should_force_api_only_mode(self, query: str, force_api_only: bool = False) -> tuple[bool, str]:
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
        db_healthy = self._check_database_health()
        
        # Decision logic
        should_force_api = force_api_only or explicit_api_only or not db_healthy
        
        # Modify query if forcing API-only mode
        modified_query = query
        if should_force_api and not explicit_api_only:
            # Add API-only instruction to query
            modified_query = f"{query}. Do NOT use SQL and only use APIs"
            
        # Log decision
        if should_force_api:
            reasons = []
            if force_api_only:
                reasons.append("frontend flag")
            if explicit_api_only:
                reasons.append("explicit user request")
            if not db_healthy:
                reasons.append("database unavailable/empty")
            
            logger.info(f"API-only mode activated: {', '.join(reasons)}")
            if modified_query != query:
                logger.info(f"Modified query: {modified_query}")
        else:
            logger.info("SQL and API modes both available")
            
        return should_force_api, modified_query
    
    def is_database_healthy(self) -> Dict[str, Any]:
        """
        Public method to check GraphDB health status.
        
        Returns:
            Dict with GraphDB health information for API endpoints/frontend
        """
        try:
            is_healthy = self._check_database_health()
            
            # Get GraphDB info
            db_dir = os.path.join(os.getcwd(), 'db')
            db_path = None
            db_size = 0
            user_count = 0
            node_count = 0
            
            if os.path.exists(db_dir):
                import glob
                graph_files = glob.glob(os.path.join(db_dir, 'tenant_graph_v*.db'))
                
                if graph_files:
                    # Get current database (highest version)
                    db_path = max(graph_files, key=lambda f: int(f.split('_v')[-1].split('.db')[0]))
                    db_size = os.path.getsize(db_path)
                    
                    if is_healthy:
                        try:
                            from src.core.okta.graph_db.sync_operations import GraphDBSyncOperations
                            graph_db = GraphDBSyncOperations(db_path=db_path)
                            
                            # Get user count
                            result = graph_db.conn.execute("MATCH (u:User) RETURN count(u) as count")
                            results_df = result.get_as_pl()
                            if results_df is not None and len(results_df) > 0:
                                user_count = results_df[0, 'count']
                            
                            # Get total node count across all types
                            result = graph_db.conn.execute("MATCH (n) RETURN count(n) as count")
                            results_df = result.get_as_pl()
                            if results_df is not None and len(results_df) > 0:
                                node_count = results_df[0, 'count']
                            
                        except Exception as e:
                            logger.warning(f"Failed to get GraphDB stats: {e}")
            
            return {
                "healthy": is_healthy,
                "database_path": db_path,
                "database_size_bytes": db_size,
                "user_count": user_count,
                "node_count": node_count,
                "cypher_available": is_healthy,
                "api_available": True,  # API is always available
                "recommendation": "Cypher and API modes available" if is_healthy else "API-only mode recommended"
            }
            
        except Exception as e:
            logger.error(f"GraphDB health check failed: {e}")
            return {
                "healthy": False,
                "error": str(e),
                "cypher_available": False,
                "api_available": True,
                "recommendation": "API-only mode required"
            }
    
    # REPEATABLE DATA FLOW METHODS - Scale with any number of tools/steps
    
    def _store_step_data(self, step_number: int, step_type: str, data: Any, metadata: Dict[str, Any] = None, step_context: str = None) -> str:
        """
        Store step data using FULL POLARS architecture for maximum performance.
        
        Args:
            step_number: Current step number
            step_type: Type of step (sql, api, etc.)
            data: Full dataset to store
            metadata: Additional metadata about the step
            step_context: Query context for this step
            
        Returns:
            Variable name for accessing this data
        """
        variable_name = f"{step_type}_data_step_{step_number}"
        
        # FULL POLARS: Convert to DataFrame for all operations
        if isinstance(data, list) and data:
            # Check if it's a list of empty lists/arrays
            if all(isinstance(item, list) and not item for item in data):
                # All items are empty lists - treat as empty data
                df = pl.DataFrame()
                self.polars_dataframes[variable_name] = df
                logger.warning(f"Created empty Polars DataFrame for {variable_name}: all API results were empty arrays")
            else:
                try:
                    # Use native Polars json_normalize for all complex nested data (API, Cypher results, etc.)
                    df = _create_api_dataframe(data)
                    # logger.debug(f"Created Polars DataFrame: {df.shape[0]} rows × {df.shape[1]} columns")
                    
                    self.polars_dataframes[variable_name] = df
                except Exception as e:
                    logger.error(f"Failed to create DataFrame from data: {e}")
                    # Fallback: create empty DataFrame
                    df = pl.DataFrame()
                    self.polars_dataframes[variable_name] = df
                    logger.warning(f"Created empty Polars DataFrame for {variable_name}: DataFrame creation failed")
        elif isinstance(data, dict):
            # Single record - convert to DataFrame
            try:
                df = pl.DataFrame([data])
                self.polars_dataframes[variable_name] = df
                # logger.debug(f"Created Polars DataFrame from single record: {df.shape[0]} rows × {df.shape[1]} columns")
            except Exception as e:
                logger.error(f"Failed to create DataFrame from single record: {e}")
                df = pl.DataFrame()
                self.polars_dataframes[variable_name] = df
                logger.warning(f"Created empty Polars DataFrame for {variable_name}: single record creation failed")
        else:
            # Empty or invalid data
            df = pl.DataFrame()
            self.polars_dataframes[variable_name] = df
            logger.warning(f"Created empty Polars DataFrame for {variable_name}: no valid data")
        
        # Store metadata including step context
        self.step_metadata[f"step_{step_number}"] = {
            "type": step_type,
            "variable_name": variable_name,
            "step_context": step_context,  # Store step context for enhanced context system
            "record_count": len(data) if isinstance(data, list) else 1,
            "success": True,
            **(metadata or {})
        }
        
        logger.debug(f"Stored {step_type} step data: variable={variable_name}, records={len(data) if isinstance(data, list) else 1}")
        return variable_name
    
    def _get_all_previous_step_contexts_and_samples(self, current_step_number: int, max_samples: int = 3) -> Dict[str, Any]:
        """
        Get contexts and samples from ALL previous steps for enhanced LLM understanding.
        
        Args:
            current_step_number: Current step number
            max_samples: Maximum number of sample items per step
            
        Returns:
            Dictionary with all previous step contexts and samples
        """
        all_contexts = {}
        
        # Iterate through all previous steps
        for step_num in range(1, current_step_number):
            step_key = f"step_{step_num}"
            
            # Get step context from metadata
            if step_key in self.step_metadata:
                step_metadata = self.step_metadata[step_key]
                step_context = step_metadata.get("step_context", f"Step {step_num} context not available")
                
                # FULL POLARS ARCHITECTURE: Get step data samples from polars_dataframes
                variable_name = step_metadata.get("variable_name")
                if variable_name and variable_name in self.polars_dataframes:
                    df = self.polars_dataframes[variable_name]
                    if not df.is_empty():
                        # Sample the DataFrame efficiently
                        step_data = df.head(max_samples).to_dicts()
                        step_sample = step_data if len(step_data) <= max_samples else step_data[:max_samples]
                    else:
                        step_sample = []
                else:
                    step_sample = []
                
                # Store in the order you specified: context first, then sample
                all_contexts[f"step_{step_num}_context"] = step_context
                all_contexts[f"step_{step_num}_sample"] = step_sample
        
        return all_contexts

    def _analyze_step_data_structures(self, step_results_for_processing: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
        """
        Analyze data structures using Polars to provide schema information to Results Formatter.
        
        Args:
            step_results_for_processing: Dictionary mapping step names to their data
            
        Returns:
            Dictionary mapping step names to their schema information
        """
        step_schemas = {}
        
        for step_name, data in step_results_for_processing.items():
            try:
                # Handle both DataFrames and dictionary data
                if hasattr(data, 'is_empty'):  # Polars DataFrame
                    if data.is_empty():
                        step_schemas[step_name] = {
                            "step_name": step_name,
                            "record_count": 0,
                            "columns": [],
                            "data_type": "empty",
                            "sample_keys": []
                        }
                        continue
                    df = data  # Already a DataFrame
                    dict_data = data.to_dicts()  # Convert for sample_keys
                elif not data:  # Empty list/dict
                    step_schemas[step_name] = {
                        "step_name": step_name,
                        "record_count": 0,
                        "columns": [],
                        "data_type": "empty",
                        "sample_keys": []
                    }
                    continue
                else:
                    # Create Polars DataFrame to analyze structure
                    df = pl.DataFrame(data)
                    dict_data = data
                
                # Get column information
                column_info = []
                for col in df.columns:
                    col_type = str(df[col].dtype)
                    # Get sample non-null value
                    sample_val = df[col].drop_nulls().head(1)
                    sample = sample_val.to_list()[0] if len(sample_val) > 0 else None
                    
                    # Convert sample to JSON-serializable format for large objects
                    if sample is not None:
                        if isinstance(sample, list) and len(sample) > 3:
                            sample = f"[List with {len(sample)} items]"
                        elif isinstance(sample, dict) and len(str(sample)) > 200:
                            sample = f"{{Complex object with {len(sample)} keys}}"
                        elif hasattr(sample, '__dict__'):  # Handle objects
                            sample = str(sample)[:100] + "..." if len(str(sample)) > 100 else str(sample)
                    
                    column_info.append({
                        "name": col,
                        "type": col_type,
                        "sample_value": sample
                    })
                
                # Analyze content type
                key_columns = [col for col in df.columns if 'id' in col.lower()]
                
                step_schemas[step_name] = {
                    "step_name": step_name,
                    "record_count": len(df),  # Use DataFrame length
                    "columns": column_info,
                    "data_type": "flattened_dataframe",
                    "key_columns": key_columns,
                    "sample_keys": list(dict_data[0].keys()) if dict_data else [],
                    "is_user_data": any('user' in col.lower() for col in df.columns),
                    "is_group_data": any('group' in col.lower() for col in df.columns),
                    "is_app_data": any('app' in col.lower() for col in df.columns),
                    "is_role_data": any('role' in col.lower() or 'label' in col.lower() for col in df.columns),
                    "has_nested_data": any('List' in str(df[col].dtype) or 'Struct' in str(df[col].dtype) for col in df.columns)
                }
                
            except Exception as e:
                # Fallback to simple analysis - handle both DataFrame and dict data
                try:
                    if hasattr(data, '__len__'):
                        record_count = len(data)
                    else:
                        record_count = 0
                    
                    if hasattr(data, 'to_dicts'):
                        sample_data = data.to_dicts()
                        sample_keys = list(sample_data[0].keys()) if sample_data else []
                    else:
                        sample_keys = list(data[0].keys()) if data else []
                except:
                    record_count = 0
                    sample_keys = []
                    
                step_schemas[step_name] = {
                    "step_name": step_name,
                    "record_count": record_count,
                    "columns": [],
                    "data_type": "raw_list",
                    "error": str(e),
                    "sample_keys": sample_keys
                }
        
        return step_schemas

    def _get_polars_data_from_previous_step(self, current_step_number: int) -> List[Dict[str, Any]]:
        """
        Get data from the previous step using FULL POLARS architecture.
        
        Args:
            current_step_number: Current step number
            
        Returns:
            List of dictionaries from previous step Polars DataFrame, or empty list if none
        """
        df = self._get_polars_dataframe_from_previous_step(current_step_number)
        if df is not None:
            return df.to_dicts()
        return []
    
    def _get_polars_dataframe_from_previous_step(self, current_step_number: int) -> Optional[pl.DataFrame]:
        """
        Get Polars DataFrame from the previous step for high-performance operations.
        
        Args:
            current_step_number: Current step number
            
        Returns:
            Polars DataFrame from previous step, or None if not available
        """
        if current_step_number <= 1:
            return None
        
        previous_step_num = current_step_number - 1
        step_key = f"step_{previous_step_num}"
        
        if step_key in self.step_metadata:
            variable_name = self.step_metadata[step_key]["variable_name"]
            if variable_name in self.polars_dataframes:
                return self.polars_dataframes[variable_name]
        
        return None
    
    def _generate_data_injection_code(self, current_step_number: int, correlation_id: str, previous_step_key: str = None) -> str:
        """
        Generate Python code that injects previous step data as variables.
        This creates the missing link between enhanced context and execution environment.
        
        CRITICAL: Creates both step_N_sample variables AND full_results dict structure
        for Results Formatter Agent compatibility.
        
        Args:
            current_step_number: Current step number
            correlation_id: Correlation ID for logging
            
        Returns:
            Python code string that creates accessible variables
        """
        import json  # Import here for json.dumps usage
        
        if not current_step_number or current_step_number <= 1:
            return "# No previous step data to inject"
        
        injection_lines = ["# === DATA INJECTION: Previous Step Data ==="]
        
        # Initialize full_results dict for Results Formatter Agent compatibility
        injection_lines.append("# Create full_results structure for Results Formatter Agent")
        injection_lines.append("full_results = {}")
        injection_lines.append("")
        
        # Inject previous step key if provided
        if previous_step_key:
            injection_lines.append("# Previous step key for dynamic data access")
            injection_lines.append(f"previous_step_key = {repr(previous_step_key)}")
            injection_lines.append("")
        
        # Inject data from all previous steps
        for step_num in range(1, current_step_number):
            step_key = f"step_{step_num}"
            
            if step_key in self.step_metadata:
                variable_name = self.step_metadata[step_key]["variable_name"]
                
                # MEMORY OPTIMIZATION: Convert DataFrame to dict only when needed for injection
                if variable_name in self.polars_dataframes:
                    df = self.polars_dataframes[variable_name]
                    step_data = df.to_dicts()  # Convert to dict ONLY for injection
                    # NOTE: Datetime objects are already converted to strings at Cypher query execution
                else:
                    step_data = []
                    
                step_type = self.step_metadata[step_key].get("type", "unknown").lower()
                
                # Create consistent key format: {step_num}_{step_type}
                full_results_key = f"{step_num}_{step_type}"
                
                # Create both the enhanced context variable name AND a simplified version
                step_sample_var = f"step_{step_num}_sample"
                step_context_var = f"step_{step_num}_context"
                
                # Get sample data (first 3 records for context)
                if isinstance(step_data, list):
                    sample_data = step_data[:3] if len(step_data) > 3 else step_data
                else:
                    sample_data = step_data
                
                # Get step context
                step_context = self.step_metadata[step_key].get("step_context", f"Step {step_num} context")
                
                # Inject sample data and full results for code generation
                injection_lines.append(f"# Step {step_num} ({step_type}) data injection")
                injection_lines.append(f"{step_sample_var} = {repr(sample_data)}")
                injection_lines.append(f"{step_context_var} = {repr(step_context)}")
                injection_lines.append(f"full_results['{full_results_key}'] = {repr(step_data)}")
                injection_lines.append("")
        
        # Add debug information for full_results structure (to stderr, not stdout)
        injection_lines.append("# Debug full_results structure for Results Formatter Agent")
        injection_lines.append("import sys")
        injection_lines.append("print(f'DEBUG: full_results keys: {list(full_results.keys())}', file=sys.stderr)")
        injection_lines.append("for key in full_results:")
        injection_lines.append("    if isinstance(full_results[key], list):")
        injection_lines.append("        print(f'DEBUG: full_results[{key}] is a list with {len(full_results[key])} items', file=sys.stderr)")
        injection_lines.append("    else:")
        injection_lines.append("        print(f'DEBUG: full_results[{key}] type: {type(full_results[key]).__name__}', file=sys.stderr)")
        injection_lines.append("")
        
        injection_lines.append("# === END DATA INJECTION ===")
        
        logger.debug(f"[{correlation_id}] Generated data injection code for {current_step_number-1} previous steps with full_results compatibility")
        return "\n".join(injection_lines)
    
    def _clear_execution_data(self):
        """Clear all execution data for fresh run - maintains repeatability."""
        # MEMORY OPTIMIZED: Only clear polars_dataframes (data_variables removed to prevent duplication)
        self.polars_dataframes.clear()  # FULL POLARS ARCHITECTURE: Clear DataFrame storage
        self.step_metadata.clear()
        self.current_step_schemas.clear()  # Clear stored schemas for Results Formatter
        logger.debug("FULL POLARS: Cleared execution data for fresh run")
    
    def cancel_query(self, correlation_id: str, reason: str = "User cancellation"):
        """Aggressively cancel a query - minimal implementation"""
        self.cancelled_queries.add(correlation_id)
        logger.warning(f"[{correlation_id}] QUERY CANCELLED: {reason} - Aggressive termination initiated")
        return True
    
    # END REPEATABLE DATA FLOW METHODS
    
    def _generate_lightweight_reference(self) -> Dict[str, Any]:
        """Generate lightweight API reference from comprehensive sources"""
        try:
            # Load comprehensive API reference - REQUIRED
            api_data = self._load_api_data()
            entity_summary = api_data.get('entity_summary', {})
            
            if not entity_summary:
                raise FileNotFoundError(f"Okta API reference file not found or empty: {self.full_api_path}")
            
            # Load SQL schema - REQUIRED
            schema_path = os.path.join(os.path.dirname(self.simple_ref_path), "okta_schema.json")
            sql_tables = []
            
            with open(schema_path, 'r', encoding='utf-8') as f:
                schema_data = json.load(f)
                # Handle different schema formats
                if 'tables' in schema_data:
                    sql_tables = schema_data['tables']
                elif 'sql_tables' in schema_data:
                    # Convert from object format to array format
                    sql_tables_obj = schema_data['sql_tables']
                    sql_tables = []
                    for table_name, table_info in sql_tables_obj.items():
                        sql_tables.append({
                            "name": table_name,
                            "columns": table_info.get('columns', [])
                        })
                else:
                    raise ValueError(f"Invalid schema format in {schema_path}. Expected 'tables' or 'sql_tables' key.")
            
            if not sql_tables:
                raise ValueError(f"No SQL tables found in schema file: {schema_path}")
            
            # Convert entity summary to entity-grouped format with entity-first naming
            entities = {}
            for entity_name, entity_data in entity_summary.items():
                operations = entity_data.get('operations', [])
                
                # Convert operations to entity-first format: entity_operation
                entity_operations = []
                for operation in operations:
                    entity_operation = f"{entity_name}_{operation}"
                    entity_operations.append(entity_operation)
                
                # Sort operations for consistency
                entity_operations.sort()
                
                entities[entity_name] = {
                    "operations": entity_operations
                }
            
            lightweight_data = {
                "entities": entities,
                "sql_tables": sql_tables
            }
            
            # Save the generated file with compact formatting
            with open(self.simple_ref_path, 'w', encoding='utf-8') as f:
                # Custom JSON formatting to keep arrays on one line
                json_str = json.dumps(lightweight_data, indent=2)
                
                # Post-process to put operations and columns arrays on single lines
                import re
                
                # Pattern for operations arrays
                operations_pattern = r'("operations":\s*\[\s*\n)((?:\s*"[^"]*",?\s*\n?)*?)(\s*\])'
                # Pattern for columns arrays  
                columns_pattern = r'("columns":\s*\[\s*\n)((?:\s*"[^"]*",?\s*\n?)*?)(\s*\])'
                
                def compress_array(match):
                    prefix = match.group(1).split(':')[0] + ':'  # Get the key part
                    array_content = match.group(2)
                    
                    # Extract array items
                    items = re.findall(r'"([^"]*)"', array_content)
                    # Format as single line
                    if items:
                        items_str = ', '.join(f'"{item}"' for item in items)
                        return f'{prefix} [{items_str}]'
                    else:
                        return f'{prefix} []'
                
                # Apply compression to both operations and columns
                json_str = re.sub(operations_pattern, compress_array, json_str, flags=re.MULTILINE)
                json_str = re.sub(columns_pattern, compress_array, json_str, flags=re.MULTILINE)
                
                # Write the formatted JSON
                f.write(json_str)
            
            # Count total operations across all entities
            total_operations = sum(len(entity_data["operations"]) for entity_data in entities.values())
            logger.info(f"Generated lightweight API reference with {total_operations} operations across {len(entities)} entities and {len(sql_tables)} SQL tables")
            return lightweight_data
            
        except FileNotFoundError as e:
            error_msg = f"Required source file missing: {e}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)
        except Exception as e:
            error_msg = f"Failed to generate lightweight reference: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def _load_simple_reference(self) -> Dict[str, Any]:
        """Load simple reference format for planning, generating it if missing"""
        try:
            with open(self.simple_ref_path, 'r', encoding='utf-8') as f:
                simple_ref = json.load(f)
            
            # INTEGRATION: Merge special tools into entities for pre-planning agent
            from src.core.tools.special_tools import get_lightweight_references
            try:
                special_tools_refs = get_lightweight_references()
                logger.info(f"Discovered {len(special_tools_refs)} special tools for integration")
                
                # Merge special tools into entities section
                entities = simple_ref.get('entities', {})
                for special_tool in special_tools_refs:
                    if 'entities' in special_tool:
                        entities.update(special_tool['entities'])
                        logger.debug(f"Integrated special tool entities: {list(special_tool['entities'].keys())}")
                
                simple_ref['entities'] = entities
                #logger.info(f"Total entities available for pre-planning: {len(entities)}")
                
            except Exception as e:
                logger.warning(f"Failed to load special tools: {e} - continuing with standard entities only")
            
            return simple_ref
        except FileNotFoundError:
            logger.warning(f"Simple reference file not found: {self.simple_ref_path}")
            logger.info("Generating lightweight API reference from comprehensive sources...")
            return self._generate_lightweight_reference()
        except Exception as e:
            logger.error(f"Failed to load simple reference: {e}")
            logger.info("Attempting to regenerate lightweight API reference...")
            return self._generate_lightweight_reference()

    def _load_api_data(self) -> Dict[str, Any]:
        """Load full API entity data for endpoint filtering"""
        try:
            with open(self.full_api_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning(f"Full API data file not found: {self.full_api_path}")
            return {'endpoints': []}
        except Exception as e:
            logger.error(f"Failed to load full API data: {e}")
            return {'endpoints': []}
    
    def _build_graph_schema(self) -> str:
        """
        Get the complete GraphDB schema description for planning agents.
        
        Returns the full schema text from get_graph_schema_description() which includes:
        - All node types with complete property lists
        - All relationship types with properties
        - Query examples and patterns
        - Status values and common patterns
        
        This is returned as a string (not Dict) to provide maximum context to LLMs.
        """
        try:
            # Use the existing comprehensive schema documentation
            from src.core.okta.graph_db.schema_v2_enhanced import get_graph_schema_description
            
            # Get the full schema description text
            schema_text = get_graph_schema_description()
            
            # Log the schema length to verify it's being loaded
            #logger.info(f"GraphDB schema description loaded: {len(schema_text)} characters")
            #logger.debug(f"GraphDB schema first 500 chars: {schema_text[:500]}")
            
            return schema_text
            
        except Exception as e:
            logger.warning(f"Failed to load GraphDB schema: {e}")
            # Return minimal schema as fallback
            return "GraphDB schema unavailable"

    
    def _get_entity_endpoints_for_entity(self, entity_name: str) -> List[Dict[str, Any]]:
        """Get all endpoints for a specific entity, including depends_on endpoints"""
        entity = entity_name.lower()
        
        # Get all endpoints for this entity
        entity_endpoints = []
        for endpoint in self.endpoints:
            if endpoint.get('entity', '').lower() == entity:
                # SECURITY VALIDATION: Validate endpoint before including
                security_result = validate_api_endpoint(endpoint)
                if security_result.is_valid:
                    entity_endpoints.append(endpoint)
                else:
                    logger.warning(f"Endpoint filtered for security: {endpoint.get('id', 'unknown')} - {'; '.join(security_result.violations)}")
        
        # Get depends_on endpoints for all matched endpoints
        depends_on_endpoints = self._get_depends_on_endpoints(entity_endpoints)
        
        # Combine and return unique endpoints
        all_endpoints = entity_endpoints + depends_on_endpoints
        seen_ids = set()
        unique_endpoints = []
        for ep in all_endpoints:
            if ep.get('id') not in seen_ids:
                unique_endpoints.append(ep)
                seen_ids.add(ep.get('id'))
        
        return unique_endpoints
    
    def _get_entity_endpoints_for_step(self, step: ExecutionStep) -> List[Dict[str, Any]]:
        """Get filtered endpoints for a specific API step, including depends_on endpoints"""
        # Use the entity field from the new format
        entity_name = step.entity
        if not entity_name:
            logger.warning(f"No entity specified in step: {step}")
            return []
        
        entity = entity_name.lower()
        raw_operation = getattr(step, 'operation', None) or 'list'  # Default to list
        
        # Parse entity_operation format (e.g., "group_list" -> entity="group", operation="list")
        if raw_operation and '_' in raw_operation and raw_operation in self.operation_mapping:
            # Use operation mapping to get the actual entity and operation
            mapping = self.operation_mapping[raw_operation]
            entity = mapping['entity'].lower()
            operation = mapping['operation'].lower()
            logger.debug(f"Mapped entity_operation '{raw_operation}' to entity='{entity}', operation='{operation}'")
        else:
            operation = raw_operation.lower()
        
        operations = [operation]
        methods = ['GET']  # Default to GET for most operations
        
        # Get matches with precise filtering
        matches = self._get_entity_operation_matches(entity, operations, methods)
        
        # NEW: Include depends_on endpoints for each matched endpoint
        depends_on_endpoints = self._get_depends_on_endpoints(matches)
        
        # Combine primary matches with dependency endpoints, removing duplicates
        all_endpoints = matches + depends_on_endpoints
        seen_ids = set()
        unique_endpoints = []
        for ep in all_endpoints:
            if ep.get('id') not in seen_ids:
                unique_endpoints.append(ep)
                seen_ids.add(ep.get('id'))
        
        # Log detailed info if no matches found for debugging
        if not matches:
            available_for_entity = [ep for ep in self.endpoints if ep.get('entity', '').lower() == entity]
            logger.error(f"No endpoint matches found for entity='{entity}', operation='{operation}', methods={methods}")
            logger.error(f"Available endpoints for entity '{entity}': {[ep.get('operation') for ep in available_for_entity]}")
            if available_for_entity:
                logger.error(f"First available endpoint for '{entity}': {available_for_entity[0]}")
        
        return unique_endpoints
    
    def _get_entity_operation_matches(self, entity: str, operations: List[str], methods: List[str]) -> List[Dict]:
        """Get endpoints matching entity + operation + method (copied from old executor)"""
        matches = []
        
        for endpoint in self.endpoints:
            if self._is_precise_match(endpoint, entity, operations, methods):
                # SECURITY VALIDATION: Validate endpoint before including
                security_result = validate_api_endpoint(endpoint)
                if security_result.is_valid:
                    matches.append(endpoint)
                else:
                    logger.warning(f"Endpoint filtered for security: {endpoint.get('id', 'unknown')} - {'; '.join(security_result.violations)}")
        
        return matches
    
    def _get_depends_on_endpoints(self, matched_endpoints: List[Dict]) -> List[Dict]:
        """Get endpoints that the matched endpoints depend on"""
        depends_on_endpoints = []
        
        for endpoint in matched_endpoints:
            depends_on_ids = endpoint.get('depends_on', [])
            if depends_on_ids:
                for dep_id in depends_on_ids:
                    # Find the dependency endpoint by ID
                    dep_endpoint = next((ep for ep in self.endpoints if ep.get('id') == dep_id), None)
                    if dep_endpoint:
                        # Validate security for dependency endpoint as well
                        security_result = validate_api_endpoint(dep_endpoint)
                        if security_result.is_valid:
                            depends_on_endpoints.append(dep_endpoint)
                        else:
                            logger.warning(f"Dependency endpoint filtered for security: {dep_id} - {'; '.join(security_result.violations)}")
                    else:
                        logger.warning(f"Dependency endpoint not found: {dep_id}")
        
        return depends_on_endpoints
    
    def _is_precise_match(self, endpoint: Dict, target_entity: str, operations: List[str], methods: List[str]) -> bool:
        """Check if endpoint matches entity + operation + method criteria (copied from old executor)"""
        
        # 1. Method must match exactly
        endpoint_method = endpoint.get('method', '').upper()
        if endpoint_method not in methods:
            return False
        
        # 2. Entity must match exactly  
        endpoint_entity = endpoint.get('entity', '').lower()
        if endpoint_entity != target_entity.lower():
            return False
        
        # 3. Operation must match (with some semantic flexibility)
        endpoint_operation = endpoint.get('operation', '').lower()
        if not self._operation_matches(endpoint_operation, operations):
            return False
        
        return True
    
    def _operation_matches(self, endpoint_op: str, requested_ops: List[str]) -> bool:
        """Check if endpoint operation matches any requested operation - PRECISE MATCHING ONLY"""
        for requested_op in requested_ops:
            if endpoint_op.lower() == requested_op.lower():
                return True
        return False
    
    async def execute_query(self, query: str, force_api_only: bool = False) -> Dict[str, Any]:
        """
        Main execution method for complex multi-step query processing.
        
        Flow:
        1. Generate/use existing correlation ID
        2. Check database health and API-only mode requirements
        3. Use Planning Agent to generate execution plan
        4. Execute steps using Modern Execution Manager
        5. Return structured results
        
        Args:
            query: Natural language query to execute
            force_api_only: Flag to force API-only mode (from frontend)
            
        Returns:
            Dict with success status, results, and correlation_id
        """
        from datetime import datetime
        from utils.logging import get_correlation_id, set_correlation_id
        
        # Use existing correlation ID if available, otherwise generate new one
        existing_correlation_id = get_correlation_id()
        if existing_correlation_id:
            correlation_id = existing_correlation_id
            logger.info(f"[{correlation_id}] Using existing correlation ID for query: {query}")
        else:
            correlation_id = f"modern_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            logger.info(f"[{correlation_id}] Generated new correlation ID for query: {query}")
            set_correlation_id(correlation_id)
        
        try:
            logger.info(f"[{correlation_id}] Starting Modern Execution Manager query execution")
            
            # Log AI provider configuration
            ai_provider = os.getenv('AI_PROVIDER', 'not_set')
            logger.info(f"[{correlation_id}] AI_PROVIDER: {ai_provider}")
            
            # NEW: Check database health and API-only mode requirements
            should_use_api_only, modified_query = self._should_force_api_only_mode(query, force_api_only)
            
            if should_use_api_only:
                logger.info(f"[{correlation_id}] Query will be executed in API-only mode")
            else:
                logger.info(f"[{correlation_id}] Query will use both SQL and API modes as planned")
            
            # Phase 0: Pre-Planning - Entity and Operation Selection
            logger.debug(f"[{correlation_id}] Phase 0: Pre-Planning Agent execution")
            
            # Track timing for thinking step
            thinking_start_time = time.time()
            
            # STEP-START for pre-planning phase (step 0)
            if self.step_start_callback:
                try:
                    await self.step_start_callback(
                        step_number=0,
                        step_type="thinking", 
                        step_name="Step 0: Analyzing Requirements",
                        query_context="Analyzing query requirements and selecting relevant entities", 
                        critical=True,
                        formatted_time=time.strftime('%H:%M:%S', time.localtime(thinking_start_time))
                    )
                except Exception as cb_err:
                    logger.debug(f"[{correlation_id}] step_start_callback preplan error ignored: {cb_err}")
            
            # Use the enhanced pre-planning agent to select relevant entities
            from src.core.agents.preplan_agent import select_relevant_entities
            
            # Get the lightweight reference data for entity selection
            lightweight_ref = self.simple_ref_data
            entities_dict = lightweight_ref.get('entities', {})
            
            preplan_result = await select_relevant_entities(
                query=modified_query,
                entity_summary=self.entity_summary,
                graph_schema=self.graph_schema,
                flow_id=correlation_id,
                available_entities=list(entities_dict.keys()) if entities_dict else None,
                entities=entities_dict
            )
            
            if not preplan_result.get('success', False):
                logger.error(f"[{correlation_id}] Pre-planning failed: {preplan_result.get('error', 'Unknown error')}")
                
                # Calculate thinking step duration
                thinking_end_time = time.time()
                thinking_duration = thinking_end_time - thinking_start_time
                
                # STEP-END for failed pre-planning phase (step 0)
                if self.step_end_callback:
                    try:
                        await self.step_end_callback(
                            step_number=0,
                            step_type="thinking",
                            success=False,
                            duration_seconds=round(thinking_duration, 2),
                            record_count=0,
                            formatted_time=time.strftime('%H:%M:%S', time.localtime(thinking_end_time)),
                            error_message=f"Pre-planning failed: {preplan_result.get('error', 'Unknown error')}"
                        )
                    except Exception as cb_err:
                        logger.debug(f"[{correlation_id}] step_end_callback preplan error ignored: {cb_err}")
                
                return {
                    'success': False,
                    'error': f"Pre-planning failed: {preplan_result.get('error', 'Unknown error')}",
                    'correlation_id': correlation_id,
                    'query': query,
                    'phase': 'preplan_error'
                }
            
            selected_entity_operations = preplan_result['selected_entity_operations']
            entity_op_pairs = [f"{eo.entity}::{eo.operation or 'null'}" for eo in selected_entity_operations]
            logger.info(f"[{correlation_id}] Pre-planning completed: selected entity-operation pairs {entity_op_pairs}")
            
            # Calculate thinking step duration  
            thinking_end_time = time.time()
            thinking_duration = thinking_end_time - thinking_start_time
            
            # STEP-END for pre-planning phase (step 0)
            if self.step_end_callback:
                try:
                    await self.step_end_callback(
                        step_number=0,
                        step_type="thinking",
                        success=True,
                        duration_seconds=round(thinking_duration, 2),
                        record_count=len(entity_op_pairs),
                        formatted_time=time.strftime('%H:%M:%S', time.localtime(thinking_end_time)),
                        error_message=None
                    )
                except Exception as cb_err:
                    logger.debug(f"[{correlation_id}] step_end_callback preplan error ignored: {cb_err}")
            
            # CHECK FOR SQL-ONLY SCENARIO: No API entities needed
            if not selected_entity_operations:
                logger.info(f"[{correlation_id}] Pre-planning determined SQL-only query - bypassing API endpoint filtering")
                unique_endpoints = []
                endpoint_based_entities = {}
                filtered_entity_summary = {}
            else:
                # Get full endpoint data for selected entity-operation pairs using existing filtering
                logger.info(f"[{correlation_id}] Filtering endpoints for selected entity-operation pairs...")
                selected_entity_endpoints = []
                
                for entity_op in selected_entity_operations:
                    entity_name = entity_op.entity.lower()
                    operation = entity_op.operation
                    
                    if operation and operation != 'null':
                        # Create a mock ExecutionStep to use existing filtering method
                        mock_step = ExecutionStep(
                            tool_name="api",
                            entity=entity_name,
                            operation=operation,
                            query_context="Mock step for filtering",
                            reasoning="Generated for endpoint filtering"
                        )
                        entity_endpoints = self._get_entity_endpoints_for_step(mock_step)
                    else:
                        # Just get entity endpoints without specific operation
                        entity_endpoints = self._get_entity_endpoints_for_entity(entity_name)
                    
                    selected_entity_endpoints.extend(entity_endpoints)
                    logger.debug(f"[{correlation_id}] Found {len(entity_endpoints)} endpoints for {entity_name}::{operation or 'all'}")
                
                # Remove duplicates based on endpoint ID
                seen_ids = set()
                unique_endpoints = []
                for endpoint in selected_entity_endpoints:
                    if endpoint.get('id') not in seen_ids:
                        unique_endpoints.append(endpoint)
                        seen_ids.add(endpoint.get('id'))
                
                logger.info(f"[{correlation_id}] Filtered to {len(unique_endpoints)} unique endpoints from {len(selected_entity_operations)} entity-operation pairs")
                
                # Build entity summary from filtered endpoints instead of raw entities
                filtered_entity_summary = {}
                endpoint_based_entities = {}
                
                # Group filtered endpoints by entity to create focused entity data
                for endpoint in unique_endpoints:
                    entity_name = endpoint.get('entity', '')
                    if entity_name:
                        if entity_name not in endpoint_based_entities:
                            endpoint_based_entities[entity_name] = {'endpoints': []}  # Use 'endpoints' not 'operations'
                            filtered_entity_summary[entity_name] = {'operations': [], 'methods': []}
                        
                        # Add the FULL endpoint details for planning agent
                        endpoint_based_entities[entity_name]['endpoints'].append(endpoint)
                        
                        # Add operation and method for summary
                        operation = endpoint.get('operation', '')
                        method = endpoint.get('method', 'GET')
                        
                        if operation and operation not in filtered_entity_summary[entity_name]['operations']:
                            filtered_entity_summary[entity_name]['operations'].append(operation)
                        
                        if method and method not in filtered_entity_summary[entity_name]['methods']:
                            filtered_entity_summary[entity_name]['methods'].append(method)            # Phase 1: Use Planning Agent to generate execution plan
            logger.debug(f"[{correlation_id}] Phase 1: Planning Agent execution")
            # Notify planning start (minimal hook)
            if self.planning_phase_callback:
                try:
                    await self.planning_phase_callback('planning_start')
                except Exception as cb_err:
                    logger.debug(f"[{correlation_id}] planning_phase_callback planning_start error ignored: {cb_err}")
            
            # Track timing for generating_steps step
            generating_start_time = time.time()
            
            # STEP-START for planning phase (step 1, consistent step numbering)
            if self.step_start_callback:
                try:
                    await self.step_start_callback(
                        step_number=1,
                        step_type="generating_steps",
                        step_name="Step 1: Generating Execution Plan",
                        query_context="Creating detailed execution plan from selected entities",
                        critical=True,
                        formatted_time=time.strftime('%H:%M:%S', time.localtime(generating_start_time))
                    )
                except Exception as cb_err:
                    logger.debug(f"[{correlation_id}] step_start_callback planning error ignored: {cb_err}")
            
            # Create dependencies for Planning Agent with filtered endpoint data
            logger.info(f"[{correlation_id}] Built focused entity data: {len(endpoint_based_entities)} entities with {len(unique_endpoints)} endpoints")
            
            planning_deps = PlanningDependencies(
                available_entities=list(endpoint_based_entities.keys()),  # Use filtered entity names
                entity_summary=filtered_entity_summary,  # Use filtered entity summary
                graph_schema=self.graph_schema,
                flow_id=correlation_id,
                entities=endpoint_based_entities  # Pass the filtered entity-grouped format
            )
            
            # Execute Planning Agent with dependencies - use modified query if needed
            try:
                logger.info(f"[{correlation_id}] Calling planning agent with query: {modified_query}")
                planning_result = await planning_agent.run(modified_query, deps=planning_deps)
                
                # Trust the agent - just extract the plan
                execution_plan = planning_result.output.plan
                
                logger.info(f"[{correlation_id}] Planning agent completed successfully")
                
            except Exception as planning_error:
                # Specific error handling for planning agent failures with enhanced sanitization
                error_msg = str(planning_error)
                logger.error(f"[{correlation_id}] Planning Agent failed: {error_msg}")
                
                # Sanitize error messages to prevent sensitive information exposure
                user_friendly_error = self._sanitize_planning_error(error_msg)
                
                # Return a structured error response that matches the expected format
                return {
                    'success': False,
                    'error': user_friendly_error,
                    'correlation_id': correlation_id,
                    'query': query,
                    'phase': 'planning_error',
                    'planning_error': True  # Flag to indicate this is a planning-specific error
                }
            
            # Store current execution plan for external access (minimal addition for realtime interface)
            self.current_execution_plan = execution_plan
            
            # Notify callback if plan is ready (minimal addition for realtime interface)
            if self.plan_ready_callback:
                await self.plan_ready_callback(execution_plan)
            
            # Calculate generating_steps duration
            generating_end_time = time.time()
            generating_duration = generating_end_time - generating_start_time
            
            # STEP-END for planning phase (step 1, consistent step numbering) - SEND FIRST
            if self.step_end_callback:
                try:
                    await self.step_end_callback(
                        step_number=1,
                        step_type="generating_steps",
                        success=True,
                        duration_seconds=round(generating_duration, 2),
                        record_count=len(execution_plan.steps),
                        formatted_time=time.strftime('%H:%M:%S', time.localtime(generating_end_time)),
                        error_message=None
                    )
                except Exception as cb_err:
                    logger.debug(f"[{correlation_id}] step_end_callback planning error ignored: {cb_err}")
            
            # NEW STANDARDIZED: PLAN-GENERATED callback - SEND AFTER STEP-END 
            if self.plan_generated_callback:
                try:
                    await self.plan_generated_callback(
                        plan=execution_plan.model_dump(),
                        step_count=len(execution_plan.steps),
                        formatted_time=time.strftime('%H:%M:%S', time.localtime()),
                        estimated_duration="30-60 seconds"  # Could be calculated based on step types
                    )
                except Exception as callback_error:
                    logger.warning(f"[{correlation_id}] Plan generated callback error: {callback_error}")
            
            # Pretty print the execution plan for debugging
            import json
            logger.info(f"[{correlation_id}] Generated execution plan:\n{json.dumps(execution_plan.model_dump(), indent=2)}")
            logger.info(f"[{correlation_id}] Planning completed: {len(execution_plan.steps)} steps generated")
            # Notify planning complete (after plan object finalized, before execution)
            if self.planning_phase_callback:
                try:
                    await self.planning_phase_callback('planning_complete')
                except Exception as cb_err:
                    logger.debug(f"[{correlation_id}] planning_phase_callback planning_complete error ignored: {cb_err}")
            
            # Phase 2: Execute steps using Modern Execution Manager
            logger.debug(f"[{correlation_id}] Phase 2: Step execution with Modern Execution Manager")
            execution_results = await self.execute_steps(execution_plan, correlation_id)
            
            # SIMPLE CANCELLATION CHECK: If fewer steps completed than planned, query was likely cancelled
            if execution_results.successful_steps < len(execution_plan.steps):
                logger.warning(f"[{correlation_id}] QUERY INCOMPLETE - Only {execution_results.successful_steps}/{len(execution_plan.steps)} steps completed, skipping results formatting")
                return {
                    "success": False,
                    "data": [],
                    "error": "Query execution incomplete - likely cancelled",
                    "cancelled": True,
                    "steps_completed": execution_results.successful_steps,
                    "total_steps": len(execution_plan.steps)
                }
            
            # Process results through Results Formatter Agent (like old executor)
            logger.info(f"[{correlation_id}] Processing results through Results Formatter Agent...")
            
            # Build step_results_for_processing using DATAFRAME REFERENCES (MEMORY OPTIMIZED)
            step_results_for_processing = {}
            raw_results = {}
            
            # Build step results for processing with DATAFRAME REFERENCES (No conversion yet)
            for i, step_result in enumerate(execution_results.steps, 1):
                # Preserve original step type for consistent key usage throughout pipeline
                step_type_key = step_result.step_type.lower()
                step_name = f"{i}_{step_type_key}"
                
                if step_result.success and step_result.result:
                    # Generic approach: Try multiple variable name patterns for any step type
                    step_type_lower = step_result.step_type.lower()
                    possible_variable_names = [
                        f"{step_type_lower}_data_step_{i}",           # e.g., api_sql_data_step_2
                        f"{step_type_lower.replace('_', '')}_data_step_{i}",  # e.g., apisql_data_step_2
                        f"{'_'.join(step_type_lower.split('_'))}_data_step_{i}",  # e.g., api_sql_data_step_2
                        f"sql_data_step_{i}",                        # legacy SQL pattern
                        f"api_data_step_{i}",                        # legacy API pattern
                    ]
                    
                    # MEMORY EFFICIENT: Store DataFrame reference, not converted data
                    found_dataframe = None
                    found_variable = None
                    for variable_name in possible_variable_names:
                        if variable_name in self.polars_dataframes:
                            found_dataframe = self.polars_dataframes[variable_name]
                            found_variable = variable_name
                            break
                    
                    if found_dataframe is not None:
                        # MEMORY OPTIMIZATION: Store DataFrame reference, convert only when needed
                        step_results_for_processing[step_name] = found_dataframe  # DataFrame reference!
                        
                        record_count = len(found_dataframe)
                        # logger.debug(f"[{correlation_id}] MEMORY EFFICIENT: Added {step_result.step_type} DataFrame from {found_variable}: {record_count} records")
                    else:
                        logger.warning(f"[{correlation_id}] FULL POLARS: No data found for {step_result.step_type} step {i} (tried: {possible_variable_names})")
            
            # Log total data being passed to Results Formatter (count from DataFrames)
            total_records = sum(len(df) for df in step_results_for_processing.values() if hasattr(df, '__len__'))
            logger.info(f"[{correlation_id}] Passing {total_records} total records to Results Formatter")
            
            # Analyze data structure using Polars for Results Formatter
            step_schemas = self._analyze_step_data_structures(step_results_for_processing)
            logger.debug(f"[{correlation_id}] Generated data structure schemas for Results Formatter: {list(step_schemas.keys())}")
            
            # Store step schemas for data injection code (needed to recreate schema-enhanced structure)
            self.current_step_schemas = step_schemas
            
            # EXECUTION DECISION SWITCH: Determine processing path based on plan characteristics
            # 1. SQL-only queries → Skip relationship analysis → Let results formatter handle single SQL optimization
            # 2. Complete data → Skip relationship analysis → Send directly to results formatter with is_sample=False
            # 3. Complex multi-step → Use full three-stage pipeline with relationship analysis
            
            # Import sampling utilities
            from .sampling_utils import estimate_token_count, create_intelligent_samples
            
            # Estimate tokens for relationship analysis decision using existing utility
            # Convert DataFrames to dict format for token estimation
            step_results_dict_for_estimation = {}
            for key, dataframe in step_results_for_processing.items():
                if hasattr(dataframe, 'to_dicts'):  # Polars DataFrame
                    step_results_dict_for_estimation[key] = dataframe.to_dicts()
                else:
                    step_results_dict_for_estimation[key] = dataframe
            
            estimated_tokens = estimate_token_count(step_results_dict_for_estimation)
            token_threshold = int(os.getenv('TOKEN_THRESHOLD', '5000'))  # Default 5K tokens threshold
            
            # Check if any step uses special tools that need complete processing
            has_special_tool = any(
                step.tool_name == 'special_tool'
                for step in execution_plan.steps
            )
            
            is_single_step = len(execution_plan.steps) == 1  # ANY single step (SQL, API, or special_tool) - no relationships to analyze
            is_complete_data = estimated_tokens <= token_threshold or has_special_tool  # Complete data = under token threshold OR access analysis tools
            
            logger.info(f"[{correlation_id}] Decision factors: single_step={is_single_step}, tokens={estimated_tokens:,}, threshold={token_threshold:,}, access_analysis={has_special_tool}, complete_data={is_complete_data}")
            
            if is_single_step:
                step_type = execution_plan.steps[0].tool_name.lower()
                logger.info(f"[{correlation_id}] Single-step query detected ({step_type}) - skipping relationship analysis, no cross-step relationships to analyze")
                relationship_analysis = None
            elif is_complete_data:
                if has_special_tool:
                    logger.info(f"[{correlation_id}] Access analysis tool detected - forcing complete data processing regardless of tokens ({estimated_tokens:,})")
                else:
                    logger.info(f"[{correlation_id}] Complete data processing ({estimated_tokens:,} tokens under {token_threshold:,} threshold) - skipping relationship analysis")
                relationship_analysis = None
            else:
                # STAGE 1: Relationship Analysis (Three-Stage Pipeline)
                # Analyze data relationships before results formatting for complex multi-step data
                relationship_analysis = None
                if estimated_tokens > token_threshold:  # Only do relationship analysis for complex datasets (token-based)
                    try:
                        # Calculate step number for Analysis Agent (after execution steps but before Results Formatter)
                        analysis_step_number = len(execution_results.steps) + 2  # +2 for thinking(0) + generating_steps(1) + execution steps
                        analysis_start_time = time.time()
                        
                        # NEW STANDARDIZED: STEP-START for Analysis Agent
                        if self.step_start_callback:
                            try:
                                await self.step_start_callback(
                                    step_number=analysis_step_number,
                                    step_type="relationship_analysis",
                                    step_name=f"Step {analysis_step_number}: Analyzing Data Relationships",
                                    query_context="Analyzing data relationships and cross-step joins for complex dataset processing",
                                    critical=True,
                                    formatted_time=time.strftime('%H:%M:%S', time.localtime(analysis_start_time))
                                )
                            except Exception as callback_error:
                                logger.warning(f"[{correlation_id}] Analysis agent start callback error: {callback_error}")
                        
                        # Notify analysis phase callback - analysis starting (legacy callback, keep for compatibility)
                        if self.analysis_phase_callback:
                            try:
                                await self.analysis_phase_callback('analysis_start')
                            except Exception as cb_err:
                                logger.debug(f"[{correlation_id}] analysis_phase_callback analysis_start error ignored: {cb_err}")
                        
                        logger.info(f"[{correlation_id}] Stage 1: Running relationship analysis on {total_records} records ({estimated_tokens:,} tokens)")
                        
                        # Use existing sampling utility for relationship analysis
                        sample_data_for_analysis = create_intelligent_samples(
                            step_results_dict_for_estimation  # Use default max_records_per_step=5
                        )
                        
                        relationship_analysis = await analyze_data_relationships(
                            sample_data=sample_data_for_analysis,  # Intelligent samples using existing utility
                            correlation_id=correlation_id,
                            query=query
                        )
                        
                        # Calculate Analysis Agent duration and metrics
                        analysis_end_time = time.time()
                        analysis_duration = analysis_end_time - analysis_start_time
                        analysis_success = relationship_analysis is not None
                        
                        logger.info(f"[{correlation_id}] Stage 1: Relationship analysis completed")
                        
                        # NEW STANDARDIZED: STEP-END for Analysis Agent 
                        if self.step_end_callback:
                            try:
                                await self.step_end_callback(
                                    step_number=analysis_step_number,
                                    step_type="relationship_analysis",
                                    success=analysis_success,
                                    duration_seconds=round(analysis_duration, 2),
                                    record_count=len(relationship_analysis.get('cross_step_joins', {})) if analysis_success else 0,
                                    formatted_time=time.strftime('%H:%M:%S', time.localtime(analysis_end_time)),
                                    error_message=None
                                )
                            except Exception as callback_error:
                                logger.warning(f"[{correlation_id}] Analysis agent end callback error: {callback_error}")
                        
                        # Notify analysis phase callback - analysis complete (legacy callback, keep for compatibility)
                        if self.analysis_phase_callback:
                            try:
                                await self.analysis_phase_callback('analysis_complete')
                            except Exception as cb_err:
                                logger.debug(f"[{correlation_id}] analysis_phase_callback analysis_complete error ignored: {cb_err}")
                                
                    except Exception as e:
                        # Calculate duration for failed analysis
                        analysis_end_time = time.time()
                        analysis_duration = analysis_end_time - analysis_start_time if 'analysis_start_time' in locals() else 0
                        
                        logger.warning(f"[{correlation_id}] Stage 1: Relationship analysis failed: {e}")
                        relationship_analysis = None
                        
                        # NEW STANDARDIZED: STEP-END for failed Analysis Agent
                        if self.step_end_callback:
                            try:
                                await self.step_end_callback(
                                    step_number=analysis_step_number if 'analysis_step_number' in locals() else 0,
                                    step_type="relationship_analysis",
                                    success=False,
                                    duration_seconds=round(analysis_duration, 2),
                                    record_count=0,
                                    formatted_time=time.strftime('%H:%M:%S', time.localtime(analysis_end_time)),
                                    error_message=str(e)
                                )
                            except Exception as callback_error:
                                logger.warning(f"[{correlation_id}] Analysis agent error callback error: {callback_error}")
                        
                        # Notify analysis phase callback - analysis error (legacy callback, keep for compatibility)
                        if self.analysis_phase_callback:
                            try:
                                await self.analysis_phase_callback('analysis_error')
                            except Exception as cb_err:
                                logger.debug(f"[{correlation_id}] analysis_phase_callback analysis_error error ignored: {cb_err}")

            # Modern Execution Manager decides sample vs complete processing based on token size
            try:
                logger.info(f"[{correlation_id}] Dataset analysis: {total_records} records, {estimated_tokens:,} estimated tokens, threshold: {token_threshold:,}")
                
                # Determine processing strategy based on estimated token size (use already calculated values)
                if is_complete_data:
                    # Complete processing for datasets under token threshold OR access analysis tools
                    use_sample_processing = False
                    if has_special_tool:
                        logger.info(f"[{correlation_id}] Access analysis mode - using complete processing (tokens: {estimated_tokens:,})")
                    else:
                        logger.info(f"[{correlation_id}] Complete data mode - using complete processing (tokens: {estimated_tokens:,} <= {token_threshold:,})")
                else:
                    # Use token-based decision for regular datasets
                    use_sample_processing = estimated_tokens > token_threshold
                    logger.info(f"[{correlation_id}] Token-based decision: {'sample' if use_sample_processing else 'complete'} processing (tokens: {estimated_tokens:,} vs threshold: {token_threshold:,})")
                
                # Include relationship analysis in metadata for enhanced processing
                formatter_metadata = {
                    "flow_id": correlation_id, 
                    "step_schemas": step_schemas,
                    "relationship_analysis": relationship_analysis  # Stage 1 results for Stage 2 code generation
                }
                
                # ROUTING DECISION: Send appropriate data based on processing strategy
                if use_sample_processing and relationship_analysis:
                    # Large dataset: Send SAMPLES + relationship analysis to Results Formatter
                    results_for_formatter = sample_data_for_analysis  # Already created above for relationship analysis
                    logger.info(f"[{correlation_id}] Sending samples + relationship analysis to Results Formatter (large dataset)")
                else:
                    # Small dataset: Send FULL DATA to Results Formatter (no relationship analysis needed)
                    step_results_dict = {}
                    for key, dataframe in step_results_for_processing.items():
                        if hasattr(dataframe, 'to_dicts'):  # Polars DataFrame
                            step_results_dict[key] = dataframe.to_dicts()
                        else:
                            step_results_dict[key] = dataframe
                    results_for_formatter = step_results_dict
                    logger.info(f"[{correlation_id}] Sending full data to Results Formatter (small dataset)")
                
                # Calculate step number for Results Formatter (after analysis step if it ran)
                formatter_step_number = len(execution_results.steps) + 2  # +2 for thinking(0) + generating_steps(1) + execution steps
                if relationship_analysis:
                    formatter_step_number += 1  # +1 more if analysis step ran before this
                formatter_start_time = time.time()
                
                # NEW STANDARDIZED: STEP-START for Results Formatter
                if self.step_start_callback:
                    try:
                        await self.step_start_callback(
                            step_number=formatter_step_number,
                            step_type="results_formatter",
                            step_name=f"Step {formatter_step_number}: Formatting Results",
                            query_context="Processing and formatting execution results for user presentation",
                            critical=True,
                            formatted_time=time.strftime('%H:%M:%S', time.localtime(formatter_start_time))
                        )
                    except Exception as callback_error:
                        logger.warning(f"[{correlation_id}] Results formatter start callback error: {callback_error}")
                
                formatted_response = await process_results_formatter(
                    query=query,
                    results=results_for_formatter,  # Samples for large datasets, full data for small datasets
                    is_sample=use_sample_processing,  # Modern execution manager makes the decision
                    relationship_analysis=relationship_analysis,  # Pass relationship analysis instead of original plan
                    metadata=formatter_metadata
                )
                
                # Calculate Results Formatter duration and metrics
                formatter_end_time = time.time()
                formatter_duration = formatter_end_time - formatter_start_time
                formatter_success = formatted_response is not None and not formatted_response.get('usage_info', {}).get('error')
                
                # NEW STANDARDIZED: STEP-END for Results Formatter
                if self.step_end_callback:
                    try:
                        await self.step_end_callback(
                            step_number=formatter_step_number,
                            step_type="results_formatter",
                            success=formatter_success,
                            duration_seconds=round(formatter_duration, 2),
                            record_count=1,  # Results formatter produces 1 formatted response
                            formatted_time=time.strftime('%H:%M:%S', time.localtime(formatter_end_time)),
                            error_message=formatted_response.get('usage_info', {}).get('error') if not formatter_success else None
                        )
                    except Exception as callback_error:
                        logger.warning(f"[{correlation_id}] Results formatter end callback error: {callback_error}")
                
                logger.info(f"[{correlation_id}] Results formatting completed with {formatted_response.get('display_type', 'unknown')} format")
                logger.debug(f"[{correlation_id}] Formatted response keys: {list(formatted_response.keys())}")
                
                # CHECK FOR PROCESSING CODE: If Results Formatter generated processing code, execute it (same pattern as API/SQL agents)
                if formatted_response.get('processing_code') and formatted_response['processing_code'].strip():
                    logger.info(f"[{correlation_id}] Results Formatter generated processing code - executing with security validation")
                    
                    # Execute the processing code with same security validation as API/SQL code
                    processing_execution_result = await self._execute_generated_code(
                        formatted_response['processing_code'], 
                        correlation_id, 
                        step=None,  # No specific step for results processing
                        current_step_number=len(execution_results.steps) + 1  # After all steps
                    )
                    
                    if processing_execution_result.get('success', False):
                        # Replace placeholder content with actual processed data
                        processed_data = processing_execution_result.get('output', [])
                        logger.info(f"[{correlation_id}] Processing code execution successful - updating formatted response with actual data")
                        formatted_response['content'] = processed_data
                        
                        # Update metadata to reflect successful processing
                        if 'metadata' in formatted_response:
                            formatted_response['metadata']['processing_executed'] = True
                            formatted_response['metadata']['actual_results'] = len(processed_data) if isinstance(processed_data, list) else 'processed'
                    else:
                        logger.error(f"[{correlation_id}] Processing code execution failed: {processing_execution_result.get('error', 'Unknown error')}")
                        # Keep original placeholder content but add error info to metadata
                        if 'metadata' in formatted_response:
                            formatted_response['metadata']['processing_executed'] = False
                            formatted_response['metadata']['execution_error'] = processing_execution_result.get('error', 'Unknown error')
                        
                        # CRITICAL FIX: Mark execution as failed when Results Formatter processing fails
                        # This ensures the frontend receives proper error status like other agent failures
                        execution_results.final_result = False
                        processing_error = processing_execution_result.get('error', 'Unknown error')
                        
                        # Add this as a step failure so it appears in the errors array
                        formatter_step = StepResult(
                            step_number=len(execution_results.steps) + 1,
                            step_type="results_formatter",
                            tool_name="results_formatter",
                            success=False,
                            error=f"Results Formatter processing code execution failed: {processing_error}",
                            data=None,
                            execution_time=0.0
                        )
                        execution_results.steps.append(formatter_step)
                
                # NOTE: File saving disabled for realtime_hybrid route - not needed for streaming results
                # await self._save_results_to_file(query, formatted_response, step_results_for_processing, correlation_id)
                
            except Exception as e:
                logger.error(f"[{correlation_id}] Results formatting failed: {e}")
                formatted_response = {
                    'display_type': 'markdown',
                    'content': {'text': f'Results formatting failed: {e}'},
                    'metadata': {'error': 'Results formatting failed'}
                }
                
                # CRITICAL FIX: Mark execution as failed when Results Formatter fails
                # This ensures the frontend receives proper error status like other agent failures
                execution_results.final_result = False
                
                # Add this as a step failure so it appears in the errors array
                formatter_step = StepResult(
                    step_number=len(execution_results.steps) + 1,
                    step_type="results_formatter",
                    tool_name="results_formatter",
                    success=False,
                    error=f"Results Formatter failed: {str(e)}",
                    data=None,
                    execution_time=0.0
                )
                execution_results.steps.append(formatter_step)
            
            # Format results for compatibility with test expectations
            success_rate = sum(1 for step in execution_results.steps if step.success) / len(execution_results.steps)
            overall_success = success_rate >= 0.5  # At least 50% success
            
            # Build structured result with comprehensive execution details
            result = {
                'success': overall_success,
                'overall_success': overall_success,  # For test compatibility
                'correlation_id': correlation_id,
                'query': query,
                'execution_plan': execution_plan.model_dump(),
                'step_results': [step.model_dump() for step in execution_results.steps],
                'final_result': execution_results.final_result,
                'total_steps': len(execution_results.steps),
                'successful_steps': sum(1 for step in execution_results.steps if step.success),
                'failed_steps': sum(1 for step in execution_results.steps if not step.success),
                'success_rate': success_rate,
                'phase': 'completed',
                # Add results formatter output like old executor
                'raw_results': raw_results,
                'processed_summary': formatted_response,
                'formatted_response': formatted_response,  # For test compatibility
                'processing_method': 'results_formatter_structured_pydantic'
            }
            
            # Add error details if any steps failed
            if not overall_success:
                failed_steps = [step for step in execution_results.steps if not step.success]
                result['errors'] = [step.error for step in failed_steps if step.error]
            
            logger.info(f"[{correlation_id}] Query execution completed: {overall_success} (success rate: {success_rate:.1%})")
            return result
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"[{correlation_id}] Query execution failed with exception: {error_msg}")
            return {
                'success': False,
                'error': error_msg,
                'correlation_id': correlation_id,
                'query': query,
                'phase': 'execution_error'
            }
    
    def regenerate_lightweight_reference(self) -> Dict[str, Any]:
        """
        Public method to manually regenerate the lightweight API reference.
        
        This method:
        1. Reads the comprehensive Okta API reference
        2. Reads the SQL schema (with fallback to defaults)
        3. Generates a new lightweight_api_reference.json file
        4. Updates internal data structures
        
        Returns:
            Dict containing the generated reference data
        """
        logger.info("Manually regenerating lightweight API reference...")
        
        # Generate new reference
        new_reference = self._generate_lightweight_reference()
        
        # Update internal data structures
        self.simple_ref_data = new_reference
        entities_dict = new_reference.get('entities', {})
        self.available_entities = list(entities_dict.keys())
        self.entity_summary = {entity_name: {'operations': entity_data['operations'], 'methods': []} 
                              for entity_name, entity_data in entities_dict.items()}
        self.sql_tables = {table['name']: {'columns': table['columns']} 
                          for table in new_reference.get('sql_tables', [])}
        
        logger.info(f"Lightweight reference regenerated: {len(self.available_entities)} entities, {len(self.sql_tables)} SQL tables")
        return new_reference
    
    async def execute_steps(self, plan: ExecutionPlan, correlation_id: str) -> ExecutionResults:
        """
        Execute all steps in the plan in order using repeatable variable-based data flow.
        
        Args:
            plan: ExecutionPlan from planning agent
            correlation_id: Correlation ID for tracking
            
        Returns:
            ExecutionResults with all step outputs
        """
        logger.info(f"[{correlation_id}] Starting execution of {len(plan.steps)} steps")
        
        # REPEATABLE PATTERN: Clear data for fresh execution run
        self._clear_execution_data()
        
        step_results = []
        successful_steps = 0
        failed_steps = 0
        
        # Walk through each step in order
        for i, step in enumerate(plan.steps):
            step_num = i + 1
            
            # MINIMAL CANCELLATION CHECK - Aggressive termination
            if correlation_id in self.cancelled_queries:
                logger.warning(f"[{correlation_id}] Step {step_num} CANCELLED - Emergency cleanup and stopping execution")
                await self._emergency_cleanup(correlation_id)
                break
            
            # Track step timing
            step_start_time = time.time()
            logger.info(f"[{correlation_id}] Executing step {step_num}/{len(plan.steps)}: {step.tool_name}")
            
            try:
                # Execute step based on type
                if step.tool_name == "cypher":
                    result = await self._execute_cypher_step(step, correlation_id, step_num)
                elif step.tool_name == "api":
                    result = await self._execute_api_step(step, correlation_id, step_num)
                elif step.tool_name == "special_tool":
                    result = await self._execute_special_tool_step(step, correlation_id, step_num)
                # REPEATABLE PATTERN: Add new tool types here
                # elif step.tool_name == "new_tool":
                #     result = await self._execute_new_tool_step(step, correlation_id, step_num)
                else:
                    # Unknown step type - REPEATABLE PATTERN: Handle new tool types here
                    logger.warning(f"[{correlation_id}] Unknown step type: {step.tool_name}")
                    result = StepResult(
                        step_number=step_num,
                        step_type=step.tool_name,
                        success=False,
                        error=f"Unknown step type: {step.tool_name}"
                    )
                
                # REPEATABLE PATTERN: Track step results and store data automatically
                step_end_time = time.time()
                step_duration = step_end_time - step_start_time
                
                if result.success:
                    successful_steps += 1
                    logger.info(f"[{correlation_id}] Step {step_num} completed successfully in {step_duration:.2f}s")
                    
                    # Get record count from result
                    record_count = 0
                    data_to_check = None
                    
                    # Try different data access patterns
                    if hasattr(result.result, 'data') and result.result.data:
                        data_to_check = result.result.data
                    elif hasattr(result, 'data') and result.data:
                        data_to_check = result.data
                    
                    if data_to_check:
                        if isinstance(data_to_check, list):
                            record_count = len(data_to_check)
                        elif isinstance(data_to_check, dict):
                            # Handle dictionary results - count all list values
                            total_records = 0
                            for key, value in data_to_check.items():
                                if isinstance(value, list):
                                    total_records += len(value)
                                elif value is not None:  # Count non-null single values
                                    total_records += 1
                            record_count = total_records
                        else:
                            # Single non-list result
                            record_count = 1
                    
                    # EARLY TERMINATION CHECK: If first step returns 0 results, terminate execution
                    if step_num == 1 and record_count == 0:
                        logger.warning(f"[{correlation_id}] EARLY TERMINATION: First step returned no data - stopping execution")
                        result.result = {
                            "early_termination": True,
                            "message": "No data found matching your criteria. Try broadening your search.",
                            "data": []
                        }
                        step_results.append(result)
                        break
                    
                    # Data storage is handled automatically in step execution methods
                    # Log current data state using FULL POLARS
                    total_dataframes = len(self.polars_dataframes)
                    total_metadata = len(self.step_metadata)
                    # logger.debug(f"[{correlation_id}] Data state: {total_dataframes} DataFrames, {total_metadata} step metadata entries")
                else:
                    failed_steps += 1
                    logger.error(f"[{correlation_id}] Step {step_num} failed: {result.error}")
                    
                    # CRITICAL ERROR HANDLING: Stop execution on step failure
                    logger.error(f"[{correlation_id}] Stopping execution due to step {step_num} failure")
                    logger.error(f"[{correlation_id}] Failed step details: {step.tool_name} - {result.error}")
                    break  # Stop executing remaining steps
                
                step_results.append(result)
                
            except Exception as e:
                # Handle unexpected errors
                logger.error(f"[{correlation_id}] Unexpected error in step {step_num}: {e}")
                error_result = self.error_handler.handle_step_error(step, e, correlation_id, step_num)
                step_results.append(error_result)
                failed_steps += 1
                
                # NEW STANDARDIZED: STEP-ERROR callback
                if self.step_error_callback:
                    try:
                        await self.step_error_callback(
                            step_number=step_num,
                            step_type=step.tool_name,
                            error_message=str(e),
                            error_type="execution_exception",
                            retry_possible=True,  # Most unexpected errors could be retried
                            technical_details=f"Exception in step execution: {type(e).__name__}",
                            formatted_time=time.strftime('%H:%M:%S', time.localtime())
                        )
                    except Exception as callback_error:
                        logger.warning(f"[{correlation_id}] Step error callback error: {callback_error}")
                
                break  # Stop execution on exception
        
        # Create final results
        final_result = step_results[-1].result if step_results and step_results[-1].success else None
        
        execution_results = ExecutionResults(
            steps=step_results,
            final_result=final_result,
            correlation_id=correlation_id,
            total_steps=len(plan.steps),
            successful_steps=successful_steps,
            failed_steps=failed_steps
        )
        
        logger.info(f"[{correlation_id}] Execution completed: {successful_steps}/{len(plan.steps)} steps successful")
        
        return execution_results
    
    async def _execute_cypher_step(self, step: ExecutionStep, correlation_id: str, step_number: int) -> StepResult:
        """
        Execute Cypher step using repeatable variable-based data flow pattern.
        
        REPEATABLE PATTERN: 
        - Get sample data for LLM context (max 3 records)
        - Get full data from previous step for processing  
        - Store full results for next step access
        """
        try:
            # FULL POLARS: Get data from previous step using Polars DataFrame only
            full_previous_data = self._get_polars_data_from_previous_step(step_number)
            logger.debug(f"[{correlation_id}] Retrieved {len(full_previous_data)} records from Polars DataFrame")
            
            # Determine which Cypher agent to use based on step position
            if step_number == 1 or len(full_previous_data) == 0:
                logger.info(f"[{correlation_id}] Step {step_number}: First Cypher step (direct mode), using Direct Cypher Agent")
                return await self._execute_direct_cypher_step(step, correlation_id, step_number)
            else:
                logger.info(f"[{correlation_id}] Step {step_number}: Multi-step Cypher processing (enrichment mode), using Cypher Enrichment Agent")
                return await self._execute_enrichment_cypher_step(step, full_previous_data, correlation_id, step_number)
                
        except Exception as e:
            return self.error_handler.handle_step_error(step, e, correlation_id, step_number)

    async def _execute_direct_cypher_step(self, step: ExecutionStep, correlation_id: str, step_number: int) -> StepResult:
        """
        Execute direct Cypher step (user question → Cypher query).
        
        REPEATABLE PATTERN:
        - Get enhanced context from all previous steps
        - Execute Cypher to get full results
        - Store full results using variable-based storage
        """
        # IMMEDIATE CANCELLATION CHECK - Don't start step if already cancelled
        if correlation_id in self.cancelled_queries:
            logger.warning(f"[{correlation_id}] Direct Cypher Step {step_number} CANCELLED before execution - Skipping")
            return StepResult(
                step_number=step_number,
                step_type="cypher",
                success=False,
                error="Query cancelled before step execution"
            )
        
        # logger.debug(f"[{correlation_id}] Executing direct Cypher step")
        
        # NEW STANDARDIZED: STEP-START callback for Cypher step
        step_start_time = time.time()
        # Calculate correct step number: execution steps start at step 2 (after thinking=0, generating_steps=1)
        callback_step_number = step_number + 1  # step_number is 0-based execution step index, callback needs 2, 3, 4, etc.
        if self.step_start_callback:
            try:
                await self.step_start_callback(
                    step_number=callback_step_number,
                    step_type="cypher",
                    step_name=f"Step {callback_step_number}: {step.tool_name}",
                    query_context=step.query_context,
                    critical=getattr(step, 'critical', True),
                    formatted_time=time.strftime('%H:%M:%S', time.localtime(step_start_time))
                )
            except Exception as callback_error:
                logger.warning(f"[{correlation_id}] Cypher step start callback error: {callback_error}")
        
        # Get enhanced context from all previous steps
        all_step_contexts = self._get_all_previous_step_contexts_and_samples(step_number, max_samples=3)
        logger.debug(f"[{correlation_id}] Enhanced context: {len(all_step_contexts)} previous step contexts provided")
        
        # Call Cypher Agent with enhanced logging
        # logger.debug(f"[{correlation_id}] Calling Direct Cypher Agent with context: {step.query_context}")
        
        cypher_result = await generate_cypher_query_with_logging(
            question=step.query_context
        )
        
        # Cypher generation returns CypherQueryOutput directly (not a dict)
        cypher_query = cypher_result.cypher_query
        explanation = cypher_result.explanation
        
        # Security validation already done in generate_cypher_query_with_logging
        
        # NEW STANDARDIZED: STEP-PROGRESS callback before Cypher execution
        if self.step_progress_callback:
            try:
                await self.step_progress_callback(
                    step_number=step_number,
                    step_type=step.tool_name,
                    progress_percentage=50.0,  # 50% - Cypher generated, about to execute
                    current=50,
                    total=100,
                    message="Executing Cypher query against GraphDB",
                    formatted_time=time.strftime('%H:%M:%S', time.localtime())
                )
            except Exception as callback_error:
                logger.warning(f"[{correlation_id}] Step progress callback error: {callback_error}")
        
        # Execute the generated Cypher query against GraphDB
        if cypher_query and cypher_query.strip():
            db_data = await self._execute_raw_cypher_query(cypher_query, correlation_id)
            logger.info(f"[{correlation_id}] Cypher execution completed: {len(db_data)} records returned")
            
            # NEW STANDARDIZED: STEP-PROGRESS callback after Cypher execution
            if self.step_progress_callback:
                try:
                    await self.step_progress_callback(
                        step_number=step_number,
                        step_type=step.tool_name,
                        progress_percentage=100.0,  # 100% - execution complete
                        current=100,
                        total=100,
                        message=f"Cypher execution completed: {len(db_data)} records retrieved",
                        formatted_time=time.strftime('%H:%M:%S', time.localtime())
                    )
                except Exception as callback_error:
                    logger.warning(f"[{correlation_id}] Step progress callback error: {callback_error}")
        else:
            logger.warning(f"[{correlation_id}] No Cypher query generated or empty query")
            db_data = []
        
        # REPEATABLE PATTERN: Store full results for next step access
        variable_name = self._store_step_data(
            step_number=step_number,
            step_type="cypher",
            data=db_data,
            metadata={
                "cypher_query": cypher_query,
                "explanation": explanation
            }
        )
        
        logger.info(f"[{correlation_id}] Cypher step completed: {len(db_data)} records stored as {variable_name}")
        
        # Check if Cypher execution was successful
        has_meaningful_data = isinstance(db_data, list) and len(db_data) > 0
        cypher_executed_successfully = bool(cypher_query)
        
        # Cypher step is successful if query was generated and executed, regardless of result count
        # "No results found" is a valid successful outcome, not an error
        step_success = cypher_executed_successfully
        
        if not cypher_executed_successfully:
            logger.warning(f"[{correlation_id}] Cypher step marked as FAILED: Cypher generation or execution failed")
        elif not has_meaningful_data:
            logger.info(f"[{correlation_id}] Cypher step completed successfully: no results found (query returned 0 records)")
        
        # Create result with Cypher execution data
        result_data = CypherExecutionResult(cypher_query, explanation, db_data)
        
        # NEW STANDARDIZED: STEP-END callback for Cypher step
        step_end_time = time.time()
        step_duration = step_end_time - step_start_time
        if self.step_end_callback:
            try:
                await self.step_end_callback(
                    step_number=callback_step_number,
                    step_type="cypher",
                    success=step_success,
                    duration_seconds=step_duration,
                    record_count=len(db_data) if isinstance(db_data, list) else 0,
                    formatted_time=time.strftime('%H:%M:%S', time.localtime(step_end_time)),
                    error_message=None if step_success else "Cypher execution failed"
                )
            except Exception as callback_error:
                logger.warning(f"[{correlation_id}] Cypher step end callback error: {callback_error}")
        
        return StepResult(
            step_number=step_number,
            step_type="CYPHER",
            success=step_success,
            result=result_data
        )
    
    async def _execute_enrichment_cypher_step(self, step: ExecutionStep, full_data: List[Dict[str, Any]], correlation_id: str, step_number: int) -> StepResult:
        """
        Execute API - Cypher enrichment step using Polars optimization.
        
        REPEATABLE PATTERN:
        - Use enhanced context from all previous steps
        - Use full data for processing (full API data from previous step)
        - Store full Cypher results for next step access
        """
        # IMMEDIATE CANCELLATION CHECK - Don't start step if already cancelled
        if correlation_id in self.cancelled_queries:
            logger.warning(f"[{correlation_id}] Cypher Enrichment Step {step_number} CANCELLED before execution - Skipping")
            return StepResult(
                step_number=step_number,
                step_type="cypher",
                success=False,
                error="Query cancelled before step execution"
            )
        
        # ENHANCED PATTERN: Get context and samples from ALL previous steps
        all_step_contexts = self._get_all_previous_step_contexts_and_samples(step_number, max_samples=3)
        
        # NEW STANDARDIZED: STEP-START callback for Cypher enrichment step
        step_start_time = time.time()
        # Calculate correct step number: execution steps start at step 2 (after thinking=0, generating_steps=1)
        callback_step_number = step_number + 1  # step_number is 0-based execution step index, callback needs 2, 3, 4, etc.
        if self.step_start_callback:
            try:
                await self.step_start_callback(
                    step_number=callback_step_number,
                    step_type="cypher",
                    step_name=f"Step {callback_step_number}: {step.tool_name}",
                    query_context=step.query_context,
                    critical=getattr(step, 'critical', True),
                    formatted_time=time.strftime('%H:%M:%S', time.localtime(step_start_time))
                )
            except Exception as callback_error:
                logger.warning(f"[{correlation_id}] Cypher enrichment step start callback error: {callback_error}")
        
        # Calculate data count for logging
        if isinstance(full_data, list):
            data_count = len(full_data)
        elif isinstance(full_data, dict):
            data_count = full_data.get('total_active_users', 1) if 'total_active_users' in full_data else 1
        else:
            data_count = 1 if full_data else 0
            
        logger.info(f"[{correlation_id}] Processing API data with Cypher Enrichment Agent: {data_count} full records")
        logger.debug(f"[{correlation_id}] Enhanced context: {len(all_step_contexts)} previous step contexts provided")
        
        # Call Cypher Enrichment Agent with Polars optimization
        result = await cypher_enrichment_agent.process_api_data(
            api_data=full_data,
            processing_context=step.query_context,
            correlation_id=correlation_id,
            all_step_contexts=all_step_contexts
        )
        
        # Execute Polars-optimized workflow for Cypher
        try:
            db_data = await self._execute_polars_optimized_workflow_cypher(
                polars_output=result,
                api_data=full_data,
                correlation_id=correlation_id
            )
            logger.info(f"[{correlation_id}] Cypher Polars optimization completed: {len(db_data)} results")
            
        except Exception as e:
            logger.error(f"[{correlation_id}] Cypher Polars optimization failed: {e}")
            db_data = []
        
        # REPEATABLE PATTERN: Store full Cypher results for next step access
        variable_name = self._store_step_data(
            step_number=step_number,
            step_type="cypher_enrichment",
            data=db_data,
            metadata={
                "cypher_query": result.cypher_query_template,
                "explanation": result.explanation,
                "input_record_count": data_count,
                "polars_processing": True,
                "polars_optimization": True,
                "id_extraction_path": result.id_extraction_path
            },
            step_context=step.query_context
        )
        
        logger.info(f"[{correlation_id}] Cypher enrichment step completed: {len(db_data)} records stored as {variable_name}")
        
        # Create result object
        result_data = CypherExecutionResult(result.cypher_query_template, result.explanation, db_data)
        
        # NEW STANDARDIZED: STEP-END callback for Cypher enrichment step
        step_end_time = time.time()
        step_duration = step_end_time - step_start_time
        if self.step_end_callback:
            try:
                await self.step_end_callback(
                    step_number=callback_step_number,
                    step_type="cypher",
                    success=True,
                    duration_seconds=step_duration,
                    record_count=len(db_data) if isinstance(db_data, list) else 0,
                    formatted_time=time.strftime('%H:%M:%S', time.localtime(step_end_time)),
                    error_message=None
                )
            except Exception as callback_error:
                logger.warning(f"[{correlation_id}] Cypher enrichment step end callback error: {callback_error}")
        
        return StepResult(
            step_number=step_number,
            step_type="CYPHER_ENRICHMENT",
            success=True,
            result=result_data
        )
    
    async def _execute_api_step(self, step: ExecutionStep, correlation_id: str, step_number: int) -> StepResult:
        """
        Execute API step using repeatable variable-based data flow pattern.
        
        REPEATABLE PATTERN:
        - Get sample data for LLM context (max 3 records)
        - Get full data from previous step for processing
        - Execute API code generation and processing
        - Store full results for next step access
        """
        # IMMEDIATE CANCELLATION CHECK - Don't start step if already cancelled
        if correlation_id in self.cancelled_queries:
            logger.warning(f"[{correlation_id}] API Step {step_number} CANCELLED before execution - Skipping")
            return StepResult(
                step_number=step_number,
                step_type="api",
                success=False,
                error="Query cancelled before step execution"
            )
        
        try:
            # Record step start time for duration calculation
            step_start_time = time.time()
            
            # NEW STANDARDIZED: STEP-START callback for API step
            # Calculate correct step number: execution steps start at step 2 (after thinking=0, generating_steps=1)
            callback_step_number = step_number + 1  # step_number is 0-based execution step index, callback needs 2, 3, 4, etc.
            if self.step_start_callback:
                try:
                    await self.step_start_callback(
                        step_number=callback_step_number,
                        step_type="api",
                        step_name=step.tool_name,
                        query_context=step.query_context,
                        critical=getattr(step, 'critical', True),
                        formatted_time=time.strftime('%H:%M:%S', time.localtime(step_start_time))
                    )
                except Exception as callback_error:
                    logger.warning(f"[{correlation_id}] API step start callback error: {callback_error}")
            
            # Get filtered endpoints for this specific step (using old executor logic)
            available_endpoints = self._get_entity_endpoints_for_step(step)
            
            # HARD STOP: If no endpoints found, fail the entire query immediately
            if not available_endpoints:
                error_msg = f"CRITICAL: No API endpoints found for entity='{step.entity}', operation='{getattr(step, 'operation', None)}'. Cannot proceed with API code generation."
                logger.error(f"[{correlation_id}] {error_msg}")
                
                # NEW STANDARDIZED: STEP-ERROR callback for missing endpoints
                if self.step_error_callback:
                    try:
                        await self.step_error_callback(
                            step_number=callback_step_number,
                            step_type="api",
                            error_message=error_msg,
                            error_type="configuration_error",
                            retry_possible=False,  # Cannot retry without endpoints
                            technical_details="No matching API endpoints found for the specified entity and operation",
                            formatted_time=time.strftime('%H:%M:%S', time.localtime())
                        )
                    except Exception as callback_error:
                        logger.warning(f"[{correlation_id}] Step error callback error: {callback_error}")
                
                return StepResult(
                    step_number=step_number,
                    step_type="api",
                    success=False,
                    error=error_msg
                )
            
            # ENHANCED PATTERN: Get context and samples from ALL previous steps
            all_step_contexts = self._get_all_previous_step_contexts_and_samples(step_number, max_samples=3)
            
            # FULL POLARS: Get data from previous step using Polars DataFrame only
            full_previous_data = self._get_polars_data_from_previous_step(step_number)
            actual_record_count = len(full_previous_data)
            logger.debug(f"[{correlation_id}] Retrieved {actual_record_count} records from Polars DataFrame")
            
            logger.debug(f"[{correlation_id}] API Code Gen: Processing {actual_record_count} records")
            logger.debug(f"[{correlation_id}] Enhanced context: {len(all_step_contexts)} previous step contexts provided")
            
            # Call API Code Gen Agent with enhanced logging using wrapper function
            logger.debug(f"[{correlation_id}] Calling API Code Gen Agent with context: {step.query_context}")
            logger.debug(f"[{correlation_id}] Available endpoints being passed to API agent: {len(available_endpoints)} endpoints")
            if available_endpoints:
                logger.debug(f"[{correlation_id}] First endpoint structure: {available_endpoints[0]}")
                # DEBUG: Log all endpoint names being passed
                endpoint_names = [ep.get('name', 'Unknown') for ep in available_endpoints]
                logger.debug(f"[{correlation_id}] Endpoint names: {endpoint_names}")
            else:
                logger.debug(f"[{correlation_id}] No endpoints available!")
            
            # Calculate previous step's full_results key for API agent
            previous_step_num = step_number - 1
            previous_step_key = f"step_{previous_step_num}"
            previous_full_results_key = None
            if previous_step_key in self.step_metadata:
                previous_step_type = self.step_metadata[previous_step_key].get("type", "unknown").lower()
                previous_full_results_key = f"{previous_step_num}_{previous_step_type}"
            
            # Use the entity field from the new format
            entity_name = step.entity or "users"
            api_result_dict = await generate_api_code(
                query=step.query_context,
                sql_record_count=actual_record_count,  # Full record count for processing logic
                available_endpoints=available_endpoints,
                entities_involved=[entity_name],
                step_description=step.reasoning if hasattr(step, 'reasoning') else step.query_context,
                correlation_id=correlation_id,
                all_step_contexts=all_step_contexts,  # Enhanced context from all previous steps
                previous_step_key=previous_full_results_key  # NEW: Pass explicit step key
            )
            
            # NEW STANDARDIZED: STEP-TOKENS callback after API code generation
            if self.step_tokens_callback and api_result_dict.get('success', False):
                try:
                    # Extract token usage from API code generation (if available)
                    input_tokens = api_result_dict.get('input_tokens', 0)
                    output_tokens = api_result_dict.get('output_tokens', 0)
                    total_tokens = input_tokens + output_tokens
                    
                    await self.step_tokens_callback(
                        step_number=callback_step_number,  # Use consistent step numbering
                        step_type="api",
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        agent_name="API Code Generation Agent",
                        formatted_time=time.strftime('%H:%M:%S', time.localtime())
                    )
                except Exception as callback_error:
                    logger.warning(f"[{correlation_id}] Step tokens callback error: {callback_error}")
            
            # Check if the wrapper function was successful
            if not api_result_dict.get('success', False):
                error_msg = api_result_dict.get('error', 'Unknown API code generation error')
                
                # NEW STANDARDIZED: STEP-ERROR callback for API code generation failure
                if self.step_error_callback:
                    try:
                        await self.step_error_callback(
                            step_number=callback_step_number,  # Use consistent step numbering
                            step_type="api",
                            error_message=error_msg,
                            error_type="code_generation_error",
                            retry_possible=True,  # Code generation errors can usually be retried
                            technical_details="API code generation failed - may be due to context limits or LLM errors",
                            formatted_time=time.strftime('%H:%M:%S', time.localtime())
                        )
                    except Exception as callback_error:
                        logger.warning(f"[{correlation_id}] Step error callback error: {callback_error}")
                
                return StepResult(
                    step_number=step_number,
                    step_type="api",
                    success=False,
                    error=error_msg
                )
            
            # Phase 5: Execute the generated API code to get actual data
            logger.debug(f"[{correlation_id}] Phase 5: Executing generated API code")
            # logger.debug(f"[{correlation_id}] Generated {len(api_result_dict.get('code', ''))} characters of API code")
            
            # DEBUG: Log the actual generated code if debug level is enabled
            generated_code = api_result_dict.get('code', '')
            if generated_code:
                logger.debug(f"[{correlation_id}] Generated API Code:\n{'-'*50}\n{generated_code}\n{'-'*50}")
            else:
                logger.warning(f"[{correlation_id}] No API code was generated!")
            
            # NEW STANDARDIZED: STEP-PROGRESS callback before API execution
            if self.step_progress_callback:
                try:
                    await self.step_progress_callback(
                        step_number=callback_step_number,  # Use consistent step numbering
                        step_type="api",
                        progress_percentage=50.0,  # 50% - code generated, about to execute
                        current=50,
                        total=100,
                        message="Executing API code to fetch data",
                        formatted_time=time.strftime('%H:%M:%S', time.localtime())
                    )
                except Exception as callback_error:
                    logger.warning(f"[{correlation_id}] Step progress callback error: {callback_error}")
            
            execution_result = await self._execute_generated_code(
                api_result_dict.get('code', ''), 
                correlation_id, 
                step, 
                current_step_number=step_number  # CRITICAL: Pass step number for data injection
            )
            
            # NEW STANDARDIZED: STEP-PROGRESS callback after API execution
            if self.step_progress_callback and execution_result.get('success', False):
                try:
                    await self.step_progress_callback(
                        step_number=callback_step_number,  # Use consistent step numbering
                        step_type="api",
                        progress_percentage=100.0,  # 100% - execution complete
                        current=100,
                        total=100,
                        message="API execution completed successfully",
                        formatted_time=time.strftime('%H:%M:%S', time.localtime())
                    )
                except Exception as callback_error:
                    logger.warning(f"[{correlation_id}] Step progress callback error: {callback_error}")
            
            if execution_result.get('success', False):
                # Use the actual execution output
                actual_data = execution_result.get('output', [])
                logger.info(f"[{correlation_id}] API code execution successful, got {len(actual_data) if isinstance(actual_data, list) else 'N/A'} results")
                
                # Log only one sample element to avoid log spam
                if isinstance(actual_data, list) and actual_data:
                    sample_str = str(actual_data[0])
                    truncated_sample = sample_str[:1000] + "..." if len(sample_str) > 1000 else sample_str
                    logger.debug(f"[{correlation_id}] Sample API result (1 of {len(actual_data)}): {truncated_sample}")
                elif actual_data:
                    sample_str = str(actual_data)
                    truncated_sample = sample_str[:1000] + "..." if len(sample_str) > 1000 else sample_str
                    logger.debug(f"[{correlation_id}] API result sample: {truncated_sample}")
                else:
                    logger.debug(f"[{correlation_id}] API execution returned no data")
                
                result_data = APIExecutionResult(
                    code=api_result_dict['code'],
                    explanation=api_result_dict['explanation'],
                    data=actual_data,
                    executed=True
                )
                
                # REPEATABLE PATTERN: Store full API results for next step access
                variable_name = self._store_step_data(
                    step_number=step_number,
                    step_type="api",
                    data=actual_data,
                    metadata={
                        "code_generated": True,
                        "code_executed": True,
                        "explanation": api_result_dict['explanation']
                    },
                    step_context=step.query_context  # NEW: Store step context
                )
                
                logger.info(f"[{correlation_id}] API step completed: {len(actual_data) if isinstance(actual_data, list) else 1} records stored as {variable_name}")
                
                # NEW STANDARDIZED: STEP-COUNT callback for successful API execution
                if self.step_count_callback:
                    try:
                        await self.step_count_callback(
                            step_number=callback_step_number,
                            step_type="api",
                            record_count=len(actual_data) if isinstance(actual_data, list) else 1,
                            operation_type="retrieved",
                            formatted_time=time.strftime('%H:%M:%S', time.localtime())
                        )
                    except Exception as callback_error:
                        logger.warning(f"[{correlation_id}] Step count callback error: {callback_error}")
            else:
                error_msg = execution_result.get('error', 'Unknown error')
                logger.error(f"[{correlation_id}] API code execution failed: {error_msg}")
                
                # NEW STANDARDIZED: STEP-ERROR callback for API code execution failure
                if self.step_error_callback:
                    try:
                        # Classify error type based on error message content (same logic as realtime_hybrid.py)
                        error_msg_lower = error_msg.lower()
                        if "oauth2" in error_msg_lower or "insufficient scopes" in error_msg_lower or "insufficient permissions" in error_msg_lower:
                            error_type = "oauth2_error"
                            retry_possible = False  # OAuth2 scope issues usually require admin intervention
                            technical_details = "OAuth2 authentication failed - check client credentials and granted scopes"
                        elif "authentication failed" in error_msg_lower or "invalid or expired" in error_msg_lower:
                            error_type = "auth_error"
                            retry_possible = False  # Auth failures require credential/config fixes
                            technical_details = "Authentication failed - check API token or OAuth2 configuration"
                        elif "access forbidden" in error_msg_lower:
                            error_type = "auth_error"
                            retry_possible = False  # Permission issues require admin intervention
                            technical_details = "Access forbidden - insufficient permissions for the requested operation"
                        else:
                            error_type = "code_execution_error"
                            retry_possible = True   # Generic code execution errors can often be retried
                            technical_details = "Generated API code failed to execute - may be due to API errors, network issues, or code logic problems"
                        
                        await self.step_error_callback(
                            step_number=callback_step_number,  # Use consistent step numbering
                            step_type="api",
                            error_message=f"API code execution failed: {error_msg}",
                            error_type=error_type,
                            retry_possible=retry_possible,
                            technical_details=technical_details,
                            formatted_time=time.strftime('%H:%M:%S', time.localtime())
                        )
                    except Exception as callback_error:
                        logger.warning(f"[{correlation_id}] Step error callback error: {callback_error}")
                
                # Fall back to code generation result without execution
                result_data = APIExecutionResult(
                    code=api_result_dict['code'],
                    explanation=api_result_dict['explanation'],
                    data=[],
                    executed=False,
                    error=error_msg
                )
                
                # REPEATABLE PATTERN: Store empty results for failed API execution
                variable_name = self._store_step_data(
                    step_number=step_number,
                    step_type="api",
                    data=[],
                    metadata={
                        "code_generated": True,
                        "code_executed": False,
                        "execution_error": execution_result.get('error', 'Unknown error')
                    },
                    step_context=step.query_context  # NEW: Store step context
                )
                logger.warning(f"[{correlation_id}] API step failed: empty results stored as {variable_name}")
            
            # Determine if step should be considered successful
            has_meaningful_data = True  # 0 results is a valid successful outcome
            execution_successful = False
            
            # API step is successful if it executed properly, regardless of result count
            # 0 results should NOT be considered a failure - it's a valid query result
            if hasattr(result_data, 'data'):
                # result_data is an APIExecutionResult object - any structure is valid
                has_meaningful_data = True
            else:
                # Fallback for raw data (shouldn't happen with current code)
                has_meaningful_data = True
            
            # Check if code executed without critical errors
            if execution_result.get('error'):
                error_msg = execution_result.get('error', '').lower()
                # Critical errors that should fail the step
                critical_error_patterns = [
                    'import', 'module', 'syntax', 'indentation', 'security violation',
                    # Authentication and authorization errors
                    'oauth2', 'insufficient scopes', 'insufficient permissions', 
                    'authentication failed', 'invalid or expired', 'access forbidden',
                    # API and HTTP errors (but not rate limits - those are retried automatically)
                    'resource not found', 'server error', 'service temporarily unavailable',
                    # Network and timeout errors
                    'network error', 'request timeout', 'connection error', 'timeout'
                ]
                if any(critical in error_msg for critical in critical_error_patterns):
                    execution_successful = False
                    logger.error(f"[{correlation_id}] API step has critical execution error: {execution_result.get('error')}")
                    
                    # Special handling for security violations - immediate step failure
                    if 'security violation' in error_msg:
                        logger.critical(f"[{correlation_id}] SECURITY VIOLATION DETECTED - Step immediately failed")
                        return StepResult(
                            step_number=step_number,
                            step_type="api",
                            success=False,
                            error=f"Security violation in generated API code: {execution_result.get('error')}"
                        )
                else:
                    execution_successful = True  # Non-critical error (like network timeout)
            else:
                execution_successful = True
            
            # Step is successful only if both conditions are met
            step_success = has_meaningful_data and execution_successful
            
            if not step_success:
                if not has_meaningful_data:
                    logger.warning(f"[{correlation_id}] API step marked as FAILED: execution structure invalid")
                if not execution_successful:
                    logger.warning(f"[{correlation_id}] API step marked as FAILED: critical execution error")
            
            # NEW STANDARDIZED: STEP-END callback for API step
            step_end_time = time.time()
            step_duration = step_end_time - step_start_time
            
            # Calculate correct record count
            if hasattr(result_data, 'data') and isinstance(result_data.data, list):
                final_record_count = len(result_data.data)
            elif isinstance(result_data, list):
                final_record_count = len(result_data)
            else:
                final_record_count = 1 if result_data else 0
            
            if self.step_end_callback:
                try:
                    await self.step_end_callback(
                        step_number=callback_step_number,  # Use consistent step numbering
                        step_type="api",
                        success=step_success,
                        duration_seconds=step_duration,
                        record_count=final_record_count,
                        formatted_time=time.strftime('%H:%M:%S', time.localtime(step_end_time)),
                        error_message=None if step_success else "API execution failed"
                    )
                except Exception as callback_error:
                    logger.warning(f"[{correlation_id}] API step end callback error: {callback_error}")
            
            return StepResult(
                step_number=step_number,
                step_type="api",
                success=step_success,
                result=result_data
            )
            
        except Exception as e:
            return self.error_handler.handle_step_error(step, e, correlation_id, step_number)
    
    async def _execute_special_tool_step(self, step: ExecutionStep, correlation_id: str, step_number: int) -> StepResult:
        """
        Execute special tool step using code template and subprocess execution (like API steps).
        
        GENERIC PROXY PATTERN:
        - Get code template from special tool
        - Fill template with whatever parameters planning agent provided
        - Execute code in subprocess using _execute_generated_code
        - Store results using variable-based storage for next steps
        """
        # IMMEDIATE CANCELLATION CHECK - Don't start step if already cancelled
        if correlation_id in self.cancelled_queries:
            logger.warning(f"[{correlation_id}] Special Tool Step {step_number} CANCELLED before execution - Skipping")
            return StepResult(
                step_number=step_number,
                step_type="special_tool",
                success=False,
                error="Query cancelled before step execution"
            )
        
        try:
            # Record step start time for duration calculation
            step_start_time = time.time()
            
            # NEW STANDARDIZED: STEP-START callback for special tool step
            callback_step_number = step_number + 1  # step_number is 0-based execution step index
            if self.step_start_callback:
                try:
                    await self.step_start_callback(
                        step_number=callback_step_number,
                        step_type="special_tool",
                        step_name=f"Step {callback_step_number}: {step.tool_name}",
                        query_context=step.query_context,
                        critical=getattr(step, 'critical', True),
                        formatted_time=time.strftime('%H:%M:%S', time.localtime(step_start_time))
                    )
                except Exception as callback_error:
                    logger.warning(f"[{correlation_id}] Special tool step start callback error: {callback_error}")
            
            # Get special tool by entity name
            entity_name = getattr(step, 'entity', None)
            if not entity_name:
                error_msg = "Special tool step missing entity name"
                logger.error(f"[{correlation_id}] {error_msg}")
                return StepResult(
                    step_number=step_number,
                    step_type="special_tool",
                    success=False,
                    error=error_msg
                )
            
            # Get the special tool
            from src.core.tools.special_tools import get_special_tool
            special_tool = get_special_tool(entity_name)
            if not special_tool:
                error_msg = f"Special tool '{entity_name}' not found"
                logger.error(f"[{correlation_id}] {error_msg}")
                return StepResult(
                    step_number=step_number,
                    step_type="special_tool",
                    success=False,
                    error=error_msg
                )
            
            # Get code template from special tool
            code_template = special_tool.get('code_template')
            if not code_template:
                error_msg = f"Special tool '{entity_name}' missing code template"
                logger.error(f"[{correlation_id}] {error_msg}")
                return StepResult(
                    step_number=step_number,
                    step_type="special_tool",
                    success=False,
                    error=error_msg
                )
            
            logger.info(f"[{correlation_id}] Generating code for special tool: {entity_name}")
            
            # Parse parameters from query_context for special tools
            parameters = self._parse_special_tool_parameters(step.query_context)
            
            # Ensure all template parameters have default values (optional parameters default to empty string)
            template_params = {
                'user_identifier': parameters.get('user_identifier', ''),
                'group_identifier': parameters.get('group_identifier', ''),
                'app_identifier': parameters.get('app_identifier', ''),
                **parameters  # Include any additional parameters
            }
            
            # Fill template with parameters (planning agent is responsible for providing correct parameters)
            generated_code = code_template.format(**template_params)
            
            logger.debug(f"[{correlation_id}] Generated special tool code: {len(generated_code)} characters")
            logger.debug(f"[{correlation_id}] Parameters passed from planning agent: {parameters}")
            logger.debug(f"[{correlation_id}] Template parameters used: {template_params}")
            
            # Execute the generated code in subprocess (exactly like API execution)
            execution_result = await self._execute_generated_code(
                generated_code,
                correlation_id,
                step,
                step_number,
                callback_step_number
            )
            
            logger.info(f"[{correlation_id}] Special tool execution completed")
            
            # Check if execution was successful
            is_successful = execution_result.get('success', False)
            result_data = execution_result.get('output', [])
            
            if is_successful:
                logger.info(f"[{correlation_id}] Special tool '{entity_name}' executed successfully")
                
                # REPEATABLE PATTERN: Store results for next step access
                variable_name = self._store_step_data(
                    step_number=step_number,
                    step_type="special_tool",
                    data=result_data,
                    metadata={
                        "tool_name": entity_name,
                        "execution_method": "subprocess_code_execution",
                        "parameters": parameters
                    },
                    step_context=step.query_context
                )
                
                logger.info(f"[{correlation_id}] Special tool results stored as {variable_name}")
            else:
                error_msg = execution_result.get('error', 'Special tool execution failed')
                logger.error(f"[{correlation_id}] Special tool '{entity_name}' failed: {error_msg}")
            
            # NEW STANDARDIZED: STEP-END callback
            step_end_time = time.time()
            step_duration = step_end_time - step_start_time
            if self.step_end_callback:
                try:
                    await self.step_end_callback(
                        step_number=callback_step_number,
                        step_type="special_tool",
                        success=is_successful,
                        duration_seconds=step_duration,
                        record_count=len(result_data) if isinstance(result_data, list) else 1,
                        formatted_time=time.strftime('%H:%M:%S', time.localtime(step_end_time)),
                        error_message=None if is_successful else error_msg
                    )
                except Exception as callback_error:
                    logger.warning(f"[{correlation_id}] Special tool step end callback error: {callback_error}")
            
            return StepResult(
                step_number=step_number,
                step_type="special_tool",
                success=is_successful,
                result=execution_result
            )
            
        except Exception as e:
            logger.error(f"[{correlation_id}] Special tool step execution failed: {e}")
            return self.error_handler.handle_step_error(step, e, correlation_id, step_number)
    
    async def _execute_generated_code(self, python_code: str, correlation_id: str, step: Optional[Dict[str, Any]] = None, current_step_number: int = None, callback_step_number: int = None) -> Dict[str, Any]:
        """
        Execute generated Python code in a subprocess with access to previous step data.
        
        Args:
            python_code: The Python code to execute
            correlation_id: Correlation ID for logging
            step: Current step information
            current_step_number: Current step number for data injection
            
        Returns:
            Dict with success status and output or error
        """
        import subprocess
        import tempfile
        import json
        import shutil
        
        try:
            # SECURITY VALIDATION: Use general validation for all Python code
            logger.debug(f"[{correlation_id}] Security validation: Checking generated code for safety")
            security_result = validate_generated_code(python_code)
            
            if not security_result.is_valid:
                error_msg = f"Security violation in generated code: {'; '.join(security_result.violations)}"
                logger.error(f"[{correlation_id}] {error_msg}")
                return {
                    'success': False,
                    'error': error_msg,
                    'security_violations': security_result.violations,
                    'risk_level': security_result.risk_level
                }
            
            logger.debug(f"[{correlation_id}] Security validation passed - code is safe to execute")
            
            # Create a temporary directory for execution
            with tempfile.TemporaryDirectory() as temp_dir:
                # Copy the base API client to the temp directory
                api_client_source = os.path.join(os.path.dirname(__file__), '..', 'okta', 'client', 'base_okta_api_client.py')
                api_client_dest = os.path.join(temp_dir, 'base_okta_api_client.py')
                
                if os.path.exists(api_client_source):
                    shutil.copy2(api_client_source, api_client_dest)
                    logger.debug(f"[{correlation_id}] Copied base_okta_api_client.py to execution directory")
                else:
                    logger.warning(f"[{correlation_id}] base_okta_api_client.py not found at {api_client_source}")
                
                # Copy special tool files if they are imported in the generated code
                special_tools_dir = os.path.join(os.path.dirname(__file__), '..', 'tools', 'special_tools')
                if os.path.exists(special_tools_dir):
                    for tool_file in os.listdir(special_tools_dir):
                        if tool_file.endswith('.py') and tool_file != '__init__.py':
                            tool_name = tool_file[:-3]  # Remove .py extension
                            if tool_name in python_code:  # If the tool is imported in the generated code
                                tool_source = os.path.join(special_tools_dir, tool_file)
                                tool_dest = os.path.join(temp_dir, tool_file)
                                shutil.copy2(tool_source, tool_dest)
                                logger.debug(f"[{correlation_id}] Copied special tool {tool_file} to execution directory")
                
                # CRITICAL FIX: Inject previous step data into execution environment
                # Calculate previous step key for dynamic access
                previous_step_key = None
                if current_step_number and current_step_number > 1:
                    previous_step_num = current_step_number - 1
                    prev_step_key = f"step_{previous_step_num}"
                    if prev_step_key in self.step_metadata:
                        previous_step_type = self.step_metadata[prev_step_key].get("type", "unknown").lower()
                        previous_step_key = f"{previous_step_num}_{previous_step_type}"
                
                data_injection_code = self._generate_data_injection_code(current_step_number, correlation_id, previous_step_key)
                
                # Create the main execution file
                temp_file_path = os.path.join(temp_dir, 'generated_code.py')
                
                # Indent the entire generated code block to fit inside try/except
                indented_code = '\n'.join('    ' + line for line in python_code.split('\n'))
                
                # Wrap the code with data injection and explicit asyncio cleanup
                wrapped_code = f"""# -*- coding: utf-8 -*-
import sys
import json
import asyncio
import datetime
{data_injection_code}
try:
{indented_code}
    # Explicit asyncio cleanup to prevent hanging
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop, try to get or create one
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        
        pending = asyncio.all_tasks(loop)
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()
    except Exception:
        pass  # Ignore cleanup errors
    
    # Force immediate exit
    sys.exit(0)
except Exception as e:
    print(json.dumps({{"status": "error", "error": str(e)}}))
    sys.exit(1)
"""
                
                with open(temp_file_path, 'w', encoding='utf-8') as temp_file:
                    temp_file.write(wrapped_code)
                
                # LOG TEMP FILE PATH for debugging
                logger.info(f"[{correlation_id}] Generated code written to: {temp_file_path}")
                logger.debug(f"[{correlation_id}] Wrapped code size: {len(wrapped_code)} bytes")
            
                # Execute the code with appropriate timeout based on entity type
                logger.debug(f"[{correlation_id}] Executing generated code in subprocess...")
                
                # CANCELLATION CHECK - Before subprocess execution
                if correlation_id in self.cancelled_queries:
                    logger.warning(f"[{correlation_id}] SUBPROCESS CANCELLED - Not executing generated code due to cancellation")
                    # Clean up Polars DataFrames from memory
                    try:
                        if hasattr(self, 'polars_dataframes') and correlation_id in self.polars_dataframes:
                            del self.polars_dataframes[correlation_id]
                            logger.debug(f"[{correlation_id}] Polars DataFrames cleared from memory during cancellation")
                    except Exception:
                        pass  # Ignore cleanup errors during cancellation
                    
                    return {
                        "success": False,
                        "data": [],
                        "error": "Query cancelled before subprocess execution",
                        "cancelled": True
                    }
                
                # Use standard API timeout for all API operations (including system_log)
                execution_timeout = API_EXECUTION_TIMEOUT
                logger.debug(f"[{correlation_id}] Using API timeout: {execution_timeout} seconds")
                
                # PURE ASYNCIO APPROACH: Use asyncio.create_subprocess_exec for real-time progress streaming
                import asyncio
                
                                # Define async callback for progress events forwarding to SSE
                async def progress_callback(event_data: str):
                    """Forward progress events to SSE via callback mechanism"""
                    if event_data.startswith('__PROGRESS__'):
                        parts = event_data.split(' ', 1)
                        if len(parts) == 2:
                            try:
                                evt = json.loads(parts[1])
                                evt_type = evt.get('type')
                                # Only log essential progress events - entity operations and rate limits
                                if evt_type in ['entity_start', 'entity_progress', 'entity_complete', 'rate_limit_wait']:
                                    logger.info(f"[{correlation_id}] PROGRESS {evt_type}: {evt}")
                                    
                                    # REAL-TIME SSE: Forward to SSE system via callback
                                    if self.subprocess_progress_callback:
                                        try:
                                            await self.subprocess_progress_callback(
                                                event_type=evt_type,
                                                event_data=evt,
                                                correlation_id=correlation_id
                                            )
                                        except Exception as callback_error:
                                            logger.warning(f"[{correlation_id}] Subprocess progress callback error: {callback_error}")
                            except json.JSONDecodeError:
                                logger.debug(f"[{correlation_id}] Failed to parse progress JSON: {parts[1]}")                # Use pure asyncio subprocess execution
                result = await self._execute_subprocess_with_streaming(
                    [sys.executable, "-u", temp_file_path],
                    progress_callback,
                    execution_timeout,
                    correlation_id,
                    cwd=temp_dir
                )
            
            # Parse the output
            if result.returncode == 0 and result.stdout.strip():
                try:
                    # DEBUG: Log raw subprocess output before parsing
                    #logger.debug(f"[{correlation_id}] Raw subprocess stdout ({len(result.stdout)} chars): {result.stdout}")
                    # Filter out __PROGRESS__ lines from stderr dump to avoid noise
                    filtered_stderr = '\n'.join([
                        line for line in result.stderr.split('\n') 
                        if not line.strip().startswith('__PROGRESS__')
                    ])
                    logger.debug(f"[{correlation_id}] Raw subprocess stderr ({len(filtered_stderr)} chars): {filtered_stderr}")

                    output = json.loads(result.stdout.strip())
                    
                    # DEBUG: Log parsed JSON structure
                    #logger.debug(f"[{correlation_id}] Parsed JSON type: {type(output)}")
                    #logger.debug(f"[{correlation_id}] Parsed JSON keys: {list(output.keys()) if isinstance(output, dict) else 'Not a dict'}")
                    logger.debug(f"[{correlation_id}] JSON status: {output.get('status') if isinstance(output, dict) else 'No status'}")
                    
                    if output.get('status') == 'success':
                        data = output.get('data', [])
                        #logger.debug(f"[{correlation_id}] Extracted data type: {type(data)}")
                        logger.debug(f"[{correlation_id}] Extracted data length: {len(data) if hasattr(data, '__len__') else 'No length'}")
                        
                        # Print just the first entry to avoid logging huge data structures
                        if isinstance(data, list) and len(data) > 0:
                            first_entry = data[0]
                            # If it's a dict, truncate any arrays to show only first item
                            if isinstance(first_entry, dict):
                                sample_entry = {k: (v[:1] if isinstance(v, list) and len(v) > 0 else v) for k, v in first_entry.items()}
                                logger.debug(f"[{correlation_id}] First data entry: {sample_entry}")
                            else:
                                logger.debug(f"[{correlation_id}] First data entry: {first_entry}")
                        elif isinstance(data, dict):
                            logger.debug(f"[{correlation_id}] Data sample: {dict(list(data.items())[:1])}")  # First 1 key-value pair
                        else:
                            logger.debug(f"[{correlation_id}] Extracted data content: {data}")
                        
                        logger.debug(f"[{correlation_id}] Code execution successful")
                        return {
                            'success': True,
                            'output': data,
                            'stdout': result.stdout,
                            'stderr': result.stderr
                        }
                    else:
                        logger.error(f"[{correlation_id}] Code execution failed: {output.get('error', 'Unknown error')}")
                        return {
                            'success': False,
                            'error': output.get('error', 'Unknown error'),
                            'stdout': result.stdout,
                            'stderr': result.stderr
                        }
                except json.JSONDecodeError:
                    logger.error(f"[{correlation_id}] Generated code did not output valid JSON. This is a critical failure.")
                    logger.error(f"[{correlation_id}] Raw stdout: {result.stdout}")
                    logger.error(f"[{correlation_id}] Raw stderr: {result.stderr}")
                    return {
                        'success': False,
                        'error': 'Generated code must output valid JSON format. Check API Code Generation Agent prompt compliance.',
                        'stdout': result.stdout,
                        'stderr': result.stderr
                    }
            else:
                # Log stdout/stderr for failed subprocess to help debugging
                logger.error(f"[{correlation_id}] Subprocess failed - returncode: {result.returncode}")
                logger.error(f"[{correlation_id}] Subprocess stdout: {result.stdout}")
                logger.error(f"[{correlation_id}] Subprocess stderr: {result.stderr}")
                
                error_msg = result.stderr or f"Process failed with return code {result.returncode}"
                logger.error(f"[{correlation_id}] Code execution failed: {error_msg}")
                return {
                    'success': False,
                    'error': error_msg,
                    'stdout': result.stdout,
                    'stderr': result.stderr
                }
                
        except subprocess.TimeoutExpired:
            timeout_used = API_EXECUTION_TIMEOUT
            logger.error(f"[{correlation_id}] Code execution timed out after {timeout_used} seconds")
            return {
                'success': False,
                'error': f'Code execution timed out after {timeout_used} seconds'
            }
        except Exception as e:
            logger.error(f"[{correlation_id}] Code execution failed with exception: {e}")
            return {
                'success': False,
                'error': f'Execution exception: {str(e)}'
            }

    async def _execute_subprocess_with_streaming(self, cmd: List[str], progress_callback: callable, timeout_seconds: int, correlation_id: str, cwd: str = None):
        """
        Execute subprocess using pure asyncio with concurrent stream reading for real-time progress events.
        
        Based on user-provided pure asyncio approach for true async subprocess execution without threading.
        
        Args:
            cmd: Command to execute as list
            progress_callback: Callback function for progress events from stderr  
            timeout_seconds: Timeout in seconds
            correlation_id: Correlation ID for logging
            cwd: Working directory for subprocess
            
        Returns:
            ProcessResult object with returncode, stdout, stderr
        """
        import asyncio
        import subprocess
        
        try:
            # Create subprocess with asyncio and increased buffer limit
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                limit=1024*1024*5  # 5MB buffer limit for large JSON output
            )
            
            stdout_lines = []
            stderr_lines = []  # COLLECT STDERR for debugging
            
            # Define async stream readers
            async def read_stdout(stream, line_list):
                """Reads all lines from stdout and appends them to a list."""
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    line_list.append(line.decode('utf-8').strip())
            
            async def read_stderr_with_callback(stream, callback, stderr_list):
                """Reads all lines from stderr, calls callback, AND saves for debugging."""
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    decoded_line = line.decode('utf-8').strip()
                    if decoded_line:  # Only process non-empty lines
                        stderr_list.append(decoded_line)  # SAVE stderr for debugging
                        await callback(decoded_line)
            
            # Run both stream readers concurrently with timeout
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        read_stdout(proc.stdout, stdout_lines),
                        read_stderr_with_callback(proc.stderr, progress_callback, stderr_lines)
                    ),
                    timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                logger.warning(f"[{correlation_id}] Subprocess timed out after {timeout_seconds} seconds, terminating...")
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning(f"[{correlation_id}] Subprocess didn't terminate gracefully, killing...")
                    proc.kill()
                    await proc.wait()
                raise subprocess.TimeoutExpired(cmd, timeout_seconds)
            
            # Wait for the process to finish and get return code
            return_code = await proc.wait()
            
            if return_code != 0:
                error_output = "\n".join(stdout_lines)
                error_stderr = "\n".join(stderr_lines)  # Include stderr
                logger.error(f"[{correlation_id}] Subprocess failed with exit code {return_code}. Stdout: {error_output}")
                logger.error(f"[{correlation_id}] Subprocess stderr: {error_stderr}")
            
            # Create result object compatible with previous code
            class ProcessResult:
                def __init__(self, returncode, stdout, stderr):
                    self.returncode = returncode
                    self.stdout = stdout
                    self.stderr = stderr
            
            return ProcessResult(
                returncode=return_code,
                stdout="\n".join(stdout_lines),
                stderr="\n".join(stderr_lines)  # Return collected stderr
            )
            
        except Exception as e:
            logger.error(f"[{correlation_id}] Pure asyncio subprocess execution failed: {e}")
            raise

    async def _execute_raw_cypher_query(self, cypher_query: str, correlation_id: str) -> List[Dict]:
        """
        Execute raw Cypher query against GraphDB and return results.
        
        Args:
            cypher_query: The Cypher query to execute
            correlation_id: Correlation ID for logging
            
        Returns:
            List of dictionaries containing query results
        """
        logger.debug(f"[{correlation_id}] Executing Cypher query against GraphDB...")
        
        # Log the actual query for debugging
        logger.info(f"[{correlation_id}] Generated Cypher query:\n{cypher_query}")
        
        # Safety check - Cypher validation already done in agent
        if not is_safe_cypher(cypher_query):
            logger.warning(f"[{correlation_id}] Cypher query failed safety check - blocking execution")
            logger.warning(f"[{correlation_id}] Unsafe query: {cypher_query}")
            return []
        
        try:
            # Import GraphDB sync operations (same class used for sync)
            from src.core.okta.graph_db.sync_operations import GraphDBSyncOperations
            from src.core.okta.graph_db.version_manager import get_version_manager
            from src.config.settings import settings
            
            # Get current database path from version manager
            version_manager = get_version_manager()
            db_path = version_manager.get_current_db_path()
            
            # Create GraphDB connection
            graph_db = GraphDBSyncOperations(db_path=db_path)
            
            # Execute Cypher query (no tenant_id parameter needed - using separate DB per tenant)
            result = graph_db.conn.execute(cypher_query)
            
            # Convert result to Polars DataFrame then to list of dicts
            results_df = result.get_as_pl()
            
            if results_df is not None and len(results_df) > 0:
                # Convert datetime columns to local timezone strings for JSON serialization
                # Assumes source data is UTC (from Okta API), converts to system local timezone
                import polars as pl
                from datetime import datetime
                import time
                
                # Get system timezone offset
                local_tz_offset = -time.timezone if time.daylight == 0 else -time.altzone
                local_tz_hours = local_tz_offset // 3600
                local_tz_minutes = abs(local_tz_offset % 3600) // 60
                local_tz_name = f"{local_tz_hours:+03d}:{local_tz_minutes:02d}"
                
                for col in results_df.columns:
                    if results_df[col].dtype in [pl.Datetime, pl.Date]:
                        # Replace timezone to UTC first (since Okta returns UTC), then convert to local
                        results_df = results_df.with_columns(
                            results_df[col]
                            .dt.replace_time_zone("UTC")  # Assume UTC from Okta
                            .dt.convert_time_zone(local_tz_name)  # Convert to local timezone with explicit offset
                            .dt.to_string("%Y-%m-%dT%H:%M:%S%z")  # Format with timezone offset
                            .alias(col)
                        )
                data = results_df.to_dicts()
            else:
                data = []
            
            logger.info(f"[{correlation_id}] Cypher query executed successfully: {len(data)} records returned")
            if data:
                logger.debug(f"[{correlation_id}] Sample record keys: {list(data[0].keys())}")
            
            return data
            
        except Exception as e:
            logger.error(f"[{correlation_id}] GraphDB query failed: {e}")
            logger.exception(e)  # Full stack trace for debugging
            return []

    async def _execute_polars_optimized_workflow_cypher(self, polars_output, api_data, correlation_id: str) -> List[Dict[str, Any]]:
        """
        Execute the Polars-optimized workflow for Cypher enrichment.
        
        1. Normalize API data to consistent format
        2. Extract IDs from API data using JSONPath
        3. Execute Cypher query with IN clause parameter
        4. Return filtered GraphDB results
        
        Args:
            polars_output: PolarsOptimizedOutput from the Cypher enrichment agent
            api_data: Raw API data to process (can be dict or list)
            correlation_id: Correlation ID for logging
            
        Returns:
            List of combined results
        """
        try:
            # Handle both single dict and list of dicts
            if isinstance(api_data, dict):
                api_records = [api_data]
                logger.debug(f"[{correlation_id}] Converted single dict to list: 1 record")
            elif isinstance(api_data, list):
                api_records = api_data
                logger.debug(f"[{correlation_id}] Using list data: {len(api_records)} records")
            else:
                logger.warning(f"[{correlation_id}] Unexpected API data type: {type(api_data)}")
                return []
            
            logger.debug(f"[{correlation_id}] Starting Cypher Polars-optimized workflow with {len(api_records)} API records")
            
            if not api_records:
                logger.warning(f"[{correlation_id}] No API data to process")
                return []
            
            # Extract IDs dynamically using the specified path
            id_extraction_path = polars_output.id_extraction_path
            logger.debug(f"[{correlation_id}] Extracting IDs using path: {id_extraction_path}")
            
            extracted_ids = []
            for i, record in enumerate(api_records):
                try:
                    if isinstance(record, str) and id_extraction_path in ['identity', 'self', '']:
                        extracted_ids.append(record)
                        continue
                    
                    if isinstance(record, dict):
                        extracted_values = self._extract_values_from_record(record, id_extraction_path)
                        extracted_ids.extend(extracted_values)
                    else:
                        if id_extraction_path in ['identity', 'self', '']:
                            extracted_ids.append(str(record))
                except Exception as e:
                    logger.debug(f"[{correlation_id}] Failed to extract from record {i}: {e}")
                    continue
            
            # Remove None values and duplicates
            user_ids = list(set([uid for uid in extracted_ids if uid is not None and uid != ""]))
            logger.info(f"[{correlation_id}] Extracted {len(user_ids)} unique IDs from {len(api_data)} API records")
            
            if not user_ids:
                logger.warning(f"[{correlation_id}] No IDs extracted from API data using path: {id_extraction_path}")
                return []
            
            # Execute Cypher query with parameter (not string replacement!)
            cypher_template = polars_output.cypher_query_template
            
            logger.debug(f"[{correlation_id}] Generated Cypher query template: {cypher_template}")
            logger.debug(f"[{correlation_id}] Executing Cypher query with {len(user_ids)} IDs...")
            
            # Import GraphDB sync operations and version manager
            from src.core.okta.graph_db.sync_operations import GraphDBSyncOperations
            from src.core.okta.graph_db.version_manager import get_version_manager
            from src.config.settings import settings
            
            # Get current database path from version manager
            version_manager = get_version_manager()
            db_path = version_manager.get_current_db_path()
            
            # Create GraphDB connection
            graph_db = GraphDBSyncOperations(db_path=db_path)
            
            # Extract parameter names used in the query (e.g., $user_ids, $group_ids)
            # Only pass the parameters that are actually referenced in the query
            import re
            used_param_names = set(re.findall(r'\$(\w+)', cypher_template))
            
            # Build parameters dict dynamically based on what the query uses
            parameters = {param_name: user_ids for param_name in used_param_names}
            
            logger.debug(f"[{correlation_id}] Detected parameters in query: {list(parameters.keys())}")
            
            # Execute Cypher query with parameters (proper parameterization!)
            result = graph_db.conn.execute(
                cypher_template,
                parameters=parameters
            )
            
            # Convert result to Polars DataFrame then to list of dicts
            results_df = result.get_as_pl()
            
            if results_df is not None and len(results_df) > 0:
                db_results = results_df.to_dicts()
            else:
                db_results = []
            
            logger.info(f"[{correlation_id}] Cypher query returned {len(db_results)} GraphDB records")
            
            if not db_results:
                logger.warning(f"[{correlation_id}] No GraphDB records found for extracted IDs")
                return []
            
            # Return GraphDB results (already filtered by the query)
            logger.info(f"[{correlation_id}] Cypher results already filtered by extracted IDs: {len(db_results)} records")
            return db_results
            
        except Exception as e:
            logger.error(f"[{correlation_id}] Cypher Polars-optimized workflow failed: {e}")
            logger.exception(e)  # Full stack trace for debugging
            return []

    # Legacy methods removed - only Polars optimization supported

    async def _emergency_cleanup(self, correlation_id: str):
        """Aggressive cleanup on cancellation - Polars DataFrame implementation"""
        try:
            # 1. Log the cancellation
            logger.warning(f"[{correlation_id}] EMERGENCY CLEANUP: Clearing DataFrames and stopping all operations")
            
            # 2. Clear ALL Polars DataFrames (memory cleanup)
            # Note: polars_dataframes is keyed by variable names like "api_data_step_1", not correlation_id
            if hasattr(self, 'polars_dataframes'):
                df_count = len(self.polars_dataframes)
                self.polars_dataframes.clear()
                logger.info(f"[{correlation_id}] Cleared {df_count} Polars DataFrames from memory")
            
            # 3. Clear any stored metadata for this query (MEMORY OPTIMIZED)
            # Note: data_variables removed during memory optimization - using polars_dataframes only
            if hasattr(self, 'step_metadata'):
                meta_count = len(self.step_metadata)
                self.step_metadata.clear()
                logger.info(f"[{correlation_id}] Cleared {meta_count} step metadata entries")
            
            # 4. Remove from cancelled set
            self.cancelled_queries.discard(correlation_id)
            
        except Exception as e:
            logger.error(f"[{correlation_id}] Emergency cleanup failed (non-critical): {e}")

    def _extract_values_from_record(self, record: Dict[str, Any], extraction_path: str) -> List[Any]:
        """
        Extract values from a record using a dot-notation path.
        
        Args:
            record: The record to extract from
            extraction_path: Dot-notation path like 'id', 'profile.login', 'user_ids.*', etc.
            
        Returns:
            List of extracted values (empty if path not found)
        """
        try:
            # Handle special array extraction syntax like 'user_ids.*'
            if extraction_path.endswith('.*'):
                array_path = extraction_path[:-2]  # Remove '.*'
                path_parts = array_path.split('.')
                
                # Navigate to the array
                current = record
                for part in path_parts:
                    if isinstance(current, dict) and part in current:
                        current = current[part]
                    else:
                        return []
                
                # If current is an array, return all items
                if isinstance(current, list):
                    return [item for item in current if item is not None]
                else:
                    return [current] if current is not None else []
            
            # Split the path into parts for normal navigation
            path_parts = extraction_path.split('.')
            
            # Navigate through the record
            current = record
            for part in path_parts:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                elif isinstance(current, list) and part.isdigit():
                    # Handle array indexing like 'items.0.id'
                    index = int(part)
                    if 0 <= index < len(current):
                        current = current[index]
                    else:
                        return []
                else:
                    return []
            
            # If we got a single value, return it as a list
            if not isinstance(current, list):
                return [current] if current is not None else []
            else:
                # If it's a list, flatten it
                return [item for item in current if item is not None]
                
        except Exception:
            return []
    
    def _parse_special_tool_parameters(self, query_context: str) -> dict:
        """
        Parse parameters from query_context for special tools.
        
        Expected format: "PARAMETERS: user_identifier='dan@fctr.io', app_identifier='Fctr Portal' | Description..."
        
        Returns:
            Dict of parameters, or empty dict if no PARAMETERS section found
        """
        if not query_context or "PARAMETERS:" not in query_context:
            return {}
        
        try:
            # Split on PARAMETERS: and take the part after it
            parts = query_context.split("PARAMETERS:", 1)
            if len(parts) < 2:
                return {}
            
            # Get the parameters part (before | or end of string)
            params_part = parts[1].split("|")[0].strip()
            
            parameters = {}
            
            # Parse key='value' pairs
            import re
            # Match patterns like: key='value' or key="value"
            pattern = r"(\w+)=(['\"])(.*?)\2"
            matches = re.findall(pattern, params_part)
            
            for match in matches:
                key, _, value = match
                parameters[key] = value
            
            return parameters
            
        except Exception as e:
            logger.warning(f"Failed to parse special tool parameters from query_context: {e}")
            return {}

# Create singleton instance
modern_executor = ModernExecutionManager()


# Utility function for easy access
async def execute_plan_steps(plan: ExecutionPlan, correlation_id: str) -> ExecutionResults:
    """
    Convenience function to execute plan steps.
    
    Args:
        plan: ExecutionPlan from planning agent
        correlation_id: Correlation ID for tracking
        
    Returns:
        ExecutionResults with all step outputs
    """
    return await modern_executor.execute_steps(plan, correlation_id)


# External cancellation API
def cancel_query_execution(correlation_id: str, reason: str = "External cancellation request") -> bool:
    """
    External API to cancel a running query execution.
    
    Args:
        correlation_id: Correlation ID of the query to cancel
        reason: Reason for cancellation
        
    Returns:
        True if cancellation was registered, False if query not found
    """
    return modern_executor.cancel_query(correlation_id, reason)