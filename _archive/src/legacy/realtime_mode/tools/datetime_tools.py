"""
Date and time utility tools for Okta API operations.
Contains documentation and examples for datetime parsing and formatting.
"""

from typing import Dict, Any, Optional, Tuple, Union
from datetime import datetime, timedelta, timezone
import dateparser
from src.utils.tool_registry import register_tool
from src.utils.logging import get_logger

# Configure logging
logger = get_logger(__name__)

# ---------- Tool Registration ----------

@register_tool(
    name="get_current_time",
    entity_type="datetime",
    aliases=["current_time", "now", "current_date", "today"]
)
async def get_current_time(client=None, buffer_hours=0, format="iso"):
    """
    Returns current UTC time as tuple (timestamp_string, error). ALWAYS use tuple unpacking: current_time, error = await get_current_time(). Returns FIRST value on success, SECOND on error. Optional: buffer_hours (int) to adjust time, format (iso/date/time/datetime) for output format.
    
    # Tool Documentation: Get Current Time Utility
    IMPORTANT: YOU MUST ALWAYS PROVIDE CODE AS MENTIONED IN THE EXAMPLE USAGE or THAT MATCHES IT. DO NOT ADD ANYTHING ELSE.
    
    ## Goal
    This tool provides the current date and time in UTC format.
    
    ## Core Functionality
    Gets current time with optional offset and formatting options.
    
    ## Parameters
    *   **`buffer_hours`** (Integer, Optional): Hours to add to current time (can be negative)
    *   **`format`** (String, Optional): Output format (iso, date, time, datetime)
    
    ## Output Pattern
    IMPORTANT: Unlike API tools, this returns a tuple (value, error):
    - Success: (timestamp, None)
    - Error: (None, error_object)
    - ALWAYS use with tuple unpacking: value, error = await get_current_time()
    
    ## Multi-Step Usage
    *   Often used at the beginning of multi-step workflows to get time bounds
    *   Frequently paired with parse_relative_time for relative date calculations
    *   Can provide times for log queries using the iso format
    *   Store results in variables named start_time, end_time, or current_time
    *   For error reporting, convert errors to standard format: `{"operation_status": "error", "reason": err["error"]}`
    
    ## Example Usage
    ```python
    current_time, err = await get_current_time()
    if err:
        return {"operation_status": "error", "reason": err["error"]}
        
    yesterday, err = await get_current_time(buffer_hours=-24)
    if err:
        return {"operation_status": "error", "reason": err["error"]}
    
    query_params = {
        "since": yesterday,
        "until": current_time
    }
    ```
    
    ## Important Notes
    - All times are in UTC
    - The ISO format used is compatible with Okta API date filters
    - No client/API calls are made by this function
    - The client parameter is optional and can be omitted
    - ALWAYS use tuple unpacking to handle both result and potential errors
    - Convert error responses to standard format when returning from steps
    """
    try:
        # Get current UTC time
        now = datetime.now(timezone.utc)
        
        # Add buffer if specified
        if buffer_hours:
            now += timedelta(hours=buffer_hours)
        
        # Format according to requested format
        if format == "iso":
            result = now.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        elif format == "date":
            result = now.strftime('%Y-%m-%d')
        elif format == "time":
            result = now.strftime('%H:%M:%S')
        elif format == "datetime":
            result = now.strftime('%Y-%m-%dT%H:%M:%SZ')
        else:
            # Default to ISO format
            result = now.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        
        return result, None
    except Exception as e:
        error = {"status": "error", "error": f"Error in get_current_time: {str(e)}"}
        return None, error


@register_tool(
    name="parse_relative_time",
    entity_type="datetime",
    aliases=["relative_time", "parse_time", "time_expression"]
)
async def parse_relative_time(client=None, time_expression=None):
    """
    Converts natural language time (e.g., "2 days ago") to ISO format UTC timestamp. Returns tuple (timestamp_string, error). ALWAYS use with tuple unpacking: timestamp, error = await parse_relative_time("expression"). For different expression formats, pass time_expression as first arg.

    # Tool Documentation: Parse Relative Time Utility
    IMPORTANT: YOU MUST ALWAYS PROVIDE CODE AS MENTIONED IN THE EXAMPLE USAGE or THAT MATCHES IT. DO NOT ADD ANYTHING ELSE.
    
    ## Goal
    This tool converts natural language time expressions to ISO format timestamps.
    
    ## Core Functionality
    Parses relative date/time expressions and returns standardized UTC timestamps.
    
    ## Parameters
    *   **`time_expression`** (Required, String): Natural language time expression to parse
        *   Examples: "2 days ago", "last week", "yesterday", "3 hours ago"
    
    ## Output Pattern
    IMPORTANT: Unlike API tools, this returns a tuple (value, error):
    - Success: (timestamp, None)
    - Error: (None, error_object)
    - ALWAYS use with tuple unpacking: value, error = await parse_relative_time()
    
    ## Multi-Step Usage
    *   Used in log and event searches to define time periods
    *   Paired with get_current_time for creating time ranges
    *   Useful for creating "since" parameters in query_params
    *   Store results in descriptive variable names like start_time, week_ago, month_ago
    *   For error reporting, convert errors to standard format: `{"operation_status": "error", "reason": err["error"]}`
    
    ## Example Usage
    ```python
    two_days_ago, err = await parse_relative_time("2 days ago")
    if err:
        return {"operation_status": "error", "reason": err["error"]}
    
    start_date, err = await parse_relative_time("7 days ago")
    if err:
        return {"operation_status": "error", "reason": err["error"]}
        
    query_params = {
        "since": start_date,
        "until": current_time
    }
    ```
    
    ## Important Notes
    - All returned times are in UTC with Z suffix
    - The function accepts many natural language formats
    - Supports relative times (ago, last week) and absolute times (May 1 2025)
    - ALWAYS use tuple unpacking to handle both result and potential errors
    - Convert error responses to standard format when returning from steps
    """
    try:
        # Handle the case where the first argument might be the time_expression
        # This happens when the function is called like parse_relative_time("2 days ago")
        if client is not None and time_expression is None and isinstance(client, str):
            time_expression = client
            client = None
        
        # Now check if time_expression is still None
        if time_expression is None:
            return None, {"status": "error", "error": "Missing required parameter: time_expression"}
        
        parsed_time = dateparser.parse(
            time_expression, 
            settings={'RETURN_AS_TIMEZONE_AWARE': True}
        )
        
        if parsed_time is None:
            return None, {"status": "error", "error": f"Could not parse time expression: '{time_expression}'"}
        
        # Format with 'Z' to explicitly indicate UTC
        result = parsed_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        return result, None
        
    except Exception as e:
        return None, {"status": "error", "error": f"Error parsing time expression '{time_expression}': {str(e)}"}


@register_tool(
    name="format_date_for_query",
    entity_type="datetime",
    aliases=["date_format", "query_date", "format_date"]
)
async def format_date_for_query(client=None, date_value=None, output_format="iso"):
    """
    Formats dates for Okta API queries, returning tuple (formatted_string, error). ALWAYS use tuple unpacking: formatted_date, error = await format_date_for_query("date_string"). Required: date_value (string/timestamp). Optional: output_format (iso/date/time/datetime).

    # Tool Documentation: Format Date for API Query
    IMPORTANT: YOU MUST ALWAYS PROVIDE CODE AS MENTIONED IN THE EXAMPLE USAGE or THAT MATCHES IT. DO NOT ADD ANYTHING ELSE.
    
    ## Goal
    This tool standardizes dates and times into formats compatible with Okta API queries.
    
    ## Core Functionality
    Converts various date/time formats to standardized strings for use in API filters.
    
    ## Parameters
    *   **`date_value`** (Required, String): The date/time value to format
        *   Can be ISO date, natural language, or Unix timestamp
    *   **`output_format`** (Optional, String): Desired format (iso, date, time, datetime)
    
    ## Output Pattern
    IMPORTANT: Unlike API tools, this returns a tuple (value, error):
    - Success: (formatted_date, None)
    - Error: (None, error_object)
    - ALWAYS use with tuple unpacking: value, error = await format_date_for_query()
    
    ## Multi-Step Usage
    *   Used to prepare query parameters for API searches
    *   Often follows parse_relative_time or get_current_time
    *   Useful for converting user-supplied dates to API-compatible formats
    *   Store results in descriptive variables like start_date, end_date, or query_date
    *   For error reporting, convert errors to standard format: `{"operation_status": "error", "reason": err["error"]}`
    
    ## Example Usage
    ```python
    formatted_date, err = await format_date_for_query("2023-06-15")
    if err:
        return {"operation_status": "error", "reason": err["error"]}
    
    date_only, err = await format_date_for_query("yesterday", "date")
    if err:
        return {"operation_status": "error", "reason": err["error"]}
        
    query_params = {
        "search": f'created gt "{date_only}"'
    }
    ```
    
    ## Important Notes
    - All times are returned in UTC
    - For Okta API queries, use ISO format with the 'Z' suffix
    - Can parse many formats: natural language, Unix timestamps, ISO dates
    - When using in filters, remember to properly escape double quotes
    - ALWAYS use tuple unpacking to handle both result and potential errors
    - Convert error responses to standard format when returning from steps
    """
    try:
        # Handle the case where the first argument might be the date_value
        if client is not None and date_value is None and not isinstance(client, dict):
            date_value = client
            client = None
            
        if date_value is None:
            error = {"status": "error", "error": "Missing required parameter: date_value"}
            return None, error
            
        # Try to parse the input date
        if isinstance(date_value, str) and date_value.isdigit():
            # Handle Unix timestamp
            parsed_date = datetime.fromtimestamp(int(date_value), tz=timezone.utc)
        else:
            # Handle string dates and natural language
            parsed_date = dateparser.parse(
                str(date_value), 
                settings={'RETURN_AS_TIMEZONE_AWARE': True}
            )
        
        if parsed_date is None:
            error = {"status": "error", "error": f"Could not parse date value: '{date_value}'"}
            return None, error
        
        # Format according to requested format
        if output_format == "iso":
            result = parsed_date.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        elif output_format == "date":
            result = parsed_date.strftime('%Y-%m-%d')
        elif output_format == "time":
            result = parsed_date.strftime('%H:%M:%S')
        elif output_format == "datetime":
            result = parsed_date.strftime('%Y-%m-%dT%H:%M:%SZ')
        else:
            # Default to ISO format
            result = parsed_date.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        
        return result, None
        
    except Exception as e:
        error = {"status": "error", "error": f"Error formatting date '{date_value}': {str(e)}"}
        return None, error

logger.info("Registered datetime utility tools")