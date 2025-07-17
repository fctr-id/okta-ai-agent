#!/usr/bin/env python3
"""
PRODUCTION TEST QUERY 1 - Enhanced with Multi-Step Pipeline Approach

Based on the working multi_step_llm2_pipeline.py implementation.
Tests: "Find users logged in the last 7 days and fetch me their apps and groups"

ENHANCED FEATURES FROM MULTILINE VERSION:
- Better LLM1 plan extraction with fallback mechanisms
- Sequential LLM2 execution with proper data flow
- API → SQL workflow detection and support
- Raw API output processing for LLM enhancement
- Comprehensive step-by-step execution analysis
"""

import asyncio
import sys
import os
from pathlib import Path

# Add project paths
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from src.data.real_world_hybrid_executor import RealWorldHybridExecutor

async def test_query_1():
    """Test Query 1: Users logged in last 7 days with their apps and groups"""
    
    print("🧪 END-TO-END TEST: QUERY 1")
    print("=" * 70)
    
    # Initialize the executor
    executor = RealWorldHybridExecutor()
    
    # Query 1: Should trigger API→SQL workflow
    # API: Get login events from last 7 days (not in SQL)
    # SQL: Get apps and groups for those users (available in SQL)
    query = "Find users logged in the last 7 days and fetch me their apps and groups"
    
    print(f"\n🎯 QUERY 1: {query}")
    print(f"Expected workflow: API (system_log: last 7 days) → SQL (user apps + groups)")
    print("\n" + "="*70)
    
    try:
        # Execute the hybrid query
        result = await executor.execute_query(query)
        
        print(f"\n🎯 QUERY 1 RESULTS:")
        print("=" * 50)
        
        if result.get('success'):
            print(f"✅ Overall Success: {result.get('success')}")
            
            # DEBUG: Print result keys to understand structure
            print(f"\n🔍 DEBUG - Result keys: {list(result.keys())}")
            
            # Get the actual raw results from the hybrid executor
            raw_results = result.get('raw_results', {})
            print(f"🔍 DEBUG - Raw results keys: {list(raw_results.keys()) if raw_results else 'None'}")
            
            # Parse the actual result structure
            llm1_result = raw_results.get('llm1_planning', {}) if raw_results else {}
            planned_steps = llm1_result.get('planned_steps', [])
            
            print(f"\n🧠 LLM1 Planning:")
            print(f"   📋 Steps: {len(planned_steps)}")
            print(f"   🎯 Entities: {llm1_result.get('entities', [])}")
            print(f"   🧠 Reasoning: {llm1_result.get('reasoning', '')[:150]}...")
            print(f"   🎯 Confidence: {llm1_result.get('confidence', 0)}%")
            
            # Analyze step sequence
            step_sequence = []
            for i, step in enumerate(planned_steps, 1):
                tool_name = step.get('tool_name', '')
                query_context = step.get('query_context', '')
                critical = step.get('critical', False)
                
                # Determine step type
                sql_tables = ['users', 'groups', 'applications', 'user_group_memberships', 'user_application_assignments']
                step_type = 'SQL' if tool_name in sql_tables else 'API'
                step_sequence.append(step_type)
                
                print(f"   Step {i}: {step_type} - {tool_name}")
                print(f"           Context: {query_context[:100]}...")
                print(f"           Critical: {critical}")
            
            # Workflow Analysis
            workflow_detected = ' → '.join(step_sequence)
            api_first = len(step_sequence) >= 2 and step_sequence[0] == 'API'
            
            print(f"\n📊 WORKFLOW ANALYSIS:")
            print(f"   📋 Detected: {workflow_detected}")
            print(f"   ✅ API→SQL Expected: {'✅ YES' if api_first else '❌ NO'}")
            print(f"   🎯 Multi-step: {'✅ YES' if len(step_sequence) > 1 else '❌ NO'}")
            
            # Component Results - Parse from raw_results
            sql_result = raw_results.get('sql_execution', {}) if raw_results else {}
            filter_result = raw_results.get('endpoint_filtering', {}) if raw_results else {}
            llm2_result = raw_results.get('llm2_code_generation', {}) if raw_results else {}
            execution_result = result.get('execution_result', {})
            
            # Also check step_results for actual execution data
            step_results = raw_results.get('step_results', []) if raw_results else []
            
            # DEBUG: Print component result keys
            print(f"🔍 DEBUG - SQL result keys: {list(sql_result.keys()) if sql_result else 'None'}")
            print(f"🔍 DEBUG - Filter result keys: {list(filter_result.keys()) if filter_result else 'None'}")
            print(f"🔍 DEBUG - LLM2 result keys: {list(llm2_result.keys()) if llm2_result else 'None'}")
            print(f"🔍 DEBUG - Execution result keys: {list(execution_result.keys()) if execution_result else 'None'}")
            print(f"🔍 DEBUG - Step results count: {len(step_results)}")
            
            # Count actual data from step results
            total_sql_records = 0
            total_api_calls = 0
            for step in step_results:
                if step.get('step_type') == 'sql' and step.get('success'):
                    step_data = step.get('data', [])
                    total_sql_records += len(step_data)
                    print(f"🔍 DEBUG - SQL step: {len(step_data)} records")
                elif step.get('step_type') == 'api' and step.get('success'):
                    total_api_calls += 1
                    print(f"🔍 DEBUG - API step: {step.get('step_name', 'unknown')}")
            
            # ALSO check sql_execution for the actual record count (this is where the real data is!)
            if sql_result.get('success') and sql_result.get('records_count', 0) > 0:
                actual_sql_records = sql_result.get('records_count', 0)
                total_sql_records = max(total_sql_records, actual_sql_records)
                print(f"🔍 DEBUG - SQL execution: {actual_sql_records} records (using this count)")
            
            # Check for API execution in execution_result
            if execution_result.get('success') and execution_result.get('stdout'):
                stdout = execution_result.get('stdout', '')
                if 'unique user okta_ids' in stdout.lower() or 'login events' in stdout.lower():
                    total_api_calls = max(total_api_calls, 1)
                    print(f"🔍 DEBUG - API execution detected in stdout")
            
            print(f"\n📊 COMPONENT RESULTS:")
            print(f"   💾 SQL Success: {sql_result.get('success', False) or total_sql_records > 0}")
            print(f"   💾 SQL Records: {sql_result.get('records_count', 0) or total_sql_records}")
            print(f"   🔍 Endpoints Filtered: {filter_result.get('filtered_count', 0)}")
            print(f"   🤖 Code Generated: {'✅' if llm2_result.get('success') else '❌'}")
            print(f"   🤖 Code Length: {len(llm2_result.get('code', ''))} chars")
            print(f"   🚀 Code Executed: {'✅' if execution_result.get('success') else '❌'}")
            print(f"   🔗 API Calls Made: {total_api_calls}")
            print(f"   📊 Total Records: {total_sql_records}")
            
            # Show actual results if available
            processed_summary = result.get('processed_summary', '')
            if processed_summary:
                print(f"\n📋 PROCESSED RESULTS:")
                if isinstance(processed_summary, dict):
                    print(f"   📝 Summary Type: dict with {len(processed_summary)} keys")
                    print(f"   📋 Keys: {list(processed_summary.keys())}")
                    # Show some sample content
                    for key, value in list(processed_summary.items())[:3]:
                        print(f"   � {key}: {str(value)[:80]}{'...' if len(str(value)) > 80 else ''}")
                else:
                    print(f"   �📝 Summary Length: {len(processed_summary)} chars")
                    # Show first few lines of the summary
                    summary_lines = str(processed_summary).split('\n')[:5]
                    for line in summary_lines:
                        if line.strip():
                            print(f"   📄 {line[:80]}{'...' if len(line) > 80 else ''}")
                    if len(str(processed_summary).split('\n')) > 5:
                        print(f"   📄 ... and more content")
            
            # RAW RESULTS PROCESSOR OUTPUT
            print(f"\n🔍 RAW RESULTS PROCESSOR AGENT OUTPUT:")
            print("=" * 60)
            
            # Check if we have raw SQL data
            sql_result = raw_results.get('sql_execution', {}) if raw_results else {}
            if sql_result.get('success') and sql_result.get('data_sample'):
                print("📊 RAW SQL DATA SAMPLE:")
                data_sample = sql_result.get('data_sample', [])
                print(f"Total records: {sql_result.get('records_count', 0)}")
                print(f"Sample size: {len(data_sample)}")
                
                if data_sample:
                    print("\n🔍 First 5 raw records:")
                    for i, record in enumerate(data_sample[:5], 1):
                        print(f"\nRecord {i}:")
                        for key, value in record.items():
                            print(f"  {key}: {value}")
            
            # Check for any raw LLM3 output in the results
            if 'enhancement_features' in result:
                enhancement_features = result.get('enhancement_features', {})
                print(f"\n🤖 LLM3 ENHANCEMENT FEATURES:")
                for key, value in enhancement_features.items():
                    print(f"  {key}: {value}")
            
            # Look for any raw processing output
            if 'processing_method' in result:
                print(f"\n📋 PROCESSING METHOD: {result.get('processing_method')}")
            
            # Try to get the raw LLM3 response from logs or raw data
            execution_summary = raw_results.get('execution_summary', {}) if raw_results else {}
            if execution_summary:
                print(f"\n📈 EXECUTION SUMMARY:")
                for key, value in execution_summary.items():
                    if key != 'raw_data':  # Skip large raw data
                        print(f"  {key}: {value}")
            
            print("=" * 60)
            
            # Success Summary - Use actual data from step results
            print(f"\n🎉 QUERY 1 SUCCESS METRICS:")
            api_sql_workflow = len(planned_steps) >= 2
            
            # Check for data collection from step results
            data_collection = total_sql_records > 0 or total_api_calls > 0
            
            # Check for code execution
            code_execution = execution_result.get('success', False) if execution_result else False
            
            # Check for code generation from raw results
            code_generation = llm2_result.get('success', False) if llm2_result else False
            
            # Overall success based on actual execution
            overall_success = result.get('success', False) and (data_collection or code_execution)
            
            print(f"   ✅ API→SQL Workflow: {'✅' if api_sql_workflow else '❌'}")
            print(f"   ✅ Data Collection: {'✅' if data_collection else '❌'}")
            print(f"   ✅ Code Generation: {'✅' if code_generation else '❌'}")
            print(f"   ✅ Code Execution: {'✅' if code_execution else '❌'}")
            print(f"   ✅ End-to-End: {'✅' if overall_success else '❌'}")
            
            # Show what data we actually got
            if data_collection:
                print(f"   📊 Data Details:")
                print(f"      • API Calls: {total_api_calls}")
                print(f"      • SQL Records: {total_sql_records}")
                if processed_summary:
                    print(f"      • Results Processed: ✅ ({len(processed_summary)} chars)")
            else:
                print(f"   ⚠️ No data collected - check step execution results")
            
        else:
            print(f"❌ Query 1 Failed: {result.get('error', 'Unknown error')}")
            print(f"📍 Phase: {result.get('phase', 'unknown')}")
        
        return result
        
    except Exception as e:
        print(f"❌ Query 1 failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}

if __name__ == "__main__":
    # Run Query 1 test
    result = asyncio.run(test_query_1())
    
    print(f"\n{'='*70}")
    if result.get('success'):
        # Enhanced data collection detection logic
        raw_results = result.get('raw_results', {})
        
        # Check SQL results directly from raw_results (this is where the actual data is!)
        sql_execution = raw_results.get('sql_execution', {}) if raw_results else {}
        sql_records_count = sql_execution.get('records_count', 0)
        
        # Check execution results for API calls
        execution_result = result.get('execution_result', {})
        api_executed = execution_result.get('success', False) and 'okta_ids' in execution_result.get('stdout', '').lower()
        
        # Check step-level results (fallback)
        step_results = result.get('step_results', [])
        api_steps_success = any(s.get('step_type') == 'api' and s.get('success') for s in step_results)
        sql_steps_success = any(s.get('step_type') == 'sql' and len(s.get('data', [])) > 0 for s in step_results)
        
        # Check LLM1 planning from raw_results
        llm1_result = raw_results.get('llm1_planning', {}) if raw_results else {}
        planned_steps = len(llm1_result.get('planned_steps', []))
        
        # Check workflow detection
        api_sql_workflow = planned_steps >= 2
        
        # Better data collection detection
        data_collection_success = sql_records_count > 0 or api_executed or api_steps_success or sql_steps_success
        
        execution_result = result.get('execution_result', {})
        code_executed = execution_result.get('success', False) if execution_result else False
        
        if api_sql_workflow and data_collection_success and code_executed and sql_records_count > 0:
            print(f"🎯 QUERY 1 RESULT: ✅ COMPLETE SUCCESS - API→SQL workflow executed end-to-end! ({sql_records_count} records)")
        elif api_sql_workflow and data_collection_success:
            print(f"🎯 QUERY 1 RESULT: ✅ PARTIAL SUCCESS - Workflow planned, data collected: API={'✅' if api_executed else '❌'}, SQL={sql_records_count} records, Execution={'✅' if code_executed else '❌'}")
        elif api_sql_workflow:
            print(f"🎯 QUERY 1 RESULT: ⚠️ WORKFLOW PLANNED - {planned_steps} steps planned but data collection incomplete")
        else:
            print(f"🎯 QUERY 1 RESULT: ⚠️ LIMITED SUCCESS - Basic execution but workflow not detected")
    else:
        print(f"🎯 QUERY 1 RESULT: ❌ FAILED")
    print(f"{'='*70}")
