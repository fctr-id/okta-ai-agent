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
    name="get_event_logs",
    entity_type="event",
    aliases=["list_logs", "get_logs", "fetch_events"]
)
async def get_event_logs(client, query_params=None):
    """
    Fetches System Log events from Okta with filtering options. Returns formatted logs with human-readable fields including actors, targets, and timestamps.

    # Tool Documentation: Get Okta System Log Events
    
    ## Goal
    This tool queries the Okta System Log API to retrieve audit events.
    
    ## Parameters
    *   **`query_params`** (Required, Dict): Parameters for filtering logs
        *   `filter`: SCIM filter expression (e.g., "eventType eq \"user.session.start\"")
        *   `since`: Start time (ISO8601 timestamp)
        *   `until`: End time (ISO8601 timestamp) 
        *   `limit`: Number of results to return (default: 1000, max: 1000)
        *   `sortOrder`: "ASCENDING" or "DESCENDING" (default: "ASCENDING")
        *   `q`: Keyword search (URL encoded)
    
    ## Output Format
    Events are returned in a standardized format with the following fields:
    - eventId: Unique identifier
    - eventType: Type of event that occurred
    - eventDescription: Human-readable description
    - timestamp: Local time of the event
    - severity: Importance level
    - result: Outcome (SUCCESS, FAILURE, etc.)
    - reason: Failure reason (if applicable)
    - actor: Who performed the action (name, email, type)
    - client: Where the action was performed (IP, location)
    - targets: What resources were affected (name, type, ID)
    
    ## Common Event Types
    - Authentication: user.session.start, user.session.end
    - User Actions: user.account.update_profile, user.mfa.factor.verify
    - Admin Actions: system.api_token.create, system.app.user.consent.grant
    - Application: application.lifecycle.create, application.user_membership.add
    - Group: group.user_membership.add, group.user_membership.remove

    ## Example Usage
    ```python
    # Get login events from the last 7 days
    # First, get ISO format timestamps using datetime tools
    current_time = format_date_for_query(datetime.now())
    start_date = format_date_for_query(datetime.now() - timedelta(days=7))
    
    # Build query parameters
    query_params = {
        "filter": "eventType eq \"user.session.start\"",
        "since": start_date,
        "until": current_time,
        "limit": 100
    }
    
    # Get logs with pagination
    raw_logs = await paginate_results(
        "get_logs",
        query_params=query_params,
        entity_name="events"
    )
    
    # Check for errors
    if isinstance(raw_logs, dict) and "status" in raw_logs and raw_logs["status"] == "error":
        return raw_logs
        
    # Handle empty results
    if not raw_logs:
        return []
        
    # Format logs with readable timestamps and clean structure
    formatted_logs = format_event_logs(raw_logs)
    return formatted_logs
    ```
    
    ## Error Handling
    If the API call fails, returns an error object: `{"status": "error", "error": error_message}`
    If no events are found, returns an empty list `[]`
    
    ## Important Notes
    - Data returned by paginate_results is already in dictionary format (not objects)
    - Access fields using dictionary syntax: event["property"]["field"] (not object.attribute syntax)
    - Pagination is handled automatically for large result sets
    - The Okta API may limit results based on your rate limits
    - Results are automatically formatted with human-readable timestamps
    - Double quotes must be used inside filter strings and properly escaped
    - Time expressions MUST be in ISO8601 format (use datetime tools if needed)
    """
    # Implementation will be handled by code generation
    # This function is just a placeholder for registration
    pass

logger.info("Registered event log tools")