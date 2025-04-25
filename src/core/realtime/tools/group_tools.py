"""
Group-related tool definitions for Okta API operations.
Contains documentation and examples for group operations.
"""

from typing import List, Dict, Any
from src.utils.tool_registry import register_tool
from src.utils.logging import get_logger

# Configure logging
logger = get_logger(__name__)

# ---------- Tool Registration ----------

@register_tool(
    name="list_groups",
    entity_type="group",
    aliases=["group_search", "groups_search", "searchgroups", "get_groups"]
)
async def list_groups(client, query=None, filter=None):
    """
    # Okta Group Search/List API

    ## Overview
    This API allows you to search for or list groups in the Okta directory based on various criteria.

    ## Use Cases
    - Get all groups in the organization
    - Find groups with specific names or descriptions
    - Filter groups by type
    - Search using complex criteria with profile attributes

    ## Example Usage
    ```python
    # List all groups
    groups, resp, err = await client.list_groups()
    if err:
        return {"status": "error", "error": str(err)}
    groups_list = [group.as_dict() for group in groups]

    # Search groups by name
    groups, resp, err = await client.list_groups(query_params={"q": "Engineering"})
    if err:
        return {"status": "error", "error": str(err)}
    groups_list = [group.as_dict() for group in groups]

    # Advanced search with specific criteria
    groups, resp, err = await client.list_groups(query_params={"search": "profile.name co \"Engineering\""})
    if err:
        return {"status": "error", "error": str(err)}
    groups_list = [group.as_dict() for group in groups]
    ```

    ## Parameters
    - **query_params**: Optional dictionary with search criteria:
      - 'q': Simple text search
      - 'search': Advanced SCIM filter expression
      - 'type': Filter by group type (OKTA_GROUP, APP_GROUP)

    ## Search Operators (for 'search' parameter)
    - eq: profile.name eq "Engineering" (equals)
    - co: profile.name co "Eng" (contains)
    - sw: profile.name sw "Dev" (starts with)
    - And other operators: ne (not equals), pr (present), gt/lt (greater/less than)

    ## Return Value
    List of group objects with these key fields:
    - id: Unique identifier
    - profile: Contains name and description
    - type: Group type (OKTA_GROUP, APP_GROUP)
    - created/lastUpdated: Timestamps
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass


@register_tool(
    name="get_group_details",
    entity_type="group",
    aliases=["group_details", "get_group", "getgroupdetails"]
)
async def get_group_details(client, group_id):
    """
    # Okta Get Group Details API

    ## Overview
    This API retrieves detailed information about a specific Okta group using its unique ID.

    ## Use Cases
    - View detailed properties of a specific group
    - Check group settings and attributes
    - Verify group type and timestamps

    ## Example Usage
    ```python
    # Get group details by ID - parameter is passed directly, not as a named argument
    group, resp, err = await client.get_group("00g1qqxig80cFCxPP0h7")
    if err:
        return {"status": "error", "error": str(err)}
        
    group_details = group.as_dict()

    # Access group properties
    group_name = group_details["profile"]["name"]
    group_description = group_details["profile"]["description"]
    group_type = group_details["type"]
    ```

    ## Parameters
    - **group_id**: Required. The unique identifier for the group, passed as a direct parameter.

    ## SDK Method Signature
    ```python
    async def get_group(group_id):
        # This is the internal SDK method signature
        # The group_id is passed as a positional argument, NOT a named argument
        pass
    ```

    ## Return Value
    Dictionary containing detailed group information:
    - id: Unique identifier
    - profile: Contains name, description and other attributes
    - type: Group type (OKTA_GROUP, APP_GROUP)
    - created: Creation timestamp
    - lastUpdated: Last update timestamp
    - lastMembershipUpdated: When membership was last changed

    ## Error Handling
    If the group doesn't exist, returns an error object:
    ```python
    {"status": "not_found", "entity": "group", "id": group_id}
    ```
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass


@register_tool(
    name="get_group_members",
    entity_type="group",
    aliases=["group_members", "list_group_members", "group_users", "find_users_in_group"]
)
async def get_group_members(client, group_id):
    """
    # Okta Group Members API

    ## Overview
    This API retrieves all users who are members of a specific Okta group.

    ## Use Cases
    - List all users in a group
    - Check group membership
    - Find user details within a specific group

    ## Example Usage
    ```python
    # Get all members of a group - IMPORTANT: parameter is passed directly, not as a named argument
    users, resp, err = await client.list_group_users("00g1qqxig80cFCxPP0h7")
    if err:
        return {"status": "error", "error": str(err)}
        
    users_list = [user.as_dict() for user in users]

    # Process the members
    for user in users_list:
        user_id = user["id"]
        email = user["profile"]["email"]
        name = f"{user['profile']['firstName']} {user['profile']['lastName']}"
        print(f"User: {name}, Email: {email}")

    # Common pattern: First find group by name, then get members
    # Step 1: Find the group by name
    groups, resp, err = await client.list_groups(query_params={"q": "okta-admins"})
    if err:
        return {"status": "error", "error": str(err)}
        
    groups_list = [group.as_dict() for group in groups]
    if groups_list:
        # Step 2: Get the members of that group - note how group_id is passed directly
        group_id = groups_list[0]["id"]
        users, resp, err = await client.list_group_users(group_id)  # NOT client.list_group_users(group_id=group_id)
        if err:
            return {"status": "error", "error": str(err)}
            
        users_list = [user.as_dict() for user in users]
    ```

    ## SDK Method Signature
    ```python
    async def list_group_users(group_id):
        # This is the internal SDK method signature
        # The group_id is passed as a positional argument, NOT a named argument
        # Do NOT use: client.list_group_users(group_id=group_id) - this will cause an error
        # Instead use: client.list_group_users(group_id)
        pass
    ```

    ## Parameters
    - **group_id**: Required. The unique identifier for the group, passed as a direct parameter.

    ## Return Value
    A list of user objects, each containing:
    - id: User's unique identifier
    - profile: User profile containing:
      - email: User's email address
      - firstName, lastName: User's name
      - login: Username (often email)
      - other profile attributes
    - status: User status (ACTIVE, SUSPENDED, etc.)
    - created: When user was created

    ## Error Handling
    If the group doesn't exist, returns an error object:
    ```python
    {"status": "not_found", "entity": "group", "id": group_id}
    ```
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass


@register_tool(
    name="list_group_applications",
    entity_type="group",
    aliases=["group_apps", "group_applications", "get_group_apps", "list_assigned_applications_for_group"]
)
async def list_group_applications(client, group_id):
    """
    # Okta Group Applications API

    ## Overview
    This API retrieves all applications that are assigned to a specific Okta group.

    ## Use Cases
    - See which applications a group has access to
    - Audit application assignments
    - View application details for group members

    ## Example Usage
    ```python
    # Get all applications assigned to a group - IMPORTANT: parameter is passed directly, not as a named argument
    apps, resp, err = await client.list_assigned_applications_for_group("00g1qqxig80cFCxPP0h7")
    if err:
        return {"status": "error", "error": str(err)}
        
    apps_list = [app.as_dict() for app in apps]

    # Process the applications
    for app in apps_list:
        app_id = app["id"]
        app_name = app["name"]
        app_label = app["label"]
        print(f"App: {app_label} ({app_name})")
    ```

    ## SDK Method Signature
    ```python
    async def list_assigned_applications_for_group(group_id):
        # This is the internal SDK method signature
        # The group_id is passed as a positional argument, NOT a named argument
        # Do NOT use: client.list_assigned_applications_for_group(group_id=group_id) - this will cause an error
        # Instead use: client.list_assigned_applications_for_group(group_id)
        pass
    ```

    ## Parameters
    - **group_id**: Required. The unique identifier for the group, passed as a direct parameter.

    ## Return Value
    A list of application objects, each containing:
    - id: Application's unique identifier
    - name: Application name (internal name)
    - label: User-facing name
    - status: Application status
    - created/lastUpdated: Timestamps

    ## Error Handling
    If the group doesn't exist, returns an error object:
    ```python
    {"status": "not_found", "entity": "group", "id": group_id}
    ```
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass

logger.info("Registered group tools")