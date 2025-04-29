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
        method_args=[policy_id],  # Pass policy_id as a positional argument
        query_params=query_params,
        entity_name="rules"
    )
    
    # Check for errors
    if isinstance(rules, dict) and "status" in rules and rules["status"] == "error":
        return rules
    
    # Return results directly
    return rules
    ```

    ## Error Handling
    If the policy doesn't exist, returns: `{"status": "not_found", "entity": "policy", "id": policy_id}`
    If another error occurs, returns: `{"status": "error", "error": error_message}`
    If no rules are found, returns an empty list `[]`

    ## Important Notes
    - Data returned by paginate_results is already in dictionary format (not objects)
    - Access fields using dictionary syntax: rule["name"] (not object.attribute syntax)
    - When using paginate_results, pass the policy_id in method_args=[policy_id]
    - Policy rules define conditions and actions applied to authentication and authorization
    - Network zones referenced by zone IDs can be looked up using list_network_zones
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
    # Get the rule using paginate_results
    rule = await paginate_results(
        "get_policy_rule",
        method_args=[policy_id, rule_id],  # Pass both IDs as positional arguments
        entity_name="rule"
    )
    
    # Check for errors
    if isinstance(rule, dict) and "status" in rule and rule["status"] == "error":
        return rule
    
    # Check if rule was found
    if not rule or (isinstance(rule, list) and len(rule) == 0):
        return {"status": "not_found", "entity": "rule", "id": rule_id}
    
    # Handle case where response might be a list with one rule
    if isinstance(rule, list) and len(rule) > 0:
        rule = rule[0]
    
    # Return the rule data directly
    return rule
    ```

    ## Error Handling
    If the policy doesn't exist, returns: `{"status": "not_found", "entity": "policy", "id": policy_id}`
    If the rule doesn't exist, returns: `{"status": "not_found", "entity": "rule", "id": rule_id}`
    If another error occurs, returns: `{"status": "error", "error": error_message}`

    ## Important Notes
    - Data returned by paginate_results is already in dictionary format (not objects)
    - Access fields using dictionary syntax: rule["name"] (not object.attribute syntax)
    - Pass both policy_id and rule_id in method_args=[policy_id, rule_id]
    - Authentication methods can be found in actions.appSignOn.constraints.authenticationMethods
    - Network zones are referenced by ID and can be looked up with list_network_zones
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass


@register_tool(
    name="list_network_zones",
    entity_type="network",
    aliases=["network_zones", "get_network_zones"]
)
async def list_network_zones(client):
    """
    Lists all network zones defined in the Okta organization. Returns details about each network zone including name, gateways, proxies, and IP ranges.

    # Tool Documentation: Okta List Network Zones API Tool

    ## Goal
    This tool retrieves all network zones defined in an Okta organization.

    ## Core Functionality
    Lists network zones with their configuration details.

    ## Parameters
    This tool doesn't require any parameters beyond the Okta client.

    ## Default Output Fields
    Each network zone contains:
    - id: Zone's unique identifier
    - name: Display name of the zone
    - status: ACTIVE or INACTIVE
    - created/lastUpdated: Timestamps
    - gateways: Array of IP address objects (for IP-based zones)
    - proxies: Array of proxy server objects (if configured)
    - type: IP or DYNAMIC (location-based)

    ## Example Usage
    ```python
    # Get all network zones
    zones = await paginate_results(
        "list_zones",
        entity_name="zones"
    )
    
    # Check for errors
    if isinstance(zones, dict) and "status" in zones and zones["status"] == "error":
        return zones
    
    # Return results directly
    return zones
    ```

    ## Error Handling
    If an error occurs, returns: `{"status": "error", "error": error_message}`
    If no zones are found, returns an empty list `[]`

    ## Important Notes
    - Data returned by paginate_results is already in dictionary format (not objects)
    - Access fields using dictionary syntax: zone["gateways"] (not object.attribute syntax)
    - Network zones define IP ranges or locations that can be used in policy rules
    - Zone IDs are referenced in policy rule conditions (network.connection.include)
    - DYNAMIC zones are based on geographic location rather than IP addresses
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass


@register_tool(
    name="get_network_zone",
    entity_type="network",
    aliases=["zone_details", "network_zone_details"]
)
async def get_network_zone(client, zone_id):
    """
    Retrieves detailed information about a specific Okta network zone by ID. Returns complete configuration of the zone including name, status, gateways, proxies, and IP ranges.

    # Tool Documentation: Okta Get Network Zone Details API Tool

    ## Goal
    This tool retrieves detailed information about a specific Okta network zone.

    ## Core Functionality
    Gets complete information about a network zone configuration.

    ## Parameters
    *   **`zone_id`** (Required, String):
        *   The unique identifier of the network zone to retrieve.
        *   Must be an Okta zone ID (e.g., "nzowdja3hKaMgfaQe0g3")

    ## Default Output Fields
    The complete network zone object with all properties:
    - id: Zone's unique identifier
    - name: Display name of the zone
    - status: ACTIVE or INACTIVE
    - created/lastUpdated: Timestamps
    - gateways: Array of IP address objects with CIDR format addresses
    - proxies: Array of proxy server objects (if configured)
    - type: IP or DYNAMIC (location-based)

    ## Example Usage
    ```python
    # Get network zone details
    zone = await paginate_results(
        "get_zone",
        method_args=[zone_id],  # Pass zone_id as a positional argument
        entity_name="zone"
    )
    
    # Check for errors
    if isinstance(zone, dict) and "status" in zone and zone["status"] == "error":
        return zone
    
    # Check if zone was found
    if not zone or (isinstance(zone, list) and len(zone) == 0):
        return {"status": "not_found", "entity": "zone", "id": zone_id}
    
    # Handle case where response might be a list with one zone
    if isinstance(zone, list) and len(zone) > 0:
        zone = zone[0]
    
    # Return the zone data directly
    return zone
    ```

    ## Error Handling
    If the zone doesn't exist, returns: `{"status": "not_found", "entity": "zone", "id": zone_id}`
    If another error occurs, returns: `{"status": "error", "error": error_message}`

    ## Important Notes
    - Data returned by paginate_results is already in dictionary format (not objects)
    - Access fields using dictionary syntax: zone["gateways"] (not object.attribute syntax)
    - IP zones contain gateways array with CIDR format addresses
    - Dynamic zones contain locations array with country/region information
    - Use this tool to look up zone details when you have a zone ID from a policy rule
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass

logger.info("Registered policy and network tools")