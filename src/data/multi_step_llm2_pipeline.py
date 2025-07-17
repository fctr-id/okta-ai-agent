#!/usr/bin/env python3
"""
MULTI-STEP LLM2 PIPELINE - CORE PRODUCTION COMPONENT

This is a critical production file that implements the breakthrough multi-step LLM2 approach.
DO NOT DELETE - This replaces the complex enhanced orchestrator with a simpler, more effective solution.

WHAT THIS DOES:
- LLM1 Planning: Analyzes query and identifies required entities and steps
- SQL Execution: Gets foundational data with proper okta_ids for API integration  
- Sequential LLM2 Execution: One separate LLM2 call per API step (instead of one big combined call)
- Data Flow: Each API step builds on results from previous steps
- Code Execution: Each step executes its own generated code

ARCHITECTURE:
Pipeline: LLM1 → SQL → Multiple Sequential LLM2 calls (one per API step) → Combined Results

BREAKTHROUGH: This solves the dependency problem between API calls by executing them sequentially
with accumulated context, rather than trying to orchestrate everything in one big LLM2 call.

EXECUTIONMANAGER ENHANCEMENTS:
- Now uses enhanced step execution with context passing
- Improved error handling and dependency resolution  
- Better data flow between SQL and API steps
- Context-aware step execution from RealWorldHybridExecutor
"""

import asyncio
import sys
import os
from pathlib import Path

# Add the project root to the path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from data.real_world_hybrid_executor import RealWorldHybridExecutor

async def execute_multi_step_llm2_pipeline():
    """
    CORE PRODUCTION FUNCTION: Execute multi-step LLM2 pipeline with data flow
    
    This is the main breakthrough implementation that replaces complex orchestrators
    with a simple, effective sequential approach.
    """
    
    print("� Testing Multi-Step LLM2 Pipeline with Data Flow")
    print("=" * 60)
    
    executor = RealWorldHybridExecutor()
    
    # TESTING API → SQL DIRECTION (flipped query)
    # Original SQL → API: "Find users in group sso-super-admins, get their applications, roles and their last 7 days login activity"
    query = "Find users who logged in the last 7 days and fetch their group memberships, then get their applications"
    
    print(f"📝 Test Query (API → SQL): {query}")
    print("-" * 50)
    
    try:
        # Phase 1: Get the initial execution results (LLM1 + SQL + basic endpoint filtering)
        print("🧠 PHASE 1: INITIAL EXECUTION (LLM1 + SQL)")
        print("=" * 45)
        
        result = await executor.execute_query(query)
        
        if not result['success']:
            print(f"❌ Failed: {result.get('error')}")
            return result
            
        # Extract the basic results
        llm1_result = result.get('llm1_planning', {})
        sql_result = result.get('sql_execution', {})
        filter_result = result.get('endpoint_filtering', {})
        
        # DEBUG: Check full result structure for plan details
        print(f"🔍 DEBUG Full result keys: {list(result.keys())}")
        if 'llm1_planning' in result:
            print(f"🔍 DEBUG LLM1 planning keys: {list(result['llm1_planning'].keys())}")
        if 'execution_summary' in result:
            print(f"🔍 DEBUG Execution summary keys: {list(result['execution_summary'].keys())}")
        if 'execution_result' in result:
            print(f"🔍 DEBUG Execution result keys: {list(result['execution_result'].keys())}")
            # Check if the full LLM1 plan is in execution_result
            exec_result = result['execution_result']
            if 'llm1_result' in exec_result:
                print(f"   LLM1 result keys: {list(exec_result['llm1_result'].keys())}")
                if 'llm1_plan' in exec_result['llm1_result']:
                    print(f"   LLM1 plan keys: {list(exec_result['llm1_result']['llm1_plan'].keys())}")
                    if 'plan' in exec_result['llm1_result']['llm1_plan']:
                        plan = exec_result['llm1_result']['llm1_plan']['plan']
                        print(f"   Plan keys: {list(plan.keys())}")
                        if 'steps' in plan:
                            print(f"   Found {len(plan['steps'])} steps in execution_result!")
        
        print(f"✅ Phase 1 Results:")
        print(f"   📋 Entities: {llm1_result.get('entities', [])}")
        print(f"   📊 Steps: {llm1_result.get('steps_count', 0)}")
        print(f"   💾 SQL Records: {sql_result.get('records_count', 0)}")
        print(f"   🔗 Filtered Endpoints: {filter_result.get('filtered_count', 0)}")
        
        # Get the LLM1 plan to identify API steps from entities
        execution_summary = result.get('execution_summary', {})
        
        # Extract entities from LLM1 results
        entities = llm1_result.get('entities', [])
        print(f"🔍 Found entities: {entities}")
        
        # DEBUG: Check what's available in LLM1 result
        print(f"🔍 DEBUG LLM1 result keys: {list(llm1_result.keys())}")
        if 'plan' in llm1_result:
            plan = llm1_result['plan']
            print(f"🔍 DEBUG Plan keys: {list(plan.keys()) if isinstance(plan, dict) else type(plan)}")
            if isinstance(plan, dict) and 'steps' in plan:
                print(f"🔍 DEBUG Plan steps: {len(plan['steps'])} steps")
                for i, step in enumerate(plan['steps']):
                    print(f"   Step {i+1}: {step}")
        
        # Try to get actual LLM1 planned steps - now available in llm1_planning
        planned_steps = []
        
        # Try the new planned_steps field first
        if 'planned_steps' in llm1_result:
            planned_steps = llm1_result['planned_steps']
            print(f"🔍 DEBUG Found {len(planned_steps)} planned steps in llm1_planning")
        
        # Fallback to execution_result (though this doesn't have the plan)
        elif ('execution_result' in result and 
            'llm1_result' in result['execution_result'] and
            'llm1_plan' in result['execution_result']['llm1_result'] and
            'plan' in result['execution_result']['llm1_result']['llm1_plan']):
            plan = result['execution_result']['llm1_result']['llm1_plan']['plan']
            planned_steps = plan.get('steps', [])
            print(f"🔍 DEBUG Found {len(planned_steps)} planned steps in execution_result")
            
        # Final fallback to direct plan access  
        elif 'plan' in llm1_result and isinstance(llm1_result['plan'], dict):
            planned_steps = llm1_result['plan'].get('steps', [])
            print(f"🔍 DEBUG Found {len(planned_steps)} planned steps in LLM1 result")
        
        if planned_steps:
            print(f"✅ Using {len(planned_steps)} steps from LLM1 plan")
            steps = planned_steps
        else:
            print(f"⚠️ No LLM1 planned steps found, falling back to entity-based step creation")
            # Create steps based on the entities and their typical order  
            steps = []
        if 'users' in entities:
            steps.append({
                'tool_name': 'users',
                'query_context': 'SQL query for users and applications',
                'step_type': 'sql',
                'critical': True
            })
        
        if 'role_assignment' in entities:
            steps.append({
                'tool_name': 'role_assignment', 
                'query_context': 'list_by_user to retrieve all role assignments for each user from the SQL result using user_okta_id',
                'step_type': 'api',
                'critical': False
            })
            
        if 'system_log' in entities:
            steps.append({
                'tool_name': 'system_log',
                'query_context': 'list_events to retrieve login events for each user in the last 7 days, filtering by actor.user.id and eventType eq user.session.start',
                'step_type': 'api', 
                'critical': False
            })
        
        if not steps:
            print("❌ No steps found in LLM1 plan")
            return {'success': False, 'error': 'No steps in plan'}
        
        print(f"\n� LLM1 PLANNED STEPS:")
        for i, step in enumerate(steps, 1):
            step_type = "SQL" if step.get('tool_name') in ['users', 'groups', 'applications'] else "API"
            print(f"   Step {i}: {step_type} - {step.get('tool_name')} - {step.get('query_context', '')[:60]}...")
        
        # Phase 2: Execute API steps sequentially with LLM2
        print(f"\n🤖 PHASE 2: SEQUENTIAL LLM2 API EXECUTION")
        print("=" * 50)
        
        api_results = []
        accumulated_data = sql_result.get('data_sample', [])  # Start with SQL data
        
        # Find ALL steps (API and SQL) and execute them in order
        all_steps = [step for step in steps]
        api_steps = [step for step in steps if step.get('tool_name') not in ['users', 'groups', 'applications']]
        sql_steps = [step for step in steps if step.get('tool_name') in ['users', 'groups', 'applications']]
        
        # Check if we have API → SQL workflow (API steps before SQL steps)
        has_api_first_workflow = False
        if api_steps and sql_steps:
            # Check if any API step comes before any SQL step
            api_indices = [i for i, step in enumerate(all_steps) if step.get('tool_name') not in ['users', 'groups', 'applications']]
            sql_indices = [i for i, step in enumerate(all_steps) if step.get('tool_name') in ['users', 'groups', 'applications']]
            
            if api_indices and sql_indices and min(api_indices) < max(sql_indices):
                has_api_first_workflow = True
                print(f"🔄 DETECTED API → SQL WORKFLOW: Will execute API steps first, then SQL with API context")
        
        if not api_steps:
            print("ℹ️ No API steps found, only SQL execution completed")
            return {
                'success': True,
                'sql_only': True,
                'sql_results': sql_result
            }
        
        print(f"🔍 Found {len(api_steps)} API steps to execute")
        if has_api_first_workflow:
            print(f"🔄 API → SQL Workflow: Will enhance SQL with API results")
        
        for step_num, api_step in enumerate(api_steps, 1):
            print(f"\n📋 API STEP {step_num}/{len(api_steps)}: {api_step.get('tool_name')}")
            print("-" * 40)
            
            # Create step-specific plan for endpoint filtering with all required fields
            step_plan = {
                'entities': [api_step.get('tool_name')],
                'confidence': 85,
                'reasoning': f"Sequential execution of step {step_num}: {api_step.get('query_context', '')[:100]}",
                'plan': {
                    'steps': [api_step],
                    'reasoning': f"Sequential execution of step {step_num}"
                }
            }
            
            # Get filtered endpoints for this specific step
            print(f"� Filtering endpoints for {api_step.get('tool_name')}...")
            step_filter_result = await executor._execute_endpoint_filtering(step_plan, f"step_{step_num}")
            step_endpoints = step_filter_result.get('filtered_endpoints', [])
            
            print(f"   🎯 Found {len(step_endpoints)} relevant endpoints")
            
            if not step_endpoints:
                print(f"   ⚠️ No endpoints found for {api_step.get('tool_name')}, skipping...")
                continue
            
            # Execute LLM2 for this step with accumulated data context
            print(f"🤖 Generating code with context from previous {len(accumulated_data)} records...")
            
            step_llm2_result = await executor._execute_llm2_code_generation(
                llm1_result={'plan': step_plan['plan']},
                sql_result={'data': accumulated_data, 'success': True},
                filter_result=step_filter_result,
                query=f"Step {step_num}: {api_step.get('query_context', '')}",
                correlation_id=f"step_{step_num}"
            )
            
            if step_llm2_result.get('success'):
                generated_code = step_llm2_result.get('code', '')
                print(f"   ✅ Generated {len(generated_code)} characters of code")
                
                # Execute the generated code
                print(f"🚀 Executing Step {step_num} code...")
                execution_result = await executor._execute_generated_code(
                    generated_code, f"step_{step_num}"
                )
                
                if execution_result and execution_result.get('success'):
                    print(f"   🔍 DEBUG: Execution result keys: {list(execution_result.keys())}")
                    step_data = execution_result.get('api_data_collected', [])
                    
                    # ENHANCED: Always store raw API execution output for LLM processing
                    raw_output = execution_result.get('output') or execution_result.get('stdout', '')
                    if raw_output:
                        # Store the raw API output for the LLM to process later
                        raw_api_output = {
                            'step_name': api_step.get('tool_name'),
                            'raw_output': raw_output,
                            'execution_context': api_step.get('query_context', ''),
                            'step_number': step_num
                        }
                        
                        # Always add raw output regardless of step_data content
                        if not step_data:  # If no structured data, initialize as list
                            step_data = []
                        step_data.append(raw_api_output)
                        
                        print(f"   📝 Stored raw API output ({len(raw_output)} chars) for LLM processing")
                    
                    print(f"   ✅ Step {step_num} executed successfully: {len(step_data)} records")
                    
                    # Add this step's results to accumulated data for next step
                    accumulated_data.extend(step_data)
                    
                    api_results.append({
                        'step': step_num,
                        'tool_name': api_step.get('tool_name'),
                        'success': True,
                        'records': len(step_data),
                        'data_sample': step_data[:2] if step_data else [],
                        'code_length': len(generated_code)
                    })
                    
                    print(f"   📊 Accumulated data now: {len(accumulated_data)} total records")
                else:
                    print(f"   ❌ Step {step_num} execution failed")
                    api_results.append({
                        'step': step_num,
                        'tool_name': api_step.get('tool_name'),
                        'success': False,
                        'error': execution_result.get('error', 'Unknown error') if execution_result else 'No execution result'
                    })
            else:
                print(f"   ❌ Step {step_num} code generation failed: {step_llm2_result.get('error', 'Unknown error')}")
                api_results.append({
                    'step': step_num,
                    'tool_name': api_step.get('tool_name'),
                    'success': False,
                    'error': f"Code generation failed: {step_llm2_result.get('error', 'Unknown')}"
                })
        
        # Phase 2.5: Execute SQL steps with API context (if API → SQL workflow)
        if has_api_first_workflow and sql_steps and accumulated_data:
            print(f"\n🤖 PHASE 2.5: SQL WITH API CONTEXT")
            print("=" * 45)
            
            print(f"🔍 Found {len(sql_steps)} SQL steps to execute with API context")
            print(f"📊 API Data Available: {len(accumulated_data)} records")
            
            for sql_step_num, sql_step in enumerate(sql_steps, 1):
                print(f"\n📋 SQL STEP {sql_step_num}/{len(sql_steps)}: {sql_step.get('tool_name')}")
                print("-" * 40)
                
                # Build enhanced query with raw API context for LLM processing
                raw_api_outputs = []
                api_context_summary = ""
                
                for record in accumulated_data:
                    if isinstance(record, dict) and 'raw_output' in record:
                        raw_api_outputs.append(record)
                        step_info = f"Step {record.get('step_number')} ({record.get('step_name')})"
                        output_preview = record['raw_output'][:200] + "..." if len(record['raw_output']) > 200 else record['raw_output']
                        api_context_summary += f"\n{step_info}: {output_preview}\n"
                
                api_context_query = f"""
                {query}
                
                API EXECUTION RESULTS TO PROCESS:
                {api_context_summary}
                
                INSTRUCTIONS:
                1. Analyze the API execution results above to extract relevant data (user IDs, group IDs, app IDs, etc.)
                2. Generate SQL queries that use this extracted data with DISTINCT for deduplication
                3. The API results may contain duplicate entries - ensure each unique ID is processed only once
                4. Structure your SQL to efficiently join with existing database tables
                
                Total API result steps: {len(raw_api_outputs)}
                """
                
                print(f"🔄 Executing SQL with API context ({len(accumulated_data)} records)...")
                
                # Create enhanced LLM1 plan for SQL with raw API context
                enhanced_llm1_plan = {
                    "requires_sql": True,
                    "sql_needed": True,
                    "explanation": f"SQL execution with API context - {len(raw_api_outputs)} API result steps",
                    "api_context": True,
                    "raw_api_data": raw_api_outputs  # Pass raw data for LLM to process
                }
                
                # Execute SQL with API context using enhanced SQL agent
                sql_with_api_result = await executor._execute_sql_queries(
                    enhanced_llm1_plan, 
                    api_context_query, 
                    f"api_sql_step_{sql_step_num}"
                )
                
                if sql_with_api_result and sql_with_api_result.get('success'):
                    sql_api_data = sql_with_api_result.get('data', [])
                    print(f"   ✅ SQL with API context: {len(sql_api_data)} records returned")
                    if sql_api_data:
                        print(f"   📄 Sample result: {sql_api_data[0]}")
                        # Add SQL results to accumulated data
                        accumulated_data.extend(sql_api_data)
                else:
                    print(f"   ❌ SQL with API context failed: {sql_with_api_result.get('error', 'Unknown error')}")
        
        # Phase 3: Results Summary
        print(f"\n🎯 PHASE 3: MULTI-STEP PIPELINE SUMMARY")
        print("=" * 45)
        
        successful_api_steps = sum(1 for r in api_results if r['success'])
        total_api_records = sum(r.get('records', 0) for r in api_results if r['success'])
        
        print(f"✅ Pipeline Results:")
        print(f"   🧠 LLM1 Planning: ✅ {llm1_result.get('entities', [])}")
        print(f"   💾 SQL Execution: ✅ {sql_result.get('records_count', 0)} records")
        print(f"   🤖 API Steps: {successful_api_steps}/{len(api_steps)} successful")
        print(f"   � Total API Records: {total_api_records}")
        print(f"   🔗 Total Data Flow: {len(accumulated_data)} records")
        
        print(f"\n📋 DETAILED API STEP RESULTS:")
        for result in api_results:
            status = "✅" if result['success'] else "❌"
            print(f"   {status} Step {result['step']} ({result['tool_name']}): ", end="")
            if result['success']:
                print(f"{result.get('records', 0)} records, {result.get('code_length', 0)} chars code")
                if result.get('data_sample'):
                    print(f"      Sample: {result['data_sample'][0] if result['data_sample'] else 'No data'}")
            else:
                print(f"Failed - {result.get('error', 'Unknown error')}")
        
        return {
            'success': True,
            'pipeline_type': 'multi_step_llm2',
            'phases': {
                'llm1_planning': llm1_result,
                'sql_execution': sql_result,
                'api_steps': api_results
            },
            'summary': {
                'total_steps': len(steps),
                'api_steps': len(api_steps),
                'successful_api_steps': successful_api_steps,
                'total_records': len(accumulated_data),
                'sql_records': sql_result.get('records_count', 0),
                'api_records': total_api_records
            },
            'accumulated_data': accumulated_data[:5]  # Sample of final results
        }
            
    except Exception as e:
        print(f"💥 Pipeline Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}

# Main execution - Core working pipeline (SQL → API)
if __name__ == "__main__":
    asyncio.run(execute_multi_step_llm2_pipeline())
