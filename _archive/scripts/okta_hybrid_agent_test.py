#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Okta Hybrid Agent Test Script

This test validates the complete hybrid workflow combining API and SQL execution
with proper security validation and results formatting.

Expected results:
- Test 1: Find users logged in last 10 days -> dan@fctr.io and aiden.garcia@fctr.io
- Test 2: Find sso-super-admins members -> dan@fctr.io (super admin role)
- Test 3: Find all admin users -> dan@fctr.io with role assignments
- For roles API call: dan@fctr.io has super admin role, aiden none
- For apps and groups: dan@fctr.io has 253 groups and 2 apps, aiden none
- Test is only successful if we get all expected data for each user
"""

import asyncio
import sys
import json
import os
from pathlib import Path

# Change to project root directory (from scripts folder to parent)
project_root = Path(__file__).parent.parent
os.chdir(str(project_root))
sys.path.insert(0, str(project_root))

from src.core.orchestration.modern_execution_manager import ModernExecutionManager

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Okta Hybrid Agent Test Script

This test runs the complete hybrid workflow and saves results to file for analysis.
No validation - just execution and output saving.
"""

import asyncio
import sys
import json
import os
import time
from pathlib import Path

# Change to project root directory (from scripts folder to parent)
project_root = Path(__file__).parent.parent
os.chdir(str(project_root))
sys.path.insert(0, str(project_root))

from src.core.orchestration.modern_execution_manager import ModernExecutionManager

async def run_test_and_save(query: str):
    """Run the test and save results to file"""
    print(f"🚀 Running hybrid agent test with query: {query}")
    print("=" * 80)
    
    start_time = time.time()
    
    manager = ModernExecutionManager()
    result = await manager.execute_query(query)
    
    end_time = time.time()
    response_time = end_time - start_time
    
    print("📊 EXECUTION RESULTS:")
    print(f"Success: {result.get('success')}")
    print(f"Total steps: {result.get('total_steps', 0)}")
    print(f"Successful steps: {result.get('successful_steps', 0)}")
    print(f"Failed steps: {result.get('failed_steps', 0)}")
    print(f"Response time: {response_time:.1f}s")
    print()
    
    # Create comprehensive test result
    test_result = {
        "timestamp": int(time.time()),
        "query": query,
        "response_time": response_time,
        "execution_result": result,
        "test_metadata": {
            "test_type": "hybrid_agent_test",
            "success": result.get('success', False),
            "total_steps": result.get('total_steps', 0),
            "successful_steps": result.get('successful_steps', 0),
            "failed_steps": result.get('failed_steps', 0)
        }
    }
    
    # Save results to file
    timestamp = int(time.time())
    output_file = Path(f"logs/json_results/hybrid_agent_test_{timestamp}.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(test_result, f, indent=2, ensure_ascii=False, default=str)
    
    print(f"� Results saved to: {output_file}")
    print()
    
    # Brief summary
    print("� TEST SUMMARY:")
    print(f"Query: {query}")
    print(f"Status: {'✅ SUCCESS' if result.get('success') else '❌ FAILED'}")
    print(f"Steps executed: {result.get('successful_steps', 0)}/{result.get('total_steps', 0)}")
    print(f"Time taken: {response_time:.1f}s")
    
    return test_result

def main():
    if len(sys.argv) != 2:
        print("Usage: python okta_hybrid_agent_test.py \"<query>\"")
        print("\nExample test queries:")
        print("1. \"Find users logged in the last 10 days and fetch me their applications and groups and role assignments\"")
        print("2. \"Find members of group sso-super-admins and fetch me their applications and groups and role assignments\"")
        print("3. \"Find all admins and return all users with role assignments\"")
        sys.exit(1)
    
    query = sys.argv[1]
    result = asyncio.run(run_test_and_save(query))
    
    # Exit with 0 for success, 1 for failure based on execution success
    success = result.get('test_metadata', {}).get('success', False)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
