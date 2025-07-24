#!/usr/bin/env python3
"""
Direct Query Test - Pass query as command line argument

Usage: python test_direct_query.py "your query here"
"""

import asyncio
import sys
import os
from datetime import datetime

# Add proper paths for imports
current_dir = os.path.dirname(__file__)
src_dir = os.path.abspath(os.path.join(current_dir, '..'))
project_root = os.path.abspath(os.path.join(current_dir, '..', '..'))

sys.path.insert(0, project_root)
sys.path.insert(0, src_dir)
sys.path.insert(0, current_dir)

from modern_execution_manager import modern_executor

async def test_direct_query(query: str):
    """Test with provided query"""
    
    print("🎯 MODERN EXECUTION MANAGER: DIRECT QUERY TEST")
    print("=" * 70)
    
    print(f"\n🔍 Executing Query: {query}")
    print(f"🕒 Test start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    try:
        # Execute the query using Modern Execution Manager's advanced multi-step processing
        print(f"\n🚀 Executing with Modern Execution Manager...")
        result = await modern_executor.execute_query(query)
        
        print(f"\n📊 EXECUTION RESULTS:")
        print(f"   Success: {result.get('success', False)}")
        print(f"   Correlation ID: {result.get('correlation_id', 'N/A')}")
        print(f"   Total Steps: {result.get('total_steps', 0)}")
        print(f"   Successful Steps: {result.get('successful_steps', 0)}")
        print(f"   Failed Steps: {result.get('failed_steps', 0)}")
        
        # Show execution plan
        execution_plan = result.get('execution_plan', {})
        if execution_plan:
            print(f"\n📋 EXECUTION PLAN:")
            steps = execution_plan.get('steps', [])
            for i, step in enumerate(steps, 1):
                print(f"   Step {i}: {step.get('tool_name', 'unknown')} - {step.get('entity', 'N/A')}")
                print(f"           Context: {step.get('query_context', '')[:80]}...")
        
        # Show step results summary
        step_results = result.get('step_results', [])
        if step_results:
            print(f"\n🔄 STEP EXECUTION SUMMARY:")
            for step_result in step_results:
                step_num = step_result.get('step_number', 0)
                step_type = step_result.get('step_type', 'unknown')
                success = step_result.get('success', False)
                status_icon = "✅" if success else "❌"
                print(f"   {status_icon} Step {step_num} ({step_type}): {'SUCCESS' if success else 'FAILED'}")
                
                if not success and step_result.get('error'):
                    print(f"      Error: {step_result['error']}")
        
        # Show final result summary
        final_result = result.get('final_result')
        if final_result:
            print(f"\n🎯 FINAL RESULTS:")
            if isinstance(final_result, dict):
                if 'data' in final_result:
                    data_count = len(final_result['data']) if isinstance(final_result['data'], list) else 1
                    print(f"   📊 Data Records: {data_count}")
                if 'summary' in final_result:
                    print(f"   📝 Summary: {final_result['summary'][:100]}...")
            
        return result.get('success', False)
        
    except Exception as e:
        print(f"\n❌ TEST EXECUTION FAILED:")
        print(f"   Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Main test execution"""
    
    if len(sys.argv) < 2:
        print("Usage: python test_direct_query.py \"your query here\"")
        print("\nExample:")
        print('python test_direct_query.py "find users who logged in the last 7 days and fetch their apps, groups and roles assigned"')
        return False
    
    query = " ".join(sys.argv[1:])
    
    print(f"🚀 Starting Modern Execution Manager Direct Test...")
    print(f"🕒 Test timestamp: {datetime.now().isoformat()}")
    print()
    
    # Run the test
    success = await test_direct_query(query)
    
    print(f"\n{'='*70}")
    if success:
        print(f"🎉 DIRECT QUERY TEST - SUCCESS!")
        print(f"✅ Modern Execution Manager processed query successfully")
    else:
        print(f"❌ DIRECT QUERY TEST - NEEDS ATTENTION")
        print(f"⚠️  Check output above for issues")
    print(f"{'='*70}")
    
    return success

if __name__ == "__main__":
    asyncio.run(main())
