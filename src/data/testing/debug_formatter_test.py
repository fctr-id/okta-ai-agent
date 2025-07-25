"""
Debug test to see what the Results Formatter LLM is actually responding with
"""
import asyncio
import os
import sys
from pydantic_ai import Agent

# Add src path for importing utils
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from src.utils.logging import get_logger

# Setup logging
logger = get_logger("debug_formatter_test")

def _load_sample_data_prompt() -> str:
    """Load system prompt for sample data processing"""
    try:
        prompt_file = r"c:\Users\Dharanidhar\Desktop\github-repos\okta-ai-agent\src\data\results_formatter_sample_data_prompt.txt"
        with open(prompt_file, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return """You are a Results Formatter Agent that processes sample data and generates processing code.
Analyze samples and create efficient code for processing complete datasets."""

# Create a simple agent without structured output to see raw response
debug_formatter = Agent(
    'openai:gpt-4o',
    system_prompt=_load_sample_data_prompt(),
    # No output_type - just raw string response
    retries=0
)

async def test_raw_response():
    """Test what the LLM actually responds with"""
    
    # Sample prompt similar to what's failing
    test_prompt = """Query: Show me all users of all statuses
Dataset Size: 324 total records (LARGE DATASET - you're seeing samples)
Plan Context: {'steps': [{'tool_name': 'sql', 'entity': 'users', 'operation': None, 'query_context': 'Find all users of all statuses', 'critical': True}]}
Sample Data: {"step_1_sql": [{"okta_id": "00uropbgt", "email": "dan@fctr.io", "login": "dan@fctr.io", "first_name": "Dan", "last_name": "G", "status": "ACTIVE"}, {"okta_id": "00us049fba", "email": "kai.wong@fctr.io", "login": "kai.wong@fctr.io", "first_name": "Kai", "last_name": "Wong", "status": "PROVISIONED"}]}"""
    
    try:
        print("🔍 Testing raw LLM response...")
        result = await debug_formatter.run(test_prompt)
        
        print(f"\n✅ Raw LLM Response Type: {type(result)}")
        print(f"✅ Raw LLM Response Length: {len(str(result))}")
        print(f"\n📄 RAW LLM RESPONSE:")
        print("=" * 80)
        print(result)
        print("=" * 80)
        
        # Check if it looks like JSON
        result_str = str(result)
        if result_str.strip().startswith('{') and result_str.strip().endswith('}'):
            print("✅ Response appears to be JSON format")
        else:
            print("❌ Response does NOT appear to be JSON format")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_raw_response())
