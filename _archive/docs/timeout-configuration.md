# Timeout Configuration for Okta AI Agent

## Overview

This document provides a comprehensive overview of all timeout configurations in the active Okta AI Agent flow, which consists of:

1. **Frontend**: `useRealtimeStream.js` - SSE streaming composable
2. **Backend**: `realtime_hybrid.py` - Realtime SSE router  
3. **Core Engine**: `modern_execution_manager.py` - Execution orchestrator

## Active Flow Architecture

```
Frontend (useRealtimeStream) → Realtime Hybrid → Modern Execution Manager
  Browser EventSource:        →    0.1s polling   →   Per-step timeouts:
  • 45-60s connection only                           • API: 180s per step
  • NO query execution timeout                       • SQL: 60s per step  
                                                     • Execution stops on first failure
```

## Timeout Configuration by Component

### 1. Modern Execution Manager (Core Engine)
**File**: `src/core/orchestration/modern_execution_manager.py`

#### API Execution Timeouts (Per Step)
```python
API_EXECUTION_TIMEOUT = 180           # 3 minutes PER API STEP - All API calls including system logs
SQL_EXECUTION_TIMEOUT = 60            # 1 minute PER SQL STEP - Database queries
```

**Important**: Each step gets its own timeout. System log operations now use the same 180s timeout as regular API calls. Execution stops on first failure.

#### Database Timeouts
```python
# Database connection and query timeouts are hardcoded for internal use
# Not exposed to users for configuration
```

#### Internal Timeouts (Not User Configurable)
```python
# HTTP and LLM timeouts are hardcoded for internal operations
# Not exposed in environment configuration
```

### 2. Base Okta API Client
**File**: `src/core/okta/client/base_okta_api_client.py`

#### HTTP Client Configuration
```python
def __init__(self, timeout: int = 300, max_pages: int = 100):
    self.timeout = timeout                # 5 minutes - Default HTTP request timeout

async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)):
    # Applied to all HTTP sessions
```

### 3. Realtime Hybrid Router
**File**: `src/api/routers/realtime_hybrid.py`

#### Event Processing Timeouts
```python
# SSE event queue polling for real-time updates
event = await asyncio.wait_for(step_status_queue.get(), timeout=0.1)
```

**Purpose**: Creates a tight 0.1-second polling loop for immediate SSE event processing while execution is running.

### 4. Frontend useRealtimeStream
**File**: `src/frontend/src/composables/useRealtimeStream.js`

#### UI Feedback Timeouts
```javascript
// Show finalizing step as active before completion
setTimeout(() => {
    // Complete finalizing step and set results
}, 500);  // 500ms delay

// Chunked streaming completion
setTimeout(() => {
    // Complete finalizing step for chunked results
}, 300);  // 300ms delay
```

#### EventSource Connection
```javascript
const eventSource = new EventSource(eventSourceUrl, {
    withCredentials: true
});
```

**Note**: Uses browser's native EventSource timeout behavior:
- Connection timeout: ~45-60 seconds (browser default for establishing connection)
- **Query execution timeout: NONE** - waits indefinitely for backend completion
- Automatic reconnection handling for connection failures
- **Critical**: Frontend relies entirely on backend per-step timeouts for execution control

## Timeout Hierarchy by Duration

### Short Timeouts (< 1 minute)
- **Event queue polling**: 0.1 seconds - Real-time SSE responsiveness
- **UI feedback delays**: 0.3-0.5 seconds - Smooth visual transitions  
- **Database connections**: 5-30 seconds - Fast failure for DB issues
- **HTTP requests**: 30 seconds - Individual API calls

### Medium Timeouts (1-5 minutes)
- **SQL execution**: 60 seconds **per SQL step** - Database query operations
- **LLM models**: 60 seconds - AI model HTTP client
- **API execution**: 180 seconds **per API step** - Standard API calls with pagination
- **Base HTTP client**: 300 seconds - Overall HTTP session timeout for individual requests
- **System logs**: 300 seconds **per system_log step** - Heavy system log queries

### Long Timeouts (> 5 minutes)
- **Frontend Query Execution**: **UNLIMITED** - useRealtimeStream has no query execution timeout
- **Multi-step execution**: Potentially unlimited if each step succeeds (each step gets its own timeout)
- **Theoretical maximum**: Sum of all step timeouts (e.g., 5 API steps = 5 × 180s = 900s = 15 minutes)

**Note**: The frontend will wait indefinitely for the backend to complete. Only individual backend steps have timeout limits.

## Per-Step Timeout Example

### Scenario: Multi-Step Execution with System Logs

```
Planning Agent generates (example):
Step 1: system_log (get audit logs)   → 300s timeout allocation
Step 2: SQL (analyze audit data)      → 60s timeout allocation  
Step 3: API (get related users)       → 180s timeout allocation
Step 4: API (get user groups)         → 180s timeout allocation
Step 5: API (get applications)        → 180s timeout allocation
```

### Execution Timeline

```
Step 1: system_log (audit) ✅ Completes in 240s (60s remaining unused)
Step 2: SQL (analysis)     ✅ Completes in 5s   (55s remaining unused)
Step 3: API (users)        ❌ TIMES OUT at 180s (due to 10k users + rate limiting)
Step 4: API (groups)       ⏸️ NEVER RUNS (execution stopped)
Step 5: API (apps)         ⏸️ NEVER RUNS (execution stopped)

Total execution time: 240s + 5s + 180s = 425 seconds (7+ minutes)
Frontend waits entire time without timeout
User sees error: "Step 3 timed out after 180 seconds"
```

### Key Behaviors

1. **Each step gets fresh timeout**: Step 3 gets full 180s despite previous steps
2. **Unused time doesn't accumulate**: Step 1's unused 60s doesn't help Step 3
3. **Execution stops on failure**: Steps 4 & 5 never execute after Step 3 fails
4. **Clear error reporting**: User knows exactly which step failed and why
5. **Frontend waits indefinitely**: useRealtimeStream has no query execution timeout
6. **Step order varies**: Planning agent determines which steps to generate based on query

## Timeout Reasoning

### Why These Values?

1. **System Log Queries (300s per step)**: Need 5 minutes due to:
   - Multiple paginated API calls to Okta system log endpoints
   - Large dataset processing (thousands of log entries)
   - Okta rate limiting delays and retry-after waits
   - **Only applies to steps with entity='system_log'**

2. **API Operations (180s per step)**: Each API step gets 3 minutes for:
   - Standard paginated API calls
   - Multiple endpoint orchestration within one step
   - Rate limit handling and retry delays
   - **Execution stops on first step failure**

3. **SQL Operations (60s per step)**: Each SQL step gets 1 minute for:
   - Local SQLite queries are fast
   - Polars DataFrame operations
   - Quick failure for issues

4. **HTTP Requests (30s)**: Need 30 seconds for:
   - Individual Okta API calls
   - Fast failure and retry logic
   - Network timeout handling

5. **Event Polling (0.1s)**: Need 0.1 seconds for:
   - Real-time SSE responsiveness during execution
   - Immediate UI updates as steps progress
   - Low CPU overhead while backend processes

6. **Frontend Query Execution (UNLIMITED)**: useRealtimeStream waits indefinitely because:
   - Complex queries can legitimately take 10+ minutes across multiple steps
   - Each backend step has its own timeout protection
   - Better user experience than arbitrary frontend timeouts
   - SSE connection auto-reconnects if network issues occur

## Error Handling & Timeout Recovery

### Timeout Error Types
- **HTTP Timeouts**: Return structured error with `TIMEOUT` error code
- **SQL Timeouts**: Database connection and query timeouts
- **Event Processing**: Graceful degradation with continued polling
- **EventSource**: Browser handles reconnection automatically

### Timeout Recovery Strategies
1. **HTTP**: Retry with exponential backoff (handled by Okta API client)
2. **Database**: Fast failure with immediate error reporting
3. **SSE**: Browser native reconnection for EventSource
4. **UI**: Visual feedback during timeout scenarios

## Configuration Environment Variables

Timeout configuration is available through the `.env.sample` file. See the "Timeout Configuration" section in that file for user-configurable timeout variables.

## Monitoring & Debugging

### Timeout-Related Logging
- **Modern Execution Manager**: Logs timeout errors with correlation IDs
- **Base API Client**: Logs HTTP timeout errors with endpoint details  
- **Realtime Hybrid**: Logs event processing timeouts
- **Frontend**: Console logs for connection errors and timeout scenarios

### Environment Variables That Affect Timeouts
- **API_EXECUTION_TIMEOUT**: Controls timeout for API operations including system logs (default: 180s)
- **SQL_EXECUTION_TIMEOUT**: Controls timeout for SQL operations (default: 60s)
- **OKTA_CONCURRENT_LIMIT**: Higher values may trigger rate limiting, affecting step completion times
- **LLM_RETRIES**: Affects total time for LLM operations (retries × internal LLM timeout)
- **VERIFY_SSL**: SSL verification adds small overhead to HTTP connections
- **LOG_LEVEL**: DEBUG logging adds small processing overhead

### Common Timeout Scenarios
1. **Large Dataset Queries**: May hit 180s API step timeout (now unified for all API operations)
2. **Network Issues**: Hit internal HTTP request timeout within a step  
3. **Database Problems**: Hit internal database timeouts or 60s SQL step timeout
4. **Browser Connection Issues**: EventSource connection timeout (~60s) for establishing SSE connection
5. **Multi-step Failures**: Execution stops at first failed step, remaining steps don't execute
6. **Long-running Queries**: Frontend waits indefinitely while backend processes steps sequentially

## Best Practices

1. **Per-Step Timeouts**: Each step gets its own timeout allocation for fair resource usage
2. **Fail-Fast Execution**: System stops at first failed step rather than continuing with bad data
3. **Unified API Timeouts**: All API operations (including system logs) use the same 180s timeout for consistency
4. **User Feedback**: UI shows progress during long operations with real-time step updates
5. **Graceful Degradation**: System provides clear error messages when steps timeout
6. **Logging**: All timeout scenarios are logged with correlation IDs for debugging

## Future Improvements

1. **Environment Variable Integration**: Timeouts could be made configurable via environment variables
2. **Adaptive Timeouts**: Dynamic timeout adjustment based on operation complexity
3. **Circuit Breakers**: Prevent cascade failures from timeout scenarios
4. **Metrics**: Timeout frequency and duration monitoring
