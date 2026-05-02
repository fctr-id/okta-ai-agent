import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

# Set environment variables if needed (assuming they are already set in the terminal session or .env)
# os.environ["OKTA_API_TOKEN"] = "..." 

from src.core.okta.client.base_okta_api_client import OktaAPIClient
from src.utils.logging import get_logger

# Configure logging to see what's happening
import logging
logging.basicConfig(level=logging.INFO)

async def analyze_risk():
    client = OktaAPIClient()
    
    print("--- Starting Special Tool Execution (Risk Analysis) ---")
    print("User: dan@fctr.io")
    
    try:
        response = await client.make_request(
            endpoint="/special-tools/login-risk-analysis",
            method="GET",
            params={
                "user_identifier": "dan@fctr.io"
            }
        )
        
        print("\n--- Execution Complete ---")
        print(f"Status: {response.get('status')}")
        
        if response.get("status") == "success":
            data = response.get("data", [])
            print(f"\nData received ({type(data)}):")
            import json
            print(json.dumps(data, indent=2, default=str))
        else:
            print(f"\nError: {response.get('error')}")
            print(f"Full response: {response}")
            
    except Exception as e:
        print(f"\nException occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(analyze_risk())
