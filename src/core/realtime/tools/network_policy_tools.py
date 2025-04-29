"""
Policy and network zone related tool definitions for Okta API operations.
Contains documentation and examples for policy and network zone operations.
"""

from typing import List, Dict, Any, Optional
from src.utils.tool_registry import register_tool
from src.utils.logging import get_logger
import os

# Configure logging
logger = get_logger(__name__)

# Helper function for direct API calls when needed
from src.utils.security_config import is_okta_url_allowed
from src.utils.error_handling import SecurityError

# Helper function for direct API calls when needed
async def make_async_request(client, method: str, url: str, headers: Dict = None, json_data: Dict = None):
    """Make an async HTTP request to the Okta API."""
    # First validate if the URL is allowed
    if not is_okta_url_allowed(url):
        error_msg = f"Security violation: URL {url} is not an authorized Okta URL"
        logger.error(error_msg)
        raise SecurityError(error_msg)
        
    try:
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            async with session.request(
                method=method,
                url=url,
                headers=headers,
                json=json_data
            ) as response:
                # Raise exception for HTTP errors
                response.raise_for_status()
                
                # Return the JSON response
                return await response.json()
    except Exception as e:
        logger.error(f"Error making async HTTP request: {str(e)}")
        raise

# ---------- Tool Registration ----------

@register_tool(
    name="list_policy_rules",
    entity_type="policy",
    aliases=["policy_rules", "get_policy_rules"]
)
@register_tool(
    name="list_policy_rules",
    entity_type="policy",
    aliases=["policy_rules", "get_policy_rules"]
)
async def list_policy_rules(client, policy_id, after=None, limit=50):
    """
    Lists all rules for a specific Okta policy. Returns detailed information about each policy rule including name, priority, conditions, and actions.

    # Tool Documentation: Okta List Policy Rules API Tool

    ## Goal
    This tool retrieves all rules for a specific Okta policy.

    ## Core Functionality
    Lists rules associated with a policy with support for pagination.

    ## Parameters
    *   **`policy_id`** (Required, String):
        *   The unique identifier of the policy.
        *   Must be an Okta policy ID (e.g., "00p1abc2defGHIjk3LMn")

    *   **`after`** (String):
        *   Pagination cursor for the next page of results.
        *   Obtained from a previous response's pagination information.

    *   **`limit`** (Integer):
        *   Specifies the number of results per page (1-200).
        *   Default: 50 if not specified

    ## Default Output Fields
    The response includes all policy rule objects with complete nested properties:
    - id: Rule's unique identifier
    - name: Display name of the rule
    - priority: Order of evaluation (lower is higher priority)
    - conditions: Authentication contexts where the rule applies (IP, user, device, etc.)
    - actions: What happens when the rule matches (factor requirements, session settings)
    - status: ACTIVE or INACTIVE

    ## Example Usage
    ```python
    # Prepare request parameters
    query_params = {}
    
    if limit:
        query_params["limit"] = limit
        
    if after:
        query_params["after"] = after
    
    # Get all rules for this policy with pagination
    rules = await paginate_results(
        "list_policy_rules",
        method_args=[policy_id],  # Pass policy_id as a positional argument in a list
        query_params=query_params,  # Pass additional query parameters
        entity_name="rules"
    )
    
    # Check for errors
    if isinstance(rules, dict) and "status" in rules and rules["status"] == "error":
        return rules
    
    # Handle empty results
    if not rules:
        return {"rules": [], "policy_id": policy_id, "total_rules": 0}
    
    # Format response with results
    result = {
        "rules": rules,  # paginate_results already converts objects to dictionaries
        "policy_id": policy_id,
        "total_rules": len(rules)
    }
    
    return result
    ```

    ## Error Handling
    If the policy doesn't exist, returns: `{"status": "not_found", "entity": "policy", "id": policy_id}`
    If another error occurs, returns: `{"status": "error", "error": error_message}`
    If no rules are found, returns an empty list for the rules field

    ## Important Implementation Notes
    - When using paginate_results, pass the policy_id in method_args=[policy_id]
    - Policy rules define conditions and actions applied to authentication and authorization
    - Common rule properties include name, priority, conditions, and actions
    - Actions may contain factormode and constraints (what type of authentication is required)
    - Network zones referenced by zone IDs (network.connection.include) can be looked up using list_network_zones
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass


@register_tool(
    name="get_policy_rule",
    entity_type="policy",
    aliases=["policy_rule_details", "rule_details"]
)
async def get_policy_rule(client, policy_id, rule_id):
    """
    Retrieves detailed information about a specific Okta policy rule. Returns complete details about the rule including name, priority, conditions, and actions.

    # Tool Documentation: Okta Get Policy Rule API Tool

    ## Goal
    This tool retrieves detailed information about a specific policy rule.

    ## Core Functionality
    Gets complete information about a single rule within a policy.

    ## Parameters
    *   **`policy_id`** (Required, String):
        *   The unique identifier of the policy that contains the rule.
        *   Must be an Okta policy ID (e.g., "00p1abc2defGHIjk3LMn")

    *   **`rule_id`** (Required, String):
        *   The unique identifier of the specific rule to retrieve.
        *   Must be an Okta rule ID (e.g., "0pr1ero7vZFVEIYLWPBN")

    ## Default Output Fields
    The response includes the complete policy rule object with all nested properties:
    - id: Rule's unique identifier
    - name: Display name of the rule
    - priority: Order of evaluation (lower is higher priority)
    - conditions: Authentication contexts where the rule applies
    - actions: What happens when the rule matches
    - status: ACTIVE or INACTIVE

    ## Example Usage
    ```python
    # Get the Okta organization URL and API token
    org_url = os.getenv('OKTA_CLIENT_ORGURL').rstrip('/')
    api_token = os.getenv('OKTA_API_TOKEN')
    
    if not org_url:
        return {"status": "error", "error": "OKTA_CLIENT_ORGURL environment variable not set"}
    if not api_token:
        return {"status": "error", "error": "OKTA_API_TOKEN environment variable not set"}
    
    # Setup headers for API call
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': f'SSWS {api_token}'
    }
    
    # Make the direct API request
    url = f"{org_url}/api/v1/policies/{policy_id}/rules/{rule_id}"
    
    try:
        # Use direct API call
        response = await make_async_request(
            client=client,
            method="GET",
            url=url,
            headers=headers
        )
        
        # Return the raw response
        return response
    except Exception as e:
        return {"status": "error", "error": str(e)}
    ```

    ## Error Handling
    If the policy doesn't exist, returns: `{"status": "not_found", "entity": "policy", "id": policy_id}`
    If the rule doesn't exist, returns: `{"status": "not_found", "entity": "rule", "id": rule_id}`
    If another error occurs, returns: `{"status": "error", "error": error_message}`

    ## Important Implementation Notes
    - This tool makes a direct API call rather than using the client library
    - Authentication methods can be found in actions.appSignOn.constraints.authenticationMethods
    - Network zones are referenced by ID and can be looked up with list_network_zones
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass


@register_tool(
    name="list_policy_rules",
    entity_type="policy",
    aliases=["policy_rules", "get_policy_rules"]
)
async def list_policy_rules(client, policy_id, after=None, limit=50):
    """
    Lists all rules for a specific Okta policy. MUST retrive the policy ID first before fetching rules. Returns detailed information about each policy rule including name, priority, conditions, and actions.

    # Tool Documentation: Okta List Policy Rules API Tool

    ## Goal
    This tool retrieves all rules for a specific Okta policy.

    ## Core Functionality
    Lists rules associated with a policy with support for pagination.

    ## Parameters
    *   **`policy_id`** (Required, String):
        *   The unique identifier of the policy.
        *   Must be an Okta policy ID (e.g., "00p1abc2defGHIjk3LMn")

    *   **`after`** (String):
        *   Pagination cursor for the next page of results.
        *   Obtained from a previous response's pagination information.

    *   **`limit`** (Integer):
        *   Specifies the number of results per page (1-200).
        *   Default: 50 if not specified

    ## Default Output Fields
    The response includes all policy rule objects with complete nested properties:
    - id: Rule's unique identifier
    - name: Display name of the rule
    - priority: Order of evaluation (lower is higher priority)
    - conditions: Authentication contexts where the rule applies (IP, user, device, etc.)
    - actions: What happens when the rule matches (factor requirements, session settings)
    - status: ACTIVE or INACTIVE

    ## Example Usage
    ```python
    # Prepare request parameters
    query_params = {}
    
    if limit:
        query_params["limit"] = limit
        
    if after:
        query_params["after"] = after
    
    # Get all rules for this policy with pagination
    rules = await paginate_results(
        "list_policy_rules",
        method_args=[policy_id],  # Pass policy_id as a positional argument in a list
        query_params=query_params,  # Pass additional query parameters
        entity_name="rules"
    )
    
    # Check for errors
    if isinstance(rules, dict) and "status" in rules and rules["status"] == "error":
        return rules
    
    # Handle empty results
    if not rules:
        return {"rules": [], "policy_id": policy_id, "total_rules": 0}
    
    # Format response with results
    result = {
        "rules": rules,  # paginate_results already converts objects to dictionaries
        "policy_id": policy_id,
        "total_rules": len(rules)
    }
    
    return result
    ```

    ## Error Handling
    If the policy doesn't exist, returns: `{"status": "not_found", "entity": "policy", "id": policy_id}`
    If another error occurs, returns: `{"status": "error", "error": error_message}`
    If no rules are found, returns an empty list for the rules field

    ## Important Implementation Notes
    - When using paginate_results, pass the policy_id in method_args=[policy_id]
    - Policy rules define conditions and actions applied to authentication and authorization
    - Common rule properties include name, priority, conditions, and actions
    - Actions may contain factormode and constraints (what type of authentication is required)
    - Network zones referenced by zone IDs (network.connection.include) can be looked up using list_network_zones
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass

logger.info("Registered policy and network tools")