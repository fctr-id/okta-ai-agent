"""
Application-related tool definitions for Okta API operations.
Contains documentation and examples for application operations.
"""

from typing import List, Dict, Any
from src.utils.tool_registry import register_tool
from src.utils.logging import get_logger

# Configure logging
logger = get_logger(__name__)

# ---------- Tool Registration ----------

@register_tool(
    name="list_applications",
    entity_type="application",
    aliases=["search_apps", "get_apps", "applications_search", "find_applications", "list_apps"]
)
async def list_applications(client, q=None, filter=None, limit=None, after=None, expand=None, include_non_deleted=False, use_optimization=False):
    """
    Lists Okta applications matching search criteria. Returns a LIST of application objects, NOT tuples. Use q= for name/label searches, filter= for exact property matches. For multiple distinct applications, use separate searches. can filter applications by userID (used to fetch apps assigned to user)

    # Tool Documentation: Okta Application Search API Tool
    IMPORTANT: YOU MUST ALWAYS PROVIDE CODE AS MENTIONED IN THE EXAMPLE USAGE or THAT MATCHES IT. DO NOT ADD ANYTHING ELSE.

    ## Goal
    This tool retrieves and searches for applications in the Okta directory based on specified criteria.

    ## Core Functionality
    Lists or searches for Okta applications with support for pagination and filtering.

    ## Parameters
    *   **`q`** (String):
        *   Searches for apps with name or label properties that start with the provided value.
        *   Uses the startsWith operation
        *   Example: `q="Workday"` - finds apps with names OR labels starting with "Workday"
        *   This is the recommended parameter for searching by application display name

    *   **`filter`** (String):
        *   Filters applications using expression syntax with the eq operator only
        *   Supported filter fields:
            *   `status` - Filter by application status
            *   `name` - Filter by exact application name (technical name)
            *   `user.id` - Filter by assigned user
            *   `group.id` - Filter by assigned group
            *   `credentials.signing.kid` - Filter by signing key ID
        *   Note: Label is NOT supported in filter expressions - use q parameter instead
        *   Example: `filter='status eq "ACTIVE"'`
        *   Example: `filter='name eq "okta_org2org"'`
        *   Note: Only the eq operator is supported for application filtering

    *   **`after`** (String):
        *   Pagination cursor for the next page of results.
        *   Treat this as an opaque value obtained from a previous response's next link.
        *   Example: after=16278919418571

    *   **`expand`** (String):
        *   An optional parameter used for link expansion to embed more resources.
        *   Only supports expand=user/{userId} format
        *   Must be used with the user.id eq "{userId}" filter for the same user
        *   Returns the assigned application user in the _embedded property
        *   Example: `expand="user/0oa1gjh63g214q0Hq0g4"`

    *   **`include_non_deleted`** (Boolean):
        *   Whether to include non-active (but not deleted) apps in results.
        *   Default: false
        *   Parameter name in URL: includeNonDeleted

    *   **`use_optimization`** (Boolean):
        *   Specifies whether to use query optimization.
        *   If true, the response contains a subset of app instance properties.
        *   Default: false
        *   Parameter name in URL: useOptimization

    ## Multi-Step Usage
    *   This tool can be used in the first step to find applications
    *   Store results in a variable named `applications` for clarity
    *   If searching for a specific app, store the first result in `app_result` for later steps
    *   Extract app ID with `app_id = app_result.get("id")` for use in later steps

    ## Example Usage
    ```python
    query_params = {"limit": 200, "expand": "user"}
    
    if q:
        query_params["q"] = q
    
    if filter:
        query_params["filter"] = filter
        
    if after:
        query_params["after"] = after
    if include_non_deleted:
        query_params["includeNonDeleted"] = "true"
    if use_optimization:
        query_params["useOptimization"] = "true"
    
    applications = await paginate_results(
        method_name="list_applications",
        query_params=query_params,
        entity_name="applications"
    )
    
    if isinstance(applications, dict) and applications.get("operation_status") in ["error", "not_found", "dependency_failed"]:
        return applications

    return applications
    ```

    ## Error Handling
    If the API call fails, returns an error object: `{"operation_status": "error", "error": error_message}`
    If no applications are found, returns an empty list `[]`

    ## Important Notes
    - Data returned by paginate_results is already in dictionary format (not objects)
    - Access fields using dictionary syntax: item["property"]["field"] (not object.attribute syntax)    
    - Use the `q` parameter for partial name/label searches (startsWith operation)
    - Use the `filter` parameter only with the eq operator for exact matches
    - Double quotes must be used inside filter strings and properly escaped
    - Return data directly without additional transformation
    - DO NOT use filter='label eq "Workday"' - this will cause an error (label is not supported in filter)
    """
    pass


@register_tool(
    name="get_application",
    entity_type="application",
    aliases=["app_details", "get_app", "getappdetails", "app_info"]
)
async def get_application(client, app_id):
    """
    Retrieves ONE specific Okta application by ID. Returns a DICTIONARY with application details, NOT a tuple. Extracts and adds policyIds.accessPolicy from _links for policy evaluation. Always verify result isn't an error object before extracting fields.

    # Tool Documentation: Okta Get Application Details API Tool
    IMPORTANT: YOU MUST ALWAYS PROVIDE CODE AS MENTIONED IN THE EXAMPLE USAGE or THAT MATCHES IT. DO NOT ADD ANYTHING ELSE.

    ## Goal
    This tool retrieves detailed information about a specific Okta application by ID, including any associated policy IDs.

    ## Core Functionality
    Retrieves information about a single application from the Okta directory, with special attention to extracting policy IDs.

    ## Parameters
    *   **`app_id`** (Required, String):
        *   The unique identifier of the application to retrieve.
        *   Must be an Okta application ID (e.g., "0oa1ero7vZFVEIYLWPBN")
        *   Note: This parameter is passed as a direct positional argument.

    ## Default Output Fields
    If no specific attributes are requested, return these minimal fields:
    - id: Application's unique Okta identifier
    - name: Application name
    - label: Display name of the application
    - status: Application's current status (e.g., ACTIVE, INACTIVE)
    - created: When the application was created
    - lastUpdated: When the application was last updated
    - signOnMode: Application's sign-on mode (e.g., SAML, BROWSER_PLUGIN)
    - _links: Contains important relationships including policy links

    ## Multi-Step Usage
    *   Can be used in a first step or after finding an application with list_applications
    *   Store the result in a variable named `app_result` for clarity
    *   Later steps can access the `app_result` variable directly
    *   Important: Always extract and append the policy ID to the response if available

    ## Example Usage
    ```python
    app_result = await handle_single_entity_request(
        method_name="get_application",
        entity_type="application",
        entity_id=app_id,
        method_args=[app_id]
    )
    
    if isinstance(app_result, dict) and app_result.get("operation_status") in ["error", "not_found", "dependency_failed"]:
        return app_result
        
    # Extract the access policy ID and add it to the result object
    if "_links" in app_result and "accessPolicy" in app_result["_links"]:
        access_policy_href = app_result["_links"]["accessPolicy"]["href"]
        access_policy_id = access_policy_href.split("/")[-1]
        
        # Add the policy ID to the app_result for the next step to use
        if "policyIds" not in app_result:
            app_result["policyIds"] = {}
        app_result["policyIds"]["accessPolicy"] = access_policy_id
    
    return app_result
    ```

    ## Error Handling
    If the application doesn't exist, returns: `{"operation_status": "not_found", "entity": "application", "id": app_id}`
    If another error occurs, returns: `{"operation_status": "error", "error": error_message}`

    ## Important Notes
    - CRITICAL: Normal Okta application objects have a "status" field with values like "ACTIVE"
    - When checking for errors, check that operation_status is an error value
    - Error status values include: "error", "not_found", "dependency_failed"
    - You MUST add the access policy ID to the app_result object before returning it
    - Extract the access policy ID from app_result["_links"]["accessPolicy"]["href"]
    - The next step will look for the policy ID in app_result["policyIds"]["accessPolicy"]
    - Always modify and return the original app_result object rather than creating a new one
    """
    pass


@register_tool(
    name="list_application_users",
    entity_type="application",
    aliases=["app_users", "get_app_users"]
)
async def list_application_users(client, app_id, expand="user", q=None, limit=None, after=None):
    """
    Lists ALL users assigned to ONE specific Okta application by app_id. Returns a LIST of user objects, NOT tuples. Uses automatic pagination to retrieve all assignments regardless of count.

    # Tool Documentation: Okta List Application Users API Tool
    IMPORTANT: YOU MUST ALWAYS PROVIDE CODE AS MENTIONED IN THE EXAMPLE USAGE or THAT MATCHES IT. DO NOT ADD ANYTHING ELSE.

    ## Goal
    This tool retrieves all users that are assigned to an Okta application.

    ## Core Functionality
    Retrieves users associated with a specific application with support for filtering and pagination.

    ## Parameters
    *   **`app_id`** (Required, String):
        *   The unique identifier of the application.
        *   Must be an Okta application ID (e.g., "0oafxqCAJWWGELFTYASJ")

    *   **`q`** (String):
        *   Filters users based on profile attributes. 
        *   Matches the beginning of userName, firstName, lastName, and email.
        *   Example: `q="sam"` finds users with names or emails starting with "sam"

    *   **`after`** (String):
        *   Pagination cursor for the next page of results.
        *   Obtained from a previous response's next link.

    ## Multi-Step Usage
    *   Typically used after retrieving app details with get_application
    *   In Step 2+, obtain app_id from previous step: `app_id = app_result.get("id")`
    *   If in Step 3+, check for app_id in earlier steps: `if "app_result" in globals()...`
    *   Store results in a variable named 'app_users' for consistency

    ## Example Usage
    ```python
    query_params = {"expand": "user", "limit": 500}
    
    if q:
        query_params["q"] = q
    if after:
        query_params["after"] = after
    
    app_users = await paginate_results(
        method_name="list_application_users",
        method_args=[app_id],
        query_params=query_params,
        entity_name="users"
    )
    
    if isinstance(app_users, dict) and app_users.get("operation_status") in ["error", "not_found", "dependency_failed"]:
        return app_users
    
    return app_users
    ```

    ## Error Handling
    If the application doesn't exist, returns: `{"operation_status": "not_found", "entity": "application", "id": app_id}`
    If another error occurs, returns: `{"operation_status": "error", "error": error_message}`
    If no users are found, returns an empty list `[]`

    ## Important Notes
    - Data returned by paginate_results is already in dictionary format (not objects)
    - Access fields using dictionary syntax: item["property"]["field"] (not object.attribute syntax)    
    - Always include expand=user in query parameters for better user information
    - Application users have a different schema than regular users
    - User information is in both the app user object and the _embedded.user object
    - In multi-step flows, check if app_id exists in previous steps if not available in current result
    """
    pass


@register_tool(
    name="list_application_group_assignments",
    entity_type="application",
    aliases=["app_groups", "get_app_groups"]
)
async def list_application_group_assignments(client, app_id, q=None, limit=None, after=None, expand=None):
    """
        Lists ALL groups assigned to ONE specific Okta application by app_id. Returns a LIST of group assignment objects, NOT tuples. Use expand=group for complete group data. Uses automatic pagination to retrieve all group assignments regardless of count.

    # Tool Documentation: Okta List Application Groups API Tool
    IMPORTANT: YOU MUST ALWAYS PROVIDE CODE AS MENTIONED IN THE EXAMPLE USAGE or THAT MATCHES IT. DO NOT ADD ANYTHING ELSE.

    ## Goal
    This tool retrieves all groups that are assigned to an Okta application.

    ## Core Functionality
    Retrieves groups associated with a specific application with support for filtering and pagination.

    ## Parameters
    *   **`app_id`** (Required, String):
        *   The unique identifier of the application.
        *   Must be an Okta application ID (e.g., "0oafxqCAJWWGELFTYASJ")

    *   **`q`** (String):
        *   Filters groups based on their names. 
        *   Matches the beginning of the group name.
        *   Example: `q="test"` finds groups with names starting with "test"

    *   **`after`** (String):
        *   Pagination cursor for the next page of results.
        *   Obtained from a previous response's next link.

    *   **`expand`** (String):
        *   An optional parameter to include additional information.
        *   Valid values: 
            * "group" - returns full Group objects in _embedded property
            * "metadata" - returns group assignment metadata details

    ## Multi-Step Usage
    *   Typically used after retrieving app details with get_application
    *   In Step 2+, get app_id from previous step: `app_id = app_result.get("id")`
    *   If in Step 3+, check for app_id in earlier steps: `if "app_result" in globals()...`
    *   Store results in a variable named 'app_groups' for consistency

    ## Example Usage
    ```python
    query_params = {"limit": 200, "expand": "group"}
    
    if q:
        query_params["q"] = q
    if after:
        query_params["after"] = after
    if expand:
        query_params["expand"] = expand
    else:
        query_params["expand"] = "group"
    
    app_groups = await paginate_results(
        method_name="list_application_group_assignments",
        method_args=[app_id], 
        query_params=query_params,
        entity_name="groups"
    )
    
    if isinstance(app_groups, dict) and app_groups.get("operation_status") in ["error", "not_found", "dependency_failed"]:
        return app_groups
    
    return app_groups
    ```

    ## Error Handling
    If the application doesn't exist, returns: `{"operation_status": "not_found", "entity": "application", "id": app_id}`
    If another error occurs, returns: `{"operation_status": "error", "error": error_message}`
    If no groups are found, returns an empty list `[]`

    ## Important Notes
    - Data returned by paginate_results is already in dictionary format (not objects)
    - Access fields using dictionary syntax: item["property"]["field"] (not object.attribute syntax)
    - Use expand=group to get full group information in the _embedded.group property
    - Application group assignments have a different structure than regular groups
    - In multi-step flows, check if app_id exists in previous steps if not available in current result
    """
    pass

logger.info("Registered application tools")