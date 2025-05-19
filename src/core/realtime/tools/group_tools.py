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
        Lists Okta groups with name matching (via q= or search=). Returns LIST of group objects with USER COUNTS in _embedded.stats.usersCount (when expand=stats used). EFFICIENT for counting group membership without fetching all users. Use for ONE group pattern per call.

    # Tool Documentation: Okta Group Search/List API Tool
    IMPORTANT: YOU MUST ALWAYS PROVIDE CODE AS MENTIONED IN THE EXAMPLE USAGE or THAT MATCHES IT. DO NOT ADD ANYTHING ELSE.

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

    ## Multi-Step Usage
    *   This tool can be used in the first step to find groups
    *   Store results in a variable named `groups` for clarity
    *   If searching for a specific group, store the first result in `group_result` for later steps
    *   Extract group ID with `group_id = group_result.get("id")` for use in later steps

    ## Example Usage
    ```python
    query_params = {"limit": 200, "expand": "stats"}
    
    if query:
        query_params["q"] = query
    if search:
        query_params["search"] = search
    
    groups = await paginate_results(
        method_name="list_groups",
        query_params=query_params,
        entity_name="groups"
    )
    
    if isinstance(groups, dict) and groups.get("operation_status") in ["error", "not_found", "dependency_failed"]:
        return groups
    
    return groups
    ```

    ## Error Handling
    If the API call fails, returns an error object: `{"operation_status": "error", "error": error_message}`
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
    """
    pass

@register_tool(
    name="list_group_users",
    entity_type="group",
    aliases=["group_users", "list_group_users", "user_membership"]
)
async def list_group_users(client, group_id):
    """
    Retrieves ALL members of ONE specific Okta group using group_id (not name). Returns a LIST of normalized user objects, NOT tuples. Requires exact group_id as first method arg. For multiple groups, use separate calls. Uses automatic pagination for complete results regardless of group size.

    # Tool Documentation: Okta Get Group Members API Tool
    IMPORTANT: YOU MUST ALWAYS PROVIDE CODE AS MENTIONED IN THE EXAMPLE USAGE or THAT MATCHES IT. DO NOT ADD ANYTHING ELSE.

    ## Goal
    This tool retrieves all members (users) of a specific Okta group.

    ## Core Functionality
    Retrieves users associated with a specific group.

    ## Parameters
    *   **`group_id`** (Required, String):
        *   The unique identifier of the group.
        *   Must be an Okta group ID (e.g., "00g1emaKYZTWRYYRRTDK")
        *   Note: If you have a group's name instead of ID, first look up the group ID using list_groups

    ## Default Output Fields
    If no specific attributes are requested, return these minimal fields for each user:
    - id: User's unique Okta identifier
    - email: User's primary email address (from profile.email)
    - firstName: User's first name (from profile.firstName)
    - lastName: User's last name (from profile.lastName)
    - status: User's current status (e.g., ACTIVE, SUSPENDED)

    ## Multi-Step Usage
    *   Typically used after finding a group with list_groups
    *   In Step 2+, obtain group_id from previous step: `group_id = group_result.get("id")`
    *   If in Step 3+, check for group_id in earlier steps: `if "group_result" in globals()...`
    *   Store results in a variable named 'group_users' for consistency

    ## Example Usage
    ```python
    group_users = await paginate_results(
        method_name="list_group_users",
        method_args=[group_id],
        entity_name="users"
    )
    
    if isinstance(group_users, dict) and group_users.get("operation_status") in ["error", "not_found", "dependency_failed"]:
        return group_users
    
    return group_users
    ```

    ## Error Handling
    If the group doesn't exist, returns: `{"operation_status": "not_found", "entity": "group", "id": group_id}`
    If another error occurs, returns: `{"operation_status": "error", "error": error_message}`
    If no users are found, returns an empty list `[]`

    ## Important Notes
    - Data returned by paginate_results is already in dictionary format (not objects)
    - Access fields using dictionary syntax: item["property"]["field"] (not object.attribute syntax)    
    - When using paginate_results, pass the group_id in method_args=[group_id]
    - Return data directly without transformation
    - In multi-step flows, check if group_id exists in previous steps if not available in current result
    """
    pass


@register_tool(
    name="list_assigned_applications_for_group",
    entity_type="group",
    aliases=["group_apps", "group_applications", "get_group_apps", "list_assigned_applications_for_group"]
)
async def list_assigned_applications_for_group(client, group_id):
    """
    Lists ALL applications assigned to ONE specific Okta group by group_id. Returns a LIST of normalized application objects, NOT tuples. Requires exact group_id as first method arg. Get complete results regardless of number of app assignments via automatic pagination handling.

    # Tool Documentation: Okta Group Applications API Tool
    IMPORTANT: YOU MUST ALWAYS PROVIDE CODE AS MENTIONED IN THE EXAMPLE USAGE or THAT MATCHES IT. DO NOT ADD ANYTHING ELSE.

    ## Goal
    This tool retrieves all applications that are assigned to a specific Okta group.

    ## Core Functionality
    Lists applications with access granted to a specific group with pagination support.

    ## Parameters
    *   **`group_id`** (Required, String):
        *   The unique identifier for the group.
        *   Example: `"00g1qqxig80cFCxPP0h7"`
        *   Note: If you have a group's name instead of ID, first look up the group ID using list_groups

    ## Default Output Fields
    Each application object contains:
    - id: Application's unique identifier
    - name: Application name (internal name)
    - label: User-facing name
    - status: Application status
    - created/lastUpdated: Timestamps

    ## Multi-Step Usage
    *   Typically used after finding a group with list_groups
    *   In Step 2+, obtain group_id from previous step: `group_id = group_result.get("id")`
    *   If in Step 3+, check for group_id in earlier steps: `if "group_result" in globals()...`
    *   Store results in a variable named 'group_applications' for consistency

    ## Example Usage
    ```python
    query_params = {"limit": 200}
    
    group_applications = await paginate_results(
        method_name="list_assigned_applications_for_group",
        method_args=[group_id],
        query_params=query_params,
        entity_name="applications"
    )
    
    if isinstance(group_applications, dict) and group_applications.get("operation_status") in ["error", "not_found", "dependency_failed"]:
        return group_applications
    
    return group_applications
    ```

    ## Error Handling
    If the group doesn't exist, returns: `{"operation_status": "not_found", "entity": "group", "id": group_id}`
    If another error occurs, returns: `{"operation_status": "error", "error": error_message}`
    If no applications are found, returns an empty list `[]`

    ## Important Notes
    - Data returned by paginate_results is already in dictionary format (not objects)
    - Access fields using dictionary syntax: item["property"]["field"] (not object.attribute syntax)    
    - When using paginate_results, pass the group_id in method_args=[group_id]
    - Return data directly without transformation
    - In multi-step flows, check if group_id exists in previous steps if not available in current result
    - Pagination is handled automatically for groups with many applications
    """
    pass

logger.info("Registered group tools")