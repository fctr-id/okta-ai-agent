"""
Clean Access Analysis Special Tool - Using only base_okta_api_client.py
"""

import sys
import os
from pathlib import Path

# Add project root to path to allow imports from src
# Current file: src/core/tools/special_tools/user_access_analysis.py
# Root: okta-ai-agent/
try:
    project_root = Path(__file__).parent.parent.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.append(str(project_root))
except Exception:
    pass

try:
    from src.core.models.model_picker import ModelConfig, ModelType
    from pydantic_ai import Agent
except ImportError:
    # Fallback if imports fail (e.g. during initial setup)
    ModelConfig = None
    ModelType = None
    Agent = None

# TOOL METADATA - Accessible to agents at runtime
TOOL_METADATA = {
    "lightweight_reference": {
        "entities": {
            "access_analysis": {
                "operations": ["special_tool_analyze_user_app_access"],
                "description": "Comprehensive access data collection for user application access evaluation - returns raw data AND an AI-generated access determination summary.",
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
                "description": "REQUIRED PARAMETERS: Extract ALL parameters from the user's natural language query: 'user_identifier' (OPTIONAL - user email/login from query), 'app_identifier' (REQUIRED - application name from query), and 'group_identifier' (OPTIONAL - group name if specified). ALL parameters must be included in PARAMETERS section even if optional. SPECIAL TOOL: Collects ALL access-related data including user details, assignments, application info, policy rules, MFA factors, and network zones. Returns comprehensive raw data AND an embedded AI access determination in the 'llm_summary' field. The tool performs its own analysis using a reasoning model. IMPORTANT: When generating code or reports, DO NOT manually format the raw data. ALWAYS output the 'llm_summary' string directly as it contains the expert analysis.",
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
            def warning(self, msg): print(f"WARNING: {msg}", file=sys.stderr)
        logger = FakeLogger()
    
    logger.info(f"can_user_access_application called with user='{user_identifier}', app='{app_identifier}', group='{group_identifier}'")
    
    # Basic progress indicator
    logger.info(f"Starting access analysis for user='{user_identifier}', app='{app_identifier}', group='{group_identifier}'")
    
    # Basic validation
    if not app_identifier:
        error_result = {
            "status": "error", 
            "error": "app_identifier must be provided",
            "tool": "access_analysis",
            "llm_summary": "## Missing Required Parameter\n\n❌ **Application identifier is required** for access analysis.\n\nPlease specify which application you want to check access for."
        }
        logger.error("Validation failed - no app_identifier")
        return error_result
        
    if not user_identifier and not group_identifier:
        error_result = {
            "status": "error", 
            "error": "Either user_identifier or group_identifier must be provided",
            "tool": "access_analysis",
            "llm_summary": "## Missing Required Parameter\n\n❌ **Either a user or group identifier is required** for access analysis.\n\nPlease specify which user or group you want to check access for."
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
            error_message = f"## Application Not Found\n\n**Application:** `{app_identifier}`\n\n❌ The application '{app_identifier}' could not be found in your Okta organization.\n\n### Possible Reasons:\n- The application name must match **exactly** (case-sensitive) as shown in the Okta Admin Portal\n- It may be a privileged system application (like 'Okta Admin Console') that cannot be queried via API\n- The application may have been deleted or renamed\n\n### What to try:\n1. Verify the exact application name in your Okta Admin Portal\n2. Check for typos or case differences\n3. Try using the application label instead of the technical name"
            
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
                "reason": "Application not found - name must match exactly (case sensitive) or may be privileged app",
                "llm_summary": error_message
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
            logger.debug(f"Starting Step 2 - Find user '{user_identifier}'")
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
                    "reason": "User not found - verify email address or username is correct",
                    "llm_summary": f"## User Not Found\n\n**User:** `{user_identifier}`\n\n❌ The user '{user_identifier}' could not be found in your Okta organization.\n\n### What to try:\n1. Verify the email address or username is spelled correctly\n2. Check if the user account exists in your Okta Admin Portal\n3. The user may have been deprovisioned or deleted"
                }
                logger.debug(f"User not found: {user_identifier}")
                return error_result
            
            logger.debug(f"User found: {user.get('id')} - {user.get('profile', {}).get('email')}")
            
            result["user_details"] = {
                "id": user.get("id"),
                "email": user.get("profile", {}).get("email"),
                "login": user.get("profile", {}).get("login"),
                "firstName": user.get("profile", {}).get("firstName"),
                "lastName": user.get("profile", {}).get("lastName"),
                "status": user.get("status")
            }
            
            user_id = user.get("id")
            
            logger.debug(f"Getting MFA factors for user {user_id}")
            # Get user's MFA factors
            factors_response = await client.make_request(f"/api/v1/users/{user_id}/factors")
            if factors_response.get("status") == "success":
                factors_data = factors_response.get("data", [])
                result["users_registered_factors"] = []
                
                logger.debug(f"Found {len(factors_data)} MFA factors")
                
                for factor in factors_data:
                    result["users_registered_factors"].append({
                        "id": factor.get("id"),
                        "type": factor.get("factorType"),
                        "provider": factor.get("provider"),
                        "status": factor.get("status"),
                        "name": factor.get("profile", {}).get("name", "")
                    })
            else:
                logger.debug(f"Failed to get MFA factors: {factors_response}")
            
        except Exception as e:
            error_result = {
                "status": "error",
                "error": f"Failed to find user: {str(e)}",
                "tool": "access_analysis"
            }
            logger.error(f"Exception in find_user: {str(e)}")
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
                                # Network zones - fetch and inject zone details directly
                                if "network" in conditions:
                                    network_conditions = conditions.get("network", {})
                                    enhanced_network_conditions = network_conditions.copy()
                                    
                                    # Fetch and inject zone details for both include and exclude
                                    if network_conditions.get("connection") == "ZONE":
                                        # Process include zones - replace original include array with detailed objects
                                        if "include" in network_conditions:
                                            enhanced_include = []
                                            for zone_id in network_conditions.get("include", []):
                                                zone_details = await fetch_zone_details(client, zone_id)
                                                enhanced_include.append({
                                                    "zone_id": zone_id,
                                                    "zone_details": zone_details
                                                })
                                            enhanced_network_conditions["include"] = enhanced_include
                                        
                                        # Process exclude zones - replace original exclude array with detailed objects
                                        if "exclude" in network_conditions:
                                            enhanced_exclude = []
                                            for zone_id in network_conditions.get("exclude", []):
                                                zone_details = await fetch_zone_details(client, zone_id)
                                                enhanced_exclude.append({
                                                    "zone_id": zone_id,
                                                    "zone_details": zone_details
                                                })
                                            enhanced_network_conditions["exclude"] = enhanced_exclude
                                    
                                    rule_info["network_conditions"] = enhanced_network_conditions
                                
                                # User conditions - fetch and inject user details
                                if "people" in conditions:
                                    people_conditions = conditions.get("people", {})
                                    enhanced_people_conditions = people_conditions.copy()
                                    
                                    # Process users in include list - replace original include array with detailed objects
                                    if "users" in people_conditions and "include" in people_conditions["users"]:
                                        enhanced_include_users = []
                                        for user_id in people_conditions["users"].get("include", []):
                                            user_details = await fetch_user_details(client, user_id)
                                            enhanced_include_users.append({
                                                "user_id": user_id,
                                                "user_details": user_details
                                            })
                                        if "users" not in enhanced_people_conditions:
                                            enhanced_people_conditions["users"] = {}
                                        enhanced_people_conditions["users"]["include"] = enhanced_include_users
                                    
                                    # Process users in exclude list - replace original exclude array with detailed objects
                                    if "users" in people_conditions and "exclude" in people_conditions["users"]:
                                        enhanced_exclude_users = []
                                        for user_id in people_conditions["users"].get("exclude", []):
                                            user_details = await fetch_user_details(client, user_id)
                                            enhanced_exclude_users.append({
                                                "user_id": user_id,
                                                "user_details": user_details
                                            })
                                        if "users" not in enhanced_people_conditions:
                                            enhanced_people_conditions["users"] = {}
                                        enhanced_people_conditions["users"]["exclude"] = enhanced_exclude_users
                                    
                                    # Process groups in include list - replace original include array with detailed objects
                                    if "groups" in people_conditions and "include" in people_conditions["groups"]:
                                        enhanced_include_groups = []
                                        for group_id in people_conditions["groups"].get("include", []):
                                            group_details = await fetch_group_details(client, group_id)
                                            enhanced_include_groups.append({
                                                "group_id": group_id,
                                                "group_details": group_details
                                            })
                                        if "groups" not in enhanced_people_conditions:
                                            enhanced_people_conditions["groups"] = {}
                                        enhanced_people_conditions["groups"]["include"] = enhanced_include_groups
                                    
                                    # Process groups in exclude list - replace original exclude array with detailed objects
                                    if "groups" in people_conditions and "exclude" in people_conditions["groups"]:
                                        enhanced_exclude_groups = []
                                        for group_id in people_conditions["groups"].get("exclude", []):
                                            group_details = await fetch_group_details(client, group_id)
                                            enhanced_exclude_groups.append({
                                                "group_id": group_id,
                                                "group_details": group_details
                                            })
                                        if "groups" not in enhanced_people_conditions:
                                            enhanced_people_conditions["groups"] = {}
                                        enhanced_people_conditions["groups"]["exclude"] = enhanced_exclude_groups
                                    
                                    rule_info["people_conditions"] = enhanced_people_conditions
                                
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
            
            except Exception as e:
                result["policy_error"] = str(e)
        
        # DO NOT MAKE DECISIONS - Just return raw data for LLM analysis
        result["status"] = "success"
        
        logger.debug(f"Analysis completed successfully. Result keys: {list(result.keys())}")
        logger.debug(f"Total result size: {len(str(result))} characters")
        
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
                "network_zones[].gateways": "FINAL decision IP ranges (CIDR/single IPs) that determine zone membership - user's effective IP must match these for zone inclusion",
                "network_zones[].proxies": "TRUSTED proxy IP ranges that Okta skips over - when request comes from these IPs, Okta looks at X-Forwarded-For to find real client IP for evaluation",
                "policy_rules[].people_conditions.users.include": "Users explicitly granted access in this rule - contains user_id and full user_details with name, email, status",
                "policy_rules[].people_conditions.users.exclude": "Users explicitly denied access in this rule - contains user_id and full user_details with name, email, status", 
                "policy_rules[].people_conditions.groups.include": "Groups explicitly granted access in this rule - contains group_id and full group_details with name, description, type",
                "policy_rules[].people_conditions.groups.exclude": "Groups explicitly denied access in this rule - contains group_id and full group_details with name, description, type"
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
            
            "network_zone_ip_evaluation": {
                "gateways_definition": "GATEWAYS are the 'final' IP addresses that act as decision endpoints for network zone evaluation. These are the trusted IP ranges (CIDR blocks) or specific IPs that Okta considers as the authoritative source location for access decisions",
                "proxies_definition": "PROXIES are trusted intermediary IP addresses that Okta's threat scorer will SKIP OVER when determining the user's actual location. When a request comes through these proxy IPs, Okta looks at the next IP in the X-Forwarded-For chain to find the real client IP",
                "gateway_evaluation_logic": "When evaluating network zones, Okta compares the user's effective IP address against the GATEWAY ranges. If the IP matches a gateway range in an 'include' zone, the user is considered inside that network zone. If it matches an 'exclude' zone gateway, they are blocked",
                "proxy_chain_logic": "If a request comes from a PROXY IP address, Okta does not use that IP for zone evaluation. Instead, it examines the X-Forwarded-For header to find the next IP in the chain (the actual client IP behind the proxy) and evaluates that IP against the gateway ranges",
                "practical_example": "Example: User connects from IP 192.168.1.100 → Corporate Proxy 203.0.113.50 → Internet. If 203.0.113.50 is listed in proxies[], Okta ignores it and evaluates 192.168.1.100 against the gateway ranges to determine zone membership",
                "threat_scoring_impact": "This proxy-skipping behavior is crucial for threat scoring accuracy - it ensures that legitimate users behind corporate proxies/NAT are evaluated based on their actual internal IP, not the shared proxy IP that many users would have"
            },
            
            "response_format_instructions": "Provide clear explanation like: 'User [Name] can/cannot access [App] because: [specific reasons based on status, assignment, and policy evaluation]. For conditional access, specify network zones and MFA requirements clearly.'"
        }
        
        logger.debug("Returning successful result")
        
        # --- INTELLIGENT TOOL: Generate LLM Access Determination ---
        try:
            if ModelConfig and Agent:
                logger.info("Step 4 - Generating LLM Access Determination")
                # Use print to stderr for user visibility
                import sys
                print("Generating AI Access Determination...", file=sys.stderr)
                
                # Initialize the reasoning model
                model = ModelConfig.get_model(ModelType.REASONING)
                agent = Agent(model)
                
                # Prepare the prompt with all the data and guidelines
                # Create a simplified version of result for the prompt to save tokens if needed, 
                # but for now pass the whole thing as it contains critical details
                
                prompt = f"""
                You are an expert Okta security architect. Analyze the following access data and determine if the user/group can access the application.
                
                FULL ACCESS DATA:
                {json.dumps(result, indent=2)}
                
                Provide a comprehensive access determination following the 'response_format_instructions' in the 'notes_must_read' section of the data.
                
                IMPORTANT FORMATTING INSTRUCTION:
                Provide the output as a clear, narrative Markdown summary. 
                Do NOT use tables. 
                Use headers, bullet points, and bold text for readability.
                """
                
                # Run the agent
                llm_response = await agent.run(prompt)
                result["llm_summary"] = llm_response.output
                
                logger.info("LLM Access Determination generated successfully")
            else:
                logger.warning("ModelConfig or Agent not available - skipping LLM assessment")
                result["llm_summary"] = "LLM assessment skipped - dependencies not available"
            
        except Exception as e:
            logger.error(f"Failed to generate LLM assessment: {str(e)}")
            result["llm_summary"] = f"Error generating access determination: {str(e)}"
            # Don't fail the whole tool, just return the data without summary

        return result
        
    except Exception as e:
        error_result = {
            "status": "error",
            "error": f"Failed to analyze access: {str(e)}",
            "tool": "access_analysis"
        }
        logger.error(f"Exception in main analysis: {str(e)}")
        return error_result


async def fetch_zone_details(client, zone_id: str) -> Dict[str, Any]:
    """Fetch detailed information for a network zone."""
    try:
        zone_response = await client.make_request(f"/api/v1/zones/{zone_id}")
        if zone_response.get("status") == "success":
            zone_data = zone_response.get("data")
            
            # Handle different response formats
            if isinstance(zone_data, list):
                # Special case: API returned a list of gateway/proxy definitions
                if zone_data and isinstance(zone_data[0], dict) and "type" in zone_data[0] and "value" in zone_data[0]:
                    return {
                        "id": zone_id,
                        "name": f"Network Zone {zone_id}",
                        "type": "IP_RANGE",
                        "status": "ACTIVE",
                        "usage": "POLICY", 
                        "gateways": zone_data,
                        "ip_ranges": [item["value"] for item in zone_data if "value" in item]
                    }
                else:
                    # Normal list format - use first item
                    zone_data = zone_data[0] if zone_data else {}
            
            if isinstance(zone_data, dict):
                return {
                    "id": zone_data.get("id", zone_id),
                    "name": zone_data.get("name", f"Zone {zone_id}"),
                    "type": zone_data.get("type", "UNKNOWN"),
                    "status": zone_data.get("status", "UNKNOWN"),
                    "usage": zone_data.get("usage", "UNKNOWN"),
                    "gateways": zone_data.get("gateways", []),
                    "proxies": zone_data.get("proxies", [])
                }
        
        return {"error": f"Failed to fetch zone details: {zone_response.get('status')}"}
        
    except Exception as e:
        return {"error": str(e)}


async def fetch_user_details(client, user_id: str) -> Dict[str, Any]:
    """Fetch detailed information for a user."""
    try:
        user_response = await client.make_request(f"/api/v1/users/{user_id}")
        if user_response.get("status") == "success":
            user_data = user_response.get("data")
            
            # Handle different response formats (similar to network zones)
            if isinstance(user_data, list):
                user_data = user_data[0] if user_data else {}
            
            if isinstance(user_data, dict):
                profile = user_data.get("profile", {})
                return {
                    "id": user_data.get("id", user_id),
                    "email": profile.get("email", "No email"),
                    "login": profile.get("login", "No login"),
                    "firstName": profile.get("firstName", ""),
                    "lastName": profile.get("lastName", ""),
                    "displayName": f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip() or profile.get("email", user_id),
                    "status": user_data.get("status", "UNKNOWN")
                }
            else:
                return {"error": f"Unexpected user data format: {type(user_data)}"}
        else:
            return {"error": f"API call failed with status: {user_response.get('status')}, message: {user_response.get('error', 'No error message')}"}
        
    except Exception as e:
        return {"error": str(e)}


async def fetch_group_details(client, group_id: str) -> Dict[str, Any]:
    """Fetch detailed information for a group using search API."""
    try:
        # Use groups list API with search filter instead of direct ID lookup
        search_filter = f'id eq "{group_id}"'
        group_response = await client.make_request("/api/v1/groups", params={"search": search_filter})
        
        if group_response.get("status") == "success":
            group_data = group_response.get("data")
            
            # Handle search results - should be a list of groups
            if isinstance(group_data, list):
                if group_data and isinstance(group_data[0], dict):
                    # Found the group - use the first (and should be only) result
                    group_obj = group_data[0]
                    profile = group_obj.get("profile", {})
                    return {
                        "id": group_obj.get("id", group_id),
                        "name": profile.get("name", f"Group {group_id[-8:]}"),
                        "description": profile.get("description", "No description"),
                        "type": group_obj.get("type", "OKTA_GROUP"),
                        "displayName": profile.get("name", f"Group {group_id[-8:]}"),
                        "created": group_obj.get("created"),
                        "lastUpdated": group_obj.get("lastUpdated"),
                        "lastMembershipUpdated": group_obj.get("lastMembershipUpdated"),
                        "objectClass": group_obj.get("objectClass", [])
                    }
                else:
                    # No results found or unexpected format
                    return {
                        "id": group_id,
                        "name": f"Group {group_id[-8:]}",
                        "description": "Group not found in search results",
                        "type": "UNKNOWN",
                        "displayName": f"Group {group_id[-8:]}",
                        "error": f"Group not found with search: {search_filter}"
                    }
            else:
                # Fallback for unexpected response format
                return {
                    "id": group_id,
                    "name": f"Group {group_id[-8:]}",
                    "description": "Group details unavailable - unexpected search response format",
                    "type": "UNKNOWN",
                    "displayName": f"Group {group_id[-8:]}",
                    "error": f"Unexpected search response format: {type(group_data)}"
                }
        else:
            return {
                "id": group_id,
                "name": f"Group {group_id[-8:]}",
                "description": "Group details unavailable - API call failed",
                "type": "UNKNOWN",
                "displayName": f"Group {group_id[-8:]}",
                "error": f"API call failed with status: {group_response.get('status')}, message: {group_response.get('error', 'No error message')}"
            }
        
    except Exception as e:
        return {
            "id": group_id,
            "name": f"Group {group_id[-8:]}",
            "description": "Group details unavailable - exception occurred",
            "type": "UNKNOWN", 
            "displayName": f"Group {group_id[-8:]}",
            "error": str(e)
        }


async def find_application(client, app_identifier: str) -> Optional[Dict[str, Any]]:
    """Find application by ID, name, or label using base_okta_api_client."""
    
    # Try direct lookup by ID first if it looks like an Okta ID
    if app_identifier.startswith("0oa"):
        response = await client.make_request(f"/api/v1/apps/{app_identifier}")
        if response.get("status") == "success":
            return response.get("data")
    
    # Search by query parameter
    response = await client.make_request("/api/v1/apps", params={"q": app_identifier})
    if response.get("status") == "success":
        apps = response.get("data", [])
        if apps:
            # Look for exact match first
            for app in apps:
                label = app.get("label", "").lower()
                name = app.get("name", "").lower()
                search_term = app_identifier.lower()
                if (label == search_term or name == search_term):
                    return app
            
            # Return first match if no exact match
            return apps[0]
    
    # Final attempt: list all and search
    response = await client.make_request("/api/v1/apps")
    if response.get("status") == "success":
        apps = response.get("data", [])
        search_term = app_identifier.lower()
        
        # Search for partial matches
        matches_found = []
        for app in apps:
            label = app.get("label", "").lower()
            name = app.get("name", "").lower()
            
            if (search_term in label or search_term in name or
                label in search_term or name in search_term):
                matches_found.append(app)
        
        if matches_found:
            return matches_found[0]
    
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


