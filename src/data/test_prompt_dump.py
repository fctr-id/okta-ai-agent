"""
Simple test to dump the complete system prompt sent to Planning Agent
"""
import asyncio
import sys
import os

# Add path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from planning_agent import generate_execution_plan
from utils.logging import generate_correlation_id

async def test_prompt_dump():
    """Test to dump the complete system prompt"""
    
    # Use simple format from simple_reference_sample.json
    import json
    
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    simple_ref_path = os.path.join(project_root, "src", "data", "lightweight_api_reference.json")
    
    # Load lightweight reference format
    try:
        with open(simple_ref_path, 'r') as f:
            simple_data = json.load(f)
            
            # Extract entities list for available_entities parameter
            available_entities = [entity['entity'] for entity in simple_data['entities']]
            
            # Format entity_summary from entities for Planning Agent
            entity_summary = {}
            for entity in simple_data['entities']:
                entity_summary[entity['entity']] = {
                    'operations': entity['operations'],
                    'methods': []  # Planning Agent expects this even if empty
                }
            
            # SQL tables format - columns should be simple string list
            sql_tables = {}
            for table in simple_data['sql_tables']:
                sql_tables[table['name']] = {
                    'columns': table['columns']  # Keep as simple list of strings
                }
            
            print(f"✅ Loaded lightweight reference: {len(available_entities)} entities, {len(sql_tables)} tables")
    except Exception as e:
        print(f"❌ Failed to load lightweight reference: {e}")
        return
    
    flow_id = generate_correlation_id("prompt_test")
    
    query = "Find users in the group sso-super-admins and fetch their apps, groups and roles"
    
    print("🔍 Testing Planning Agent Prompt Dump...")
    print(f"📝 Query: {query}")
    print("=" * 70)
    
    # This will dump the complete system prompt in logs
    result = await generate_execution_plan(
        query=query,
        available_entities=available_entities,
        entity_summary=entity_summary,
        sql_tables=sql_tables,
        flow_id=flow_id
    )
    
    print("\n✅ Prompt dump completed - check logs for full system prompt")
    print(f"🔗 Correlation ID: {flow_id}")
    
    if result.get('success'):
        print(f"✅ Planning successful: {len(result['plan']['steps'])} steps generated")
    else:
        print(f"❌ Planning failed: {result.get('error', 'Unknown error')}")
    
    return result

if __name__ == "__main__":
    result = asyncio.run(test_prompt_dump())
