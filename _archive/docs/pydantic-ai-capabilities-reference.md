# Pydantic-AI Feature Checklist for Tako

**Purpose:** Quick reference - check before building custom code  
**Version:** Pydantic-AI 1.17.0

---

## ✅ Already Using

| Feature | What It Does | Where in Tako |
|---------|-------------|---------------|
| **Dependencies** | Share clients, config, circuit breakers across tools | `ReactAgentDependencies` in one_react_agent.py |
| **Message History** | Resume conversations, pass context between runs | Used in deferred tools pattern (documented) |
| **Union Output Types** | `output_type=[str, DeferredToolRequests]` | For approval workflow (documented) |

---

## 🔥 Should Use (High Value)

| Feature | Docs Link | Why Tako Needs It |
|---------|-----------|-------------------|
| **ModelRetry** | [Link](https://ai.pydantic.dev/tools-advanced/#tool-retries) | **Current:** Tools return `{"error": "Rate limited"}`<br>**Better:** `raise ModelRetry("Rate limited, try different endpoint")`<br>LLM gets guidance, knows to retry |
| **UsageLimits** | [Link](https://ai.pydantic.dev/agents/#usage-limits) | Cap tool calls per run: `UsageLimits(tool_calls_limit=25)`<br>Prevents runaway costs |
| **Deferred Tools (Approval)** | [Link](https://ai.pydantic.dev/deferred-tools/) | Documented in execution-manager-spec.md<br>Pause before WRITE operations |

---

## 🤔 Maybe Use (Medium Value)

| Feature | Docs Link | Use Case |
|---------|-----------|----------|
| **Dynamic Tools (prepare)** | [Link](https://ai.pydantic.dev/tools-advanced/#dynamic-tools) | Actually disable tools when circuit breaker trips<br>Currently: Track failures but tool still callable |
| **Sequential Execution** | [Link](https://ai.pydantic.dev/tools-advanced/#parallel-tool-calls-concurrency) | Mark WRITE tools with `sequential=True`<br>Only needed when approval workflow added |

---

## ❌ Don't Need

| Feature | Why NOT |
|---------|---------|
| **ToolReturn** | Hides data from LLM. Tako's ReAct needs to see full JSON probe responses to learn structure |
| **Graph Beta** | Static workflows. Tako needs dynamic reasoning (agent decides path based on discoveries) |
| **Streaming** | Token-by-token output. Tako generates complete code in one shot |
| **Custom Tool Schemas** | For legacy code. All Tako tools properly typed |
| **Multi-Agent** | Single ReAct agent handles everything |

---

---

## 📝 Quick Implementation Examples

### ModelRetry (Replace Error Returns)
```python
@agent.tool
async def execute_test_query(ctx: RunContext, code: str) -> dict:
    try:
        result = await execute_code(code)
        return result
    except RateLimitError:
        raise ModelRetry("Rate limited. Try filtering client-side or use different endpoint")
    except InvalidFilterError as e:
        raise ModelRetry(f"Filter syntax wrong: {e}. Use: field eq 'value' and field2 sw 'prefix'")
```

### UsageLimits (Cost Control)
```python
result = await agent.run(
    user_query,
    usage_limits=UsageLimits(tool_calls_limit=25)  # Stop after 25 tool calls
)
```

### Dynamic Tools (Enforce Circuit Breakers)
```python
async def enforce_circuit_breaker(ctx: RunContext, tool_def: ToolDefinition) -> ToolDefinition | None:
    if ctx.deps.api_circuit_breaker.attempts >= 20:
        return None  # Disable tool
    return tool_def

@agent.tool(prepare=enforce_circuit_breaker)
async def execute_test_query(ctx: RunContext, code: str) -> dict:
    ctx.deps.api_circuit_breaker.attempts += 1
    # ... execute
```

---

## 🔗 Full Docs

- Main: https://ai.pydantic.dev/
- Tools: https://ai.pydantic.dev/tools-advanced/
- Deferred: https://ai.pydantic.dev/deferred-tools/
- Testing: https://ai.pydantic.dev/testing/# Agent output type must include DeferredToolRequests
agent = Agent('openai:gpt-4', output_type=[str, DeferredToolRequests])

# First run - agent pauses when tool called
result = await agent.run("Delete all inactive users")
if isinstance(result.output, DeferredToolRequests):
    # Show approval UI to user
    for call in result.output.approvals:
        print(f"Approve: {call.tool_name}({call.args})?")

# After user approves
approval = DeferredToolResults()
approval.approvals[tool_call_id] = True  # or ToolDenied("reason")

# Resume from pause point
result = await agent.run(
    message_history=result.all_messages(),
    deferred_tool_results=approval
)
```

**Tako Use Cases:**
- ✅ Pause before executing SQL WRITE operations
- ✅ Pause before Okta API calls that modify data (user updates, group assignments)
- ✅ Show user exactly what will be executed + affected entities
- ✅ Resume execution only on approved entities

**Alternative Approaches:**
- `ctx.tool_call_approved` property - Check if already approved (for conditional approval)
- `raise ApprovalRequired()` - Conditionally require approval based on args/context
- `ToolApproved(override_args={...})` - Approve with modified arguments
- `ToolDenied("reason")` - Deny with custom message to LLM

**Status in Tako:** 📝 Documented in execution-manager-implementation-spec.md, not yet implemented

---

### 2. Dependencies (RunContext)

**Documentation:** https://ai.pydantic.dev/dependencies/

**What it does:**
- Type-safe dependency injection for sharing resources across tools
- Pass clients, connections, configuration to tools via `ctx.deps`
- Enable testing via `agent.override(deps=mock_deps)`

**How to use:**
```python
from dataclasses import dataclass
from pydantic_ai import Agent, RunContext

@dataclass
class AppDependencies:
    okta_client: OktaClient
    database: AsyncConnection
    circuit_breaker: CircuitBreaker
    config: Settings

agent = Agent('openai:gpt-4', deps_type=AppDependencies)

@agent.tool
async def query_users(ctx: RunContext[AppDependencies], filter: str) -> list:
    # Access dependencies via ctx.deps
    result = await ctx.deps.okta_client.list_users(filter=filter)
    return result
```

**Tako Use Cases:**
- ✅ Share Okta API client across tools
- ✅ Share SQLite connection across SQL tools
- ✅ Circuit breakers for rate limiting (SQL: 5, API: 20, Schema: 3)
- ✅ Configuration settings (API limits, timeouts)
- ✅ Mutable state (tracking tool call counts, data freshness)

**Status in Tako:** ✅ Implemented as `ReactAgentDependencies` in one_react_agent.py

---

### 3. Message History

**Documentation:** https://ai.pydantic.dev/message-history/

**What it does:**
- Access complete conversation history via `result.all_messages()`
- Resume conversations from specific points (deferred tools, multi-turn flows)
- Debug agent reasoning by inspecting message sequence

**How to use:**
```python
# First run
result = await agent.run("Show me all admin users")
messages = result.all_messages()

# Continue conversation
result2 = await agent.run(
    "Now remove their admin access",
    message_history=messages
)

# For deferred tools
result = await agent.run(
    message_history=paused_messages,
    deferred_tool_results=approval
)
```

**Tako Use Cases:**
- ✅ Resume agent after approval (continue from pause point)
- ✅ Multi-step queries (chain READ → analyze → WRITE operations)
- ✅ Debug agent reasoning (inspect tool calls, LLM responses)

**Status in Tako:** ✅ Used implicitly in agent.run() calls

---

### 4. Graph Beta (Static Workflows)

**Documentation:** https://ai.pydantic.dev/graph/beta/

**What it does:**
- Define static workflow graphs with predetermined nodes and edges
- Parallel execution of independent steps
- Conditional routing based on step outputs
- Use cases: ETL pipelines, multi-agent routing with fixed paths

**Why Tako DOESN'T use it:**
❌ Tako's ReAct pattern requires **dynamic reasoning loops**:
- Agent decides tool sequence based on intermediate results
- Emergent behavior (not predetermined paths)
- Adaptive intelligence (changes based on what it discovers)

Graph Beta would **kill Tako's core value**: intelligent query planning and adaptive execution.

**When to consider:**
- ✅ Fixed multi-step workflows (ETL, batch processing)
- ✅ Multi-agent orchestration with predetermined handoffs
- ❌ ReAct agents (dynamic reasoning)
- ❌ Exploratory queries (unknown path)

**Status in Tako:** ❌ Evaluated, determined NOT suitable

---

### 5. External Tools (Deferred Execution)

**Documentation:** https://ai.pydantic.dev/deferred-tools/#external-tool-execution

**What it does:**
- Execute tools outside the agent process (background workers, client-side)
- Return `DeferredToolRequests.calls` with tool call details
- Resume agent when results ready via `DeferredToolResults.calls`

**How to use:**
```python
@agent.tool
async def long_running_task(ctx: RunContext, query: str) -> str:
    # Schedule background task
    task_id = await schedule_background_job(ctx.tool_call_id, query)
    raise CallDeferred  # Tell agent to pause

# Later, when task completes
results = DeferredToolResults()
results.calls[tool_call_id] = task_result

result = await agent.run(
    message_history=original_messages,
    deferred_tool_results=results
)
```

**Tako Use Cases:**
- 🤔 Long-running Okta sync operations (thousands of users)
- 🤔 Async data refresh (re-fetch data while user reviews approval)
- 🤔 Client-side tool execution (frontend executes, reports back)

**Status in Tako:** 📝 Potential future use (not current priority)

---

### 6. Tool Retries & Error Handling

**Documentation:** https://ai.pydantic.dev/tools-advanced/#tool-retries

**What it does:**
- Automatic validation retry (LLM gets validation errors, tries again)
- `ModelRetry("reason")` - Trigger LLM retry with custom message
- Configurable retry limits per tool or agent-wide

**How to use:**
```python
from pydantic_ai import ModelRetry

@agent.tool
async def query_okta_api(ctx: RunContext, endpoint: str, method: str) -> dict:
    try:
        result = await ctx.deps.okta_client.request(method, endpoint)
        return result
    except RateLimitError as e:
        # Tell LLM to retry with different approach
        raise ModelRetry(
            f"Rate limited on {endpoint}. Try using a different endpoint "
            f"or filtering data client-side instead. Details: {e}"
        )
    except InvalidFilterError as e:
        # Validation passed but filter syntax wrong - guide LLM
        raise ModelRetry(
            f"Filter syntax invalid: {e}. "
            f"Okta filter format: field eq \"value\" and field2 sw \"prefix\""
        )
```

**Tako Use Cases:**
- ✅ Rate limit handling with alternative suggestions
- ✅ Invalid Okta filter syntax (guide LLM to fix)
- ✅ Transient network failures (auto-retry)
- ✅ SQL syntax errors (let LLM fix query)
- ✅ API endpoint not found (suggest alternatives)

**Key Insight:** 
`ModelRetry` is **better than returning error strings** because:
- LLM knows it should try again (not just report failure)
- You provide specific guidance on how to fix
- Respects retry limits (won't loop forever)
- Auto-generates RetryPromptPart in message history

**Status in Tako:** ✅ Circuit breakers implemented, ⚠️ ModelRetry should replace error returns

---

### 7. Dynamic Tools (Circuit Breaker Enforcement)

**Documentation:** https://ai.pydantic.dev/tools-advanced/#dynamic-tools

**What it does:**
- Per-tool `prepare` function - Conditionally disable tools based on state
- Agent-wide `prepare_tools` - Filter all tools globally
- Use case: Enforce circuit breakers (disable tool after N failures)

**How to use:**
```python
# Disable tool after circuit breaker trips
async def enforce_circuit_breaker(
    ctx: RunContext, tool_def: ToolDefinition
) -> ToolDefinition | None:
    if ctx.deps.api_circuit_breaker.attempts >= 20:
        return None  # Disable tool
    return tool_def

@agent.tool(prepare=enforce_circuit_breaker)
async def execute_test_query(ctx: RunContext, code: str) -> dict:
    ctx.deps.api_circuit_breaker.attempts += 1
    # Execute query
```

**Tako Use Cases:**
- ✅ **Circuit breaker enforcement** - Disable execute_test_query after 20 API failures
- ✅ **Rate limit protection** - Disable API tools when approaching limits
- ✅ **Schema freshness** - Disable schema tools if data too old (force refresh)

**Why Tako Needs This:**
Currently circuit breakers are tracked but not enforced. Tools keep getting called even after breaker trips. Dynamic tools would actually disable the tool.

**Status in Tako:** ❌ Not implemented, **MEDIUM VALUE** (nice-to-have for safety)

---

### 8. Parallel vs Sequential Tool Execution

**Documentation:** https://ai.pydantic.dev/tools-advanced/#parallel-tool-calls-concurrency

**What it does:**
- Default: Multiple tool calls run concurrently (asyncio.create_task)
- Force sequential: `@agent.tool(sequential=True)` for tools that must run in order
- Limit total calls: `UsageLimits(tool_calls_limit=N)`

**How to use:**
```python
# Force sequential for order-dependent operations
@agent.tool(sequential=True)
async def execute_write_query(ctx: RunContext, code: str) -> dict:
    """MUST run in order (writes depend on previous writes)"""
    return await execute_in_production(code)

# Or limit total tool calls per run
from pydantic_ai import UsageLimits
result = await agent.run(
    "Query",
    usage_limits=UsageLimits(tool_calls_limit=25)  # Cap at 25 tools
)
```

**Tako Use Cases:**
- ⚠️ **WRITE operations** - Would need sequential (if we add approval workflow)
- ✅ **Cost control** - Limit tool calls to prevent runaway costs
- ❌ **READ/probe operations** - Should stay parallel (independent, safe)

**Status in Tako:** ⚠️ Currently all parallel (fine for READ-only agent), would need for WRITE workflow

---

### 9. Structured Output Types (For Results Validation)

**Documentation:** https://ai.pydantic.dev/output/

**What it does:**
- Type-safe output validation via Pydantic models
- Union types for multiple possible outputs

**How to use:**
```python
from pydantic import BaseModel

# Validate final agent response structure
agent = Agent('openai:gpt-4', output_type=[str, DeferredToolRequests])

result = await agent.run("Find all admin users")
# Type-safe: result.output is either str or DeferredToolRequests
```

**Tako Use Cases:**
- ✅ Union types for deferred tools: `[str, DeferredToolRequests]`
- ✅ Validation (ensure LLM returns expected format)

**Status in Tako:** ✅ Already using for DeferredToolRequests union type

---

### 10. Testing & Mocking (Future)

**Documentation:** https://ai.pydantic.dev/testing/

**What it does:**
- Override dependencies for testing
- Mock LLM responses with TestModel
- Deterministic testing

**How to use:**
```python
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

# Mock dependencies
mock_deps = AppDependencies(
    okta_client=MockOktaClient(),
    database=MockDatabase()
)

# Mock LLM responses
test_model = TestModel(custom_result_text="Success")

# Test agent
with agent.override(deps=mock_deps, model=test_model):
    result = await agent.run("Test query")
```

**Tako Use Cases:**
- ✅ Unit test individual tools
- ✅ Integration test agent flows
- ✅ Test approval workflows without real LLM calls

**Status in Tako:** 🤔 Not yet implemented (manual testing only)

---

## 🚫 Features Tako Does NOT Need

### 1. Streaming Output
**Docs:** https://ai.pydantic.dev/agents/#streaming  
**Why not:** Tako generates code in one shot, no need for token-by-token streaming

### 2. Multi-Agent Patterns
**Docs:** https://ai.pydantic.dev/multi-agent-applications/  
**Why not:** Single ReAct agent handles all tasks (no specialized sub-agents)

### 3. Durable Execution (Temporal/DBOS)
**Docs:** https://ai.pydantic.dev/durable_execution/overview/  
**Why not:** Approval workflow provides sufficient durability (state stored in DB)

### 4. AG-UI / Vercel AI
**Docs:** https://ai.pydantic.dev/ui/overview/  
**Why not:** Custom React frontend already built

---

## 📋 Implementation Checklist

### ✅ Already Using
- [x] Dependencies (ReactAgentDependencies) - Share clients, circuit breakers across tools
- [x] Message History (implicit in agent.run) - Resume conversations, deferred tools
- [x] Union output types ([str, DeferredToolRequests]) - Handle approval workflow
- [x] Circuit breakers (via dependencies) - Track failures (not enforced yet)

### 🔥 High Priority (Should Implement)
- [ ] **ModelRetry** - Replace error returns with guided retries (rate limits, invalid filters)
  - Current: Tools return `{"error": "Rate limited"}` (LLM doesn't know to retry)
  - Better: `raise ModelRetry("Rate limited, try filtering client-side")`
- [ ] **UsageLimits** - Cap tool calls per run to prevent runaway costs
  - Example: `UsageLimits(tool_calls_limit=25)` stops at 25 tool executions
- [ ] **Deferred Tools - Human Approval** - Pause before WRITE operations (documented, not coded)

### 🤔 Medium Priority (Nice to Have)
- [ ] **Dynamic Tools (prepare)** - Actually disable tools when circuit breaker trips
  - Current: Circuit breakers track failures but tools still callable
  - Better: `prepare` function returns `None` to disable tool
- [ ] **Sequential writes** - Mark WRITE tools with `sequential=True` (when approval workflow added)

### 📝 Low Priority (Future)
- [ ] Testing framework (override deps, TestModel) - Unit test agent flows
- [ ] External Tools (CallDeferred) - Background job execution for slow operations

### ❌ Not Needed for Tako
- [x] **ToolReturn** - Separates LLM context from app data
  - Reason: Tako's ReAct agent NEEDS to see full JSON probe responses to learn structure
  - Use case it solves: Multimedia agents (screenshots), not JSON API exploration
- [x] **Custom tool schemas** - Wrap legacy functions with manual JSON schemas
  - Reason: All Tako tools are properly typed with Pydantic
- [x] **Graph Beta** - Static workflow orchestration
  - Reason: Kills Tako's dynamic reasoning (agent decides path based on discoveries)
- [x] **Streaming output** - Token-by-token output
  - Reason: Tako generates complete code in one shot
- [x] **Multi-agent patterns** - Multiple specialized sub-agents
  - Reason: Single ReAct agent handles all tasks
- [x] **Durable execution** (Temporal/DBOS) - Workflow persistence
  - Reason: Approval workflow + DB storage provides sufficient durability

---

## 🔗 Quick Links

- **Pydantic-AI Main Docs:** https://ai.pydantic.dev/
- **API Reference:** https://ai.pydantic.dev/api/agent/
- **Examples:** https://ai.pydantic.dev/examples/setup/
- **GitHub:** https://github.com/pydantic/pydantic-ai

---

## 📝 Usage Notes

**When adding new features:**
1. ✅ Check this document first
2. ✅ Search Pydantic-AI docs: https://ai.pydantic.dev/
3. ✅ Use native features when available
4. ⚠️ Only build custom if no native solution exists
5. 📝 Update this document with new discoveries

**When encountering issues:**
1. Check Pydantic-AI troubleshooting: https://ai.pydantic.dev/troubleshooting/
2. Review API changes: https://ai.pydantic.dev/changelog/
3. Test with latest version (currently 1.17.0)
