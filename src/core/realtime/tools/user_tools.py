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
    name="list_users",
    entity_type="user",
    aliases=["user_search", "users_search", "searchusers", "find_users", "list_users"]
)
async def list_users(client, search=None, limit=None):
    """
    Searches for users in the Okta directory using advanced search expressions (SCIM filter syntax) with support for pagination.

    # Tool Documentation: Okta User Search API Tool

    ## Goal
    This tool searches for users in the Okta directory based on specified criteria.
    IMPORTANT: YOU MUST ALWAYS PROVIDE CODE AS MENTIONED IN THE EXAMPLE USAGE or THAT MATCCHES IT. DO NOT ADD ANYTHING ELSE.

    ## Core Functionality
    Searches for Okta users using advanced search expressions with support for pagination.

    ## Parameters
    *   **`search`** (String):
        *   Applies an advanced search filter using Okta's SCIM filter expression syntax.
        *   Examples:
            *   `profile.lastName eq \"Smith\"`
            *   `profile.login eq \"john.doe@example.com\"`
            *   `profile.email eq \"john.doe@example.com\"`
            *   `status eq \"ACTIVE\"`
            *   `profile.firstName co \"Joh\"` (contains operator)
        *   IMPORTANT: Always prefix user attributes with 'profile.' (e.g., profile.login, profile.email)

    *   **`limit`** (Integer):
        *   Specifies the maximum number of results to return per page.

    ## Search Operators
    *   **eq**: Equals - `status eq \"ACTIVE\"`
    *   **sw**: Starts with - `profile.firstName sw \"J\"`
    *   **co**: Contains - `profile.email co \"example\"` (only for firstName, lastName, email, and login)
    *   **gt/lt**: Greater than/Less than - `lastUpdated gt \"2023-01-01T00:00:00.000Z\"`
    *   **ge/le**: Greater than or equal/Less than or equal
    *   Combine with `and`, `or`, and parentheses for complex queries

    ## Example Usage
    ```python
    # Build query parameters
    query_params = {"limit": 200}
    
    # Example: To search by email or login (always use profile prefix)
    if search:
        query_params["search"] = search
    else:
        # If looking for a specific user by email
        user_email = "aiden.garcia@fctr.io"
        query_params["search"] = f'profile.email eq "{user_email}"'
        # Or by login
        # query_params["search"] = f'profile.login eq "{user_email}"'
        
    
    # Get users with pagination 
    users = await paginate_results(
        "list_users",
        query_params=query_params,
        entity_name="users"
    )
    
    # Check for errors
    if isinstance(users, dict) and "status" in users and users["status"] == "error":
        return users

    # Return the results directly - filtering/formatting will be handled by the results processor
    return users
    ```

    ## Error Handling
    If the API call fails, returns an error object: `{"status": "error", "error": error_message}`

    ## Important Notes
    - Data returned by paginate_results is already in dictionary format (not objects)
    - Access fields using dictionary syntax: item["property"]["field"] (not object.attribute syntax)    
    - Pagination is handled automatically for large result sets
    - Double quotes must be used inside the search string and properly escaped
    - ALWAYS use the 'profile.' prefix when searching user attributes (profile.login, profile.email, etc.)
    - DO NOT use attributes without the profile prefix (e.g., 'login eq "value"' will fail)
    - DO NOT use single quotes for the search values
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass


@register_tool(
    name="get_user",
    entity_type="user",
    aliases=["user_details", "get_user", "getuserdetails", "user_info"]
)
async def get_user(client, user_id_or_login):
    """
    Retrieves detailed information about a specific Okta user by ID or login (email). Returns user profile data including ID, email, name, login, status, and creation date.

    # Tool Documentation: Okta Get User Details API Tool

    ## Goal
    This tool retrieves detailed information about a specific Okta user by ID or login.

    ## Core Functionality
    Retrieves information about a single user from the Okta directory.

    ## Parameters
    *   **`user_id_or_login`** (Required, String):
        *   The unique identifier or login (usually email) of the user to retrieve.
        *   Can be either:
            *   An Okta user ID (e.g., "00u1ero7vZFVEIYLWPBN")
            *   A user's login/email (e.g., "john.doe@example.com")
        *   Note: This parameter is passed as a direct positional argument.

    ## Default Output Fields
    If no specific attributes are requested, return these minimal fields:
    - id: User's unique Okta identifier
    - email: User's primary email address (from profile.email)
    - firstName: User's first name (from profile.firstName)
    - lastName: User's last name (from profile.lastName)
    - login: User's username (from profile.login)
    - status: User's current status (e.g., ACTIVE, SUSPENDED)
    - created: When the user was created

    If the user specifically asks for different attributes, return those instead of the default fields.
    If the user asks for "all" or "complete" data, return the full user object.

    ## Example Usage
    ```python
    # Get user by ID or email using handle_single_entity_request
    user_result = await handle_single_entity_request(
        method_name="get_user",
        entity_type="user",
        entity_id=user_id_or_login,
        method_args=[user_id_or_login]
    )
    
    # Check for errors or not found status
    if isinstance(user_result, dict) and "status" in user_result:
        return user_result
    
    # Return the user data directly - the results processor will handle formatting
    return user_result
    ```

    ## Error Handling
    If the user doesn't exist, returns: `{"status": "not_found", "entity": "user", "id": user_id_or_login}`
    If another error occurs, returns: `{"status": "error", "error": error_message}`

    ## Important Notes
    - Data returned by handle_single_entity_request is already in dictionary format
    - Access fields using dictionary syntax: item["property"]["field"] (not object.attribute syntax)    
    - This function is specifically designed for retrieving single entities (not collections)
    - Return the data directly without additional transformation
    - The results processor will handle filtering fields based on query context
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
    Retrieves all groups that an Okta user belongs to by user ID or login (email). Returns group information including ID, name, and type for each group membership.

    # Tool Documentation: Okta List User Groups API Tool

    ## Goal
    This tool retrieves all groups that an Okta user belongs to.

    ## Core Functionality
    Retrieves groups associated with a specific user.

    ## Parameters
    *   **`user_id_or_login`** (Required, String):
        *   The unique identifier or login (usually email) of the user.
        *   Can be either:
            *   An Okta user ID (e.g., "00u1ero7vZFVEIYLWPBN")
            *   A user's login/email (e.g., "john.doe@example.com")

    ## Default Output Fields
    If no specific attributes are requested, return these minimal fields for each group:
    - id: Group's unique Okta identifier
    - name: Group name (from profile.name)
    - type: Group type (Usually "OKTA_GROUP")

    ## Example Usage
    ```python
    # Convert email to user ID if needed
    if "@" in user_id_or_login:
        user, resp, err = normalize_okta_response(await client.get_user(user_id_or_login))
        if err or not user:
            return {"status": "error" if err else "not_found", "id": user_id_or_login}
        user_id = user.id
    else:
        user_id = user_id_or_login
    
    # Get groups for this user
    groups = await paginate_results(
        "list_user_groups",
        method_args=[user_id],  # Must be in a list
        entity_name="groups"
    )
    
    # Return results directly
    if isinstance(groups, dict) and "status" in groups:
        return groups
    return groups
    ```

    ## Error Handling
    If the user doesn't exist, returns: `{"status": "not_found", "id": user_id_or_login}`
    If another error occurs, returns: `{"status": "error", "error": message}`
    If no groups are found, returns an empty list `[]`

    ## Important Notes
    - Data returned by paginate_results is already in dictionary format (not objects)
    - Access fields using dictionary syntax: item["property"]["field"] (not object.attribute syntax)    
    - Pass user_id in method_args as a list
    - Return data directly without transformation
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass


@register_tool(
    name="list_factors",
    entity_type="user",
    aliases=["user_factors", "get_user_factors", "list_factors", "authentication_factors"]
)
async def list_factors(client, user_id_or_login):
    """
    Retrieves all authentication factors enrolled for a specific Okta user. IMPORTANT: Requires user ID (not login/email).

    # Tool Documentation: Okta List User Factors API Tool

    ## Goal
    This tool retrieves all authentication factors that an Okta user has enrolled.

    ## Core Functionality
    Retrieves MFA factors associated with a specific user with detailed factor information.

    ## Parameters
    *   **`user_id_or_login`** (Required, String):
        *   The unique identifier of the user.
        *   Must be a valid Okta user ID (e.g., "00ub0oNGTSWTBKOLGLNR")
        *   Cannot be a login or email - must be converted to ID first if needed

    ## API Details
    * Endpoint: GET /api/v1/users/{userId}/factors
    * Path Parameters:
        * userId (required): ID of an existing Okta user (e.g., "00ub0oNGTSWTBKOLGLNR")

    ## Default Output Fields
    If no specific attributes are requested, return these minimal fields for each factor:
    - id: Factor's unique identifier
    - factorType: The type of factor (e.g., "sms", "push", "webauthn", "email")
    - provider: The provider of the factor (e.g., "OKTA", "GOOGLE", "SYMANTEC")
    - status: Current status of the factor (e.g., "ACTIVE", "PENDING_ACTIVATION")
    - created: When the factor was enrolled

    ## Example Usage
    ```python
    # Get user ID first if needed (usually when user_id_or_login is an email or login)
    user_result = await handle_single_entity_request(
        method_name="get_user",
        entity_type="user",
        entity_id=user_id_or_login,
        method_args=[user_id_or_login]
    )
    
    # Check if user retrieval failed
    if isinstance(user_result, dict) and "status" in user_result and user_result["status"] in ["not_found", "error"]:
        return user_result
    
    # Extract user ID from the user result
    user_id = user_result["id"]
    
    # Now get factors for this user ID using paginate_results for list operations
    factors = await paginate_results(
        "list_factors",
        query_params={},  # No query params needed for this operation
        method_args=[user_id],
        entity_name="factors"
    )
    
    # Check for errors in the factors result
    if isinstance(factors, dict) and "status" in factors and factors["status"] == "error":
        return factors
        
    return factors
    ```

    ## Error Handling
    If the user doesn't exist, returns: `{"status": "not_found", "entity": "user", "id": user_id}`
    If another error occurs, returns: `{"status": "error", "error": message}`
    If no factors are found, returns an empty list `[]`

    ## Important Notes
    - This tool requires a valid Okta user ID to retrieve factors
    - If you have a login or email, you MUST first perform a user lookup to get the ID
    - IMPORTANT: Use paginate_results (not handle_single_entity_request) when retrieving multiple items
    - handle_single_entity_request is only for single entity operations (like get_user)
    - paginate_results is for operations that return lists/collections (like list_factors)
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass

logger.info("Registered user tools")