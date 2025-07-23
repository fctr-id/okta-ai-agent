"""
Test to verify AI_PROVIDER logging in Modern Execution Manager
"""
import asyncio
import sys
import os

# Add path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from modern_execution_manager import modern_executor
from utils.logging import generate_correlation_id

async def test_ai_provider_logging():
    """Test to verify AI_PROVIDER logging appears in Modern Execution Manager"""
    
    # Get and display the AI_PROVIDER value first
    ai_provider = os.getenv('AI_PROVIDER', 'not_set')
    
    print("🧪 Testing AI_PROVIDER logging in Modern Execution Manager...")
    print(f"🤖 Current AI_PROVIDER setting: {ai_provider}")
    
    query = "Find users in the group sso-super-admins"
    print(f"📝 Query: {query}")
    print("=" * 70)
    
    # This will call the Modern Execution Manager's execute_query method
    # which should log the AI_PROVIDER environment variable
    result = await modern_executor.execute_query(query)
    
    print("\n✅ Modern Execution Manager test completed")
    print(f"🔗 Correlation ID: {result.get('correlation_id', 'N/A')}")
    print(f"🤖 AI_PROVIDER was logged as: {ai_provider} (check logs for confirmation)")
    
    if result.get('success'):
        print(f"✅ Execution successful")
    else:
        print(f"❌ Execution failed: {result.get('error', 'Unknown error')}")
    
    return result

if __name__ == "__main__":
    result = asyncio.run(test_ai_provider_logging())
