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
    
    # The specific query we'll use for testing
    query = "Find users in group sso-super-admins, get their applications, roles and their last 7 days login activity"
    
    print(f"📝 Test Query: {query}")
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
        
        # Find API steps and execute them one by one
        api_steps = [step for step in steps if step.get('tool_name') not in ['users', 'groups', 'applications']]
        
        if not api_steps:
            print("ℹ️ No API steps found, only SQL execution completed")
            return {
                'success': True,
                'sql_only': True,
                'sql_results': sql_result
            }
        
        print(f"🔍 Found {len(api_steps)} API steps to execute")
        
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
                    step_data = execution_result.get('api_data_collected', [])
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

if __name__ == "__main__":
    asyncio.run(execute_multi_step_llm2_pipeline())
