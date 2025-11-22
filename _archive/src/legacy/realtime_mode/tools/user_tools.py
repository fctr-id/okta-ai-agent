"""
User-related tool definitions for Okta API operations.
Contains documentation and examples for user operations.
"""

from typing import List, Dict, Any
from src.utils.tool_registry import register_tool
from src.utils.logging import get_logger

logger = get_logger(__name__)

# ---------- Tool Registration ----------

@register_tool(
    name="list_users",
    entity_type="user",
    aliases=["user_search", "users_search", "searchusers", "find_users", "list_users"]
)
async def list_users(client, search=None, limit=None):
    """
    Searches for Okta users matching criteria. Returns a LIST of user objects, NOT tuples. ALWAYS prefix user attributes with 'profile.' (e.g., search='profile.email eq "user@example.com"'). Uses automatic pagination for complete results regardless of count.

    # Tool Documentation: Okta User Search API Tool
    IMPORTANT: YOU MUST ALWAYS PROVIDE CODE AS MENTIONED IN THE EXAMPLE USAGE or THAT MATCHES IT. DO NOT ADD ANYTHING ELSE.

    ## Goal
    This tool searches for users in the Okta directory based on specified criteria.
    
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

    ## Multi-Step Usage
    *   This tool can be used in the first step to find users
    *   In later steps you can reference this step's results as `users` if they were stored with that variable name

    ## Example Usage
    ```python
    query_params = {"limit": 200}
    
    if search:
        query_params["search"] = search
    else:
        user_email = "aiden.garcia@fctr.io"
        query_params["search"] = f'profile.email eq "{user_email}"'
        
    users = await paginate_results(
        method_name="list_users",
        query_params=query_params,
        entity_name="users"
    )
    
    if isinstance(users, dict) and users.get("operation_status") in ["error", "not_found", "dependency_failed"]:
        return users
    
    return users
    ```

    ## Error Handling
    If the API call fails, returns an error object: `{"operation_status": "error", "error": error_message}`

    ## Important Notes
    - Data returned by paginate_results is already in dictionary format (not objects)
    - Access fields using dictionary syntax: item["property"]["field"] (not object.attribute syntax)    
    - Pagination is handled automatically for large result sets
    - Double quotes must be used inside the search string and properly escaped
    - ALWAYS use the 'profile.' prefix when searching user attributes (profile.login, profile.email, etc.)
    - DO NOT use attributes without the profile prefix (e.g., 'login eq "value"' will fail)
    - DO NOT use single quotes for the search values
    """
    pass


@register_tool(
    name="get_user",
    entity_type="user",
    aliases=["user_details", "get_user", "getuserdetails", "user_info"]
)
async def get_user(client, user_id_or_login):
    """
    Retrieves ONE specific user by ID or login/email. Returns a DICTIONARY with user details, NOT a tuple. Contains normalized profile data with common fields like id, email, firstName, lastName, login, and status. Use handle_single_entity_request to process errors properly.

    # Tool Documentation: Okta Get User Details API Tool
    IMPORTANT: YOU MUST ALWAYS PROVIDE CODE AS MENTIONED IN THE EXAMPLE USAGE or THAT MATCHES IT. DO NOT ADD ANYTHING ELSE.

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

    ## Multi-Step Usage
    *   This tool is often the first step in multi-step workflows
    *   Store the result in a variable named `user_result` for clarity
    *   Extract the user ID with `user_id = user_result.get("id")` for use in later steps
    *   Later steps can access both the `user_result` and `user_id` variables

    ## Example Usage
    ```python
    user_result = await handle_single_entity_request(
        method_name="get_user",
        entity_type="user", 
        entity_id=user_id_or_login,
        method_args=[user_id_or_login]
    )
    
    if isinstance(user_result, dict) and user_result.get("operation_status") in ["error", "not_found", "dependency_failed"]:
        return user_result
    
    # Extract and store user_id for later steps if needed
    user_id = user_result.get("id")
    
    return user_result
    ```

    ## Error Handling
    If the user doesn't exist, returns: `{"operation_status": "not_found", "entity": "user", "id": user_id_or_login}`
    If another error occurs, returns: `{"operation_status": "error", "error": error_message}`

    ## Important Notes
    - Data returned by handle_single_entity_request is already in dictionary format
    - Access fields using dictionary syntax: item["property"]["field"] (not object.attribute syntax)    
    - This function is specifically designed for retrieving single entities (not collections)
    - Return the data directly without additional transformation
    - The results processor will handle filtering fields based on query context
    """
    pass


@register_tool(
    name="list_user_groups",
    entity_type="user",
    aliases=["user_groups", "get_user_groups"]
)
async def list_user_groups(client, user_id):
    """
    Lists ALL groups that ONE specific Okta user belongs to. Returns a LIST of group objects, NOT tuples. Accepts user ID. Uses automatic pagination to retrieve all group memberships regardless of count.

    # Tool Documentation: Okta List User Groups API Tool
    IMPORTANT: YOU MUST ALWAYS PROVIDE CODE AS MENTIONED IN THE EXAMPLE USAGE or THAT MATCHES IT. DO NOT ADD ANYTHING ELSE.

    ## Goal
    This tool retrieves all groups that an Okta user belongs to.

    ## Core Functionality
    Retrieves groups associated with a specific user.

    ## Parameters
    *   **`user_id`** (Required, String):
        *   The unique identifier of the user.
        *   Must be an Okta user ID (e.g., "00u1ero7vZFVEIYLWPBN")
        *   Note: If you have a user's email or login, first convert it to a user ID using the get_user tool
        *   In multi-step workflows, this value usually comes from a previous step's result

    ## Default Output Fields
    If no specific attributes are requested, return these minimal fields for each group:
    - id: Group's unique Okta identifier
    - name: Group name (from profile.name)
    - type: Group type (Usually "OKTA_GROUP")

    ## Multi-Step Usage
    *   Typically used after retrieving user details with get_user
    *   In Step 2+, get user_id from previous step: `user_id = user_result.get("id")`
    *   If in Step 3+, check if user_id exists in previous variables: `if "user_result" in globals()...`
    *   Store results in a variable named 'groups' for consistency

    ## Example Usage
    ```python
    groups = await paginate_results(
        method_name="list_user_groups",
        method_args=[user_id],
        entity_name="groups"
    )
    
    if isinstance(groups, dict) and groups.get("operation_status") in ["error", "not_found", "dependency_failed"]:
        return groups
    
    return groups
    ```

    ## Error Handling
    If the user doesn't exist, returns: `{"operation_status": "not_found", "id": user_id}`
    If another error occurs, returns: `{"operation_status": "error", "error": message}`
    If no groups are found, returns an empty list `[]`

    ## Important Notes
    - Data returned by paginate_results is already in dictionary format (not objects)
    - Access fields using dictionary syntax: item["property"]["field"] (not object.attribute syntax)    
    - Pass user_id in method_args as a list
    - Return data directly without transformation
    - This tool expects a valid Okta user ID, not an email or login
    - In multi-step flows, check if user_id exists in previous steps if not available in current result
    """
    pass


@register_tool(
    name="list_factors",
    entity_type="user",
    aliases=["user_factors", "get_user_factors", "list_factors", "authentication_factors"]
)
async def list_factors(client, user_id):
    """
    Lists ALL authentication factors enrolled for ONE specific user. Returns a LIST of factor objects, NOT tuples. REQUIRES user ID. Contains factor types, providers, and status. Uses automatic pagination.

    # Tool Documentation: Okta List User Factors API Tool
    IMPORTANT: YOU MUST ALWAYS PROVIDE CODE AS MENTIONED IN THE EXAMPLE USAGE or THAT MATCHES IT. DO NOT ADD ANYTHING ELSE.

    ## Goal
    This tool retrieves all authentication factors that an Okta user has enrolled.

    ## Core Functionality
    Retrieves MFA factors associated with a specific user with detailed factor information.

    ## Parameters
    *   **`user_id`** (Required, String):
        *   The unique identifier of the user.
        *   Must be a valid Okta user ID (e.g., "00ub0oNGTSWTBKOLGLNR")
        *   Note: If you have a user's email or login, first convert it to a user ID using the get_user tool
        *   In multi-step workflows, may come from user_result.id from a prior get_user step

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

    ## Multi-Step Usage
    *   Typically used after retrieving user details with get_user
    *   May be used after listing groups or other user operations
    *   For Step 3+, when user_id isn't in the immediate result:
        - First check previous step variables: `if "user_result" in globals()...`
        - Then extract user_id from the appropriate variable
    *   Store results in a variable named 'factors' for consistency

    ## Example Usage
    ```python
    factors = await paginate_results(
        method_name="list_factors",
        method_args=[user_id],
        entity_name="factors"
    )
    
    if isinstance(factors, dict) and factors.get("operation_status") in ["error", "not_found", "dependency_failed"]:
        return factors
    
    return factors
    ```

    ## Error Handling
    If the user doesn't exist, returns: `{"operation_status": "not_found", "entity": "user", "id": user_id}`
    If another error occurs, returns: `{"operation_status": "error", "error": message}`
    If no factors are found, returns an empty list `[]`

    ## Important Notes
    - This tool requires a valid Okta user ID to retrieve factors
    - If you have a login or email, first perform a user lookup to get the ID in a separate step
    - Use paginate_results for retrieving multiple items in a collection
    - Variables from all previous steps remain available - check user_result or user_id from earlier steps
    - When used in Step 3+, check for user_id in earlier steps if not in immediate previous result
    """
    pass

logger.info("Registered user tools")