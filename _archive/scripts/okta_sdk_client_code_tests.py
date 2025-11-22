import asyncio
import sys
import json
import os
import argparse
from pathlib import Path
from pprint import pprint
from dotenv import load_dotenv
from enum import Enum

# Load environment variables from .env file
load_dotenv()

# Add parent directory to path to find modules
sys.path.append(str(Path(__file__).parent.parent))

# Import Okta client
from okta.client import Client as OktaClient
from src.utils.pagination_limits import make_async_request

# Custom JSON encoder to handle Okta enum types
class OktaJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Enum):
            return obj.value
        return super().default(obj)

# Helper function to convert enums in dictionaries/lists
def convert_enums(data):
    if isinstance(data, dict):
        return {k: convert_enums(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [convert_enums(i) for i in data]
    elif isinstance(data, Enum):
        return data.value if hasattr(data, 'value') else str(data)
    else:
        return data

async def get_policy(client, policy_id):
    """Helper function to get policy details by ID"""
    try:
        policy_resp, resp, err = await client.get_policy(policy_id)
        if err:
            return {"error": f"API error retrieving policy: {err}"}
        return policy_resp.as_dict()
    except Exception as e:
        return {"error": f"Exception retrieving policy: {str(e)}"}

async def get_policy_rules(client, policy_id):
    """
    Helper function to get policy rules using make_async_request
    """
    try:
        # Use make_async_request to fetch policy rules
        url = f"/api/v1/policies/{policy_id}/rules"
        rules = await make_async_request(client, "GET", url)
        
        # Check if it's an error response
        if isinstance(rules, dict) and rules.get("errorCode"):
            return {"error": rules.get("errorSummary", "Unknown error")}
        
        # If successful, should be a list of rule objects
        if not isinstance(rules, list):
            return {"error": f"Unexpected response type: {type(rules)}"}
            
        return rules
    except Exception as e:
        return {"error": f"Exception retrieving policy rules: {str(e)}"}

async def get_zone_details(client, zone_id):
    """Helper function to get network zone details using list_network_zones with filter"""
    try:
        # Use filter parameter to get just this specific zone
        query_params = {
            'filter': f'id eq "{zone_id}"'
        }
        
        # Call list_network_zones with the filter
        zones_resp, resp, err = await client.list_network_zones(query_params)
        
        if err:
            # Return error message, converting err to string to avoid issues
            return {"error": str(err)}
            
        if not zones_resp or len(zones_resp) == 0:
            return {"error": f"Zone with ID {zone_id} not found"}
            
        # Return the first (and should be only) zone that matches the filter
        zone_dict = zones_resp[0].as_dict()
        
        # Convert enum values to strings
        if "type" in zone_dict and hasattr(zone_dict["type"], "value"):
            zone_dict["type"] = zone_dict["type"].value
        if "status" in zone_dict and hasattr(zone_dict["status"], "value"):
            zone_dict["status"] = zone_dict["status"].value
        if "usage" in zone_dict and hasattr(zone_dict["usage"], "value"):
            zone_dict["usage"] = zone_dict["usage"].value
            
        # Convert enums in gateways
        if "gateways" in zone_dict and isinstance(zone_dict["gateways"], list):
            for gateway in zone_dict["gateways"]:
                if "type" in gateway and hasattr(gateway["type"], "value"):
                    gateway["type"] = gateway["type"].value
        
        return zone_dict
        
    except Exception as e:
        return {"error": f"Exception retrieving zone: {str(e)}"}
    
async def get_device_details(client, factor_id):
    """Helper function to get device details using a factor ID"""
    try:
        # Search for devices associated with this factor ID using SCIM filter
        url = f"/api/v1/devices?search=id eq \"{factor_id}\""
        
        # Make the API request
        devices = await make_async_request(client, "GET", url)
        
        # If no devices found or error
        if not devices or not isinstance(devices, list) or not devices:
            return {"error": f"No device details found for factor ID: {factor_id}"}
            
        # Extract relevant information from device
        device_info = devices[0]
        profile = device_info.get("profile", {})
        
        # Get management status from embedded users
        management_status = "UNMANAGED"
        embedded = device_info.get("_embedded", {})
        users = embedded.get("users", [])
        if users and isinstance(users, list) and len(users) > 0:
            management_status = users[0].get("managementStatus", "UNMANAGED")
        
        # Create simplified device record
        return {
            "id": device_info.get("id"),
            "status": device_info.get("status"),
            "displayName": profile.get("displayName", "Unknown Device"),
            "platform": profile.get("platform", "Unknown"),
            "registered": profile.get("registered", False),
            "managed": management_status == "MANAGED",
            "model": profile.get("model", ""),
            "osVersion": profile.get("osVersion", "")
        }
        
    except Exception as e:
        return {"error": f"Exception retrieving device details: {str(e)}"}
        
async def get_user_devices(client, user_factors):
    """Extracts device information from factors that have deviceType in their profile"""
    device_factors = []
    
    # Filter factors that contain deviceType
    for factor in user_factors:
        if "profile" in factor and "deviceType" in factor.get("profile", {}):
            device_factors.append({
                "id": factor.get("id"),
                "type": factor.get("factorType", "unknown"),
                "name": factor.get("profile", {}).get("name", "Unknown Device"),
                "platform": factor.get("profile", {}).get("platform", "Unknown"),
                "deviceType": factor.get("profile", {}).get("deviceType", "Unknown")
            })
    
    # No device factors found
    if not device_factors:
        return []
    
    # Get detailed device information for each factor
    devices = []
    for device_factor in device_factors:
        factor_id = device_factor.get("id")
        
        # Make separate API call to get device details
        device_details = await get_device_details(client, factor_id)
        
        # If error in retrieving device details, include factor info with error
        if "error" in device_details:
            devices.append({
                **device_factor,
                "error": device_details["error"]
            })
        else:
            # Merge factor information with device details
            devices.append({
                **device_factor,
                **device_details
            })
    
    return devices    

async def user_has_access_to_app(client, user_identifier, app_identifier):
    """
    Collects all data relevant to determining whether a user can access an application.
    """
    result = {}
    
    # Step 1: Fetch user details
    try:
        user = None
        if "@" in user_identifier:
            query_parameters = {'filter': f'profile.email eq "{user_identifier}"'}
            users, resp, err = await client.list_users(query_parameters)
            if users and len(users) > 0:
                user = users[0].as_dict()
        else:
            try:
                user_resp = await client.get_user(user_identifier)
                user = user_resp.as_dict()
            except Exception:
                query_parameters = {'q': user_identifier}
                users, resp, err = await client.list_users(query_parameters)
                if users and len(users) > 0:
                    user = users[0].as_dict()
        
        if not user:
            result["user_details"] = {"error": f"User '{user_identifier}' not found"}
            return result
            
        # Extract essential user fields
        result["user_details"] = {
            "id": user.get("id"),
            "status": user.get("status").value if hasattr(user.get("status"), "value") else user.get("status"),
            "email": user.get("profile", {}).get("email"),
            "login": user.get("profile", {}).get("login"),
            "firstName": user.get("profile", {}).get("firstName"),
            "lastName": user.get("profile", {}).get("lastName")
        }
        
        # Check if user is active
        if user.get("status") != "ACTIVE" and hasattr(user.get("status"), "value") and user.get("status").value != "ACTIVE":
            result["user_details"]["access_blocked_reason"] = "User is not in ACTIVE status"
            return result  # Stop execution if user is not active
            
    except Exception as e:
        result["user_details"] = {"error": f"Failed to retrieve user: {str(e)}"}
        return result
    
    # Step 2: Get user's factors
    try:
        user_id = user.get("id")
        factors_resp, resp, err = await client.list_factors(user_id)
        
        if err:
            result["users_registered_factors"] = {"error": f"API error retrieving factors: {err}"}
            return result
            
        factors = [f.as_dict() for f in factors_resp]
        
        result["users_registered_factors"] = []
        for factor in factors:
            factor_provider = factor.get("provider")
            factor_status = factor.get("status")
            
            result["users_registered_factors"].append({
                "id": factor.get("id"),
                "type": factor.get("factorType"),
                "provider": factor_provider.value if hasattr(factor_provider, "value") else factor_provider,
                "status": factor_status.value if hasattr(factor_status, "value") else factor_status,
                "name": factor.get("profile", {}).get("name", "")
            })
            
        # Get device information based on factors
        user_devices = await get_user_devices(client, factors)
        if user_devices:
            result["user_devices"] = user_devices            
            
    except Exception as e:
        result["users_registered_factors"] = {"error": f"Failed to retrieve factors: {str(e)}"}
        return result  # Stop if we can't retrieve factors
    
    # Step 3: Get application details
    try:
        app = None
        
        # First try direct lookup by ID
        try:
            app_resp = await client.get_application(app_identifier)
            app = app_resp.as_dict()
        except Exception:
            # If direct lookup fails, search by name/label
            query_params = {"q": app_identifier}
            apps_resp, resp, err = await client.list_applications(query_params)
            
            if err:
                result["application_details"] = {"error": f"Error searching for application: {err}"}
                return result
                
            apps = [a.as_dict() for a in apps_resp]
            
            if apps:
                # Find the best match by label or name
                for potential_app in apps:
                    app_label = potential_app.get("label", "").lower()
                    app_name = potential_app.get("name", "").lower()
                    search_term = app_identifier.lower()
                    
                    if search_term in app_label or search_term in app_name:
                        app = potential_app
                        break
                
                # If no specific match found, use the first app
                if not app and apps:
                    app = apps[0]
        
        if not app:
            result["application_details"] = {"error": f"Application '{app_identifier}' not found"}
            return result
            
        # Extract access policy ID from _links
        access_policy_href = app.get("_links", {}).get("accessPolicy", {}).get("href", "")
        access_policy_id = access_policy_href.split("/")[-1] if access_policy_href else None
        
        # Extract key application fields
        sign_on_mode = app.get("signOnMode")
        
        result["application_details"] = {
            "id": app.get("id"),
            "name": app.get("name"),
            "label": app.get("label"),
            "status": app.get("status"),
            "signOnMode": sign_on_mode.value if hasattr(sign_on_mode, "value") else sign_on_mode,
            "accessPolicyID": access_policy_id
        }
        
        # Check if application is active
        if app.get("status") != "ACTIVE":
            result["application_details"]["access_blocked_reason"] = "Application is not in ACTIVE status"
            return result  # Stop execution if app is not active
            
        app_id = app.get("id")
        
    except Exception as e:
        result["application_details"] = {"error": f"Failed to retrieve application: {str(e)}"}
        return result
    
    # Step 4: Check if user is assigned to the application
    try:
        is_directly_assigned = False
        assignment_type = "none"
        assigned_via_groups = []
        
        # First check direct assignment
        try:
            app_user_resp = await client.get_application_user(app_id, user_id)
            is_directly_assigned = True
            assignment_type = "individual"
        except Exception:
            # User might not be directly assigned - check groups
            
            # Get user groups
            user_groups_resp, resp, err = await client.list_user_groups(user_id)
            if err:
                result["is_user_assigned_to_app_currently"] = {"error": f"API error retrieving user groups: {err}"}
                return result
                
            user_groups = [g.as_dict() for g in user_groups_resp]
            user_group_ids = [g.get("id") for g in user_groups]
            
            # Get app groups
            app_groups_resp, resp, err = await client.list_application_group_assignments(app_id)
            if err:
                result["is_user_assigned_to_app_currently"] = {"error": f"API error retrieving app group assignments: {err}"}
                return result
                
            app_groups = [g.as_dict() for g in app_groups_resp]
            
            # Find matching groups
            for app_group in app_groups:
                group_id = app_group.get("id")
                if group_id in user_group_ids:
                    # Find the full group details
                    matching_group = next((g for g in user_groups if g.get("id") == group_id), {})
                    assigned_via_groups.append({
                        "id": group_id,
                        "name": matching_group.get("profile", {}).get("name", "Unknown Group")
                    })
            
            if assigned_via_groups:
                assignment_type = "group"
        
        # Build the assignment info
        result["is_user_assigned_to_app_currently"] = {
            "assigned": "yes" if (is_directly_assigned or assigned_via_groups) else "no",
            "assignment_type": assignment_type,
            "assigned_via_groups": assigned_via_groups if assigned_via_groups else None
        }
            
    except Exception as e:
        result["is_user_assigned_to_app_currently"] = {"error": f"Failed to check assignment: {str(e)}"}
        return result  # Stop if assignment check fails
    
    # Step 5: Get groups assigned to the application
    try:
        app_groups_resp, resp, err = await client.list_application_group_assignments(app_id)
        if err:
            result["groups_assigned_to_app"] = {"error": f"API error retrieving app groups: {err}"}
            return result
            
        app_groups = [g.as_dict() for g in app_groups_resp]
        
        result["groups_assigned_to_app"] = []
        for app_group in app_groups:
            # Get full group details
            group_id = app_group.get("id")
            try:
                # Properly handle get_group response
                group_resp, resp, err = await client.get_group(group_id)
                
                if err:
                    result["groups_assigned_to_app"].append({
                        "id": group_id,
                        "name": "Unknown Group",
                        "error": str(err)
                    })
                    continue
                    
                if group_resp:
                    group_details = group_resp.as_dict()
                    result["groups_assigned_to_app"].append({
                        "id": group_id,
                        "name": group_details.get("profile", {}).get("name", "Unnamed Group"),
                        "description": group_details.get("profile", {}).get("description", "")
                    })
                else:
                    result["groups_assigned_to_app"].append({
                        "id": group_id,
                        "name": "Unknown Group",
                        "error": "No group details returned"
                    })
            except Exception as e:
                result["groups_assigned_to_app"].append({
                    "id": group_id,
                    "name": "Unknown Group",
                    "error": str(e)
                })
                
    except Exception as e:
        result["groups_assigned_to_app"] = {"error": f"Failed to retrieve app groups: {str(e)}"}
        return result
    
    # Step 6: Get access policy details
    access_policy_id = result["application_details"].get("accessPolicyID")
    if not access_policy_id:
        result["access_policy_name"] = "No access policy found"
        result["policy_restrictions"] = []
        return result  # Stop as requested if no access policy found
        
    try:
        policy = await get_policy(client, access_policy_id)
        if "error" in policy:
            result["access_policy_name"] = {"error": policy["error"]}
            return result  # Stop if policy fetch fails
            
        result["access_policy_name"] = policy.get("name")
            
    except Exception as e:
        result["access_policy_name"] = {"error": f"Failed to retrieve policy: {str(e)}"}
        return result  # Stop if policy fetch fails
    
    # Step 7: Get policy rules and their constraints
    try:
        rules = await get_policy_rules(client, access_policy_id)
        if isinstance(rules, dict) and "error" in rules:
            result["policy_restrictions"] = {"error": rules["error"]}
            return result  # Stop if rules fetch fails
            
        if not isinstance(rules, list):
            result["policy_restrictions"] = {"error": f"Unexpected response type: {type(rules)}"}
            return result
            
        result["policy_restrictions"] = []
        
        # Loop through all rules in the policy
        for rule in rules:
            rule_info = {
                "name": rule.get("name"),
                "status": rule.get("status"),
                "priority": rule.get("priority"),
                "system": rule.get("system", False),
                "id": rule.get("id"),
                "created": rule.get("created"),
                "lastUpdated": rule.get("lastUpdated"),
                "type": rule.get("type")
            }
            
            # Process conditions (people, network, device, risk, etc.)
            conditions = rule.get("conditions")
            if conditions and isinstance(conditions, dict):
                # Process network conditions
                if "network" in conditions:
                    network = conditions.get("network", {})
                    zone_includes = network.get("include", [])
                    zone_excludes = network.get("exclude", [])
                    
                    # Get zone details
                    zone_details = []
                    all_zone_ids = zone_includes + zone_excludes
                    
                    for zone_id in all_zone_ids:
                        zone = await get_zone_details(client, zone_id)
                        if isinstance(zone, dict) and "error" not in zone:
                            # Convert enum values to strings in gateways
                            if "gateways" in zone and isinstance(zone["gateways"], list):
                                for gateway in zone["gateways"]:
                                    if "type" in gateway and hasattr(gateway["type"], "value"):
                                        gateway["type"] = gateway["type"].value
                                        
                            zone_details.append(zone)
                        else:
                            error_msg = zone.get("error") if isinstance(zone, dict) and "error" in zone else "Unknown error"
                            zone_details.append({
                                "id": zone_id,
                                "name": "Unknown Zone",
                                "error": error_msg
                            })
                    
                    rule_info["zone_constraints"] = {
                        "include": zone_includes,
                        "exclude": zone_excludes,
                        "zone_details": zone_details
                    }
                
                # Process device conditions
                if "device" in conditions:
                    rule_info["device_constraints"] = conditions.get("device", {})
                
                # Process risk score conditions
                if "riskScore" in conditions:
                    rule_info["risk_constraints"] = conditions.get("riskScore", {})
                    
                # Process user type conditions
                if "userType" in conditions:
                    rule_info["user_type_constraints"] = conditions.get("userType", {})
                    
                # Process people conditions (users/groups)
                if "people" in conditions:
                    people = conditions.get("people", {})
                    rule_info["people_constraints"] = people
            
            # Process factor requirements
            actions = rule.get("actions", {})
            if actions and "appSignOn" in actions:
                app_sign_on = actions.get("appSignOn", {})
                access = app_sign_on.get("access")
                rule_info["access"] = access
                
                verification_method = app_sign_on.get("verificationMethod", {})
                factor_mode = verification_method.get("factorMode")
                rule_info["factor_mode"] = factor_mode
                
                # Add reauth timeframe if present
                if "reauthenticateIn" in verification_method:
                    rule_info["reauthenticate_in"] = verification_method.get("reauthenticateIn")
                    
                # Add verification type
                if "type" in verification_method:
                    rule_info["verification_type"] = verification_method.get("type")
                
                constraints = verification_method.get("constraints", [])
                factor_requirements = []
                
                for constraint in constraints:
                    # Handle knowledge factors (password)
                    if "knowledge" in constraint:
                        knowledge = constraint.get("knowledge", {})
                        knowledge_req = {
                            "category": "knowledge",
                            "required": knowledge.get("required", False)
                        }
                        
                        # Add types if present (for password)
                        if "types" in knowledge:
                            knowledge_req["types"] = knowledge.get("types", [])
                            
                        # Add auth methods if present
                        if "authenticationMethods" in knowledge:
                            knowledge_req["methods"] = knowledge.get("authenticationMethods", [])
                            
                        factor_requirements.append(knowledge_req)
                    
                    # Handle possession factors (Okta Verify, SMS, etc)
                    if "possession" in constraint:
                        possession = constraint.get("possession", {})
                        auth_methods = possession.get("authenticationMethods", [])
                        if auth_methods:
                            # Store the entire auth methods array directly
                            factor_requirements.append({
                                "category": "possession",
                                "required": possession.get("required", False),
                                "methods": auth_methods
                            })
                
                rule_info["factor_requirements"] = factor_requirements
            
            result["policy_restrictions"].append(rule_info)
                
    except Exception as e:
        result["policy_restrictions"] = {"error": f"Failed to process policy information: {str(e)}"}
        return result  # Stop if policy processing fails
                
    except Exception as e:
        result["policy_restrictions"] = {"error": f"Failed to process policy information: {str(e)}"}
        return result  # Stop if policy processing fails
    
    # Return the complete analysis data
    return result

# Parse command-line arguments
parser = argparse.ArgumentParser(description='Check if a user has access to an Okta application')
parser.add_argument('-u', '--user', required=True, help='User identifier (email, login, or ID)')
parser.add_argument('-a', '--app', required=True, help='Application identifier (name, label, or ID)')
args = parser.parse_args()

# Initialize Okta client
config = {
    'orgUrl': os.getenv('OKTA_CLIENT_ORGURL'),
    'token': os.getenv('OKTA_API_TOKEN')
}

if not config['orgUrl'] or not config['token']:
    print("ERROR: Missing required environment variables. Please set OKTA_CLIENT_ORGURL and OKTA_API_TOKEN.")
    print("You can create a .env file with these variables or set them in your environment.")
    sys.exit(1)

okta_client = OktaClient(config)
print(f"Okta client initialized with orgUrl: {config['orgUrl']}")

async def main():
    user_identifier = args.user
    app_identifier = args.app
    
    print(f"Collecting access data for user '{user_identifier}' to app '{app_identifier}'...")
    
    # Get the data while preserving original key names
    access_data = await user_has_access_to_app(okta_client, user_identifier, app_identifier)
    
    # Save the data to a JSON file for LLM consumption
    with open("access_analysis_results.json", "w") as f:
        json.dump(access_data, f, indent=2, cls=OktaJSONEncoder)
    
    # Print results in a readable format
    print("\n===== User Access Analysis =====")
    
    # Print user details
    print("\n--- User Details ---")
    pprint(convert_enums(access_data.get("user_details", {})))
    
    # Print factor information
    print("\n--- User Factors ---")
    pprint(convert_enums(access_data.get("users_registered_factors", [])))
    
    # Print application details
    print("\n--- Application Details ---")
    pprint(convert_enums(access_data.get("application_details", {})))
    
    # Print assignment information
    print("\n--- Assignment Status ---")
    pprint(convert_enums(access_data.get("is_user_assigned_to_app_currently", {})))
    
    # Print group assignments
    print("\n--- Groups Assigned to Application ---")
    pprint(convert_enums(access_data.get("groups_assigned_to_app", [])))
    
    # Print policy information
    print("\n--- Access Policy ---")
    pprint(access_data.get("access_policy_name", ""))
    
    # Print policy rules
    print("\n--- Policy Rules ---")
    policy_rules = access_data.get("policy_restrictions", [])
    if isinstance(policy_rules, list) and policy_rules:
        print(f"Found {len(policy_rules)} policy rules")
        
        # Print all rule details
        for i, rule in enumerate(policy_rules):
            print(f"\nRule {i+1} details:")
            pprint(rule)
    else:
        pprint(policy_rules)
    
    print("\nComplete results saved to 'access_analysis_results.json'")

# Run the async main function
if __name__ == "__main__":
    asyncio.run(main())