"""
Tools for querying Okta System Log events.
"""

from typing import Dict, Any, Optional, List
import dateparser
from datetime import datetime
from src.utils.tool_registry import register_tool
from src.utils.logging import get_logger

# Configure logging
logger = get_logger(__name__)

def format_event_logs(logs: List[Dict]) -> List[Dict]:
    """
    Formats event logs into a consistent structure with properly formatted timestamps,
    aggregating related events by UUID.
    
    Args:
        logs: List of raw event log dictionaries from Okta API
        
    Returns:
        List of formatted event log dictionaries, aggregated by UUID
    """
    import dateparser
    from datetime import datetime
    import pytz
    from tzlocal import get_localzone
    
    # Get the local timezone
    local_tz = get_localzone()
    
    # Use dictionary to group by UUID for aggregation
    events_by_uuid = {}
    
    for event in logs:
        uuid = event.get("uuid", "unknown")
        
        # Format timestamp to proper local time with timezone
        if "published" in event:
            # Parse the ISO 8601 timestamp (which is in UTC)
            utc_time = dateparser.parse(event["published"])
            if utc_time:
                # Convert to local timezone
                local_time = utc_time.astimezone(local_tz)
                # Format with timezone name
                formatted_time = local_time.strftime("%Y-%m-%d %H:%M:%S %Z")
            else:
                formatted_time = "Unknown"
        else:
            formatted_time = "Unknown"
            
        # Create base event structure if this UUID hasn't been seen before
        if uuid not in events_by_uuid:
            events_by_uuid[uuid] = {
                "eventId": uuid,
                "eventType": event.get("eventType", ""),
                "eventDescription": event.get("displayMessage", ""),
                "timestamp": formatted_time,
                "utcTimestamp": event.get("published", ""),  # Preserve original UTC timestamp
                "severity": event.get("severity", ""),
                "result": event.get("outcome", {}).get("result", ""),
                "reason": event.get("outcome", {}).get("reason", ""),
                "transaction": event.get("transaction", {}).get("id", ""),
                "legacyEventType": event.get("legacyEventType", ""),
                "actors": [],
                "clients": [],
                "targets": [],
                "securityContext": {}
            }
            
            # Add security context if available
            sec_context = event.get("securityContext")
            if sec_context:
                events_by_uuid[uuid]["securityContext"] = {
                    "asNumber": sec_context.get("asNumber", ""),
                    "asOrg": sec_context.get("asOrg", ""),
                    "isp": sec_context.get("isp", ""),
                    "domain": sec_context.get("domain", ""),
                    "isProxy": sec_context.get("isProxy", False)
                }
                
            # Add debug context if available
            debug_context = event.get("debugContext")
            if debug_context and "debugData" in debug_context:
                events_by_uuid[uuid]["debugInfo"] = debug_context["debugData"]
        
        # Add actor information (who performed the action) if new
        actor = event.get("actor")
        if actor:
            actor_id = actor.get("id", "")
            if actor_id:
                # Check if this actor is already in the list
                actor_exists = False
                for existing_actor in events_by_uuid[uuid]["actors"]:
                    if existing_actor.get("id") == actor_id:
                        actor_exists = True
                        break
                
                if not actor_exists:
                    events_by_uuid[uuid]["actors"].append({
                        "name": actor.get("displayName", ""),
                        "id": actor_id,
                        "email": actor.get("alternateId", ""),
                        "type": actor.get("type", "")
                    })
        
        # Add client information (where the action was performed) if new
        client = event.get("client")
        if client:
            ip_address = client.get("ipAddress", "")
            if ip_address:
                # Check if this client is already in the list
                client_exists = False
                for existing_client in events_by_uuid[uuid]["clients"]:
                    if existing_client.get("ipAddress") == ip_address:
                        client_exists = True
                        break
                
                if not client_exists:
                    geo = client.get("geographicalContext", {})
                    
                    # Build location string
                    location_parts = []
                    if geo.get("city"):
                        location_parts.append(geo["city"])
                    if geo.get("state"):
                        location_parts.append(geo["state"])
                    if geo.get("country"):
                        location_parts.append(geo["country"])
                    
                    location = ", ".join(location_parts) if location_parts else ""
                    
                    events_by_uuid[uuid]["clients"].append({
                        "ipAddress": ip_address,
                        "location": location,
                        "device": client.get("device", ""),
                        "userAgent": client.get("userAgent", {}).get("rawUserAgent", "")
                    })
        
        # Add target information (what was affected)
        targets = event.get("target", [])
        if targets:
            for target in targets:
                target_id = target.get("id", "")
                if target_id:
                    # Check if this target is already in the list
                    target_exists = False
                    for existing_target in events_by_uuid[uuid]["targets"]:
                        if existing_target.get("id") == target_id:
                            target_exists = True
                            break
                    
                    if not target_exists:
                        target_formatted = {
                            "name": target.get("displayName", ""),
                            "id": target_id,
                            "identifier": target.get("alternateId", ""),
                            "type": target.get("type", "")
                        }
                        
                        # Add details if available
                        detail_entry = target.get("detailEntry")
                        if detail_entry:
                            target_formatted["details"] = detail_entry
                        
                        events_by_uuid[uuid]["targets"].append(target_formatted)
    
    # Convert the dictionary values to a list for return
    return list(events_by_uuid.values())

@register_tool(
    name="get_logs",
    entity_type="event",
    aliases=["list_logs", "fetch_events"]
)
async def get_logs(client, query_params=None):
    """
    Fetches Okta System Log events via paginate_results. Returns LIST of event objects, NOT tuples. For time filtering use 'since' and 'until' params NOT 'published' field. Example: query_params={"since":"2025-05-05T00:00:00Z", "filter":'eventType eq "user.session.start"'}

    # Tool Documentation: Get Okta System Log Events
    #IMPORTANT: YOU MUST ALWAYS PROVIDE CODE AS MENTIONED IN THE EXAMPLE USAGE or THAT MATCCHES IT. DO NOT ADD ANYTHING ELSE.

    ## Goal
    This tool queries the Okta System Log API to retrieve audit events using SCIM filter syntax.

    ## Core Functionality
    Retrieves detailed system log events with filtering options for time ranges, event types, users, and authentication events. Supports all SCIM filter operators including eq, gt, lt, ge, le, sw, and Okta-specific co, ew operators.

    ## Parameters
    *   **`query_params`** (Required, Dict): Parameters for filtering logs
        *   `filter`: SCIM filter expression (see examples below)
        *   `since`: Start time (ISO8601 timestamp) - RECOMMENDED for time filtering
        *   `until`: End time (ISO8601 timestamp) - RECOMMENDED for time filtering
        *   `limit`: Number of results to return (default: 1000, max: 1000)
        *   `sortOrder`: "ASCENDING" or "DESCENDING" (default: "ASCENDING")
        *   `q`: Keyword search (URL encoded)

    ## SCIM Filter Operators
    - Equality: eq (equals), ne (not equals)
    - Comparison: gt (greater than), lt (less than), ge (greater than or equal), le (less than or equal)
    - String: sw (starts with), co (contains), ew (ends with)
    - Logical: and, or, not
    - Grouping: ( )

    ## Common Event Fields
    - actor.id: User ID who performed the action
    - actor.alternateId: User email who performed the action
    - target.id: ID of object affected by the action
    - target.alternateId: Email/name of object affected
    - eventType: Type of event (e.g., "user.session.start")
    - published: UTC timestamp of when the event occurred
    - displayMessage: Human-readable description of the event

    IMPORTANT: YOU MUST ALWAYS PROVIDE CODE AS MENTIONED IN THE EXAMPLE USAGE or THAT MATCHES IT. DO NOT ADD ANYTHING ELSE.

    ## Example Usage
    ```python
    # Example 1: Basic search by user who performed actions
    # RECOMMENDED: Use 'since' parameter instead of 'published gt' in filter
    two_days_ago, err = await parse_relative_time("2 days ago")
    if err:
        return {"status": "error", "error": err["error"]}
    
    query_params = {
        "since": two_days_ago,
        "filter": 'actor.alternateId eq "user@example.com"',
        "limit": 100
    }
    
    log_results = await paginate_results(
        "get_logs",
        query_params=query_params,
        entity_name="events"
    )
    
    if isinstance(log_results, dict) and "status" in log_results and log_results["status"] == "error":
        return log_results
        
    if not log_results:
        return []
        
    return log_results

    # Example 2: Multi-step workflow with time calculation
    # Step 1: Get time for 7 days ago
    time_result, err = await parse_relative_time("7 days ago")
    if err:
        return {"status": "error", "error": err["error"]}
    
    # Step 2: Get logs for login and password change events
    # RECOMMENDED: Using since parameter for time filtering
    query_params = {
        "since": time_result,
        "filter": '(eventType eq "user.session.start" or eventType eq "user.account.update_password")',
        "limit": 100
    }
    
    # Step 3: Get logs with pagination
    log_results = await paginate_results(
        "get_logs",
        query_params=query_params,
        entity_name="events"
    )
    
    if isinstance(log_results, dict) and "status" in log_results and log_results["status"] == "error":
        return log_results
        
    if not log_results:
        return []
        
    return log_results

    # Example 3: Using results from previous steps with time window
    # Step 1: Get user
    user_result = await handle_single_entity_request(
        method_name="get_user",
        entity_type="user",
        entity_id=user_email,
        method_args=[user_email]
    )
    
    if isinstance(user_result, dict) and "status" in user_result:
        return user_result
    
    # Step 2: Extract user ID and get timestamps
    user_id = user_result["id"]
    two_days_ago, err = await parse_relative_time("2 days ago")
    if err:
        return {"status": "error", "error": err["error"]}
    
    # Note: Use since parameter for time filtering and actor.id for user filtering
    query_params = {
        "since": two_days_ago,
        "filter": 'actor.id eq "' + user_id + '"',
        "limit": 100
    }
    
    # Step 3: Get logs with pagination
    log_results = await paginate_results(
        "get_logs",
        query_params=query_params,
        entity_name="events"
    )
    
    if isinstance(log_results, dict) and "status" in log_results and log_results["status"] == "error":
        return log_results
        
    if not log_results:
        return []
        
    return log_results
    ```

    ## Common Filter Patterns
    ```python
    # Login events
    'eventType eq "user.session.start"'
    
    # Password changes
    'eventType eq "user.account.update_password"'
    
    # Admin actions by specific user
    'actor.alternateId eq "admin@example.com" and eventType sw "system."'
    
    # Failed login attempts
    'eventType eq "user.session.start" and outcome.result eq "FAILURE"'
    
    # Search by IP address
    'client.ipAddress eq "192.168.1.1"'
    
    # Events containing specific text
    'displayMessage co "password"'
    ```

    ## Error Handling
    - If the API call fails, returns an error object: `{"status": "error", "error": error_message}`
    - If no events are found, returns an empty list `[]`
    - If a previous step fails, use: `return {"status": "dependency_failed", "dependency": "step_name", "error": error_message}`

    ## Important Notes
    - For time-based filtering, use 'since' and 'until' parameters instead of 'published' field in filter
    - Data returned by paginate_results is already in dictionary format (not objects)
    - Do NOT call as_dict() on the results - this will cause errors
    - Use actor.id/alternateId for searching who performed actions
    - Use target.id/alternateId for searching what was affected
    - SCIM filter syntax requires individual comparisons with 'or', not 'in' operators
    - String values must be enclosed in double quotes and properly escaped
    - Date values must use ISO 8601 format: YYYY-MM-DDTHH:mm:ss.SSSZ
    - The System Log API uniquely supports 'co' (contains) and 'ew' (ends with) operators
    - For multi-step workflows, always properly reference previous step variables
    - Never use underscore (_) as a variable name for previous step results
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass

logger.info("Registered event log tools")