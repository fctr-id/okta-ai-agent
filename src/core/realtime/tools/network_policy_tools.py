"""
Policy and network zone related tool definitions for Okta API operations.
Contains documentation and examples for policy and network zone operations.
"""

from typing import List, Dict, Any, Optional
from src.utils.tool_registry import register_tool
from src.utils.logging import get_logger
import os, traceback

# Configure logging
logger = get_logger(__name__)

# Helper function for direct API calls when needed
from src.utils.security_config import is_okta_url_allowed
from src.utils.error_handling import SecurityError
from src.utils.pagination_limits import make_async_request

# ---------- Tool Registration ----------


@register_tool(
    name="list_policy_rules",
    entity_type="policy_rule",
    aliases=["policy_rules", "get_policy_rules", "show_rules"]
)
async def list_policy_rules(client, policy_id: str, query_params: Optional[Dict] = None):
    """
    Retrieves all policy rules associated with the specified policy ID and extracts network zone IDs.

    # Tool Documentation: Okta List Policy Rules API Tool

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

@register_tool(
    name="list_network_zones",
    entity_type="network",
    aliases=["network_zones", "get_network_zones"]
)
async def list_network_zones(client, zone_ids: Optional[List[str]] = None):
    """
    Lists network zones defined in the Okta organization. Can retrieve all zones or specific ones by ID.

    # Tool Documentation: Okta List Network Zones API Tool

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
    all_zones = await list_network_zones(client)
    
    # Get specific zones by ID
    zone_ids = ["nzondmw5liMu8IdyB5d7", "nzondmw5liMu8IdyC6e8"]
    specific_zones = await list_network_zones(client, zone_ids=zone_ids)
    
    # Extract zone IDs from policy rules
    zone_ids_to_fetch = []
    for rule in policy_rules:
        if (rule.get("conditions") and rule["conditions"].get("network") and 
            rule["conditions"]["network"].get("include")):
            zone_ids_to_fetch.extend(rule["conditions"]["network"]["include"])
    
    # Fetch only those zones
    relevant_zones = await list_network_zones(client, zone_ids=zone_ids_to_fetch)
    
    # Return results
    return all_zones  # or specific_zones or relevant_zones
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
    # Get network zone details using handle_single_entity_request
    zone = await handle_single_entity_request(
        method_name="get_zone",
        entity_type="network_zone",
        entity_id=zone_id,
        method_args=[zone_id]
    )
    
    # Check for errors or not found status
    if isinstance(zone, dict) and "status" in zone:
        return zone
    
    # Return the zone data directly
    return zone
    ```

    ## Error Handling
    If the zone doesn't exist, returns: `{"status": "not_found", "entity": "zone", "id": zone_id}`
    If another error occurs, returns: `{"status": "error", "error": error_message}`

    ## Important Notes
    - Data returned by handle_single_entity_request is already in dictionary format
    - Access fields using dictionary syntax: zone["gateways"] (not object.attribute syntax)
    - IP zones contain gateways array with CIDR format addresses
    - Dynamic zones contain locations array with country/region information
    - Use this tool to look up zone details when you have a zone ID from a policy rule
    - This function is specifically designed for retrieving single entities (not collections)
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass

logger.info("Registered policy and network tools")