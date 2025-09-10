"""
Login Risk Analysis Special Tool - Using only base_okta_api_client.py
"""

# TOOL METADATA - Accessible to agents at runtime
TOOL_METADATA = {
    "lightweight_reference": {
        "entities": {
            "login_risk_analysis": {
                "operations": ["special_tool_analyze_login_risk"],
                "description": "Comprehensive login behavior analysis for risk assessment - returns raw data for LLM analysis",
                "aliases": ["login risk", "login analysis", "suspicious login", "login behavior", "authentication risk"],
                "query_patterns": [
                    "analyze login risk for {user}",
                    "check login behavior for {user}",
                    "is this login suspicious for {user}",
                    "login risk assessment"
                ]
            }
        },
        "entity_summary": {
            "login_risk_analysis": {
                "endpoint_count": 1
            }
        },
        "endpoints": [
            {
                "id": "special_tool_login-risk-analysis",
                "operationId": "special_tool_analyze_login_risk",
                "operation": "special_tool_analyze_login_risk",
                "path": "/special-tools/login-risk-analysis",
                "method": "GET",
                "summary": "SPECIAL TOOL: Comprehensive login risk analysis for users",
                "description": "REQUIRED PARAMETERS: Extract user identifier from the user's natural language query: 'user_identifier' (REQUIRED - user email/login/ID from query). SPECIAL TOOL: Collects last 10 login events (policy.evaluate_sign_on) including location patterns, device fingerprints, user agents, ISPs, network zones, and behavioral indicators. Returns comprehensive raw data for LLM risk assessment without making risk decisions. LLM MUST analyze the returned data and provide clear risk assessment with reasoning based on login patterns, location consistency, device familiarity, and behavioral anomalies while protecting PII.",
                "entity": "login_risk_analysis",
                "operation_group": "special_tool_analyze_login_risk",
                "parameters": {
                    "user_identifier": {
                        "type": "string",
                        "required": True,
                        "description": "User email, login, or Okta ID"
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
logger = logging.getLogger("special_tool_login_risk_analysis")
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
    Main function to analyze login risk for a user.
    Template parameters will be filled in by execution manager:
    - user_identifier: {user_identifier}
    """
    try:
        logger.info("Starting login risk analysis special tool...")
        logger.info(f"Parameters - user: '{user_identifier}'")
        
        client = OktaAPIClient(timeout=180)
        logger.info("OktaAPIClient created successfully")
        
        # Parameters extracted from query by planning agent
        user_identifier = "{user_identifier}"
        
        logger.info(f"Template parameters - user: '{user_identifier}'")
        
        # Import and call our login risk analysis function
        from login_risk_analysis import analyze_user_login_risk
        logger.info("Imported analyze_user_login_risk successfully")
        
        logger.info("Calling analyze_user_login_risk...")
        result = await analyze_user_login_risk(
            client=client,
            user_identifier=user_identifier
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
        error_result = {{"status": "error", "error": f"Exception in main: {{str(e)}}", "tool": "login_risk_analysis"}}
        logger.error(f"Exception caught: {{str(e)}}")
        print(json.dumps(error_result))

if __name__ == "__main__":
    try:
        logger.info("__main__ block executing...")
        asyncio.run(main())
        logger.info("asyncio.run completed successfully")
    except Exception as e:
        logger.error(f"Exception in __main__: {{str(e)}}")
        error_result = {{"status": "error", "error": f"Exception in __main__: {{str(e)}}", "tool": "login_risk_analysis"}}
        print(json.dumps(error_result))
'''

import json
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone


def get_tool_metadata(reference_type: str = "both"):
    """Get tool metadata for agent consumption."""
    if reference_type == "lightweight":
        return TOOL_METADATA["lightweight_reference"]
    else:
        return TOOL_METADATA


def get_tool_function():
    """Get the main tool function for execution."""
    return analyze_user_login_risk


def get_code_template():
    """Get the code template for subprocess execution."""
    return CODE_TEMPLATE


async def analyze_user_login_risk(
    client, 
    user_identifier: str
) -> Dict[str, Any]:
    """
    SPECIAL TOOL: Comprehensive login risk data collection for user behavior analysis.
    
    Uses only base_okta_api_client.py - no SDK dependencies.
    
    IMPORTANT: This tool ONLY collects raw data - it makes NO risk decisions.
    The LLM will analyze the returned data and make the final risk assessment.
    
    Args:
        client: OktaAPIClient instance
        user_identifier: User email, login, or ID (required)
        
    Returns:
        Dict containing raw login behavior data for LLM analysis (no decisions made)
    """
    # Import logging (will be available in subprocess context)
    try:
        from logging import get_logger, get_default_log_dir
        logger = get_logger("login_risk_analysis_function", get_default_log_dir())
    except:
        # Fallback to print if logging not available
        import sys
        class FakeLogger:
            def info(self, msg): print(f"INFO: {msg}", file=sys.stderr)
            def debug(self, msg): print(f"DEBUG: {msg}", file=sys.stderr)
            def error(self, msg): print(f"ERROR: {msg}", file=sys.stderr)
        logger = FakeLogger()
    
    logger.info(f"analyze_user_login_risk called with user='{user_identifier}'")
    
    # User-friendly progress messages
    print(f"STARTING LOGIN RISK ANALYSIS", file=sys.stderr)
    print(f"User: {user_identifier}", file=sys.stderr)
    sys.stderr.flush()
    
    # Basic validation
    if not user_identifier:
        error_result = {
            "status": "error", 
            "error": "user_identifier must be provided",
            "tool": "login_risk_analysis"
        }
        logger.error("Validation failed - no user_identifier")
        return error_result
    
    logger.info("Basic validation passed")
    
    result = {
        "status": "analyzing",
        "tool": "login_risk_analysis",
        "query_parameters": {
            "user_identifier": user_identifier
        }
    }
    
    try:
        # Step 1: Find the user
        logger.info(f"Step 1 - Finding user '{user_identifier}'")
        user = await find_user(client, user_identifier)
        if not user:
            print(f"USER NOT FOUND: '{user_identifier}'", file=sys.stderr)
            return {
                "status": "success",
                "result_type": "user_not_found",
                "entity": "user",
                "id": user_identifier,
                "tool": "login_risk_analysis",
                "message": f"User '{user_identifier}' not found. Please verify the email address or username is correct.",
                "error": f"User '{user_identifier}' not found in Okta org"
            }
        
        logger.info(f"User found: {user.get('id')} - {user.get('profile', {}).get('email')}")
        
        result["user_details"] = {
            "id": user.get("id"),
            "email": user.get("profile", {}).get("email"),
            "login": user.get("profile", {}).get("login"),
            "firstName": user.get("profile", {}).get("firstName"),
            "lastName": user.get("profile", {}).get("lastName"),
            "status": user.get("status")
        }
        
        user_id = user.get("id")
        
        # Step 2: Get last 10 policy.evaluate_sign_on events
        logger.info(f"Step 2 - Getting last 10 login events for user {user_id}")
        print(f"Fetching last 10 login events...", file=sys.stderr)
        
        # Calculate date range (last 30 days to ensure we get enough events)
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=30)
        
        # Format dates for Okta API
        since_param = start_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        until_param = end_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        
        # Get system log events
        logs_params = {
            "since": since_param,
            "until": until_param,
            "filter": f'eventType eq "policy.evaluate_sign_on" and actor.id eq "{user_id}"',
            "sortOrder": "DESCENDING",
            "limit": "10"
        }
        
        logs_response = await client.make_request("/api/v1/logs", params=logs_params, max_results=10)
        
        if logs_response.get("status") != "success":
            logger.error(f"Failed to fetch logs: {logs_response}")
            return {
                "status": "error",
                "error": f"Failed to fetch login events: {logs_response.get('error', 'Unknown error')}",
                "tool": "login_risk_analysis"
            }
        
        login_events = logs_response.get("data", [])
        logger.info(f"Retrieved {len(login_events)} login events")
        print(f"Found {len(login_events)} login events", file=sys.stderr)
        
        if not login_events:
            return {
                "status": "success",
                "result_type": "no_login_events",
                "tool": "login_risk_analysis",
                "message": f"No login events found for user '{user_identifier}' in the last 30 days",
                "user_details": result["user_details"]
            }
        
        # Step 3: Extract and structure login behavior data
        logger.info("Step 3 - Analyzing login behavior patterns")
        print(f"Analyzing login behavior patterns...", file=sys.stderr)
        
        login_behavior_data = []
        
        for i, event in enumerate(login_events):
            event_data = extract_login_event_data(event, i + 1)
            login_behavior_data.append(event_data)
        
        # Step 4: Build baseline patterns for comparison
        logger.info("Step 4 - Building baseline behavior patterns")
        baseline_patterns = build_baseline_patterns(login_behavior_data)
        
        # Step 5: Prepare comprehensive result
        result.update({
            "status": "success",
            "user_details": result["user_details"],
            "login_events_analyzed": len(login_behavior_data),
            "login_behavior_data": login_behavior_data,
            "baseline_patterns": baseline_patterns,
            "analysis_period": {
                "start_date": since_param,
                "end_date": until_param,
                "days_analyzed": 30
            }
        })
        
        # Add comprehensive analysis notes for LLM - similar to user_access_analysis.py
        result["notes_must_read"] = {
            "login_risk_assessment_logic": "To assess login risk for a user, analyze ALL the following behavioral patterns from the login_behavior_data and baseline_patterns: 1) CRITICAL: Check for VPN/Tor/Proxy usage in network data - immediate HIGH RISK, 2) CRITICAL: Check threat_suspected field - if true, immediate HIGH RISK, 3) Geographic impossibility - multiple distant locations in short timeframes, 4) Location consistency across events, 5) Network/ISP consistency, 6) Device fingerprint patterns, 7) User agent (OS/browser) stability, 8) Okta's behavioral risk scores, 9) Authentication timing patterns. Consider BOTH individual anomalies AND pattern deviations from user's baseline. VPN/Tor detection and threat flags override all other considerations.",
            
            "json_key_mapping": {
                "user_details.status": "User account status - ACTIVE users have normal login patterns",
                "login_events_analyzed": "Number of recent login events available for pattern analysis",
                "login_behavior_data[].location_data": "Geographic information for each login event",
                "login_behavior_data[].location_data.city": "City where login occurred - analyze for consistency",
                "login_behavior_data[].location_data.state": "State/region where login occurred",
                "login_behavior_data[].location_data.country": "Country where login occurred",
                "login_behavior_data[].network_data.isp": "Internet Service Provider - analyze for consistency",
                "login_behavior_data[].network_data.as_org": "Network organization - often same as ISP",
                "login_behavior_data[].network_data.is_proxy": "Whether connection uses proxy - sudden changes are suspicious",
                "login_behavior_data[].device_data.device_fingerprint": "Unique device identifier - STRONG indicator when consistent",
                "login_behavior_data[].device_data.os": "Operating system - analyze for consistency",
                "login_behavior_data[].device_data.browser": "Browser type - analyze for consistency",
                "login_behavior_data[].behavioral_analysis.risk_level": "Okta's assessment: LOW/MEDIUM/HIGH",
                "login_behavior_data[].behavioral_analysis.behaviors": "Okta's specific behavioral flags",
                "baseline_patterns.consistency_indicators": "Overall consistency assessment across all factors",
                "baseline_patterns.pattern_summary": "Count of unique values for each factor"
            },
            
            "risk_assessment_examples": {
                "low_risk_example": "This appears to be LOW RISK because over the last [X] login events, the user consistently logs in from their usual geographic area, uses the same network provider, maintains consistent device fingerprints, and shows stable browser/OS patterns. Okta's behavioral risk scores are consistently low with no anomalies detected.",
                "medium_risk_example": "This appears to be MEDIUM RISK because while the user shows some consistent patterns (same general region, familiar device fingerprint), there are minor variations such as occasional different network providers or browser updates. The behavioral risk scores show slight elevation but within normal variance.",
                "high_risk_example": "This appears to be HIGH RISK because the login patterns show significant deviations including: new geographic locations far from usual areas, unfamiliar network providers, new device fingerprints not seen before, and/or elevated behavioral risk scores with multiple anomaly flags.",
                "immediate_high_risk_vpn_example": "This is IMMEDIATE HIGH RISK because network analysis reveals VPN/Tor/Proxy usage (ISP contains anonymization keywords), which indicates potential credential compromise or unauthorized access attempts.",
                "immediate_high_risk_threat_example": "This is IMMEDIATE HIGH RISK because Okta's threat detection flagged this activity as suspicious (threat_suspected = true), indicating machine learning models detected attack patterns.",
                "geographic_impossibility_example": "This is IMMEDIATE HIGH RISK because the user appears to be logging in from multiple distant geographic locations within an impossible timeframe, strongly indicating credential compromise."
            },
            
            "pattern_evaluation_rules": {
                "location_analysis": "Consistent city/state indicates normal behavior. Sudden changes to distant locations raise suspicion unless travel is expected",
                "network_analysis": "Same ISP/network organization indicates familiar environment. New ISPs, especially with proxy usage, increase risk",
                "device_fingerprint_priority": "Device fingerprints are STRONGEST consistency indicator when present. Same fingerprint = high confidence it's the same device. Missing fingerprints should not increase risk score",
                "user_agent_analysis": "Stable OS and browser combinations indicate normal device usage. Dramatic changes (Windows to mobile, Chrome to Safari) may indicate different devices or compromise",
                "behavioral_score_interpretation": "Okta's risk_level and behaviors provide additional context. Multiple 'POSITIVE' behavioral flags indicate Okta detected anomalies",
                "baseline_comparison": "Compare current event against user's historical patterns. Deviations from established baseline are more significant than absolute values"
            },
            
            "high_risk_indicators_critical": {
                "vpn_tor_detection": "IMMEDIATE HIGH RISK - If ISP/network organization contains keywords like 'VPN', 'Tor', 'Proxy', 'Anonymous', 'VPS', 'Cloud', 'Hosting' - this indicates potential anonymization tools and should be flagged as HIGH RISK immediately",
                "geographic_impossibility": "IMMEDIATE HIGH RISK - Logins from multiple distant countries/continents within short time periods (impossible travel) indicate credential compromise",
                "proxy_usage_patterns": "HIGH RISK - If is_proxy field shows 'true' or network data indicates proxy/relay services, especially when combined with unfamiliar locations",
                "behavioral_velocity_flags": "HIGH RISK - If Okta behavioral analysis shows 'POSITIVE' flags for velocity, new geo-location, or multiple anomalies simultaneously",
                "threat_detection": "IMMEDIATE HIGH RISK - If threat_suspected field is 'true' or any value other than 'false', this indicates Okta's ML detected suspicious activity",
                "device_anomalies": "MEDIUM-HIGH RISK - Multiple different device fingerprints in short time periods, or sudden changes in OS/browser combinations",
                "failed_then_success": "MEDIUM RISK - Pattern of CHALLENGE/FAILURE outcomes followed by SUCCESS may indicate credential stuffing or brute force attempts",
                "unusual_authentication_patterns": "MEDIUM RISK - Inconsistent authentication step patterns or unusual session ID formats may indicate automated tools"
            },
            
            "network_risk_keywords": {
                "immediate_high_risk_isp_keywords": [
                    "VPN", "Tor", "TOR", "Proxy", "Anonymous", "Private", "Tunnel", "VPS", "Virtual", "Cloud", "Hosting", "Datacenter", "Server", "Relay", "Shield", "Hide", "Mask", "Ghost"
                ],
                "suspicious_domains": [
                    "Contains 'vpn', 'proxy', 'tor', 'hide', 'anonymous', 'private' in domain names",
                    "Generic cloud/hosting domains instead of residential ISPs",
                    "Domains from known VPN/proxy service providers"
                ],
                "evaluation_instruction": "Scan network_data.isp, network_data.as_org, and network_data.domain fields for these keywords. Even partial matches should trigger HIGH RISK assessment."
            },
            
            "privacy_protection_mandatory": {
                "never_reveal_in_response": [
                    "Specific city, state, or country names",
                    "IP addresses or network ranges", 
                    "ISP names or network organization names",
                    "Exact geographic coordinates",
                    "Device fingerprint values",
                    "Any personally identifiable information from the data"
                ],
                "use_these_generic_terms": [
                    "'usual location' or 'familiar geographic area' instead of city names",
                    "'same network provider' or 'different ISP' instead of ISP names",
                    "'consistent location pattern' or 'geographic anomaly' instead of specific places",
                    "'known device fingerprint' or 'unfamiliar device' instead of fingerprint values",
                    "'typical network environment' or 'new network context' instead of network details"
                ],
                "example_compliant_language": "The user consistently logs in from their usual location using familiar network infrastructure with the same device fingerprint pattern, indicating low risk behavior."
            },
            
            "confidence_assessment_guidelines": {
                "high_confidence": "5+ login events with complete data (location, network, device info) showing clear patterns",
                "medium_confidence": "3-4 login events or some missing data but clear trends visible", 
                "low_confidence": "Less than 3 events or significant missing data (many null values)",
                "data_quality_factors": "Device fingerprints, complete location data, and behavioral scores increase confidence"
            },
            
            "response_format_instructions": "Always structure response as: 1) RISK LEVEL (LOW/MEDIUM/HIGH), 2) CONFIDENCE (HIGH/MEDIUM/LOW), 3) Detailed reasoning based on pattern analysis using ONLY generic privacy-safe language, 4) Specific factors that influenced the assessment, 5) Any data limitations that affected confidence level."
        }
        
        logger.info("Login risk analysis completed successfully")
        print(f"Analysis completed - ready for LLM assessment", file=sys.stderr)
        
        return result
        
    except Exception as e:
        error_result = {
            "status": "error",
            "error": f"Failed to analyze login risk: {str(e)}",
            "tool": "login_risk_analysis"
        }
        logger.error(f"Exception in main analysis: {str(e)}")
        return error_result


def extract_login_event_data(event: Dict[str, Any], event_number: int) -> Dict[str, Any]:
    """Extract relevant data from a single login event."""
    
    # Extract client information
    client_info = event.get("client", {})
    user_agent = client_info.get("userAgent", {})
    geo_context = client_info.get("geographicalContext", {})
    geolocation = geo_context.get("geolocation", {})
    
    # Extract security context
    security_context = event.get("securityContext", {})
    
    # Extract debug context for behavioral data
    debug_context = event.get("debugContext", {})
    debug_data = debug_context.get("debugData", {})
    
    # Parse behavioral risk data
    behavioral_data = {}
    log_only_security_data = debug_data.get("logOnlySecurityData")
    if log_only_security_data:
        try:
            import json
            if isinstance(log_only_security_data, str):
                behavioral_data = json.loads(log_only_security_data)
            else:
                behavioral_data = log_only_security_data
        except:
            behavioral_data = {"parse_error": True}
    
    # Extract outcome information
    outcome = event.get("outcome", {})
    
    return {
        "event_number": event_number,
        "timestamp": event.get("published"),
        "event_type": event.get("eventType"),
        "outcome": {
            "result": outcome.get("result"),
            "reason": outcome.get("reason")
        },
        "location_data": {
            "city": geo_context.get("city"),
            "state": geo_context.get("state"), 
            "country": geo_context.get("country"),
            "postal_code": geo_context.get("postalCode"),
            "latitude": geolocation.get("lat"),
            "longitude": geolocation.get("lon")
        },
        "network_data": {
            "ip_address": client_info.get("ipAddress"),
            "as_number": security_context.get("asNumber"),
            "as_org": security_context.get("asOrg"),
            "isp": security_context.get("isp"),
            "domain": security_context.get("domain"),
            "is_proxy": security_context.get("isProxy", False),
            "zone": client_info.get("zone")
        },
        "device_data": {
            "device_type": client_info.get("device"),
            "device_fingerprint": debug_data.get("deviceFingerprint"),
            "os": user_agent.get("os"),
            "browser": user_agent.get("browser"),
            "raw_user_agent": user_agent.get("rawUserAgent")
        },
        "behavioral_analysis": {
            "risk_level": behavioral_data.get("risk", {}).get("level"),
            "behaviors": behavioral_data.get("behaviors", {}),
            "threat_suspected": debug_data.get("threatSuspected")
        }
    }


def build_baseline_patterns(login_events: list) -> Dict[str, Any]:
    """Build baseline patterns from login events for comparison."""
    
    if not login_events:
        return {}
    
    # Extract unique values for pattern analysis
    locations = set()
    isps = set()
    oses = set()
    browsers = set()
    device_fingerprints = set()
    risk_levels = []
    device_types = set()
    
    for event in login_events:
        # Location patterns
        location_data = event.get("location_data", {})
        if location_data.get("city") and location_data.get("state"):
            locations.add(f"{location_data.get('city')}, {location_data.get('state')}")
        
        # Network patterns
        network_data = event.get("network_data", {})
        if network_data.get("isp"):
            isps.add(network_data.get("isp"))
        
        # Device patterns
        device_data = event.get("device_data", {})
        if device_data.get("os"):
            oses.add(device_data.get("os"))
        if device_data.get("browser"):
            browsers.add(device_data.get("browser"))
        if device_data.get("device_fingerprint"):
            device_fingerprints.add(device_data.get("device_fingerprint"))
        if device_data.get("device_type"):
            device_types.add(device_data.get("device_type"))
        
        # Risk patterns
        behavioral_analysis = event.get("behavioral_analysis", {})
        if behavioral_analysis.get("risk_level"):
            risk_levels.append(behavioral_analysis.get("risk_level"))
    
    return {
        "pattern_summary": {
            "unique_locations": len(locations),
            "unique_isps": len(isps),
            "unique_operating_systems": len(oses),
            "unique_browsers": len(browsers),
            "unique_device_fingerprints": len(device_fingerprints),
            "unique_device_types": len(device_types)
        },
        "consistency_indicators": {
            "location_consistency": "HIGH" if len(locations) <= 2 else "MEDIUM" if len(locations) <= 4 else "LOW",
            "network_consistency": "HIGH" if len(isps) <= 1 else "MEDIUM" if len(isps) <= 2 else "LOW",
            "device_consistency": "HIGH" if len(device_fingerprints) <= 2 else "MEDIUM" if len(device_fingerprints) <= 4 else "LOW",
            "browser_consistency": "HIGH" if len(browsers) <= 1 else "MEDIUM" if len(browsers) <= 2 else "LOW"
        },
        "risk_pattern": {
            "most_common_risk_level": max(set(risk_levels), key=risk_levels.count) if risk_levels else None,
            "risk_level_variations": len(set(risk_levels))
        },
        "analysis_confidence": {
            "data_quality": "HIGH" if len(login_events) >= 5 else "MEDIUM" if len(login_events) >= 3 else "LOW",
            "pattern_reliability": "HIGH" if all([
                len(locations) > 0,
                len(isps) > 0, 
                len(device_fingerprints) > 0
            ]) else "MEDIUM"
        }
    }


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
