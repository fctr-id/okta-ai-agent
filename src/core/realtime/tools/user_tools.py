"""
User-related tool definitions for Okta API operations.
Contains documentation and examples for user operations.
"""

from typing import List, Dict, Any
from src.utils.tool_registry import register_tool
from src.utils.logging import get_logger

# Configure logging
logger = get_logger(__name__)

# ---------- Tool Registration ----------

@register_tool(
    name="search_users",
    entity_type="user",
    aliases=["user_search", "users_search", "searchusers", "find_users", "list_users"]
)
async def search_users(client, query=None, filter=None, limit=None):
    """
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
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass


@register_tool(
    name="get_user_details",
    entity_type="user",
    aliases=["user_details", "get_user", "getuserdetails", "user_info"]
)
async def get_user_details(client, user_id_or_login):
    """
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
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass


@register_tool(
    name="list_user_groups",
    entity_type="user",
    aliases=["user_groups", "get_user_groups"]
)
async def list_user_groups(client, user_id_or_login):
    """
    # Okta List User Groups API

    ## Overview
    This API retrieves all groups that a user belongs to.

    ## Use Cases
    - Check group memberships for a user
    - Determine a user's roles and access rights
    - Audit user permissions and group assignments
    - Filter groups by different criteria

    ## Example Usage
    ```python
    # Get groups for a user by user ID
    user_id = "00u1qqxig80cFCxPP0h7"
    groups, resp, err = await client.list_user_groups(user_id)
    if err:
        return {"status": "error", "error": str(err)}

    groups_list = [group.as_dict() for group in groups]

    # Get groups for a user by email
    user_email = "user@example.com"
    # First get the user to find their ID
    user, resp, err = await client.get_user(user_email)
    if err:
        return {"status": "error", "error": str(err)}

    user_id = user.id
    groups, resp, err = await client.list_user_groups(user_id)
    if err:
        return {"status": "error", "error": str(err)}

    groups_list = [group.as_dict() for group in groups]
    ```

    ## SDK Method Signature
    ```python
    async def list_user_groups(user_id):
        # This is the internal SDK method signature
        pass
    ```

    ## Parameters
    - **user_id**: Required. The user's unique ID (not email/login).

    ## Return Value
    List of group objects the user belongs to, each containing:
    - id: Group unique identifier
    - name: Group name
    - description: Group description
    - type: Group type (Usually "OKTA_GROUP")
    - created: Creation timestamp
    - lastUpdated: Last update timestamp
    - objectClass: Usually ["okta:user_group"]

    ## Error Handling
    If the user doesn't exist, returns an error object:
    ```python
    {"status": "not_found", "entity": "user", "id": user_id}
    ```
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass

logger.info("Registered user tools")