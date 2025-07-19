#!/usr/bin/env python3
"""
Simple test for the simplified SQL agent
"""

import asyncio
import sys
import os
from pathlib import Path

# Add src to path
sys.path.append('..')

from sql_agent import professional_sql_query

async def test_simple_sql_query():
    """Test our simplified SQL agent"""
    print("🧪 TESTING SIMPLIFIED SQL AGENT")
    print("="*50)
    
    test_queries = [
        "Show me all active users",
        "Find users in Engineering department", 
        "List all applications"
    ]
    
    for i, query in enumerate(test_queries, 1):
        print(f"\n📋 Test {i}: {query}")
        print("-" * 30)
        
        try:
            result, usage_info = await professional_sql_query(query)
            
            print(f"✅ Generated SQL: {result.sql}")
            print(f"📝 Explanation: {result.explanation}")
            print(f"🔧 Complexity: {result.complexity}")
            print(f"💰 Tokens: {usage_info['total_tokens']}")
            print(f"✓ Quality Check: {result.validate_sql_quality()}")
            
        except Exception as e:
            print(f"❌ Error: {e}")
    
    print(f"\n🎉 Simplified SQL Agent tests complete!")

if __name__ == "__main__":
    asyncio.run(test_simple_sql_query())
