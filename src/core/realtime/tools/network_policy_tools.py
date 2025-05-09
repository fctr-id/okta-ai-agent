"""
Policy and network zone related tool definitions for Okta API operations.
Contains documentation and examples for policy and network zone operations.
"""

from typing import List, Dict, Any, Optional
from src.utils.tool_registry import register_tool
from src.utils.logging import get_logger

# Configure logging
logger = get_logger(__name__)

# ---------- Tool Registration ----------

@register_tool(
    name="list_policy_rules",
    entity_type="policy_rule",
    aliases=["policy_rules", "get_policy_rules", "show_rules"]
)
async def list_policy_rules(client, policy_id: str, query_params: Optional[Dict] = None):
    """
    Retrieves rules for ONE specific policy ID. Returns OBJECT with rules array and extracted zone_ids, NOT tuples. Required: policy_id (string). Always check for error status VALUES (error/not_found), not just presence of status field. Can be used in app-policy-rule flows.

    # Tool Documentation: Okta List Policy Rules API Tool
    #IMPORTANT: YOU MUST ALWAYS PROVIDE CODE AS MENTIONED IN THE EXAMPLE USAGE or THAT MATCHES IT. DO NOT ADD ANYTHING ELSE.

    ## Goal
    List all rules for a specific policy ID (typically an access policy) and extract relevant network zone IDs.

    ## Core Functionality
    Retrieves the complete set of rules defined for a given policy, with details about conditions and actions.
    Automatically extracts network zone IDs from rules for further processing.

    ## Parameters
    *   **`policy_id`** (Required, String):
        *   The unique identifier of the policy whose rules to retrieve.
        *   Must be a valid Okta policy ID (e.g., "00pst3fOSDEBXPSHSUVG")

    *   **`query_params`** (Optional, Dictionary):
        *   Additional parameters for filtering or controlling the query.
        *   Not needed for most use cases.

    ## Example Usage Using Okta SDK Client
    ```python
    # If this is part of an app-policy-rule flow, check for app_result errors first
    # IMPORTANT: Check for error status VALUES, not just the presence of a status field
    if isinstance(app_result, dict) and "status" in app_result and app_result["status"] in ["error", "not_found", "dependency_failed"]:
        return {"status": "dependency_failed", "dependency": "get_application_details", "error": app_result.get("error", "Unknown error")}
    
    # If we're in an app-policy-rule flow, extract the policy ID from the app
    if 'app_result' in locals() or 'app_result' in globals():
        # Get the access policy ID from the app_result object
        access_policy_id = None
        
        # First check if it's in the policyIds structure
        if isinstance(app_result, dict):
            if "policyIds" in app_result and "accessPolicy" in app_result["policyIds"]:
                access_policy_id = app_result["policyIds"]["accessPolicy"]
            
            # If not found, try to extract from _links
            elif "_links" in app_result and "accessPolicy" in app_result["_links"]:
                access_policy_href = app_result["_links"]["accessPolicy"]["href"]
                access_policy_id = access_policy_href.split("/")[-1]
        
        # Use the extracted policy ID if found
        if access_policy_id:
            policy_id = access_policy_id
    
    # Validate we have a policy ID to work with
    if not policy_id:
        return {"status": "error", "error": "No policy ID provided or found in application details"}

    # Get the policy rules (automatically includes zone IDs)
    result = await list_policy_rules(client, policy_id)
    
    # If we want to fetch network zone details
    if result.get("zone_ids") and len(result["zone_ids"]) > 0:
        zones = await list_network_zones(client, zone_ids=result["zone_ids"])
        
        # Return complete information including zones
        return {
            "rules": result["rules"],
            "zones": zones,
            "policy_id": policy_id
        }
    
    return result
    ```

    ## Error Handling
    If the policy doesn't exist, the API will return a 404 error.
    If another error occurs, returns: `{"status": "error", "error": detailed_error_message}`

    ## Important Notes
    - Returns an enriched response with both rules and extracted metadata
    - Always includes zone_ids array if any zones are referenced in policy rules
    - Network zones are referenced in policy rules via conditions.network.include arrays
    - You can get zone details by passing the extracted IDs to the list_network_zones tool
    - Standard Okta objects have a "status" field with values like "ACTIVE" - these are not error indicators
    - Error responses will have "status" values like "error", "not_found", or "dependency_failed"
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass

@register_tool(
    name="list_network_zones",
    entity_type="network",
    aliases=["network_zones", "get_network_zones"]
)
async def list_network_zones(client, zone_ids: Optional[List[str]] = None):
    """
    Lists Okta network zones. Returns LIST of zone objects via paginate_results, NOT tuples. Optional: zone_ids list to filter specific zones. Each zone contains ID, name, status, gateways (IPs), proxies, type (IP/DYNAMIC). Access fields using zone["property"] dictionary syntax.

    # Tool Documentation: Okta List Network Zones API Tool
    #IMPORTANT: YOU MUST ALWAYS PROVIDE CODE AS MENTIONED IN THE EXAMPLE USAGE or THAT MATCHES IT. DO NOT ADD ANYTHING ELSE.

    ## Goal
    This tool retrieves network zones defined in an Okta organization, either all zones or specific zones by ID.

    ## Core Functionality
    Lists network zones with their configuration details.

    ## Parameters
    *   **`zone_ids`** (Optional, List[str]):
        *   List of specific zone IDs to retrieve.
        *   If provided, only returns information about these specific zones.
        *   If not provided (or empty), returns all zones in the organization.

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
    all_zones = await paginate_results(
        "list_network_zones",  # SDK method name
        query_params={},
        method_args=[],
        entity_name="zones"
    )
    
    # Filter zones by ID if needed
    if zone_ids:
        filtered_zones = [zone for zone in all_zones if zone.get("id") in zone_ids]
        return filtered_zones
    else:
        return all_zones
    ```

    ## Error Handling
    If an error occurs, returns: `{"status": "error", "error": error_message}`
    If no zones are found, returns an empty list `[]`
    If a specific zone ID is not found, it will be omitted from results

    ## Important Notes
    - Data returned is in dictionary format (not objects)
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
    Retrieves ONE specific network zone by ID. Use with handle_single_entity_request which returns a DICTIONARY, NOT tuple. Required: zone_id (string). Contains complete zone config including gateways, proxies, IP ranges. Check response for status="error" or status="not_found".

    # Tool Documentation: Okta Get Network Zone Details API Tool
    #IMPORTANT: YOU MUST ALWAYS PROVIDE CODE AS MENTIONED IN THE EXAMPLE USAGE or THAT MATCHES IT. DO NOT ADD ANYTHING ELSE.

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

    # Get network zone by ID using handle_single_entity_request
    zone_result = await handle_single_entity_request(
        method_name="get_network_zone",  # SDK method name
        entity_type="network_zone",
        entity_id=zone_id,
        method_args=[zone_id]
    )
    
    # Check for errors or not found status
    if isinstance(zone_result, dict) and "status" in zone_result and zone_result["status"] in ["error", "not_found"]:
        return zone_result
    
    # Return the zone data directly
    return zone_result
    
    # If you need to find by name instead of ID:
    if not zone_id.startswith("nz"):
        # List all zones
        zones = await paginate_results(
            "list_network_zones",
            query_params={},
            method_args=[],
            entity_name="zones"
        )
        
        # Find zone by name
        for zone in zones:
            if zone.get("name") == zone_id:
                return zone
                
        return {"status": "not_found", "entity": "network_zone", "name": zone_id}
    ```

    ## Error Handling
    If the zone doesn't exist, returns: `{"status": "not_found", "entity": "network_zone", "id": zone_id}`
    If another error occurs, returns: `{"status": "error", "error": error_message}`

    ## Important Notes
    - For singular entities, use handle_single_entity_request (not paginate_results)
    - Data returned is already in dictionary format (not objects)
    - Access fields using dictionary syntax: zone["gateways"] (not object.attribute syntax)
    - IP zones contain gateways array with CIDR format addresses
    - Dynamic zones contain locations array with country/region information
    - Use this tool to look up zone details when you have a zone ID from a policy rule
    - When a name is provided instead of an ID, the function will attempt to find the zone by name
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass

logger.info("Registered policy and network tools")