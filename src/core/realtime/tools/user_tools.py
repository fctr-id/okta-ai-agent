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
List Okta users with filtering. Use query for simple terms (e.g. 'Dan') or search for SCIM filters (e.g. profile.firstName sw "Dan").
            IMPORTANT: make sure you understand the user query. USE co or pr unless the user specifically asks for the exact name match.
            search (Recommended, Powerful):
            Uses flexible SCIM filter syntax.
            Supports operators: eq, ne, gt, lt, ge, le, sw (starts with), co (contains), pr (present), and, or.
            Filters on most user properties, including custom attributes, id, status, dates, arrays.
            Supports sorting (sortBy, sortOrder) - NOTE: Sorting parameters ONLY work with 'search' parameter, not with 'query'.
            Examples:
            {'search': 'profile.department eq "Engineering" and status eq "ACTIVE"'}
            {'search': 'profile.firstName sw "A"'}
            {'search': 'profile.city eq "San Francisco" or profile.city eq "London"'}
            Sorting: {'search': 'status eq "ACTIVE"', 'sortBy': 'profile.lastName', 'sortOrder': 'ascending'}
            Custom Attribute (Exact): {'search': 'profile.employeeNumber eq "12345"'}
            Custom Attribute (Starts With): {'search': 'profile.employeeNumber sw "123"'}
            Custom Attribute (Present): {'search': 'profile.employeeNumber pr'}

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