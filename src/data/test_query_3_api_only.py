#!/usr/bin/env python3
"""
Test Query 3: API-ONLY Forced Execution
Tests the same query as Query 2 but with explicit SQL restriction
Query: "Find users in the group sso-super-admins and fetch their apps, groups and roles and DO NOT use the local SQL DB"
Expected: Pure API workflow with multiple API calls
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from real_world_hybrid_executor import RealWorldHybridExecutor
import json
from datetime import datetime

def test_api_only_query():
    """Test API-only execution with SQL explicitly forbidden"""
    
    print("🚀 Starting API-ONLY Hybrid Query Test...")
    print("🧪 END-TO-END TEST: QUERY 3 (API-ONLY FORCED)")
    print("=" * 70)
    
    # Modified query with explicit SQL restriction
    query = "Find users in the group sso-super-admins and fetch their apps, groups and roles and DO NOT use the local SQL DB"
    
    print(f"🎯 QUERY 3: {query}")
    print("Expected workflow: API-ONLY (SQL forbidden)")
    print("=" * 70)
    
    try:
        # Initialize executor
        executor = RealWorldHybridExecutor()
        print(f"✅ RealWorldHybridExecutor initialized")
        
        # Execute the query
        print("🚀 EXECUTING API-ONLY QUERY")
        print("=" * 60)
        print(f"📝 Query: {query}")
        
        result = executor.execute_hybrid_query(query)
        
        print("\n🎯 QUERY 3 (API-ONLY) RESULTS:")
        print("=" * 50)
        
        # Analyze results
        success = result.get('success', False)
        print(f"✅ Overall Success: {success}")
        
        # Check workflow detection
        if 'llm1_plan' in result:
            llm1_plan = result['llm1_plan']
            print(f"🧠 LLM1 Planning:")
            print(f"   📋 Steps: {len(llm1_plan.get('steps', []))}")
            print(f"   🎯 Entities: {llm1_plan.get('entities', [])}")
            print(f"   🧠 Reasoning: {llm1_plan.get('reasoning', 'N/A')[:100]}...")
            print(f"   🎯 Confidence: {llm1_plan.get('confidence', 0)}%")
        
        # Analyze step results
        if 'step_results' in result:
            step_results = result['step_results']
            print(f"📊 WORKFLOW ANALYSIS:")
            
            sql_steps = 0
            api_steps = 0
            total_records = 0
            
            for step_name, step_data in step_results.items():
                if isinstance(step_data, dict):
                    if step_data.get('type') == 'sql':
                        sql_steps += 1
                        records = len(step_data.get('data', []))
                        total_records += records
                        print(f"   💾 SQL Step: {step_name} - {records} records")
                    elif step_data.get('type') == 'api':
                        api_steps += 1
                        endpoints = len(step_data.get('endpoints', []))
                        print(f"   🔗 API Step: {step_name} - {endpoints} endpoints")
            
            print(f"   📋 Detected: {'API-ONLY' if sql_steps == 0 else 'HYBRID'}")
            print(f"   ✅ API-ONLY Expected: {'✅ YES' if sql_steps == 0 else '❌ NO (found SQL)'}")
            print(f"   🎯 API Steps: {api_steps}")
            print(f"   💾 SQL Steps: {sql_steps}")
        
        # Component analysis
        print(f"📊 COMPONENT RESULTS:")
        
        # SQL data check
        sql_data = []
        if 'sql_results' in result:
            sql_data = result['sql_results']
        elif 'data' in result and isinstance(result['data'], list):
            # Check if data comes from SQL
            sql_data = result['data'] if 'sql' in str(result).lower() else []
        
        print(f"   💾 SQL Success: {len(sql_data) > 0}")
        print(f"   💾 SQL Records: {len(sql_data)}")
        
        # API data check
        api_calls = result.get('api_calls_made', 0)
        endpoints_filtered = result.get('endpoints_filtered', 0)
        
        print(f"   🔍 Endpoints Filtered: {endpoints_filtered}")
        print(f"   🔗 API Calls Made: {api_calls}")
        
        # Code generation check
        code_generated = result.get('code_generated', False)
        code_length = len(result.get('generated_code', ''))
        code_executed = result.get('code_executed', False)
        
        print(f"   🤖 Code Generated: {'✅' if code_generated else '❌'}")
        print(f"   🤖 Code Length: {code_length} chars")
        print(f"   🚀 Code Executed: {'✅' if code_executed else '❌'}")
        
        # Results processing
        total_records = 0
        if 'data' in result:
            total_records = len(result['data']) if isinstance(result['data'], list) else 1
        
        print(f"   📊 Total Records: {total_records}")
        
        # Processed results analysis
        if 'processed_results' in result:
            processed = result['processed_results']
            print(f"📋 PROCESSED RESULTS:")
            print(f"   📝 Summary Type: {type(processed).__name__} with {len(processed) if isinstance(processed, (dict, list)) else 'N/A'} keys")
            
            if isinstance(processed, dict):
                print(f"   📋 Keys: {list(processed.keys())}")
                for key, value in processed.items():
                    if key in ['display_type', 'content', 'metadata']:
                        if key == 'content' and isinstance(value, list) and value:
                            print(f"   📊 {key}: {type(value).__name__}[{len(value)}] - Sample: {str(value[0])[:100]}...")
                        else:
                            print(f"   📊 {key}: {str(value)[:100]}...")
        
        # Success metrics
        print(f"🎉 QUERY 3 (API-ONLY) SUCCESS METRICS:")
        
        # Check if SQL was actually avoided
        sql_avoided = len(sql_data) == 0
        data_collected = total_records > 0 or api_calls > 0
        
        print(f"   ✅ SQL Avoided: {'✅' if sql_avoided else '❌'}")
        print(f"   ✅ Data Collection: {'✅' if data_collected else '❌'}")
        print(f"   ✅ Code Generation: {'✅' if code_generated else 'N/A (may be skipped)'}")
        print(f"   ✅ Code Execution: {'✅' if code_executed else '❌'}")
        print(f"   ✅ End-to-End: {'✅' if success else '❌'}")
        
        print(f"   📊 Data Details:")
        print(f"      • API Calls: {api_calls}")
        print(f"      • SQL Records: {len(sql_data)}")
        print(f"      • Results Processed: {'✅' if 'processed_results' in result else '❌'}")
        
        # Final assessment
        if sql_avoided and data_collected:
            result_status = "✅ FULL SUCCESS"
        elif sql_avoided:
            result_status = "⚠️ PARTIAL SUCCESS - SQL avoided but limited data"
        elif data_collected:
            result_status = "⚠️ PARTIAL SUCCESS - Data collected but SQL used"
        else:
            result_status = "❌ FAILURE"
        
        print("=" * 70)
        print(f"🎯 QUERY 3 (API-ONLY) RESULT: {result_status}")
        print("=" * 70)
        
        return success
        
    except Exception as e:
        print(f"❌ Error during API-only test: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 API-ONLY Query Test (Query 3)")
    print("Testing explicit SQL restriction with API-only execution")
    print()
    
    success = test_api_only_query()
    
    print(f"\n🏁 Test completed with result: {'✅ SUCCESS' if success else '❌ FAILURE'}")
