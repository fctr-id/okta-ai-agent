"""
Real-world Hybrid Executor for Okta AI Agent.
Based on test_streamlined_pipeline.py logic - NO MOCKS!

This executor:
1. Uses Planning Agent to generate execution plans (real ExecutionPlanResponse)
2. Uses SQL agent for database queries (real SQL execution)
3. Uses endpoint filtering for API calls (real API endpoints)
4. Combines SQL data + API endpoints for final results
"""

import asyncio
import json
import sys
import os
import re
import sqlite3
import subprocess
import tempfile
import traceback
import time
from typing import Dict, List, Any
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel

# Add src to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from dotenv import load_dotenv
from pydantic_ai import Agent

# Import model picker for LLM configurations
from src.core.model_picker import ModelConfig, ModelType

# Import centralized logging with correlation ID support
from src.utils.logging import get_logger, set_correlation_id, get_correlation_id, get_default_log_dir

# Import real components
try:
    from sql_agent import sql_agent, SQLDependencies, is_safe_sql, extract_json_from_text
    print("SQL agent imported successfully (local copy)")
except ImportError as e:
    print(f"[ERROR] Failed to import local SQL agent: {e}")
    sql_agent = None
    is_safe_sql = None
    extract_json_from_text = None

try:
    from planning_agent import planning_agent, PlanningDependencies
    print("Planning agent imported successfully (local copy)")
except ImportError as e:
    print(f"[ERROR] Failed to import local Planning agent: {e}")
    planning_agent = None
    PlanningDependencies = None

# Constants for sampling and results processing (inspired by ExecutionManager)
MAX_CHARS_FOR_FULL_RESULTS = 60000
MAX_SAMPLES_PER_STEP = 5

class ExecutionPlanResponse(BaseModel):
    """Planning Agent response matching the existing ExecutionPlan format"""
    plan: Dict[str, Any]  # Contains steps, reasoning, partial_success_acceptable
    confidence: int

class LLM2CodeResponse(BaseModel):
    """LLM2 JSON response format according to system prompt"""
    python_code: str
    explanation: str
    requirements: List[str]

class ValidationError(Exception):
    """Custom exception for validation failures"""
    pass

class StrictValidator:
    """Strict validation to prevent LLM hallucination"""
    
    @staticmethod
    def validate_planning_agent_response(response: Dict, available_entities: List[str], entity_summary: Dict) -> Dict:
        """Validate Planning Agent response in ExecutionPlan format against available entities"""
        plan = response.get('plan', {})
        steps = plan.get('steps', [])
        
        if not steps:
            raise ValidationError("PLANNING AGENT RESPONSE INVALID - No steps provided in plan")
        
        # Extract entities from tool_names in steps
        tool_names = [step.get('tool_name', '') for step in steps]
        
        # 1. Validate tool_names - allow both API entities and SQL table names  
        api_entities = list(entity_summary.keys())
        sql_tables = ['users', 'groups', 'user_group_memberships', 'applications', 'user_application_assignments', 
                     'group_application_assignments', 'user_factors', 'devices', 'user_devices', 'policies', 'sync_history']
        
        invalid_entities = []
        sql_steps = []
        api_steps = []
        
        for step in steps:
            tool_name = step.get('tool_name', '')
            query_context = step.get('query_context', '')
            
            # Check if this is a SQL step (by tool_name or query_context)
            is_sql_step = (tool_name in sql_tables) or (query_context.upper().startswith('SQL:')) or (tool_name == 'sql_query')
            
            if is_sql_step:
                sql_steps.append(step)
            elif tool_name in api_entities:
                api_steps.append(step)
            else:
                invalid_entities.append(tool_name)
        
        if invalid_entities:
            raise ValidationError(f"PLANNING AGENT HALLUCINATION DETECTED - Invalid entities: {invalid_entities}. Must use API entities: {api_entities[:5]}... or SQL tables: {sql_tables[:5]}...")
        
        # 2. Validate each step has required fields
        for i, step in enumerate(steps):
            required_fields = ['tool_name', 'query_context', 'critical', 'reasoning']
            missing_fields = [field for field in required_fields if field not in step]
            if missing_fields:
                raise ValidationError(f"PLANNING AGENT STEP {i+1} INVALID - Missing fields: {missing_fields}")
        
        print(f"[SUCCESS] PLANNING AGENT VALIDATION PASSED - {len(api_steps)} API steps, {len(sql_steps)} SQL steps")
        
        # Check for hybrid optimization opportunities
        if len(sql_steps) == 0 and len(api_steps) > 2:
            print(f"💡 HYBRID OPTIMIZATION SUGGESTION:")
            print(f"   Current plan: {len(api_steps)} API steps")
            print(f"   Consider: SQL can provide users, groups, apps, factors in 1 query")
            print(f"   Efficiency: Use SQL for bulk data, API only for roles")
        
        return response

class PreciseEndpointFilter:
    """Precise filtering that mimics GenericEndpointFilter logic"""
    
    def __init__(self, condensed_reference: Dict):
        self.api_data = condensed_reference
        self.endpoints = condensed_reference['endpoints']
        self.entity_summary = condensed_reference['entity_summary']
    
    def filter_endpoints(self, planning_plan: ExecutionPlanResponse) -> Dict[str, Any]:
        """Filter endpoints based on Planning Agent's explicit entity+operation specifications"""
        steps = planning_plan.plan.get('steps', [])
        
        # Extract entities and operations DIRECTLY from Planning Agent's explicit specifications
        api_entities = []
        operations = []
        
        print(f"[SEARCH] EXTRACTING ENTITIES AND OPERATIONS FROM PLANNING AGENT PLAN:")
        for i, step in enumerate(steps, 1):
            tool_name = step.get('tool_name', '').lower()
            query_context = step.get('query_context', '')
            
            # Check if this is an API step by checking if tool_name exists in entity_summary
            if tool_name in self.entity_summary:
                api_entities.append(tool_name)
                # Get the default operation for this entity (usually first one)
                entity_ops = self.entity_summary[tool_name].get('operations', ['list'])
                default_op = entity_ops[0] if entity_ops else 'list'
                operations.append(default_op.lower())
                print(f"   Step {i}: API entity='{tool_name}', default_operation='{default_op}'")
            else:
                print(f"   Step {i}: SQL step '{tool_name}' (no operation filtering needed)")
        
        # Remove duplicates
        entities = list(set(api_entities))
        operations = list(set(operations))
        methods = ['GET']  # Default to GET for most operations
        
        print(f"[TARGET] PRECISE FILTERING (API STEPS ONLY)")
        print(f"   Entities: {entities}")
        print(f"   Operations: {operations}")
        print(f"   Methods: {methods}")
        
        if not entities:
            print("   [INFO] No API entities found - all steps are SQL")
            return {
                'success': True,
                'original_endpoint_count': len(self.endpoints),
                'filtered_endpoint_count': 0,
                'reduction_percentage': 100.0,
                'filtered_endpoints': [],
                'entity_results': {},
                'total_endpoints': 0,
                'planning_plan': planning_plan.model_dump()
            }
        
        # Filter endpoints for each entity
        filtered_endpoints = []
        entity_results = {}
        
        for entity in entities:
            entity_endpoints = self._get_entity_operation_matches(entity, operations, methods)
            
            if entity_endpoints:
                # Limit per entity (max 3 per entity to prevent explosion)
                max_per_entity = min(3, max(1, 8 // len(entities)))
                selected = entity_endpoints[:max_per_entity]
                
                filtered_endpoints.extend(selected)
                entity_results[entity] = {
                    'found': len(entity_endpoints),
                    'selected': len(selected),
                    'endpoints': [ep['name'] for ep in selected]
                }
                print(f"   [SUCCESS] {entity}: {len(selected)} endpoints selected (from {len(entity_endpoints)} matches)")
                for ep in selected:
                    print(f"      • {ep['method']} {ep['url_pattern']} - {ep['name']}")
            else:
                entity_results[entity] = {'found': 0, 'selected': 0, 'endpoints': []}
                print(f"   [ERROR] {entity}: No matching endpoints")
        
        # Final safety limit
        if len(filtered_endpoints) > 8:
            print(f"🚨 WARNING: {len(filtered_endpoints)} endpoints found, limiting to 8")
            filtered_endpoints = filtered_endpoints[:8]
        
        reduction_pct = round((1 - len(filtered_endpoints) / len(self.endpoints)) * 100, 2)
        
        return {
            'original_endpoint_count': len(self.endpoints),
            'filtered_endpoint_count': len(filtered_endpoints),
            'reduction_percentage': reduction_pct,
            'entity_results': entity_results,
            'filtered_endpoints': filtered_endpoints,
            'planning_plan': planning_plan.model_dump()
        }
    
    def _get_entity_operation_matches(self, entity: str, operations: List[str], methods: List[str]) -> List[Dict]:
        """Get endpoints matching entity + operation + method"""
        matches = []
        
        for endpoint in self.endpoints:
            if self._is_precise_match(endpoint, entity, operations, methods):
                matches.append(endpoint)
        
        return matches
    
    def _is_precise_match(self, endpoint: Dict, target_entity: str, operations: List[str], methods: List[str]) -> bool:
        """Check if endpoint matches entity + operation + method criteria"""
        
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
        """Check if endpoint operation matches any requested operation"""
        for requested_op in requested_ops:
            if self._semantic_operation_match(endpoint_op, requested_op.lower()):
                return True
        return False
    
    def _semantic_operation_match(self, endpoint_op: str, requested_op: str) -> bool:
        """Semantic matching for operations with common aliases"""
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

class RealWorldHybridExecutor:
    """
    Real-world hybrid executor that implements the exact logic from test_streamlined_pipeline.py
    NO MOCKS - only real Planning Agent, real SQL, real endpoint filtering
    """
    
    def __init__(self):
        # Initialize centralized logging
        self.logger = get_logger("okta_ai_agent.hybrid_executor", log_dir=get_default_log_dir())
        
        self.db_path = os.path.join(project_root, "sqlite_db", "okta_sync.db")
        self.api_data_path = os.path.join(project_root, "src", "data", "Okta_API_entitity_endpoint_reference.json")
        self.schema_path = os.path.join(project_root, "src", "data", "okta_schema.json")
        
        # Load API data for endpoint filtering
        self.api_data = self._load_api_data()
        
        # Load database schema for SQL operations
        self.db_schema = self._load_db_schema()
        
        # Load environment
        load_dotenv()
        
        # Initialize model configuration
        self._initialize_model_config()
        
        print("[LAUNCH] RealWorldHybridExecutor initialized")
        print(f"   📁 DB Path: {self.db_path}")
        print(f"   📁 API Data: {self.api_data_path}")
        print(f"   📁 Schema: {self.schema_path}")
        print(f"   [DATA] Entities loaded: {len(self.api_data.get('entity_summary', {}))}")
        print(f"   [DB] Tables loaded: {len(self.db_schema.get('sql_tables', {}))}")
    
    def _initialize_model_config(self):
        """Initialize and log model configuration"""
        try:
            ai_provider = os.getenv('AI_PROVIDER', 'openai').lower()
            models = ModelConfig.get_models()
            
            print(f"[BOT] Model Configuration:")
            print(f"   [TARGET] AI Provider: {ai_provider}")
            print(f"   [BRAIN] Planning Agent (Reasoning): {models[ModelType.REASONING]}")
            print(f"   [CODE] LLM2 (Coding): {models[ModelType.CODING]}")
            
            # Store models for easy access
            self.reasoning_model = models[ModelType.REASONING]
            self.coding_model = models[ModelType.CODING]
            
        except Exception as e:
            print(f"[WARNING] Model configuration warning: {e}")
            print(f"   Using fallback configuration")
            self.reasoning_model = None
            self.coding_model = None

    def _load_api_data(self) -> Dict:
        """Load API endpoints data for filtering"""
        try:
            with open(self.api_data_path, 'r') as f:
                api_data = json.load(f)
            
            endpoints_count = len(api_data.get('endpoints', []))
            entity_count = len(api_data.get('entity_summary', {}))
            
            print(f"[SUCCESS] Loaded API data: {endpoints_count} endpoints, {entity_count} entities")
            
            # Log entity summary for verification
            entities = list(api_data.get('entity_summary', {}).keys())
            print(f"   [TAG] Available entities: {entities[:10]}{'...' if len(entities) > 10 else ''}")
            
            return api_data
        except Exception as e:
            print(f"[ERROR] Failed to load API data: {e}")
            return {'endpoints': [], 'entity_summary': {}}
    
    def _load_db_schema(self) -> Dict:
        """Load database schema for SQL operations"""
        try:
            with open(self.schema_path, 'r') as f:
                schema_data = json.load(f)
            
            tables_count = len(schema_data.get('sql_tables', {}))
            print(f"[SUCCESS] Loaded DB schema: {tables_count} tables")
            
            # Log table names for verification
            tables = list(schema_data.get('sql_tables', {}).keys())
            print(f"   [DB] Available tables: {tables}")
            
            return schema_data
        except Exception as e:
            print(f"[ERROR] Failed to load DB schema: {e}")
            return {'sql_tables': {}}
    
    def verify_loaded_data(self):
        """Verify that all required data is loaded correctly"""
        print("\n[SEARCH] VERIFYING LOADED DATA")
        print("=" * 50)
        
        # Verify API data
        api_entities = list(self.api_data.get('entity_summary', {}).keys())
        api_endpoints = self.api_data.get('endpoints', [])
        
        print(f"[DATA] API Data:")
        print(f"   [TAG] Entities: {len(api_entities)}")
        print(f"   [LINK] Endpoints: {len(api_endpoints)}")
        
        if api_entities:
            print(f"   [LIST] Sample entities: {api_entities[:5]}")
            
            # Show sample entity details
            sample_entity = api_entities[0]
            entity_details = self.api_data['entity_summary'][sample_entity]
            print(f"   [SEARCH] Sample '{sample_entity}' operations: {entity_details.get('operations', [])[:3]}")
        
        # Verify DB schema
        db_tables = list(self.db_schema.get('sql_tables', {}).keys())
        
        print(f"[DB] Database Schema:")
        print(f"   [LIST] Tables: {len(db_tables)}")
        
        if db_tables:
            print(f"   [SEARCH] Available tables: {db_tables}")
            
            # Show sample table details
            sample_table = db_tables[0]
            table_details = self.db_schema['sql_tables'][sample_table]
            columns = table_details.get('columns', [])
            print(f"   [DATA] Sample '{sample_table}' columns: {columns[:5]}{'...' if len(columns) > 5 else ''}")
        
        # Verify files exist
        api_exists = os.path.exists(self.api_data_path)
        schema_exists = os.path.exists(self.schema_path)
        db_exists = os.path.exists(self.db_path)
        
        print(f"📁 File Status:")
        print(f"   {'[SUCCESS]' if api_exists else '[ERROR]'} API Data: {self.api_data_path}")
        print(f"   {'[SUCCESS]' if schema_exists else '[ERROR]'} Schema: {self.schema_path}")
        print(f"   {'[SUCCESS]' if db_exists else '[ERROR]'} Database: {self.db_path}")
        
        return {
            'api_entities_count': len(api_entities),
            'api_endpoints_count': len(api_endpoints),
            'db_tables_count': len(db_tables),
            'files_status': {
                'api_data': api_exists,
                'schema': schema_exists,
                'database': db_exists
            }
        }
    
    async def execute_query(self, query: str) -> Dict[str, Any]:
        """
        Main execution method that follows test_streamlined_pipeline logic:
        1. Planning Agent generates execution plan
        2. SQL queries based on steps  
        3. Endpoint filtering for LLM2
        4. Return combined results
        """
        
        print(f"\n[LAUNCH] EXECUTING REAL HYBRID QUERY")
        print(f"=" * 60)
        print(f"[NOTE] Query: {query}")
        
        # Use existing correlation ID if available, otherwise generate hybrid-specific one
        existing_correlation_id = get_correlation_id()
        if existing_correlation_id:
            correlation_id = existing_correlation_id
            print(f"[SYNC] Using existing correlation ID: {correlation_id}")
        else:
            correlation_id = f"hybrid_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            print(f"[NEW] Generated hybrid correlation ID: {correlation_id}")
        
        # CRITICAL: Always set the correlation ID to ensure ALL agents use the same ID
        # This ensures Planning Agent, SQL Agent, AND Results Formatter Agent all use identical correlation IDs
        set_correlation_id(correlation_id)
        print(f"[LOCK] Correlation ID locked for all agents: {correlation_id}")
        
        try:
            # Phase 1: Planning Agent (REAL)
            print(f"\n[BRAIN] PHASE 1: PLANNING AGENT")
            print("=" * 50)
            
            planning_result = await self._execute_planning_agent(query, correlation_id)
            if not planning_result or not planning_result.get('success'):
                return {'success': False, 'error': 'Planning Agent failed', 'correlation_id': correlation_id}
            
            # Extract the execution plan for compatibility with existing code
            execution_plan_response = planning_result['execution_plan']
            llm1_plan = execution_plan_response.model_dump()  # Keep variable name for compatibility
            
            # Phase 2-N: Dynamic Execution Based on LLM1 Plan Order
            sql_result = {'success': True, 'data': [], 'explanation': 'No SQL steps executed yet'}
            filter_result = {'success': True, 'filtered_endpoints': [], 'filtered_endpoint_count': 0}
            api_data_collected = []
            
            # Execute steps in the order specified by LLM1
            step_results = await self._execute_steps_in_order(llm1_plan, query, correlation_id)
            
            # Extract results for backward compatibility
            if step_results.get('sql_result'):
                sql_result = step_results['sql_result']
            if step_results.get('filter_result'):
                filter_result = step_results['filter_result']
            if step_results.get('api_data'):
                api_data_collected = step_results['api_data']
            
            # Determine if we need LLM2 code generation based on collected data
            # FIXED: Only consider SQL data valid if it actually came from step execution AND has data
            has_sql_data = (step_results.get('sql_result') is not None and 
                           sql_result.get('success') and 
                           len(sql_result.get('data', [])) > 0)
            has_api_endpoints = len(filter_result.get('filtered_endpoints', [])) > 0
            
            # Debug information
            print(f"\n[SEARCH] LLM2 DECISION LOGIC:")
            print(f"   [LIST] SQL result exists: {step_results.get('sql_result') is not None}")
            print(f"   [SUCCESS] SQL success: {sql_result.get('success')}")
            print(f"   [DATA] SQL data count: {len(sql_result.get('data', []))}")
            print(f"   [TARGET] Has SQL data: {has_sql_data}")
            print(f"   [LINK] API endpoints: {has_api_endpoints}")
            print(f"   [NOTE] LLM2 condition (has_api_endpoints and not has_sql_data): {has_api_endpoints and not has_sql_data}")
            
            # Only run LLM2 if we have API endpoints but no complete SQL data
            # Skip LLM2 if we already have complete results from SQL
            llm2_result = {'success': False, 'code': '', 'explanation': 'Skipped - using direct SQL results'}
            
            if has_api_endpoints and not has_sql_data:
                print(f"\n[BOT] PHASE 4: LLM2 CODE GENERATION")
                print("=" * 50)
                print("[TARGET] Generating API code for endpoints without SQL data")
                
                llm2_result = await self._execute_llm2_code_generation(
                    planning_result, sql_result, filter_result, query, correlation_id, api_data_collected
                )
            else:
                print(f"\n[SKIP] PHASE 4: SKIPPING LLM2 CODE GENERATION")
                print("=" * 50)
                if has_sql_data:
                    print("[SUCCESS] Complete SQL data available - proceeding directly to results processing")
                else:
                    print("[INFO] No API endpoints to process")
            
            # Phase 5: Execute Generated Code (only if LLM2 generated code)
            execution_result = None
            if llm2_result.get('success') and llm2_result.get('code'):
                print(f"\n[LAUNCH] PHASE 5: CODE EXECUTION")
                print("=" * 50)
                
                execution_result = await self._execute_generated_code(
                    llm2_result['code'], correlation_id
                )
            else:
                print(f"\n[SKIP] PHASE 5: SKIPPING CODE EXECUTION")
                print("=" * 50)
                print("[INFO] No code generated by LLM2 - using step results directly")
                execution_result = {'success': True, 'stdout': 'No code execution needed', 'stderr': ''}
            
            # Phase 6: Results Combination
            print(f"\n[TARGET] PHASE 6: RESULTS COMBINATION")
            print("=" * 50)
            
            final_result = await self._combine_results(planning_result, sql_result, filter_result, llm2_result, correlation_id)
            
            # Add execution results to final result
            if execution_result:
                final_result['execution_result'] = execution_result
            
            # Phase 7: Enhanced Results Processing with Results Formatter Agent (NEW!)
            print(f"\n[BRAIN] PHASE 7: RESULTS FORMATTER AGENT PROCESSING")
            print("=" * 50)
            
            try:
                # CRITICAL: Ensure correlation ID is set before Results Formatter Agent execution
                set_correlation_id(correlation_id)
                
                enhanced_final_result = await self._process_final_results_with_llm3(
                    combined_results=final_result,
                    original_query=query,
                    correlation_id=correlation_id,
                    execution_result=execution_result,
                    step_context=step_results.get('execution_context', {})  # Pass step context
                )
                
                print(f"[SUCCESS] Results Formatter Agent processing completed successfully")
                
                # Export results to CSV file
                csv_file = await self._export_results_to_csv(enhanced_final_result, query, correlation_id, step_results)
                if csv_file:
                    enhanced_final_result['csv_export_path'] = csv_file
                
                final_result = enhanced_final_result
                
            except Exception as formatter_error:
                print(f"[WARNING] Results Formatter Agent processing failed: {formatter_error}")
                print(f"[REFRESH] Continuing with basic results...")
                # Keep the original final_result if Results Formatter Agent fails
            
            print(f"\n[SUCCESS] HYBRID EXECUTION COMPLETED!")
            print(f"   [DATA] Planning Steps: {len(llm1_plan.get('plan', {}).get('steps', []))}")
            print(f"   [SAVE] SQL Results: {len(sql_result.get('data', []))} records")
            print(f"   [SEARCH] Filtered Endpoints: {filter_result.get('filtered_endpoint_count', 0)}")
            print(f"   [BOT] LLM2 Code Generated: {llm2_result.get('success', False)}")
            print(f"   [NOTE] Code Length: {len(llm2_result.get('code', ''))} characters")
            print(f"   [LAUNCH] Code Executed: {execution_result.get('success', False) if execution_result else False}")
            
            # Enhanced execution summary with Results Formatter Agent info
            processing_method = final_result.get('processing_method', 'basic_combination')
            enhancement_features = final_result.get('enhancement_features', {})
            print(f"   [LIST] Results Processing: {processing_method}")
            if enhancement_features.get('pandas_analytics'):
                print(f"   [DATA] Pandas Analytics: [SUCCESS] Enabled")
                print(f"   [UP] Data Insights: [SUCCESS] Generated")
                print(f"   [DOWN] Visualizations: [SUCCESS] Suggested")
            
            # Export results to CSV
            csv_path = await self._export_results_to_csv(final_result, query, correlation_id, step_results)
            if csv_path:
                print(f"[EXPORT] Results exported to CSV: {csv_path}")
            
            return final_result
            
        except Exception as e:
            print(f"[ERROR] Hybrid execution failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False, 
                'error': str(e), 
                'correlation_id': correlation_id,
                'phase': 'execution'
            }
    
    async def _execute_planning_agent(self, query: str, correlation_id: str) -> Dict[str, Any]:
        """Execute Planning Agent using PydanticAI with structured output and validation"""
        
        if planning_agent is None:
            return {'success': False, 'error': 'Planning agent not available'}
        
        
        # Build database schema context
        db_schema_context = self._build_db_schema_context()
        
        # Build API entities context
        available_entities = list(self.api_data.get('entity_summary', {}).keys())
        entity_summary = self.api_data.get('entity_summary', {})
        api_entities_context = self._build_api_entities_context(available_entities, entity_summary)
        
        print(f"[REFRESH] Running Planning Agent with PydanticAI...")
        print(f"   [DATA] {len(available_entities)} API entities available")
        print(f"   [DB] {len(self.db_schema.get('sql_tables', {}))} SQL tables available")
        
        try:
            # Create dependencies for Planning Agent
            planning_deps = PlanningDependencies(
                available_entities=available_entities,
                entity_summary=self.api_data.get('entity_summary', {}),
                sql_tables=self.db_schema.get('tables', {}),
                flow_id=correlation_id
            )
            
            # CRITICAL: Ensure correlation ID is set before Planning Agent execution
            set_correlation_id(correlation_id)
            
            # Log Planning Agent execution start
            self.logger.info(f"[{correlation_id}] Planning Agent: Starting execution plan generation")
            self.logger.debug(f"[{correlation_id}] Planning query: {query}")
            
            # Execute Planning Agent with structured output
            planning_result = await planning_agent.run(
                query, 
                deps=planning_deps
            )
            
            # Extract the structured output
            planning_output = planning_result.output
            
            # Log Planning Agent completion
            if hasattr(planning_result, 'usage') and planning_result.usage():
                usage = planning_result.usage()
                input_tokens = getattr(usage, 'request_tokens', getattr(usage, 'input_tokens', 0))
                output_tokens = getattr(usage, 'response_tokens', getattr(usage, 'output_tokens', 0))
                self.logger.info(f"[{correlation_id}] Planning Agent completed - {input_tokens} in, {output_tokens} out tokens")
            else:
                self.logger.info(f"[{correlation_id}] Planning Agent completed successfully")
            
            print(f"[SUCCESS] Planning Agent completed successfully")
            print(f"   [LIST] Plan confidence: {planning_output.plan.confidence}")
            print(f"   [TARGET] Steps planned: {len(planning_output.plan.steps)}")
            
            # Convert to ExecutionPlanResponse format for compatibility
            execution_plan_response = ExecutionPlanResponse(
                plan={
                    'steps': [step.model_dump() for step in planning_output.plan.steps],
                    'reasoning': planning_output.plan.reasoning,
                },
                confidence=planning_output.plan.confidence
            )
            
            # Validate the response
            try:
                validated_response = StrictValidator.validate_planning_agent_response(
                    execution_plan_response.model_dump(), 
                    available_entities, 
                    entity_summary
                )
            except ValidationError as ve:
                print(f"[ERROR] PLANNING AGENT VALIDATION FAILED: {ve}")
                return {'success': False, 'error': f'Planning Agent validation failed: {ve}'}
            
            # Display plan details
            print(f"� PLANNING AGENT PLAN:")
            steps = execution_plan_response.plan.get('steps', [])
            entities = list(set([step.get('tool_name', '') for step in steps]))
            print(f"[TARGET] Entities: {entities}")
            print(f"[LIST] Steps: {len(steps)} steps planned")
            
            # Return success with the execution plan
            return {
                'success': True,
                'execution_plan': execution_plan_response,
                'planning_output': planning_output,
                'entities': entities,
                'correlation_id': correlation_id
            }
            
        except Exception as e:
            print(f"[ERROR] Planning Agent execution failed: {e}")
            print(f"Error details: {traceback.format_exc()}")
            return {'success': False, 'error': f'Planning Agent error: {e}'}
    
    def _build_db_schema_context(self) -> str:
        """Build database schema context for Planning Agent"""
        sql_tables = self.db_schema.get('sql_tables', {})
        sql_table_names = list(sql_tables.keys())
        
        # Build detailed SQL schema information from actual schema
        sql_schema_details = []
        for table_name, table_info in sql_tables.items():
            columns = table_info.get('columns', [])
            fast_ops = table_info.get('fast_operations', [])
            
            # Show what each table actually contains
            table_desc = f"• {table_name}: columns={columns[:8]}{'...' if len(columns) > 8 else ''}"
            if fast_ops:
                table_desc += f", operations={fast_ops[:3]}{'...' if len(fast_ops) > 3 else ''}"
            sql_schema_details.append(table_desc)
        
        return f"""
SQL DATABASE SCHEMA (actual schema data):
Available Tables: {', '.join(sql_table_names)}

{chr(10).join(sql_schema_details)}

KEY INSIGHT: Look at the actual columns and operations above to determine what data IS or IS NOT available in SQL.
- If you see columns like 'user_okta_id', 'app_okta_id', 'factor_type' → that data is available in SQL
- If you don't see role-related columns → that data requires API calls
- Use table names as tool_name for SQL operations, API entity names for non-SQL operations"""
    
    def _build_api_entities_context(self, available_entities: List[str], entity_summary: Dict) -> str:
        """Build API entities context for Planning Agent"""
        entity_operations_text = []
        for entity, details in entity_summary.items():
            operations = details.get('operations', [])
            methods = details.get('methods', [])
            entity_operations_text.append(f"  • {entity}: operations=[{', '.join(operations)}], methods=[{', '.join(methods)}]")
        
        return f"AVAILABLE ENTITIES AND OPERATIONS:\n{chr(10).join(entity_operations_text)}"
    
    async def _execute_sql_queries(self, planning_plan: Dict, query: str, correlation_id: str, api_context: List = None) -> Dict[str, Any]:
        """Execute SQL queries with optional API context data"""
        
        if not sql_agent:
            print("[ERROR] SQL agent not available")
            return {'success': False, 'error': 'SQL agent not available', 'data': []}
        
        print(f"[SAVE] Executing SQL queries...")
        print(f"   [SEARCH] DEBUG: Starting SQL execution")
        
        try:
            # Use the real SQL agent with proper tenant_id and correlation ID
            sql_dependencies = SQLDependencies(tenant_id="default", flow_id=correlation_id)
            
            # CRITICAL: Ensure correlation ID is set before SQL Agent execution  
            set_correlation_id(correlation_id)
            
            # Build context query if API context is provided
            context_query = query
            if api_context:
                context_query = f"{query}\n\nCONTEXT FROM PREVIOUS STEPS:\n"
                for api_item in api_context:
                    if 'sample_data' in api_item:
                        # Extract user IDs from API events for SQL agent
                        sample_data = api_item['sample_data'][:MAX_SAMPLES_PER_STEP]  # Use proper sampling
                        
                        # For system log or any other data, use standard format and let LLM decide what to extract
                        context_query += f"[DATA] Step {api_item.get('step_name', 'unknown')}:\n"
                        context_query += f"   • Variable: {api_item.get('variable_name', 'unknown_variable')}\n"
                        context_query += f"   • Total Records: {api_item.get('total_records', len(sample_data))}\n"
                        context_query += f"   • Fields: {api_item.get('data_fields', [])}\n"
                        context_query += f"   • Sample Data:\n{json.dumps(sample_data, indent=6)}\n"
                        context_query += f"   [WARNING]  IMPORTANT: Use variable '{api_item.get('variable_name', 'unknown_variable')}' in your code to process ALL {api_item.get('total_records', len(sample_data))} records\n\n"
            
            print(f"[SEARCH] DEBUG: Starting SQL execution")
            print(f"[CHAT] FULL QUERY TEXT PASSED TO SQL AGENT:")
            print("=" * 80)
            print(context_query)
            print("=" * 80)
            
            # Log SQL agent execution start
            self.logger.info(f"[{correlation_id}] SQL Agent: Starting query generation")
            self.logger.debug(f"[{correlation_id}] Input query length: {len(context_query)} characters")
            
            sql_result = await sql_agent.run(context_query, deps=sql_dependencies)
            
            # Log SQL agent execution completion
            if hasattr(sql_result, 'usage') and sql_result.usage():
                usage = sql_result.usage()
                input_tokens = getattr(usage, 'request_tokens', getattr(usage, 'input_tokens', 0))
                output_tokens = getattr(usage, 'response_tokens', getattr(usage, 'output_tokens', 0))
                self.logger.info(f"[{correlation_id}] SQL Agent completed - {input_tokens} in, {output_tokens} out tokens")
            else:
                self.logger.info(f"[{correlation_id}] SQL Agent completed successfully")
            
            # Extract data from the SQL agent response (PydanticAI structured output)
            try:
                # Use result.output for modern PydanticAI
                sql_output = sql_result.output
                sql_query = sql_output.sql if sql_output else ''
                explanation = sql_output.explanation if sql_output else ''
                
                print(f"[SEARCH] DEBUG: Generated FULL SQL Query:")
                print(f"   {sql_query}")
                print(f"[NOTE] SQL Explanation: {explanation}")
                print(f"[SEARCH] DEBUG: SQL Query Length: {len(sql_query)} characters")
                
                # Simple safety check
                if is_safe_sql and not is_safe_sql(sql_query):
                    print("[WARNING] SQL query failed safety check - blocking execution")
                    return {'success': False, 'error': 'Unsafe SQL query generated', 'explanation': explanation, 'data': []}
                
                # Execute the SQL query against the database
                if sql_query and sql_query.strip():
                    db_data = await self._execute_raw_sql_query(sql_query, correlation_id)
                    
                    return {
                        'success': True, 
                        'data': db_data, 
                        'sql_query': sql_query,
                        'explanation': explanation,
                        'correlation_id': correlation_id
                    }
                else:
                    print("[WARNING] SQL agent returned empty query")
                    return {'success': False, 'error': 'Empty SQL query generated', 'explanation': explanation, 'data': []}
                    
            except Exception as e:
                print(f"[ERROR] Failed to parse SQL agent response: {e}")
                return {'success': False, 'error': f'SQL parsing error: {e}', 'data': []}
                
        except Exception as e:
            print(f"[ERROR] SQL execution failed: {e}")
            return {'success': False, 'error': str(e), 'data': []}

    async def _execute_raw_sql_query(self, sql_query: str, correlation_id: str) -> List[Dict]:
        """Execute raw SQL query against the database and return results"""
        
        print(f"[DB] Executing SQL query against database...")
        
        try:
            import sqlite3
            
            # Connect to database
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row  # Enable column access by name
            cursor = conn.cursor()
            
            # Execute query
            cursor.execute(sql_query)
            rows = cursor.fetchall()
            
            # Convert to list of dictionaries
            data = [dict(row) for row in rows]
            
            conn.close()
            
            print(f"[SUCCESS] SQL query executed successfully: {len(data)} records returned")
            if data:
                print(f"[DATA] Sample record keys: {list(data[0].keys())}")
            
            return data
            
        except Exception as e:
            print(f"[ERROR] Database query failed: {e}")
            return []
    
    async def _execute_endpoint_filtering(self, planning_plan: Dict, correlation_id: str) -> Dict[str, Any]:
        """Execute endpoint filtering based on LLM1 plan using REAL filtering logic"""
        
        print(f"[SEARCH] Filtering endpoints based on LLM1 plan...")
        
        try:
            # Create ExecutionPlanResponse from the plan
            planning_output = ExecutionPlanResponse(**planning_plan)
            
            # Use the real endpoint filter
            filter_engine = PreciseEndpointFilter(self.api_data)
            filter_results = filter_engine.filter_endpoints(planning_output)
            
            print(f"[DATA] FILTERING RESULTS:")
            print(f"[UP] Original endpoints: {filter_results['original_endpoint_count']}")
            print(f"[DOWN] Filtered endpoints: {filter_results['filtered_endpoint_count']}")
            print(f"[TARGET] Reduction: {filter_results['reduction_percentage']}%")
            
            # Add explicit success indicator for downstream processing
            filter_results['success'] = True
            
            return filter_results
            
        except Exception as e:
            print(f"[ERROR] Endpoint filtering failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False, 
                'error': str(e),
                'filtered_endpoint_count': 0,
                'filtered_endpoints': []
            }
    
    async def _execute_llm2_code_generation(self, planning_result: Dict, sql_result: Dict, filter_result: Dict, query: str, correlation_id: str, api_data_collected: List = None) -> Dict[str, Any]:
        """Execute LLM2 code generation phase using SQL data + filtered endpoints"""
        
        # Prepare data for LLM2 first
        sql_data = sql_result.get('data', [])
        filtered_endpoints = filter_result.get('filtered_endpoints', [])
        
        print(f"[BOT] Generating Python code with SQL data + API endpoints...")
        print(f"[DATA] LLM2 Context Summary:")
        print(f"   [SAVE] SQL Records: {len(sql_data)}")
        print(f"   [LINK] API Endpoints: {len(filtered_endpoints)}")
        
        # Log endpoint details for verification
        for i, ep in enumerate(filtered_endpoints, 1):
            print(f"   [LIST] Endpoint {i}: {ep.get('method', '')} {ep.get('url_pattern', '')}")
            print(f"      • Name: {ep.get('name', '')}")
            print(f"      • Entity: {ep.get('entity', '')}, Operation: {ep.get('operation', '')}")
            req_params = ep.get('parameters', {}).get('required', [])
            opt_params = ep.get('parameters', {}).get('optional', [])
            print(f"      • Required: {req_params}")
            print(f"      • Optional: {opt_params}")
            print(f"      • Description: {ep.get('description', '')[:100]}...")
        
        
        if not sql_data and not filtered_endpoints:
            print("[WARNING] No SQL data or API endpoints available for code generation")
            return {
                'success': False, 
                'error': 'No data available for code generation',
                'code': '',
                'explanation': ''
            }
        
        # Build context for LLM2 with COMPLETE API data
        context_info = {
            'query': query,
            'sql_data_sample': sql_data[:3] if sql_data else [],  # First 3 records as sample
            'sql_record_count': len(sql_data),
            'available_endpoints': [
                {
                    'id': ep.get('id', ''),
                    'name': ep.get('name', ''),
                    'method': ep.get('method', ''),
                    'url_pattern': ep.get('url_pattern', ''),
                    'entity': ep.get('entity', ''),
                    'operation': ep.get('operation', ''),
                    'description': ep.get('description', ''),
                    'folder_path': ep.get('folder_path', ''),
                    'parameters': ep.get('parameters', {})
                }
                for ep in filtered_endpoints
            ],
            'entities_involved': planning_result.get('entities', [])
        }
        
        # Load LLM2 system prompt from file
        llm2_prompt_path = os.path.join(os.path.dirname(__file__), "llm2_system_prompt.txt")
        try:
            with open(llm2_prompt_path, 'r', encoding='utf-8') as f:
                base_llm2_prompt = f.read()
        except FileNotFoundError:
            print(f"[WARNING] llm2_system_prompt.txt not found at {llm2_prompt_path}, using fallback prompt")
            base_llm2_prompt = "You are LLM2, a Python code generator for Okta operations. Generate working Python code that combines SQL data with API calls."
        
        # Create dynamic LLM2 system prompt with context
        # Extract Step 2 description for LLM2 context
        planning_plan = planning_result.get('execution_plan', {}).model_dump() if 'execution_plan' in planning_result else planning_result.get('planning_output', {}).execution_plan.model_dump() if 'planning_output' in planning_result else {}
        steps = planning_plan.get('plan', {}).get('steps', []) if 'plan' in planning_plan else planning_plan.get('steps', [])
        step2_description = "No specific step found"
        
        # Find the API step (usually step 2 for role assignments)
        for step in steps:
            if step.get('tool_name') in ['role_assignment', 'role']:
                step2_description = f"Step: {step.get('tool_name')} - {step.get('query_context', '')} - Reason: {step.get('reason', '')}"
                break
        
        llm2_system_prompt = f"""{base_llm2_prompt}

DYNAMIC CONTEXT FOR THIS REQUEST:
- LLM2 Task: {step2_description}
- SQL Records Available: {len(sql_data)}
- API Endpoints Available: {len(filtered_endpoints)}
- Entities: {planning_result.get('entities', [])}

AVAILABLE SQL DATA SAMPLE:
{json.dumps(sql_data[:2], indent=2) if sql_data else 'No SQL data available'}

AVAILABLE API ENDPOINTS WITH COMPLETE DOCUMENTATION:
{json.dumps(context_info['available_endpoints'], indent=2)}

🚨 CRITICAL API GUIDELINES - FOLLOW STRICTLY:

1. **PARAMETER COMPLIANCE**:
   - ALWAYS use ONLY the parameters listed in 'parameters.required' and 'parameters.optional'
   - NEVER use parameters not in the API specification (like 'published' for system logs)
   - For system_log endpoints, use 'since', 'until', 'filter', 'q', 'limit', 'sortOrder' ONLY
   
2. **URL CONSTRUCTION**:
   - Use the exact 'url_pattern' provided
   - Replace :paramName with actual values (e.g., :userId with actual user ID)
   - Build full URLs: https://{{okta_domain}}/api/v1/...
   
3. **METHOD COMPLIANCE**:
   - Use the exact HTTP method specified ('method' field)
   - GET for retrieving data, POST for creating, PUT for updating, DELETE for removing
   
4. **DESCRIPTION ADHERENCE**:
   - Read the 'description' field carefully for API-specific guidance
   - Follow any special notes, limitations, or requirements mentioned
   - Pay attention to default values, pagination, and rate limits
   
5. **TIME FILTERING** (Critical for logs/events):
   - Use 'since' and 'until' parameters for time-based filtering
   - Format: ISO 8601 with Z suffix (e.g., "2025-07-09T00:00:00.000Z")
   - NEVER use 'published' in filter expressions - use 'since'/'until' instead
   
6. **FILTER EXPRESSIONS**:
   - Follow SCIM filter syntax as documented
   - Use correct operators: eq, ne, gt, lt, sw, co, ew
   - Quote string values properly
   
7. **ERROR HANDLING**:
   - Include proper error handling for API calls
   - Handle rate limits, timeouts, and authentication errors
   - Provide meaningful error messages

GENERATE COMPLIANT CODE THAT STRICTLY FOLLOWS THESE API SPECIFICATIONS.

Generate practical, executable code that solves the user's query: {query}"""
        
        try:
            # Create LLM2 agent using coding model with strict JSON response format
            coding_model = self.coding_model if self.coding_model else ModelConfig.get_model(ModelType.CODING)
            llm2_agent = Agent(
                model=coding_model,
                system_prompt=llm2_system_prompt,
                result_type=LLM2CodeResponse  # Enforce JSON structure
            )
            
            print(f"[REFRESH] Running LLM2 code generation...")
            
            # Log LLM2 execution start with detailed context
            self.logger.info(f"[{correlation_id}] LLM2 Code Generation: Starting code generation")
            self.logger.debug(f"[{correlation_id}] LLM2 Context: SQL records={len(sql_data)}, API endpoints={len(filtered_endpoints)}")
            
            # Generate code
            llm2_raw_result = await llm2_agent.run(
                f"Generate Python code for: {step2_description}\n\nSQL Data Structure: {list(sql_data[0].keys()) if sql_data else []}\nAPI Endpoints: {len(filtered_endpoints)} available"
            )
            
            llm2_output = llm2_raw_result.output
            print(f"[SEARCH] LLM2 output type: {type(llm2_output)}")
            
            # Log LLM2 token usage if available
            if hasattr(llm2_raw_result, 'usage') and llm2_raw_result.usage():
                usage = llm2_raw_result.usage()
                input_tokens = getattr(usage, 'request_tokens', getattr(usage, 'input_tokens', 0))
                output_tokens = getattr(usage, 'response_tokens', getattr(usage, 'output_tokens', 0))
                self.logger.info(f"[{correlation_id}] LLM2 Code Generation completed - {input_tokens} in, {output_tokens} out tokens")
            else:
                self.logger.info(f"[{correlation_id}] LLM2 Code Generation completed successfully")
            
            # Parse LLM2 response - should be LLM2CodeResponse object
            if isinstance(llm2_output, LLM2CodeResponse):
                # Direct Pydantic model response
                python_code = llm2_output.python_code
                explanation = llm2_output.explanation
                requirements = llm2_output.requirements
                print(f"[SUCCESS] Successfully parsed LLM2 Pydantic response")
            elif isinstance(llm2_output, str):
                try:
                    # Fallback: try to parse JSON manually
                    llm2_response = json.loads(llm2_output)
                    python_code = llm2_response.get('python_code', '')
                    explanation = llm2_response.get('explanation', '')
                    requirements = llm2_response.get('requirements', [])
                    print(f"[SUCCESS] Successfully parsed LLM2 JSON response")
                except json.JSONDecodeError as e:
                    print(f"[ERROR] LLM2 returned invalid JSON: {e}")
                    print(f"Raw output: {llm2_output[:500]}...")
                    return {
                        'success': False,
                        'error': f'LLM2 JSON parsing failed: {e}',
                        'code': '',
                        'explanation': 'Failed to parse LLM2 response',
                        'requirements': []
                    }
            else:
                # Convert dict to expected format
                llm2_response = llm2_output
                python_code = llm2_response.get('python_code', '')
                explanation = llm2_response.get('explanation', '')
                requirements = llm2_response.get('requirements', [])
            
            # Clean up markdown formatting from code
            if python_code:
                # Remove markdown code blocks
                python_code = re.sub(r'^```(?:python)?\s*\n', '', python_code, flags=re.MULTILINE)
                python_code = re.sub(r'\n```\s*$', '', python_code, flags=re.MULTILINE)
                python_code = python_code.strip()
            
            # Log the FULL generated code for debugging (user requested complete code visibility)
            self.logger.info(f"[{correlation_id}] LLM2 Generated Code - Length: {len(python_code)} characters")
            self.logger.debug(f"[{correlation_id}] LLM2 Complete Generated Code:\n{python_code}")
            self.logger.debug(f"[{correlation_id}] LLM2 Explanation: {explanation}")
            self.logger.debug(f"[{correlation_id}] LLM2 Requirements: {requirements}")
            
            print(f"[SUCCESS] LLM2 code generation completed")
            print(f"[NOTE] Code length: {len(python_code)} characters")
            print(f"[LIST] Requirements: {requirements}")
            print(f"[SEARCH] Code preview: {python_code[:200]}{'...' if len(python_code) > 200 else ''}")
            
            return {
                'success': True,
                'code': python_code,
                'explanation': explanation,
                'requirements': requirements,
                'context_used': {
                    'sql_records': len(sql_data),
                    'api_endpoints': len(filtered_endpoints)
                },
                'correlation_id': correlation_id
            }
            
        except Exception as e:
            print(f"[ERROR] LLM2 code generation failed: {e}")
            # Log the LLM2 error for debugging
            self.logger.error(f"[{correlation_id}] LLM2 Code Generation failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'error': str(e),
                'code': '',
                'explanation': '',
                'requirements': []
            }
    
    async def _combine_results(self, planning_result: Dict, sql_result: Dict, filter_result: Dict, llm2_result: Dict, correlation_id: str) -> Dict[str, Any]:
        """Combine all results into final response"""
        
        print(f"[TARGET] Combining all results...")
        
        return {
            'success': True,
            'correlation_id': correlation_id,
            'timestamp': datetime.now().isoformat(),
            'planning_agent': {
                'success': planning_result.get('success'),
                'entities': planning_result.get('entities', []),
                'steps_count': len(planning_result.get('execution_plan', {}).plan.get('steps', []) if 'execution_plan' in planning_result else []),
                'confidence': planning_result.get('execution_plan', {}).confidence if 'execution_plan' in planning_result else None,
                'reasoning': planning_result.get('planning_output', {}).plan.reasoning if 'planning_output' in planning_result else None,
                'full_plan': planning_result.get('execution_plan', {}).plan if 'execution_plan' in planning_result else {},
                'planned_steps': planning_result.get('execution_plan', {}).plan.get('steps', []) if 'execution_plan' in planning_result else []
            },
            'sql_execution': {
                'success': sql_result.get('success'),
                'records_count': len(sql_result.get('data', [])),
                'data_sample': sql_result.get('data', [])[:3],  # First 3 records as sample for display
                'data': sql_result.get('data', []),  # Complete dataset for Results Formatter Agent counting
                'sql_query': sql_result.get('sql_query', ''),
                'explanation': sql_result.get('explanation', '')
            },
            'endpoint_filtering': {
                'success': filter_result.get('success', True),
                'original_count': filter_result.get('original_endpoint_count', 0),
                'filtered_count': filter_result.get('filtered_endpoint_count', 0),
                'reduction_percentage': filter_result.get('reduction_percentage', 0),
                'endpoints': filter_result.get('filtered_endpoints', [])
            },
            'llm2_code_generation': {
                'success': llm2_result.get('success', False),
                'code': llm2_result.get('code', ''),
                'explanation': llm2_result.get('explanation', ''),
                'requirements': llm2_result.get('requirements', []),
                'code_length': len(llm2_result.get('code', ''))
            },
            'execution_summary': {
                'total_sql_records': len(sql_result.get('data', [])),
                'total_api_endpoints': filter_result.get('filtered_endpoint_count', 0),
                'entities_involved': planning_result.get('entities', []),
                'sql_to_api_ready': len(sql_result.get('data', [])) > 0 and filter_result.get('filtered_endpoint_count', 0) > 0,
                'next_phase': 'Ready for SQL→API mapping execution'
            }
        }
    
    async def _process_final_results_with_llm3(self, combined_results: Dict[str, Any], original_query: str, correlation_id: str, execution_result: Dict[str, Any] = None, step_context: Dict[str, Any] = None, use_structured: bool = True) -> Dict[str, Any]:
        """
        Process final results using Results Formatter Agent with pandas enhancement.
        
        This method uses the dedicated Results Formatter Agent system prompt and enhanced pandas processing
        to create comprehensive, user-friendly summaries with data insights.
        
        Args:
            combined_results: The raw combined results from all phases
            original_query: The user's original query
            execution_result: Optional code execution results
            step_context: Context from step execution
            use_structured: Whether to use structured PydanticAI Results Formatter Agent (Phase 1)
            
        Returns:
            Dict containing both raw results and enhanced processed summary
        """
        
        print(f"[LIST] PHASE 7: ENHANCED RESULTS PROCESSING (Results Formatter Agent)")
        print("=" * 50)
        
        # Phase 1: Try structured Results Formatter Agent first if enabled
        if use_structured:
            print(f"[BOT] Using Results Formatter Agent with PydanticAI (Modern)")
            try:
                from src.data.results_formatter_agent import process_results_structured
                
                # Build step_results_for_processing with variable names
                step_results_for_processing = {}
                
                # Extract data from step context using the new variable system
                if step_context and step_context.get('data_variables'):
                    for var_name, var_data in step_context['data_variables'].items():
                        step_results_for_processing[var_name] = var_data
                
                # Fallback to old format if no variables stored
                if not step_results_for_processing:
                    # CRITICAL: For Results Formatter Agent, pass COMPLETE SQL data for proper counting
                    # Use the full data from sql_execution, not just the sample
                    sql_data = combined_results.get('sql_execution', {}).get('data', [])  # Use COMPLETE data
                    if sql_data:
                        step_results_for_processing["step_1_sql"] = sql_data
                        print(f"[DATA] Passing {len(sql_data)} SQL records to Results Formatter Agent")
                    
                    if execution_result and execution_result.get('success'):
                        stdout = execution_result.get('stdout', '')
                        if stdout:
                            step_results_for_processing["step_2_api"] = [{'raw_output': stdout}]

                # CRITICAL: Pass the complete raw_results to Results Formatter Agent for proper record counting
                # This allows the agent to count total records correctly for mode selection (sample vs complete)
                # The Results Formatter Agent needs ALL data for counting, then will create samples internally for LLM
                complete_results_structure = {
                    'raw_results': combined_results,  # Complete results for counting
                    'step_results': step_results_for_processing  # Processed results for formatting
                }
                
                print(f"[DEBUG] Results Formatter Agent Data Summary:")
                print(f"   SQL Records: {len(combined_results.get('sql_execution', {}).get('data', []))}")
                print(f"   API Endpoints: {combined_results.get('endpoint_filtering', {}).get('filtered_count', 0)}")
                print(f"   Total for counting: {len(combined_results.get('sql_execution', {}).get('data', []))}")
                
                # Use structured Results Formatter Agent processor
                structured_response = await process_results_structured(
                    query=original_query,
                    results=complete_results_structure,  # Pass complete structure for proper counting
                    original_plan=None,
                    is_sample=False,
                    metadata={'flow_id': correlation_id}  # Use the SAME correlation ID as other agents
                )
                
                print(f"[SUCCESS] Results Formatter Agent processed with {structured_response.get('display_type')} format")
                
                return {
                    'success': True,
                    'raw_results': combined_results,
                    'processed_summary': structured_response,
                    'processing_method': 'results_formatter_structured_pydantic',
                    'enhancement_features': {
                        'pandas_analytics': True,
                        'data_insights': True,
                        'visualization_suggestions': True
                    }
                }
                
            except Exception as e:
                print(f"[WARNING] [Structured Results Formatter Agent] Failed: {e}")
                print(f"[REFRESH] Falling back to original Results Formatter Agent implementation...")
        
        # Original LLM3 implementation (fallback) - DISABLED due to compatibility issues
        print(f"[BOT] Skipping Original LLM3 Results Processor (deprecated interface)")
        
        # Use basic fallback instead since the structured formatter already processed results
        print(f"[REFRESH] Using basic results combination...")
        return {
            'success': True,
            'raw_results': combined_results,
            'processed_summary': f"Query: {original_query}\n\nResults: {len(combined_results)} phases completed",
            'processing_method': 'basic_fallback'
        }
    
    async def _execute_generated_code(self, python_code: str, correlation_id: str) -> Dict[str, Any]:
        """Execute the generated Python code and capture results"""
        
        print(f"[LAUNCH] EXECUTING GENERATED CODE")
        
        # Log code execution start (avoid logging full code due to size)
        self.logger.info(f"[{correlation_id}] Code Execution: Starting execution of generated LLM2 code")
        self.logger.debug(f"[{correlation_id}] Code length: {len(python_code)} characters")
        
        try:
            # Save the code to a temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(python_code)
                temp_file = f.name
            
            self.logger.debug(f"[{correlation_id}] Code Execution: Saved code to temporary file: {temp_file}")
            
            # Execute the code and capture output
            result = subprocess.run(
                [sys.executable, temp_file],
                capture_output=True,
                text=True,
                timeout=60,  # 60 second timeout for API calls that may need pagination
                cwd=os.path.dirname(__file__)  # Run in data directory
            )
            
            # Clean up temp file
            os.unlink(temp_file)
            
            if result.returncode == 0:
                print(f"[SUCCESS] Code executed successfully!")
                print(result.stdout)
                
                # Log successful execution results (truncate large outputs)
                self.logger.info(f"[{correlation_id}] Code Execution: Completed successfully (return code: 0)")
                stdout_preview = result.stdout[:500] + "..." if len(result.stdout) > 500 else result.stdout
                self.logger.debug(f"[{correlation_id}] Code Execution stdout preview: {stdout_preview}")
                if result.stderr:
                    self.logger.debug(f"[{correlation_id}] Code Execution stderr: {result.stderr}")
                
                return {
                    'success': True,
                    'stdout': result.stdout,
                    'stderr': result.stderr,
                    'return_code': result.returncode,
                    'execution_time': 'N/A'  # Could add timing if needed
                }
            else:
                print(f"[ERROR] Code execution failed with return code {result.returncode}")
                print(result.stderr)
                
                # Log failed execution
                self.logger.error(f"[{correlation_id}] Code Execution: Failed with return code {result.returncode}")
                self.logger.error(f"[{correlation_id}] Code Execution stderr: {result.stderr}")
                self.logger.debug(f"[{correlation_id}] Code Execution stdout: {result.stdout}")
                
                return {
                    'success': False,
                    'stdout': result.stdout,
                    'stderr': result.stderr,
                    'return_code': result.returncode,
                    'error': f"Execution failed with code {result.returncode}"
                }
                
        except subprocess.TimeoutExpired:
            print(f"⏰ Code execution timed out after 60 seconds")
            self.logger.error(f"[{correlation_id}] Code Execution: Timed out after 60 seconds")
            return {
                'success': False,
                'error': 'Execution timeout (60s)',
                'stdout': '',
                'stderr': 'Timeout expired'
            }
        except Exception as e:
            print(f"[ERROR] Failed to execute code: {e}")
            self.logger.error(f"[{correlation_id}] Code Execution: Exception occurred - {e}")
            return {
                'success': False,
                'error': str(e),
                'stdout': '',
                'stderr': str(e)
            }
    
    async def _execute_steps_in_order(self, planning_plan: Dict, query: str, correlation_id: str) -> Dict[str, Any]:
        """
        Execute steps in the order specified by LLM1 plan with ExecutionManager pattern enhancements.
        
        Key enhancements:
        - Step context passing between steps
        - Dependency resolution 
        - Better error handling with critical/non-critical step support
        - Structured execution flow with proper data flow tracking
        """
        
        steps = planning_plan.get('plan', {}).get('steps', [])
        if not steps:
            print("[WARNING] No steps found in Planning plan")
            return {
                'sql_result': {'success': True, 'data': [], 'explanation': 'No steps to execute'},
                'filter_result': {'success': True, 'filtered_endpoints': [], 'filtered_endpoint_count': 0},
                'api_data': []
            }

        # ExecutionManager Enhancement: Initialize step execution context
        step_context = {
            'correlation_id': correlation_id,
            'original_query': query,
            'execution_start_time': datetime.now(),
            'completed_steps': {},
            'step_results': {},
            'accumulated_data': [],
            'errors': [],
            'data_flow': {}
        }

        print(f"[REFRESH] ENHANCED EXECUTION: {len(steps)} steps with context passing")
        for i, step in enumerate(steps, 1):
            tool_name = step.get('tool_name', '')
            query_context = step.get('query_context', '')
            critical = step.get('critical', False)
            print(f"   Step {i}: {tool_name} - {query_context} (Critical: {critical})")

        # Results for backward compatibility
        sql_result = {'success': True, 'data': [], 'explanation': 'No SQL steps executed'}
        filter_result = {'success': True, 'filtered_endpoints': [], 'filtered_endpoint_count': 0}
        api_data_collected = []

        # ExecutionManager Enhancement: Execute steps with context tracking
        for i, step in enumerate(steps, 1):
            step_start_time = time.time()
            tool_name = step.get('tool_name', '')
            query_context = step.get('query_context', '')
            critical = step.get('critical', False)
            
            print(f"\n[LIST] STEP {i}/{len(steps)}: {tool_name}")
            print(f"   Context: {query_context}")
            print(f"   Critical: {critical}")
            print(f"   Available Data: {len(step_context['accumulated_data'])} items")
            
            try:
                # ExecutionManager Enhancement: Context-aware step execution
                step_result = await self._execute_single_step_enhanced(
                    step, step_context, query, correlation_id, planning_plan
                )
                
                # Ensure step_result is a dictionary
                if not isinstance(step_result, dict):
                    step_result = {'success': False, 'error': str(step_result), 'data': []}
                
                # Update step context with results
                step_context['completed_steps'][str(i)] = step_result
                step_context['step_results'][f'step_{i}'] = step_result.get('data', [])
                
                # Track data flow
                step_time = time.time() - step_start_time
                step_context['data_flow'][f'step_{i}'] = {
                    'type': step_result.get('step_type', 'unknown'),
                    'tool': tool_name,
                    'execution_time_ms': int(step_time * 1000),
                    'success': step_result.get('success', False),
                    'data_count': len(step_result.get('data', []))
                }
                
                # Update legacy results (don't add to accumulated_data here - that's handled in _execute_single_step_enhanced)
                if step_result.get('step_type') == 'sql':
                    sql_result = step_result.get('result', sql_result)
                elif step_result.get('step_type') == 'api':
                    filter_result = step_result.get('result', filter_result)
                    if step_result.get('api_data'):
                        api_data_collected.extend(step_result['api_data'])
                
                print(f"   [SUCCESS] Step {i} completed in {step_time:.2f}s")
                
            except Exception as e:
                step_time = time.time() - step_start_time
                error_info = {
                    'step': i,
                    'tool_name': tool_name,
                    'error': str(e),
                    'execution_time': step_time,
                    'critical': critical
                }
                step_context['errors'].append(error_info)
                
                print(f"   [ERROR] Step {i} failed in {step_time:.2f}s: {str(e)}")
                
                if critical:
                    print(f"   � Critical step failed, halting execution")
                    break
                else:
                    print(f"   [WARNING] Non-critical step failed, continuing")
                    continue

        # ExecutionManager Enhancement: Execution summary
        total_time = (datetime.now() - step_context['execution_start_time']).total_seconds()
        print(f"\n[DATA] EXECUTION SUMMARY:")
        print(f"   [TIME] Total Time: {total_time:.2f}s")
        print(f"   [SUCCESS] Completed: {len(step_context['completed_steps'])}/{len(steps)}")
        print(f"   [ERROR] Errors: {len(step_context['errors'])}")
        print(f"   [DATA] Total Data: {len(step_context['accumulated_data'])} items")

        return {
            'sql_result': sql_result,
            'filter_result': filter_result,
            'api_data': api_data_collected,
            'execution_context': step_context,  # ExecutionManager Enhancement
            'enhanced': True
        }

    def _extract_sample_for_context(self, data: Any, variable_name: str, max_samples: int = MAX_SAMPLES_PER_STEP) -> Dict[str, Any]:
        """
        Extract a sample from data for context passing between steps.
        Based on ExecutionManager's intelligent sampling approach.
        
        Args:
            data: The full dataset to sample from
            variable_name: Name of the variable storing the full data
            max_samples: Maximum number of sample items to include
            
        Returns:
            Dict with sample data and metadata for LLM context
        """
        if not data:
            return {
                'variable_name': variable_name,
                'sample_data': [],
                'total_records': 0,
                'context_message': f"Variable {variable_name} contains no data"
            }
        
        # Handle lists - take first N items
        if isinstance(data, list):
            total_count = len(data)
            sample_data = data[:max_samples] if total_count > max_samples else data
            
            return {
                'variable_name': variable_name,
                'sample_data': sample_data,
                'total_records': total_count,
                'data_fields': list(sample_data[0].keys()) if sample_data and isinstance(sample_data[0], dict) else [],
                'context_message': f"Sample from {variable_name} (contains {total_count} total records)"
            }
        
        # Handle single records - wrap in list for consistency
        elif isinstance(data, dict):
            return {
                'variable_name': variable_name,
                'sample_data': [data],
                'total_records': 1,
                'data_fields': list(data.keys()),
                'context_message': f"Single record from {variable_name}"
            }
        
        # Handle other types
        else:
            return {
                'variable_name': variable_name,
                'sample_data': [str(data)],
                'total_records': 1,
                'data_fields': [],
                'context_message': f"Data from {variable_name} ({type(data).__name__})"
            }
    
    def _build_enhanced_context_for_llm(self, step_context: Dict, current_step_name: str) -> str:
        """
        Build enhanced context message for LLM with samples and variable names.
        This allows LLMs to understand data structure while knowing which variables contain full datasets.
        
        Args:
            step_context: Current step execution context
            current_step_name: Name of the current step being executed
            
        Returns:
            Formatted context string for LLM prompt
        """
        if not step_context.get('accumulated_data'):
            return ""
        
        context_parts = ["\n[LINK] CONTEXT FROM PREVIOUS STEPS:"]
        
        for item in step_context['accumulated_data']:
            # Ensure item is a dictionary, skip if it's not
            if not isinstance(item, dict):
                print(f"   [WARNING] Skipping non-dict item in accumulated_data: {type(item)} - {str(item)[:50]}...")
                continue
                
            variable_name = item.get('variable_name', 'unknown_variable')
            sample_data = item.get('sample_data', [])
            total_records = item.get('total_records', 0)
            step_name = item.get('step_name', 'unknown_step')
            data_fields = item.get('data_fields', [])
            
            context_parts.append(f"\n[DATA] Step {step_name}:")
            context_parts.append(f"   • Variable: {variable_name}")
            context_parts.append(f"   • Total Records: {total_records}")
            context_parts.append(f"   • Fields: {data_fields}")
            
            if sample_data and total_records > 0:
                # Show sample structure for LLM understanding
                if len(sample_data) <= 3:
                    context_parts.append(f"   • Sample Data:\n{json.dumps(sample_data, indent=6)}")
                else:
                    context_parts.append(f"   • Sample (first 3 records):\n{json.dumps(sample_data[:3], indent=6)}")
            
            # Key instruction for LLMs
            context_parts.append(f"   [WARNING]  IMPORTANT: Use variable '{variable_name}' in your code to process ALL {total_records} records")
        
        context_parts.append(f"\n[TARGET] Current Step: {current_step_name}")
        context_parts.append("[NOTE] INSTRUCTIONS: The samples above show data structure. Generate code that processes the FULL datasets stored in the named variables.")
        
        return "\n".join(context_parts)

    async def _execute_single_step_enhanced(self, step: Dict, step_context: Dict, query: str, 
                                          correlation_id: str, planning_plan: Dict = None) -> Dict:
        """
        Execute a single step with enhanced context tracking and sample-based data passing.
        Implements ExecutionManager patterns for variable management and context passing.
        """
        step_name = step.get('tool_name', f"Step_{len(step_context['completed_steps']) + 1}")
        step_type = self._determine_step_type_simple(step)
        
        print(f"   [TARGET] Executing {step_type.upper()} Step: {step_name}")
        
        try:
            if step_type == 'sql':
                print(f"   [SEARCH] DEBUG: About to execute SQL step")
                
                try:
                    # Use the step's query_context instead of the original user query
                    step_query = step.get('query_context', query)
                    print(f"   [SEARCH] DEBUG: Using step query_context: {step_query}")
                    
                    # Build enhanced context with samples and variable names
                    enhanced_context = self._build_enhanced_context_for_llm(step_context, step_name)
                    enhanced_query = f"{step_query}{enhanced_context}" if enhanced_context else step_query
                    
                    # Check if we have API data samples to enhance the SQL query
                    if step_context['accumulated_data']:
                        print(f"   [LINK] Using sample context from {len(step_context['accumulated_data'])} previous steps")
                        result = await self._execute_sql_queries(
                            planning_plan, enhanced_query, correlation_id, step_context['accumulated_data']
                        )
                    else:
                        result = await self._execute_sql_queries(planning_plan, enhanced_query, correlation_id)
                    
                    # Debug: Log result details
                    print(f"   [SEARCH] SQL result type: {type(result)}")
                    print(f"   [SEARCH] SQL result preview: {str(result)[:100]}...")
                    
                    # Ensure result is a dictionary
                    if not isinstance(result, dict):
                        print(f"   [WARNING] Converting non-dict result to error dict")
                        result = {'success': False, 'error': str(result), 'data': []}
                    
                    # Store SQL result with VARIABLE NAME and SAMPLE for next steps
                    if isinstance(result, dict) and result.get('success'):
                        sql_data = result.get('data', [])
                        print(f"   [SEARCH] SQL data type: {type(sql_data)}, length: {len(sql_data) if hasattr(sql_data, '__len__') else 'N/A'}")
                        
                        variable_name = f"sql_data_step_{len(step_context['completed_steps']) + 1}"
                        
                        # Store full dataset with named variable
                        step_context['data_variables'] = step_context.get('data_variables', {})
                        step_context['data_variables'][variable_name] = sql_data
                        
                        # Store metadata for future reference
                        step_context['sql_results'] = step_context.get('sql_results', [])
                        step_context['sql_results'].append({
                            'step_name': step_name,
                            'variable_name': variable_name,  # Key enhancement: variable name
                            'data': sql_data,  # Full data stored
                            'sample_data': sql_data[:5],  # Sample for context
                            'total_records': len(sql_data)
                        })
                        
                        # Add structured sample context for next steps
                        if sql_data:
                            sample_context = self._extract_sample_for_context(sql_data, variable_name)
                            sample_context.update({
                                'step_name': step_name,
                                'step_number': len(step_context['completed_steps']) + 1,
                                'step_type': 'sql'
                            })
                            step_context['accumulated_data'].append(sample_context)
                    
                    return {
                        'success': result.get('success', False),
                        'step_type': 'sql',
                        'result': result,
                        'data': result.get('data', [])
                    }
                    
                except Exception as sql_error:
                    print(f"   [ERROR] SQL step execution error: {sql_error}")
                    print(f"   [SEARCH] Error type: {type(sql_error)}")
                    import traceback
                    traceback.print_exc()
                    return {
                        'success': False,
                        'step_type': 'sql',
                        'error': str(sql_error),
                        'data': []
                    }
                
            else:  # API step
                # Execute endpoint filtering with the full Planning plan
                if planning_plan:
                    filter_result = await self._execute_endpoint_filtering(planning_plan, correlation_id)
                else:
                    print("[WARNING] No Planning plan available for endpoint filtering")
                    filter_result = {'success': False, 'error': 'No Planning plan available'}
                
                # Check if there are SQL steps after this that might need the API data
                total_steps = len(planning_plan.get('plan', {}).get('steps', [])) if planning_plan else 1
                current_step = len(step_context['completed_steps']) + 1
                has_dependent_steps = current_step < total_steps
                
                print(f"   [SEARCH] Dependency check: Step {current_step}/{total_steps}, Has dependent steps: {has_dependent_steps}")
                print(f"   [SEARCH] Filter result success: {filter_result.get('success')}")
                
                if has_dependent_steps and filter_result.get('success'):
                    print(f"   [LAUNCH] API→SQL workflow detected - executing API call for data collection")
                    
                    # Generate and execute code for this API step
                    api_llm2_result = await self._execute_llm2_code_generation(
                        {'entities': [step_name], 'steps_count': 1}, 
                        {'success': True, 'data': [], 'records_count': 0},
                        filter_result, 
                        step.get('query_context', ''), 
                        correlation_id
                    )
                    
                    if api_llm2_result.get('success') and api_llm2_result.get('code'):
                        # Execute the API call
                        api_execution_result = await self._execute_generated_code(
                            api_llm2_result['code'], 
                            correlation_id
                        )
                        
                        if api_execution_result.get('success'):
                            # Store the API data with variable name and sample
                            api_raw_output = api_execution_result.get('stdout', '')
                            variable_name = f"api_data_step_{len(step_context['completed_steps']) + 1}"
                            
                            # Store full API output with named variable
                            step_context['data_variables'] = step_context.get('data_variables', {})
                            step_context['data_variables'][variable_name] = api_raw_output
                            
                            # Try to extract structured data from API output for sampling
                            try:
                                import re
                                # Look for JSON arrays in the output
                                json_match = re.search(r'\[[\s\S]*\]', api_raw_output)
                                if json_match:
                                    api_data_list = json.loads(json_match.group(0))
                                    sample_context = self._extract_sample_for_context(api_data_list, variable_name)
                                else:
                                    # Fallback: treat as single data item
                                    sample_context = self._extract_sample_for_context(api_raw_output, variable_name)
                            except:
                                # Fallback: treat as raw string
                                sample_context = self._extract_sample_for_context(api_raw_output, variable_name)
                            
                            # Add API step metadata
                            sample_context.update({
                                'step_name': step_name,
                                'step_number': len(step_context['completed_steps']) + 1,
                                'step_type': 'api',
                                'execution_context': step.get('query_context', '')
                            })
                            
                            step_context['accumulated_data'].append(sample_context)
                            print(f"   [SUCCESS] API Step executed: stored variable {variable_name} with {len(api_raw_output)} chars")
                            
                            return {
                                'success': True,
                                'step_type': 'api',
                                'api_data': api_raw_output,  # Return raw output for legacy compatibility
                                'variable_name': variable_name,
                                'sample_context': sample_context  # Structured context for next steps
                            }
                        else:
                            return {'success': False, 'error': 'API execution failed'}
                    else:
                        return {'success': False, 'error': 'API code generation failed'}
                else:
                    print(f"   [SUCCESS] API Step completed: {filter_result.get('filtered_endpoint_count', 0)} endpoints")
                    return filter_result
                    
        except Exception as e:
            error_msg = f"Step execution failed: {str(e)}"
            print(f"   [ERROR] {error_msg}")
            step_context['errors'].append({
                'step_name': step_name,
                'error': error_msg,
                'step_type': step_type
            })
            return {'success': False, 'error': error_msg}

    def _determine_step_type_simple(self, step: Dict) -> str:
        """Simple step type determination"""
        tool_name = step.get('tool_name', '')
        query_context = step.get('query_context', '').upper()
        
        sql_tables = ['users', 'groups', 'applications', 'user_group_memberships', 
                     'user_application_assignments', 'group_application_assignments', 
                     'user_factors', 'devices', 'user_devices', 'policies', 'sync_history']
        
        if tool_name in sql_tables or query_context.startswith('SQL:'):
            return 'sql'
        else:
            return 'api'
    
    async def _export_results_to_csv(self, results: Dict[str, Any], query: str, correlation_id: str, step_results: Dict[str, Any] = None) -> str:
        """
        Export final results to CSV file in the results folder.
        
        Args:
            results: The processed results from LLM3
            query: Original user query
            correlation_id: Unique identifier for this execution
            
        Returns:
            Path to the exported CSV file
        """
        import csv
        import os
        from datetime import datetime
        import re
        
        try:
            # Create results directory if it doesn't exist - UNDER src/data
            results_dir = os.path.join(os.path.dirname(__file__), 'results')
            os.makedirs(results_dir, exist_ok=True)
            
            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_query = re.sub(r'[^\w\s-]', '', query.replace(' ', '_'))[:30]
            filename = f"okta_hybrid_results_{safe_query}_{timestamp}.csv"
            filepath = os.path.join(results_dir, filename)
            
            # Extract data for CSV export - PRIORITIZE SQL DATA FROM STEP_RESULTS
            rows_to_export = []
            sql_data = []
            
            print(f"[SEARCH] DEBUG: Looking for SQL data in step_results and raw_results...")
            
            # Method 1: Check step_results parameter first (most reliable)
            if step_results and 'sql_result' in step_results:
                sql_result = step_results['sql_result']
                if isinstance(sql_result, dict) and 'data' in sql_result:
                    sql_data = sql_result['data']
                    print(f"   Method 1 - step_results parameter: Found {len(sql_data)} records")
            
            # Method 2: Try sql_execution from raw_results (fallback)
            if not sql_data:
                raw_results = results.get('raw_results', {})
                print(f"   Raw results keys: {list(raw_results.keys()) if raw_results else 'None'}")
                
                sql_execution = raw_results.get('sql_execution', {})
                if sql_execution:
                    sql_data = sql_execution.get('data', [])
                    print(f"   Method 2 - sql_execution: Found {len(sql_data)} records")
            
            # Method 3: Try execution_result from raw_results
            if not sql_data and raw_results:
                execution_result = raw_results.get('execution_result', {})
                if execution_result and isinstance(execution_result, dict):
                    sql_data = execution_result.get('data', [])
                    print(f"   Method 3 - execution_result: Found {len(sql_data)} records")
            
            # Method 4: Try step results from the step context
            if not sql_data and raw_results:
                step_res_list = raw_results.get('step_results', [])
                if step_res_list:
                    for step in step_res_list:
                        if step.get('step_type') == 'sql' and step.get('data'):
                            sql_data = step.get('data', [])
                            print(f"   Method 4 - step_results: Found {len(sql_data)} records")
                            break
            
            # Method 5: Look in execution_summary (last resort)
            if not sql_data and raw_results:
                exec_summary = raw_results.get('execution_summary', {})
                if exec_summary:
                    sql_data = exec_summary.get('sql_data', [])
                    print(f"   Method 5 - execution_summary: Found {len(sql_data)} records")
                    
            print(f"[SEARCH] Final SQL data found: {len(sql_data)} records")
            
            # Check for LLM3 processed results first (new aggregated format)
            processed_summary = results.get('processed_summary', {})
            if isinstance(processed_summary, dict) and processed_summary.get('display_type') == 'table':
                llm3_content = processed_summary.get('content', [])
                if llm3_content and isinstance(llm3_content, list) and len(llm3_content) > 0:
                    print(f"[FILE] Exporting {len(llm3_content)} LLM3 aggregated records to CSV...")
                    
                    # Use CSV headers from metadata if available, or intelligently select fields
                    csv_headers = []
                    metadata = processed_summary.get('metadata', {})
                    if metadata.get('csv_headers'):
                        csv_headers = [h['value'] for h in metadata['csv_headers']]
                    else:
                        # Fallback: intelligently select all relevant fields from first record
                        first_record = llm3_content[0]
                        priority_fields = ['okta_id', 'name', 'first_name', 'last_name', 'email', 'status']
                        for field in priority_fields:
                            if field in first_record:
                                csv_headers.append(field)
                        
                        # Add CSV-friendly fields if available, otherwise use regular fields
                        for key in first_record.keys():
                            if key.endswith('_csv') or key.endswith('_count'):
                                csv_headers.append(key)
                            elif key in ['groups', 'applications'] and key not in csv_headers:
                                csv_headers.append(key)  # Include groups/applications even if not CSV format
                    
                    # Add metadata columns
                    csv_headers.extend(['query', 'correlation_id', 'timestamp', 'processing_method'])
                    
                    # Write CSV with LLM3 aggregated data
                    with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
                        writer = csv.DictWriter(csvfile, fieldnames=csv_headers)
                        writer.writeheader()
                        
                        for row in llm3_content:
                            # Add metadata to each row
                            export_row = {}
                            for header in csv_headers:
                                if header in ['query', 'correlation_id', 'timestamp', 'processing_method']:
                                    continue  # Handle metadata separately
                                export_row[header] = row.get(header, '')
                            
                            # Add metadata
                            export_row.update({
                                'query': query,
                                'correlation_id': correlation_id,
                                'timestamp': datetime.now().isoformat(),
                                'processing_method': results.get('processing_method', 'llm3_aggregated')
                            })
                            writer.writerow(export_row)
                            
                    print(f"[SUCCESS] Exported {len(llm3_content)} LLM3 aggregated records to: {filepath}")
                    return filepath
            
            # Fallback to SQL data if LLM3 processed format not available
            if sql_data and isinstance(sql_data, list) and len(sql_data) > 0:
                # Use SQL data as primary export - THIS IS THE REAL DATA!
                print(f"[FILE] Exporting {len(sql_data)} SQL records to CSV...")
                
                # Get column headers from first record
                if isinstance(sql_data[0], dict):
                    headers = list(sql_data[0].keys())
                    
                    # Add metadata columns
                    headers.extend(['query', 'correlation_id', 'timestamp', 'processing_method'])
                    
                    # Write CSV with ACTUAL SQL DATA
                    with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
                        writer = csv.DictWriter(csvfile, fieldnames=headers)
                        writer.writeheader()
                        
                        for row in sql_data:
                            # Add metadata to each row
                            export_row = row.copy()
                            export_row.update({
                                'query': query,
                                'correlation_id': correlation_id,
                                'timestamp': datetime.now().isoformat(),
                                'processing_method': results.get('processing_method', 'unknown')
                            })
                            writer.writerow(export_row)
                            
                    print(f"[SUCCESS] Exported {len(sql_data)} SQL records to: {filepath}")
                    return filepath
            
            # Fallback: Export processed summary as text-based CSV
            processed_summary = results.get('processed_summary', {})
            content = processed_summary.get('content', '') if isinstance(processed_summary, dict) else str(processed_summary)
            
            # Create a simple CSV with summary data
            headers = ['timestamp', 'query', 'correlation_id', 'processing_method', 'content_type', 'content']
            
            with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=headers)
                writer.writeheader()
                
                writer.writerow({
                    'timestamp': datetime.now().isoformat(),
                    'query': query,
                    'correlation_id': correlation_id,
                    'processing_method': results.get('processing_method', 'unknown'),
                    'content_type': processed_summary.get('display_type', 'text') if isinstance(processed_summary, dict) else 'text',
                    'content': content[:1000] + '...' if len(content) > 1000 else content
                })
            
            print(f"[SUCCESS] Exported summary to: {filepath}")
            return filepath
            
        except Exception as e:
            print(f"[ERROR] CSV export failed: {e}")
            return None

# Test function
async def test_real_execution():
    """Test the real execution with a sample query"""
    
    print("🧪 TESTING REAL WORLD HYBRID EXECUTOR")
    print("=" * 70)
    
    executor = RealWorldHybridExecutor()
    
    # First verify all data is loaded correctly
    verification_result = executor.verify_loaded_data()
    
    if not verification_result['files_status']['api_data']:
        print("[ERROR] API data file not found - cannot proceed")
        return {'success': False, 'error': 'API data file missing'}
    
    if not verification_result['files_status']['schema']:
        print("[ERROR] Schema file not found - cannot proceed")
        return {'success': False, 'error': 'Schema file missing'}
    
    # Test query that should trigger both SQL and API operations  
    test_query = "find users in group [GROUP_NAME] and get their applications and roles"
    
    result = await executor.execute_query(test_query)
    
    print(f"\n[TARGET] FINAL TEST RESULT:")
    print(f"[SUCCESS] Success: {result.get('success')}")
    if result.get('success'):
        print(f"[DATA] SQL Records: {result.get('sql_execution', {}).get('records_count', 0)}")
        print(f"[SEARCH] API Endpoints: {result.get('endpoint_filtering', {}).get('filtered_count', 0)}")
        print(f"[TARGET] Entities: {result.get('execution_summary', {}).get('entities_involved', [])}")
        print(f"[BOT] Code Generated: {result.get('llm2_code_generation', {}).get('success', False)}")
        print(f"� Code Length: {result.get('llm2_code_generation', {}).get('code_length', 0)}")
        print(f"�[LAUNCH] Ready for Execution: {result.get('execution_summary', {}).get('ready_for_execution', False)}")
    else:
        print(f"[ERROR] Error: {result.get('error')}")
    
    return result

if __name__ == "__main__":
    asyncio.run(test_real_execution())