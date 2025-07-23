"""
Modern Execution Manager for Okta AI Agent.

Simple pass-through orchestrator that:
- Walks through planning agent steps in order
- Executes SQL and     async def _execute_sql_step(self, step: ExecutionStep, previous_sample: dict, correlation_id: str, step_number: int) -> StepResult:PI steps using existing agents
- Passes sample data between steps for context
- Returns all step results without complex processing

This replaces the complex real_world_hybrid_executor.py with a simple step walker.
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
from sql_agent import sql_agent, SQLDependencies, generate_sql_query_with_logging
from api_code_gen_agent import api_code_gen_agent, ApiCodeGenDependencies, generate_api_code  
from planning_agent import ExecutionPlan, ExecutionStep, planning_agent
from results_formatter_agent import process_results_structured

# Import logging
from utils.logging import get_logger

# Configure logging
logger = get_logger(__name__)


class StepResult(BaseModel):
    """Result from executing a single step"""
    step_number: int
    step_type: str
    success: bool
    result: Any = None
    error: Optional[str] = None
    sample_extracted: Any = None


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
    Simple execution manager that walks through plan steps and executes them.
    
    Core philosophy: Trust the agents to do their jobs. Just orchestrate the steps.
    """
    
    def __init__(self):
        """Initialize the modern execution manager"""
        self.error_handler = BasicErrorHandler()
        
        # Load API data and DB schema (same as old executor)
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        self.api_data_path = os.path.join(project_root, "src", "data", "Okta_API_entitity_endpoint_reference.json")
        self.db_schema_path = os.path.join(project_root, "src", "data", "okta_schema.json")
        
        # Load data files
        self.api_data = self._load_api_data()
        self.db_schema = self._load_db_schema()
        
        # Extract planning dependencies
        self.available_entities = list(self.api_data.get('entity_summary', {}).keys())
        self.entity_summary = self.api_data.get('entity_summary', {})
        self.sql_tables = self.db_schema.get('sql_tables', {})
        self.endpoints = self.api_data.get('endpoints', [])  # Load endpoints for filtering
        
        logger.info(f"Modern Execution Manager initialized: {len(self.available_entities)} API entities, {len(self.sql_tables)} SQL tables, {len(self.endpoints)} endpoints")
    
    def _load_api_data(self) -> Dict[str, Any]:
        """Load API entity data from JSON file"""
        try:
            with open(self.api_data_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning(f"API data file not found: {self.api_data_path}")
            return {'entity_summary': {}}
        except Exception as e:
            logger.error(f"Failed to load API data: {e}")
            return {'entity_summary': {}}
    
    def _load_db_schema(self) -> Dict[str, Any]:
        """Load database schema from JSON file"""
        try:
            with open(self.db_schema_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning(f"DB schema file not found: {self.db_schema_path}")
            return {'sql_tables': {}}
        except Exception as e:
            logger.error(f"Failed to load DB schema: {e}")
            return {'sql_tables': {}}
    
    def _get_entity_endpoints_for_step(self, step: ExecutionStep) -> List[Dict[str, Any]]:
        """Get filtered endpoints for a specific API step (copied from old executor)"""
        # Handle both old 'entity' field and new 'tool_name' field for compatibility
        entity_name = getattr(step, 'entity', None) or getattr(step, 'tool_name', None)
        if not entity_name:
            return []
        
        entity = entity_name.lower()
        operation = getattr(step, 'operation', None) or 'list'  # Default to list
        operations = [operation.lower()]
        methods = ['GET']  # Default to GET for most operations
        
        # Use the exact same filtering logic as old executor
        return self._get_entity_operation_matches(entity, operations, methods)
    
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
        """Check if endpoint operation matches any requested operation (copied from old executor)"""
        for requested_op in requested_ops:
            if self._semantic_operation_match(endpoint_op, requested_op.lower()):
                return True
        return False
    
    def _semantic_operation_match(self, endpoint_op: str, requested_op: str) -> bool:
        """Semantic matching for operations with common aliases (copied from old executor)"""
        # Direct match
        if endpoint_op == requested_op:
            return True
        
        # Common aliases
        aliases = {
            'list': ['list', 'get', 'retrieve', 'fetch'],
            'list_members': ['list_members', 'members', 'list'],
            'list_user_assignments': ['list_user_assignments', 'assignments', 'list'],
            'list_factors': ['list_factors', 'factors', 'list_enrollments', 'list'],
            'get': ['get', 'retrieve', 'fetch'],
            'create': ['create', 'add', 'post'],
        }
        
        for alias_group in aliases.values():
            if endpoint_op in alias_group and requested_op in alias_group:
                return True
        
        return False
    
    async def execute_query(self, query: str) -> Dict[str, Any]:
        """
        Main execution method that provides the same interface as RealWorldHybridExecutor.
        
        Flow:
        1. Generate/use existing correlation ID
        2. Use Planning Agent to generate execution plan
        3. Execute steps using Modern Execution Manager
        4. Return results in compatible format
        
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
            logger.info(f"[{correlation_id}] Planning completed: {len(execution_plan.steps)} steps generated")
            
            # Phase 2: Execute steps using Modern Execution Manager
            logger.info(f"[{correlation_id}] Phase 2: Step execution with Modern Execution Manager")
            execution_results = await self.execute_steps(execution_plan, correlation_id)
            
            # Process results through Results Formatter Agent (like old executor)
            logger.info(f"[{correlation_id}] Processing results through Results Formatter Agent...")
            
            # Build step_results_for_processing in the format expected by results formatter
            step_results_for_processing = {}
            raw_results = {}
            
            for i, step_result in enumerate(execution_results.steps, 1):
                step_name = f"step_{i}_{step_result.step_type.lower()}"
                
                if step_result.success and step_result.result:
                    if step_result.step_type == "SQL":
                        # Extract SQL data for results formatter
                        sql_data = step_result.result.get('data', [])
                        step_results_for_processing[step_name] = sql_data
                        raw_results['sql_execution'] = step_result.result
                        logger.debug(f"[{correlation_id}] Added SQL data: {len(sql_data)} records")
                        
                    elif step_result.step_type == "API":
                        # Extract API execution results
                        api_data = step_result.result.get('stdout', '')
                        if api_data:
                            step_results_for_processing[step_name] = [{'raw_output': api_data}]
                        raw_results['execution_result'] = step_result.result
                        logger.debug(f"[{correlation_id}] Added API data: {len(api_data)} chars")
            
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
            
            # Build compatible result structure (matching old executor format)
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
    
    async def execute_steps(self, plan: ExecutionPlan, correlation_id: str) -> ExecutionResults:
        """
        Execute all steps in the plan in order.
        
        Args:
            plan: ExecutionPlan from planning agent
            correlation_id: Correlation ID for tracking
            
        Returns:
            ExecutionResults with all step outputs
        """
        logger.info(f"[{correlation_id}] Starting execution of {len(plan.steps)} steps")
        
        step_results = []
        previous_sample = None
        successful_steps = 0
        failed_steps = 0
        
        # Walk through each step in order
        for i, step in enumerate(plan.steps):
            step_num = i + 1
            logger.info(f"[{correlation_id}] Executing step {step_num}/{len(plan.steps)}: {step.tool_name}")
            
            try:
                # Execute step based on type
                if step.tool_name == "sql":
                    result = await self._execute_sql_step(step, previous_sample, correlation_id, step_num)
                elif step.tool_name == "api":
                    result = await self._execute_api_step(step, previous_sample, correlation_id, step_num)
                else:
                    # Unknown step type
                    logger.warning(f"[{correlation_id}] Unknown step type: {step.tool_name}")
                    result = StepResult(
                        step_number=step_num,
                        step_type=step.tool_name,
                        success=False,
                        error=f"Unknown step type: {step.tool_name}"
                    )
                
                # Track success/failure
                if result.success:
                    successful_steps += 1
                    # Extract sample for next step
                    sample = self._extract_sample(result.result)
                    result.sample_extracted = sample
                    previous_sample = sample
                    logger.info(f"[{correlation_id}] Step {step_num} completed successfully")
                    logger.info(f"[{correlation_id}] === SAMPLE DATA FOR NEXT STEP ===")
                    logger.info(f"[{correlation_id}] {sample}")
                    logger.info(f"[{correlation_id}] === END SAMPLE DATA ===")
                else:
                    failed_steps += 1
                    previous_sample = None  # No sample for failed steps
                    logger.error(f"[{correlation_id}] Step {step_num} failed: {result.error}")
                
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
    
    async def _execute_sql_step(self, step: ExecutionStep, previous_sample: Any, correlation_id: str, step_number: int) -> StepResult:
        """
        Execute SQL step using SQL Agent.
        
        Args:
            step: SQL step to execute
            previous_sample: Sample data from previous step
            correlation_id: Correlation ID for tracking
            
        Returns:
            StepResult with SQL execution output
        """
        try:
            # Call SQL Agent with enhanced logging using wrapper function
            logger.debug(f"[{correlation_id}] Calling SQL Agent with context: {step.query_context}")
            sql_result_dict = await generate_sql_query_with_logging(
                question=step.query_context,
                tenant_id="test_tenant",
                include_deleted=False,
                flow_id=correlation_id
            )
            
            # Check if the wrapper function was successful
            if not sql_result_dict.get('success', False):
                error_msg = sql_result_dict.get('error', 'Unknown SQL generation error')
                return StepResult(
                    step_number=step_number,
                    step_type="sql",
                    success=False,
                    error=error_msg
                )
            
            # Create a mock result object that matches the expected structure
            class MockSQLResult:
                def __init__(self, sql_text, explanation):
                    self.sql = sql_text
                    self.explanation = explanation
            
            result_data = MockSQLResult(sql_result_dict['sql'], sql_result_dict['explanation'])
            
            return StepResult(
                step_number=step_number,
                step_type="sql",
                success=True,
                result=result_data
            )
            
        except Exception as e:
            return self.error_handler.handle_step_error(step, e, correlation_id, step_number)
    
    async def _execute_api_step(self, step: ExecutionStep, previous_sample: Any, correlation_id: str, step_number: int) -> StepResult:
        """
        Execute API step using API Code Gen Agent.
        
        Args:
            step: API step to execute
            previous_sample: Sample data from previous step
            correlation_id: Correlation ID for tracking
            step_number: Current step number
            
        Returns:
            StepResult with API execution output
        """
        try:
            # Get filtered endpoints for this specific step (using old executor logic)
            available_endpoints = self._get_entity_endpoints_for_step(step)
            
            # Call API Code Gen Agent with enhanced logging using wrapper function
            logger.debug(f"[{correlation_id}] Calling API Code Gen Agent with context: {step.query_context}")
            # Handle both old 'entity' field and new 'tool_name' field for compatibility
            entity_name = getattr(step, 'entity', None) or getattr(step, 'tool_name', None) or "users"
            api_result_dict = await generate_api_code(
                query=step.query_context,
                sql_data_sample=previous_sample if isinstance(previous_sample, list) else [{"sample": "data"}],
                sql_record_count=len(previous_sample) if isinstance(previous_sample, list) else 1,
                available_endpoints=available_endpoints,
                entities_involved=[entity_name],
                step_description=step.reasoning if hasattr(step, 'reasoning') else step.query_context,
                correlation_id=correlation_id
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
            
            execution_result = self._execute_generated_code(api_result_dict.get('code', ''), correlation_id)
            
            if execution_result.get('success', False):
                # Use the actual execution output
                actual_data = execution_result.get('output', [])
                logger.info(f"[{correlation_id}] API code execution successful, got {len(actual_data) if isinstance(actual_data, list) else 'N/A'} results")
                logger.info(f"[{correlation_id}] === API EXECUTION OUTPUT ===")
                logger.info(f"[{correlation_id}] {actual_data[:3] if isinstance(actual_data, list) and actual_data else 'No data'}")
                logger.info(f"[{correlation_id}] === END API OUTPUT ===")
                
                result_data = {
                    'code': api_result_dict['code'],
                    'explanation': api_result_dict['explanation'],
                    'requirements': api_result_dict.get('requirements', []),
                    'execution_output': actual_data,
                    'executed': True
                }
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
            
            return StepResult(
                step_number=step_number,
                step_type="api",
                success=True,
                result=result_data
            )
            
        except Exception as e:
            return self.error_handler.handle_step_error(step, e, correlation_id, step_number)
    
    def _extract_sample(self, step_result: Any) -> Any:
        """
        Extract a small sample from step result for next step context.
        
        Args:
            step_result: Result from previous step
            
        Returns:
            Sample data (first 2-3 items) for next step
        """
        if step_result is None:
            return None
        
        # Handle list results - take first 3 items
        if isinstance(step_result, list):
            sample_size = min(3, len(step_result))
            return step_result[:sample_size] if sample_size > 0 else []
        
        # Handle dict results with nested data
        if isinstance(step_result, dict):
            # Special handling for API execution results
            if 'execution_output' in step_result and isinstance(step_result['execution_output'], list):
                sample_size = min(3, len(step_result['execution_output']))
                return step_result['execution_output'][:sample_size] if sample_size > 0 else []
            
            # Check for common list keys
            for key in ['items', 'data', 'results', 'users', 'groups', 'applications']:
                if key in step_result and isinstance(step_result[key], list):
                    sample_size = min(3, len(step_result[key]))
                    return step_result[key][:sample_size] if sample_size > 0 else []
            
            # If no list found, return the dict as-is (it might be a single entity)
            return step_result
        
        # For other types, return as-is
        return step_result

    def _execute_generated_code(self, python_code: str, correlation_id: str) -> Dict[str, Any]:
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
        
        try:
            # Create a temporary Python file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as temp_file:
                # Wrap the code to capture output as JSON
                wrapped_code = f"""
import sys
import json
try:
{python_code}
    # Try to capture any printed output or variables
    # This is a best-effort attempt to get structured data
    if 'result' in locals():
        print(json.dumps({{"status": "success", "data": result}}))
    elif 'users' in locals():
        print(json.dumps({{"status": "success", "data": users}}))
    elif 'data' in locals():
        print(json.dumps({{"status": "success", "data": data}}))
    else:
        print(json.dumps({{"status": "success", "data": []}}))
except Exception as e:
    print(json.dumps({{"status": "error", "error": str(e)}}))
"""
                temp_file.write(wrapped_code)
                temp_file_path = temp_file.name
            
            # Execute the code
            logger.debug(f"[{correlation_id}] Executing generated code in subprocess...")
            result = subprocess.run(
                [sys.executable, temp_file_path],
                capture_output=True,
                text=True,
                timeout=60  # 60 second timeout
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
                    logger.warning(f"[{correlation_id}] Could not parse JSON output, using raw stdout")
                    return {
                        'success': True,
                        'output': result.stdout.strip().split('\n') if result.stdout.strip() else [],
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
            logger.error(f"[{correlation_id}] Code execution timed out")
            return {
                'success': False,
                'error': 'Code execution timed out after 60 seconds'
            }
        except Exception as e:
            logger.error(f"[{correlation_id}] Code execution failed with exception: {e}")
            return {
                'success': False,
                'error': f'Execution exception: {str(e)}'
            }
        finally:
            # Clean up temporary file
            try:
                import os
                if 'temp_file_path' in locals():
                    os.unlink(temp_file_path)
            except:
                pass


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
