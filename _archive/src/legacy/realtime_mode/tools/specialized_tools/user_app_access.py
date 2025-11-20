"""
Access-related tool definitions for Okta API operations.
Contains documentation and examples for access operations.
"""

from typing import List, Dict, Any, Optional
from src.utils.tool_registry import register_tool
from src.utils.logging import get_logger
from src.utils.pagination_limits import normalize_okta_response, make_async_request
import json

# Configure logging
logger = get_logger(__name__)

# ---------- Tool Registration ----------

@register_tool(
    name="can_user_access_application",
    entity_type="access",
    aliases=["check_app_access", "user_app_access", "app_access_check"]
)
async def can_user_access_application(client, user_identifier=None, group_identifier=None, app_identifier=None, ip_address=None):
    """
    #SPECIAL TOOL: Use this single use special tool call to answer the questions like : "Can a user or group access a specific application?", "Can user X access application Y?". No other tool is needed to answer this question.

    # Tool Documentation: Can User Access Application

    ## Parameters
    *   **`user_identifier`** (Optional, String):
        *   The email, login, or ID of the user to check
        *   Example: "john.doe@example.com" or "00u1a2b3cDeFgHiJk4"

    *   **`group_identifier`** (Optional, String):
        *   The name or ID of a group to check access for
        *   Example: "Sales Team" or "00g1a2b3cDeFgHiJk4"

    *   **`app_identifier`** (Required, String):
        *   The application name, label, or ID to check access for
        *   Example: "Salesforce" or "0oa1a2b3cDeFgHiJk4"

    *   **`ip_address`** (Optional, String):
        *   IP address to check against network zone restrictions
        *   Example: "192.168.1.1"

    ## Return Value
    *   A single dictionary containing:
        *   `status`: "success" for successful checks, "error" for failures, or "not_found" for missing entities
        *   `user_details` or `group_details`: Information about the user or group
        *   `application_details`: Information about the application
        *   `assignment`: Whether and how the user is assigned to the application
        *   `policy_rules`: Access policies and rules that apply
        *   `network_zones`: Details about network zones referenced in policies

    ## IMPORTANT: This function returns a single dictionary, not a tuple. Do not use tuple unpacking when calling this function.

    ## Example Usage
    ```python
    # Check user access
    result = await can_user_access_application(
        client=client,
        user_identifier="john.doe@example.com",
        app_identifier="salesforce"
    )
    
    # Check group access
    result = await can_user_access_application(
        client=client,
        group_identifier="sales-team",
        app_identifier="salesforce"
    )
    
    # INCORRECT USAGE - DO NOT DO THIS
    # result, _, error = await can_user_access_application(...)  # WRONG!
    ```
    """
    # Basic validation
    if not app_identifier:
        return {"status": "error", "error": "app_identifier must be provided"}
        
    if not user_identifier and not group_identifier:
        return {"status": "error", "error": "Either user_identifier or group_identifier must be provided"}
    
    # Initialize result structure
    result = {
        "status": "collecting_data"
    }
    
    # Step 1: Get application details
    try:
        app = None
        logger.info(f"Searching for application: {app_identifier}")
        
        # Try direct lookup by ID first if it looks like an ID
        if app_identifier.startswith("0oa"):
            try:
                response = await client.get_application(app_identifier)
                items, resp, err = normalize_okta_response(response)
                
                if not err and items:
                    if isinstance(items, list) and items:
                        app = items[0]
                    else:
                        app = items
            except Exception as e:
                logger.info(f"Direct application lookup failed: {str(e)}")
        
        # If direct lookup fails, search by name/label
        if not app:
            query_params = {"q": app_identifier}
            response = await client.list_applications(query_params)
            items, resp, err = normalize_okta_response(response)
            
            if not err and items:
                # Try to find exact or partial match
                app_identifier_lower = app_identifier.lower()
                
                # First try exact match on label or name
                for potential_app in items:
                    if hasattr(potential_app, 'as_dict'):
                        potential_app = potential_app.as_dict()
                    
                    app_label = potential_app.get("label", "").lower()
                    app_name = potential_app.get("name", "").lower()
                    
                    if app_identifier_lower == app_label or app_identifier_lower == app_name:
                        app = potential_app
                        logger.info(f"Found exact match for application: {potential_app.get('label')}")
                        break
                
                # If no exact match, try contains match
                if not app:
                    for potential_app in items:
                        if hasattr(potential_app, 'as_dict'):
                            potential_app = potential_app.as_dict()
                        
                        app_label = potential_app.get("label", "").lower()
                        app_name = potential_app.get("name", "").lower()
                        
                        if app_identifier_lower in app_label or app_identifier_lower in app_name:
                            app = potential_app
                            logger.info(f"Found partial match for application: {potential_app.get('label')}")
                            break
                
                # If no specific match, use first app in results
                if not app and items:
                    first_app = items[0]
                    if hasattr(first_app, 'as_dict'):
                        first_app = first_app.as_dict()
                    
                    app = first_app
                    logger.info(f"Using first result from search: {first_app.get('label')}")
        
        # If still no app found, try listing all applications
        if not app:
            logger.info("Attempting to list all applications")
            response = await client.list_applications()
            items, resp, err = normalize_okta_response(response)
            
            if not err and items:
                # Try exact and partial matches again
                app_identifier_lower = app_identifier.lower()
                
                for potential_app in items:
                    if hasattr(potential_app, 'as_dict'):
                        potential_app = potential_app.as_dict()
                    
                    app_label = potential_app.get("label", "").lower()
                    app_name = potential_app.get("name", "").lower()
                    
                    if (app_identifier_lower == app_label or 
                        app_identifier_lower == app_name or
                        app_identifier_lower in app_label or 
                        app_identifier_lower in app_name):
                        app = potential_app
                        logger.info(f"Found match in full application list: {potential_app.get('label')}")
                        break
        
        if not app:
            logger.info(f"No matching application found for: {app_identifier}")
            return {
                "status": "not_found",
                "entity": "application",
                "id": app_identifier
            }
        
        # Extract application details
        logger.info(f"Successfully found application: {app.get('label')} ({app.get('id')})")
        
        # Extract access policy ID from _links if available
        access_policy_id = None
        access_policy_href = app.get("_links", {}).get("accessPolicy", {}).get("href")
        if access_policy_href and "/" in access_policy_href:
            access_policy_id = access_policy_href.split("/")[-1]
        
        # Extract sign-on mode safely
        sign_on_mode = app.get("signOnMode")
        if hasattr(sign_on_mode, "value"):
            sign_on_mode = sign_on_mode.value
        
        # Extract status safely
        status = app.get("status")
        if hasattr(status, "value"):
            status = status.value
        
        result["application_details"] = {
            "id": app.get("id"),
            "name": app.get("name"),
            "label": app.get("label"),
            "status": status,
            "signOnMode": sign_on_mode,
            "accessPolicyID": access_policy_id
        }
        
        app_id = app.get("id")
    
    except Exception as e:
        logger.error(f"Error retrieving application information: {str(e)}")
        return {
            "status": "error",
            "error": f"Failed to retrieve application information: {str(e)}"
        }
    
    # Step 2: Get user details if user identifier is provided
    if user_identifier:
        try:
            user = None
            logger.info(f"Looking up user: {user_identifier}")
            
            # Try direct lookup by ID
            try:
                response = await client.get_user(user_identifier)
                items, resp, err = normalize_okta_response(response)
                
                if not err and items:
                    if isinstance(items, list) and items:
                        user = items[0]
                    else:
                        user = items
            except Exception:
                # ID lookup failed, try search by email
                if "@" in user_identifier:
                    query_params = {"filter": f'profile.email eq "{user_identifier}"'}
                else:
                    # Try by login
                    query_params = {"filter": f'profile.login eq "{user_identifier}"'}
                
                response = await client.list_users(query_params)
                items, resp, err = normalize_okta_response(response)
                
                if not err and items and len(items) > 0:
                    user = items[0]
                else:
                    # Try with q parameter as last resort
                    query_params = {"q": user_identifier}
                    response = await client.list_users(query_params)
                    items, resp, err = normalize_okta_response(response)
                    
                    if not err and items and len(items) > 0:
                        user = items[0]
            
            if not user:
                logger.info(f"User not found: {user_identifier}")
                return {
                    "status": "not_found",
                    "entity": "user",
                    "id": user_identifier
                }
            
            # Extract user details
            if hasattr(user, 'as_dict'):
                user = user.as_dict()
            
            # Handle custom user fields
            status = user.get("status")
            if hasattr(status, "value"):
                status = status.value
            
            result["user_details"] = {
                "id": user.get("id"),
                "email": user.get("profile", {}).get("email"),
                "login": user.get("profile", {}).get("login"),
                "firstName": user.get("profile", {}).get("firstName"),
                "lastName": user.get("profile", {}).get("lastName"),
                "status": status
            }
            
            user_id = user.get("id")
            
            # Get user's factors
            logger.info(f"Fetching authentication factors for user: {user_id}")
            response = await client.list_factors(user_id)
            items, resp, err = normalize_okta_response(response)
            
            if not err and items:
                result["users_registered_factors"] = []
                
                for factor in items:
                    if hasattr(factor, 'as_dict'):
                        factor = factor.as_dict()
                    
                    # Handle factor properties safely
                    factor_type = factor.get("factorType")
                    if hasattr(factor_type, "value"):
                        factor_type = factor_type.value
                    
                    factor_provider = factor.get("provider")
                    if hasattr(factor_provider, "value"):
                        factor_provider = factor_provider.value
                    
                    factor_status = factor.get("status")
                    if hasattr(factor_status, "value"):
                        factor_status = factor_status.value
                    
                    result["users_registered_factors"].append({
                        "id": factor.get("id"),
                        "type": factor_type,
                        "provider": factor_provider,
                        "status": factor_status,
                        "name": factor.get("profile", {}).get("name", "")
                    })
            
            # Check user-to-app assignment
            logger.info(f"Checking if user {user_id} is assigned to application {app_id}")
            result["assignment"] = {}
            
            # Check direct assignment
            try:
                response = await client.get_application_user(app_id, user_id)
                items, resp, err = normalize_okta_response(response)
                
                if not err and items:
                    result["assignment"]["direct_assignment"] = True
                    result["assignment"]["is_assigned"] = True
                    logger.info(f"User {user_id} is directly assigned to application {app_id}")
                else:
                    result["assignment"]["direct_assignment"] = False
                    
                    # Check group assignment
                    logger.info(f"Checking if user {user_id} has group-based access to application {app_id}")
                    
                    # Get user's groups
                    groups_response = await client.list_user_groups(user_id)
                    groups_items, groups_resp, groups_err = normalize_okta_response(groups_response)
                    
                    if not groups_err and groups_items:
                        user_groups = []
                        user_group_ids = []
                        
                        for group in groups_items:
                            if hasattr(group, 'as_dict'):
                                group = group.as_dict()
                            
                            user_groups.append({
                                "id": group.get("id"),
                                "name": group.get("profile", {}).get("name")
                            })
                            user_group_ids.append(group.get("id"))
                        
                        result["user_groups"] = user_groups
                        
                        # Get groups assigned to the application
                        app_groups_response = await client.list_application_group_assignments(app_id)
                        app_groups_items, app_groups_resp, app_groups_err = normalize_okta_response(app_groups_response)
                        
                        if not app_groups_err and app_groups_items:
                            group_assignments = []
                            
                            for app_group in app_groups_items:
                                if hasattr(app_group, 'as_dict'):
                                    app_group = app_group.as_dict()
                                
                                if app_group.get("id") in user_group_ids:
                                    # Find the matching group info
                                    for user_group in user_groups:
                                        if user_group["id"] == app_group.get("id"):
                                            group_assignments.append(user_group)
                                            break
                            
                            result["assignment"]["via_groups"] = group_assignments
                            result["assignment"]["is_assigned"] = len(group_assignments) > 0
                            
                            if len(group_assignments) > 0:
                                logger.info(f"User {user_id} has access to application {app_id} via groups")
                            else:
                                logger.info(f"User {user_id} is not assigned to application {app_id} via groups")
                        else:
                            result["assignment"]["via_groups"] = []
                            result["assignment"]["is_assigned"] = False
                            logger.info(f"No groups found assigned to application {app_id}")
            except Exception as e:
                logger.error(f"Error checking user assignment: {str(e)}")
                result["assignment"]["error"] = str(e)
            
            # Get application access policy if available
            if access_policy_id:
                logger.info(f"Fetching policy rules for application policy: {access_policy_id}")
                try:
                    # Get policy details
                    policy_url = f"/api/v1/policies/{access_policy_id}"
                    policy_response = await make_async_request(client, "GET", policy_url)
                    
                    if isinstance(policy_response, dict) and policy_response.get("status") == "error":
                        logger.error(f"Error fetching policy: {policy_response.get('error')}")
                        result["policy_error"] = policy_response.get("error")
                    elif isinstance(policy_response, list) and policy_response:
                        # Handle case where response is a list - use the first item
                        policy_item = policy_response[0]
                        if hasattr(policy_item, 'as_dict'):
                            policy_item = policy_item.as_dict()
                        
                        result["access_policy"] = {
                            "id": policy_item.get("id"),
                            "name": policy_item.get("name"),
                            "status": policy_item.get("status"),
                            "type": policy_item.get("type")
                        }
                    elif policy_response:
                        # Handle case where response is a single object
                        if hasattr(policy_response, 'as_dict'):
                            policy_response = policy_response.as_dict()
                        
                        result["access_policy"] = {
                            "id": policy_response.get("id"),
                            "name": policy_response.get("name"),
                            "status": policy_response.get("status"),
                            "type": policy_response.get("type")
                        }
                    else:
                        logger.error("No policy data returned")
                        result["policy_error"] = "No policy data returned"
                    
                    # Get policy rules if we successfully got policy data
                    if "access_policy" in result:
                        rules_url = f"/api/v1/policies/{access_policy_id}/rules"
                        rules_response = await make_async_request(client, "GET", rules_url)
                        
                        if isinstance(rules_response, dict) and rules_response.get("status") == "error":
                            logger.error(f"Error fetching policy rules: {rules_response.get('error')}")
                            result["rules_error"] = rules_response.get("error")
                        else:
                            # Store rules
                            result["policy_rules"] = []
                            
                            # Ensure rules_response is a list for iteration
                            rules_list = []
                            if isinstance(rules_response, list):
                                rules_list = rules_response
                            elif rules_response:
                                rules_list = [rules_response]
                            
                            # Track zone IDs used in rules
                            zone_ids = set()
                            
                            for rule in rules_list:
                                if hasattr(rule, 'as_dict'):
                                    rule = rule.as_dict()
                                
                                rule_info = {
                                    "id": rule.get("id"),
                                    "name": rule.get("name"),
                                    "status": rule.get("status"),
                                    "priority": rule.get("priority"),
                                    "system": rule.get("system", False)
                                }
                                
                                # Extract rule conditions
                                conditions = rule.get("conditions", {})
                                if conditions:
                                    # Network zones
                                    if "network" in conditions:
                                        network_conditions = conditions.get("network", {})
                                        rule_info["network_conditions"] = network_conditions
                                        
                                        # Collect zone IDs for later retrieval
                                        if network_conditions.get("connection") == "ZONE" and "include" in network_conditions:
                                            for zone_id in network_conditions.get("include", []):
                                                zone_ids.add(zone_id)
                                    
                                    # User type conditions
                                    if "people" in conditions:
                                        rule_info["people_conditions"] = conditions.get("people", {})
                                    
                                    # Device conditions
                                    if "device" in conditions:
                                        rule_info["device_conditions"] = conditions.get("device", {})
                                
                                # Extract authentication requirements
                                actions = rule.get("actions", {})
                                if actions and "appSignOn" in actions:
                                    app_sign_on = actions.get("appSignOn", {})
                                    
                                    # Access type (ALLOW/DENY)
                                    rule_info["access"] = app_sign_on.get("access")
                                    
                                    # Verification requirements
                                    if "verificationMethod" in app_sign_on:
                                        verification = app_sign_on.get("verificationMethod", {})
                                        rule_info["verification_method"] = {
                                            "factorMode": verification.get("factorMode"),
                                            "type": verification.get("type"),
                                            "constraints": verification.get("constraints", [])
                                        }
                                
                                result["policy_rules"].append(rule_info)
                            
                            # Fetch network zone details
                            if zone_ids:
                                result["network_zones"] = {}
                                logger.info(f"Fetching details for {len(zone_ids)} network zones")
                                
                                for zone_id in zone_ids:
                                    try:
                                        # Use list_network_zones with filter instead of get_network_zone
                                        query_params = {
                                            'filter': f'id eq "{zone_id}"'
                                        }
                                        
                                        # Call list_network_zones with the filter
                                        zones_resp, resp, err = await client.list_network_zones(query_params)
                                        
                                        if err:
                                            logger.error(f"Failed to get zone details for {zone_id}: {err}")
                                            result["network_zones"][zone_id] = {"error": f"Failed to fetch zone details: {err}"}
                                            continue
                                            
                                        if not zones_resp or len(zones_resp) == 0:
                                            logger.error(f"Zone with ID {zone_id} not found")
                                            result["network_zones"][zone_id] = {"error": f"Zone not found"}
                                            continue
                                            
                                        # Convert the first (and should be only) zone to dictionary
                                        zone_data = zones_resp[0].as_dict() if hasattr(zones_resp[0], 'as_dict') else zones_resp[0]
                                        
                                        # Process all enum values in the zone data
                                        processed_zone = {}
                                        
                                        # Handle top-level enum fields explicitly
                                        for key, value in zone_data.items():
                                            if key in ["type", "status", "usage"] and hasattr(value, "value"):
                                                processed_zone[key] = value.value
                                            elif key == "gateways" and isinstance(value, list):
                                                # Handle gateways specially
                                                processed_gateways = []
                                                for gateway in value:
                                                    processed_gateway = {}
                                                    for k, v in gateway.items():
                                                        if hasattr(v, "value"):
                                                            processed_gateway[k] = v.value
                                                        else:
                                                            processed_gateway[k] = v
                                                    processed_gateways.append(processed_gateway)
                                                processed_zone[key] = processed_gateways
                                            else:
                                                processed_zone[key] = value
                                                
                                        result["network_zones"][zone_id] = processed_zone
                                        
                                    except Exception as e:
                                        logger.error(f"Error fetching network zone {zone_id}: {str(e)}")
                                        result["network_zones"][zone_id] = {"error": str(e)}
                
                except Exception as e:
                    logger.error(f"Error fetching policy information: {str(e)}")
                    result["policy_error"] = str(e)
        
        except Exception as e:
            logger.error(f"Error retrieving user information: {str(e)}")
            return {
                "status": "error",
                "error": f"Failed to retrieve user information: {str(e)}"
            }
    
    # Step 3: Get group details if group identifier is provided
    elif group_identifier:
        try:
            group = None
            logger.info(f"Looking up group: {group_identifier}")
            
            # Try direct lookup by ID
            try:
                response = await client.get_group(group_identifier)
                items, resp, err = normalize_okta_response(response)
                
                if not err and items:
                    if isinstance(items, list) and items:
                        group = items[0]
                    else:
                        group = items
            except Exception:
                # ID lookup failed, try search by name
                query_params = {"q": group_identifier}
                response = await client.list_groups(query_params)
                items, resp, err = normalize_okta_response(response)
                
                if not err and items and len(items) > 0:
                    # Try to find exact match first
                    group_identifier_lower = group_identifier.lower()
                    
                    for potential_group in items:
                        if hasattr(potential_group, 'as_dict'):
                            potential_group = potential_group.as_dict()
                        
                        group_name = potential_group.get("profile", {}).get("name", "").lower()
                        
                        if group_name == group_identifier_lower:
                            group = potential_group
                            break
                    
                    # If no exact match, use first result
                    if not group:
                        group = items[0]
                        if hasattr(group, 'as_dict'):
                            group = group.as_dict()
            
            if not group:
                logger.info(f"Group not found: {group_identifier}")
                return {
                    "status": "not_found",
                    "entity": "group",
                    "id": group_identifier
                }
            
            # Extract group details
            result["group_details"] = {
                "id": group.get("id"),
                "name": group.get("profile", {}).get("name"),
                "description": group.get("profile", {}).get("description")
            }
            
            group_id = group.get("id")
            
            # Check group-to-app assignment
            logger.info(f"Checking if group {group_id} is assigned to application {app_id}")
            result["assignment"] = {}
            
            try:
                # Check if group is assigned to application
                response = await client.list_application_group_assignments(app_id)
                items, resp, err = normalize_okta_response(response)
                
                if not err and items:
                    assigned = False
                    
                    for app_group in items:
                        if hasattr(app_group, 'as_dict'):
                            app_group = app_group.as_dict()
                        
                        if app_group.get("id") == group_id:
                            assigned = True
                            break
                    
                    result["assignment"]["is_assigned"] = assigned
                    logger.info(f"Group {group_id} assignment to application {app_id}: {assigned}")
                else:
                    result["assignment"]["is_assigned"] = False
                    logger.info(f"No group assignments found for application {app_id}")
            
            except Exception as e:
                logger.error(f"Error checking group assignment: {str(e)}")
                result["assignment"]["error"] = str(e)
            
            # Get application access policy if available
            if access_policy_id:
                logger.info(f"Fetching policy rules for application policy: {access_policy_id}")
                try:
                    # Get policy details
                    policy_url = f"/api/v1/policies/{access_policy_id}"
                    policy_response = await make_async_request(client, "GET", policy_url)
                    
                    if isinstance(policy_response, dict) and policy_response.get("status") == "error":
                        logger.error(f"Error fetching policy: {policy_response.get('error')}")
                        result["policy_error"] = policy_response.get("error")
                    else:
                        # Store policy details
                        result["access_policy"] = {
                            "id": policy_response.get("id"),
                            "name": policy_response.get("name"),
                            "status": policy_response.get("status"),
                            "type": policy_response.get("type")
                        }
                        
                        # Get policy rules
                        rules_url = f"/api/v1/policies/{access_policy_id}/rules"
                        rules_response = await make_async_request(client, "GET", rules_url)
                        
                        if isinstance(rules_response, dict) and rules_response.get("status") == "error":
                            logger.error(f"Error fetching policy rules: {rules_response.get('error')}")
                            result["rules_error"] = rules_response.get("error")
                        else:
                            # Store rules
                            result["policy_rules"] = []
                            
                            # Track zone IDs used in rules
                            zone_ids = set()
                            
                            if isinstance(rules_response, list):
                                for rule in rules_response:
                                    if hasattr(rule, 'as_dict'):
                                        rule = rule.as_dict()
                                    
                                    rule_info = {
                                        "id": rule.get("id"),
                                        "name": rule.get("name"),
                                        "status": rule.get("status"),
                                        "priority": rule.get("priority"),
                                        "system": rule.get("system", False)
                                    }
                                    
                                    # Extract rule conditions
                                    conditions = rule.get("conditions", {})
                                    if conditions:
                                        # Network zones
                                        if "network" in conditions:
                                            network_conditions = conditions.get("network", {})
                                            rule_info["network_conditions"] = network_conditions
                                            
                                            # Collect zone IDs for later retrieval
                                            if network_conditions.get("connection") == "ZONE" and "include" in network_conditions:
                                                for zone_id in network_conditions.get("include", []):
                                                    zone_ids.add(zone_id)
                                        
                                        # Group type conditions
                                        if "people" in conditions:
                                            rule_info["people_conditions"] = conditions.get("people", {})
                                        
                                        # Device conditions
                                        if "device" in conditions:
                                            rule_info["device_conditions"] = conditions.get("device", {})
                                    
                                    # Extract authentication requirements
                                    actions = rule.get("actions", {})
                                    if actions and "appSignOn" in actions:
                                        app_sign_on = actions.get("appSignOn", {})
                                        
                                        # Access type (ALLOW/DENY)
                                        rule_info["access"] = app_sign_on.get("access")
                                        
                                        # Verification requirements
                                        if "verificationMethod" in app_sign_on:
                                            verification = app_sign_on.get("verificationMethod", {})
                                            rule_info["verification_method"] = {
                                                "factorMode": verification.get("factorMode"),
                                                "type": verification.get("type"),
                                                "constraints": verification.get("constraints", [])
                                            }
                                    
                                    result["policy_rules"].append(rule_info)
                            
                            # Fetch network zone details
                            if zone_ids:
                                result["network_zones"] = {}
                                logger.info(f"Fetching details for {len(zone_ids)} network zones")
                                
                                for zone_id in zone_ids:
                                    try:
                                        # Use list_network_zones with filter instead of get_network_zone
                                        query_params = {
                                            'filter': f'id eq "{zone_id}"'
                                        }
                                        
                                        # Call list_network_zones with the filter
                                        zones_resp, resp, err = await client.list_network_zones(query_params)
                                        
                                        if err:
                                            logger.error(f"Failed to get zone details for {zone_id}: {err}")
                                            result["network_zones"][zone_id] = {"error": f"Failed to fetch zone details: {err}"}
                                            continue
                                            
                                        if not zones_resp or len(zones_resp) == 0:
                                            logger.error(f"Zone with ID {zone_id} not found")
                                            result["network_zones"][zone_id] = {"error": f"Zone not found"}
                                            continue
                                            
                                        # Convert the first (and should be only) zone to dictionary
                                        zone_data = zones_resp[0].as_dict() if hasattr(zones_resp[0], 'as_dict') else zones_resp[0]
                                        
                                        # Process all enum values in the zone data
                                        processed_zone = {}
                                        
                                        # Handle top-level enum fields explicitly
                                        for key, value in zone_data.items():
                                            if key in ["type", "status", "usage"] and hasattr(value, "value"):
                                                processed_zone[key] = value.value
                                            elif key == "gateways" and isinstance(value, list):
                                                # Handle gateways specially
                                                processed_gateways = []
                                                for gateway in value:
                                                    processed_gateway = {}
                                                    for k, v in gateway.items():
                                                        if hasattr(v, "value"):
                                                            processed_gateway[k] = v.value
                                                        else:
                                                            processed_gateway[k] = v
                                                    processed_gateways.append(processed_gateway)
                                                processed_zone[key] = processed_gateways
                                            else:
                                                processed_zone[key] = value
                                                
                                        result["network_zones"][zone_id] = processed_zone
                                        
                                    except Exception as e:
                                        logger.error(f"Error fetching network zone {zone_id}: {str(e)}")
                                        result["network_zones"][zone_id] = {"error": str(e)}
                            
                except Exception as e:
                    logger.error(f"Error fetching policy information: {str(e)}")
                    result["policy_error"] = str(e)
        
        except Exception as e:
            logger.error(f"Error retrieving group information: {str(e)}")
            return {
                "status": "error",
                "error": f"Failed to retrieve group information: {str(e)}"
            }
    
    # Step 4: Set final status and return result
    result["status"] = "success"
    
    # Print the complete result object for debugging
    try:
        logger.info("\n===== FULL ACCESS CHECK RESULTS =====")
        logger.info(f"User: {user_identifier}, Group: {group_identifier}, Application: {app_identifier}")
        
        # Print nicely formatted JSON
        formatted_result = json.dumps(result, indent=2, default=str)
        logger.info(f"Complete Result Object:\n{formatted_result}")
    except Exception as e:
        logger.error(f"Error printing results: {str(e)}")
    
    return result

logger.info("Registered application access tools")