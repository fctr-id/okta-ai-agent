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
    print("✅ SQL agent imported successfully")
except ImportError as e:
    print(f"❌ Failed to import SQL agent: {e}")
    sql_agent = None

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
        """Ultra-precise filtering using steps from ExecutionPlan - ONLY for API steps"""
        steps = llm1_plan.plan.get('steps', [])
        
        # Extract entities and operations ONLY from API steps (not SQL steps)
        api_entities = []
        operations = []
        
        print(f"🔍 EXTRACTING OPERATIONS FROM QUERY CONTEXT:")
        for i, step in enumerate(steps, 1):
            query_context = step.get('query_context', '').lower()
            tool_name = step.get('tool_name', '').lower()
            
            # Skip SQL steps - only process API steps
            if query_context.startswith('sql:'):
                print(f"   Step {i}: '{query_context}' → [] (SQL step - skipped)")
                continue
                
            # This is an API step - extract operations DYNAMICALLY
            extracted_ops = []
            
            # DYNAMIC operation extraction - get all operations from entity_summary
            entity_name = tool_name.lower()
            if entity_name in self.entity_summary:
                available_operations = self.entity_summary[entity_name].get('operations', [])
                
                # Match operations mentioned in query_context against available operations
                for operation in available_operations:
                    if operation.lower() in query_context.lower():
                        extracted_ops.append(operation)
                
                # If no specific operation found, check for common patterns
                if not extracted_ops:
                    for operation in available_operations:
                        # Check for semantic matches
                        if any(pattern in query_context.lower() for pattern in [
                            'list', 'get', 'fetch', 'retrieve', 'find'
                        ]) and operation.startswith('list'):
                            extracted_ops.append(operation)
                            break
                        elif 'create' in query_context.lower() and operation == 'create':
                            extracted_ops.append(operation)
                            break
                        elif any(pattern in query_context.lower() for pattern in [
                            'update', 'modify', 'change'
                        ]) and operation in ['update', 'replace']:
                            extracted_ops.append(operation)
                            break
                        elif 'delete' in query_context.lower() and operation == 'delete':
                            extracted_ops.append(operation)
                            break
            
            print(f"   Step {i}: '{query_context}' → {extracted_ops}")
            
            # Only add to entities and operations if this is an API step with operations
            if extracted_ops:
                api_entities.append(tool_name)
                operations.extend(extracted_ops)
        
        # Remove duplicates
        entities = list(set(api_entities))
        operations = list(set(operations))
        methods = ['GET']  # Default to GET for most operations
        
        print(f"🎯 PRECISE FILTERING (API STEPS ONLY)")
        print(f"   Entities: {entities}")
        print(f"   Operations: {operations}")
        print(f"   Methods: {methods}")
        
        filtered_endpoints = []
        entity_results = {}
        
        for entity in entities:
            if not entity:  # Skip empty entities
                continue
                
            entity_endpoints = self._get_entity_operation_matches(entity, operations, methods)
            
            if entity_endpoints:
                # Limit per entity (max 3 per entity to prevent explosion)
                max_per_entity = min(3, max(1, 8 // len([e for e in entities if e])))
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
            
            # Phase N+1: LLM2 Code Generation (using all collected data)
            print(f"\n🤖 PHASE 4: LLM2 CODE GENERATION")
            print("=" * 50)
            
            llm2_result = await self._execute_llm2_code_generation(
                llm1_result, sql_result, filter_result, query, correlation_id, api_data_collected
            )
            
            # Phase 4: Data Mapping Analysis (NEW)
            print(f"\n🔗 PHASE 4: DATA MAPPING ANALYSIS")
            print("=" * 50)
            
            mapping_result = await self._analyze_sql_to_api_mapping(
                llm1_result, sql_result, filter_result, correlation_id
            )
            
            # Phase 5: Execute Generated Code (NEW)
            execution_result = None
            if llm2_result.get('success') and llm2_result.get('code'):
                print(f"\n🚀 PHASE 5: CODE EXECUTION")
                print("=" * 50)
                
                execution_result = await self._execute_generated_code(
                    llm2_result['code'], correlation_id
                )
            
            # Phase 6: Results Combination
            print(f"\n🎯 PHASE 6: RESULTS COMBINATION")
            print("=" * 50)
            
            final_result = await self._combine_results(llm1_result, sql_result, filter_result, llm2_result, correlation_id)
            
            # Add execution results to final result
            if execution_result:
                final_result['execution_result'] = execution_result
            
            print(f"\n✅ HYBRID EXECUTION COMPLETED!")
            print(f"   📊 LLM1 Steps: {len(llm1_plan.get('plan', {}).get('steps', []))}")
            print(f"   💾 SQL Results: {len(sql_result.get('data', []))} records")
            print(f"   🔍 Filtered Endpoints: {filter_result.get('filtered_endpoint_count', 0)}")
            print(f"   🤖 LLM2 Code Generated: {llm2_result.get('success', False)}")
            print(f"   📝 Code Length: {len(llm2_result.get('code', ''))} characters")
            print(f"   🚀 Code Executed: {execution_result.get('success', False) if execution_result else False}")
            
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
    
    async def _execute_sql_queries(self, llm1_plan: Dict, query: str, correlation_id: str) -> Dict[str, Any]:
        """Execute SQL queries based on LLM1 plan using REAL SQL agent"""
        
        if not sql_agent:
            print("❌ SQL agent not available")
            return {'success': False, 'error': 'SQL agent not available', 'data': []}
        
        print(f"💾 Executing SQL queries based on LLM1 plan...")
        
        try:
            # Use the real SQL agent with proper tenant_id
            sql_dependencies = SQLDependencies(tenant_id="default")  # Use default tenant_id
            
            print(f"🔍 Running SQL agent with query: {query}")
            sql_result = await sql_agent.run(query, deps=sql_dependencies)
            
            print(f"📊 SQL agent result type: {type(sql_result)}")
            print(f"📊 SQL agent raw output: {sql_result.output}")
            
            # Extract JSON from the SQL agent response
            try:
                sql_response_json = extract_json_from_text(str(sql_result.output))
                sql_query = sql_response_json.get('sql', '')
                explanation = sql_response_json.get('explanation', '')
                
                print(f"✅ Generated SQL: {sql_query[:100]}{'...' if len(sql_query) > 100 else ''}")
                print(f"📝 Explanation: {explanation}")
                
                # Now execute the SQL query against the database
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
                    return {
                        'success': False, 
                        'error': 'Empty SQL query generated',
                        'explanation': explanation,
                        'data': []
                    }
                    
            except Exception as e:
                print(f"❌ Failed to parse SQL agent response: {e}")
                return {'success': False, 'error': f'SQL parsing error: {e}', 'data': []}
                
        except Exception as e:
            print(f"❌ SQL execution failed: {e}")
            import traceback
            traceback.print_exc()
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
                'reasoning': llm1_result.get('llm1_plan', {}).get('plan', {}).get('reasoning')
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
    
    async def _analyze_sql_to_api_mapping(self, llm1_result: Dict, sql_result: Dict, filter_result: Dict, correlation_id: str) -> Dict[str, Any]:
        """Analyze how SQL results map to API endpoints for subsequent API calls"""
        
        print(f"🔗 Analyzing SQL data → API endpoint mapping...")
        
        sql_data = sql_result.get('data', [])
        filtered_endpoints = filter_result.get('filtered_endpoints', [])
        entities = llm1_result.get('entities', [])
        
        if not sql_data:
            print("⚠️ No SQL data available for mapping analysis")
            return {'success': False, 'error': 'No SQL data for mapping'}
        
        if not filtered_endpoints:
            print("⚠️ No API endpoints available for mapping analysis")
            return {'success': False, 'error': 'No API endpoints for mapping'}
        
        # Analyze the SQL data structure
        print(f"📊 SQL Data Analysis:")
        print(f"   Records: {len(sql_data)}")
        if sql_data:
            sample_record = sql_data[0]
            print(f"   Sample record keys: {list(sample_record.keys())}")
            
            # Look for key fields that can be used for API calls
            key_fields = self._identify_key_fields(sample_record)
            print(f"   Key fields for API calls: {key_fields}")
        
        # Analyze endpoint requirements
        print(f"🔗 API Endpoint Analysis:")
        endpoint_requirements = []
        for endpoint in filtered_endpoints:
            url_pattern = endpoint.get('url_pattern', '')
            method = endpoint.get('method', '')
            entity = endpoint.get('entity', '')
            operation = endpoint.get('operation', '')
            
            # Extract URL parameters
            url_params = self._extract_url_parameters(url_pattern)
            
            endpoint_info = {
                'name': endpoint.get('name', ''),
                'method': method,
                'url_pattern': url_pattern,
                'entity': entity,
                'operation': operation,
                'url_parameters': url_params,
                'can_use_sql_data': self._can_use_sql_data(url_params, key_fields) if sql_data else False
            }
            endpoint_requirements.append(endpoint_info)
            
            print(f"   • {method} {url_pattern}")
            print(f"     Entity: {entity}, Operation: {operation}")
            print(f"     URL Parameters: {url_params}")
            print(f"     Can use SQL data: {endpoint_info['can_use_sql_data']}")
        
        # Create mapping strategy
        mapping_strategy = self._create_mapping_strategy(sql_data, endpoint_requirements, entities)
        
        print(f"\n🎯 MAPPING STRATEGY:")
        for step in mapping_strategy.get('steps', []):
            print(f"   Step {step['order']}: {step['description']}")
            print(f"   → Use: {step['sql_fields']} → Call: {step['endpoint']}")
        
        return {
            'success': True,
            'sql_analysis': {
                'record_count': len(sql_data),
                'key_fields': key_fields if sql_data else [],
                'sample_record': sql_data[0] if sql_data else {}
            },
            'endpoint_analysis': endpoint_requirements,
            'mapping_strategy': mapping_strategy,
            'correlation_id': correlation_id
        }
    
    def _identify_key_fields(self, record: Dict) -> List[str]:
        """Identify key fields in SQL record that can be used for API calls"""
        key_fields = []
        
        # Common Okta ID fields
        for field in record.keys():
            if any(pattern in field.lower() for pattern in ['okta_id', 'id', 'email', 'login', 'name']):
                key_fields.append(field)
        
        return key_fields
    
    def _extract_url_parameters(self, url_pattern: str) -> List[str]:
        """Extract parameters from URL pattern like /api/v1/groups/:groupId/users"""
        import re
        # Find parameters in :param format
        params = re.findall(r':(\w+)', url_pattern)
        return params
    
    def _can_use_sql_data(self, url_params: List[str], key_fields: List[str]) -> bool:
        """Check if SQL data contains fields needed for URL parameters"""
        if not url_params:
            return True  # No parameters needed
        
        # Check if we have matching fields
        for param in url_params:
            # Common mappings
            if param == 'groupId' and any('group' in field.lower() and 'id' in field.lower() for field in key_fields):
                return True
            elif param == 'userId' and any('user' in field.lower() and 'id' in field.lower() for field in key_fields):
                return True
            elif param == 'appId' and any('app' in field.lower() and 'id' in field.lower() for field in key_fields):
                return True
            elif param.lower().replace('id', '') in [field.lower().replace('_', '').replace('okta', '') for field in key_fields]:
                return True
        
        return False
    
    def _create_mapping_strategy(self, sql_data: List[Dict], endpoint_requirements: List[Dict], entities: List[str]) -> Dict:
        """Create a strategy for mapping SQL results to API calls"""
        
        steps = []
        step_order = 1
        
        if not sql_data:
            return {'steps': [], 'summary': 'No SQL data available'}
        
        sample_record = sql_data[0]
        
        # Strategy based on entities and available data
        for entity in entities:
            matching_endpoints = [ep for ep in endpoint_requirements if ep['entity'].lower() == entity.lower()]
            
            for endpoint in matching_endpoints:
                if endpoint['can_use_sql_data']:
                    # Find relevant SQL fields
                    relevant_fields = []
                    for param in endpoint['url_parameters']:
                        for field in sample_record.keys():
                            if self._field_matches_param(field, param):
                                relevant_fields.append(field)
                    
                    step = {
                        'order': step_order,
                        'description': f"Call {endpoint['name']} for each SQL record",
                        'endpoint': f"{endpoint['method']} {endpoint['url_pattern']}",
                        'sql_fields': relevant_fields,
                        'entity': entity,
                        'operation': endpoint['operation']
                    }
                    steps.append(step)
                    step_order += 1
        
        return {
            'steps': steps,
            'summary': f"{len(steps)} API calls can be made using SQL data",
            'total_potential_calls': len(sql_data) * len(steps) if steps else 0
        }
    
    def _field_matches_param(self, field: str, param: str) -> bool:
        """Check if a SQL field matches a URL parameter"""
        field_lower = field.lower()
        param_lower = param.lower()
        
        # Direct mappings
        mappings = {
            'groupid': ['group_okta_id', 'group_id'],
            'userid': ['user_okta_id', 'okta_id', 'user_id'],
            'appid': ['application_okta_id', 'app_okta_id', 'application_id'],
            'id': ['okta_id', 'id']
        }
        
        if param_lower in mappings:
            return any(mapping in field_lower for mapping in mappings[param_lower])
        
        # Fallback pattern matching
        return param_lower.replace('id', '') in field_lower

    async def _execute_generated_code(self, python_code: str, correlation_id: str) -> Dict[str, Any]:
        """Execute the generated Python code and capture results"""
        
        print(f"🚀 EXECUTING GENERATED CODE")
        print(f"==================================================")
        
        try:
            # Save the code to a temporary file
            import tempfile
            import subprocess
            import sys
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(python_code)
                temp_file = f.name
            
            # Execute the code and capture output
            result = subprocess.run(
                [sys.executable, temp_file],
                capture_output=True,
                text=True,
                timeout=30,  # 30 second timeout
                cwd=os.path.dirname(__file__)  # Run in data directory
            )
            
            # Clean up temp file
            os.unlink(temp_file)
            
            if result.returncode == 0:
                print(f"✅ Code executed successfully!")
                print(f"📊 EXECUTION RESULTS:")
                print(f"{'='*60}")
                print(result.stdout)
                print(f"{'='*60}")
                
                return {
                    'success': True,
                    'stdout': result.stdout,
                    'stderr': result.stderr,
                    'return_code': result.returncode,
                    'execution_time': 'N/A'  # Could add timing if needed
                }
            else:
                print(f"❌ Code execution failed with return code {result.returncode}")
                print(f"📝 Error output:")
                print(result.stderr)
                
                return {
                    'success': False,
                    'stdout': result.stdout,
                    'stderr': result.stderr,
                    'return_code': result.returncode,
                    'error': f"Execution failed with code {result.returncode}"
                }
                
        except subprocess.TimeoutExpired:
            print(f"⏰ Code execution timed out after 30 seconds")
            return {
                'success': False,
                'error': 'Execution timeout (30s)',
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
        """Execute steps in the order specified by LLM1 plan"""
        
        steps = llm1_plan.get('plan', {}).get('steps', [])
        if not steps:
            print("⚠️ No steps found in LLM1 plan")
            return {
                'sql_result': {'success': True, 'data': [], 'explanation': 'No steps to execute'},
                'filter_result': {'success': True, 'filtered_endpoints': [], 'filtered_endpoint_count': 0},
                'api_data': []
            }
        
        # Check if this is a complex workflow (more than 2 steps or mixed types)
        step_types = [self._determine_step_type_simple(step) for step in steps]
        is_complex_workflow = len(steps) > 2 or ('sql' in step_types and 'api' in step_types)
        
        if is_complex_workflow:
            print(f"🔄 DETECTED COMPLEX WORKFLOW - Using Enhanced Step Orchestrator")
            print(f"   Steps: {len(steps)}")
            print(f"   Types: {step_types}")
            
            # Use the enhanced orchestrator for complex workflows
            try:
                from enhanced_step_orchestrator import StepOrchestrator
                orchestrator = StepOrchestrator(self)
                workflow_result = await orchestrator.execute_complex_workflow(query, llm1_plan)
                
                # Convert workflow result to expected format
                return self._convert_workflow_to_legacy_format(workflow_result)
                
            except ImportError:
                print("⚠️ Enhanced orchestrator not available, falling back to simple execution")
        
        print(f"🔄 Executing {len(steps)} steps in LLM1-specified order (Simple Mode):")
        for i, step in enumerate(steps, 1):
            tool_name = step.get('tool_name', '')
            query_context = step.get('query_context', '')
            critical = step.get('critical', False)
            print(f"   Step {i}: {tool_name} - {query_context} (Critical: {critical})")
        
        sql_result = {'success': True, 'data': [], 'explanation': 'No SQL steps executed'}
        filter_result = {'success': True, 'filtered_endpoints': [], 'filtered_endpoint_count': 0}
        api_data_collected = []
        
        # Execute steps in order (simple mode - no data flow)
        for i, step in enumerate(steps, 1):
            tool_name = step.get('tool_name', '')
            query_context = step.get('query_context', '')
            critical = step.get('critical', False)
            
            print(f"\n📋 EXECUTING STEP {i}: {tool_name}")
            print(f"   Query Context: {query_context}")
            print(f"   Critical: {critical}")
            
            # Determine if this is SQL or API step
            # SQL step: tool_name is a SQL table name OR query_context contains "SQL:"
            sql_tables = ['users', 'groups', 'applications', 'user_group_memberships', 
                         'user_application_assignments', 'group_application_assignments', 
                         'user_factors', 'devices', 'user_devices', 'policies', 'sync_history']
            
            is_sql_step = (tool_name in sql_tables) or (query_context.upper().startswith('SQL:'))
            
            if is_sql_step:
                # SQL Step
                print(f"   💾 SQL EXECUTION (Step {i})")
                print("   " + "=" * 40)
                
                step_sql_result = await self._execute_sql_queries(llm1_plan, query, correlation_id)
                sql_result = step_sql_result  # Keep the most recent SQL result
                
                print(f"   ✅ SQL Step {i} completed: {len(sql_result.get('data', []))} records")
                
            else:
                # API Step  
                print(f"   🔍 API ENDPOINT FILTERING (Step {i})")
                print("   " + "=" * 40)
                
                step_filter_result = await self._execute_endpoint_filtering(llm1_plan, correlation_id)
                filter_result = step_filter_result  # Keep the most recent filter result
                
                print(f"   ✅ API Step {i} completed: {filter_result.get('filtered_endpoint_count', 0)} endpoints")
        
        return {
            'sql_result': sql_result,
            'filter_result': filter_result, 
            'api_data': api_data_collected
        }
    
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
    
    def _convert_workflow_to_legacy_format(self, workflow_result: Dict) -> Dict[str, Any]:
        """Convert enhanced workflow result to legacy format for backward compatibility"""
        
        workflow_details = workflow_result.get('workflow_results', {})
        step_details = workflow_details.get('step_details', {})
        
        # Find the last successful SQL and API results
        sql_result = {'success': True, 'data': [], 'explanation': 'No SQL steps executed'}
        filter_result = {'success': True, 'filtered_endpoints': [], 'filtered_endpoint_count': 0}
        
        for step_id, details in step_details.items():
            if details.get('success') and details.get('type') == 'sql':
                sql_result = {
                    'success': True,
                    'data': [],  # Would need to extract from actual step results
                    'explanation': f"Enhanced workflow SQL step: {details.get('records', 0)} records"
                }
            elif details.get('success') and details.get('type') == 'api':
                filter_result = {
                    'success': True,
                    'filtered_endpoints': [],  # Would need to extract from actual step results
                    'filtered_endpoint_count': details.get('records', 0)
                }
        
        return {
            'sql_result': sql_result,
            'filter_result': filter_result,
            'api_data': [],
            'workflow_enhanced': True,
            'workflow_summary': workflow_details
        }

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