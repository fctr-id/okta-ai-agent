"""
User-related tool definitions for Okta API operations.
Contains documentation and examples for user operations.
"""

from typing import List, Optional, Dict, Set
from pydantic import BaseModel, Field

class ToolPrompt(BaseModel):
    """Base model for tool prompts with common properties."""
    name: str
    entity_type: str
    description: str
    parameters: List[str]
    usage: str 
    prompt: str
    aliases: Set[str] = Field(default_factory=set)

# Create specific tool instances
SEARCH_USERS = ToolPrompt(
    name="search_users",
    entity_type="user",
    description="Search for users in the Okta directory based on different criteria",
    parameters=["search_term"],
    usage="Find users matching specific criteria (email, name, status, etc.)",
    aliases={"user_search", "users_search", "searchusers"},
    prompt="""
# Okta User Search API

## Overview
The Okta User API allows you to search for users based on various criteria.

## Python SDK Example
```python
    # 1. Simple 'q' (query) parameter
    query_params_q = {'q': 'john'}  # Searches firstName, lastName, email (startsWith)
    users, resp, err = await okta_client.list_users(query_params=query_params_q)
    print(f"Users matching 'john': {len(users) if users else 0}")
    if err:
        print(f"Error: {err}")  # Example error handling

    # 2. 'filter' parameter (limited, but simpler)
    query_params_filter = {'filter': 'status eq "ACTIVE"'}
    users, resp, err = await okta_client.list_users(query_params=query_params_filter)
    print(f"Active users (filter): {len(users) if users else 0}")

    # 'filter' with 'lastUpdated' (supports date comparisons)
    query_params_filter_date = {'filter': 'lastUpdated gt "2024-01-01T00:00:00.000Z"'}
    users, resp, err = await okta_client.list_users(query_params=query_params_filter_date)
    print(f"Users updated after 2024-01-01: {len(users) if users else 0}")

    # 'filter' combining conditions
    query_params_filter_combined = {'filter': 'status eq "ACTIVE" and profile.lastName eq "Doe"'}
    users, resp, err = await okta_client.list_users(query_params=query_params_filter_combined)
    print(f"Active users with last name Doe: {len(users) if users else 0}")

    # 3. 'search' parameter (recommended, powerful)
    query_params_search = {'search': 'profile.department eq "Engineering" and status eq "ACTIVE"'}
    users, resp, err = await okta_client.list_users(query_params=query_params_search)
    print(f"Active Engineering users (search): {len(users) if users else 0}")

    # 'search' with 'startsWith'
    query_params_search_sw = {'search': 'profile.firstName sw "A"'}
    users, resp, err = await okta_client.list_users(query_params=query_params_search_sw)
    print(f"Users with first name starting with A: {len(users) if users else 0}")

    # 'search' combining conditions with 'or'
    query_params_search_or = {'search': 'profile.city eq "San Francisco" or profile.city eq "London"'}
    users, resp, err = await okta_client.list_users(query_params=query_params_search_or)
    print(f"Users in San Francisco or London: {len(users) if users else 0}")

    # search with sorting
    query_params_search_sort = {
        'search': 'status eq "ACTIVE"',
        'sortBy': 'profile.lastName',
        'sortOrder': 'ascending'
    }
    users, resp, err = await okta_client.list_users(query_params=query_params_search_sort)
    if users:
        print(f"First user by last name after sorting: {users[0].profile.lastName if users else 'N/A'}")


    # 4. Limit and Pagination (can be combined with any of the above)
    query_params_limit = {'limit': 5, 'search': 'status eq "ACTIVE"'}  # Limit to 5 results
    users, resp, err = await okta_client.list_users(query_params=query_params_limit)
    print(f"Limited to 5 active users: {len(users) if users else 0}")
    if resp and resp.has_next(): # resp could be None if error occurred
      print("  More results available (pagination needed)")

    # 5. 'expand' parameter
    query_params_expand = {'expand': 'user', 'filter': 'status eq "ACTIVE"'}
    users, resp, err = await okta_client.list_users(query_params=query_params_expand)

  # Custom Attributes examples

    custom_attribute_name = "employeeNumber"

    # 1. Exact match for a custom attribute
    query_params_exact = {
        'search': f'profile.{custom_attribute_name} eq "12345"'
    }
    users, resp, err = await okta_client.list_users(query_params=query_params_exact)
    print(f"Users with {custom_attribute_name} = 12345: {len(users) if users else 0}")

    # 2. Starts-with search for a custom attribute
    query_params_startswith = {
        'search': f'profile.{custom_attribute_name} sw "123"'
    }
    users, resp, err = await okta_client.list_users(query_params=query_params_startswith)
    print(f"Users with {custom_attribute_name} starting with '123': {len(users) if users else 0}")

    # 3. Check if a custom attribute is present (has any value)
    query_params_present = {
        'search': f'profile.{custom_attribute_name} pr'
    }
    users, resp, err = await okta_client.list_users(query_params=query_params_present)
    print(f"Users with {custom_attribute_name} present: {len(users) if users else 0}")
    
    # Async Iteration example (alternative to while loop with resp.next())
    users_list = []
    async for user in await okta_client.list_users(search='profile.department eq "Engineering"'):
        users_list.append(user)
    print(f"Engineering users using async for: {len(users_list)}")
```

## Search Parameters

### search (Recommended)
- Powerful and flexible filtering
- Uses SCIM filter syntax (e.g., `profile.department eq "Engineering" and status eq "ACTIVE"`)
- Supports operators: eq, ge, gt, le, lt, sw, co, pr, and, or
- Filters on most user properties, including custom ones, id, status, dates, and arrays
- Supports sorting with sortBy and sortOrder
- Supports pagination

### filter (Limited)
- Simpler filtering, but less powerful than search
- Supports only eq (except for lastUpdated, which allows date comparisons)
- Filters on: status, lastUpdated, id, profile.login, profile.email, profile.firstName, profile.lastName
- Supports pagination

### q (Simple Lookup)
- Basic lookup, limited functionality
- Searches firstName, lastName, email (startsWith)
- Default limit is 10
- Does not support full pagination when alone

### Pagination
- limit: Max results per page (default is 200 or 10, max 200)
- after: Cursor for the next page (from Link header)
- expand: Includes related resources (e.g., expand=user)

### List All Users
Calling the API without other parameters such as filter, search or q will list all the users except ones with DEPROVISIONED status.

## Return Format
The API returns User objects with these key fields:
- id: Unique identifier
- profile: Contains email, firstName, lastName, etc.
- status: User's status
- created: Creation timestamp
- lastUpdated: Last update timestamp
""")

### GET USER DETAILS TOOL ###
GET_USER_DETAILS = ToolPrompt(
    name="get_user_details",
    entity_type="user",
    description="Get detailed information about a specific user",
    parameters=["user_id_or_login"],
    usage="Retrieve complete details for a user by ID or login",
    aliases={"user_details", "get_user", "getuserdetails"},
    prompt="""
# Okta Get User Details API

## Overview
This API retrieves detailed information about a specific user by their ID or login.

## Python SDK Example
```python
# Get user by ID
user = await client.get_user("00u1qqxig80cFCxPP0h7")

# Get user by login (usually email)
user = await client.get_user("user@example.com")

# Access user properties
user_id = user.id
email = user.profile.email
status = user.status
created = user.created
```

## Important User Fields
- **id**: Unique identifier
- **profile**: Contains all profile attributes like:
  - **email**: User's email address
  - **firstName**: User's first name
  - **lastName**: User's last name
  - **login**: Username (often email)
  - **mobilePhone**: Mobile phone number
  - (+ any custom attributes)
- **status**: User status (ACTIVE, PROVISIONED, STAGED, SUSPENDED, DEPROVISIONED)
- **created**: Creation timestamp
- **activated**: Activation timestamp
- **statusChanged**: Status change timestamp
- **lastUpdated**: Last update timestamp
- **lastLogin**: Last login timestamp
- **credentials**: Contains credential information (password, recovery question, provider)

## Error Handling
- If the user doesn't exist, the API will return a 404 error
- Handle this case by checking for exceptions
""" )

# List of all user tools
USER_TOOLS = [SEARCH_USERS, GET_USER_DETAILS]

# Create lookup maps for efficient tool retrieval
_name_to_tool = {tool.name: tool for tool in USER_TOOLS}
_alias_map = {}

# Build the alias map
for tool in USER_TOOLS:
    for alias in tool.aliases:
        _alias_map[alias] = tool.name

def get_user_tool_prompt(tool_name: str) -> Optional[str]:
    """
    Get the documentation prompt for a user tool.
    
    Args:
        tool_name: Name of the tool (flexible naming supported)
        
    Returns:
        Tool documentation prompt or None if not found
    """
    # First check exact match
    if tool_name in _name_to_tool:
        return _name_to_tool[tool_name].prompt
        
    # Check for alias match
    normalized_name = tool_name.lower().replace("_", "").replace(" ", "")
    if normalized_name in _alias_map:
        canonical_name = _alias_map[normalized_name]
        return _name_to_tool[canonical_name].prompt
        
    # No match found
    return None

def get_all_user_tools() -> List[ToolPrompt]:
    """Get all available user tools."""
    return USER_TOOLS