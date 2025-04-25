"""
User-related tool definitions for Okta API operations.
Contains documentation and examples for user operations.
"""

from typing import List, Optional, Dict, Set, Any
from pydantic import BaseModel, Field
from src.utils.pagination_limits import paginate_results, handle_single_entity_request

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
    aliases={"user_search", "users_search", "searchusers", "find_users", "list_users"},
    prompt="""
# Okta User Search API

## Overview
This API allows you to search for users in the Okta directory based on various criteria.

## Use Cases
- Find users by name, email, or other attributes
- Filter users by status, department, or custom attributes
- Get all active users in the organization
- Search based on complex criteria with profile attributes

## Example Usage
```python
# List all users (excluding DEPROVISIONED)
users, resp, err = await client.list_users()
if err:
    return {"status": "error", "error": str(err)}
users_list = [user.as_dict() for user in users]

# Basic search by name or email
users, resp, err = await client.list_users(query_params={"q": "John Smith"})
if err:
    return {"status": "error", "error": str(err)}
users_list = [user.as_dict() for user in users]

# Advanced search with specific criteria
query_params = {'search': 'profile.department eq "Engineering" and status eq "ACTIVE"'}
users, resp, err = await client.list_users(query_params=query_params)
if err:
    return {"status": "error", "error": str(err)}
users_list = [user.as_dict() for user in users]

# Search by first name with starts with
query_params = {'search': 'profile.firstName sw "A"'}
users, resp, err = await client.list_users(query_params=query_params)
if err:
    return {"status": "error", "error": str(err)}
users_list = [user.as_dict() for user in users]
```

## SDK Method Signature
```python
async def list_users(query_params=None):
    # This is the internal SDK method signature
    # query_params is an optional dictionary with search criteria
    pass
```

## Parameters
- **query_params**: Optional dictionary with search criteria:
  - 'q': Simple text search
  - 'search': Advanced SCIM filter expression
  - 'sortBy': Field to sort results by (only works with 'search')
  - 'sortOrder': Direction to sort ('ascending' or 'descending')

## Search Operators (for 'search' parameter)
- eq: profile.department eq "Engineering" (equals)
- ne: profile.department ne "Sales" (not equals)
- co: profile.displayName co "Smith" (contains)
- sw: profile.firstName sw "J" (starts with)
- pr: profile.mobilePhone pr (present/has value)
- gt/lt/ge/le: For dates and numeric values
- Combine with 'and', 'or' for complex filters

## Note on Group Membership
To find users in a specific group, DO NOT use search filters. Instead, use the get_group_members tool with the group ID.

## Return Value
List of user objects, each containing:
- id: Unique identifier
- profile: Contains email, firstName, lastName, etc.
- status: User's status (ACTIVE, PROVISIONED, STAGED, SUSPENDED, DEPROVISIONED)
- created: Creation timestamp
- lastUpdated: Last update timestamp

## Error Handling
If the API call fails, returns an error object:
```python
{"status": "error", "error": error_message}
```
""")

GET_USER_DETAILS = ToolPrompt(
    name="get_user_details",
    entity_type="user",
    description="Get detailed information about a specific user",
    parameters=["user_id_or_login"],
    usage="Retrieve complete details for a user by ID or login",
    aliases={"user_details", "get_user", "getuserdetails", "user_info"},
    prompt="""
# Okta Get User Details API

## Overview
This API retrieves detailed information about a specific user by their ID or login (email).

## Use Cases
- View complete user profile and attributes
- Check user status and credentials
- Get user creation and activity timestamps
- Verify user settings and account details

## Example Usage
```python
# Get user by ID - parameter is passed directly, not as a named argument
user, resp, err = await client.get_user("00u1qqxig80cFCxPP0h7")
if err:
    return {"status": "error", "error": str(err)}
user_details = user.as_dict()

# Get user by login (usually email) - parameter is passed directly
user, resp, err = await client.get_user("user@example.com")
if err:
    return {"status": "error", "error": str(err)}
user_details = user.as_dict()

# Access user properties
user_id = user_details["id"]
email = user_details["profile"]["email"]
status = user_details["status"]
created = user_details["created"]
first_name = user_details["profile"]["firstName"]
last_name = user_details["profile"]["lastName"]
```

## SDK Method Signature
```python
async def get_user(user_id_or_login):
    # This is the internal SDK method signature
    # The user_id_or_login is passed as a positional argument, NOT a named argument
    # Do NOT use: client.get_user(user_id=user_id) - this will cause an error
    # Instead use: client.get_user(user_id)
    pass
```

## Parameters
- **user_id_or_login**: Required. Either the user's unique ID or their login (typically email), passed as a direct parameter.

## Return Value
User object containing detailed information:
- id: Unique identifier
- profile: Contains all profile attributes including:
  - email: User's email address
  - firstName, lastName: User's name
  - login: Username (often email)
  - mobilePhone: Mobile phone number
  - (+ any custom attributes)
- status: User status (ACTIVE, PROVISIONED, STAGED, SUSPENDED, DEPROVISIONED)
- created: Creation timestamp
- activated: Activation timestamp
- statusChanged: Status change timestamp
- lastUpdated: Last update timestamp
- lastLogin: Last login timestamp
- credentials: Contains credential information

## Error Handling
If the user doesn't exist, returns an error object:
```python
{"status": "not_found", "entity": "user", "id": user_id_or_login}
```
""" )

# List of all user tools
USER_TOOLS = [SEARCH_USERS, GET_USER_DETAILS]

# Create lookup maps for efficient tool retrieval
_name_to_tool = {tool.name: tool for tool in USER_TOOLS}
_alias_map = {}

# Build the alias map
for tool in USER_TOOLS:
    for alias in tool.aliases:
        normalized_alias = alias.lower().replace("_", "").replace(" ", "")
        _alias_map[normalized_alias] = tool.name

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

# New function for registry integration
def register_tools(registry: Any) -> None:
    """
    Register all user tools with the provided registry.
    
    Args:
        registry: The tool registry to register with
    """
    for tool in USER_TOOLS:
        registry.register_tool(tool)