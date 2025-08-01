"""
Modern Execution Manager for Okta AI Agent.

REPEATABLE DATA FLOW ARCHITECTURE:
================================

This executor implements a variable-based data flow pattern that scales with any number of tools/steps:

1. DATA STORAGE PATTERN:
   - data_variables: {"sql_data_step_1": [all_records], "api_data_step_2": response}
   - step_metadata: {"step_1": {"type": "sql", "success": True, "record_count": 1000, "step_context": "query description"}}

2. STEP EXECUTION PATTERN:
   - Each step gets ENHANCED CONTEXT from ALL previous steps
   - Each step gets FULL data from previous step for processing
   - Each step stores FULL results using _store_step_data()

3. ADDING NEW TOOLS/STEPS:
   - Add new tool type in execute_steps() elif block
   - Create _execute_[tool]_step() method following pattern:
     * Get enhanced context: self._get_all_previous_step_contexts_and_samples(step_number, max_samples=3)
     * Get full data: self._get_full_data_from_previous_step(step_number)
     * Process with tool agent (full data for processing, enhanced context for LLM)
     * Store results: self._store_step_data(step_number, "tool_type", data, metadata, step_context)
   - No changes needed to existing steps - fully repeatable!

4. DATA ACCESS PATTERN:
   - LLM Context: Always use enhanced context from ALL previous steps for intelligent decisions
   - Processing: Always use full datasets for actual execution
   - Variable Lookup: Access any previous step data by variable name
   - Automatic Storage: All results stored with consistent naming

This replaces complex sample extraction and "last step" tracking with a clean,
scalable variable-based approach proven in the old executor.
"""

from typing import Dict, List, Any, Optional
import asyncio
import os
import sys
import sqlite3
import json
from pydantic import BaseModel

# Add src path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

# Import existing agents from agents directory
from src.core.agents.sql_code_gen_agent import sql_agent, SQLDependencies, generate_sql_query_with_logging, is_safe_sql
from src.core.agents.api_code_gen_agent import api_code_gen_agent, ApiCodeGenDependencies, generate_api_code  
from src.core.agents.planning_agent import ExecutionPlan, ExecutionStep, planning_agent
from src.core.agents.results_formatter_agent import process_results_structured
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
# - System Logs: 300s (5 min) - Extended for heavy system log queries  
# - SQL Operations: 60s (1 min) - Database queries
# - HTTP Requests: 30s - Individual API requests (used in generated code)
#
# REASONING FOR VALUES:
# - System log queries need 5 minutes due to pagination + large datasets
# - Regular API calls need 3 minutes for multiple paginated calls
# - SQL queries are fast, 1 minute is sufficient
# - HTTP requests timeout quickly to fail fast and retry
# ================================================================

# API Execution Timeouts (in seconds)
API_EXECUTION_TIMEOUT = 180           # Subprocess timeout for API code execution (3 minutes)
SYSTEM_LOG_TIMEOUT = 300              # Extended timeout for system_log queries (5 minutes)
SQL_EXECUTION_TIMEOUT = 60            # Subprocess timeout for SQL operations (1 minute)

# Database Timeouts (in seconds)
DATABASE_CONNECTION_TIMEOUT = 30      # SQLite connection timeout
SQL_QUERY_TIMEOUT = 60                # Individual SQL query execution timeout

# HTTP Request Timeouts (in seconds) - Used in generated API code
HTTP_REQUEST_TIMEOUT = 30             # Individual HTTP request timeout to Okta API

# LLM Model Timeouts (in seconds)
LLM_MODEL_TIMEOUT = 60                # AI model HTTP client timeout

# ================================================================


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
        self.data_variables = {}      # Full datasets: {"sql_data_step_1": [all_records], "api_data_step_2": response}
        self.step_metadata = {}       # Step tracking: {"step_1": {"type": "sql", "success": True, "record_count": 1000, "step_context": "query"}}
        
        # EXECUTION PLAN ACCESS: Store current execution plan for external access (minimal for realtime interface)
        self.current_execution_plan = None
        self.plan_ready_callback = None  # Optional callback for when plan is ready
        self.step_status_callback = None  # Optional callback for step status updates (step_number, step_type, status)
        
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
        Store step data using repeatable variable-based pattern.
        
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
        
        # Store full dataset
        self.data_variables[variable_name] = data
        
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
                
                # Get step data samples
                variable_name = step_metadata.get("variable_name")
                if variable_name and variable_name in self.data_variables:
                    step_data = self.data_variables[variable_name]
                    
                    # Sample the data
                    if isinstance(step_data, list):
                        step_sample = step_data[:max_samples] if len(step_data) > max_samples else step_data
                    else:
                        step_sample = step_data
                else:
                    step_sample = []
                
                # Store in the order you specified: context first, then sample
                all_contexts[f"step_{step_num}_context"] = step_context
                all_contexts[f"step_{step_num}_sample"] = step_sample
        
        return all_contexts

    def _get_full_data_from_previous_step(self, current_step_number: int) -> Any:
        """
        Get full dataset from the previous step using variable lookup.
        
        Args:
            current_step_number: Current step number
            
        Returns:
            Full dataset from previous step, or empty list if none
        """
        if current_step_number <= 1:
            return []
        
        # Look for the most recent step's variable
        previous_step_key = f"step_{current_step_number - 1}"
        if previous_step_key in self.step_metadata:
            variable_name = self.step_metadata[previous_step_key]["variable_name"]
            return self.data_variables.get(variable_name, [])
        
        return []
    
    def _generate_data_injection_code(self, current_step_number: int, correlation_id: str) -> str:
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
        
        # Inject data from all previous steps
        for step_num in range(1, current_step_number):
            step_key = f"step_{step_num}"
            
            if step_key in self.step_metadata:
                variable_name = self.step_metadata[step_key]["variable_name"]
                step_data = self.data_variables.get(variable_name, [])
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
        self.data_variables.clear()
        self.step_metadata.clear()
        logger.debug("Cleared execution data for fresh run")
    
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
            
            with open(schema_path, 'r') as f:
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
            with open(self.simple_ref_path, 'w') as f:
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
            with open(self.simple_ref_path, 'r') as f:
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
            with open(self.full_api_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning(f"Full API data file not found: {self.full_api_path}")
            return {'endpoints': []}
        except Exception as e:
            logger.error(f"Failed to load full API data: {e}")
            return {'endpoints': []}
    

    
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
            
            # Phase 1: Use Planning Agent to generate execution plan
            logger.info(f"[{correlation_id}] Phase 1: Planning Agent execution")
            
            # Create dependencies for Planning Agent (same as old executor)
            from src.core.agents.planning_agent import PlanningDependencies
            
            # Get the lightweight reference for new entities format
            lightweight_ref = self.simple_ref_data  # Use already loaded reference data
            entities = lightweight_ref.get('entities', {})
            
            planning_deps = PlanningDependencies(
                available_entities=self.available_entities,
                entity_summary=self.entity_summary,
                sql_tables=self.sql_tables,
                flow_id=correlation_id,
                entities=entities  # Pass the new entity-grouped format
            )
            
            # Execute Planning Agent with dependencies - use modified query if needed
            planning_result = await planning_agent.run(modified_query, deps=planning_deps)
            
            # Trust the agent - just extract the plan
            execution_plan = planning_result.output.plan
            
            # Store current execution plan for external access (minimal addition for realtime interface)
            self.current_execution_plan = execution_plan
            
            # Notify callback if plan is ready (minimal addition for realtime interface)
            if self.plan_ready_callback:
                await self.plan_ready_callback(execution_plan)
            
            # Pretty print the execution plan for debugging
            import json
            logger.info(f"[{correlation_id}] Generated execution plan:\n{json.dumps(execution_plan.model_dump(), indent=2)}")
            logger.info(f"[{correlation_id}] Planning completed: {len(execution_plan.steps)} steps generated")
            
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
            
            # Build step_results_for_processing using our data_variables storage (FULL DATASETS)
            step_results_for_processing = {}
            raw_results = {}
            
            # Collect ALL data from our variable-based storage
            all_collected_data = []
            for variable_name, data in self.data_variables.items():
                logger.debug(f"[{correlation_id}] Collecting data from {variable_name}: {len(data)} records")
                all_collected_data.extend(data)
            
            # Build step results for processing with ACTUAL DATA (Generic for all step types)
            for i, step_result in enumerate(execution_results.steps, 1):
                step_name = f"{i}_{step_result.step_type.lower()}"
                
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
                    
                    # Find the actual variable that exists in our storage
                    step_data = []
                    found_variable = None
                    for variable_name in possible_variable_names:
                        if variable_name in self.data_variables:
                            step_data = self.data_variables.get(variable_name, [])
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
                        logger.debug(f"[{correlation_id}] Added {step_result.step_type} data from {found_variable}: {len(step_data)} records")
                    else:
                        logger.warning(f"[{correlation_id}] No data found for {step_result.step_type} step {i} (tried: {possible_variable_names})")
            
            # Log total data being passed to Results Formatter
            total_records = sum(len(data) for data in step_results_for_processing.values() if isinstance(data, list))
            logger.info(f"[{correlation_id}] Passing {total_records} total records to Results Formatter")
            
            # Call Results Formatter Agent like old executor
            try:
                formatted_response = await process_results_structured(
                    query=query,
                    results=step_results_for_processing,
                    original_plan=str(execution_plan.model_dump()),
                    is_sample=False,
                    metadata={'flow_id': correlation_id}
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
                
                # Save results to file
                await self._save_results_to_file(query, formatted_response, step_results_for_processing, correlation_id)
                
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
                    # Log current data state
                    total_variables = len(self.data_variables)
                    total_metadata = len(self.step_metadata)
                    logger.debug(f"[{correlation_id}] Data state: {total_variables} variables, {total_metadata} step metadata entries")
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
            # REPEATABLE PATTERN: Get full data from previous step for processing
            full_previous_data = self._get_full_data_from_previous_step(step_number)
            
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
        
        step_success = has_meaningful_data and sql_executed_successfully
        
        if not step_success:
            if not has_meaningful_data:
                logger.warning(f"[{correlation_id}] SQL step marked as FAILED: no data returned from database")
            if not sql_executed_successfully:
                logger.warning(f"[{correlation_id}] SQL step marked as FAILED: SQL generation or execution failed")
        
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
        Execute API → SQL step using repeatable pattern with Internal API-SQL Agent.
        
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
        
        # ALWAYS use temp table mode to avoid placeholder issues
        # This is safer and more robust than placeholder replacement
        use_temp_table = True
        logger.debug(f"[{correlation_id}] Using temp table mode for all API-SQL operations")
        
        # Call Internal API-SQL Agent - IT handles all the complexity
        # Pass raw data through as-is - let LLM handle any processing needed
        result = await api_sql_code_gen_agent.process_api_data(
            api_data=full_data,  # REPEATABLE PATTERN: Pass raw data through as-is
            processing_context=step.query_context,
            correlation_id=correlation_id,
            use_temp_table=use_temp_table,
            all_step_contexts=all_step_contexts,  # NEW: Enhanced context from all previous steps
            sql_tables=self.sql_tables  # NEW: Pass dynamic schema information
        )
        
        # Check if enhanced API-SQL agent returned sql_statements (new format)
        if hasattr(result.output, 'sql_statements') and result.output.sql_statements:
            logger.info(f"[{correlation_id}] Executing enhanced SQL statements: {len(result.output.sql_statements)} statements")
            
            try:
                # Execute all SQL statements in sequence
                db_data = await self._execute_sql_statements_sequence(
                    sql_statements=result.output.sql_statements,
                    correlation_id=correlation_id
                )
                logger.info(f"[{correlation_id}] Enhanced API-SQL processing completed: {len(db_data)} results")
                
            except Exception as e:
                logger.error(f"[{correlation_id}] SQL statements execution failed: {e}")
                db_data = []
                
        # Legacy temp table workflow (for backward compatibility)
        elif result.output.uses_temp_table and hasattr(result.output, 'table_structure') and result.output.table_structure:
            logger.info(f"[{correlation_id}] Creating temporary table and inserting {data_count} API records (legacy mode)")
            
            try:
                # Debug output structure
                logger.debug(f"[{correlation_id}] Output fields available: {dir(result.output)}")
                logger.debug(f"[{correlation_id}] Table structure type: {type(result.output.table_structure)}")
                logger.debug(f"[{correlation_id}] Data extraction type: {type(result.output.data_extraction)}")
                
                # Execute temp table operations in a single connection session
                db_data = await self._execute_temp_table_workflow(
                    table_structure=result.output.table_structure.dict() if hasattr(result.output.table_structure, 'dict') else result.output.table_structure,
                    data_extraction=result.output.data_extraction.dict() if hasattr(result.output.data_extraction, 'dict') else result.output.data_extraction,
                    processing_query=result.output.processing_query,
                    api_data=full_data,
                    correlation_id=correlation_id
                )
                logger.info(f"[{correlation_id}] Temp table API-SQL processing completed: {len(db_data)} results")
                
            except Exception as e:
                logger.error(f"[{correlation_id}] Temp table workflow failed: {e}")
                db_data = []
            
        elif result.output.processing_query:
            # Direct mode (shouldn't happen now since we force temp table)
            db_data = await self._execute_raw_sql_query(result.output.processing_query, correlation_id)
            logger.info(f"[{correlation_id}] Direct API-SQL processing completed: {len(db_data)} results")
        else:
            logger.warning(f"[{correlation_id}] No SQL query generated by Internal API-SQL Agent")
            db_data = []
        
        # REPEATABLE PATTERN: Store full SQL results for next step access
        variable_name = self._store_step_data(
            step_number=step_number,
            step_type="api_sql",
            data=db_data,
            metadata={
                "sql_query": result.output.sql_statements[-1] if hasattr(result.output, 'sql_statements') and result.output.sql_statements else result.output.processing_query,
                "explanation": result.output.explanation,
                "input_record_count": data_count,
                "use_temp_table": use_temp_table,
                "sql_statements_count": len(result.output.sql_statements) if hasattr(result.output, 'sql_statements') else 1
            },
            step_context=step.query_context  # NEW: Store step context
        )
        
        logger.info(f"[{correlation_id}] API-SQL step completed: {len(db_data)} records stored as {variable_name}")
        
        # Create result object that matches expected structure
        sql_query = result.output.sql_statements[-1] if hasattr(result.output, 'sql_statements') and result.output.sql_statements else result.output.processing_query
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
            
            # REPEATABLE PATTERN: Get full data from previous step for processing
            full_previous_data = self._get_full_data_from_previous_step(step_number)
            actual_record_count = len(full_previous_data) if isinstance(full_previous_data, list) else 1
            
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
            
            # Use the entity field from the new format
            entity_name = step.entity or "users"
            api_result_dict = await generate_api_code(
                query=step.query_context,
                sql_record_count=actual_record_count,  # Full record count for processing logic
                available_endpoints=available_endpoints,
                entities_involved=[entity_name],
                step_description=step.reasoning if hasattr(step, 'reasoning') else step.query_context,
                correlation_id=correlation_id,
                all_step_contexts=all_step_contexts  # Enhanced context from all previous steps
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
                logger.debug(f"[{correlation_id}] Generated API Code:\n{'-'*50}\n{generated_code}\n{'-'*50}")
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
            has_meaningful_data = False
            execution_successful = False
            
            # Check if the APIExecutionResult has meaningful data
            if hasattr(result_data, 'data'):
                # result_data is an APIExecutionResult object
                if isinstance(result_data.data, list) and len(result_data.data) > 0:
                    has_meaningful_data = True
                elif isinstance(result_data.data, dict) and result_data.data:
                    has_meaningful_data = True
            else:
                # Fallback for raw data (shouldn't happen with current code)
                if isinstance(result_data, list) and len(result_data) > 0:
                    has_meaningful_data = True
                elif isinstance(result_data, dict) and result_data:
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
                    logger.warning(f"[{correlation_id}] API step marked as FAILED: no meaningful data returned")
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
                data_injection_code = self._generate_data_injection_code(current_step_number, correlation_id)
                
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
                    # Direct temp table cleanup using standard db_path pattern
                    try:
                        db_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'sqlite_db', 'okta_sync.db')
                        db_path = os.path.abspath(db_path)
                        with sqlite3.connect(db_path) as conn:
                            cursor = conn.cursor()
                            cursor.execute("DROP TABLE IF EXISTS temp_api_users")
                            cursor.execute("DROP TABLE IF EXISTS temp_api_data")
                            conn.commit()
                    except Exception:
                        pass  # Ignore cleanup errors during cancellation
                    
                    return {
                        "success": False,
                        "data": [],
                        "error": "Query cancelled before subprocess execution",
                        "cancelled": True
                    }
                
                # Determine timeout based on entity type
                if step and step.entity == 'system_log':
                    execution_timeout = SYSTEM_LOG_TIMEOUT
                    logger.debug(f"[{correlation_id}] Using system_log timeout: {execution_timeout} seconds")
                else:
                    execution_timeout = API_EXECUTION_TIMEOUT
                    logger.debug(f"[{correlation_id}] Using standard API timeout: {execution_timeout} seconds")
                    
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
                    output = json.loads(result.stdout.strip())
                    if output.get('status') == 'success':
                        logger.info(f"[{correlation_id}] Code execution successful")
                        return {
                            'success': True,
                            'output': output.get('data', []),
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
            timeout_used = SYSTEM_LOG_TIMEOUT if (step and step.entity == 'system_log') else API_EXECUTION_TIMEOUT
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
            use_internal_validation: If True, use internal SQL validation (allows temp tables)
            
        Returns:
            List of dictionaries containing query results
        """
        logger.debug(f"[{correlation_id}] Executing SQL query against database...")
        
        # Safety check - use internal validation for temp table operations
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

    async def _execute_temp_table_workflow(self, table_structure: Dict[str, Any], data_extraction: Dict[str, Any], 
                                          processing_query: str, api_data: List[Any], correlation_id: str) -> List[Dict[str, Any]]:
        """
        Execute the complete temp table workflow using LLM-provided specifications.
        Creates temp table from structure spec, extracts data using extraction spec, and runs query.
        
        Args:
            table_structure: JSON specification of table columns and types
            data_extraction: JSON specification of how to extract API data
            processing_query: Main SQL query that uses the temporary table
            api_data: Data to insert into the temporary table
            correlation_id: Correlation ID for logging
            
        Returns:
            List of query results
        """
        # Execute in thread pool to avoid blocking event loop
        import asyncio
        import concurrent.futures
        
        def _generate_safe_table_schema(table_structure: Dict[str, Any], table_name: str) -> str:
            """Generate safe SQL DDL from JSON table structure specification"""
            # Whitelist of allowed column types
            ALLOWED_TYPES = {'TEXT', 'INTEGER', 'REAL', 'BLOB'}
            
            columns = table_structure.get('columns', [])
            if not columns:
                raise ValueError("Table structure must have at least one column")
            
            column_definitions = []
            primary_keys = []
            
            for col in columns:
                # Validate column name (alphanumeric + underscore only)
                name = col.get('name', '').strip()
                if not name or not name.replace('_', '').replace('-', '').isalnum():
                    raise ValueError(f"Invalid column name: {name}")
                
                # Validate column type
                col_type = col.get('type', '').upper()
                if col_type not in ALLOWED_TYPES:
                    raise ValueError(f"Invalid column type: {col_type}. Allowed: {ALLOWED_TYPES}")
                
                # Build column definition
                col_def = f"{name} {col_type}"
                
                if col.get('primary_key', False):
                    primary_keys.append(name)
                
                column_definitions.append(col_def)
            
            # Add primary key constraint if specified
            if primary_keys:
                pk_constraint = f"PRIMARY KEY ({', '.join(primary_keys)})"
                column_definitions.append(pk_constraint)
            
            return f"CREATE TEMPORARY TABLE {table_name} ({', '.join(column_definitions)})"
        
        def _extract_data_from_api_response(api_data: List[Any], data_extraction: Dict[str, Any]) -> List[tuple]:
            """Extract data from API response using extraction specification"""
            extraction_type = data_extraction.get('extraction_type', '')
            mappings = data_extraction.get('mappings', [])
            
            extracted_rows = []
            
            # Special handling for nested_extraction with array patterns
            if extraction_type == 'nested_extraction':
                for mapping in mappings:
                    source_field = mapping.get('source_field', '')
                    if source_field.endswith('.*'):
                        # Array extraction - process differently
                        field_name = source_field.replace('.*', '')
                        logger.debug(f"Processing array extraction for field: {field_name}")
                        
                        for record in api_data:
                            if isinstance(record, dict) and field_name in record:
                                array_data = record[field_name]
                                if isinstance(array_data, list):
                                    logger.debug(f"Extracting {len(array_data)} items from {field_name}")
                                    for item in array_data:
                                        extracted_rows.append((item,))
                                else:
                                    logger.warning(f"Field {field_name} is not a list: {type(array_data)}")
                            else:
                                logger.debug(f"Record missing field {field_name} or not a dict: {type(record)}")
                        return extracted_rows
            
            # Standard extraction for other types
            for record in api_data:
                row_values = []
                record_processed = False
                
                for mapping in mappings:
                    source_field = mapping.get('source_field', '')
                    required = mapping.get('required', True)
                    default_value = mapping.get('default_value', '')
                    
                    try:
                        if extraction_type == 'dictionary_mapping':
                            # Extract from dictionary
                            if isinstance(record, dict):
                                value = record.get(source_field, default_value if not required else None)
                            else:
                                value = default_value if not required else None
                                
                        elif extraction_type == 'list_values':
                            # Extract the item itself (for string lists)
                            if source_field == '@item':
                                value = record
                            else:
                                value = default_value if not required else None
                                
                        elif extraction_type == 'nested_extraction':
                            # Handle non-array nested extraction
                            if '.' in source_field and not source_field.endswith('.*'):
                                # Navigate nested object paths like "users.id"
                                parts = source_field.split('.')
                                value = record
                                for part in parts:
                                    if isinstance(value, dict) and part in value:
                                        value = value[part]
                                    else:
                                        value = default_value if not required else None
                                        break
                            else:
                                value = default_value if not required else None
                        else:
                            value = default_value if not required else None
                        
                        if value is None and required:
                            logger.warning(f"Required field {source_field} not found in record: {record}")
                            record_processed = True
                            break
                            
                        row_values.append(value)
                        
                    except Exception as e:
                        if required:
                            logger.error(f"Error extracting {source_field}: {e}")
                            record_processed = True
                            break
                        else:
                            row_values.append(default_value)
                
                # Only add row if we have the expected number of values and no errors
                if not record_processed and row_values and len(row_values) == len(mappings):
                    extracted_rows.append(tuple(row_values))
            
            return extracted_rows
        
        def _sync_temp_table_workflow():
            try:
                import sqlite3
                
                # Database path (correct for new structure)
                db_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'sqlite_db', 'okta_sync.db')
                db_path = os.path.abspath(db_path)
                
                # Single connection for entire workflow
                conn = sqlite3.connect(db_path)
                
                try:
                    # Enable WAL mode for concurrent access  
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute("PRAGMA synchronous=NORMAL")
                    
                    cursor = conn.cursor()
                    
                    # Generate secure table name
                    table_name = f"temp_api_users_{correlation_id.replace('-', '_')}"
                    
                    # Step 1: Generate and execute safe table schema
                    temp_table_schema = _generate_safe_table_schema(table_structure, table_name)
                    logger.debug(f"[{correlation_id}] Creating temporary table with schema: {temp_table_schema}")
                    cursor.execute(temp_table_schema)
                    
                    # Step 2: Extract and insert API data using LLM specifications
                    if api_data:
                        # DEBUG: Show the actual API data structure before extraction
                        logger.debug(f"[{correlation_id}] Raw API data structure: {type(api_data)}")
                        if isinstance(api_data, list) and api_data:
                            logger.debug(f"[{correlation_id}] First API record: {api_data[0]}")
                            logger.debug(f"[{correlation_id}] API data sample: {api_data[:2]}")
                        elif isinstance(api_data, dict):
                            logger.debug(f"[{correlation_id}] API data keys: {list(api_data.keys())}")
                            logger.debug(f"[{correlation_id}] API data structure: {api_data}")
                        
                        extracted_data = _extract_data_from_api_response(api_data, data_extraction)
                        
                        # DEBUG: Show what was extracted
                        logger.debug(f"[{correlation_id}] Data extraction spec: {data_extraction}")
                        logger.debug(f"[{correlation_id}] Extracted data: {extracted_data}")
                        
                        if extracted_data:
                            # Build parameterized insert query
                            columns = [col['name'] for col in table_structure.get('columns', [])]
                            placeholders = ', '.join(['?' for _ in columns])
                            insert_sql = f"INSERT OR IGNORE INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
                            
                            logger.debug(f"[{correlation_id}] Inserting {len(extracted_data)} rows into temp table")
                            cursor.executemany(insert_sql, extracted_data)
                            
                            rows_inserted = cursor.rowcount
                            logger.debug(f"[{correlation_id}] Successfully inserted {rows_inserted} rows into temp table")
                        else:
                            logger.warning(f"[{correlation_id}] No data extracted from API response")
                    else:
                        logger.warning(f"[{correlation_id}] No API data provided for temp table")
                    
                    # Step 3: Execute the main processing query
                    # Replace temp_api_users with actual table name in query
                    actual_query = processing_query.replace('temp_api_users', table_name)
                    logger.debug(f"[{correlation_id}] Executing processing query: {actual_query}")
                    
                    # DEBUG: Show what user IDs are in the temp table for debugging
                    cursor.execute(f"SELECT okta_id FROM {table_name}")
                    temp_user_ids = [row[0] for row in cursor.fetchall()]
                    logger.debug(f"[{correlation_id}] Temp table contains user IDs: {temp_user_ids}")
                    
                    # Execute query without parameters since tenant_id is now injected directly into the query
                    cursor.execute(actual_query)
                    columns = [description[0] for description in cursor.description]
                    results = cursor.fetchall()
                    
                    # Convert to list of dictionaries
                    result_dicts = []
                    for row in results:
                        result_dict = dict(zip(columns, row))
                        result_dicts.append(result_dict)
                    
                    logger.debug(f"[{correlation_id}] Query returned {len(result_dicts)} results")
                    
                    # Step 4: Cleanup - drop temp table
                    cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
                    logger.debug(f"[{correlation_id}] Cleaned up temporary table: {table_name}")
                    
                    return result_dicts
                
                except Exception as e:
                    logger.error(f"[{correlation_id}] Error in temp table workflow: {e}")
                    raise
                finally:
                    conn.close()
                    
            except Exception as e:
                logger.error(f"[{correlation_id}] Failed to execute temp table workflow: {e}")
                raise
        
        try:
            # Run workflow in thread pool
            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                return await loop.run_in_executor(executor, _sync_temp_table_workflow)
        except Exception as e:
            logger.error(f"[{correlation_id}] Failed to execute temp table workflow: {e}")
            raise

    async def _insert_api_data_into_temp_table(self, api_data: List[Dict[str, Any]], correlation_id: str) -> None:
        """
        Insert API data into the temporary table created by the API-SQL agent.
        Uses thread pool to avoid blocking the event loop.
        
        Args:
            api_data: List of API response data to insert
            correlation_id: Correlation ID for logging
        """
        if not api_data:
            logger.warning(f"[{correlation_id}] No API data to insert into temp table")
            return
        
        # Execute in thread pool to avoid blocking event loop
        import asyncio
        import concurrent.futures
        
        def _sync_insert_data():
            try:
                import sqlite3
                
                # Database path (correct for new structure)
                db_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'sqlite_db', 'okta_sync.db')
                db_path = os.path.abspath(db_path)
                
                # Connect to database
                conn = sqlite3.connect(db_path)
                
                # Enable WAL mode for concurrent access  
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                
                cursor = conn.cursor()
                
                # Get the first record to determine the structure
                first_record = api_data[0]
                
                # Handle both string lists (user IDs) and dictionary lists
                if isinstance(first_record, str):
                    # Convert string list to dictionary list for temp table insertion
                    # Assume these are okta_id values for temp_api_users table
                    columns = ['okta_id']
                    logger.debug(f"[{correlation_id}] Converting string list to okta_id dictionary format")
                else:
                    # Dictionary format - always use okta_id schema for consistency
                    columns = ['okta_id']
                    logger.debug(f"[{correlation_id}] Using okta_id extraction for dictionary format")
                
                # Create parameterized INSERT statement
                # Assume temp table is named temp_api_users (standard from prompt)
                placeholders = ', '.join(['?' for _ in columns])
                column_names = ', '.join(columns)
                
                insert_sql = f"INSERT OR IGNORE INTO temp_api_users ({column_names}) VALUES ({placeholders})"
                
                logger.debug(f"[{correlation_id}] Inserting {len(api_data)} records into temp table")
                logger.debug(f"[{correlation_id}] Insert SQL: {insert_sql}")
                
                # Insert all records
                for record in api_data:
                    if isinstance(record, str):
                        # Handle string records (user IDs) - convert to dictionary format
                        values = [record]  # okta_id value
                    else:
                        # Handle dictionary records - extract okta_id intelligently
                        if 'user_id' in record:
                            # Role assignment format
                            values = [record['user_id']]
                        elif 'actor' in record and 'id' in record.get('actor', {}):
                            # Login event format
                            values = [record['actor']['id']]
                        elif 'id' in record:
                            # Standard user record
                            values = [record['id']]
                        else:
                            # Cannot extract - skip record
                            logger.warning(f"[{correlation_id}] Cannot extract okta_id, skipping record")
                            continue
                    cursor.execute(insert_sql, values)
                
                conn.commit()
                cursor.close()
                conn.close()
                
                logger.info(f"[{correlation_id}] Successfully inserted {len(api_data)} records into temp table")
                
            except Exception as e:
                logger.error(f"[{correlation_id}] Failed to insert API data into temp table: {e}")
                raise
        
        try:
            # Run insertion in thread pool
            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                await loop.run_in_executor(executor, _sync_insert_data)
        except Exception as e:
            logger.error(f"[{correlation_id}] Failed to insert API data into temp table: {e}")
            raise

    async def _cleanup_temp_table(self, correlation_id: str) -> None:
        """
        Drop the temporary table created during API-SQL processing.
        Uses thread pool to avoid blocking the event loop.
        
        Args:
            correlation_id: Correlation ID for logging
        """
        # Execute in thread pool to avoid blocking event loop
        import asyncio
        import concurrent.futures
        
        def _sync_cleanup():
            try:
                import sqlite3
                
                # Database path (correct for new structure)
                db_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'sqlite_db', 'okta_sync.db')
                db_path = os.path.abspath(db_path)
                
                # Connect to database
                conn = sqlite3.connect(db_path)
                
                # Enable WAL mode for concurrent access
                conn.execute("PRAGMA journal_mode=WAL")
                
                cursor = conn.cursor()
                
                # Drop the temp table (standard name from prompt)
                drop_sql = "DROP TABLE IF EXISTS temp_api_users"
                cursor.execute(drop_sql)
                
                conn.commit()
                cursor.close()
                conn.close()
                
                logger.debug(f"[{correlation_id}] Temporary table cleaned up successfully")
                
            except Exception as e:
                logger.warning(f"[{correlation_id}] Failed to cleanup temp table (non-critical): {e}")
        
        try:
            # Run cleanup in thread pool
            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                await loop.run_in_executor(executor, _sync_cleanup)
        except Exception as e:
            logger.warning(f"[{correlation_id}] Failed to cleanup temp table (non-critical): {e}")

    async def _save_results_to_file(self, query: str, formatted_response: Dict[str, Any], 
                                   raw_data: Dict[str, Any], correlation_id: str) -> None:
        """
        Save query results to files for analysis and debugging.
        
        Args:
            query: Original user query
            formatted_response: Formatted response from Results Formatter Agent
            raw_data: Raw data from all steps
            correlation_id: Correlation ID for this execution
        """
        try:
            import json
            from datetime import datetime
            
            # Create timestamp for unique filenames
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_correlation = correlation_id.replace('-', '_')[:20]  # Truncate for filename
            
            # Create results directory if it doesn't exist
            results_dir = os.path.join(os.path.dirname(__file__), "results")
            os.makedirs(results_dir, exist_ok=True)
            
            # Save formatted results (what user sees)
            formatted_file = os.path.join(results_dir, f"query_results_{timestamp}_{safe_correlation}.json")
            
            # Calculate record count based on display type
            record_count = 0
            if formatted_response.get('display_type') == 'table':
                content = formatted_response.get('content', [])
                if isinstance(content, list):
                    record_count = len(content)
                elif isinstance(content, dict):
                    rows = content.get('rows', [])
                    record_count = len(rows)
            
            formatted_data = {
                "query": query,
                "timestamp": datetime.now().isoformat(),
                "correlation_id": correlation_id,
                "formatted_response": formatted_response,
                "summary": {
                    "display_type": formatted_response.get('display_type', 'unknown'),
                    "record_count": record_count,
                    "metadata": formatted_response.get('metadata', {})
                }
            }
            
            with open(formatted_file, 'w', encoding='utf-8') as f:
                json.dump(formatted_data, f, indent=2, ensure_ascii=False)
            
            # Save raw data (for debugging)
            raw_file = os.path.join(results_dir, f"raw_data_{timestamp}_{safe_correlation}.json")
            raw_export = {
                "query": query,
                "timestamp": datetime.now().isoformat(),
                "correlation_id": correlation_id,
                "raw_step_data": {}
            }
            
            # Export all step data with record counts
            for variable_name, data in self.data_variables.items():
                raw_export["raw_step_data"][variable_name] = {
                    "record_count": len(data) if isinstance(data, list) else 1,
                    "data_type": str(type(data).__name__),
                    "sample": data[:3] if isinstance(data, list) and len(data) > 0 else data,
                    "full_data": data  # Include full data for analysis
                }
            
            with open(raw_file, 'w', encoding='utf-8') as f:
                json.dump(raw_export, f, indent=2, ensure_ascii=False, default=str)
            
            # Create a readable summary file
            summary_file = os.path.join(results_dir, f"summary_{timestamp}_{safe_correlation}.md")
            summary_content = f"""# Query Results Summary

## Query Information
- **Query**: {query}
- **Execution Time**: {datetime.now().isoformat()}
- **Correlation ID**: {correlation_id}

## Results Overview
- **Display Type**: {formatted_response.get('display_type', 'unknown')}
- **Processing Method**: Results Formatter Agent (LLM Intelligence)
- **Code Generation**: No - Direct data formatting by LLM

## Data Processing
"""
            
            # Add step summary
            if formatted_response.get('display_type') == 'table':
                table_data = formatted_response.get('content', [])
                
                # Handle different content formats
                if isinstance(table_data, str):
                    # Code generation mode - content is a description string
                    summary_content += f"- **Content**: {table_data}\n\n"
                    summary_content += "## Generated Processing Code\n"
                    if formatted_response.get('processing_code'):
                        summary_content += "```python\n"
                        summary_content += formatted_response['processing_code']
                        summary_content += "\n```\n\n"
                elif isinstance(table_data, list) and table_data:
                    # Extract headers from first record
                    headers = list(table_data[0].keys()) if table_data else []
                    rows = table_data
                    summary_content += f"- **Table Format**: {len(headers)} columns, {len(rows)} rows\n"
                    summary_content += f"- **Columns**: {', '.join(headers)}\n\n"
                    
                    # Add sample of table data
                    summary_content += "## Sample Results\n"
                    if rows:
                        summary_content += "| " + " | ".join(headers) + " |\n"
                        summary_content += "|" + "|".join(["---" for _ in headers]) + "|\n"
                        for row in rows[:3]:  # Show first 3 rows
                            values = [str(row.get(header, 'N/A')) for header in headers]
                            summary_content += "| " + " | ".join(values) + " |\n"
                elif isinstance(table_data, dict):
                    # Legacy format with headers/rows structure
                    headers = table_data.get('headers', [])
                    rows = table_data.get('rows', [])
                    summary_content += f"- **Table Format**: {len(headers)} columns, {len(rows)} rows\n"
                    summary_content += f"- **Columns**: {', '.join(headers)}\n\n"
                    
                    # Add sample of table data
                    summary_content += "## Sample Results\n"
                    if rows:
                        summary_content += "| " + " | ".join(headers) + " |\n"
                        summary_content += "|" + "|".join(["---" for _ in headers]) + "|\n"
                        for row in rows[:3]:  # Show first 3 rows
                            values = [str(row.get(header, 'N/A')) for header in headers]
                            summary_content += "| " + " | ".join(values) + " |\n"
            
            # Add step information
            summary_content += f"\n## Processing Steps\n"
            for variable_name, data in self.data_variables.items():
                record_count = len(data) if isinstance(data, list) else 1
                summary_content += f"- **{variable_name}**: {record_count} records\n"
            
            # Add metadata
            if formatted_response.get('metadata'):
                summary_content += f"\n## Execution Metadata\n"
                metadata = formatted_response['metadata']
                for key, value in metadata.items():
                    summary_content += f"- **{key}**: {value}\n"
            
            with open(summary_file, 'w', encoding='utf-8') as f:
                f.write(summary_content)
            
            logger.info(f"[{correlation_id}] Results saved to files:")
            logger.info(f"[{correlation_id}]   - Formatted: {formatted_file}")
            logger.info(f"[{correlation_id}]   - Raw Data: {raw_file}")
            logger.info(f"[{correlation_id}]   - Summary: {summary_file}")
            
        except Exception as e:
            logger.error(f"[{correlation_id}] Failed to save results to file: {e}")

    async def _emergency_cleanup(self, correlation_id: str):
        """Aggressive cleanup on cancellation - minimal implementation"""
        try:
            # 1. Log the cancellation
            logger.warning(f"[{correlation_id}] EMERGENCY CLEANUP: Deleting temp tables and stopping all operations")
            
            # 2. Drop any temp tables aggressively
            await self._force_drop_temp_tables(correlation_id)
            
            # 3. Clear any stored data for this query
            self.data_variables.clear()
            self.step_metadata.clear()
            
            # 4. Remove from cancelled set
            self.cancelled_queries.discard(correlation_id)
            
        except Exception as e:
            logger.error(f"[{correlation_id}] Emergency cleanup failed (non-critical): {e}")

    async def _force_drop_temp_tables(self, correlation_id: str):
        """Force drop temp tables - aggressive cleanup"""
        def _sync_force_cleanup():
            try:
                import sqlite3
                
                # Database path (correct for new structure)
                db_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'sqlite_db', 'okta_sync.db')
                db_path = os.path.abspath(db_path)
                
                conn = sqlite3.connect(db_path)
                
                # Drop common temp table names aggressively
                temp_tables = ['temp_api_users', 'temp_user_data', 'temp_processing']
                for table in temp_tables:
                    try:
                        conn.execute(f"DROP TABLE IF EXISTS {table}")
                    except:
                        pass  # Ignore errors - aggressive cleanup
                
                conn.commit()
                conn.close()
                logger.info(f"[{correlation_id}] Temp tables forcefully dropped")
                
            except Exception as e:
                logger.warning(f"[{correlation_id}] Force temp table cleanup failed (non-critical): {e}")
        
        # Run in thread pool
        import concurrent.futures
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            await loop.run_in_executor(executor, _sync_force_cleanup)


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
