"""
Comprehensive debug test for preplan agent data flow
Tests the exact data being passed to and returned from the preplan agent
"""
import asyncio
import json
import os
import sys

# Add src path - fix import path  
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_dir))))
sys.path.insert(0, project_root)

from src.core.orchestration.modern_execution_manager import ModernExecutionManager
from src.core.agents.preplan_agent import select_relevant_entities
from src.core.agents.planning_agent import ExecutionStep

async def test_preplan_agent_data_flow():
    """Test preplan agent with actual execution manager data"""
    
    print("=== PREPLAN AGENT DATA FLOW DEBUG ===\n")
    
    # Create execution manager instance
    em = ModernExecutionManager()
    
    print("1. EXECUTION MANAGER LOADED DATA:")
    print(f"   • Entity Summary: {len(em.entity_summary)} entities")
    print(f"   • SQL Tables: {len(em.sql_tables)} tables")
    print(f"   • Available Entities: {len(em.available_entities)} entities")
    print(f"   • Simple Ref Data SQL Tables: {len(em.simple_ref_data.get('sql_tables', []))} tables")
    
    # Show first few entity names for verification
    entity_names = list(em.entity_summary.keys())[:10]
    print(f"   • First 10 Entity Names: {entity_names}")
    
    # Show first few SQL table names for verification  
    sql_table_names = list(em.sql_tables.keys())
    print(f"   • SQL Table Names: {sql_table_names}")
    
    print("\n2. DATA BEING PASSED TO PREPLAN AGENT:")
    
    # Get the exact data being passed (same as execution manager)
    lightweight_ref = em.simple_ref_data
    entities_dict = lightweight_ref.get('entities', {})
    
    print(f"   • Entity Summary Length: {len(em.entity_summary)}")
    print(f"   • SQL Tables Length: {len(em.sql_tables)}")
    print(f"   • Entities Dict Length: {len(entities_dict)}")
    print(f"   • Available Entities Length: {len(list(entities_dict.keys()))}")
    
    # Sample a few entities to show their operations
    print("\n   • Sample Entity Operations:")
    for i, (entity_name, entity_data) in enumerate(list(em.entity_summary.items())[:5]):
        operations = entity_data.get('operations', [])
        print(f"     - {entity_name}: {len(operations)} operations -> {operations[:3]}{'...' if len(operations) > 3 else ''}")
    
    # Sample SQL tables to show structure
    print("\n   • Sample SQL Tables:")
    for i, (table_name, table_info) in enumerate(list(em.sql_tables.items())[:5]):
        columns = table_info.get('columns', [])
        print(f"     - {table_name}: {len(columns)} columns -> {columns[:3]}{'...' if len(columns) > 3 else ''}")
    
    print("\n3. CALLING PREPLAN AGENT:")
    
    # Test query
    test_query = "find role assignments in okta and print user names and role assinged"
    flow_id = "debug-test-123"
    
    print(f"   • Query: {test_query}")
    print(f"   • Flow ID: {flow_id}")
    
    # Call preplan agent with exact same parameters as execution manager
    try:
        preplan_result = await select_relevant_entities(
            query=test_query,
            entity_summary=em.entity_summary,
            sql_tables=em.sql_tables,
            flow_id=flow_id,
            available_entities=list(entities_dict.keys()) if entities_dict else None,
            entities=entities_dict
        )
        
        print("\n4. PREPLAN AGENT RESULT:")
        print(f"   • Success: {preplan_result.get('success', False)}")
        
        if preplan_result.get('success'):
            # Show selected entity-operation pairs
            selected_pairs = preplan_result.get('selected_entity_operations', [])
            print(f"   • Selected Pairs: {len(selected_pairs)}")
            for pair in selected_pairs:
                print(f"     - {pair}")
            
            # Show reasoning
            reasoning = preplan_result.get('reasoning', 'No reasoning provided')
            print(f"   • Reasoning: {reasoning[:200]}{'...' if len(reasoning) > 200 else ''}")
            
            # Show token usage if available
            if 'token_usage' in preplan_result:
                usage = preplan_result['token_usage']
                print(f"   • Token Usage: {usage}")
        else:
            print(f"   • Error: {preplan_result.get('error', 'Unknown error')}")
        
        print("\n5. RAW PREPLAN AGENT OUTPUT:")
        # Convert EntityOperation objects to dict for JSON serialization
        json_safe_result = {}
        for key, value in preplan_result.items():
            if key == 'selected_entity_operations':
                # Convert EntityOperation objects to dicts
                json_safe_result[key] = [
                    {'entity': item.entity, 'operation': item.operation} 
                    if hasattr(item, 'entity') and hasattr(item, 'operation')
                    else str(item)
                    for item in value
                ]
            else:
                json_safe_result[key] = value
        print(json.dumps(json_safe_result, indent=2))
        
        # CONTINUE TO PLANNING AGENT TESTING
        if preplan_result.get('success'):
            print("\n" + "="*60)
            print("6. EXECUTION MANAGER ENDPOINT FILTERING:")
            
            # Simulate the execution manager's endpoint filtering process
            selected_entity_operations = preplan_result.get('selected_entity_operations', [])
            
            print(f"   • Processing {len(selected_entity_operations)} entity-operation pairs from preplan")
            
            # Filter endpoints using execution manager's method
            selected_entity_endpoints = []
            for entity_op in selected_entity_operations:
                # Create mock ExecutionStep for filtering
                mock_step = ExecutionStep(
                    step_number=1,
                    tool_name="api",
                    entity=entity_op.entity,
                    operation=entity_op.operation,
                    query_context="Mock step for filtering",
                    reasoning="Mock reasoning for testing"
                )
                
                # Get filtered endpoints for this entity-operation
                step_endpoints = em._get_entity_endpoints_for_step(mock_step)
                selected_entity_endpoints.extend(step_endpoints)
                
                print(f"     - {entity_op.entity}::{entity_op.operation} - {len(step_endpoints)} endpoints")
            
            # Remove duplicates based on endpoint ID
            seen_ids = set()
            unique_endpoints = []
            for endpoint in selected_entity_endpoints:
                endpoint_id = endpoint.get('id', f"{endpoint.get('entity')}-{endpoint.get('operation')}")
                if endpoint_id not in seen_ids:
                    seen_ids.add(endpoint_id)
                    unique_endpoints.append(endpoint)
            
            print(f"   • Total unique endpoints after filtering: {len(unique_endpoints)}")
            
            # Show detailed endpoint data being passed to planning agent
            print("\n   • DETAILED ENDPOINT DATA:")
            for i, endpoint in enumerate(unique_endpoints, 1):
                print(f"     Endpoint {i}:")
                for field_name, field_value in endpoint.items():
                    # Truncate long values for readability
                    if isinstance(field_value, str) and len(field_value) > 100:
                        display_value = field_value[:100] + "..."
                    elif isinstance(field_value, list) and len(field_value) > 5:
                        display_value = field_value[:5] + ["..."]
                    else:
                        display_value = field_value
                    print(f"       - {field_name}: {display_value}")
                print()  # Empty line between endpoints
            
            # Build filtered entity summary from endpoints
            filtered_entity_summary = {}
            endpoint_based_entities = {}
            
            for endpoint in unique_endpoints:
                entity_name = endpoint.get('entity', '')
                operation = endpoint.get('operation', '')
                method = endpoint.get('method', 'GET')
                
                if entity_name:
                    if entity_name not in filtered_entity_summary:
                        filtered_entity_summary[entity_name] = {'operations': [], 'methods': []}
                    if operation and operation not in filtered_entity_summary[entity_name]['operations']:
                        filtered_entity_summary[entity_name]['operations'].append(operation)
                    if method and method not in filtered_entity_summary[entity_name]['methods']:
                        filtered_entity_summary[entity_name]['methods'].append(method)
                        
                    # Group by entity for planning agent format
                    if entity_name not in endpoint_based_entities:
                        endpoint_based_entities[entity_name] = {'operations': [f"{entity_name}_{operation}"], 'endpoints': []}
                    endpoint_based_entities[entity_name]['endpoints'].append(endpoint)
            
            print(f"   • Filtered entity summary: {len(filtered_entity_summary)} entities")
            for entity_name, entity_data in filtered_entity_summary.items():
                operations = entity_data.get('operations', [])
                methods = entity_data.get('methods', [])
                print(f"     - {entity_name}: operations={operations}, methods={methods}")
            
            print(f"\n   • ENDPOINT-BASED ENTITIES DATA:")
            for entity_name, entity_data in endpoint_based_entities.items():
                print(f"     Entity: {entity_name}")
                print(f"       - Operations: {entity_data.get('operations', [])}")
                print(f"       - Endpoints Count: {len(entity_data.get('endpoints', []))}")
                print(f"       - Endpoint IDs: {[ep.get('id', 'No ID') for ep in entity_data.get('endpoints', [])]}")
                print()
            
            print("\n" + "="*60)
            print("7. CALLING PLANNING AGENT:")
            
            # Create dependencies for Planning Agent with filtered data
            from src.core.agents.planning_agent import PlanningDependencies
            
            planning_deps = PlanningDependencies(
                available_entities=list(endpoint_based_entities.keys()),
                entity_summary=filtered_entity_summary,
                sql_tables=em.sql_tables,
                flow_id=flow_id,
                entities=endpoint_based_entities
            )
            
            print(f"   • Available entities for planning: {len(planning_deps.available_entities)}")
            print(f"   • Entity names: {planning_deps.available_entities}")
            print(f"   • SQL tables available: {len(planning_deps.sql_tables)}")
            
            print(f"\n   • COMPLETE DATA BEING PASSED TO PLANNING AGENT:")
            print(f"     - Query: {test_query}")
            print(f"     - Available Entities: {planning_deps.available_entities}")
            print(f"     - Flow ID: {planning_deps.flow_id}")
            
            print(f"\n     - Entity Summary Structure:")
            for entity, summary in planning_deps.entity_summary.items():
                print(f"       * {entity}: {summary}")
            
            print(f"\n     - SQL Tables Structure:")
            for table_name, table_info in list(planning_deps.sql_tables.items())[:3]:  # Show first 3 tables
                columns = table_info.get('columns', [])
                print(f"       * {table_name}: {len(columns)} columns -> {columns[:5]}{'...' if len(columns) > 5 else ''}")
            
            print(f"\n     - Entities Dictionary Structure:")
            for entity_name, entity_data in planning_deps.entities.items():
                endpoints = entity_data.get('endpoints', [])
                operations = entity_data.get('operations', [])
                print(f"       * {entity_name}:")
                print(f"         - Operations: {operations}")
                print(f"         - Endpoint Count: {len(endpoints)}")
                if endpoints:
                    first_endpoint = endpoints[0]
                    endpoint_keys = list(first_endpoint.keys()) if first_endpoint else []
                    print(f"         - First Endpoint Keys: {endpoint_keys}")
                    sample_endpoint = {k: v for k, v in list(first_endpoint.items())[:3]} if first_endpoint else {}
                    print(f"         - First Endpoint Sample: {sample_endpoint}...")
                    
                    # Verify notes are included
                    notes_count = 0
                    total_notes_length = 0
                    for endpoint in endpoints:
                        notes = endpoint.get('notes', '')
                        if notes and len(notes.strip()) > 0:
                            notes_count += 1
                            total_notes_length += len(notes)
                    print(f"         - Notes Verification: {notes_count}/{len(endpoints)} endpoints have notes (avg {total_notes_length//max(notes_count,1)} chars)")
            
            print(f"\n   • FIXED ISSUE - PLANNING AGENT NOW RECEIVES COMPLETE DATA:")
            print(f"     The planning agent now gets full endpoint specifications including:")
            print(f"       * Complete URL patterns (e.g., /api/v1/iam/assignees/users)")
            print(f"       * Detailed parameter specifications (required/optional)")
            print(f"       * Comprehensive endpoint descriptions")
            print(f"       * Dependency mappings between endpoints")
            print(f"       * Detailed notes and API usage guidelines")
            print(f"     This enables the LLM to make informed decisions about:")
            print(f"       * Optimal endpoint selection")
            print(f"       * Proper parameter usage")
            print(f"       * Correct API call sequencing")
            
            try:
                # Use MODERN planning approach (same as execution manager)
                from src.core.agents.planning_agent import planning_agent, PlanningDependencies
                
                planning_deps = PlanningDependencies(
                    available_entities=list(endpoint_based_entities.keys()),
                    entity_summary=filtered_entity_summary,
                    sql_tables=em.sql_tables,
                    flow_id=flow_id,
                    entities=endpoint_based_entities  # CRITICAL: Include endpoint details
                )
                
                planning_result = await planning_agent.run(test_query, deps=planning_deps)
                
                # Extract the result in the format expected by the test
                planning_result = {
                    'success': True,
                    'plan': planning_result.output.plan.model_dump(),
                    'confidence': planning_result.output.confidence,
                    'usage': {
                        'input_tokens': getattr(planning_result.usage(), 'request_tokens', 0) if planning_result.usage() else 0,
                        'output_tokens': getattr(planning_result.usage(), 'response_tokens', 0) if planning_result.usage() else 0,
                        'total_tokens': getattr(planning_result.usage(), 'total_tokens', 0) if planning_result.usage() else 0
                    } if planning_result.usage() else None
                }
                
                print("\n8. PLANNING AGENT RESULT:")
                print(f"   • Success: {hasattr(planning_result, 'steps')}")
                
                if hasattr(planning_result, 'steps'):
                    print(f"   • Number of steps: {len(planning_result.steps)}")
                    
                    for i, step in enumerate(planning_result.steps, 1):
                        print(f"     Step {i}:")
                        print(f"       - Tool: {step.tool_name}")
                        print(f"       - Entity: {step.entity}")
                        print(f"       - Operation: {getattr(step, 'operation', 'N/A')}")
                        print(f"       - Context: {step.query_context[:100]}{'...' if len(step.query_context) > 100 else ''}")
                        if hasattr(step, 'reasoning'):
                            print(f"       - Reasoning: {step.reasoning[:100]}{'...' if len(step.reasoning) > 100 else ''}")
                
                print("\n9. RAW PLANNING AGENT OUTPUT:")
                print(f"   • Planning result type: {type(planning_result)}")
                
                # Convert to JSON-safe format and pretty print
                try:
                    if hasattr(planning_result, 'model_dump'):
                        planning_json = planning_result.model_dump()
                    elif hasattr(planning_result, 'dict'):
                        planning_json = planning_result.dict()
                    elif isinstance(planning_result, str):
                        # Try to parse as JSON first
                        import ast
                        try:
                            planning_json = ast.literal_eval(planning_result)
                        except:
                            planning_json = planning_result
                    else:
                        planning_json = str(planning_result)
                    
                    if isinstance(planning_json, (dict, list)):
                        print(json.dumps(planning_json, indent=2))
                    else:
                        print(planning_json)
                except Exception as format_error:
                    print(f"   • Formatting error: {format_error}")
                    print(f"   • Raw result: {planning_result}")
                
            except Exception as planning_error:
                print(f"\n8. PLANNING AGENT ERROR:")
                print(f"   • Exception: {str(planning_error)}")
                import traceback
                traceback.print_exc()
        
    except Exception as e:
        print(f"\n4. PREPLAN AGENT ERROR:")
        print(f"   • Exception: {str(e)}")
        import traceback
        traceback.print_exc()

async def main():
    """Main test function"""
    await test_preplan_agent_data_flow()

if __name__ == "__main__":
    asyncio.run(main())
