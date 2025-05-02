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
    Lists all applications in the Okta organization with pagination support. Returns application information including ID, name, label, and status.

    # Tool Documentation: Okta Application Search API Tool

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

    *   **`limit`** (Integer):
        *   Specifies the number of results per page (maximum 200).
        *   Default is determined by the Okta API if not specified.

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

    ## Example Usage
    ```python
    # Build query parameters
    query_params = {}
    
    # To search by application display name (most common case)
    query_params["q"] = "Workday"  # Searches both name and label fields
    
    # To filter by specific attributes (exact matches only)
    # query_params["filter"] = 'status eq "ACTIVE"'
    
    # Add pagination and other parameters if needed
    if limit:
        query_params["limit"] = limit
    if after:
        query_params["after"] = after
    if expand:
        query_params["expand"] = expand
    if include_non_deleted:
        query_params["includeNonDeleted"] = "true"
    if use_optimization:
        query_params["useOptimization"] = "true"
    
    # Get applications with pagination 
    apps = await paginate_results(
        "list_applications",
        query_params=query_params,
        entity_name="applications"
    )
    
    # Check for errors
    if isinstance(apps, dict) and "status" in apps and apps["status"] == "error":
        return apps

    # Return results directly - the results processor will handle formatting
    return apps
    ```

    ## Error Handling
    If the API call fails, returns an error object: `{"status": "error", "error": error_message}`
    If no applications are found, returns an empty list `[]`

    ## Important Notes
    - Data returned by paginate_results is already in dictionary format (not objects)
    - Access fields using dictionary syntax: item["property"]["field"] (not object.attribute syntax)    
    - Use the `q` parameter for partial name/label searches (startsWith operation)
    - Use the `filter` parameter only with the eq operator for exact matches
    - Double quotes must be used inside filter strings and properly escaped
    - Return data directly without additional transformation
    - The results processor will handle filtering fields based on query context
    - DO NOT use filter='label eq "Workday"' - this will cause an error (label is not supported in filter)
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass


@register_tool(
    name="get_application_details",
    entity_type="application",
    aliases=["app_details", "get_app", "getappdetails", "app_info"]
)
async def get_application_details(client, app_id):
    """
    Retrieves detailed information about a specific Okta application by ID. Returns application profile data including ID, name, label, status, creation date, sign-on mode, and accessPolicyId.

    # Tool Documentation: Okta Get Application Details API Tool

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

    ## Example Usage
    ```python
    # Check if the input app object has an error status - it's very important to check
    # for ERROR STATUS VALUES specifically, not just the presence of a status field
    if isinstance(workday_app, dict) and "status" in workday_app and workday_app["status"] in ["error", "not_found", "dependency_failed"]:
        return {"status": "dependency_failed", "dependency": "list_applications", "error": workday_app.get("error", "Application not found")}

    # Extract the app ID
    app_id = workday_app.get("id")
    if not app_id:
        return {"status": "error", "error": "Application ID not found in previous step"}

    # Get application details by ID using handle_single_entity_request
    app_result = await handle_single_entity_request(
        method_name="get_application",
        entity_type="application",
        entity_id=app_id,
        method_args=[app_id]
    )
    
    # Check if the API call returned an error
    if isinstance(app_result, dict) and "status" in app_result and app_result["status"] in ["error", "not_found", "dependency_failed"]:
        return app_result
        
    # CRITICAL: Extract the access policy ID and ADD IT TO THE RESULT OBJECT
    # Variables don't pass between steps, so we must add this to the returned object
    if "_links" in app_result and "accessPolicy" in app_result["_links"]:
        access_policy_href = app_result["_links"]["accessPolicy"]["href"]
        access_policy_id = access_policy_href.split("/")[-1]
        
        # Add the policy ID to the app_result for the next step to use
        if "policyIds" not in app_result:
            app_result["policyIds"] = {}
        app_result["policyIds"]["accessPolicy"] = access_policy_id
    
    # Return the modified application object with embedded policy ID
    return app_result
    ```

    ## Error Handling
    If the application doesn't exist, returns: `{"status": "not_found", "entity": "application", "id": app_id}`
    If another error occurs, returns: `{"status": "error", "error": error_message}`

    ## Important Notes
    - CRITICAL: Normal Okta application objects have a "status" field with values like "ACTIVE"
    - When checking for errors, always check BOTH the presence of "status" AND that its value is an error value
    - Error status values include: "error", "not_found", "dependency_failed"
    - Variables defined in one step are NOT available in subsequent steps
    - You MUST add the access policy ID to the app_result object before returning it
    - Extract the access policy ID from app_result["_links"]["accessPolicy"]["href"]
    - The next step will look for the policy ID in app_result["policyIds"]["accessPolicy"]
    - Always modify and return the original app_result object rather than creating a new one
    - Data returned is already in dictionary format - use dictionary syntax for access
    """
    # Implementation will be handled by code generation
    pass


@register_tool(
    name="list_application_users",
    entity_type="application",
    aliases=["app_users", "get_app_users"]
)
async def list_application_users(client, app_id, expand="user", q=None, limit=None, after=None):
    """
    Retrieves all users that are assigned to an Okta application by application ID. Returns user information including ID, name, and status for each user assigned to the application.

    # Tool Documentation: Okta List Application Users API Tool

    ## Goal
    This tool retrieves all users that are assigned to an Okta application.

    ## Core Functionality
    Retrieves users associated with a specific application with support for filtering and pagination.

    ## Parameters
    *   **`app_id`** (Required, String):
        *   The unique identifier of the application.
        *   Must be an Okta application ID (e.g., "0oafxqCAJWWGELFTYASJ")

    *   **`expand`** (String):
        *   A parameter to include additional information.
        *   Default value: "user" - returns full User objects in _embedded property
        *   This parameter is recommended for proper user information extraction

    *   **`q`** (String):
        *   Filters users based on profile attributes. 
        *   Matches the beginning of userName, firstName, lastName, and email.
        *   Example: `q="sam"` finds users with names or emails starting with "sam"

    *   **`limit`** (Integer):
        *   Specifies the number of results per page (1-500).
        *   Default: 50 if not specified

    *   **`after`** (String):
        *   Pagination cursor for the next page of results.
        *   Obtained from a previous response's next link.

    ## Example Usage
    ```python
    # Build query parameters
    query_params = {"expand": "user"}  # Always include expand=user for better data
    
    if q:
        query_params["q"] = q
    if limit:
        query_params["limit"] = limit
    if after:
        query_params["after"] = after
    
    # Get all users for this application with pagination
    users = await paginate_results(
        "list_application_users",
        method_args=[app_id],  # Pass app_id as a positional argument
        query_params=query_params,
        entity_name="users"
    )
    
    # Check for errors
    if isinstance(users, dict) and "status" in users and users["status"] == "error":
        return users
    
    # Return results directly - the results processor will handle formatting
    return users
    ```

    ## Error Handling
    If the application doesn't exist, returns: `{"status": "not_found", "entity": "application", "id": app_id}`
    If another error occurs, returns: `{"status": "error", "error": error_message}`
    If no users are found, returns an empty list `[]`

    ## Important Notes
    - Data returned by paginate_results is already in dictionary format (not objects)
    - Access fields using dictionary syntax: item["property"]["field"] (not object.attribute syntax)    
    - Always include expand=user in query parameters for better user information
    - Application users have a different schema than regular users
    - User information is in both the app user object and the _embedded.user object
    - Return data directly without additional transformation
    - The results processor will handle filtering fields based on query context
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass


@register_tool(
    name="list_application_groups",
    entity_type="application",
    aliases=["app_groups", "get_app_groups"]
)
async def list_application_groups(client, app_id, q=None, limit=None, after=None, expand=None):
    """
    Retrieves all groups that are assigned to an Okta application by application ID. Returns group information including ID, name, and type for each group assigned to the application.

    # Tool Documentation: Okta List Application Groups API Tool

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

    *   **`limit`** (Integer):
        *   Specifies the number of results per page (20-200).
        *   Default: 20 if not specified

    *   **`after`** (String):
        *   Pagination cursor for the next page of results.
        *   Obtained from a previous response's next link.

    *   **`expand`** (String):
        *   An optional parameter to include additional information.
        *   Valid values: 
            * "group" - returns full Group objects in _embedded property
            * "metadata" - returns group assignment metadata details

    ## Example Usage
    ```python
    # Build query parameters
    query_params = {}
    
    if q:
        query_params["q"] = q
    if limit:
        query_params["limit"] = limit
    if after:
        query_params["after"] = after
    if expand:
        query_params["expand"] = expand
    
    # Get all groups for this application with pagination
    groups = await paginate_results(
        "list_application_group_assignments",
        method_args=[app_id], 
        query_params=query_params,
        entity_name="groups"
    )
    
    # Check for errors
    if isinstance(groups, dict) and "status" in groups and groups["status"] == "error":
        return groups
    
    # Return results directly - the results processor will handle formatting
    return groups
    ```

    ## Error Handling
    If the application doesn't exist, returns: `{"status": "not_found", "entity": "application", "id": app_id}`
    If another error occurs, returns: `{"status": "error", "error": error_message}`
    If no groups are found, returns an empty list `[]`

    ## Important Notes
    - Data returned by paginate_results is already in dictionary format (not objects)
    - Access fields using dictionary syntax: item["property"]["field"] (not object.attribute syntax)
    - Use expand=group to get full group information in the _embedded.group property
    - Application group assignments have a different structure than regular groups
    - Return data directly without additional transformation
    - The results processor will handle filtering fields based on query context
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass

logger.info("Registered application tools")