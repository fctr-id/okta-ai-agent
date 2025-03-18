import asyncio
import sys
from pathlib import Path

# Add parent directory to path to find modules
sys.path.append(str(Path(__file__).parent.parent))

# Import from your project
from src.config.settings import settings
from okta.client import Client as OktaClient

# Instantiating with a Python dictionary in the constructor
config = {
    'orgUrl': settings.OKTA_CLIENT_ORGURL,
    'token': settings.OKTA_API_TOKEN
}
okta_client = OktaClient(config)
print(f"Okta client initialized with orgUrl: {config['orgUrl']}")

# Search users with first name starting with 'Noah'
async def main():
    # Create query parameters with the "sw" (starts with) operator
    query_params_search_sw = {'search': 'profile.firstName sw "Noah"'}
    
    # Execute the search
    users, resp, err = await okta_client.list_users(query_params=query_params_search_sw)
    
    if err:
        print(f"Error: {err}")
        return
    
    # Print the matching users
    print("Users with first name starting with 'Noah':")
    for user in users:
        print(f"{user.profile.first_name} {user.profile.last_name} ({user.profile.email})")
        
    # Convert users to list of dictionaries if needed
    users_list = [user.as_dict() for user in users]
    print(f"\nFound {len(users_list)} users")

# Use the new async/await pattern to avoid deprecation warnings
async def run():
    await main()

asyncio.run(run())