"""
Clean Access Analysis Special Tool - Using only base_okta_api_client.py
"""

# TOOL METADATA - Accessible to agents at runtime
TOOL_METADATA = {
    "lightweight_reference": {
        "entities": {
            "access_analysis": {
                "operations": ["special_tool_analyze_user_app_access"],
                "description": "Comprehensive access data collection for user application access evaluation - returns raw data for LLM analysis",
                "aliases": ["user access", "app access", "access check", "permissions", "can access"],
                "query_patterns": [
                    "can user {user} access {app}",
                    "user access to application",
                    "check permissions for",
                    "access analysis"
                ]
            }
        },
        "entity_summary": {
            "access_analysis": {
                "endpoint_count": 1
            }
        },
        "endpoints": [
            {
                "id": "special_tool_access-analysis-comprehensive",
                "operationId": "special_tool_analyze_user_app_access",
                "operation": "special_tool_analyze_user_app_access",
                "path": "/special-tools/access-analysis",
                "method": "GET",
                "summary": "SPECIAL TOOL: Comprehensive access analysis for users and applications",
                "description": "REQUIRED PARAMETERS: Extract ALL parameters from the user's natural language query: 'user_identifier' (OPTIONAL - user email/login from query), 'app_identifier' (REQUIRED - application name from query), and 'group_identifier' (OPTIONAL - group name if specified). ALL parameters must be included in PARAMETERS section even if optional. SPECIAL TOOL: Collects ALL access-related data including user details, assignments, application info, policy rules, MFA factors, and network zones. Returns comprehensive raw data for LLM analysis without making access decisions. LLM MUST analyze the returned data and provide clear access determination with specific reasoning based on user status, application assignments, and policy rule evaluation.",
                "entity": "access_analysis",
                "operation_group": "special_tool_analyze_user_app_access",
                "parameters": {
                    "user_identifier": {
                        "type": "string",
                        "required": False,
                        "description": "User email, login, or Okta ID (optional - either user_identifier or group_identifier must be provided)"
                    },
                    "group_identifier": {
                        "type": "string", 
                        "required": False,
                        "description": "Group name or Okta ID (optional - either user_identifier or group_identifier must be provided)"
                    },
                    "app_identifier": {
                        "type": "string",
                        "required": True,
                        "description": "Application name, label, or Okta ID"
                    }
                }
            }
        ]
    }
}

# CODE TEMPLATE - For execution manager subprocess execution
CODE_TEMPLATE = '''import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add current directory to path for imports
sys.path.append(str(Path(__file__).parent))
from base_okta_api_client import OktaAPIClient

# Setup logging - self-contained logging setup like base_okta_api_client.py
import logging
logger = logging.getLogger("special_tool_access_analysis")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

async def main():
    """
    Main function to analyze user access to an application.
    Template parameters will be filled in by execution manager:
    - user_identifier: {user_identifier}
    - group_identifier: {group_identifier}
    - app_identifier: {app_identifier}
    """
    try:
        logger.info("Starting user access analysis special tool...")
        logger.info(f"Parameters - user: '{user_identifier}', app: '{app_identifier}', group: '{group_identifier}'")
        
        client = OktaAPIClient(timeout=180)
        logger.info("OktaAPIClient created successfully")
        
        # Parameters extracted from query by planning agent
        user_identifier = "{user_identifier}"
        app_identifier = "{app_identifier}"
        
        logger.info(f"Template parameters - user: '{user_identifier}', app: '{app_identifier}', group: '{group_identifier}'")
        
        # Import and call our access analysis function
        from user_access_analysis import can_user_access_application
        logger.info("Imported can_user_access_application successfully")
        
        logger.info("Calling can_user_access_application...")
        result = await can_user_access_application(
            client=client,
            user_identifier=user_identifier,
            app_identifier=app_identifier,
            group_identifier="{group_identifier}"
        )
        
        logger.info(f"Analysis completed. Result status: {{result.get('status')}}")
        
        # Output result in expected format
        if result.get("status") == "success":
            output_data = {{"status": "success", "data": result}}
            logger.info(f"Outputting success result with {{len(str(result))}} characters")
            print(json.dumps(output_data))
        else:
            logger.info(f"Outputting error result: {{result.get('status')}}")
            print(json.dumps(result))
            
    except Exception as e:
        error_result = {{"status": "error", "error": f"Exception in main: {{str(e)}}", "tool": "access_analysis"}}
        logger.error(f"Exception caught: {{str(e)}}")
        print(json.dumps(error_result))

if __name__ == "__main__":
    try:
        logger.info("__main__ block executing...")
        asyncio.run(main())
        logger.info("asyncio.run completed successfully")
    except Exception as e:
        logger.error(f"Exception in __main__: {{str(e)}}")
        error_result = {{"status": "error", "error": f"Exception in __main__: {{str(e)}}", "tool": "access_analysis"}}
        print(json.dumps(error_result))
'''

import json
from typing import Dict, Any, Optional


def get_tool_metadata(reference_type: str = "both"):
    """Get tool metadata for agent consumption."""
    if reference_type == "lightweight":
        return TOOL_METADATA["lightweight_reference"]
    else:
        return TOOL_METADATA


def get_tool_function():
    """Get the main tool function for execution."""
    return can_user_access_application


def get_code_template():
    """Get the code template for subprocess execution."""
    return CODE_TEMPLATE


async def can_user_access_application(
    client, 
    user_identifier: str = None, 
    app_identifier: str = None,
    group_identifier: str = None
) -> Dict[str, Any]:
    """
    SPECIAL TOOL: Comprehensive access data collection for user application access.
    
    Uses only base_okta_api_client.py - no SDK dependencies.
    
    IMPORTANT: This tool ONLY collects raw data - it makes NO access decisions.
    The LLM will analyze the returned data and make the final access determination.
    
    Args:
        client: OktaAPIClient instance
        user_identifier: User email, login, or ID (optional)
        app_identifier: Application name, label, or ID (required)
        group_identifier: Group name or ID (optional)
        
    Returns:
        Dict containing raw access data for LLM analysis (no decisions made)
    """
    # Import logging (will be available in subprocess context)
    try:
        from logging import get_logger, get_default_log_dir
        logger = get_logger("access_analysis_function", get_default_log_dir())
    except:
        # Fallback to print if logging not available
        import sys
        class FakeLogger:
            def info(self, msg): print(f"INFO: {msg}", file=sys.stderr)
            def debug(self, msg): print(f"DEBUG: {msg}", file=sys.stderr)
            def error(self, msg): print(f"ERROR: {msg}", file=sys.stderr)
        logger = FakeLogger()
    
    logger.info(f"can_user_access_application called with user='{user_identifier}', app='{app_identifier}', group='{group_identifier}'")
    
    # User-friendly progress messages
    print(f"STARTING ACCESS ANALYSIS", file=sys.stderr)
    print(f"User: {user_identifier}", file=sys.stderr)
    print(f"Application: {app_identifier}", file=sys.stderr)
    if group_identifier:
        print(f"Group: {group_identifier}", file=sys.stderr)
    sys.stderr.flush()
    
    # Basic validation
    if not app_identifier:
        error_result = {
            "status": "error", 
            "error": "app_identifier must be provided",
            "tool": "access_analysis"
        }
        logger.error("Validation failed - no app_identifier")
        return error_result
        
    if not user_identifier and not group_identifier:
        error_result = {
            "status": "error", 
            "error": "Either user_identifier or group_identifier must be provided",
            "tool": "access_analysis"
        }
        logger.error("Validation failed - no user or group identifier")
        return error_result
    
    logger.info("Basic validation passed")
    
    result = {
        "status": "analyzing",
        "tool": "access_analysis",
        "query_parameters": {
            "user_identifier": user_identifier,
            "group_identifier": group_identifier,
            "app_identifier": app_identifier
        }
    }
    
    logger.info("Starting Step 1 - Find application")
    
    # Step 1: Find the application
    try:
        logger.info(f"Calling find_application with '{app_identifier}'")
        app = await find_application(client, app_identifier)
        if not app:
            print(f"APPLICATION NOT FOUND: '{app_identifier}'", file=sys.stderr)
            print(f"This could mean:", file=sys.stderr) 
            print(f"  - The application name must match exactly (case sensitive)", file=sys.stderr)
            print(f"  - Provide the exact name/label as shown in Okta Admin Portal", file=sys.stderr)
            print(f"  - It's a privileged app (like 'Okta Admin Console') that cannot be queried via API", file=sys.stderr)
            sys.stderr.flush()
            error_result = {
                "status": "success",
                "result_type": "application_not_found",
                "entity": "application",
                "id": app_identifier,
                "tool": "access_analysis",
                "message": f"Application '{app_identifier}' not found. The application name must match exactly (case sensitive) as shown in Okta Admin Portal, or it may be a privileged app like 'Okta Admin Console' that cannot be queried via API.",
                "error": f"Application '{app_identifier}' not found in Okta org",
                "debug_info": f"Searched for app with identifier: '{app_identifier}' - no matches found in applications list",
                "search_attempted": ["direct_id_lookup", "query_search", "full_list_search"],
                "can_access": False,
                "reason": "Application not found - name must match exactly (case sensitive) or may be privileged app"
            }
            logger.error(f"Application not found: {app_identifier}")
            return error_result
        
        logger.info(f"Application found: {app.get('id')} - {app.get('name')} - {app.get('label')}")
        
        result["application_details"] = {
            "id": app.get("id"),
            "name": app.get("name"),
            "label": app.get("label"),
            "status": app.get("status"),
            "signOnMode": app.get("signOnMode")
        }
        
        # Extract access policy ID from _links if available
        access_policy_id = None
        access_policy_href = app.get("_links", {}).get("accessPolicy", {}).get("href")
        if access_policy_href and "/" in access_policy_href:
            access_policy_id = access_policy_href.split("/")[-1]
            result["application_details"]["accessPolicyID"] = access_policy_id
            logger.info(f"Found access policy ID: {access_policy_id}")
        
    except Exception as e:
        error_result = {
            "status": "error",
            "error": f"Failed to find application: {str(e)}",
            "tool": "access_analysis"
        }
        logger.error(f"Exception in find_application: {str(e)}")
        return error_result
    
    # Step 2: Process User or Group
    if user_identifier:
        try:
            print(f"DEBUG: Starting Step 2 - Find user '{user_identifier}'", file=sys.stderr)
            user = await find_user(client, user_identifier)
            if not user:
                error_result = {
                    "status": "success",
                    "result_type": "user_not_found",
                    "entity": "user",
                    "id": user_identifier,
                    "tool": "access_analysis",
                    "message": f"User '{user_identifier}' not found. Please verify the email address or username is correct.",
                    "error": f"User '{user_identifier}' not found in Okta org",
                    "can_access": False,
                    "reason": "User not found - verify email address or username is correct"
                }
                print(f"DEBUG: User not found: {user_identifier}", file=sys.stderr)
                return error_result
            
            print(f"DEBUG: User found: {user.get('id')} - {user.get('profile', {}).get('email')}", file=sys.stderr)
            
            result["user_details"] = {
                "id": user.get("id"),
                "email": user.get("profile", {}).get("email"),
                "login": user.get("profile", {}).get("login"),
                "firstName": user.get("profile", {}).get("firstName"),
                "lastName": user.get("profile", {}).get("lastName"),
                "status": user.get("status")
            }
            
            user_id = user.get("id")
            
            print(f"DEBUG: Getting MFA factors for user {user_id}", file=sys.stderr)
            # Get user's MFA factors
            factors_response = await client.make_request(f"/api/v1/users/{user_id}/factors")
            if factors_response.get("status") == "success":
                factors_data = factors_response.get("data", [])
                result["users_registered_factors"] = []
                
                print(f"DEBUG: Found {len(factors_data)} MFA factors", file=sys.stderr)
                
                for factor in factors_data:
                    result["users_registered_factors"].append({
                        "id": factor.get("id"),
                        "type": factor.get("factorType"),
                        "provider": factor.get("provider"),
                        "status": factor.get("status"),
                        "name": factor.get("profile", {}).get("name", "")
                    })
            else:
                print(f"DEBUG: Failed to get MFA factors: {factors_response}", file=sys.stderr)
            
        except Exception as e:
            error_result = {
                "status": "error",
                "error": f"Failed to find user: {str(e)}",
                "tool": "access_analysis"
            }
            print(f"DEBUG: Exception in find_user: {str(e)}", file=sys.stderr)
            return error_result

    elif group_identifier:
        try:
            group = await find_group(client, group_identifier)
            if not group:
                return {
                    "status": "success",
                    "result_type": "group_not_found",
                    "entity": "group", 
                    "id": group_identifier,
                    "tool": "access_analysis",
                    "message": f"Group '{group_identifier}' not found. The group name must exactly match the group name in Okta (case sensitive).",
                    "error": f"Group '{group_identifier}' not found in Okta org",
                    "can_access": False,
                    "reason": "Group not found - name must exactly match group name in Okta (case sensitive)"
                }
            
            result["group_details"] = {
                "id": group.get("id"),
                "name": group.get("profile", {}).get("name"),
                "description": group.get("profile", {}).get("description"),
                "type": group.get("type")
            }
            
        except Exception as e:
            return {
                "status": "error",
                "error": f"Failed to find group: {str(e)}",
                "tool": "access_analysis"
            }
    
    # Step 3: Check assignments and policies
    try:
        app_id = app.get("id")
        
        if user_identifier:
            user_id = result["user_details"]["id"]
            # Check user assignment
            assignment_result = await check_user_app_assignment(client, app_id, user_id)
            result["assignment"] = assignment_result
            
        elif group_identifier:
            group_id = result["group_details"]["id"]
            # Check group assignment
            assignment_result = await check_group_app_assignment(client, app_id, group_id)
            result["assignment"] = assignment_result
        
        # Get application access policy if available
        access_policy_id = result["application_details"].get("accessPolicyID")
        if access_policy_id:
            try:
                # Get policy details
                policy_response = await client.make_request(f"/api/v1/policies/{access_policy_id}")
                if policy_response.get("status") == "success":
                    policy_data = policy_response.get("data")
                    
                    # Handle case where policy_data might be a list
                    if isinstance(policy_data, list):
                        policy_data = policy_data[0] if policy_data else {}
                    elif not isinstance(policy_data, dict):
                        policy_data = {}
                    
                    result["access_policy"] = {
                        "id": policy_data.get("id"),
                        "name": policy_data.get("name"),
                        "status": policy_data.get("status"),
                        "type": policy_data.get("type")
                    }
                    
                    # Get policy rules
                    rules_response = await client.make_request(f"/api/v1/policies/{access_policy_id}/rules")
                    if rules_response.get("status") == "success":
                        rules_data = rules_response.get("data", [])
                        result["policy_rules"] = []
                        
                        # Track zone IDs used in rules
                        zone_ids = set()
                        
                        for rule in rules_data:
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
                            
                            for zone_id in zone_ids:
                                try:
                                    zone_response = await client.make_request(f"/api/v1/zones/{zone_id}")
                                    if zone_response.get("status") == "success":
                                        zone_data = zone_response.get("data")
                                        
                                        result["network_zones"][zone_id] = {
                                            "id": zone_data.get("id"),
                                            "name": zone_data.get("name"),
                                            "type": zone_data.get("type"),
                                            "status": zone_data.get("status"),
                                            "usage": zone_data.get("usage"),
                                            "gateways": zone_data.get("gateways", []),
                                            "proxies": zone_data.get("proxies", [])
                                        }
                                except Exception as e:
                                    result["network_zones"][zone_id] = {"error": str(e)}
            
            except Exception as e:
                result["policy_error"] = str(e)
        
        # DO NOT MAKE DECISIONS - Just return raw data for LLM analysis
        result["status"] = "success"
        
        print(f"DEBUG: Analysis completed successfully. Result keys: {list(result.keys())}", file=sys.stderr)
        print(f"DEBUG: Total result size: {len(str(result))} characters", file=sys.stderr)
        
        # Add comprehensive analysis notes for LLM
        result["notes_must_read"] = {
            "access_determination_logic": "To determine if a user can access an application, analyze ALL the following conditions in order: 1) User must be ACTIVE (status='ACTIVE'), 2) User must be assigned to application either directly OR via group membership, 3) All policy rules must be satisfied including network zones and MFA requirements",
            
            "json_key_mapping": {
                "user_details.status": "User account status - must be 'ACTIVE' for access",
                "application_details.status": "Application status - must be 'ACTIVE' for access", 
                "assignment.is_assigned": "True if user has access via direct or group assignment",
                "assignment.assignment_type": "How user gets access: 'direct' or 'group'",
                "assignment.via_groups": "List of groups that grant the user access to this app",
                "users_registered_factors": "MFA factors user has enrolled (SMS, TOTP, PUSH, etc.)",
                "policy_rules": "Access policy rules that define conditions for app access",
                "policy_rules[].access": "'ALLOW' or 'DENY' - determines if rule grants or blocks access",
                "policy_rules[].priority": "Lower number = higher priority rule",
                "policy_rules[].verification_method.factorMode": "'1FA' (password only) or '2FA' (password + MFA factor required)",
                "policy_rules[].network_conditions": "Network zone restrictions for this rule",
                "network_zones": "Details about network zones referenced in policy rules",
                "network_zones[].name": "Human readable name of the network zone (e.g. 'Corporate Network')",
                "network_zones[].type": "Zone type: 'IP' for IP ranges, 'DYNAMIC' for dynamic zones",
                "network_zones[].gateways": "IP ranges or addresses included in this zone"
            },
            
            "access_decision_examples": {
                "full_access_example": "User [Name] can access application [App Name] because: 1) User is ACTIVE, 2) User is assigned via group '[Group Name]', 3) Policy allows access with 1FA from any location",
                "conditional_access_example": "User [Name] can access application [App Name] from internal network '[Zone Name]' with password only, but external access requires 2FA with PUSH factor which the user has enrolled",
                "no_access_example": "User [Name] cannot access application [App Name] because: 1) User is ACTIVE ✓, 2) User is NOT assigned to application (no direct assignment or group membership found) ✗"
            },
            
            "policy_evaluation_rules": {
                "rule_priority": "Rules are evaluated by priority (lower number = higher priority). First matching ALLOW rule grants access unless overridden by higher priority DENY rule",
                "network_zones": "If rule has network conditions with 'ZONE' connection, user must be in specified zones. If user is outside these zones, rule may not apply or may require additional factors",
                "mfa_requirements": "If rule requires '2FA', user must have enrolled MFA factors that satisfy the policy constraints. Check users_registered_factors for available factors",
                "default_behavior": "If no explicit DENY rules match and at least one ALLOW rule matches, access is typically granted"
            },
            
            "response_format_instructions": "Provide clear explanation like: 'User [Name] can/cannot access [App] because: [specific reasons based on status, assignment, and policy evaluation]. For conditional access, specify network zones and MFA requirements clearly.'"
        }
        
        print(f"DEBUG: Returning successful result", file=sys.stderr)
        return result
        
    except Exception as e:
        error_result = {
            "status": "error",
            "error": f"Failed to analyze access: {str(e)}",
            "tool": "access_analysis"
        }
        logger.error(f"Exception in main analysis: {str(e)}")
        return error_result


async def find_application(client, app_identifier: str) -> Optional[Dict[str, Any]]:
    """Find application by ID, name, or label using base_okta_api_client."""
    import sys
    
    print(f"SEARCHING FOR APPLICATION: '{app_identifier}'", file=sys.stderr)
    sys.stderr.flush()
    
    # Try direct lookup by ID first if it looks like an Okta ID
    if app_identifier.startswith("0oa"):
        print(f"Trying direct ID lookup for {app_identifier}...", file=sys.stderr)
        response = await client.make_request(f"/api/v1/apps/{app_identifier}")
        if response.get("status") == "success":
            found_label = response.get('data', {}).get('label', 'Unknown')
            print(f"Found app by ID: '{found_label}'", file=sys.stderr)
            return response.get("data")
        else:
            print(f"Direct ID lookup failed: {response.get('status')}", file=sys.stderr)
    
    # Search by query parameter
    print(f"Trying query-based search for '{app_identifier}'...", file=sys.stderr)
    response = await client.make_request("/api/v1/apps", params={"q": app_identifier})
    if response.get("status") == "success":
        apps = response.get("data", [])
        print(f"Query search returned {len(apps)} applications", file=sys.stderr)
        if apps:
            # Show what we found
            print(f"Found apps from query search:", file=sys.stderr)
            for i, app in enumerate(apps[:3]):  # Show first 3
                print(f"   {i+1}. '{app.get('label', 'No Label')}' (name: {app.get('name', 'No Name')})", file=sys.stderr)
            
            # Look for exact match first
            for app in apps:
                label = app.get("label", "").lower()
                name = app.get("name", "").lower()
                search_term = app_identifier.lower()
                if (label == search_term or name == search_term):
                    print(f"Found EXACT match: '{app.get('label')}'", file=sys.stderr)
                    return app
            
            # Return first match if no exact match
            print(f"No exact match found. Using first result: '{apps[0].get('label')}'", file=sys.stderr)
            return apps[0]
        else:
            print("Query search returned no results", file=sys.stderr)
    else:
        print(f"Query search failed: {response.get('status')}", file=sys.stderr)
    
    # Final attempt: list all and search
    print("Trying full application list search (this may take a moment)...", file=sys.stderr)
    response = await client.make_request("/api/v1/apps")
    if response.get("status") == "success":
        apps = response.get("data", [])
        search_term = app_identifier.lower()
        print(f"Retrieved {len(apps)} total applications from Okta", file=sys.stderr)
        
        # Show sample of available apps for debugging
        print(f"Sample of available applications:", file=sys.stderr)
        for i, app in enumerate(apps[:10]):  # Show first 10
            print(f"   {i+1}. '{app.get('label', 'No Label')}' (name: {app.get('name', 'No Name')})", file=sys.stderr)
        if len(apps) > 10:
            print(f"   ... and {len(apps) - 10} more applications", file=sys.stderr)
        
        # Search for partial matches
        matches_found = []
        for app in apps:
            label = app.get("label", "").lower()
            name = app.get("name", "").lower()
            
            if (search_term in label or search_term in name or
                label in search_term or name in search_term):
                matches_found.append(app)
        
        if matches_found:
            print(f"Found {len(matches_found)} partial matches:", file=sys.stderr)
            for i, app in enumerate(matches_found[:5]):  # Show first 5 matches
                print(f"   {i+1}. '{app.get('label')}' (name: {app.get('name')})", file=sys.stderr)
            print(f"Using first match: '{matches_found[0].get('label')}'", file=sys.stderr)
            return matches_found[0]
        else:
            print(f"No matches found for '{app_identifier}' in {len(apps)} applications", file=sys.stderr)
    else:
        print(f"Full list search failed: {response.get('status')}", file=sys.stderr)
    
    print(f"APPLICATION NOT FOUND: '{app_identifier}' does not exist in this Okta organization", file=sys.stderr)
    sys.stderr.flush()
    return None


async def find_user(client, user_identifier: str) -> Optional[Dict[str, Any]]:
    """Find user by ID, login, or email using base_okta_api_client with comprehensive search."""
    
    # Try direct lookup by ID first if it looks like an Okta ID
    if user_identifier.startswith("00u"):
        response = await client.make_request(f"/api/v1/users/{user_identifier}")
        if response.get("status") == "success":
            return response.get("data")
    
    # Try filter-based search (more precise than query search)
    if "@" in user_identifier:
        # Search by email filter
        response = await client.make_request("/api/v1/users", params={"filter": f'profile.email eq "{user_identifier}"'})
        if response.get("status") == "success":
            users = response.get("data", [])
            if users:
                return users[0]
    else:
        # Search by login filter
        response = await client.make_request("/api/v1/users", params={"filter": f'profile.login eq "{user_identifier}"'})
        if response.get("status") == "success":
            users = response.get("data", [])
            if users:
                return users[0]
    
    # Fallback to query parameter search
    response = await client.make_request("/api/v1/users", params={"q": user_identifier})
    if response.get("status") == "success":
        users = response.get("data", [])
        if users:
            # Look for exact match on email or login
            for user in users:
                profile = user.get("profile", {})
                if (profile.get("email", "").lower() == user_identifier.lower() or
                    profile.get("login", "").lower() == user_identifier.lower()):
                    return user
            
            # Return first match if no exact match
            return users[0]
    
    return None


async def find_group(client, group_identifier: str) -> Optional[Dict[str, Any]]:
    """Find group by ID or name using base_okta_api_client."""
    
    # Try direct lookup by ID first if it looks like an Okta ID
    if group_identifier.startswith("00g"):
        response = await client.make_request(f"/api/v1/groups/{group_identifier}")
        if response.get("status") == "success":
            return response.get("data")
    
    # Search by query parameter
    response = await client.make_request("/api/v1/groups", params={"q": group_identifier})
    if response.get("status") == "success":
        groups = response.get("data", [])
        if groups:
            # Look for exact match on group name
            for group in groups:
                profile = group.get("profile", {})
                if profile.get("name", "").lower() == group_identifier.lower():
                    return group
            
            # Return first match if no exact match
            return groups[0]
    
    return None


async def check_user_app_assignment(client, app_id: str, user_id: str) -> Dict[str, Any]:
    """Check if user is assigned to application and collect comprehensive assignment data."""
    
    assignment_result = {
        "is_assigned": False,
        "assignment_type": "none",
        "direct_assignment": False
    }
    
    # Check direct assignment
    response = await client.make_request(f"/api/v1/apps/{app_id}/users/{user_id}")
    
    if response.get("status") == "success":
        assignment_result.update({
            "is_assigned": True,
            "assignment_type": "direct",
            "direct_assignment": True
        })
        return assignment_result
    
    # If direct assignment fails, check through groups
    # Get user's groups
    groups_response = await client.make_request(f"/api/v1/users/{user_id}/groups")
    if groups_response.get("status") == "success":
        user_groups_data = groups_response.get("data", [])
        user_groups = []
        user_group_ids = []
        
        for group in user_groups_data:
            user_groups.append({
                "id": group.get("id"),
                "name": group.get("profile", {}).get("name")
            })
            user_group_ids.append(group.get("id"))
        
        assignment_result["user_groups"] = user_groups
        
        # Check if any of these groups are assigned to the app
        app_groups_response = await client.make_request(f"/api/v1/apps/{app_id}/groups")
        if app_groups_response.get("status") == "success":
            app_groups_data = app_groups_response.get("data", [])
            app_group_ids = {group.get("id") for group in app_groups_data}
            
            group_assignments = []
            for user_group in user_groups:
                if user_group["id"] in app_group_ids:
                    group_assignments.append(user_group)
            
            if group_assignments:
                assignment_result.update({
                    "is_assigned": True,
                    "assignment_type": "group",
                    "direct_assignment": False,
                    "via_groups": group_assignments,
                    "assigned_via_group": group_assignments[0]["name"]  # For backward compatibility
                })
            else:
                assignment_result["via_groups"] = []
    
    return assignment_result


async def check_group_app_assignment(client, app_id: str, group_id: str) -> Dict[str, Any]:
    """Check if group is assigned to application."""
    
    assignment_result = {
        "is_assigned": False,
        "assignment_type": "none",
        "group_assignment": False
    }
    
    # Check if group is assigned to application
    app_groups_response = await client.make_request(f"/api/v1/apps/{app_id}/groups")
    if app_groups_response.get("status") == "success":
        app_groups_data = app_groups_response.get("data", [])
        
        for app_group in app_groups_data:
            if app_group.get("id") == group_id:
                assignment_result.update({
                    "is_assigned": True,
                    "assignment_type": "group",
                    "group_assignment": True
                })
                break
    
    return assignment_result


# COMMENTED OUT - WE DO NOT MAKE DECISIONS, JUST COLLECT DATA
# def generate_access_decision(result: Dict[str, Any]) -> Dict[str, Any]:
#     """Generate comprehensive access decision based on analysis results."""
#     decision = {
#         "final_decision": "denied",
#         "decision_factors": [],
#         "confidence": "high"
#     }
#     
#     # Check application status
#     app_details = result.get("application_details", {})
#     if app_details.get("status") != "ACTIVE":
#         decision["decision_factors"].append(f"Application status is {app_details.get('status')}")
#         return decision
#     
#     # Check user status
#     user_details = result.get("user_details", {})
#     user_status = user_details.get("status")
#     if user_status not in ["ACTIVE", "PASSWORD_EXPIRED"]:
#         decision["decision_factors"].append(f"User status is {user_status}")
#         return decision
#     
#     # Check assignment
#     assignment = result.get("assignment", {})
#     if assignment.get("is_assigned"):
#         decision["final_decision"] = "allowed"
#         assignment_type = assignment.get("assignment_type")
#         decision["decision_factors"].append(f"User has {assignment_type} assignment to application")
#         
#         if assignment_type == "group":
#             group_name = assignment.get("assigned_via_group", "unknown group")
#             decision["decision_factors"].append(f"Access granted via group: {group_name}")
#     else:
#         decision["decision_factors"].append("No application assignment found (direct or group-based)")
#     
#     return decision
