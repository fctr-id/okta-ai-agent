"""
Test the improved planning agent with SQL-first data availability mapping
"""

import asyncio
import json
from planning_agent import generate_execution_plan

async def test_group_membership_query():
    """Test the classic group membership query that was using API incorrectly"""
    
    # Mock the data that would be provided to the planning agent
    available_entities = ["group", "user", "system_log", "application"]
    
    entity_summary = {
        "group": {
            "operations": ["list", "get", "list_members", "create", "update", "delete"],
            "methods": []
        },
        "user": {
            "operations": ["list", "get", "create", "update", "delete", "list_groups", "list_app_links"],
            "methods": []
        },
        "system_log": {
            "operations": ["list_events"],
            "methods": []
        },
        "application": {
            "operations": ["list", "get", "list_users", "list_groups"],
            "methods": []
        }
    }
    
    sql_tables = {
        "users": {
            "columns": ["id", "okta_id", "email", "first_name", "last_name", "login", "status", "department"],
            "fast_operations": ["bulk_select", "email_lookup", "status_filtering"]
        },
        "groups": {
            "columns": ["id", "okta_id", "name", "description", "created_at"],
            "fast_operations": ["name_lookup", "bulk_select"]
        },
        "user_group_memberships": {
            "columns": ["user_okta_id", "group_okta_id", "tenant_id", "created_at"],
            "fast_operations": ["group_member_lookup", "user_groups_lookup"]
        },
        "applications": {
            "columns": ["id", "okta_id", "name", "label", "status", "sign_on_mode"],
            "fast_operations": ["name_lookup", "status_filtering"]
        },
        "user_application_assignments": {
            "columns": ["user_okta_id", "application_okta_id", "tenant_id", "assignment_id"],
            "fast_operations": ["user_app_lookup", "app_users_lookup"]
        },
        "group_application_assignments": {
            "columns": ["group_okta_id", "application_okta_id", "tenant_id", "assignment_id"],
            "fast_operations": ["group_app_lookup", "app_groups_lookup"]
        }
    }
    
    # Test query that should use SQL only
    query = "get all users in the sso-super-admins group and their applications"
    
    print("🧪 Testing improved planning agent...")
    print(f"Query: {query}")
    print(f"Available SQL tables: {list(sql_tables.keys())}")
    print()
    
    result = await generate_execution_plan(
        query=query,
        available_entities=available_entities,
        entity_summary=entity_summary,
        sql_tables=sql_tables,
        flow_id="test_001"
    )
    
    print("📊 Planning Result:")
    print(json.dumps(result, indent=2))
    
    if result.get('success'):
        plan = result.get('plan', {})
        steps = plan.get('steps', [])
        
        print(f"\n✅ Plan generated with {len(steps)} steps:")
        for i, step in enumerate(steps, 1):
            print(f"  Step {i}: {step['tool_name']} - {step['entity']}")
            if step.get('operation'):
                print(f"    Operation: {step['operation']}")
            print(f"    Context: {step['query_context']}")
            print()
        
        # Check if it's using SQL-first approach
        if len(steps) == 1 and steps[0]['tool_name'] == 'sql':
            print("🎉 SUCCESS: Using single SQL step as expected!")
        else:
            print("❌ ISSUE: Still not using optimal SQL-first approach")
            api_steps = [s for s in steps if s['tool_name'] == 'api']
            if api_steps:
                print(f"   Found {len(api_steps)} unnecessary API steps:")
                for step in api_steps:
                    print(f"   - {step['entity']}.{step.get('operation', 'N/A')}")
    else:
        print(f"❌ Planning failed: {result.get('error')}")

if __name__ == "__main__":
    asyncio.run(test_group_membership_query())
