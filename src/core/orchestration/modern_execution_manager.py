"""
Modern Execution Manager for Okta AI Agent.


"""

from typing import Dict, List, Any, Optional
import asyncio
import os
import sys
import sqlite3
import json
import polars as pl  # High-performance DataFrame operations replacing temp tables
from pydantic import BaseModel

# Add src path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

# Import existing agents from agents directory
from src.core.agents.sql_code_gen_agent import sql_agent, SQLDependencies, generate_sql_query_with_logging, is_safe_sql
from src.core.agents.api_code_gen_agent import api_code_gen_agent, ApiCodeGenDependencies, generate_api_code  
from src.core.agents.planning_agent import ExecutionPlan, ExecutionStep, planning_agent, PlanningDependencies
from src.core.agents.results_formatter_agent import format_results as process_results_formatter  # Unified token-based results formatting
from src.core.agents.api_sql_code_gen_agent import api_sql_code_gen_agent  # NEW: Internal API-SQL agent

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
# - SQL Operations: 60s (1 min) - Database queries
#
# REASONING FOR VALUES:
# - API calls (including system logs) need 3 minutes for multiple paginated calls
# - SQL queries are fast, 1 minute is sufficient
# ================================================================

# API Execution Timeouts (in seconds) - Read from environment with fallbacks
API_EXECUTION_TIMEOUT = int(os.getenv('API_EXECUTION_TIMEOUT', 180))           # Subprocess timeout for API code execution (3 minutes)
SQL_EXECUTION_TIMEOUT = int(os.getenv('SQL_EXECUTION_TIMEOUT', 60))            # Subprocess timeout for SQL operations (1 minute)

# ================================================================


def _create_sql_dataframe(data: List[Dict[str, Any]]) -> pl.DataFrame:
    """
    Create Polars DataFrame from SQL query results with enhanced robustness.
    
    Uses native Polars json_normalize first for consistent handling, then falls back
    to traditional schema inference strategies for simpler SQL results.
    
    Handles complex SQL scenarios including:
    - CTE queries with multiple result sets
    - UNION queries with mixed schemas (direct vs group assignments)
    - Complex joins with duplicate/null columns  
    - JSON columns (custom_attributes) with mixed data types
    - Datetime columns with inconsistent formats
    
    Args:
        data: List of dictionaries from SQL query results (SQLAlchemy models)
        
    Returns:
        Polars DataFrame with proper schema handling for SQL data
    """
    if not data:
        return pl.DataFrame()
        
    try:
        # Strategy 1: Try json_normalize first - handles mixed schemas beautifully
        # Benefits: UNION queries, JSON columns, complex CTE results
        return pl.json_normalize(
            data,
            separator='_',           # Flatten any nested structures
            max_level=2,            # SQL is less nested than APIs, so limit levels
            infer_schema_length=None # Scan all records for consistent schema
        )
    except Exception as e:
        logger.debug(f"SQL json_normalize failed, trying traditional approach: {e}")
        try:
            # Strategy 2: Enhanced schema inference for complex SQL results
            # Scan more records to handle UNION queries with mixed schemas
            return pl.DataFrame(data, infer_schema_length=500)
        except Exception as e2:
            logger.warning(f"SQL DataFrame creation failed with full inference: {e2}")
            try:
                # Strategy 3: Conservative inference for datetime conflicts
                # Common issue: mixed datetime formats from different tables
                return pl.DataFrame(data, infer_schema_length=100)
            except Exception as e3:
                logger.warning(f"SQL DataFrame creation failed with limited inference: {e3}")
                try:
                    # Strategy 4: Minimal inference - force string types first
                    # Handles complex CTEs with inconsistent column types
                    return pl.DataFrame(data, infer_schema_length=1)
                except Exception as e4:
                    logger.warning(f"SQL DataFrame creation failed with minimal inference: {e4}")
                    try:
                        # Strategy 5: No inference - all columns as strings
                        # Last resort for highly complex UNION/CTE results
                        return pl.DataFrame(data, infer_schema_length=0)
                    except Exception as e5:
                        logger.error(f"All SQL DataFrame creation strategies failed: {e5}")
                        # Absolute last resort - empty DataFrame
                        return pl.DataFrame()


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
        # Fallback to existing robust function for compatibility
        try:
            return _create_sql_dataframe(data)
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
        self.sql_tables = {table['name']: {'columns': table['columns']} 
                          for table in self.simple_ref_data.get('sql_tables', [])}
        self.endpoints = self.full_api_data.get('endpoints', [])  # Load endpoints for filtering
        
        # Legacy operation mapping for backwards compatibility (generate from entities)
        self.operation_mapping = {}
        for entity_name, entity_data in entities_dict.items():
            for operation in entity_data['operations']:
                # Extract base operation from entity-first format (e.g., "user_list" -> "list")
                if '_' in operation and operation.startswith(entity_name + '_'):
                    base_operation = operation[len(entity_name) + 1:]
                    self.operation_mapping[operation] = {'entity': entity_name, 'operation': base_operation}
        self.endpoints = self.full_api_data.get('endpoints', [])  # Load endpoints for filtering
        
        # REPEATABLE DATA FLOW PATTERN: Variable-based data management
        # Based on proven old executor approach - scales with any number of tools/steps
        self.data_variables = {}      # Legacy compatibility - FULL POLARS architecture uses polars_dataframes
        self.step_metadata = {}       # Step tracking: {"step_1": {"type": "sql", "success": True, "record_count": 1000, "step_context": "query"}}
        
        # POLARS DATAFRAME ENHANCEMENT: High-performance DataFrame storage replacing temp tables
        self.polars_dataframes: Dict[str, pl.DataFrame] = {}  # {"sql_data_step_1": DataFrame, "api_data_step_2": DataFrame}
        
        # EXECUTION PLAN ACCESS: Store current execution plan for external access (minimal for realtime interface)
        self.current_execution_plan = None
        self.plan_ready_callback = None  # Optional callback for when plan is ready
        self.step_status_callback = None  # Optional callback for step status updates (step_number, step_type, status)
        self.planning_phase_callback = None  # Optional callback for planning lifecycle ('planning_start'/'planning_complete')
        
        # MINIMAL CANCELLATION SYSTEM: Aggressive termination on user request
        self.cancelled_queries = set()  # Just store correlation_ids that are cancelled
        
        logger.info(f"Modern Execution Manager initialized: {len(self.available_entities)} API entities, {len(self.sql_tables)} SQL tables, {len(self.endpoints)} endpoints")
    
    # DATABASE HEALTH CHECK METHODS
    
    def _check_database_health(self) -> bool:
        """
        Check if the SQLite database exists and is populated with users.
        
        Returns:
            bool: True if database exists and has users (>= 1), False otherwise
        """
        try:
            # Get database path from settings or default location
            from src.config.settings import Settings
            settings = Settings()
            
            # Try multiple possible database locations
            possible_db_paths = [
                getattr(settings, 'database_path', None),
                os.path.join(os.getcwd(), 'sqlite_db', 'okta_sync.db'),
                os.path.join(os.path.dirname(__file__), '..', '..', '..', 'sqlite_db', 'okta_sync.db'),
                'sqlite_db/okta_sync.db'
            ]
            
            db_path = None
            for path in possible_db_paths:
                if path and os.path.exists(path):
                    db_path = path
                    break
            
            if not db_path:
                logger.warning("Database file not found in any expected location")
                return False
            
            # Check if database is accessible and has users
            with sqlite3.connect(db_path, timeout=5) as conn:
                cursor = conn.cursor()
                
                # Check if users table exists
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
                if not cursor.fetchone():
                    logger.warning("Users table not found in database")
                    return False
                
                # Check if users table has at least 1 record
                cursor.execute("SELECT COUNT(*) FROM users")
                user_count = cursor.fetchone()[0]
                
                logger.info(f"Database health check: Found {user_count} users in database")
                return user_count >= 1
                
        except Exception as e:
            logger.warning(f"Database health check failed: {e}")
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
        Public method to check database health status.
        
        Returns:
            Dict with database health information for API endpoints/frontend
        """
        try:
            is_healthy = self._check_database_health()
            
            # Get additional database info
            from src.config.settings import Settings
            settings = Settings()
            
            # Try to get database path and stats
            possible_db_paths = [
                getattr(settings, 'database_path', None),
                os.path.join(os.getcwd(), 'sqlite_db', 'okta_sync.db'),
                os.path.join(os.path.dirname(__file__), '..', '..', '..', 'sqlite_db', 'okta_sync.db'),
                'sqlite_db/okta_sync.db'
            ]
            
            db_path = None
            db_size = 0
            user_count = 0
            table_count = 0
            
            for path in possible_db_paths:
                if path and os.path.exists(path):
                    db_path = path
                    db_size = os.path.getsize(path)
                    break
            
            if db_path and is_healthy:
                try:
                    with sqlite3.connect(db_path, timeout=5) as conn:
                        cursor = conn.cursor()
                        
                        # Get user count
                        cursor.execute("SELECT COUNT(*) FROM users")
                        user_count = cursor.fetchone()[0]
                        
                        # Get table count
                        cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
                        table_count = cursor.fetchone()[0]
                        
                except Exception as e:
                    logger.warning(f"Failed to get database stats: {e}")
            
            return {
                "healthy": is_healthy,
                "database_path": db_path,
                "database_size_bytes": db_size,
                "user_count": user_count,
                "table_count": table_count,
                "sql_available": is_healthy,
                "api_available": True,  # API is always available
                "recommendation": "SQL and API modes available" if is_healthy else "API-only mode recommended"
            }
            
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return {
                "healthy": False,
                "error": str(e),
                "sql_available": False,
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
                    # Choose DataFrame creation method based on step type
                    if step_type in ('api', 'api_sql'):
                        # Use native Polars json_normalize for complex API responses and API_SQL (which contains API-like nested data)
                        df = _create_api_dataframe(data)
                        logger.debug(f"Created API Polars DataFrame: {df.shape[0]} rows × {df.shape[1]} columns")
                    else:
                        # Use robust handling for SQL and other step types
                        df = _create_sql_dataframe(data)
                        logger.debug(f"Created Polars DataFrame: {df.shape[0]} rows × {df.shape[1]} columns")
                    
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
                logger.debug(f"Created Polars DataFrame from single record: {df.shape[0]} rows × {df.shape[1]} columns")
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
                if not data:
                    step_schemas[step_name] = {
                        "step_name": step_name,
                        "record_count": 0,
                        "columns": [],
                        "data_type": "empty",
                        "sample_keys": []
                    }
                    continue
                
                # Create Polars DataFrame to analyze structure
                df = pl.DataFrame(data)
                
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
                    "record_count": len(data),
                    "columns": column_info,
                    "data_type": "flattened_dataframe",
                    "key_columns": key_columns,
                    "sample_keys": list(data[0].keys()) if data else [],
                    "is_user_data": any('user' in col.lower() for col in df.columns),
                    "is_group_data": any('group' in col.lower() for col in df.columns),
                    "is_app_data": any('app' in col.lower() for col in df.columns),
                    "is_role_data": any('role' in col.lower() or 'label' in col.lower() for col in df.columns),
                    "has_nested_data": any('List' in str(df[col].dtype) or 'Struct' in str(df[col].dtype) for col in df.columns)
                }
                
            except Exception as e:
                # Fallback to simple analysis
                step_schemas[step_name] = {
                    "step_name": step_name,
                    "record_count": len(data),
                    "columns": [],
                    "data_type": "raw_list",
                    "error": str(e),
                    "sample_keys": list(data[0].keys()) if data else []
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
                
                # FULL POLARS: Get data from Polars DataFrame instead of legacy data_variables
                if variable_name in self.polars_dataframes:
                    df = self.polars_dataframes[variable_name]
                    step_data = df.to_dicts()
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
                
                # Generate the injection code with Python-compatible serialization
                injection_lines.append(f"# Step {step_num} ({step_type}) data injection")
                injection_lines.append(f"{step_sample_var} = {repr(sample_data)}")
                injection_lines.append(f"{step_context_var} = {repr(step_context)}")
                injection_lines.append(f"# Full data available as: {variable_name} = {repr(step_data)}")
                
                # CRITICAL: Add to full_results dict with consistent step_type key for Results Formatter Agent
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
        self.data_variables.clear()  # Legacy compatibility - FULL POLARS uses polars_dataframes
        self.polars_dataframes.clear()  # FULL POLARS ARCHITECTURE: Clear DataFrame storage
        self.step_metadata.clear()
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
                return json.load(f)
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
            logger.info(f"[{correlation_id}] Phase 0: Pre-Planning Agent execution")
            
            # Use the enhanced pre-planning agent to select relevant entities
            from src.core.agents.preplan_agent import select_relevant_entities
            
            # Get the lightweight reference data for entity selection
            lightweight_ref = self.simple_ref_data
            entities_dict = lightweight_ref.get('entities', {})
            
            preplan_result = await select_relevant_entities(
                query=modified_query,
                entity_summary=self.entity_summary,
                sql_tables=self.sql_tables,
                flow_id=correlation_id,
                available_entities=list(entities_dict.keys()) if entities_dict else None,
                entities=entities_dict
            )
            
            if not preplan_result.get('success', False):
                logger.error(f"[{correlation_id}] Pre-planning failed: {preplan_result.get('error', 'Unknown error')}")
                return {
                    'success': False,
                    'error': f"Pre-planning failed: {preplan_result.get('error', 'Unknown error')}",
                    'correlation_id': correlation_id,
                    'query': query,
                    'phase': 'preplan_error'
                }
            
            selected_entity_operations = preplan_result['selected_entity_operations']
            entity_op_pairs = [f"{eo.entity}::{eo.operation or 'null'}" for eo in selected_entity_operations]
            logger.info(f"[{correlation_id}] Pre-planning completed - selected entity-operation pairs: {entity_op_pairs}")
            
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
                            filtered_entity_summary[entity_name]['methods'].append(method)
            
            # Phase 1: Use Planning Agent to generate execution plan
            logger.info(f"[{correlation_id}] Phase 1: Planning Agent execution")
            # Notify planning start (minimal hook)
            if self.planning_phase_callback:
                try:
                    await self.planning_phase_callback('planning_start')
                except Exception as cb_err:
                    logger.debug(f"[{correlation_id}] planning_phase_callback planning_start error ignored: {cb_err}")
            
            # Create dependencies for Planning Agent with filtered endpoint data
            logger.info(f"[{correlation_id}] Built focused entity data: {len(endpoint_based_entities)} entities with {len(unique_endpoints)} endpoints")
            
            planning_deps = PlanningDependencies(
                available_entities=list(endpoint_based_entities.keys()),  # Use filtered entity names
                entity_summary=filtered_entity_summary,  # Use filtered entity summary
                sql_tables=self.sql_tables,
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
            logger.info(f"[{correlation_id}] Phase 2: Step execution with Modern Execution Manager")
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
            
            # Build step_results_for_processing using FULL POLARS architecture (FULL DATASETS)
            step_results_for_processing = {}
            raw_results = {}
            
            # FULL POLARS: Collect ALL data from polars_dataframes storage
            all_collected_data = []
            for variable_name, df in self.polars_dataframes.items():
                data = df.to_dicts() if not df.is_empty() else []
                logger.debug(f"[{correlation_id}] FULL POLARS: Added {variable_name.split('_')[0]} data from {variable_name}: {len(data)} records")
                all_collected_data.extend(data)
            
            # Build step results for processing with ACTUAL DATA (Generic for all step types)
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
                    
                    # FULL POLARS ARCHITECTURE: Find data in polars_dataframes instead of data_variables
                    step_data = []
                    found_variable = None
                    for variable_name in possible_variable_names:
                        if variable_name in self.polars_dataframes:
                            # Convert Polars DataFrame to list of dicts for Results Formatter
                            df = self.polars_dataframes[variable_name]
                            step_data = df.to_dicts() if not df.is_empty() else []
                            found_variable = variable_name
                            break
                    
                    if found_variable:
                        # Build result dictionary based on step type characteristics
                        if 'sql' in step_type_lower:
                            # SQL-like steps (SQL, API_SQL, etc.)
                            result_dict = {
                                'success': True,
                                'sql': getattr(step_result.result, 'sql', ''),
                                'explanation': getattr(step_result.result, 'explanation', ''),
                                'data': step_data
                            }
                            raw_results['sql_execution'] = result_dict
                        else:
                            # API-like steps (API, etc.)
                            raw_results['execution_result'] = {'execution_output': step_data}
                        
                        step_results_for_processing[step_name] = step_data
                        logger.debug(f"[{correlation_id}] FULL POLARS: Added {step_result.step_type} data from {found_variable}: {len(step_data)} records")
                    else:
                        logger.warning(f"[{correlation_id}] FULL POLARS: No data found for {step_result.step_type} step {i} (tried: {possible_variable_names})")
            
            # Log total data being passed to Results Formatter
            total_records = sum(len(data) for data in step_results_for_processing.values() if isinstance(data, list))
            logger.info(f"[{correlation_id}] Passing {total_records} total records to Results Formatter")
            
            # Analyze data structure using Polars for Results Formatter
            step_schemas = self._analyze_step_data_structures(step_results_for_processing)
            logger.debug(f"[{correlation_id}] Generated data structure schemas for Results Formatter: {list(step_schemas.keys())}")
            
            # Call Results Formatter Agent like backup executor - let it decide complete vs sample processing
            try:
                formatted_response = await process_results_formatter(
                    query=query,
                    results=step_results_for_processing,
                    is_sample=False,  # Pattern-based approach handles all data
                    original_plan=json.dumps(execution_plan.model_dump()),
                    metadata={"flow_id": correlation_id, "step_schemas": step_schemas}
                )
                
                logger.info(f"[{correlation_id}] Results formatting completed with {formatted_response.get('display_type', 'unknown')} format")
                logger.debug(f"[{correlation_id}] Formatted response keys: {list(formatted_response.keys())}")
                
                # CHECK FOR PROCESSING CODE: If Results Formatter generated processing code, execute it (same pattern as API/SQL agents)
                if formatted_response.get('processing_code') and formatted_response['processing_code'].strip():
                    logger.info(f"[{correlation_id}] Results Formatter generated processing code - executing with security validation")
                    
                    # Execute the processing code with same security validation as API/SQL code
                    processing_execution_result = self._execute_generated_code(
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
            
            logger.info(f"[{correlation_id}] Executing step {step_num}/{len(plan.steps)}: {step.tool_name}")
            
            # Notify step status callback - step starting
            if self.step_status_callback:
                try:
                    await self.step_status_callback(step_num, step.tool_name, "running")
                except Exception as callback_error:
                    logger.warning(f"[{correlation_id}] Step status callback error: {callback_error}")
            
            try:
                # Execute step based on type
                if step.tool_name == "sql":
                    result = await self._execute_sql_step(step, correlation_id, step_num)
                elif step.tool_name == "api":
                    result = await self._execute_api_step(step, correlation_id, step_num)
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
                if result.success:
                    successful_steps += 1
                    logger.info(f"[{correlation_id}] Step {step_num} completed successfully")
                    
                    # Notify step status callback - step completed
                    if self.step_status_callback:
                        try:
                            await self.step_status_callback(step_num, step.tool_name, "completed")
                        except Exception as callback_error:
                            logger.warning(f"[{correlation_id}] Step status callback error: {callback_error}")
                    
                    # Data storage is handled automatically in step execution methods
                    # Log current data state using FULL POLARS
                    total_dataframes = len(self.polars_dataframes)
                    total_metadata = len(self.step_metadata)
                    logger.debug(f"[{correlation_id}] Data state: {total_dataframes} DataFrames, {total_metadata} step metadata entries")
                else:
                    failed_steps += 1
                    logger.error(f"[{correlation_id}] Step {step_num} failed: {result.error}")
                    
                    # Notify step status callback - step failed
                    if self.step_status_callback:
                        try:
                            await self.step_status_callback(step_num, step.tool_name, "error")
                        except Exception as callback_error:
                            logger.warning(f"[{correlation_id}] Step status callback error: {callback_error}")
                    
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
                
                # Notify step status callback - step failed with exception
                if self.step_status_callback:
                    try:
                        await self.step_status_callback(step_num, step.tool_name, "error")
                    except Exception as callback_error:
                        logger.warning(f"[{correlation_id}] Step status callback error: {callback_error}")
                
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
    
    async def _execute_sql_step(self, step: ExecutionStep, correlation_id: str, step_number: int) -> StepResult:
        """
        Execute SQL step using repeatable variable-based data flow pattern.
        
        REPEATABLE PATTERN: 
        - Get sample data for LLM context (max 3 records)
        - Get full data from previous step for processing  
        - Store full results for next step access
        """
        try:
            # FULL POLARS: Get data from previous step using Polars DataFrame only
            full_previous_data = self._get_polars_data_from_previous_step(step_number)
            logger.debug(f"[{correlation_id}] Retrieved {len(full_previous_data)} records from Polars DataFrame")
            
            # Determine which SQL agent to use based on step position
            if step_number == 1:
                logger.info(f"[{correlation_id}] Step {step_number}: First SQL step, using User SQL Agent")
                return await self._execute_user_sql_step(step, correlation_id, step_number)
            else:
                logger.info(f"[{correlation_id}] Step {step_number}: Multi-step SQL processing, using Internal API-SQL Agent")
                return await self._execute_api_sql_step(step, full_previous_data, correlation_id, step_number)
                
        except Exception as e:
            return self.error_handler.handle_step_error(step, e, correlation_id, step_number)

    async def _execute_user_sql_step(self, step: ExecutionStep, correlation_id: str, step_number: int) -> StepResult:
        """
        Execute standard user SQL step using repeatable pattern.
        
        REPEATABLE PATTERN:
        - Get enhanced context from all previous steps
        - Execute SQL to get full results
        - Store full results using variable-based storage
        """
        # IMMEDIATE CANCELLATION CHECK - Don't start step if already cancelled
        if correlation_id in self.cancelled_queries:
            logger.warning(f"[{correlation_id}] User SQL Step {step_number} CANCELLED before execution - Skipping")
            return StepResult(
                step_number=step_number,
                step_type="sql",
                success=False,
                error="Query cancelled before step execution"
            )
        
        logger.debug(f"[{correlation_id}] Executing user SQL step")
        
        # Get enhanced context from all previous steps
        all_step_contexts = self._get_all_previous_step_contexts_and_samples(step_number, max_samples=3)
        logger.debug(f"[{correlation_id}] Enhanced context: {len(all_step_contexts)} previous step contexts provided")
        
        # Call existing SQL Agent with enhanced logging using wrapper function
        logger.debug(f"[{correlation_id}] Calling User SQL Agent with context: {step.query_context}")
        
        sql_result_dict = await generate_sql_query_with_logging(
            question=step.query_context,
            tenant_id=self.tenant_id,  # Keep this for SQL agent (different from API-SQL agent)
            include_deleted=False,
            flow_id=correlation_id,
            all_step_contexts=all_step_contexts  # NEW: Enhanced context from all previous steps
        )
        
        # Handle both dictionary response and AgentRunResult response
        if hasattr(sql_result_dict, 'output'):
            sql_dict = {
                'success': True,
                'sql': sql_result_dict.output.sql,
                'explanation': sql_result_dict.output.explanation,
                'usage': getattr(sql_result_dict, 'usage', lambda: None)()
            }
        else:
            sql_dict = sql_result_dict
        
        # Check if the operation was successful
        if not sql_dict.get('success', False):
            error_msg = sql_dict.get('error', 'Unknown SQL generation error')
            return StepResult(
                step_number=step_number,
                step_type="SQL",
                success=False,
                error=error_msg
            )
        
        # Execute the generated SQL query against the database
        if sql_dict['sql'] and sql_dict['sql'].strip():
            db_data = await self._execute_raw_sql_query(sql_dict['sql'], correlation_id)
            logger.info(f"[{correlation_id}] SQL execution completed: {len(db_data)} records returned")
            if db_data:
                logger.debug(f"[{correlation_id}] Sample SQL record (1 of {len(db_data)}): {db_data[0]}")
        else:
            logger.warning(f"[{correlation_id}] No SQL query generated or empty query")
            db_data = []
        
        # REPEATABLE PATTERN: Store full results for next step access
        variable_name = self._store_step_data(
            step_number=step_number,
            step_type="sql",
            data=db_data,
            metadata={
                "sql_query": sql_dict['sql'],
                "explanation": sql_dict['explanation']
            }
        )
        
        logger.info(f"[{correlation_id}] SQL step completed: {len(db_data)} records stored as {variable_name}")
        
        # Check if SQL execution was successful
        has_meaningful_data = isinstance(db_data, list) and len(db_data) > 0
        sql_executed_successfully = bool(sql_dict and sql_dict.get('sql'))
        
        # SQL step is successful if SQL was generated and executed, regardless of result count
        # "No results found" is a valid successful outcome, not an error
        step_success = sql_executed_successfully
        
        if not sql_executed_successfully:
            logger.warning(f"[{correlation_id}] SQL step marked as FAILED: SQL generation or execution failed")
        elif not has_meaningful_data:
            logger.info(f"[{correlation_id}] SQL step completed successfully: no results found (query returned 0 records)")
        
        # Create result with SQL execution data
        result_data = SQLExecutionResult(sql_dict['sql'], sql_dict['explanation'], db_data)
        
        return StepResult(
            step_number=step_number,
            step_type="SQL",
            success=step_success,
            result=result_data
        )
    
    async def _execute_api_sql_step(self, step: ExecutionStep, full_data: List[Dict[str, Any]], correlation_id: str, step_number: int) -> StepResult:
        """
        Execute API - SQL step using repeatable pattern with Internal API-SQL Agent.
        
        REPEATABLE PATTERN:
        - Use enhanced context from all previous steps
        - Use full data for processing (full API data from previous step)
        - Store full SQL results for next step access
        """
        # IMMEDIATE CANCELLATION CHECK - Don't start step if already cancelled
        if correlation_id in self.cancelled_queries:
            logger.warning(f"[{correlation_id}] API-SQL Step {step_number} CANCELLED before execution - Skipping")
            return StepResult(
                step_number=step_number,
                step_type="sql",
                success=False,
                error="Query cancelled before step execution"
            )
        
        # ENHANCED PATTERN: Get context and samples from ALL previous steps
        all_step_contexts = self._get_all_previous_step_contexts_and_samples(step_number, max_samples=3)
        
        # DON'T PROCESS DATA - Just pass it through as-is, let LLM handle it
        # Only fix the data count calculation for logging
        if isinstance(full_data, list):
            data_count = len(full_data)
        elif isinstance(full_data, dict):
            # For dict responses, try to estimate records for logging only
            data_count = full_data.get('total_active_users', 1) if 'total_active_users' in full_data else 1
        else:
            data_count = 1 if full_data else 0
            
        logger.info(f"[{correlation_id}] Processing API data with Internal API-SQL Agent: {data_count} full records")
        logger.debug(f"[{correlation_id}] Enhanced context: {len(all_step_contexts)} previous step contexts provided")
        
        # ALWAYS use Polars DataFrame processing (13,964x performance improvement)
        logger.debug(f"[{correlation_id}] Using Polars DataFrame processing for all API-SQL operations")
        
        # Call Internal API-SQL Agent with Polars optimization (ONLY mode)
        result = await api_sql_code_gen_agent.process_api_data(
            api_data=full_data,
            processing_context=step.query_context,
            correlation_id=correlation_id,
            all_step_contexts=all_step_contexts,
            sql_tables=self.sql_tables,
            use_polars_optimization=True  # Always use Polars optimization
        )
        
        # Execute Polars-optimized workflow (ONLY flow)
        try:
            db_data = await self._execute_polars_optimized_workflow(
                polars_output=result.output,
                api_data=full_data,
                correlation_id=correlation_id
            )
            logger.info(f"[{correlation_id}] Polars optimization completed: {len(db_data)} results")
            
        except Exception as e:
            logger.error(f"[{correlation_id}] Polars optimization failed: {e}")
            db_data = []
        
        # REPEATABLE PATTERN: Store full SQL results for next step access
        variable_name = self._store_step_data(
            step_number=step_number,
            step_type="api_sql",
            data=db_data,
            metadata={
                "sql_query": result.output.sql_query_template,  # Use Polars template
                "explanation": result.output.explanation,
                "input_record_count": data_count,
                "polars_processing": True,  # Track that we used Polars processing
                "polars_optimization": True,  # Polars optimization mode
                "id_extraction_path": result.output.id_extraction_path
            },
            step_context=step.query_context  # NEW: Store step context
        )
        
        logger.info(f"[{correlation_id}] API-SQL step completed: {len(db_data)} records stored as {variable_name}")
        
        # Create result object that matches expected structure
        sql_query = result.output.sql_query_template  # Use Polars template
        result_data = SQLExecutionResult(sql_query, result.output.explanation, db_data)
        
        return StepResult(
            step_number=step_number,
            step_type="API_SQL",
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
            # Get filtered endpoints for this specific step (using old executor logic)
            available_endpoints = self._get_entity_endpoints_for_step(step)
            
            # HARD STOP: If no endpoints found, fail the entire query immediately
            if not available_endpoints:
                error_msg = f"CRITICAL: No API endpoints found for entity='{step.entity}', operation='{getattr(step, 'operation', None)}'. Cannot proceed with API code generation."
                logger.error(f"[{correlation_id}] {error_msg}")
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
            
            logger.info(f"[{correlation_id}] API Code Gen: Processing {actual_record_count} records")
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
            
            # Check if the wrapper function was successful
            if not api_result_dict.get('success', False):
                error_msg = api_result_dict.get('error', 'Unknown API code generation error')
                return StepResult(
                    step_number=step_number,
                    step_type="api",
                    success=False,
                    error=error_msg
                )
            
            # Phase 5: Execute the generated API code to get actual data
            logger.info(f"[{correlation_id}] Phase 5: Executing generated API code")
            logger.debug(f"[{correlation_id}] Generated {len(api_result_dict.get('code', ''))} characters of API code")
            
            # DEBUG: Log the actual generated code if debug level is enabled
            generated_code = api_result_dict.get('code', '')
            if generated_code:
                logger.info(f"[{correlation_id}] Generated API Code:\n{'-'*50}\n{generated_code}\n{'-'*50}")
            else:
                logger.warning(f"[{correlation_id}] No API code was generated!")
            
            execution_result = self._execute_generated_code(
                api_result_dict.get('code', ''), 
                correlation_id, 
                step, 
                current_step_number=step_number  # CRITICAL: Pass step number for data injection
            )
            
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
            else:
                logger.error(f"[{correlation_id}] API code execution failed: {execution_result.get('error', 'Unknown error')}")
                # Fall back to code generation result without execution
                result_data = APIExecutionResult(
                    code=api_result_dict['code'],
                    explanation=api_result_dict['explanation'],
                    data=[],
                    executed=False,
                    error=execution_result.get('error', 'Unknown error')
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
                if any(critical in error_msg for critical in ['import', 'module', 'syntax', 'indentation']):
                    execution_successful = False
                    logger.error(f"[{correlation_id}] API step has critical execution error: {execution_result.get('error')}")
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
            
            return StepResult(
                step_number=step_number,
                step_type="api",
                success=step_success,
                result=result_data
            )
            
        except Exception as e:
            return self.error_handler.handle_step_error(step, e, correlation_id, step_number)
    
    def _execute_generated_code(self, python_code: str, correlation_id: str, step: Optional[Dict[str, Any]] = None, current_step_number: int = None) -> Dict[str, Any]:
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
            logger.info(f"[{correlation_id}] Security validation: Checking generated code for safety")
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
            
            logger.info(f"[{correlation_id}] Security validation passed - code is safe to execute")
            
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
                
                # Wrap the code with data injection and error handling
                wrapped_code = f"""# -*- coding: utf-8 -*-
import sys
import json
{data_injection_code}
try:
{indented_code}
except Exception as e:
    print(json.dumps({{"status": "error", "error": str(e)}}))
"""
                
                with open(temp_file_path, 'w', encoding='utf-8') as temp_file:
                    temp_file.write(wrapped_code)
            
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
                    
                result = subprocess.run(
                    [sys.executable, temp_file_path],
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    timeout=execution_timeout,
                    cwd=temp_dir  # Set working directory to temp dir so imports work
                )
            
            # Parse the output
            if result.returncode == 0 and result.stdout.strip():
                try:
                    # DEBUG: Log raw subprocess output before parsing
                    #logger.debug(f"[{correlation_id}] Raw subprocess stdout ({len(result.stdout)} chars): {result.stdout}")
                    logger.debug(f"[{correlation_id}] Raw subprocess stderr ({len(result.stderr)} chars): {result.stderr}")

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
                            logger.debug(f"[{correlation_id}] First data entry: {data[0]}")
                        elif isinstance(data, dict):
                            logger.debug(f"[{correlation_id}] Data sample: {dict(list(data.items())[:1])}")  # First 1 key-value pair
                        else:
                            logger.debug(f"[{correlation_id}] Extracted data content: {data}")
                        
                        logger.info(f"[{correlation_id}] Code execution successful")
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

    async def _execute_raw_sql_query(self, sql_query: str, correlation_id: str, use_internal_validation: bool = False) -> List[Dict]:
        """
        Execute raw SQL query against the database and return results.
        Uses thread pool to avoid blocking the event loop.
        
        Args:
            sql_query: The SQL query to execute
            correlation_id: Correlation ID for logging
            use_internal_validation: If True, use internal SQL validation (legacy mode)
            
        Returns:
            List of dictionaries containing query results
        """
        logger.debug(f"[{correlation_id}] Executing SQL query against database...")
        
        # Safety check - use internal validation for legacy operations
        if use_internal_validation:
            from src.core.security.sql_security_validator import validate_internal_sql
            is_valid, error_msg = validate_internal_sql(sql_query, correlation_id)
            if not is_valid:
                logger.warning(f"[{correlation_id}] Internal SQL validation failed: {error_msg}")
                logger.warning(f"[{correlation_id}] Unsafe query: {sql_query}")
                return []
        else:
            # Use standard user validation
            if not is_safe_sql(sql_query):
                logger.warning(f"[{correlation_id}] SQL query failed safety check - blocking execution")
                logger.warning(f"[{correlation_id}] Unsafe query: {sql_query}")
                return []
        
        # Execute in thread pool to avoid blocking event loop
        import asyncio
        import concurrent.futures
        
        def _sync_sql_execute():
            try:
                import sqlite3
                
                # Database path (correct for new structure)
                db_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'sqlite_db', 'okta_sync.db')
                db_path = os.path.abspath(db_path)
                
                # Connect to database
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row  # Enable column access by name
                
                # Enable WAL mode for concurrent access
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA cache_size=10000")
                conn.execute("PRAGMA temp_store=memory")
                
                cursor = conn.cursor()
                
                # Execute query
                cursor.execute(sql_query)
                rows = cursor.fetchall()
                
                # Convert to list of dictionaries
                data = [dict(row) for row in rows]
                
                conn.close()
                
                return data
                
            except Exception as e:
                logger.error(f"[{correlation_id}] Database query failed: {e}")
                return []
        
        try:
            # Run SQL in thread pool
            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                data = await loop.run_in_executor(executor, _sync_sql_execute)
            
            logger.info(f"[{correlation_id}] SQL query executed successfully: {len(data)} records returned")
            if data:
                logger.debug(f"[{correlation_id}] Sample record keys: {list(data[0].keys())}")
            
            return data
            
        except Exception as e:
            logger.error(f"[{correlation_id}] Database query failed: {e}")
            return []

    async def _execute_sql_statements_sequence(self, sql_statements: List[str], correlation_id: str) -> List[Dict[str, Any]]:
        """
        Execute a sequence of SQL statements and return results from the final SELECT.
        This is for the enhanced API-SQL agent that generates complete SQL solutions.
        
        Args:
            sql_statements: List of SQL statements (CREATE, INSERT, SELECT)
            correlation_id: Correlation ID for logging
            
        Returns:
            List of query results from the final SELECT statement
        """
        logger.debug(f"[{correlation_id}] Executing {len(sql_statements)} SQL statements in sequence")
        
        # Import security validation
        from src.utils.security_config import validate_sql_for_execution
        
        # Validate all SQL statements first
        is_valid, error_msg = validate_sql_for_execution(sql_statements)
        if not is_valid:
            logger.error(f"[{correlation_id}] SQL statements failed security validation: {error_msg}")
            return []
        
        logger.info(f"[{correlation_id}] All {len(sql_statements)} SQL statements passed security validation")
        
        # Execute in thread pool to avoid blocking event loop
        import asyncio
        import concurrent.futures
        
        def _sync_sql_sequence_execute():
            """Synchronous SQL sequence execution in thread pool"""
            try:
                import sqlite3
                from src.config.settings import settings
                
                # Connect to database using same pattern as other methods
                import os
                
                # Derive database path using same logic as other methods
                database_paths = [
                    os.path.join(os.getcwd(), "sqlite_db", "okta_sync.db"),
                    os.path.join(os.path.dirname(__file__), "..", "..", "..", "sqlite_db", "okta_sync.db"),
                    "sqlite_db/okta_sync.db"
                ]
                
                db_path = None
                for path in database_paths:
                    if os.path.exists(path):
                        db_path = path
                        break
                
                if not db_path:
                    logger.error(f"[{correlation_id}] Database file not found in any expected location")
                    return []
                
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                results = []
                
                # Execute all statements in sequence
                for i, sql_stmt in enumerate(sql_statements):
                    logger.debug(f"[{correlation_id}] Executing statement {i+1}: {sql_stmt[:100]}...")
                    
                    cursor.execute(sql_stmt)
                    
                    # Only collect results from SELECT statements
                    if sql_stmt.strip().upper().startswith('SELECT'):
                        rows = cursor.fetchall()
                        statement_results = [dict(row) for row in rows]
                        results.extend(statement_results)
                        logger.debug(f"[{correlation_id}] SELECT statement {i+1} returned {len(statement_results)} rows")
                    else:
                        logger.debug(f"[{correlation_id}] Non-SELECT statement {i+1} executed successfully")
                
                # Commit all changes
                conn.commit()
                conn.close()
                
                logger.info(f"[{correlation_id}] SQL sequence execution completed: {len(results)} total results")
                return results
                
            except Exception as e:
                logger.error(f"[{correlation_id}] SQL sequence execution failed: {e}")
                return []
        
        try:
            # Run SQL sequence in thread pool
            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                data = await loop.run_in_executor(executor, _sync_sql_sequence_execute)
            
            return data
            
        except Exception as e:
            logger.error(f"[{correlation_id}] SQL sequence execution failed: {e}")
            return []

    async def _execute_polars_optimized_workflow(self, polars_output, api_data, correlation_id: str) -> List[Dict[str, Any]]:
        """
        Execute the new Polars-optimized workflow with flexible data handling.
        
        1. Normalize API data to consistent format
        2. Extract IDs from API data using JSONPath
        3. Execute SQL query with IN clause  
        4. Return filtered SQL results directly (simplified JOIN)
        
        Args:
            polars_output: PolarsOptimizedOutput from the API-SQL agent
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
            
            logger.debug(f"[{correlation_id}] Starting Polars-optimized workflow with {len(api_records)} API records")
            logger.debug(f"[{correlation_id}] Sample API data structure: {api_records[:2] if api_records else 'No data'}")
            
            if not api_records:
                logger.warning(f"[{correlation_id}] No API data to process")
                return []
            
            # Step 2: Extract IDs dynamically using the specified path
            id_extraction_path = polars_output.id_extraction_path
            logger.debug(f"[{correlation_id}] Extracting IDs using path: {id_extraction_path}")
            
            # Dynamic ID extraction using JSONPath-like logic
            extracted_ids = []
            
            logger.debug(f"[{correlation_id}] Processing {len(api_records)} API records for ID extraction")
            
            for i, record in enumerate(api_records):
                try:
                    # Handle special case where API data is simple strings (like user IDs)
                    if isinstance(record, str) and id_extraction_path in ['identity', 'self', '']:
                        extracted_ids.append(record)
                        continue
                    
                    # Handle normal dictionary records with path navigation
                    if isinstance(record, dict):
                        extracted_values = self._extract_values_from_record(record, id_extraction_path)
                        extracted_ids.extend(extracted_values)
                    else:
                        # For other data types, try to convert to string if it's a simple value
                        if id_extraction_path in ['identity', 'self', '']:
                            extracted_ids.append(str(record))
                except Exception as e:
                    logger.debug(f"[{correlation_id}] Failed to extract from record {i} using path '{id_extraction_path}': {e}")
                    continue
            
            # Remove None values and duplicates
            user_ids = list(set([uid for uid in extracted_ids if uid is not None and uid != ""]))
            logger.info(f"[{correlation_id}] Extracted {len(user_ids)} unique IDs from {len(api_data)} API records using path: {id_extraction_path}")
            
            if not user_ids:
                logger.warning(f"[{correlation_id}] No IDs extracted from API data using path: {id_extraction_path}")
                logger.debug(f"[{correlation_id}] Sample API data structure: {api_records[:2] if api_records else 'No data'}")
                return []
            
            # Step 2.5: Create API DataFrame for potential JOIN operations with schema normalization
            try:
                # Normalize API data for consistent schema
                normalized_api_records = []
                for record in api_records:
                    if isinstance(record, dict):
                        normalized_record = {}
                        for key, value in record.items():
                            # Ensure consistent data types
                            if value is None:
                                normalized_record[key] = ""
                            elif isinstance(value, (list, dict)):
                                normalized_record[key] = str(value)  # Convert complex types to strings
                            else:
                                normalized_record[key] = value
                        normalized_api_records.append(normalized_record)
                    else:
                        # Handle non-dict records
                        normalized_api_records.append({'value': str(record)})
                
                # Check if all normalized records are empty or problematic
                if not normalized_api_records:
                    api_df = pl.DataFrame()
                    logger.debug(f"[{correlation_id}] Created empty API DataFrame: no records to normalize")
                elif all(not record or (isinstance(record, dict) and not record) for record in normalized_api_records):
                    api_df = pl.DataFrame()
                    logger.debug(f"[{correlation_id}] Created empty API DataFrame: all normalized records were empty")
                else:
                    try:
                        api_df = pl.DataFrame(normalized_api_records, infer_schema_length=None)
                        logger.debug(f"[{correlation_id}] Created API DataFrame with schema normalization: {api_df.shape[0]} rows × {api_df.shape[1]} columns")
                    except Exception as e:
                        logger.warning(f"[{correlation_id}] Could not create API DataFrame with full schema, trying with limited inference: {e}")
                        try:
                            # Try with limited schema inference to handle mixed types
                            api_df = pl.DataFrame(normalized_api_records, infer_schema_length=100)
                            logger.debug(f"[{correlation_id}] Created API DataFrame with limited schema inference: {api_df.shape[0]} rows × {api_df.shape[1]} columns")
                        except Exception as e2:
                            logger.warning(f"[{correlation_id}] Could not create API DataFrame at all: {e2}")
                            api_df = None
            except Exception as e:
                logger.warning(f"[{correlation_id}] Could not create API DataFrame: {e}")
                api_df = None
            
            # Step 3: Execute SQL query with IN clause
            sql_template = polars_output.sql_query_template
            
            # Format the IN clause with proper SQL escaping
            id_placeholders = ', '.join([f"'{str(uid).replace(chr(39), chr(39) + chr(39))}'" for uid in user_ids])
            sql_query = sql_template.replace('{user_ids}', id_placeholders)
            
            logger.debug(f"[{correlation_id}] Executing SQL query: {sql_query[:200]}...")
            
            # Execute the SQL query
            db_results = await self._execute_raw_sql_query(sql_query, correlation_id)
            logger.info(f"[{correlation_id}] SQL query returned {len(db_results)} database records")
            
            if not db_results:
                logger.warning(f"[{correlation_id}] No database records found for extracted user IDs")
                return []
            
            # Step 4: Create database DataFrame - comprehensive NULL and schema handling
            try:
                # Clean and normalize database results
                clean_results = []
                for row in db_results:
                    # Create a clean copy of the row
                    clean_row = {}
                    for key, value in row.items():
                        # Handle NULL values
                        if value is None:
                            clean_row[key] = ""  # Convert NULL to empty string
                        elif isinstance(value, (list, dict)):
                            clean_row[key] = str(value)  # Convert complex types to strings
                        else:
                            clean_row[key] = value
                    clean_results.append(clean_row)
                
                if clean_results:
                    try:
                        # Try creating DataFrame with full schema inference
                        db_df = pl.DataFrame(clean_results, infer_schema_length=None)
                        logger.debug(f"[{correlation_id}] Created database DataFrame (cleaned {len(db_results)} rows): {db_df.shape[0]} rows × {db_df.shape[1]} columns")
                    except Exception as e:
                        logger.warning(f"[{correlation_id}] Full schema inference failed, trying limited: {e}")
                        try:
                            # Try with limited schema inference
                            db_df = pl.DataFrame(clean_results, infer_schema_length=100)
                            logger.debug(f"[{correlation_id}] Created database DataFrame with limited schema inference: {db_df.shape[0]} rows × {db_df.shape[1]} columns")
                        except Exception as e2:
                            logger.error(f"[{correlation_id}] All DataFrame creation attempts failed: {e2}")
                            # Fallback: return raw database results
                            logger.warning(f"[{correlation_id}] Falling back to raw database results due to DataFrame creation error")
                            return db_results
                else:
                    logger.warning(f"[{correlation_id}] No clean results after processing, returning raw data")
                    return db_results
            except Exception as e:
                logger.error(f"[{correlation_id}] Unexpected error in database DataFrame processing: {e}")
                # Fallback: return raw database results
                logger.warning(f"[{correlation_id}] Falling back to raw database results due to unexpected error")
                return db_results
            
            # Prepare API DataFrame with only needed fields
            api_fields = polars_output.api_dataframe_fields
            if api_fields and api_df is not None and not (len(api_records) > 0 and isinstance(api_records[0], str)):
                # Only filter fields if we have structured data (not raw strings)
                try:
                    # Select only the specified fields from API data
                    api_df_filtered = api_df.select(api_fields)
                    logger.debug(f"[{correlation_id}] Filtered API DataFrame to {len(api_fields)} fields: {api_fields}")
                except Exception as e:
                    logger.warning(f"[{correlation_id}] Failed to filter API fields, using all: {e}")
                    api_df_filtered = api_df
            else:
                api_df_filtered = api_df if api_df is not None else pl.DataFrame()
            
            # Handle JOIN based on data type
            join_field = polars_output.join_field
            logger.debug(f"[{correlation_id}] Joining on field: {join_field}")
            
            try:
                # Since the SQL query already filtered by the extracted IDs,
                # we can return the database results directly
                # The API data was only used for ID extraction
                result_data = db_results
                logger.info(f"[{correlation_id}] SQL results already filtered by extracted IDs: {len(result_data)} records")
                
                return result_data
                
            except Exception as e:
                logger.error(f"[{correlation_id}] Result processing failed: {e}")
                return db_results  # Fallback to raw database results
            
        except Exception as e:
            logger.error(f"[{correlation_id}] Polars-optimized workflow failed: {e}")
            return []

    # Legacy methods removed - only Polars optimization supported

    async def _emergency_cleanup(self, correlation_id: str):
        """Aggressive cleanup on cancellation - Polars DataFrame implementation"""
        try:
            # 1. Log the cancellation
            logger.warning(f"[{correlation_id}] EMERGENCY CLEANUP: Clearing DataFrames and stopping all operations")
            
            # 2. Clear Polars DataFrames (memory cleanup)
            if hasattr(self, 'polars_dataframes') and correlation_id in self.polars_dataframes:
                del self.polars_dataframes[correlation_id]
                logger.info(f"[{correlation_id}] Polars DataFrames cleared from memory")
            
            # 3. Clear any stored data for this query
            self.data_variables.clear()
            self.step_metadata.clear()
            
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