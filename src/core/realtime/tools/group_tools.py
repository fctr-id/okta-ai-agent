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
async def list_groups(client, query=None, search=None):
    """
    Lists groups in the Okta directory based on name, and also get basic statistics like user counts. Returns group information including ID, name, description, type and statistical data (user count, app count, groupPushMappings count and if the group has adminPrivileges assigned.).

    # Tool Documentation: Okta Group Search/List API Tool
    # IMPORTANT: YOU MUST ALWAYS PROVIDE CODE AS MENTIONED IN THE EXAMPLE USAGE or THAT MATCHES IT. DO NOT ADD ANYTHING ELSE.

    ## Goal
    This tool searches for or lists groups in the Okta directory based on various criteria.

    ## Core Functionality
    Retrieves groups matching search criteria or lists all groups with pagination support.
    IMPORTANT: Make sure you read the example and documentation carefully to understand how to use this tool effectively.

    ## Parameters
    *   **`query`** (String):
        *   RECOMMENDED simple text search across group names and descriptions.
        *   Example: `"Engineering"` will find groups with "Engineering" in name or description.

    *   **`search`** (String):
        *   Optional advanced SCIM filter expression for more complex searches.
        *   Examples:
            *   `profile.name eq \"Engineering\"`
            *   `profile.name co \"Dev\"`
            *   `type eq \"OKTA_GROUP\"`
            
    ## Search Operators (for 'search' parameter)
    *   **eq**: Equals - `profile.name eq \"Engineering\"`
    *   **co**: Contains - `profile.name co \"Eng\"`
    *   **sw**: Starts with - `profile.name sw \"Dev\"`
    *   Others: ne (not equals), pr (present), gt/lt (greater/less than)

    ## Default Output Fields
    Groups contain these key fields:
    - id: Unique group identifier
    - profile: Contains name and description
    - type: Group type (OKTA_GROUP, APP_GROUP)
    - created/lastUpdated: Timestamps
    - _embedded.stats: Contains statistical data:
      - usersCount: Number of users in the group
      - appsCount: Number of applications assigned to the group
      - groupPushMappingsCount: Number of push mappings
      - hasAdminPrivilege: Whether group has admin privileges

    ## Example Usage
    ```python
    # Build query parameters based on inputs
    query_params = {"limit": 200, "expand": "stats"}
    if query:
        query_params["q"] = query
    if search:
        query_params["search"] = search
    
    # Get groups with pagination
    groups = await paginate_results(
        "list_groups",
        query_params=query_params,
        entity_name="groups"
    )
    
    # Check for errors
    if isinstance(groups, dict) and "status" in groups and groups["status"] == "error":
        return groups

    # Example of accessing stats data
    if groups and isinstance(groups, list):
        for group in groups:
            stats = group.get("_embedded", {}).get("stats", {})
            user_count = stats.get("usersCount", 0)
            app_count = stats.get("appsCount", 0)
            # These counts are now available for processing
    
    # Return results directly
    return groups
    ```

    ## Error Handling
    If the API call fails, returns an error object: `{"status": "error", "error": error_message}`
    If no groups are found, returns an empty list `[]`

    ## Important Notes
    - Data returned by paginate_results is already in dictionary format (not objects)
    - Access fields using dictionary syntax: item["property"]["field"] (not object.attribute syntax)
    - Pagination is handled automatically for large result sets
    - The Okta API limits results to 200 groups per page
    - Double quotes must be used inside search strings and properly escaped
    - DO NOT use single quotes for the search values
    - Try using the simple "q" parameter first if specific filters fail
    - Statistical data (_embedded.stats) is always included in the results
    - Check if "_embedded" and "stats" keys exist before accessing them
    - Return data directly without transformation - formatting will be handled by the results processor
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass

@register_tool(
    name="list_group_users",
    entity_type="group",
    aliases=["group_users", "list_group_users", "user_membership"]
)
async def list_group_users(client, group_id):
    """
    Retrieves all members (users) detailed properties of a specific Okta group by group ID. Returns user information including ID, email, and status for each user in the group. For just stats or counts  use the list_groups tool.

    # Tool Documentation: Okta Get Group Members API Tool

    ## Goal
    This tool retrieves all members (users) of a specific Okta group.
    IMPORTANT: YOU MUST ALWAYS PROVIDE CODE AS MENTIONED IN THE EXAMPLE USAGE or THAT MATCHES IT. DO NOT ADD ANYTHING ELSE.

    ## Core Functionality
    Retrieves users associated with a specific group.

    ## Parameters
    *   **`group_id`** (Required, String):
        *   The unique identifier of the group.
        *   Must be an Okta group ID (e.g., "00g1emaKYZTWRYYRRTDK")

    ## Default Output Fields
    If no specific attributes are requested, return these minimal fields for each user:
    - id: User's unique Okta identifier
    - email: User's primary email address (from profile.email)
    - firstName: User's first name (from profile.firstName)
    - lastName: User's last name (from profile.lastName)
    - status: User's current status (e.g., ACTIVE, SUSPENDED)

    ## Example Usage
    ```python
    # Get all users for this group with pagination
    users = await paginate_results(
        "list_group_users",
        method_args=[group_id],  # Pass group_id as a positional argument in a list
        entity_name="users"
    )
    
    # Check for errors
    if isinstance(users, dict) and "status" in users and users["status"] == "error":
        return users
    
    # Return results directly
    return users
    ```

    ## Error Handling
    If the group doesn't exist, returns: `{"status": "not_found", "entity": "group", "id": group_id}`
    If another error occurs, returns: `{"status": "error", "error": error_message}`
    If no users are found, returns an empty list `[]`

    ## Important Notes
    - Data returned by paginate_results is already in dictionary format (not objects)
    - Access fields using dictionary syntax: item["property"]["field"] (not object.attribute syntax)    
    - When using paginate_results, pass the group_id in method_args=[group_id]
    - Return data directly without transformation
    - The results processor will handle filtering fields based on query context
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass


@register_tool(
    name="list_assigned_applications_for_group",
    entity_type="group",
    aliases=["group_apps", "group_applications", "get_group_apps", "list_assigned_applications_for_group"]
)
async def list_assigned_applications_for_group(client, group_id):
    """
    Retrieves all applications that are assigned to a specific Okta group by group ID. Returns application information including ID, name, label and status for each assigned app.

    # Tool Documentation: Okta Group Applications API Tool
    # IMPORTANT: YOU MUST ALWAYS PROVIDE CODE AS MENTIONED IN THE EXAMPLE USAGE or THAT MATCHES IT. DO NOT ADD ANYTHING ELSE.

    ## Goal
    This tool retrieves all applications that are assigned to a specific Okta group.

    ## Core Functionality
    Lists applications with access granted to a specific group with pagination support.

    ## Parameters
    *   **`group_id`** (Required, String):
        *   The unique identifier for the group.
        *   Example: `"00g1qqxig80cFCxPP0h7"`
        *   Note: This parameter is passed via method_args when using paginate_results.

    ## Default Output Fields
    Each application object contains:
    - id: Application's unique identifier
    - name: Application name (internal name)
    - label: User-facing name
    - status: Application status
    - created/lastUpdated: Timestamps

    ## Example Usage
    ```python
    # Get all applications assigned to the group with pagination
    query_params = {"limit": 200}
    apps = await paginate_results(
        "list_assigned_applications_for_group",
        method_args=[group_id],  # Pass group_id as a positional argument in a list
        query_params=query_params,
        entity_name="applications"
    )
    
    # Check for errors
    if isinstance(apps, dict) and "status" in apps and apps["status"] == "error":
        return apps
    
    # Return results directly
    return apps
    ```

    ## Error Handling
    If the group doesn't exist, returns: `{"status": "not_found", "entity": "group", "id": group_id}`
    If another error occurs, returns: `{"status": "error", "error": error_message}`
    If no applications are found, returns an empty list `[]`

    ## Important Notes
    - Data returned by paginate_results is already in dictionary format (not objects)
    - Access fields using dictionary syntax: item["property"]["field"] (not object.attribute syntax)    
    - When using paginate_results, pass the group_id in method_args=[group_id]
    - Return data directly without transformation
    - The results processor will handle filtering fields based on query context
    - Pagination is handled automatically for groups with many applications
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass

logger.info("Registered group tools")