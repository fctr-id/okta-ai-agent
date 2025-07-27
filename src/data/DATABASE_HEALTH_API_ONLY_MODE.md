# Database Health Check & API-Only Mode Feature

## Overview

The Modern Execution Manager now includes intelligent database health checking and API-only mode functionality. This ensures the system gracefully handles scenarios where the SQL database is unavailable or when users explicitly request API-only operations.

## Features Added

### 1. Database Health Check

```python
def _check_database_health(self) -> bool:
    """Check if SQLite database exists and is populated with users."""
```

- **Purpose**: Verifies that the SQLite database exists and contains at least 1 user record
- **Locations Checked**: Multiple possible database paths including `sqlite_db/okta_sync.db`
- **Validation**: Checks both table existence and user count
- **Error Handling**: Gracefully handles database connection failures

### 2. API-Only Mode Detection

```python
def _should_force_api_only_mode(self, query: str, force_api_only: bool = False) -> tuple[bool, str]:
    """Determine if query should use API-only mode and modify query if needed."""
```

**Triggers API-only mode when:**
1. **Frontend Flag**: `force_api_only=True` parameter passed
2. **User Request**: Query contains phrases like:
   - "do not use sql" / "don't use sql"
   - "no sql"
   - "api only" / "apis only" / "api calls only"
   - "without using sql"
3. **Database Unavailable**: Health check fails (DB missing or empty)

**Query Modification:**
- If API-only mode is triggered but not explicitly requested, appends: `". Do NOT use SQL and only use APIs"`
- This ensures the Planning Agent generates API-only execution plans

### 3. Enhanced Execute Query Method

```python
async def execute_query(self, query: str, force_api_only: bool = False) -> Dict[str, Any]:
```

- **New Parameter**: `force_api_only` flag for frontend control
- **Intelligent Decision**: Automatically determines best execution mode
- **Comprehensive Logging**: Logs decision rationale and mode selection

### 4. Public Health Check API

```python
def is_database_healthy(self) -> Dict[str, Any]:
    """Public method to check database health status for API endpoints/frontend."""
```

**Returns comprehensive health information:**
```json
{
  "healthy": true,
  "database_path": "C:/path/to/okta_sync.db",
  "database_size_bytes": 1310720,
  "user_count": 324,
  "table_count": 13,
  "sql_available": true,
  "api_available": true,
  "recommendation": "SQL and API modes available"
}
```

## Usage Examples

### Frontend Integration
```python
# Force API-only mode from frontend
result = await manager.execute_query(
    "List all active users", 
    force_api_only=True
)
```

### Health Check for UI
```python
# Get database status for frontend display
health = manager.is_database_healthy()
if health["sql_available"]:
    show_sql_option()
else:
    disable_sql_option()
```

### User Query Examples
```python
# These automatically trigger API-only mode:
"List users without using SQL"
"Get user data - API calls only"
"Show me groups (no SQL please)"
```

## Decision Logic Flow

1. **Check Frontend Flag**: If `force_api_only=True` → Use API-only mode
2. **Parse User Query**: Look for explicit API-only phrases → Use API-only mode
3. **Database Health**: If DB unhealthy/empty → Use API-only mode
4. **Default**: Use both SQL and API modes (Planning Agent decides)

## Benefits

- **Graceful Degradation**: System continues working even if database is unavailable
- **User Control**: Frontend can force API-only mode for specific use cases
- **Intelligent Fallback**: Automatically detects and handles database issues
- **Clear Logging**: Full visibility into mode selection decisions
- **Backward Compatible**: Existing code continues to work without changes

## Testing

The feature has been thoroughly tested with:
- ✅ Database health checks with populated database (324 users)
- ✅ API-only mode detection from user queries
- ✅ Frontend force flag functionality
- ✅ Full query execution with API-only mode
- ✅ Planning Agent correctly generating API-only plans
- ✅ Complete workflow validation

## Production Ready

This feature is production-ready and provides robust handling of database availability scenarios while maintaining full backward compatibility with existing functionality.
