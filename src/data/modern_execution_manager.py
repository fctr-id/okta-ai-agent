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
import json
from pydantic import BaseModel

# Add src path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

# Import existing agents from local directory
from sql_agent import sql_agent, SQLDependencies, generate_sql_query_with_logging, is_safe_sql
from api_code_gen_agent import api_code_gen_agent, ApiCodeGenDependencies, generate_api_code  
from planning_agent import ExecutionPlan, ExecutionStep, planning_agent
from results_formatter_agent import process_results_structured
from api_sql_agent import api_sql_agent  # NEW: Internal API-SQL agent

# Import logging
from utils.logging import get_logger, get_default_log_dir

# Configure logging
logger = get_logger(__name__, log_dir=get_default_log_dir())

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


class MockSQLResult:
    """Mock SQL result object for consistent step result structure"""
    def __init__(self, sql_text: str, explanation: str, data: List[Dict[str, Any]]):
        self.sql = sql_text
        self.explanation = explanation
        self.data = data


class ExecutionResults(BaseModel):
    """Results from executing all steps"""
    steps: List[StepResult]
    final_result: Any = None
    correlation_id: str
    total_steps: int
    successful_steps: int
    failed_steps: int


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
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        self.simple_ref_path = os.path.join(project_root, "src", "data", "lightweight_api_reference.json")
        self.full_api_path = os.path.join(project_root, "src", "data", "Okta_API_entitity_endpoint_reference.json")
        
        # Load simple reference for planning
        self.simple_ref_data = self._load_simple_reference()
        
        # Load full API data for endpoint filtering during execution
        self.full_api_data = self._load_api_data()
        
        # Extract planning dependencies from simple reference
        self.available_entities = [entity['entity'] for entity in self.simple_ref_data.get('entities', [])]
        self.entity_summary = {entity['entity']: {'operations': entity['operations'], 'methods': []} 
                              for entity in self.simple_ref_data.get('entities', [])}
        self.sql_tables = {table['name']: {'columns': table['columns']} 
                          for table in self.simple_ref_data.get('sql_tables', [])}
        self.endpoints = self.full_api_data.get('endpoints', [])  # Load endpoints for filtering
        
        # REPEATABLE DATA FLOW PATTERN: Variable-based data management
        # Based on proven old executor approach - scales with any number of tools/steps
        self.data_variables = {}      # Full datasets: {"sql_data_step_1": [all_records], "api_data_step_2": response}
        self.step_metadata = {}       # Step tracking: {"step_1": {"type": "sql", "success": True, "record_count": 1000, "step_context": "query"}}
        
        logger.info(f"Modern Execution Manager initialized: {len(self.available_entities)} API entities, {len(self.sql_tables)} SQL tables, {len(self.endpoints)} endpoints")
    
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
    
    def _clear_execution_data(self):
        """Clear all execution data for fresh run - maintains repeatability."""
        self.data_variables.clear()
        self.step_metadata.clear()
        logger.debug("Cleared execution data for fresh run")
    
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
            
            # Convert entity summary to lightweight format
            entities = []
            for entity_name, entity_data in entity_summary.items():
                entities.append({
                    "entity": entity_name,
                    "operations": entity_data.get('operations', [])
                })
            
            # Sort entities alphabetically for consistency
            entities.sort(key=lambda x: x['entity'])
            
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
            
            logger.info(f"Generated lightweight API reference with {len(entities)} entities and {len(sql_tables)} SQL tables")
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
        """Get filtered endpoints for a specific API step"""
        # Use the entity field from the new format
        entity_name = step.entity
        if not entity_name:
            logger.warning(f"No entity specified in step: {step}")
            return []
        
        entity = entity_name.lower()
        operation = getattr(step, 'operation', None) or 'list'  # Default to list
        operations = [operation.lower()]
        methods = ['GET']  # Default to GET for most operations
        
        # Get matches with precise filtering
        matches = self._get_entity_operation_matches(entity, operations, methods)
        
        # Log detailed info if no matches found for debugging
        if not matches:
            available_for_entity = [ep for ep in self.endpoints if ep.get('entity', '').lower() == entity]
            logger.error(f"No endpoint matches found for entity='{entity}', operation='{operation}', methods={methods}")
            logger.error(f"Available endpoints for entity '{entity}': {[ep.get('operation') for ep in available_for_entity]}")
            if available_for_entity:
                logger.error(f"First available endpoint for '{entity}': {available_for_entity[0]}")
        
        return matches
    
    def _get_entity_operation_matches(self, entity: str, operations: List[str], methods: List[str]) -> List[Dict]:
        """Get endpoints matching entity + operation + method (copied from old executor)"""
        matches = []
        
        for endpoint in self.endpoints:
            if self._is_precise_match(endpoint, entity, operations, methods):
                matches.append(endpoint)
        
        return matches
    
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
    
    async def execute_query(self, query: str) -> Dict[str, Any]:
        """
        Main execution method for complex multi-step query processing.
        
        Flow:
        1. Generate/use existing correlation ID
        2. Use Planning Agent to generate execution plan
        3. Execute steps using Modern Execution Manager
        4. Return structured results
        
        Args:
            query: Natural language query to execute
            
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
            
            # Phase 1: Use Planning Agent to generate execution plan
            logger.info(f"[{correlation_id}] Phase 1: Planning Agent execution")
            
            # Create dependencies for Planning Agent (same as old executor)
            from planning_agent import PlanningDependencies
            planning_deps = PlanningDependencies(
                available_entities=self.available_entities,
                entity_summary=self.entity_summary,
                sql_tables=self.sql_tables,
                flow_id=correlation_id
            )
            
            # Execute Planning Agent with dependencies - trust the agent to handle validation
            planning_result = await planning_agent.run(query, deps=planning_deps)
            
            # Trust the agent - just extract the plan
            execution_plan = planning_result.output.plan
            
            # Pretty print the execution plan for debugging
            import json
            logger.info(f"[{correlation_id}] Generated execution plan:\n{json.dumps(execution_plan.model_dump(), indent=2)}")
            logger.info(f"[{correlation_id}] Planning completed: {len(execution_plan.steps)} steps generated")
            
            # Phase 2: Execute steps using Modern Execution Manager
            logger.info(f"[{correlation_id}] Phase 2: Step execution with Modern Execution Manager")
            execution_results = await self.execute_steps(execution_plan, correlation_id)
            
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
            
            # Build step results for processing with ACTUAL DATA
            for i, step_result in enumerate(execution_results.steps, 1):
                step_name = f"step_{i}_{step_result.step_type.lower()}"
                
                if step_result.success and step_result.result:
                    if step_result.step_type == "SQL":
                        # For SQL steps, get the actual executed data from our storage
                        variable_name = f"sql_data_step_{i}"
                        sql_data = self.data_variables.get(variable_name, [])
                        
                        sql_result_dict = {
                            'success': True,
                            'sql': getattr(step_result.result, 'sql', ''),
                            'explanation': getattr(step_result.result, 'explanation', ''),
                            'data': sql_data  # ACTUAL SQL RESULTS
                        }
                        step_results_for_processing[step_name] = sql_data  # PASS ACTUAL DATA
                        raw_results['sql_execution'] = sql_result_dict
                        logger.debug(f"[{correlation_id}] Added SQL data: {len(sql_data)} records")
                        
                    elif step_result.step_type == "API":
                        # For API steps, get the actual executed data from our storage
                        variable_name = f"api_data_step_{i}"
                        api_data = self.data_variables.get(variable_name, [])
                        
                        step_results_for_processing[step_name] = api_data  # PASS ACTUAL DATA
                        raw_results['execution_result'] = {'execution_output': api_data}
                        logger.debug(f"[{correlation_id}] Added API data: {len(api_data)} records")
            
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
                
            except Exception as e:
                logger.error(f"[{correlation_id}] Results formatting failed: {e}")
                formatted_response = {
                    'display_type': 'markdown',
                    'content': {'text': f'Results formatting failed: {e}'},
                    'metadata': {'error': 'Results formatting failed'}
                }
            
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
        self.available_entities = [entity['entity'] for entity in new_reference.get('entities', [])]
        self.entity_summary = {entity['entity']: {'operations': entity['operations'], 'methods': []} 
                              for entity in new_reference.get('entities', [])}
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
            logger.info(f"[{correlation_id}] Executing step {step_num}/{len(plan.steps)}: {step.tool_name}")
            
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
                    
                    # Data storage is handled automatically in step execution methods
                    # Log current data state
                    total_variables = len(self.data_variables)
                    total_metadata = len(self.step_metadata)
                    logger.debug(f"[{correlation_id}] Data state: {total_variables} variables, {total_metadata} step metadata entries")
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
                previous_sample = None
        
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
        logger.debug(f"[{correlation_id}] Executing user SQL step")
        
        # Get enhanced context from all previous steps
        all_step_contexts = self._get_all_previous_step_contexts_and_samples(step_number, max_samples=3)
        logger.debug(f"[{correlation_id}] Enhanced context: {len(all_step_contexts)} previous step contexts provided")
        
        # Call existing SQL Agent with enhanced logging using wrapper function
        logger.debug(f"[{correlation_id}] Calling User SQL Agent with context: {step.query_context}")
        
        sql_result_dict = await generate_sql_query_with_logging(
            question=step.query_context,
            tenant_id=self.tenant_id,  # Use actual tenant_id from settings
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
        result_data = MockSQLResult(sql_dict['sql'], sql_dict['explanation'], db_data)
        
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
        
        # ENHANCED PATTERN: Get context and samples from ALL previous steps
        all_step_contexts = self._get_all_previous_step_contexts_and_samples(step_number, max_samples=3)
        
        data_count = len(full_data) if isinstance(full_data, list) else 0
        logger.info(f"[{correlation_id}] Processing API data with Internal API-SQL Agent: {data_count} full records")
        logger.debug(f"[{correlation_id}] Enhanced context: {len(all_step_contexts)} previous step contexts provided")
        
        # ALWAYS use temp table mode to avoid placeholder issues
        # This is safer and more robust than placeholder replacement
        use_temp_table = True
        logger.debug(f"[{correlation_id}] Using temp table mode for all API-SQL operations")
        
        # Call Internal API-SQL Agent - IT handles all the complexity
        # Use full data for processing, not just samples
        result = await api_sql_agent.process_api_data(
            api_data=full_data,  # REPEATABLE PATTERN: Use full data for processing
            processing_context=step.query_context,
            correlation_id=correlation_id,
            use_temp_table=use_temp_table,
            all_step_contexts=all_step_contexts  # NEW: Enhanced context from all previous steps
        )
        
        # The Internal API-SQL Agent generates the complete SQL query
        # For temp table mode, we need to create table and insert data first
        if result.output.uses_temp_table and result.output.temp_table_schema:
            logger.info(f"[{correlation_id}] Creating temporary table and inserting {data_count} API records")
            
            try:
                # Execute temp table operations in a single connection session
                db_data = await self._execute_temp_table_workflow(
                    temp_table_schema=result.output.temp_table_schema,
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
                "sql_query": result.output.processing_query,
                "explanation": result.output.explanation,
                "input_record_count": data_count,
                "use_temp_table": use_temp_table
            },
            step_context=step.query_context  # NEW: Store step context
        )
        
        logger.info(f"[{correlation_id}] API-SQL step completed: {len(db_data)} records stored as {variable_name}")
        
        # Create result object that matches expected structure
        result_data = MockSQLResult(result.output.processing_query, result.output.explanation, db_data)
        
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
            logger.debug(f"[{correlation_id}] First endpoint structure: {available_endpoints[0] if available_endpoints else 'None'}")
            
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
            logger.info(f"[{correlation_id}] === GENERATED API CODE ===")
            logger.info(f"[{correlation_id}]\n{api_result_dict.get('code', 'No code')}")
            logger.info(f"[{correlation_id}] === END GENERATED CODE ===")
            
            execution_result = self._execute_generated_code(api_result_dict.get('code', ''), correlation_id, step)
            
            if execution_result.get('success', False):
                # Use the actual execution output
                actual_data = execution_result.get('output', [])
                logger.info(f"[{correlation_id}] API code execution successful, got {len(actual_data) if isinstance(actual_data, list) else 'N/A'} results")
                
                # Log only one sample element to avoid log spam
                if isinstance(actual_data, list) and actual_data:
                    logger.debug(f"[{correlation_id}] Sample API result (1 of {len(actual_data)}): {actual_data[0]}")
                elif actual_data:
                    logger.debug(f"[{correlation_id}] API result sample: {actual_data}")
                else:
                    logger.debug(f"[{correlation_id}] API execution returned no data")
                
                result_data = {
                    'code': api_result_dict['code'],
                    'explanation': api_result_dict['explanation'],
                    'requirements': api_result_dict.get('requirements', []),
                    'execution_output': actual_data,
                    'executed': True
                }
                
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
                logger.info(f"[{correlation_id}] === EXECUTION ERROR DETAILS ===")
                logger.info(f"[{correlation_id}] STDOUT: {execution_result.get('stdout', 'None')}")
                logger.info(f"[{correlation_id}] STDERR: {execution_result.get('stderr', 'None')}")
                logger.info(f"[{correlation_id}] === END ERROR DETAILS ===")
                # Fall back to code generation result without execution
                result_data = {
                    'code': api_result_dict['code'],
                    'explanation': api_result_dict['explanation'],
                    'requirements': api_result_dict.get('requirements', []),
                    'execution_output': [],
                    'executed': False,
                    'execution_error': execution_result.get('error', 'Unknown error')
                }
                
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
    
    def _execute_generated_code(self, python_code: str, correlation_id: str, step: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute generated Python code in a subprocess and capture output.
        
        Args:
            python_code: The Python code to execute
            correlation_id: Correlation ID for logging
            
        Returns:
            Dict with success status and output or error
        """
        import subprocess
        import tempfile
        import json
        import shutil
        
        try:
            # Create a temporary directory for execution
            with tempfile.TemporaryDirectory() as temp_dir:
                # Copy the base API client to the temp directory
                api_client_source = os.path.join(os.path.dirname(__file__), 'base_okta_api_client.py')
                api_client_dest = os.path.join(temp_dir, 'base_okta_api_client.py')
                
                if os.path.exists(api_client_source):
                    shutil.copy2(api_client_source, api_client_dest)
                    logger.debug(f"[{correlation_id}] Copied base_okta_api_client.py to execution directory")
                else:
                    logger.warning(f"[{correlation_id}] base_okta_api_client.py not found at {api_client_source}")
                
                # Create the main execution file
                temp_file_path = os.path.join(temp_dir, 'generated_code.py')
                
                # Indent the entire generated code block to fit inside try/except
                indented_code = '\n'.join('    ' + line for line in python_code.split('\n'))
                
                # Wrap the code to capture output as JSON
                wrapped_code = f"""
import sys
import json
try:
{indented_code}
except Exception as e:
    print(json.dumps({{"status": "error", "error": str(e)}}))
"""
                
                with open(temp_file_path, 'w') as temp_file:
                    temp_file.write(wrapped_code)
            
                # Execute the code with appropriate timeout based on entity type
                logger.debug(f"[{correlation_id}] Executing generated code in subprocess...")
                
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
            from sql_security_validator import validate_internal_sql
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
                
                # Database path (same as old executor)
                db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'sqlite_db', 'okta_sync.db')
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

    async def _execute_temp_table_workflow(self, temp_table_schema: str, processing_query: str, 
                                          api_data: List[Any], correlation_id: str) -> List[Dict[str, Any]]:
        """
        Execute the complete temp table workflow in a single database connection session.
        This ensures the TEMPORARY table remains available throughout the entire operation.
        
        Args:
            temp_table_schema: SQL schema to create the temporary table
            processing_query: Main SQL query that uses the temporary table
            api_data: Data to insert into the temporary table
            correlation_id: Correlation ID for logging
            
        Returns:
            List of query results
        """
        # Execute in thread pool to avoid blocking event loop
        import asyncio
        import concurrent.futures
        
        def _sync_temp_table_workflow():
            try:
                import sqlite3
                
                # Database path (same as old executor)
                db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'sqlite_db', 'okta_sync.db')
                db_path = os.path.abspath(db_path)
                
                # Single connection for entire workflow
                conn = sqlite3.connect(db_path)
                
                try:
                    # Enable WAL mode for concurrent access  
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute("PRAGMA synchronous=NORMAL")
                    
                    cursor = conn.cursor()
                    
                    # Step 1: Create temporary table
                    logger.debug(f"[{correlation_id}] Creating temporary table with schema: {temp_table_schema}")
                    cursor.execute(temp_table_schema)
                    
                    # Step 2: Insert API data
                    if api_data:
                        # Get the first record to determine the structure
                        first_record = api_data[0]
                        
                        # Handle different API data formats intelligently  
                        if isinstance(first_record, str):
                            # Simple string list (user IDs from step 1) - direct okta_id insertion
                            columns = ['okta_id']
                            insert_sql = f"INSERT OR IGNORE INTO temp_api_users (okta_id) VALUES (?)"
                            logger.debug(f"[{correlation_id}] Converting string list to okta_id format for temp table")
                        elif isinstance(first_record, dict):
                            # Dictionary format - need to extract okta_id equivalent 
                            if 'user_id' in first_record:
                                # Role assignment format: {"user_id": "...", "roles": [...]}
                                columns = ['okta_id']  # temp table expects okta_id
                                insert_sql = f"INSERT OR IGNORE INTO temp_api_users (okta_id) VALUES (?)"
                                logger.debug(f"[{correlation_id}] Converting role assignment dict to okta_id format for temp table")
                            else:
                                # Generic dictionary format
                                columns = list(first_record.keys())
                                placeholders = ', '.join(['?' for _ in columns])
                                column_names = ', '.join(columns)
                                insert_sql = f"INSERT OR IGNORE INTO temp_api_users ({column_names}) VALUES ({placeholders})"
                                logger.debug(f"[{correlation_id}] Using dictionary format for temp table")
                        else:
                            logger.warning(f"[{correlation_id}] Unknown API data format: {type(first_record)}")
                            return []
                        
                        logger.debug(f"[{correlation_id}] Inserting {len(api_data)} records into temp table")
                        logger.debug(f"[{correlation_id}] Insert SQL: {insert_sql}")
                        
                        # Insert all records with intelligent value extraction
                        for record in api_data:
                            if isinstance(record, str):
                                # Handle string records (user IDs) - direct okta_id value
                                values = [record]
                            elif isinstance(record, dict):
                                if 'user_id' in record:
                                    # Role assignment format - extract user_id as okta_id
                                    values = [record['user_id']]  
                                else:
                                    # Generic dictionary format - use all values
                                    values = [record.get(col) for col in columns]
                            else:
                                logger.warning(f"[{correlation_id}] Skipping unknown record type: {type(record)}")
                                continue
                                
                            cursor.execute(insert_sql, values)
                        
                        conn.commit()
                        logger.info(f"[{correlation_id}] Successfully inserted {len(api_data)} records into temp table")
                    
                    # Step 3: Execute main processing query
                    logger.debug(f"[{correlation_id}] Executing processing query: {processing_query}")
                    cursor.execute(processing_query, [self.tenant_id])  # Add tenant_id parameter
                    
                    # Fetch all results
                    columns = [description[0] for description in cursor.description]
                    rows = cursor.fetchall()
                    
                    # Convert to list of dictionaries
                    results = []
                    for row in rows:
                        results.append(dict(zip(columns, row)))
                    
                    logger.debug(f"[{correlation_id}] Processing query returned {len(results)} results")
                    
                    # Step 4: Temp table cleanup happens automatically when connection closes
                    cursor.close()
                    
                    return results
                    
                finally:
                    # Ensure connection is closed (temp table auto-drops)
                    conn.close()
                    logger.debug(f"[{correlation_id}] Temporary table automatically cleaned up")
                    
            except Exception as e:
                logger.error(f"[{correlation_id}] Temp table workflow failed: {e}")
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
                
                # Database path (same as old executor)
                db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'sqlite_db', 'okta_sync.db')
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
                    # Standard dictionary format
                    columns = list(first_record.keys())
                
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
                        # Handle dictionary records - standard format
                        values = [record.get(col) for col in columns]
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
                
                # Database path (same as old executor)
                db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'sqlite_db', 'okta_sync.db')
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
