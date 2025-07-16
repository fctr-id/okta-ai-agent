#!/usr/bin/env python3
"""
Test SQL-First Approach with Integrated Data Mapping LLM
Complete pipeline: LLM1 → SQL → LLM2/Data Mapper → LLM3 Consolidator
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

async def test_complete_hybrid_pipeline():
    """Test complete pipeline with LLM2 code generation"""
    
    print("🔍 Testing Complete Hybrid Pipeline with LLM2 Code Generation")
    print("=" * 60)
    
    executor = RealWorldHybridExecutor()
    
    # Example query - replace with actual group name for testing
    query = "Fetch users from group YOUR_GROUP_NAME and retrieve their applications assigned, registered factors and their roles"
    
    # For testing purposes, replace YOUR_GROUP_NAME with an actual group name like:
    # query = query.replace("YOUR_GROUP_NAME", "Engineering")
    
    print(f"📝 SQL-First Query: {query}")
    print("-" * 50)
    
    try:
        # Phase 1: LLM1 Planning (existing)
        print("🧠 PHASE 1: LLM1 PLANNING")
        print("=" * 30)
        
        result = await executor.execute_query(query)
        
        if not result['success']:
            print(f"❌ Failed: {result.get('error')}")
            return result
            
        llm1_planning = result['llm1_planning']
        sql_execution = result['sql_execution'] 
        endpoint_filtering = result['endpoint_filtering']
        
        print(f"✅ LLM1 Results:")
        print(f"   📋 Entities: {llm1_planning['entities']}")
        print(f"   � Steps: {llm1_planning['steps_count']}")
        print(f"   🧠 Reasoning: {llm1_planning['reasoning']}")
        
        print(f"\n💾 SQL Results:")
        print(f"   📈 Records: {sql_execution['records_count']}")
        print(f"   🗃️ Query: {sql_execution['sql_query'][:100]}...")
        
        print(f"\n🔍 Endpoint Filtering:")
        print(f"   📉 Filtered: {endpoint_filtering['filtered_count']} from {endpoint_filtering['original_count']}")
        print(f"   🎯 Reduction: {endpoint_filtering['reduction_percentage']}%")
        
        # Phase 3: LLM2 Code Generation (NOW ENABLED IN EXECUTOR)
        print(f"\n🤖 PHASE 3: LLM2 CODE GENERATION RESULTS")
        print("=" * 50)
        
        # Get LLM2 results from the executor
        llm2_code_generation = result.get('llm2_code_generation', {})
        
        if llm2_code_generation.get('success'):
            print(f"✅ LLM2 Code Generation Results:")
            print(f"   🎯 Success: {llm2_code_generation.get('success', False)}")
            print(f"   📝 Code Length: {len(llm2_code_generation.get('code', ''))} characters")
            print(f"   � Requirements: {llm2_code_generation.get('requirements', [])}")
            print(f"   � Explanation: {llm2_code_generation.get('explanation', 'No explanation')}")
            
            # Show the generated code for manual validation
            generated_code = llm2_code_generation.get('code', '')
            print(f"\n📄 GENERATED PYTHON CODE (for manual validation):")
            print("=" * 60)
            print(generated_code)
            print("=" * 60)
            
            # Manual validation prompt
            print(f"\n� MANUAL VALIDATION REQUIRED:")
            print(f"   1. Check if the code uses correct API endpoints")
            print(f"   2. Verify SQL data is properly processed") 
            print(f"   3. Confirm error handling is adequate")
            print(f"   4. Test if code can actually fetch the required details")
            print(f"   5. Validate authentication handling")
            
            # Phase 4: Results Summary
            print(f"\n🎯 PHASE 4: COMPLETE PIPELINE SUMMARY")
            print("=" * 40)
            
            print(f"✅ Pipeline Success:")
            print(f"   🧠 LLM1 Planning: ✅ {llm1_planning['entities']}")
            print(f"   💾 SQL Execution: ✅ {sql_execution['records_count']} records")
            print(f"   🔍 Endpoint Filtering: ✅ {endpoint_filtering['filtered_count']} endpoints")
            print(f"   🤖 LLM2 Code Generation: ✅ {len(generated_code)} characters")
            print(f"   � Manual Validation: ⏳ REQUIRED")
            
            return {
                'success': True,
                'pipeline_phases': {
                    'llm1_planning': llm1_planning,
                    'sql_execution': sql_execution,
                    'endpoint_filtering': endpoint_filtering,
                    'llm2_code_generation': llm2_code_generation
                },
                'generated_code': generated_code,
                'validation_required': True
            }
        else:
            print(f"❌ LLM2 Code Generation failed: {llm2_code_generation.get('error', 'Unknown error')}")
            return {'success': False, 'error': 'LLM2 code generation failed'}
            
    except Exception as e:
        print(f"💥 Pipeline Error: {str(e)}")
        return {'success': False, 'error': str(e)}

if __name__ == "__main__":
    asyncio.run(test_complete_hybrid_pipeline())
