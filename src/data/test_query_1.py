#!/usr/bin/env python3
"""
PRODUCTION TEST QUERY 1 - MODERNIZED with Modern Execution Manager

Tests: "Find users logged in the last 7 days and fetch me their apps and groups"
Expected workflow: Query → Planning Agent → Modern Execution Manager → Results

Uses the same interface as RealWorldHybridExecutor but with our simplified Modern Execution Manager.
"""

import asyncio
import sys
import os
from datetime import datetime

# Add local path for modern imports
sys.path.append(os.path.dirname(__file__))

from modern_execution_manager import modern_executor

async def test_query_1():
    """Test Query 1: Users logged in last 7 days with their apps and groups"""
    
    print("🎯 MODERN END-TO-END TEST: QUERY 1")
    print("=" * 70)
    
    # The query that should trigger API→SQL workflow
    query = "Find users logged in the last 7 days and fetch me their applications and groups"
    
    print(f"📝 Query: {query}")
    print(f"🔗 Expected workflow: API (login events) → SQL (user details)")
    print(f"🕒 Test start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    try:
        # Execute the query using Modern Execution Manager (same interface as RealWorldHybridExecutor)
        print(f"\n🚀 Executing with Modern Execution Manager...")
        result = await modern_executor.execute_query(query)
        
        print(f"\n📊 EXECUTION RESULTS:")
        print("=" * 50)
        print(f"✅ Overall Success: {result.get('success', False)}")
        print(f"🔗 Correlation ID: {result.get('correlation_id', 'N/A')}")
        print(f"📋 Total Steps: {result.get('total_steps', 0)}")
        print(f"✅ Successful Steps: {result.get('successful_steps', 0)}")
        print(f"❌ Failed Steps: {result.get('failed_steps', 0)}")
        
        # Show step details
        step_results = result.get('step_results', [])
        if step_results:
            print(f"\n📋 STEP EXECUTION DETAILS:")
            for i, step_result in enumerate(step_results, 1):
                success = step_result.get('success', False)
                step_type = step_result.get('step_type', 'unknown')
                status = "✅" if success else "❌"
                print(f"   {status} Step {i} ({step_type})")
                if step_result.get('error'):
                    print(f"      Error: {step_result['error']}")
                elif step_result.get('result_type'):
                    print(f"      Result: {step_result['result_type']}")
        
        # Show final result
        final_result = result.get('final_result')
        if final_result:
            print(f"\n🎯 FINAL RESULT:")
            print(f"   Type: {type(final_result).__name__}")
            print(f"   Available: ✅")
        else:
            print(f"\n❌ NO FINAL RESULT")
        
        # Final assessment
        overall_success = result.get('success', False)
        success_rate = result.get('success_rate', 0)
        
        print(f"\n🏆 TEST ASSESSMENT:")
        print("=" * 40)
        if overall_success and success_rate >= 1.0:
            print(f"🎉 QUERY 1 - COMPLETE SUCCESS!")
            print(f"   All steps executed successfully")
            print(f"   Ready to proceed to Query 2")
            return True
        elif overall_success and success_rate >= 0.5:
            print(f"✅ QUERY 1 - SUCCESS!")
            print(f"   Success rate: {success_rate:.1%}")
            print(f"   Ready to proceed to Query 2")
            return True
        else:
            print(f"❌ QUERY 1 - FAILED")
            print(f"   Success rate: {success_rate:.1%}")
            print(f"   Check logs before proceeding")
            return False
            
    except Exception as e:
        print(f"\n❌ EXECUTION ERROR: {e}")
        print(f"   Exception type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Main test execution"""
    print(f"🚀 Starting Modern Test Query 1...")
    print(f"🕒 Test timestamp: {datetime.now().isoformat()}")
    print()
    
    # Run the test
    success = await test_query_1()
    
    print(f"\n{'='*70}")
    if success:
        print(f"🎉 MODERN TEST QUERY 1 - SUCCESS!")
        print(f"✅ Ready to proceed to Test Query 2")
    else:
        print(f"❌ MODERN TEST QUERY 1 - NEEDS ATTENTION")
        print(f"⚠️  Check logs for issues before proceeding")
    print(f"{'='*70}")
    
    return success

if __name__ == "__main__":
    asyncio.run(main())
