#!/usr/bin/env python3
"""
Streamlined End-to-End Pipeline Test
Clean test that only generates essential output files
"""
import os
import sys
import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from dotenv import load_dotenv
from pydantic import BaseModel
from pydantic_ai import Agent

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
        
        # 1. Validate all tool_names are valid entities
        invalid_entities = []
        for tool_name in tool_names:
            if tool_name not in available_entities:
                invalid_entities.append(tool_name)
        
        if invalid_entities:
            raise ValidationError(f"LLM1 HALLUCINATION DETECTED - Invalid entities: {invalid_entities}. Must use only: {available_entities}")
        
        # 2. Validate each step has required fields
        for i, step in enumerate(steps):
            required_fields = ['tool_name', 'query_context', 'critical', 'reason']
            missing_fields = [field for field in required_fields if field not in step]
            if missing_fields:
                raise ValidationError(f"LLM1 STEP {i+1} INVALID - Missing fields: {missing_fields}")
        
        print(f"✅ LLM1 VALIDATION PASSED - No hallucination detected")
        return response

class ExecutionPlanResponse(BaseModel):
    """LLM1 response matching the existing ExecutionPlan format"""
    plan: Dict[str, Any]  # Contains steps, reasoning, partial_success_acceptable
    confidence: int

class CodeResponse(BaseModel):
    python_code: str
    explanation: str
    requirements: List[str]

class PreciseEndpointFilter:
    """Precise filtering that mimics GenericEndpointFilter logic"""
    
    def __init__(self, condensed_reference: Dict):
        self.api_data = condensed_reference
        self.endpoints = condensed_reference['endpoints']
        self.entity_summary = condensed_reference['entity_summary']
    
    def filter_endpoints(self, llm1_plan: ExecutionPlanResponse) -> Dict[str, Any]:
        """Ultra-precise filtering using steps from ExecutionPlan"""
        steps = llm1_plan.plan.get('steps', [])
        
        # Extract entities and operations from steps with improved parsing
        entities = list(set([step.get('tool_name', '').lower() for step in steps]))
        operations = []
        
        print(f"🔍 EXTRACTING OPERATIONS FROM QUERY CONTEXT:")
        for i, step in enumerate(steps, 1):
            query_context = step.get('query_context', '').lower()
            extracted_ops = []
            
            # More comprehensive operation extraction
            if 'list_members' in query_context:
                extracted_ops.append('list_members')
            elif 'list_user_assignments' in query_context:
                extracted_ops.append('list_user_assignments')
            elif 'list_enrollments' in query_context or 'list_factors' in query_context:
                extracted_ops.append('list_factors')
            elif 'list_by_user' in query_context:
                extracted_ops.append('list_by_user')
            elif 'list groups' in query_context or 'list' in query_context:
                extracted_ops.append('list')
            elif 'get' in query_context:
                extracted_ops.append('get')
            elif 'create' in query_context:
                extracted_ops.append('create')
            
            print(f"   Step {i}: '{query_context}' → {extracted_ops}")
            operations.extend(extracted_ops)
        
        operations = list(set(operations))
        methods = ['GET']  # Default to GET for most operations
        
        print(f"🎯 PRECISE FILTERING")
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
        
        # Final safety limit (should never trigger with proper LLM1 output)
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
        
        # Semantic aliases
        operation_aliases = {
            'list': ['search', 'get_all', 'find', 'query'],
            'get': ['retrieve', 'show', 'read', 'fetch'],
            'create': ['add', 'new', 'post'],
            'update': ['modify', 'edit', 'change', 'put', 'patch'],
            'delete': ['remove', 'destroy'],
            'assign': ['add_to', 'attach'],
            'unassign': ['remove_from', 'detach']
        }
        
        # Check if endpoint operation is an alias of requested operation
        for main_op, aliases in operation_aliases.items():
            if requested_op == main_op and endpoint_op in aliases:
                return True
            if endpoint_op == main_op and requested_op in aliases:
                return True
        
        return False

async def run_streamlined_test():
    """Run streamlined end-to-end test with minimal file generation"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    query = "list users of group sso-super-admins and fetch their applications, factors and roles assigned"
    
    print("🎯 STREAMLINED PIPELINE TEST")
    print("=" * 70)
    print(f"📅 Started: {datetime.now()}")
    print(f"📝 Query: {query}")
    print(f"🎯 Goal: Complete workflow with minimal file generation")
    
    try:
        load_dotenv()
        
        # Load condensed reference
        with open('Okta_API_entitity_endpoint_reference.json', 'r') as f:
            api_data = json.load(f)
        
        print(f"✅ Loaded {len(api_data['entity_summary'])} entities, {len(api_data['endpoints'])} endpoints")
        
        # Phase 1: LLM1 Planning
        print("\n🧠 PHASE 1: LLM1 STRATEGIC PLANNING")
        print("=" * 50)
        
        entity_summary = api_data['entity_summary']
        available_entities = list(entity_summary.keys())
        
        # Load system prompt and SQL schema
        with open('llm1_system_prompt.txt', 'r', encoding='utf-8') as f:
            base_system_prompt = f.read()
        
        with open('okta_schema.json', 'r') as f:
            sql_schema = json.load(f)
        
        # Build dynamic system prompt
        entity_operations_text = []
        for entity, details in entity_summary.items():
            operations = details.get('operations', [])
            methods = details.get('methods', [])
            entity_operations_text.append(f"  • {entity}: operations=[{', '.join(operations)}], methods=[{', '.join(methods)}]")
        
        entities_with_operations = "\n".join(entity_operations_text)
        
        sql_tables = sql_schema.get('sql_tables', {})
        sql_table_names = list(sql_tables.keys())
        
        sql_info = f"""
SQL DATABASE SCHEMA:
Available Tables: {', '.join(sql_table_names)}
• users: basic profiles, status, department info
• groups: group names, descriptions  
• user_group_memberships: which users belong to which groups
• applications: app names, status, sign-on modes
• user_application_assignments: user-to-app assignments
• user_factors: MFA enrollment info
• devices: device basic info
• policies: policy definitions

IMPORTANT: Role assignments (user roles, admin roles) are NOT available in SQL - they require API access."""
        
        # Update system prompt
        import re
        entities_section = f"AVAILABLE ENTITIES AND OPERATIONS:\n{entities_with_operations}"
        complete_section = f"{entities_section}\n{sql_info}"
        
        pattern = r'AVAILABLE ENTITIES:.*?(?=\n\n|\nIMPORTANT|\nAVAILABLE|\nCORE|$)'
        
        if re.search(pattern, base_system_prompt, flags=re.DOTALL):
            updated_system_prompt = re.sub(pattern, complete_section, base_system_prompt, flags=re.DOTALL)
        else:
            insertion_point = "2. Okta API: Real-time operations, lifecycle management, audit logs, data not available in SQL"
            updated_system_prompt = base_system_prompt.replace(
                insertion_point,
                f"{insertion_point}\n{complete_section}"
            )
        
        # Create LLM1 agent without strict validation first
        llm1_agent_raw = Agent(
            model='openai:gpt-4o-mini',
            system_prompt=updated_system_prompt
            # No result_type for raw response
        )
        
        print(f"📝 Query: {query}")
        print(f"🔄 Running LLM1 planning...")
        
        # Get raw response first
        raw_result = await llm1_agent_raw.run(query)
        raw_output = raw_result.output
        print(f"🔍 Raw LLM1 output: {raw_output}")
        
        # Parse the raw output manually
        if isinstance(raw_output, str):
            import json as json_module
            try:
                llm1_output_dict = json_module.loads(raw_output)
            except Exception as e:
                print(f"❌ Failed to parse LLM1 JSON output: {e}")
                return None
        else:
            llm1_output_dict = raw_output
        
        # Create validated response object
        try:
            llm1_output = ExecutionPlanResponse(**llm1_output_dict)
        except Exception as e:
            print(f"❌ Failed to validate LLM1 response: {e}")
            print(f"Response was: {llm1_output_dict}")
            return None
        
        # Validate LLM1 response
        print("\n🔍 VALIDATING LLM1 RESPONSE...")
        try:
            StrictValidator.validate_llm1_response(
                llm1_output.model_dump(), 
                available_entities, 
                entity_summary
            )
        except ValidationError as ve:
            print(f"❌ LLM1 VALIDATION FAILED: {ve}")
            return None
        
        print(f"\n📋 LLM1 PLAN:")
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
        
        # Phase 2: Endpoint Filtering
        print("\n🔍 PHASE 2: ENDPOINT FILTERING")
        print("=" * 50)
        
        filter_engine = PreciseEndpointFilter(api_data)
        filter_results = filter_engine.filter_endpoints(llm1_output)
        
        print(f"\n📊 FILTERING RESULTS:")
        print(f"📈 Original endpoints: {filter_results['original_endpoint_count']}")
        print(f"📉 Filtered endpoints: {filter_results['filtered_endpoint_count']}")
        print(f"🎯 Reduction: {filter_results['reduction_percentage']}%")
        
        # Extract entities for summary
        steps = llm1_output.plan.get('steps', [])
        entities = list(set([step.get('tool_name', '') for step in steps]))
        
        # Final Summary - Focus on LLM1 and filtering
        print("\n🎉 LLM1 PHASE COMPLETED!")
        print("=" * 70)
        print(f"📊 Phase 1 Results:")
        print(f"   • Entities: {entities}")
        print(f"   • Steps: {len(steps)}")
        print(f"   • Confidence: {llm1_output.confidence}%")
        print(f"📊 Phase 2 Results:")
        print(f"   • Endpoints: {filter_results['original_endpoint_count']} → {filter_results['filtered_endpoint_count']}")
        print(f"   • Reduction: {filter_results['reduction_percentage']}%")
        print(f"   • Entity Results: {filter_results['entity_results']}")
        
        print(f"\n🔍 FILTERING DEBUG:")
        print(f"   Issue: Only {filter_results['filtered_endpoint_count']} endpoints found for {len(entities)} entities")
        print(f"   Need to improve operation extraction from query_context")
        
        return {
            'success': True,
            'llm1_plan': llm1_output.model_dump(),
            'filtering_results': filter_results,
            'entities': entities,
            'debug_info': {
                'endpoints_found': filter_results['filtered_endpoint_count'],
                'entities_requested': len(entities),
                'entity_results': filter_results['entity_results']
            }
        }
        
    except Exception as e:
        print(f"❌ Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}

if __name__ == "__main__":
    asyncio.run(run_streamlined_test())
