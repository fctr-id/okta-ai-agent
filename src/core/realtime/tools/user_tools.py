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
async def search_users(client, search=None, limit=None):
    """
    Searches for users in the Okta directory using advanced search expressions (SCIM filter syntax) with support for pagination. Returns user information on identity profile attributes.

    # Tool Documentation: Okta User Search API Tool

    ## Goal
    This tool searches for users in the Okta directory based on specified criteria.

    ## Core Functionality
    Searches for Okta users using advanced search expressions with support for pagination.

    ## Parameters
    *   **`search`** (String):
        *   Applies an advanced search filter using Okta's SCIM filter expression syntax.
        *   Okta recommends this parameter for optimal search performance.
        *   Examples:
            *   `profile.lastName eq \"Smith\"`
            *   `status eq \"ACTIVE\"`
            *   `profile.department eq \"Engineering\" and status eq \"ACTIVE\"`
            *   `lastUpdated gt \"2023-01-01T00:00:00.000Z\"`
            *   `id eq \"00u1ero7vZFVEIYLWPBN\"`
            *   `profile.firstName co \"Joh\"` (contains operator)

    *   **`limit`** (Integer):
        *   Specifies the maximum number of results to return per page.
        *   Pagination is handled automatically by the underlying function.

    ## Default Output Fields
    If no specific attributes are requested, return these minimal fields:
    - id: User's unique Okta identifier
    - email: User's primary email address (from profile.email)
    - firstName: User's first name (from profile.firstName)
    - lastName: User's last name (from profile.lastName)
    - status: User's current status (e.g., ACTIVE, SUSPENDED)

    If the user specifically asks for different attributes, return those instead of the default fields.
    If the user asks for "all" or "complete" data, return the full user objects.

    ## Search Operators
    *   **eq**: Equals - `status eq \"ACTIVE\"`
    *   **sw**: Starts with - `profile.firstName sw \"J\"` (for string fields)
    *   **co**: Contains - `profile.email co \"example\"` (only for firstName, lastName, email, and login)
    *   **gt/lt**: Greater than/Less than - `lastUpdated gt \"2023-01-01T00:00:00.000Z\"`
    *   **ge/le**: Greater than or equal/Less than or equal
    *   Combine with `and`, `or`, and parentheses for complex queries

    ## Example Usage
    ```python
    # Build query parameters
    query_params = {}
    
    if search:
        query_params["search"] = search
        
    if limit:
        query_params["limit"] = limit
    
    # Get users with pagination 
    users = await paginate_results(
        "list_users",
        query_params=query_params,
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
        minimal_users.append({
            "id": user["id"],
            "email": user["profile"].get("email"),
            "firstName": user["profile"].get("firstName"),
            "lastName": user["profile"].get("lastName"),
            "status": user["status"]
        })
    
    # Return the transformed results
    return minimal_users
    ```

    ## Example Search Syntax
    ```python
    # Correct syntax with double quotes
    query_params = {
        "search": "profile.firstName eq \"Dan\""
    }

    # For starts with
    query_params = {
        "search": "profile.firstName sw \"D\""
    }

    # For contains
    query_params = {
        "search": "profile.firstName co \"an\""
    }
    ```

    ## Error Handling
    If the API call fails, returns an error object: `{"status": "error", "error": error_message}`

    ## Important Notes
    - Pagination is handled automatically for large result sets
    - The Okta API limits results to 200 users per page
    - Results are already converted to dictionaries; do not call as_dict() on them
    - Double quotes must be used inside the search string and properly escaped
    - DO NOT use single quotes for the search values
    - Empty results are normal and will return an empty list []
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
    # Get user by ID or email
    user, resp, err = await client.get_user(user_id_or_login)
    if err:
        return {"status": "error", "error": str(err)}
    
    # If user not found (would be caught in error handling above but being explicit)
    if not user:
        return {"status": "not_found", "entity": "user", "id": user_id_or_login}
    
    user_details = user.as_dict()
    
    # Return default fields unless full data is requested
    minimal_user = {
        "id": user_details["id"],
        "email": user_details["profile"].get("email"),
        "firstName": user_details["profile"].get("firstName"),
        "lastName": user_details["profile"].get("lastName"),
        "login": user_details["profile"].get("login"),
        "status": user_details["status"],
        "created": user_details.get("created")
    }
    
    return minimal_user
    ```

    ## Error Handling
    If the user doesn't exist, returns: `{"status": "not_found", "entity": "user", "id": user_id_or_login}`
    If another error occurs, returns: `{"status": "error", "error": error_message}`

    ## Important Notes
    - Pass user_id_or_login as a positional argument: client.get_user(user_id)
    - Do NOT use named arguments: client.get_user(user_id=user_id)
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

    If the user specifically asks for different attributes, return those instead of the default fields.
    If the user asks for "all" or "complete" data, return the full group objects.

    ## Example Usage
    ```python
    # If input is an email/login rather than ID, look up the user ID first
    if "@" in user_id_or_login:
        user, resp, err = await client.get_user(user_id_or_login)
        if err:
            return {"status": "error", "error": str(err)}
        user_id = user.id
    else:
        # Input is already a user ID
        user_id = user_id_or_login
    
    # Get all groups for this user
    groups = await paginate_results(
        "list_user_groups",
        method_args=[user_id],  # Pass user_id as a positional argument in a list
        entity_name="groups"
    )
    
    # Check for errors
    if isinstance(groups, dict) and "status" in groups and groups["status"] == "error":
        return groups
    
    # Handle empty results
    if not groups:
        return []
    
    # Transform results to include only default fields
    minimal_groups = []
    for group in groups:
        minimal_groups.append({
            "id": group["id"],
            "name": group["profile"].get("name"),
            "type": group.get("type", "OKTA_GROUP")
        })
    
    return minimal_groups
    ```

    ## Error Handling
    If the user doesn't exist, returns: `{"status": "not_found", "entity": "user", "id": user_id_or_login}`
    If another error occurs, returns: `{"status": "error", "error": error_message}`
    If no groups are found, returns an empty list `[]`

    ## Important Implementation Notes
    - The method does NOT accept query_params
    - When using paginate_results, pass the user_id in method_args=[user_id]
    - Results are already converted to dictionaries; do not call as_dict() on them
    - Empty results are normal and will return an empty list []
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass

logger.info("Registered user tools")