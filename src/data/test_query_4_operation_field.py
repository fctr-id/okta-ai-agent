#!/usr/bin/env python3
"""
Test Query 4: Test LLM1 Operation Field
Quick test to verify LLM1 outputs operation field and executor uses it correctly
Query: "Find users of group sso-super-admins. DO NOT use SQL database."
Expected: LLM1 outputs operation: "list_members" and executor finds the correct endpoint
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from real_world_hybrid_executor import RealWorldHybridExecutor
import json
from datetime import datetime

import asyncio

async def test_llm1_operation_field():
    """Test that LLM1 outputs operation field and executor uses it"""
    
    print("🚀 Testing LLM1 Operation Field Output...")
    print("🧪 OPERATION FIELD TEST: QUERY 4")
    print("=" * 70)
    
    # Simple query to test operation field
    query = "Find users of group sso-super-admins. DO NOT use SQL database."
    
    print(f"🎯 QUERY 4: {query}")
    print("Expected: LLM1 outputs 'operation: list_members' and executor finds /groups/:groupId/users endpoint")
    print("=" * 70)
    
    try:
        # Initialize executor
        executor = RealWorldHybridExecutor()
        print(f"✅ RealWorldHybridExecutor initialized")
        
        # Execute only the LLM1 planning phase to see what it outputs
        print("🧠 TESTING LLM1 PLANNING PHASE ONLY")
        print("=" * 50)
        
        # Call LLM1 planning directly
        correlation_id = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        llm1_result = await executor._execute_llm1_planning(query, correlation_id)
        
        if not llm1_result.get('success', False):
            print(f"❌ LLM1 planning failed: {llm1_result.get('error', 'Unknown error')}")
            return False
            
        llm1_plan = llm1_result.get('llm1_plan', {})
        steps = llm1_plan.get('plan', {}).get('steps', [])
        
        print(f"📋 LLM1 PLAN ANALYSIS:")
        print(f"   📊 Steps: {len(steps)}")
        
        operation_found = False
        correct_operation = False
        
        for i, step in enumerate(steps, 1):
            tool_name = step.get('tool_name', '')
            operation = step.get('operation', '')
            query_context = step.get('query_context', '')
            
            print(f"   Step {i}:")
            print(f"      🎯 Entity: {tool_name}")
            print(f"      ⚙️ Operation: {operation}")
            print(f"      📝 Context: {query_context}")
            
            if operation:
                operation_found = True
                if operation == 'list_members' and tool_name == 'group':
                    correct_operation = True
                    print(f"      ✅ CORRECT: Found 'list_members' operation for group entity")
                else:
                    print(f"      ⚠️ Operation found but may not be optimal: {operation}")
            else:
                print(f"      ❌ NO OPERATION FIELD")
        
        # Test endpoint filtering with the LLM1 plan
        print(f"\n🔍 TESTING ENDPOINT FILTERING")
        print("=" * 40)
        
        from real_world_hybrid_executor import ExecutionPlanResponse
        llm1_response = ExecutionPlanResponse(**llm1_plan)
        
        filtering_result = executor.filter_endpoints(llm1_response)
        
        filtered_endpoints = filtering_result.get('filtered_endpoints', [])
        
        print(f"📊 FILTERING RESULTS:")
        print(f"   🔍 Endpoints found: {len(filtered_endpoints)}")
        
        correct_endpoint_found = False
        for endpoint in filtered_endpoints:
            url_pattern = endpoint.get('url_pattern', '')
            operation = endpoint.get('operation', '')
            name = endpoint.get('name', '')
            
            print(f"   • {url_pattern} ({operation}) - {name}")
            
            if '/groups/:groupId/users' in url_pattern and operation == 'list_members':
                correct_endpoint_found = True
                print(f"     ✅ CORRECT ENDPOINT FOUND!")
        
        # Results summary
        print(f"\n🎉 TEST RESULTS:")
        print("=" * 30)
        print(f"   ✅ LLM1 Operation Field: {'✅ YES' if operation_found else '❌ NO'}")
        print(f"   ✅ Correct Operation: {'✅ YES' if correct_operation else '❌ NO'}")
        print(f"   ✅ Correct Endpoint: {'✅ YES' if correct_endpoint_found else '❌ NO'}")
        
        overall_success = operation_found and correct_operation and correct_endpoint_found
        
        print(f"\n🏆 OVERALL RESULT: {'✅ SUCCESS' if overall_success else '❌ NEEDS FIX'}")
        
        if not overall_success:
            print("\n🔧 NEEDED FIXES:")
            if not operation_found:
                print("   • LLM1 needs to output 'operation' field")
            if not correct_operation:
                print("   • LLM1 needs to output 'list_members' for group member queries")
            if not correct_endpoint_found:
                print("   • Executor needs to find /groups/:groupId/users endpoint")
        
        return overall_success
        
    except Exception as e:
        print(f"❌ Error during operation field test: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 LLM1 Operation Field Test (Query 4)")
    print("Testing that LLM1 outputs explicit operations and executor uses them")
    print()
    
    success = asyncio.run(test_llm1_operation_field())
    
    print(f"\n🏁 Test completed with result: {'✅ SUCCESS' if success else '❌ FAILURE'}")
