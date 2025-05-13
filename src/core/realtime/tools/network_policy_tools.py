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
    Retrieves rules for ONE specific policy ID. Returns OBJECT with rules array and extracted zone_ids, NOT tuples. Required: policy_id (string). Always check for error status VALUES in operation_status field, not just presence of status field. Can be used in app-policy-rule flows.

    # Tool Documentation: Okta List Policy Rules API Tool
    IMPORTANT: YOU MUST ALWAYS PROVIDE CODE AS MENTIONED IN THE EXAMPLE USAGE or THAT MATCHES IT. DO NOT ADD ANYTHING ELSE.

    ## Goal
    List all rules for a specific policy ID (typically an access policy) and extract relevant network zone IDs.

    ## Core Functionality
    Retrieves the complete set of rules defined for a given policy, with details about conditions and actions.
    Automatically extracts network zone IDs from rules for further processing.

    ## Parameters
    *   **`policy_id`** (Required, String):
        *   The unique identifier of the policy whose rules to retrieve.
        *   Must be a valid Okta policy ID (e.g., "00pst3fOSDEBXPSHSUVG")
        *   In multi-step workflows, this often comes from an app_result's policyIds.accessPolicy

    *   **`query_params`** (Optional, Dictionary):
        *   Additional parameters for filtering or controlling the query.
        *   Not needed for most use cases.

    ## Multi-Step Usage
    *   Typically used after retrieving an application with get_application
    *   Access policy_id from app_result: `policy_id = app_result.get("policyIds", {}).get("accessPolicy")`
    *   If in Step 3+, check earlier steps: `if "app_result" in globals()...`
    *   Store results in a variable named 'policy_rules' for consistency
    *   Automatically extracts zone_ids for use with network zone tools

    ## Example Usage
    ```python
    if not policy_id:
        return {"operation_status": "error", "reason": "No policy ID provided"}

    result = await make_async_request(
        client.list_policy_rules,
        policy_id
    )
    
    if isinstance(result, dict) and result.get("operation_status") in ["error", "not_found", "dependency_failed"]:
        return result
    
    # Extract network zone IDs from rules
    zone_ids = []
    if isinstance(result, list):
        for rule in result:
            if "conditions" in rule and "network" in rule["conditions"]:
                network = rule["conditions"]["network"]
                if "include" in network:
                    for item in network["include"]:
                        if item.get("type") == "ZONE" and "id" in item:
                            zone_id = item["id"]
                            if zone_id not in zone_ids:
                                zone_ids.append(zone_id)
    
    return {
        "rules": result,
        "zone_ids": zone_ids
    }
    ```

    ## Error Handling
    If the policy doesn't exist, returns: `{"operation_status": "not_found", "entity": "policy", "id": policy_id}`
    If another error occurs, returns: `{"operation_status": "error", "reason": "Error message"}`

    ## Important Notes
    - Returns an enriched response with both rules and extracted metadata
    - Always includes zone_ids array if any zones are referenced in policy rules
    - Network zones are referenced in policy rules via conditions.network.include arrays
    - You can get zone details by passing the extracted IDs to the list_network_zones tool
    - Check error status in operation_status field, not in the standard status field
    - Error responses will have operation_status values like "error", "not_found", "dependency_failed"
    - In multi-step flows, check if policy_id exists in previous steps
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
    IMPORTANT: YOU MUST ALWAYS PROVIDE CODE AS MENTIONED IN THE EXAMPLE USAGE or THAT MATCHES IT. DO NOT ADD ANYTHING ELSE.

    ## Goal
    This tool retrieves network zones defined in an Okta organization, either all zones or specific zones by ID.

    ## Core Functionality
    Lists network zones with their configuration details.

    ## Parameters
    *   **`zone_ids`** (Optional, List[str]):
        *   List of specific zone IDs to retrieve.
        *   If provided, only returns information about these specific zones.
        *   If not provided (or empty), returns all zones in the organization.
        *   In multi-step workflows, often comes from policy_rules["zone_ids"]

    ## Default Output Fields
    Each network zone contains:
    - id: Zone's unique identifier
    - name: Display name of the zone
    - status: ACTIVE or INACTIVE
    - created/lastUpdated: Timestamps
    - gateways: Array of IP address objects (for IP-based zones)
    - proxies: Array of proxy server objects (if configured)
    - type: IP or DYNAMIC (location-based)

    ## Multi-Step Usage
    *   Often used after list_policy_rules to get details about zones used in policies
    *   Access zone_ids from policy_rules: `zone_ids = policy_rules.get("zone_ids", [])`
    *   If in Step 3+, check earlier steps: `if "policy_rules" in globals()...`
    *   Store results in a variable named 'zones' for consistency

   ## Example Usage
    ```python
    all_zones = await paginate_results(
        method_name="list_network_zones",
        query_params={},
        entity_name="zones"
    )
    
    if isinstance(all_zones, dict) and all_zones.get("operation_status") in ["error", "not_found", "dependency_failed"]:
        return all_zones
    
    # Filter zones by ID if needed
    if zone_ids:
        filtered_zones = [zone for zone in all_zones if zone.get("id") in zone_ids]
        return filtered_zones
    
    return all_zones
    ```

    ## Error Handling
    If an error occurs, returns: `{"operation_status": "error", "reason": "Error message"}`
    If no zones are found, returns an empty list `[]`
    If a specific zone ID is not found, it will be omitted from results

    ## Important Notes
    - Data returned is in dictionary format (not objects)
    - Access fields using dictionary syntax: zone["gateways"] (not object.attribute syntax)
    - Network zones define IP ranges or locations that can be used in policy rules
    - Zone IDs are referenced in policy rule conditions (network.connection.include)
    - DYNAMIC zones are based on geographic location rather than IP addresses
    - In multi-step flows, check if zone_ids exists in previous steps
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
    Retrieves ONE specific network zone by ID. Use with handle_single_entity_request which returns a DICTIONARY, NOT tuple. Required: zone_id (string). Contains complete zone config including gateways, proxies, IP ranges. Check response for operation_status field values.

    # Tool Documentation: Okta Get Network Zone Details API Tool
    IMPORTANT: YOU MUST ALWAYS PROVIDE CODE AS MENTIONED IN THE EXAMPLE USAGE or THAT MATCHES IT. DO NOT ADD ANYTHING ELSE.

    ## Goal
    This tool retrieves detailed information about a specific Okta network zone.

    ## Core Functionality
    Gets complete information about a network zone configuration.

    ## Parameters
    *   **`zone_id`** (Required, String):
        *   The unique identifier of the network zone to retrieve.
        *   Must be an Okta zone ID (e.g., "nzowdja3hKaMgfaQe0g3")
        *   In multi-step flows, often obtained from policy rules or network zone list

    ## Default Output Fields
    The complete network zone object with all properties:
    - id: Zone's unique identifier
    - name: Display name of the zone
    - status: ACTIVE or INACTIVE
    - created/lastUpdated: Timestamps
    - gateways: Array of IP address objects with CIDR format addresses
    - proxies: Array of proxy server objects (if configured)
    - type: IP or DYNAMIC (location-based)

    ## Multi-Step Usage
    *   Can be used after list_policy_rules or list_network_zones
    *   Often follows retrieving a zone_id from policy conditions
    *   If in Step 3+, check earlier steps: `if "zones" in globals()...`
    *   Store the result in a variable named 'zone_result' for clarity

    ## Example Usage
    ```python
    zone_result = await handle_single_entity_request(
        method_name="get_network_zone",
        entity_type="network_zone",
        entity_id=zone_id,
        method_args=[zone_id]
    )
    
    if isinstance(zone_result, dict) and zone_result.get("operation_status") in ["error", "not_found", "dependency_failed"]:
        return zone_result
    
    return zone_result
    ```

    ## Error Handling
    If the zone doesn't exist, returns: `{"operation_status": "not_found", "entity": "network_zone", "id": zone_id}`
    If another error occurs, returns: `{"operation_status": "error", "reason": "Error message"}`

    ## Important Notes
    - For singular entities, use handle_single_entity_request (not paginate_results)
    - Data returned is already in dictionary format (not objects)
    - Access fields using dictionary syntax: zone["gateways"] (not object.attribute syntax)
    - IP zones contain gateways array with CIDR format addresses
    - Dynamic zones contain locations array with country/region information
    - Use this tool to look up zone details when you have a zone ID from a policy rule
    - Check error status in operation_status field, not in the standard status field
    - In multi-step flows, check if zone_id exists in previous steps
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass

logger.info("Registered policy and network tools")