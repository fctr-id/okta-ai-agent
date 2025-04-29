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
        *   Example: `q="Okta"` - finds apps with names starting with "Okta"

    *   **`filter`** (String):
        *   Filters applications using expression syntax with the eq operator only
        *   Supported filter fields:
            *   `status` - Filter by application status
            *   `name` - Filter by exact application name
            *   `user.id` - Filter by assigned user
            *   `group.id` - Filter by assigned group
            *   `credentials.signing.kid` - Filter by signing key ID
        *   Example: `filter='status eq "ACTIVE"'`
        *   Example: `filter='name eq "okta_org2org"'`
        *   Note: Only the eq operator is supported for application filtering

    *   **`limit`** (Integer):
        *   Specifies the number of results per page (maximum 200).
        *   Default is determined by the Okta API if not specified.

    *   **`after`** (String):
        *   Pagination cursor for the next page of results.
        *   Obtained from a previous response's next link.

    *   **`expand`** (String):
        *   An optional parameter used for link expansion to embed more resources.
        *   Only supports expand=user/{userId} format
        *   Must be used with the user.id eq "{userId}" filter for the same user
        *   Returns the assigned application user in the _embedded property

    *   **`include_non_deleted`** (Boolean):
        *   Whether to include non-active (but not deleted) apps in results.
        *   Default: false

    *   **`use_optimization`** (Boolean):
        *   Specifies whether to use query optimization.
        *   If true, the response contains a subset of app instance properties.
        *   Default: false

    ## Default Output Fields
    If no specific attributes are requested, return these minimal fields:
    - id: Application's unique Okta identifier
    - name: Application name
    - label: Display name of the application
    - status: Application's current status (e.g., ACTIVE, INACTIVE)
    - signOnMode: Application's sign-on mode (e.g., SAML_2_0, BROWSER_PLUGIN)

    If the user specifically asks for different attributes, return those instead of the default fields.
    If the user asks for "all" or "complete" data, return the full application objects.

    ## Example Usage
    ```python
    # Build query parameters
    query_params = {}
    
    # Use q parameter for startsWith search on name/label
    if q:
        query_params["q"] = q
        
    # Use filter parameter for exact matches with eq operator
    if filter:
        query_params["filter"] = filter
        
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

    # Handle empty results
    if not apps:
        return []

    # Transform results to include only default fields
    minimal_apps = []
    for app in apps:
        minimal_apps.append({
            "id": app["id"],
            "name": app.get("name"),
            "label": app.get("label"),
            "status": app.get("status"),
            "signOnMode": app.get("signOnMode")
        })
    
    # Return the transformed results
    return minimal_apps
    ```

    ## Example Filter and Search Patterns
    ```python
    # Search for apps with names starting with "Okta"
    query_params = {
        "q": "Okta"
    }

    # Filter for active applications (exact match with eq)
    query_params = {
        "filter": 'status eq "ACTIVE"'
    }

    # Filter for applications by exact name (exact match with eq)
    query_params = {
        "filter": 'name eq "okta_org2org"'
    }
    
    # Filter for applications assigned to a specific user
    query_params = {
        "filter": 'user.id eq "00u1gjh63g214q0Hq0g5"'
    }
    
    # Filter for applications assigned to a specific group
    query_params = {
        "filter": 'group.id eq "00g15acRUy0SYb9GT0g4"'
    }
    
    # Get applications with expanded user information
    query_params = {
        "filter": 'user.id eq "00u1gjh63g214q0Hq0g5"',
        "expand": "user/00u1gjh63g214q0Hq0g5"
    }
    ```

    ## Error Handling
    If the API call fails, returns an error object: `{"status": "error", "error": error_message}`

    ## Important Notes
    - Use the `q` parameter for partial name/label searches (startsWith operation)
    - Use the `filter` parameter only with the eq operator for exact matches
    - The filter parameter only supports the eq operator, NOT co (contains), sw (startsWith), etc.
    - When filtering by user.id, you can use expand=user/{userId} to get embedded user data
    - Double quotes must be used inside filter strings and properly escaped
    - Pagination is handled automatically for large result sets
    - Empty results are normal and will return an empty list []
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
    Retrieves detailed information about a specific Okta application by ID. Returns application profile data including ID, name, label, status, creation date, sign-on mode, and associated policy IDs that can be used with list_policy_rules.

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
    - policyIds: Object containing associated policy IDs extracted from _links section

    If the user specifically asks for different attributes, return those instead of the default fields.
    If the user asks for "all" or "complete" data, return the full application object.

    ## Example Usage
    ```python
    # Get application by ID
    app, resp, err = await client.get_application(app_id)
    if err:
        return {"status": "error", "error": str(err)}
    
    # If application not found (would be caught in error handling above but being explicit)
    if not app:
        return {"status": "not_found", "entity": "application", "id": app_id}
    
    app_details = app.as_dict()
    
    # Extract policy IDs from links section if available
    policy_ids = {}
    if "_links" in app_details:
        links = app_details["_links"]
                
        # Extract access policy ID if present
        if "accessPolicy" in links and "href" in links["accessPolicy"]:
            access_url = links["accessPolicy"]["href"]
            # Extract ID from URL format like "https://domain/api/v1/policies/policy_id"
            if "/policies/" in access_url:
                policy_ids["accessPolicyId"] = access_url.split("/policies/")[1]
    
    # Return default fields unless full data is requested
    minimal_app = {
        "id": app_details["id"],
        "name": app_details.get("name"),
        "label": app_details.get("label"),
        "status": app_details.get("status"),
        "created": app_details.get("created"),
        "lastUpdated": app_details.get("lastUpdated"),
        "signOnMode": app_details.get("signOnMode"),
        "policyIds": policy_ids  # Include extracted policy IDs
    }
    
    return minimal_app
    ```

    ## Error Handling
    If the application doesn't exist, returns: `{"status": "not_found", "entity": "application", "id": app_id}`
    If another error occurs, returns: `{"status": "error", "error": error_message}`

    ## Important Implementation Notes
    - Pass app_id as a positional argument: client.get_application(app_id)
    - Do NOT use named arguments: client.get_application(app_id=app_id)
    - Policy IDs are found in the _links section of the response
    - Extract profileEnrollment policy ID from _links.profileEnrollment.href
    - Extract access policy ID from _links.accessPolicy.href
    - These policy IDs can be used with list_policy_rules to get detailed policy information
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
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
        *   A mandatory parameter to include additional information.
        *   Default value: "user" - returns full User objects in _embedded property
        *   This parameter is required for proper user information extraction

    *   **`q`** (String):
        *   Filters users based on profile attributes. 
        *   Matches the beginning of userName, firstName, lastName, and email.
        *   Example: `q="sam"` finds users with names or emails starting with "sam"
        *   Note: For OIDC apps, only matches against userName or email

    *   **`limit`** (Integer):
        *   Specifies the number of results per page (1-500).
        *   Default: 50 if not specified

    *   **`after`** (String):
        *   Pagination cursor for the next page of results.
        *   Obtained from a previous response's next link.

    ## Response Structure
    Application users have a different structure than regular users:
    - User information is in the `profile` object
    - Email may be in `profile.email`, `credentials.userName`, or both
    - When using `expand=user`, the full user object is in `_embedded.user`
    - Status is typically "PROVISIONED" for app users (different from user status)

    ## Default Output Fields
    If no specific attributes are requested, return these minimal fields for each user:
    - id: User's unique Okta identifier
    - email: User's primary email address (from profile.email or credentials.userName)
    - firstName: User's first name (from profile.firstName)
    - lastName: User's last name (from profile.lastName)
    - status: User's application status (e.g., PROVISIONED)
    - userName: Username for this application (from credentials.userName)

    If the user specifically asks for different attributes, return those instead of the default fields.
    If the user asks for "all" or "complete" data, return the full user objects.

    ## Example Usage
    ```python
    # Build query parameters
    query_params = {"expand": "user"}  # Always include expand=user
    
    if q:
        query_params["q"] = q
        
    if limit:
        query_params["limit"] = limit
        
    if after:
        query_params["after"] = after
    
    # Get all users for this application with pagination
    users = await paginate_results(
        "list_application_users",
        method_args=[app_id],  # Pass app_id as a positional argument in a list
        query_params=query_params,  # Pass additional query parameters
        entity_name="users"
    )
    
    # Check for errors
    if isinstance(users, dict) and "status" in users and users["status"] == "error":
        return users
    
    # Handle empty results
    if not users:
        return []
    
    # Transform results to include only default fields
    minimal_users = []
    for user in users:
        # Initialize user data fields
        user_id = user["id"]
        email = ""
        first_name = ""
        last_name = ""
        status = user.get("status", "")
        username = user.get("credentials", {}).get("userName", "")
        
        # First check for embedded user data (most complete source)
        if "_embedded" in user and "user" in user["_embedded"]:
            embedded_user = user["_embedded"]["user"]
            
            # Get profile from embedded user (usually more complete)
            if "profile" in embedded_user:
                embedded_profile = embedded_user["profile"]
                first_name = embedded_profile.get("firstName", "")
                last_name = embedded_profile.get("lastName", "")
                email = embedded_profile.get("email", "")
                
            # If embedded user has a status, capture it too (but don't override app user status)
            if not status and "status" in embedded_user:
                status = embedded_user["status"]
        
        # If we couldn't get data from embedded user, try app user profile
        if not email or not first_name or not last_name:
            profile = user.get("profile", {})
            
            # Only override values that weren't found in embedded user
            if not email:
                email = profile.get("email", "")
            if not first_name:
                first_name = profile.get("firstName", "")
            if not last_name:
                last_name = profile.get("lastName", "")
        
        # Last resort fallback for email from credentials
        if not email and username:
            email = username
        
        minimal_users.append({
            "id": user_id,
            "email": email,
            "firstName": first_name,
            "lastName": last_name,
            "status": status,
            "userName": username
        })
    
    return minimal_users
    ```

    ## Error Handling
    If the application doesn't exist, returns: `{"status": "not_found", "entity": "application", "id": app_id}`
    If another error occurs, returns: `{"status": "error", "error": error_message}`
    If no users are found, returns an empty list `[]`

    ## Important Implementation Notes
    - When using paginate_results, pass the app_id in method_args=[app_id]
    - Always include expand=user in query parameters for proper user information
    - Application users have a different schema than regular users
    - Email can be in profile.email or credentials.userName
    - The embedded user.profile contains complete user information
    - Results are already converted to dictionaries; do not call as_dict() on them
    - Empty results are normal and will return an empty list []
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

    ## Response Structure
    Application group assignments have a different structure than regular groups:
    - The response contains group assignments, not direct group objects
    - Each assignment has an ID, priority, and lastUpdated timestamp
    - Group profile information is in the profile object, which varies by application type
    - The full group object may be in _embedded.group when using expand=group
    - Assignment metadata may be in _embedded.metadata when using expand=metadata
    - Links to related resources are in _links, including app and group links

    ## Default Output Fields
    If no specific attributes are requested, return these minimal fields for each group:
    - id: Group assignment ID
    - priority: Assignment priority value (if available)
    - lastUpdated: When the assignment was last updated
    - profile: Any relevant application-specific profile attributes

    If the user specifically asks for different attributes, return those instead of the default fields.
    If the user asks for "all" or "complete" data, return the full group assignment objects.

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
    group_assignments = await paginate_results(
        "list_application_groups",
        method_args=[app_id],  # Pass app_id as a positional argument in a list
        query_params=query_params,  # Pass additional query parameters
        entity_name="groups"
    )
    
    # Check for errors
    if isinstance(group_assignments, dict) and "status" in group_assignments and group_assignments["status"] == "error":
        return group_assignments
    
    # Handle empty results
    if not group_assignments:
        return []
    
    # Transform results to include only default fields
    minimal_groups = []
    for assignment in group_assignments:
        # Create base group info with ID and metadata
        group_info = {
            "id": assignment["id"],
            "priority": assignment.get("priority"),
            "lastUpdated": assignment.get("lastUpdated")
        }
        
        # Get profile information if available
        if "profile" in assignment and assignment["profile"]:
            # Extract relevant profile fields (filter out null values)
            profile = {k: v for k, v in assignment.get("profile", {}).items() if v is not None}
            if profile:
                group_info["profile"] = profile
        
        # Try to get group information from embedded data
        if "_embedded" in assignment:
            embedded = assignment["_embedded"]
            
            # Check for embedded group data
            if "group" in embedded:
                group_data = embedded["group"]
                group_info["name"] = group_data.get("profile", {}).get("name")
                group_info["type"] = group_data.get("type")
                
            # Check for embedded metadata
            if "metadata" in embedded:
                # Include only non-empty metadata
                metadata = embedded["metadata"]
                if metadata and isinstance(metadata, dict):
                    group_info["metadata"] = metadata
        
        # If we don't have a name yet, try to extract from links
        if "name" not in group_info and "_links" in assignment:
            # Sometimes group details can be extracted from the link
            group_link = assignment.get("_links", {}).get("group", {}).get("href", "")
            # Extract group ID from link if possible
            if group_link and "/" in group_link:
                group_info["groupId"] = group_link.split("/")[-1]
        
        minimal_groups.append(group_info)
    
    return minimal_groups
    ```

    ## Error Handling
    If the application doesn't exist, returns: `{"status": "not_found", "entity": "application", "id": app_id}`
    If another error occurs, returns: `{"status": "error", "error": error_message}`
    If no groups are found, returns an empty list `[]`

    ## Important Implementation Notes
    - When using paginate_results, pass the app_id in method_args=[app_id]
    - The response contains group assignments, not direct group objects
    - Group assignments have profile data that varies by application type
    - To get the actual group name, use expand=group and check in _embedded.group
    - Results are already converted to dictionaries; do not call as_dict() on them
    - Empty results are normal and will return an empty list []
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass

logger.info("Registered application tools")