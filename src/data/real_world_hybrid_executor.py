"""
Real-world Hybrid Executor for Okta AI Agent.
Based on test_streamlined_pipeline.py logic - NO MOCKS!

This executor:
1. Uses LLM1 to generate execution plans (real ExecutionPlanResponse)
2. Uses SQL agent for database queries (real SQL execution)
3. Uses endpoint filtering for LLM2 (real API endpoints)
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

# Import real components
try:
    from src.core.helpers.okta_generate_sql import sql_agent, SQLDependencies, extract_json_from_text
    print("SQL agent imported successfully")
except ImportError as e:
    print(f"❌ Failed to import SQL agent: {e}")
    sql_agent = None

# Constants for sampling and results processing (inspired by ExecutionManager)
MAX_CHARS_FOR_FULL_RESULTS = 60000
MAX_SAMPLES_PER_STEP = 5

class ExecutionPlanResponse(BaseModel):
    """LLM1 response matching the existing ExecutionPlan format"""
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
    def validate_llm1_response(response: Dict, available_entities: List[str], entity_summary: Dict) -> Dict:
        """Validate LLM1 response in ExecutionPlan format against available entities"""
        plan = response.get('plan', {})
        steps = plan.get('steps', [])
        
        if not steps:
            raise ValidationError("LLM1 RESPONSE INVALID - No steps provided in plan")
        
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
            raise ValidationError(f"LLM1 HALLUCINATION DETECTED - Invalid entities: {invalid_entities}. Must use API entities: {api_entities[:5]}... or SQL tables: {sql_tables[:5]}...")
        
        # 2. Validate each step has required fields
        for i, step in enumerate(steps):
            required_fields = ['tool_name', 'query_context', 'critical', 'reason']
            missing_fields = [field for field in required_fields if field not in step]
            if missing_fields:
                raise ValidationError(f"LLM1 STEP {i+1} INVALID - Missing fields: {missing_fields}")
        
        print(f"✅ LLM1 VALIDATION PASSED - {len(api_steps)} API steps, {len(sql_steps)} SQL steps")
        
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
    
    def filter_endpoints(self, llm1_plan: ExecutionPlanResponse) -> Dict[str, Any]:
        """Filter endpoints based on LLM1's explicit entity+operation specifications"""
        steps = llm1_plan.plan.get('steps', [])
        
        # Extract entities and operations DIRECTLY from LLM1's explicit specifications
        api_entities = []
        operations = []
        
        print(f"🔍 EXTRACTING ENTITIES AND OPERATIONS FROM LLM1 PLAN:")
        for i, step in enumerate(steps, 1):
            tool_name = step.get('tool_name', '').lower()
            operation = step.get('operation', '')
            query_context = step.get('query_context', '')
            
            # Check if this is an API step (has operation specified)
            if operation and tool_name in self.entity_summary:
                api_entities.append(tool_name)
                operations.append(operation.lower())
                print(f"   Step {i}: entity='{tool_name}', operation='{operation}'")
            else:
                print(f"   Step {i}: SQL step '{tool_name}' (no operation filtering needed)")
        
        # Remove duplicates
        entities = list(set(api_entities))
        operations = list(set(operations))
        methods = ['GET']  # Default to GET for most operations
        
        print(f"🎯 PRECISE FILTERING (API STEPS ONLY)")
        print(f"   Entities: {entities}")
        print(f"   Operations: {operations}")
        print(f"   Methods: {methods}")
        
        if not entities:
            print("   ℹ️ No API entities found - all steps are SQL")
            return {
                'success': True,
                'filtered_endpoints': [],
                'entity_results': {},
                'total_endpoints': 0,
                'llm1_plan': llm1_plan.model_dump()
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
                print(f"   ✅ {entity}: {len(selected)} endpoints selected (from {len(entity_endpoints)} matches)")
                for ep in selected:
                    print(f"      • {ep['method']} {ep['url_pattern']} - {ep['name']}")
            else:
                entity_results[entity] = {'found': 0, 'selected': 0, 'endpoints': []}
                print(f"   ❌ {entity}: No matching endpoints")
        
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
            'llm1_plan': llm1_plan.model_dump()
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
    NO MOCKS - only real LLM1, real SQL, real endpoint filtering
    """
    
    def __init__(self):
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
        
        print("🚀 RealWorldHybridExecutor initialized")
        print(f"   📁 DB Path: {self.db_path}")
        print(f"   📁 API Data: {self.api_data_path}")
        print(f"   📁 Schema: {self.schema_path}")
        print(f"   📊 Entities loaded: {len(self.api_data.get('entity_summary', {}))}")
        print(f"   🗃️ Tables loaded: {len(self.db_schema.get('sql_tables', {}))}")
    
    def _initialize_model_config(self):
        """Initialize and log model configuration"""
        try:
            ai_provider = os.getenv('AI_PROVIDER', 'openai').lower()
            models = ModelConfig.get_models()
            
            print(f"🤖 Model Configuration:")
            print(f"   🎯 AI Provider: {ai_provider}")
            print(f"   🧠 LLM1 (Reasoning): {models[ModelType.REASONING]}")
            print(f"   💻 LLM2 (Coding): {models[ModelType.CODING]}")
            
            # Store models for easy access
            self.reasoning_model = models[ModelType.REASONING]
            self.coding_model = models[ModelType.CODING]
            
        except Exception as e:
            print(f"⚠️ Model configuration warning: {e}")
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
            
            print(f"✅ Loaded API data: {endpoints_count} endpoints, {entity_count} entities")
            
            # Log entity summary for verification
            entities = list(api_data.get('entity_summary', {}).keys())
            print(f"   🏷️ Available entities: {entities[:10]}{'...' if len(entities) > 10 else ''}")
            
            return api_data
        except Exception as e:
            print(f"❌ Failed to load API data: {e}")
            return {'endpoints': [], 'entity_summary': {}}
    
    def _load_db_schema(self) -> Dict:
        """Load database schema for SQL operations"""
        try:
            with open(self.schema_path, 'r') as f:
                schema_data = json.load(f)
            
            tables_count = len(schema_data.get('sql_tables', {}))
            print(f"✅ Loaded DB schema: {tables_count} tables")
            
            # Log table names for verification
            tables = list(schema_data.get('sql_tables', {}).keys())
            print(f"   🗃️ Available tables: {tables}")
            
            return schema_data
        except Exception as e:
            print(f"❌ Failed to load DB schema: {e}")
            return {'sql_tables': {}}
    
    def verify_loaded_data(self):
        """Verify that all required data is loaded correctly"""
        print("\n🔍 VERIFYING LOADED DATA")
        print("=" * 50)
        
        # Verify API data
        api_entities = list(self.api_data.get('entity_summary', {}).keys())
        api_endpoints = self.api_data.get('endpoints', [])
        
        print(f"📊 API Data:")
        print(f"   🏷️ Entities: {len(api_entities)}")
        print(f"   🔗 Endpoints: {len(api_endpoints)}")
        
        if api_entities:
            print(f"   📋 Sample entities: {api_entities[:5]}")
            
            # Show sample entity details
            sample_entity = api_entities[0]
            entity_details = self.api_data['entity_summary'][sample_entity]
            print(f"   🔍 Sample '{sample_entity}' operations: {entity_details.get('operations', [])[:3]}")
        
        # Verify DB schema
        db_tables = list(self.db_schema.get('sql_tables', {}).keys())
        
        print(f"🗃️ Database Schema:")
        print(f"   📋 Tables: {len(db_tables)}")
        
        if db_tables:
            print(f"   🔍 Available tables: {db_tables}")
            
            # Show sample table details
            sample_table = db_tables[0]
            table_details = self.db_schema['sql_tables'][sample_table]
            columns = table_details.get('columns', [])
            print(f"   📊 Sample '{sample_table}' columns: {columns[:5]}{'...' if len(columns) > 5 else ''}")
        
        # Verify files exist
        api_exists = os.path.exists(self.api_data_path)
        schema_exists = os.path.exists(self.schema_path)
        db_exists = os.path.exists(self.db_path)
        
        print(f"📁 File Status:")
        print(f"   {'✅' if api_exists else '❌'} API Data: {self.api_data_path}")
        print(f"   {'✅' if schema_exists else '❌'} Schema: {self.schema_path}")
        print(f"   {'✅' if db_exists else '❌'} Database: {self.db_path}")
        
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
        1. LLM1 generates execution plan
        2. SQL queries based on steps  
        3. Endpoint filtering for LLM2
        4. Return combined results
        """
        
        print(f"\n🚀 EXECUTING REAL HYBRID QUERY")
        print(f"=" * 60)
        print(f"📝 Query: {query}")
        
        correlation_id = f"hybrid_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        try:
            # Phase 1: LLM1 Planning (REAL)
            print(f"\n🧠 PHASE 1: LLM1 PLANNING")
            print("=" * 50)
            
            llm1_result = await self._execute_llm1_planning(query, correlation_id)
            if not llm1_result or not llm1_result.get('success'):
                return {'success': False, 'error': 'LLM1 planning failed', 'correlation_id': correlation_id}
            
            llm1_plan = llm1_result['llm1_plan']
            
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
            print(f"\n🔍 LLM2 DECISION LOGIC:")
            print(f"   📋 SQL result exists: {step_results.get('sql_result') is not None}")
            print(f"   ✅ SQL success: {sql_result.get('success')}")
            print(f"   📊 SQL data count: {len(sql_result.get('data', []))}")
            print(f"   🎯 Has SQL data: {has_sql_data}")
            print(f"   🔗 API endpoints: {has_api_endpoints}")
            print(f"   📝 LLM2 condition (has_api_endpoints and not has_sql_data): {has_api_endpoints and not has_sql_data}")
            
            # Only run LLM2 if we have API endpoints but no complete SQL data
            # Skip LLM2 if we already have complete results from SQL
            llm2_result = {'success': False, 'code': '', 'explanation': 'Skipped - using direct SQL results'}
            
            if has_api_endpoints and not has_sql_data:
                print(f"\n🤖 PHASE 4: LLM2 CODE GENERATION")
                print("=" * 50)
                print("🎯 Generating API code for endpoints without SQL data")
                
                llm2_result = await self._execute_llm2_code_generation(
                    llm1_result, sql_result, filter_result, query, correlation_id, api_data_collected
                )
            else:
                print(f"\n⏭️ PHASE 4: SKIPPING LLM2 CODE GENERATION")
                print("=" * 50)
                if has_sql_data:
                    print("✅ Complete SQL data available - proceeding directly to results processing")
                else:
                    print("ℹ️ No API endpoints to process")
            
            # Phase 5: Execute Generated Code (only if LLM2 generated code)
            execution_result = None
            if llm2_result.get('success') and llm2_result.get('code'):
                print(f"\n🚀 PHASE 5: CODE EXECUTION")
                print("=" * 50)
                
                execution_result = await self._execute_generated_code(
                    llm2_result['code'], correlation_id
                )
            else:
                print(f"\n⏭️ PHASE 5: SKIPPING CODE EXECUTION")
                print("=" * 50)
                print("ℹ️ No code generated by LLM2 - using step results directly")
                execution_result = {'success': True, 'stdout': 'No code execution needed', 'stderr': ''}
            
            # Phase 6: Results Combination
            print(f"\n🎯 PHASE 6: RESULTS COMBINATION")
            print("=" * 50)
            
            final_result = await self._combine_results(llm1_result, sql_result, filter_result, llm2_result, correlation_id)
            
            # Add execution results to final result
            if execution_result:
                final_result['execution_result'] = execution_result
            
            # Phase 7: Enhanced Results Processing with LLM3 (NEW!)
            print(f"\n🧠 PHASE 7: LLM3 RESULTS PROCESSING")
            print("=" * 50)
            
            try:
                enhanced_final_result = await self._process_final_results_with_llm3(
                    combined_results=final_result,
                    original_query=query,
                    execution_result=execution_result,
                    step_context=step_results.get('execution_context', {})  # Pass step context
                )
                
                print(f"✅ LLM3 processing completed successfully")
                
                # Export results to CSV file
                csv_file = await self._export_results_to_csv(enhanced_final_result, query, correlation_id, step_results)
                if csv_file:
                    enhanced_final_result['csv_export_path'] = csv_file
                
                final_result = enhanced_final_result
                
            except Exception as llm3_error:
                print(f"⚠️ LLM3 processing failed: {llm3_error}")
                print(f"🔄 Continuing with basic results...")
                # Keep the original final_result if LLM3 fails
            
            print(f"\n✅ HYBRID EXECUTION COMPLETED!")
            print(f"   📊 LLM1 Steps: {len(llm1_plan.get('plan', {}).get('steps', []))}")
            print(f"   💾 SQL Results: {len(sql_result.get('data', []))} records")
            print(f"   🔍 Filtered Endpoints: {filter_result.get('filtered_endpoint_count', 0)}")
            print(f"   🤖 LLM2 Code Generated: {llm2_result.get('success', False)}")
            print(f"   📝 Code Length: {len(llm2_result.get('code', ''))} characters")
            print(f"   🚀 Code Executed: {execution_result.get('success', False) if execution_result else False}")
            
            # Enhanced execution summary with LLM3 info
            processing_method = final_result.get('processing_method', 'basic_combination')
            enhancement_features = final_result.get('enhancement_features', {})
            print(f"   📋 Results Processing: {processing_method}")
            if enhancement_features.get('pandas_analytics'):
                print(f"   📊 Pandas Analytics: ✅ Enabled")
                print(f"   📈 Data Insights: ✅ Generated")
                print(f"   📉 Visualizations: ✅ Suggested")
            
            # Export results to CSV
            csv_path = await self._export_results_to_csv(final_result, query, correlation_id, step_results)
            if csv_path:
                print(f"📤 Results exported to CSV: {csv_path}")
            
            return final_result
            
        except Exception as e:
            print(f"❌ Hybrid execution failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False, 
                'error': str(e), 
                'correlation_id': correlation_id,
                'phase': 'execution'
            }
    
    async def _execute_llm1_planning(self, query: str, correlation_id: str) -> Dict[str, Any]:
        """Execute LLM1 planning phase using REAL LLM with existing system prompt (following test_streamlined_pipeline pattern)
        
        VALIDATION APPROACH:
        - LLM1 can suggest both SQL operations (using table names) and API operations (using entity names)
        - SQL steps: tool_name in ['users', 'groups', 'applications', etc.] → go to SQL agent
        - API steps: tool_name in ['user', 'group', 'application', etc.] → go to endpoint filtering
        - Only validate that tool_name is either a valid SQL table OR a valid API entity
        """
        
        # Get available entities and build system prompt DYNAMICALLY (following test_streamlined_pipeline.py)
        available_entities = list(self.api_data.get('entity_summary', {}).keys())
        entity_summary = self.api_data.get('entity_summary', {})
        
        print(f"🔍 Building LLM1 system prompt with {len(available_entities)} entities")
        
        # Load existing system prompt (like test_streamlined_pipeline.py)
        system_prompt_path = os.path.join(os.path.dirname(__file__), "llm1_system_prompt.txt")
        with open(system_prompt_path, 'r', encoding='utf-8') as f:
            base_system_prompt = f.read()
        
        # Build dynamic entity operations text (exactly like test_streamlined_pipeline.py)
        entity_operations_text = []
        for entity, details in entity_summary.items():
            operations = details.get('operations', [])
            methods = details.get('methods', [])
            entity_operations_text.append(f"  • {entity}: operations=[{', '.join(operations)}], methods=[{', '.join(methods)}]")
        
        entities_with_operations = "\n".join(entity_operations_text)
        
        # Build SQL schema context dynamically from actual schema data
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
        
        sql_info = f"""
SQL DATABASE SCHEMA (actual schema data):
Available Tables: {', '.join(sql_table_names)}

{chr(10).join(sql_schema_details)}

KEY INSIGHT: Look at the actual columns and operations above to determine what data IS or IS NOT available in SQL.
- If you see columns like 'user_okta_id', 'app_okta_id', 'factor_type' → that data is available in SQL
- If you don't see role-related columns → that data requires API calls
- Use table names as tool_name for SQL operations, API entity names for non-SQL operations"""
        
        # Update system prompt preserving HYBRID STRATEGY section
        import re
        entities_section = f"AVAILABLE ENTITIES AND OPERATIONS:\n{entities_with_operations}"
        complete_section = f"{entities_section}\n{sql_info}"
        
        # Look for the specific AVAILABLE ENTITIES list (not HYBRID sections)
        pattern = r'AVAILABLE ENTITIES:\nYou can use these exact entity names.*?(?=\n\nEXAMPLES|\nCRITICAL|\nCOMPLETE|$)'
        
        if re.search(pattern, base_system_prompt, flags=re.DOTALL):
            updated_system_prompt = re.sub(pattern, complete_section, base_system_prompt, flags=re.DOTALL)
            print(f"✅ Updated AVAILABLE ENTITIES section with dynamic content")
        else:
            # Fallback: append without replacing hybrid strategy
            updated_system_prompt = base_system_prompt + f"\n\n{complete_section}"
            print(f"⚠️ Appended dynamic content to preserve HYBRID STRATEGY")
        
        print(f"📝 System prompt built with:")
        print(f"   🏷️ {len(available_entities)} entities")
        print(f"   🗃️ {len(sql_tables)} SQL tables")
        print(f"   📋 Sample entities: {available_entities[:5]}")
        
        # Create LLM1 agent (like test_streamlined_pipeline.py) using reasoning model
        reasoning_model = self.reasoning_model if self.reasoning_model else ModelConfig.get_model(ModelType.REASONING)
        llm1_agent_raw = Agent(
            model=reasoning_model,
            system_prompt=updated_system_prompt
            # No result_type for raw response
        )
        
        print(f"🔄 Running LLM1 planning...")
        
        # Get raw response (like test_streamlined_pipeline.py)
        raw_result = await llm1_agent_raw.run(query)
        raw_output = raw_result.output
        print(f"🔍 Raw LLM1 output type: {type(raw_output)}")
        
        # Parse the raw output (like test_streamlined_pipeline.py)
        if isinstance(raw_output, str):
            try:
                # Use extract_json_from_text to handle markdown code blocks
                llm1_output_dict = extract_json_from_text(raw_output)
            except Exception as e:
                print(f"❌ Failed to parse LLM1 JSON output: {e}")
                print(f"Raw output: {raw_output[:500]}...")
                return {'success': False, 'error': f'LLM1 JSON parse error: {e}'}
        else:
            llm1_output_dict = raw_output
        
        # Create validated response object (like test_streamlined_pipeline.py)
        try:
            llm1_output = ExecutionPlanResponse(**llm1_output_dict)
        except Exception as e:
            print(f"❌ Failed to validate LLM1 response: {e}")
            print(f"Response was: {llm1_output_dict}")
            return {'success': False, 'error': f'LLM1 validation error: {e}'}
        
        # Validate LLM1 response using our updated validation logic
        print("🔍 VALIDATING LLM1 RESPONSE...")
        try:
            # Call our static validation method correctly - it's in StrictValidator, not ValidationError
            validated_response = StrictValidator.validate_llm1_response(
                llm1_output.model_dump(), 
                available_entities, 
                entity_summary
            )
        except ValidationError as ve:
            print(f"❌ LLM1 VALIDATION FAILED: {ve}")
            return {'success': False, 'error': f'LLM1 validation failed: {ve}'}
        except Exception as e:
            print(f"❌ VALIDATION ERROR: {e}")
            return {'success': False, 'error': f'Validation error: {e}'}
        
        # Display plan details
        print(f"📋 LLM1 PLAN:")
        steps = llm1_output.plan.get('steps', [])
        entities = list(set([step.get('tool_name', '') for step in steps]))
        print(f"🎯 Entities: {entities}")
        print(f"📋 Steps: {len(steps)} steps planned")
        print(f"🧠 Reasoning: {llm1_output.plan.get('reasoning', '')}")
        print(f"🎯 Confidence: {llm1_output.confidence}%")
        
        # Show individual steps
        for i, step in enumerate(steps, 1):
            print(f"   Step {i}: {step.get('tool_name', '')} - {step.get('query_context', '')}")
            print(f"           Critical: {step.get('critical', False)}, Reason: {step.get('reason', '')}")
        
        return {
            'success': True,
            'llm1_plan': llm1_output.model_dump(),
            'entities': entities,
            'correlation_id': correlation_id
        }
    
    async def _execute_sql_queries(self, llm1_plan: Dict, query: str, correlation_id: str, api_context: List = None) -> Dict[str, Any]:
        """Execute SQL queries with optional API context data"""
        
        if not sql_agent:
            print("❌ SQL agent not available")
            return {'success': False, 'error': 'SQL agent not available', 'data': []}
        
        print(f"💾 Executing SQL queries...")
        print(f"   🔍 DEBUG: Starting SQL execution")
        
        try:
            # Use the real SQL agent with proper tenant_id
            sql_dependencies = SQLDependencies(tenant_id="default")
            
            # Build context query if API context is provided
            context_query = query
            if api_context:
                context_query = f"{query}\n\nCONTEXT FROM PREVIOUS STEPS:\n"
                for api_item in api_context:
                    if 'sample_data' in api_item:
                        # Extract user IDs from API events for SQL agent
                        sample_data = api_item['sample_data'][:MAX_SAMPLES_PER_STEP]  # Use proper sampling
                        
                        # For system log or any other data, use standard format and let LLM decide what to extract
                        context_query += f"📊 Step {api_item.get('step_name', 'unknown')}:\n"
                        context_query += f"   • Variable: {api_item.get('variable_name', 'unknown_variable')}\n"
                        context_query += f"   • Total Records: {api_item.get('total_records', len(sample_data))}\n"
                        context_query += f"   • Fields: {api_item.get('data_fields', [])}\n"
                        context_query += f"   • Sample Data:\n{json.dumps(sample_data, indent=6)}\n"
                        context_query += f"   ⚠️  IMPORTANT: Use variable '{api_item.get('variable_name', 'unknown_variable')}' in your code to process ALL {api_item.get('total_records', len(sample_data))} records\n\n"
            
            print(f"🔍 DEBUG: Starting SQL execution")
            print(f"💬 FULL QUERY TEXT PASSED TO SQL AGENT:")
            print("=" * 80)
            print(context_query)
            print("=" * 80)
            sql_result = await sql_agent.run(context_query, deps=sql_dependencies)
            
            # Extract JSON from the SQL agent response
            try:
                sql_response_json = extract_json_from_text(str(sql_result.output))
                sql_query = sql_response_json.get('sql', '')
                explanation = sql_response_json.get('explanation', '')
                
                print(f"🔍 DEBUG: Generated FULL SQL Query:")
                print(f"   {sql_query}")
                print(f"📝 SQL Explanation: {explanation}")
                print(f"🔍 DEBUG: SQL Query Length: {len(sql_query)} characters")
                
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
                    print("⚠️ SQL agent returned empty query")
                    return {'success': False, 'error': 'Empty SQL query generated', 'explanation': explanation, 'data': []}
                    
            except Exception as e:
                print(f"❌ Failed to parse SQL agent response: {e}")
                return {'success': False, 'error': f'SQL parsing error: {e}', 'data': []}
                
        except Exception as e:
            print(f"❌ SQL execution failed: {e}")
            return {'success': False, 'error': str(e), 'data': []}

    async def _execute_raw_sql_query(self, sql_query: str, correlation_id: str) -> List[Dict]:
        """Execute raw SQL query against the database and return results"""
        
        print(f"🗃️ Executing SQL query against database...")
        
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
            
            print(f"✅ SQL query executed successfully: {len(data)} records returned")
            if data:
                print(f"📊 Sample record keys: {list(data[0].keys())}")
            
            return data
            
        except Exception as e:
            print(f"❌ Database query failed: {e}")
            return []
    
    async def _execute_endpoint_filtering(self, llm1_plan: Dict, correlation_id: str) -> Dict[str, Any]:
        """Execute endpoint filtering based on LLM1 plan using REAL filtering logic"""
        
        print(f"🔍 Filtering endpoints based on LLM1 plan...")
        
        try:
            # Create ExecutionPlanResponse from the plan
            llm1_output = ExecutionPlanResponse(**llm1_plan)
            
            # Use the real endpoint filter
            filter_engine = PreciseEndpointFilter(self.api_data)
            filter_results = filter_engine.filter_endpoints(llm1_output)
            
            print(f"📊 FILTERING RESULTS:")
            print(f"📈 Original endpoints: {filter_results['original_endpoint_count']}")
            print(f"📉 Filtered endpoints: {filter_results['filtered_endpoint_count']}")
            print(f"🎯 Reduction: {filter_results['reduction_percentage']}%")
            
            # Add explicit success indicator for downstream processing
            filter_results['success'] = True
            
            return filter_results
            
        except Exception as e:
            print(f"❌ Endpoint filtering failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False, 
                'error': str(e),
                'filtered_endpoint_count': 0,
                'filtered_endpoints': []
            }
    
    async def _execute_llm2_code_generation(self, llm1_result: Dict, sql_result: Dict, filter_result: Dict, query: str, correlation_id: str, api_data_collected: List = None) -> Dict[str, Any]:
        """Execute LLM2 code generation phase using SQL data + filtered endpoints"""
        
        # Prepare data for LLM2 first
        sql_data = sql_result.get('data', [])
        filtered_endpoints = filter_result.get('filtered_endpoints', [])
        
        print(f"🤖 Generating Python code with SQL data + API endpoints...")
        print(f"📊 LLM2 Context Summary:")
        print(f"   💾 SQL Records: {len(sql_data)}")
        print(f"   🔗 API Endpoints: {len(filtered_endpoints)}")
        
        # Log endpoint details for verification
        for i, ep in enumerate(filtered_endpoints, 1):
            print(f"   📋 Endpoint {i}: {ep.get('method', '')} {ep.get('url_pattern', '')}")
            print(f"      • Name: {ep.get('name', '')}")
            print(f"      • Entity: {ep.get('entity', '')}, Operation: {ep.get('operation', '')}")
            req_params = ep.get('parameters', {}).get('required', [])
            opt_params = ep.get('parameters', {}).get('optional', [])
            print(f"      • Required: {req_params}")
            print(f"      • Optional: {opt_params}")
            print(f"      • Description: {ep.get('description', '')[:100]}...")
        
        
        if not sql_data and not filtered_endpoints:
            print("⚠️ No SQL data or API endpoints available for code generation")
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
            'entities_involved': llm1_result.get('entities', [])
        }
        
        # Load LLM2 system prompt from file
        llm2_prompt_path = os.path.join(os.path.dirname(__file__), "llm2_system_prompt.txt")
        try:
            with open(llm2_prompt_path, 'r', encoding='utf-8') as f:
                base_llm2_prompt = f.read()
        except FileNotFoundError:
            print(f"⚠️ llm2_system_prompt.txt not found at {llm2_prompt_path}, using fallback prompt")
            base_llm2_prompt = "You are LLM2, a Python code generator for Okta operations. Generate working Python code that combines SQL data with API calls."
        
        # Create dynamic LLM2 system prompt with context
        # Extract Step 2 description for LLM2 context
        llm1_plan = llm1_result.get('llm1_plan', {}).get('plan', {})
        steps = llm1_plan.get('steps', [])
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
- Entities: {llm1_result.get('entities', [])}

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
            
            print(f"🔄 Running LLM2 code generation...")
            
            # Generate code
            llm2_raw_result = await llm2_agent.run(
                f"Generate Python code for: {step2_description}\n\nSQL Data Structure: {list(sql_data[0].keys()) if sql_data else []}\nAPI Endpoints: {len(filtered_endpoints)} available"
            )
            
            llm2_output = llm2_raw_result.output
            print(f"🔍 LLM2 output type: {type(llm2_output)}")
            
            # Parse LLM2 response - should be LLM2CodeResponse object
            if isinstance(llm2_output, LLM2CodeResponse):
                # Direct Pydantic model response
                python_code = llm2_output.python_code
                explanation = llm2_output.explanation
                requirements = llm2_output.requirements
                print(f"✅ Successfully parsed LLM2 Pydantic response")
            elif isinstance(llm2_output, str):
                try:
                    # Fallback: try to parse JSON manually
                    llm2_response = json.loads(llm2_output)
                    python_code = llm2_response.get('python_code', '')
                    explanation = llm2_response.get('explanation', '')
                    requirements = llm2_response.get('requirements', [])
                    print(f"✅ Successfully parsed LLM2 JSON response")
                except json.JSONDecodeError as e:
                    print(f"❌ LLM2 returned invalid JSON: {e}")
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
            
            print(f"✅ LLM2 code generation completed")
            print(f"📝 Code length: {len(python_code)} characters")
            print(f"📋 Requirements: {requirements}")
            print(f"🔍 Code preview: {python_code[:200]}{'...' if len(python_code) > 200 else ''}")
            
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
            print(f"❌ LLM2 code generation failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'error': str(e),
                'code': '',
                'explanation': '',
                'requirements': []
            }
    
    async def _combine_results(self, llm1_result: Dict, sql_result: Dict, filter_result: Dict, llm2_result: Dict, correlation_id: str) -> Dict[str, Any]:
        """Combine all results into final response"""
        
        print(f"🎯 Combining all results...")
        
        return {
            'success': True,
            'correlation_id': correlation_id,
            'timestamp': datetime.now().isoformat(),
            'llm1_planning': {
                'success': llm1_result.get('success'),
                'entities': llm1_result.get('entities', []),
                'steps_count': len(llm1_result.get('llm1_plan', {}).get('plan', {}).get('steps', [])),
                'confidence': llm1_result.get('llm1_plan', {}).get('confidence'),
                'reasoning': llm1_result.get('llm1_plan', {}).get('plan', {}).get('reasoning'),
                'full_plan': llm1_result.get('llm1_plan', {}).get('plan', {}),  # Include full plan for multi-step pipeline
                'planned_steps': llm1_result.get('llm1_plan', {}).get('plan', {}).get('steps', [])  # Direct access to steps
            },
            'sql_execution': {
                'success': sql_result.get('success'),
                'records_count': len(sql_result.get('data', [])),
                'data_sample': sql_result.get('data', [])[:3],  # First 3 records as sample
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
                'entities_involved': llm1_result.get('entities', []),
                'sql_to_api_ready': len(sql_result.get('data', [])) > 0 and filter_result.get('filtered_endpoint_count', 0) > 0,
                'next_phase': 'Ready for SQL→API mapping execution'
            }
        }
    
    async def _process_final_results_with_llm3(self, combined_results: Dict[str, Any], original_query: str, execution_result: Dict[str, Any] = None, step_context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Process final results using LLM3 Results Processor Agent with pandas enhancement.
        
        This method uses the dedicated LLM3 system prompt and enhanced pandas processing
        to create comprehensive, user-friendly summaries with data insights.
        
        Args:
            combined_results: The raw combined results from all phases
            original_query: The user's original query
            execution_result: Optional code execution results
            
        Returns:
            Dict containing both raw results and enhanced processed summary
        """
        
        print(f"📋 PHASE 7: ENHANCED RESULTS PROCESSING (LLM3)")
        print("=" * 50)
        print(f"🤖 Using LLM3 Results Processor with pandas enhancement")
        
        try:
            # Try to import LLM3 processor
            llm3_processor = None
            try:
                from src.core.realtime.agents.results_processor_agent import results_processor as llm3_processor
            except ImportError:
                pass
            
            if llm3_processor:
                # Build step_results_for_processing with variable names (ExecutionManager pattern)
                step_results_for_processing = {}
                
                # Extract data from step context using the new variable system
                if step_context and step_context.get('data_variables'):
                    for var_name, var_data in step_context['data_variables'].items():
                        step_results_for_processing[var_name] = var_data
                
                # Fallback to old format if no variables stored
                if not step_results_for_processing:
                    sql_data = combined_results.get('sql_execution', {}).get('data', [])
                    if sql_data:
                        step_results_for_processing["step_1_sql"] = sql_data
                    
                    if execution_result and execution_result.get('success'):
                        stdout = execution_result.get('stdout', '')
                        if stdout:
                            step_results_for_processing["step_2_api"] = [{'raw_output': stdout}]
                
                # Use the LLM3 processor with proper format
                prompt = f"Process these results for query: {original_query}\n\nResults: {json.dumps(step_results_for_processing, default=str)[:1000]}..."
                
                print(f"🔍 DEBUG: LLM3 Input Data Structure:")
                for var_name, var_data in step_results_for_processing.items():
                    if isinstance(var_data, list) and len(var_data) > 0:
                        print(f"   📊 {var_name}: {len(var_data)} records")
                        print(f"      Sample keys: {list(var_data[0].keys()) if isinstance(var_data[0], dict) else 'Not dict'}")
                        if isinstance(var_data[0], dict):
                            sample_record = var_data[0]
                            print(f"      Sample values:")
                            for key, value in list(sample_record.items())[:5]:
                                print(f"        {key}: {value}")
                    else:
                        print(f"   📊 {var_name}: {type(var_data)} - {str(var_data)[:100]}...")
                
                # Call LLM3 processor with correct method
                result = await llm3_processor.process_results(
                    query=original_query,
                    results=step_results_for_processing,
                    original_plan=None,
                    is_sample=False,
                    metadata={'flow_id': 'hybrid_executor'}
                )
                
                # Parse response from ResultsProcessorAgent
                if hasattr(result, 'display_type') and hasattr(result, 'content'):
                    response_json = {
                        'display_type': result.display_type,
                        'content': result.content,
                        'metadata': getattr(result, 'metadata', {})
                    }
                elif hasattr(result, 'output'):
                    # Extract from agent output
                    response_json = {
                        'display_type': 'markdown',
                        'content': str(result.output),
                        'metadata': {}
                    }
                else:
                    # Fallback: treat as string
                    response_json = {
                        'display_type': 'markdown',
                        'content': str(result),
                        'metadata': {}
                    }
                
                print(f"🔍 DEBUG: LLM3 Raw Response:")
                print(f"   Display Type: {response_json.get('display_type')}")
                print(f"   Content Type: {type(response_json.get('content'))}")
                if isinstance(response_json.get('content'), list) and len(response_json['content']) > 0:
                    print(f"   Content Length: {len(response_json['content'])} items")
                    print(f"   First Item Keys: {list(response_json['content'][0].keys()) if isinstance(response_json['content'][0], dict) else 'Not dict'}")
                    if isinstance(response_json['content'][0], dict):
                        first_item = response_json['content'][0]
                        print(f"   First Item Sample:")
                        for key, value in list(first_item.items())[:8]:
                            print(f"     {key}: {str(value)[:100]}{'...' if len(str(value)) > 100 else ''}")
                else:
                    print(f"   Content Preview: {str(response_json.get('content'))[:200]}...")
                print(f"   Metadata: {response_json.get('metadata', {})}")
                
                return {
                    'success': True,
                    'raw_results': combined_results,
                    'processed_summary': response_json,
                    'processing_method': 'llm3_enhanced'
                }
                
            else:
                print(f"⚠️ LLM3 processor not available - using basic results")
                return {
                    'success': True,
                    'raw_results': combined_results,
                    'processed_summary': f"Query: {original_query}\n\nResults: {len(combined_results)} phases completed",
                    'processing_method': 'basic_fallback'
                }
            
        except Exception as e:
            print(f"❌ LLM3 processing failed: {e}")
            return {
                'success': False,
                'raw_results': combined_results,
                'processed_summary': f"Results processing failed: {str(e)}",
                'error': str(e)
            }
    
    async def _execute_generated_code(self, python_code: str, correlation_id: str) -> Dict[str, Any]:
        """Execute the generated Python code and capture results"""
        
        print(f"🚀 EXECUTING GENERATED CODE")
        
        try:
            # Save the code to a temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(python_code)
                temp_file = f.name
            
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
                print(f"✅ Code executed successfully!")
                print(result.stdout)
                
                return {
                    'success': True,
                    'stdout': result.stdout,
                    'stderr': result.stderr,
                    'return_code': result.returncode,
                    'execution_time': 'N/A'  # Could add timing if needed
                }
            else:
                print(f"❌ Code execution failed with return code {result.returncode}")
                print(result.stderr)
                
                return {
                    'success': False,
                    'stdout': result.stdout,
                    'stderr': result.stderr,
                    'return_code': result.returncode,
                    'error': f"Execution failed with code {result.returncode}"
                }
                
        except subprocess.TimeoutExpired:
            print(f"⏰ Code execution timed out after 60 seconds")
            return {
                'success': False,
                'error': 'Execution timeout (60s)',
                'stdout': '',
                'stderr': 'Timeout expired'
            }
        except Exception as e:
            print(f"❌ Failed to execute code: {e}")
            return {
                'success': False,
                'error': str(e),
                'stdout': '',
                'stderr': str(e)
            }
    
    async def _execute_steps_in_order(self, llm1_plan: Dict, query: str, correlation_id: str) -> Dict[str, Any]:
        """
        Execute steps in the order specified by LLM1 plan with ExecutionManager pattern enhancements.
        
        Key enhancements:
        - Step context passing between steps
        - Dependency resolution 
        - Better error handling with critical/non-critical step support
        - Structured execution flow with proper data flow tracking
        """
        
        steps = llm1_plan.get('plan', {}).get('steps', [])
        if not steps:
            print("⚠️ No steps found in LLM1 plan")
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

        print(f"🔄 ENHANCED EXECUTION: {len(steps)} steps with context passing")
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
            
            print(f"\n📋 STEP {i}/{len(steps)}: {tool_name}")
            print(f"   Context: {query_context}")
            print(f"   Critical: {critical}")
            print(f"   Available Data: {len(step_context['accumulated_data'])} items")
            
            try:
                # ExecutionManager Enhancement: Context-aware step execution
                step_result = await self._execute_single_step_enhanced(
                    step, step_context, query, correlation_id, llm1_plan
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
                
                print(f"   ✅ Step {i} completed in {step_time:.2f}s")
                
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
                
                print(f"   ❌ Step {i} failed in {step_time:.2f}s: {str(e)}")
                
                if critical:
                    print(f"   � Critical step failed, halting execution")
                    break
                else:
                    print(f"   ⚠️ Non-critical step failed, continuing")
                    continue

        # ExecutionManager Enhancement: Execution summary
        total_time = (datetime.now() - step_context['execution_start_time']).total_seconds()
        print(f"\n📊 EXECUTION SUMMARY:")
        print(f"   ⏱️ Total Time: {total_time:.2f}s")
        print(f"   ✅ Completed: {len(step_context['completed_steps'])}/{len(steps)}")
        print(f"   ❌ Errors: {len(step_context['errors'])}")
        print(f"   📊 Total Data: {len(step_context['accumulated_data'])} items")

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
        
        context_parts = ["\n🔗 CONTEXT FROM PREVIOUS STEPS:"]
        
        for item in step_context['accumulated_data']:
            # Ensure item is a dictionary, skip if it's not
            if not isinstance(item, dict):
                print(f"   ⚠️ Skipping non-dict item in accumulated_data: {type(item)} - {str(item)[:50]}...")
                continue
                
            variable_name = item.get('variable_name', 'unknown_variable')
            sample_data = item.get('sample_data', [])
            total_records = item.get('total_records', 0)
            step_name = item.get('step_name', 'unknown_step')
            data_fields = item.get('data_fields', [])
            
            context_parts.append(f"\n📊 Step {step_name}:")
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
            context_parts.append(f"   ⚠️  IMPORTANT: Use variable '{variable_name}' in your code to process ALL {total_records} records")
        
        context_parts.append(f"\n🎯 Current Step: {current_step_name}")
        context_parts.append("📝 INSTRUCTIONS: The samples above show data structure. Generate code that processes the FULL datasets stored in the named variables.")
        
        return "\n".join(context_parts)

    async def _execute_single_step_enhanced(self, step: Dict, step_context: Dict, query: str, 
                                          correlation_id: str, llm1_plan: Dict = None) -> Dict:
        """
        Execute a single step with enhanced context tracking and sample-based data passing.
        Implements ExecutionManager patterns for variable management and context passing.
        """
        step_name = step.get('tool_name', f"Step_{len(step_context['completed_steps']) + 1}")
        step_type = self._determine_step_type_simple(step)
        
        print(f"   🎯 Executing {step_type.upper()} Step: {step_name}")
        
        try:
            if step_type == 'sql':
                print(f"   🔍 DEBUG: About to execute SQL step")
                
                try:
                    # Use the step's query_context instead of the original user query
                    step_query = step.get('query_context', query)
                    print(f"   🔍 DEBUG: Using step query_context: {step_query}")
                    
                    # Build enhanced context with samples and variable names
                    enhanced_context = self._build_enhanced_context_for_llm(step_context, step_name)
                    enhanced_query = f"{step_query}{enhanced_context}" if enhanced_context else step_query
                    
                    # Check if we have API data samples to enhance the SQL query
                    if step_context['accumulated_data']:
                        print(f"   🔗 Using sample context from {len(step_context['accumulated_data'])} previous steps")
                        result = await self._execute_sql_queries(
                            llm1_plan, enhanced_query, correlation_id, step_context['accumulated_data']
                        )
                    else:
                        result = await self._execute_sql_queries(llm1_plan, enhanced_query, correlation_id)
                    
                    # Debug: Log result details
                    print(f"   🔍 SQL result type: {type(result)}")
                    print(f"   🔍 SQL result preview: {str(result)[:100]}...")
                    
                    # Ensure result is a dictionary
                    if not isinstance(result, dict):
                        print(f"   ⚠️ Converting non-dict result to error dict")
                        result = {'success': False, 'error': str(result), 'data': []}
                    
                    # Store SQL result with VARIABLE NAME and SAMPLE for next steps
                    if isinstance(result, dict) and result.get('success'):
                        sql_data = result.get('data', [])
                        print(f"   🔍 SQL data type: {type(sql_data)}, length: {len(sql_data) if hasattr(sql_data, '__len__') else 'N/A'}")
                        
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
                    print(f"   ❌ SQL step execution error: {sql_error}")
                    print(f"   🔍 Error type: {type(sql_error)}")
                    import traceback
                    traceback.print_exc()
                    return {
                        'success': False,
                        'step_type': 'sql',
                        'error': str(sql_error),
                        'data': []
                    }
                
            else:  # API step
                # Execute endpoint filtering with the full LLM1 plan
                if llm1_plan:
                    filter_result = await self._execute_endpoint_filtering(llm1_plan, correlation_id)
                else:
                    print("⚠️ No LLM1 plan available for endpoint filtering")
                    filter_result = {'success': False, 'error': 'No LLM1 plan available'}
                
                # Check if there are SQL steps after this that might need the API data
                total_steps = len(llm1_plan.get('plan', {}).get('steps', [])) if llm1_plan else 1
                current_step = len(step_context['completed_steps']) + 1
                has_dependent_steps = current_step < total_steps
                
                print(f"   🔍 Dependency check: Step {current_step}/{total_steps}, Has dependent steps: {has_dependent_steps}")
                print(f"   🔍 Filter result success: {filter_result.get('success')}")
                
                if has_dependent_steps and filter_result.get('success'):
                    print(f"   🚀 API→SQL workflow detected - executing API call for data collection")
                    
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
                            print(f"   ✅ API Step executed: stored variable {variable_name} with {len(api_raw_output)} chars")
                            
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
                    print(f"   ✅ API Step completed: {filter_result.get('filtered_endpoint_count', 0)} endpoints")
                    return filter_result
                    
        except Exception as e:
            error_msg = f"Step execution failed: {str(e)}"
            print(f"   ❌ {error_msg}")
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
            
            print(f"🔍 DEBUG: Looking for SQL data in step_results and raw_results...")
            
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
                    
            print(f"🔍 Final SQL data found: {len(sql_data)} records")
            
            # Check for LLM3 processed results first (new aggregated format)
            processed_summary = results.get('processed_summary', {})
            if isinstance(processed_summary, dict) and processed_summary.get('display_type') == 'table':
                llm3_content = processed_summary.get('content', [])
                if llm3_content and isinstance(llm3_content, list) and len(llm3_content) > 0:
                    print(f"📄 Exporting {len(llm3_content)} LLM3 aggregated records to CSV...")
                    
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
                            
                    print(f"✅ Exported {len(llm3_content)} LLM3 aggregated records to: {filepath}")
                    return filepath
            
            # Fallback to SQL data if LLM3 processed format not available
            if sql_data and isinstance(sql_data, list) and len(sql_data) > 0:
                # Use SQL data as primary export - THIS IS THE REAL DATA!
                print(f"📄 Exporting {len(sql_data)} SQL records to CSV...")
                
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
                            
                    print(f"✅ Exported {len(sql_data)} SQL records to: {filepath}")
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
            
            print(f"✅ Exported summary to: {filepath}")
            return filepath
            
        except Exception as e:
            print(f"❌ CSV export failed: {e}")
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
        print("❌ API data file not found - cannot proceed")
        return {'success': False, 'error': 'API data file missing'}
    
    if not verification_result['files_status']['schema']:
        print("❌ Schema file not found - cannot proceed")
        return {'success': False, 'error': 'Schema file missing'}
    
    # Test query that should trigger both SQL and API operations  
    test_query = "find users in group [GROUP_NAME] and get their applications and roles"
    
    result = await executor.execute_query(test_query)
    
    print(f"\n🎯 FINAL TEST RESULT:")
    print(f"✅ Success: {result.get('success')}")
    if result.get('success'):
        print(f"📊 SQL Records: {result.get('sql_execution', {}).get('records_count', 0)}")
        print(f"🔍 API Endpoints: {result.get('endpoint_filtering', {}).get('filtered_count', 0)}")
        print(f"🎯 Entities: {result.get('execution_summary', {}).get('entities_involved', [])}")
        print(f"🤖 Code Generated: {result.get('llm2_code_generation', {}).get('success', False)}")
        print(f"� Code Length: {result.get('llm2_code_generation', {}).get('code_length', 0)}")
        print(f"�🚀 Ready for Execution: {result.get('execution_summary', {}).get('ready_for_execution', False)}")
    else:
        print(f"❌ Error: {result.get('error')}")
    
    return result

if __name__ == "__main__":
    asyncio.run(test_real_execution())