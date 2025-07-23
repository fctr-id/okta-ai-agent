#!/usr/bin/env python3
"""
PRODUCTION TEST QUERY 2 - MODERNIZED with Modern Execution Manager

Test Query 2: SQL→API Workflow
Find users of group sso-super-admins and fetch their apps, groups and assigned roles.

Expected workflow: 
1. SQL: Get users in the sso-super-admins group
2. API: Get application assignments and roles for those users

Uses the same interface as RealWorldHybridExecutor but with our simplified Modern Execution Manager.
"""

import asyncio
import sys
import os
from datetime import datetime

# Add local path for modern imports
sys.path.append(os.path.dirname(__file__))

from modern_execution_manager import modern_executor

async def test_query_2():
    """Test SQL→API workflow with group-based user query"""
    
    print("🎯 MODERN END-TO-END TEST: QUERY 2")
    print("=" * 70)
    
    # The query that should trigger SQL first, then API
    query = "Find users in the group sso-super-admins and fetch their apps, groups and roles"
    
    print(f"📝 Query: {query}")
    print(f"🔗 Expected workflow: SQL (group members) → API (app assignments + roles)")
    print(f"🕒 Test start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    try:
        # Execute the query using Modern Execution Manager (same interface as RealWorldHybridExecutor)
        print(f"\n🚀 Executing with Modern Execution Manager...")
        result = await modern_executor.execute_query(query)
        
        print(f"\n� EXECUTION RESULTS:")
        print("=" * 50)
        print(f"✅ Overall Success: {result.get('success', False)}")
        print(f"🔗 Correlation ID: {result.get('correlation_id', 'N/A')}")
        print(f"📋 Total Steps: {result.get('total_steps', 0)}")
        print(f"✅ Successful Steps: {result.get('successful_steps', 0)}")
        print(f"❌ Failed Steps: {result.get('failed_steps', 0)}")
        
        # Show step details
        step_results = result.get('step_results', [])
        if step_results:
        
        # Analyze the execution pattern
        raw_results = result.get('raw_results', {})
        
        # Initialize steps variable
        steps = []
        
        # Check LLM1 planning
        llm1_data = raw_results.get('llm1_planning', {})
        if llm1_data.get('success'):
            execution_plan = llm1_data.get('execution_plan', {})
            steps = execution_plan.get('steps', [])
            entities = execution_plan.get('entities', [])
            
            print(f"\n🧠 LLM1 Planning:")
            print(f"   📋 Steps: {len(steps)}")
            print(f"   🎯 Entities: {entities}")
            print(f"   🧠 Reasoning: {execution_plan.get('reasoning', 'N/A')[:100]}...")
            print(f"   🎯 Confidence: {execution_plan.get('confidence', 0)}%")
            
            for i, step in enumerate(steps, 1):
                # Determine step type based on entity and context
                entity_name = step.get('entity_name', '')
                context = step.get('context', '')
                step_type = "SQL" if entity_name in ['users', 'groups'] else "API"
                
                print(f"   Step {i}: {step_type} - {entity_name}")
                print(f"           Context: {context[:80]}...")
                print(f"           Critical: {step.get('critical', False)}")
        
        # Analyze workflow detection
        print(f"\n📊 WORKFLOW ANALYSIS:")
        execution_summary = raw_results.get('execution_summary', {})
        detected_workflow = "Unknown"
        
        # Look for SQL and API step results
        sql_results = raw_results.get('sql_execution', {})
        endpoint_results = raw_results.get('endpoint_filtering', {})
        
        has_sql = sql_results.get('success', False)
        has_api_filtering = endpoint_results.get('success', False)
        
        if has_sql and has_api_filtering:
            detected_workflow = "SQL→API"
        elif has_sql and not has_api_filtering:
            detected_workflow = "SQL Only"
        elif not has_sql and has_api_filtering:
            detected_workflow = "API Only"
        
        print(f"   📋 Detected: {detected_workflow}")
        print(f"   ✅ SQL→API Expected: {'✅ YES' if expected_workflow == 'SQL→API' else '❌ NO'}")
        print(f"   🎯 Multi-step: {'✅ YES' if len(steps) > 1 else '❌ NO'}")
        
        # Component analysis
        print(f"\n📊 COMPONENT RESULTS:")
        
        # SQL Results
        if has_sql:
            sql_count = sql_results.get('records_count', 0)
            print(f"   💾 SQL Success: True")
            print(f"   💾 SQL Records: {sql_count}")
        else:
            print(f"   💾 SQL Success: False")
        
        # API Results
        if has_api_filtering:
            filtered_count = endpoint_results.get('filtered_count', 0)
            print(f"   🔍 Endpoints Filtered: {filtered_count}")
        else:
            print(f"   🔍 Endpoints Filtered: 0")
        
        # Code Generation and Execution
        api_code_results = raw_results.get('api_code_generation', {})
        code_generated = api_code_results.get('success', False)
        code_length = api_code_results.get('code_length', 0)
        
        execution_results = raw_results.get('execution_result')
        code_executed = execution_results is not None
        
        print(f"   🤖 Code Generated: {'✅' if code_generated else '❌'}")
        print(f"   🤖 Code Length: {code_length} chars")
        print(f"   🚀 Code Executed: {'✅' if code_executed else '❌'}")
        print(f"   🔗 API Calls Made: {len(execution_results.get('step_results', [])) if execution_results else 0}")
        
        # Total records
        total_records = sql_count if has_sql else 0
        if execution_results:
            total_records += len(execution_results.get('step_results', []))
        
        print(f"   📊 Total Records: {total_records}")
        
        # Final results
        processed_summary = result.get('processed_summary', {})
        if processed_summary:
            print(f"\n📋 PROCESSED RESULTS:")
            print(f"   📝 Summary Type: {type(processed_summary).__name__} with {len(processed_summary)} keys")
            if isinstance(processed_summary, dict):
                print(f"   📋 Keys: {list(processed_summary.keys())}")
                for key, value in processed_summary.items():
                    if isinstance(value, str):
                        preview = value[:50] + "..." if len(value) > 50 else value
                        print(f"   � {key}: {preview}")
                    else:
                        print(f"   � {key}: {value}")
        
        # Success metrics
        print(f"\n🎉 {test_name} SUCCESS METRICS:")
        
        workflow_success = detected_workflow == expected_workflow
        data_success = total_records > 0
        processing_success = bool(processed_summary)
        
        print(f"   ✅ SQL→API Workflow: {'✅' if workflow_success else '❌'}")
        print(f"   ✅ Data Collection: {'✅' if data_success else '❌'}")
        print(f"   ✅ Code Generation: {'✅' if code_generated else 'N/A (may be skipped)'}")
        print(f"   ✅ Code Execution: {'✅' if code_executed else 'N/A (may be skipped)'}")
        print(f"   ✅ End-to-End: {'✅' if result.get('success') else '❌'}")
        
        # Export info
        csv_path = result.get('csv_export_path')
        if csv_path:
            print(f"   📊 Data Details:")
            print(f"      • API Calls: {len(execution_results.get('step_results', [])) if execution_results else 0}")
            print(f"      • SQL Records: {sql_count if has_sql else 0}")
            print(f"      • Results Processed: {'✅' if processed_summary else '❌'} ({len(str(processed_summary))} chars)")
            print(f"      • CSV Export: ✅ {csv_path}")
        
        print(f"\n{'='*70}")
        final_status = "✅ COMPLETE SUCCESS" if result.get('success') and workflow_success else "⚠️ PARTIAL SUCCESS" if result.get('success') else "❌ FAILED"
        workflow_desc = f"{detected_workflow} workflow executed successfully!" if workflow_success else f"Expected {expected_workflow}, got {detected_workflow}"
        print(f"🎯 {test_name} RESULT: {final_status} - {workflow_desc} ({total_records} records collected)")
        print(f"{'='*70}")
        
        return result.get('success', False)
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚀 Starting SQL→API Hybrid Query Test...")
    result = asyncio.run(test_query_2())
    print(f"\n🏁 Test completed with result: {'✅ SUCCESS' if result else '❌ FAILURE'}")
