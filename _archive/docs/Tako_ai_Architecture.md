# Tako AI Agent: Complete Execution Flow
## From User Query to Final Results

This document explains the complete journey of a user query through Tako's multi-agent system, detailing each step, agent involvement, and data transformation.

---

## Table of Contents
1. [High-Level Architecture](#high-level-architecture)
2. [Detailed Execution Flow](#detailed-execution-flow)
3. [Agent Responsibilities](#agent-responsibilities)
4. [Data Flow & Context Management](#data-flow--context-management)
5. [Example Walkthrough](#example-walkthrough)
6. [Technical Implementation Details](#technical-implementation-details)

---

## High-Level Architecture

```
User Query
    ↓
Modern Execution Manager
    ↓
[Optional] Pre-Planning Agent (Thinking Phase)
    ↓
Planning Agent (Creates Execution Plan)
    ↓
Step Execution Loop
    ├─→ Cypher Code Gen Agent → Execute Query → Store Results
    └─→ API Code Gen Agent → Execute Python Code → Store Results
    ↓
Results Formatter Agent
    ↓
Streaming Response (SSE)
    ↓
User (Web UI)
```

**Sequential Flow:**
1. **Query Reception** → Modern Execution Manager
2. **Pre-Planning** (Optional) → Initial understanding
3. **Planning** → Generate step-by-step execution plan
4. **Step Execution** → For each step, call appropriate agent (Cypher or API)
5. **Results Formatting** → Transform raw data into user-friendly format
6. **Streaming** → Send results to frontend via Server-Sent Events

---

## Detailed Execution Flow

### Phase 1: Query Reception & Pre-Planning

**Entry Point:** `ModernExecutionManager.execute_plan_with_streaming()`

1. **User Query Arrives**
   - User submits natural language query via web UI
   - Query sent to backend API endpoint: `/api/realtime/hybrid/stream`
   - Correlation ID generated for tracking

2. **Pre-Planning Agent (Optional Thinking Phase)**
   - **Purpose:** Understand query complexity and approach
   - **Agent:** `pre_planning_agent` (not always triggered)
   - **Output:** Initial understanding of query requirements
   - **Prompt:** `preplan_agent_system_prompt.txt`

---

### Phase 2: Planning

**Component:** `planning_agent.py`
**Prompt:** `planning_agent_system_prompt.txt`

3. **Plan Generation**
   - **Input:**
     - User's natural language query
     - Available tools: `cypher`, `api`, `special_tool`
     - Entity metadata (users, groups, applications, etc.)
     - Simple API reference (lightweight endpoint list)
   
   - **Agent Configuration:**
     ```python
     planning_agent = Agent(
         model=ModelConfig.get_model(ModelType.REASONING),
         instructions=BASE_PLANNING_PROMPT,
         output_type=ExecutionPlan,
         deps_type=PlanningDependencies,
         retries=0
     )
     ```
   
   - **Processing:**
     - LLM analyzes query intent
     - Determines required entities (users, groups, apps, etc.)
     - Selects appropriate tools (cypher for GraphDB, api for real-time data)
     - Generates step-by-step execution plan
   
   - **Output Structure:**
     ```python
     ExecutionPlan:
       - steps: List[ExecutionStep]
         - tool_name: "cypher" | "api" | "special_tool"
         - entity: "users" | "groups" | "applications" | etc.
         - operation: "list" | "get" | "search" | etc.
         - parameters: Dict[str, Any]
         - query_context: str (what this step does)
         - critical: bool (must succeed for overall success)
         - reasoning: str (why this step is needed)
       - reasoning: str (overall plan explanation)
       - partial_success_acceptable: bool
     ```

   - **Event Emitted:** `PLAN-GENERATED` (SSE to frontend)

---

### Phase 3: Step Execution (The Core Loop)

**Component:** `ModernExecutionManager._execute_steps()`

For each step in the plan, the execution manager:

#### Step 3.1: Determine Tool Type

```python
if step.tool_name == "cypher":
    → Execute Cypher Query (GraphDB)
elif step.tool_name == "api":
    → Execute API Code Generation & Execution
elif step.tool_name == "special_tool":
    → Execute Special Tool (custom handlers)
```

---

### Phase 4A: Cypher Query Execution (GraphDB Path)

**Component:** `cypher_code_gen_agent.py`
**Prompt:** `cypher_code_gen_agent_system_prompt.txt`

4. **Cypher Code Generation**
   - **Agent:** `cypher_code_gen_agent`
   - **Model:** Uses `ModelType.CODING`
   
   - **Input Context:**
     ```python
     CypherGenDependencies:
       - query: str (user's original query)
       - entity: str (e.g., "users", "applications")
       - operation: str (e.g., "list", "search")
       - parameters: Dict[str, Any]
       - previous_step_data: Dict (data from prior steps)
       - step_number: int
       - total_steps: int
     ```
   
   - **Dynamic Instructions:**
     - Graph schema (nodes, relationships, properties)
     - Previous step results (for context)
     - Kuzu-specific syntax rules
     - Array search patterns (`any()`, `IN` operator)
     - Status filtering rules
   
   - **Agent Configuration:**
     ```python
     cypher_enrichment_agent = Agent(
         model=model,
         instructions=BASE_SYSTEM_PROMPT,  # Static rules
         output_type=CypherQueryOutput,
         deps_type=CypherGenDependencies,
         retries=0
     )
     
     @cypher_enrichment_agent.instructions
     def create_dynamic_instructions(ctx):
         # Injects graph schema, previous step data, etc.
     ```
   
   - **Output:**
     ```python
     CypherQueryOutput:
       - cypher_query: str (valid Kuzu Cypher)
       - explanation: str
       - expected_columns: List[str]
       - requires_union: bool
       - complexity: "simple" | "moderate" | "complex"
     ```

5. **Cypher Query Execution**
   - **Safety Validation:**
     ```python
     is_safe_cypher(cypher_query)
     # Checks: No CREATE, DELETE, SET, MERGE, DROP, ALTER
     # Only allows: MATCH, RETURN, WHERE, ORDER BY, LIMIT
     ```
   
   - **Execution:**
     ```python
     async with graph_db_manager.get_connection() as conn:
         result = await conn.execute(cypher_query)
         data = result.get_as_pl()  # Returns Polars DataFrame
     ```
   
   - **Data Storage:**
     ```python
     step_key = f"{step_number}_cypher"
     execution_data[step_key] = data  # Polars DataFrame
     
     # Store in metadata for next steps
     step_metadata[step_key] = {
         "type": "cypher",
         "query": cypher_query,
         "record_count": len(data),
         "context": explanation
     }
     ```
   
   - **Event Emitted:** `STEP-END` with progress and record count

---

### Phase 4B: API Code Execution (Real-time API Path)

**Component:** `api_code_gen_agent.py`
**Prompt:** `api_code_gen_agent_system_prompt.txt`

6. **API Endpoint Filtering**
   - **Input:** Full API reference (107+ GET endpoints)
   - **Filtering Logic:**
     ```python
     filtered = [
         ep for ep in full_api_data
         if ep['entity'] in step.entity
         and ep['operation'] == step.operation
     ]
     ```
   - **Output:** 1-5 relevant endpoints with full documentation

7. **API Code Generation**
   - **Agent:** `api_code_gen_agent`
   - **Model:** Uses `ModelType.CODING`
   
   - **Tools Available:**
     - `get_detailed_events_from_keys()`: For system log queries
       - Returns specific Okta event types from categories
       - Example: "user-authentication-session" → 20+ login event types
   
   - **Input Context:**
     ```python
     ApiCodeGenDependencies:
       - query: str
       - sql_record_count: int (from previous Cypher step)
       - available_endpoints: List[Dict]
       - entities_involved: List[str]
       - step_description: str
       - flow_id: str (correlation ID)
       - all_step_contexts: Dict (ALL previous step data)
     ```
   
   - **Dynamic Instructions:**
     ```python
     @api_code_gen_agent.instructions
     def create_dynamic_instructions(ctx):
         return f"""
         DYNAMIC CONTEXT:
         - Task: {step_description}
         - Previous Step Data: {all_step_contexts}
         - Available Endpoints: {available_endpoints}
         - Event Type Categories: {OKTA_EVENT_TYPES.keys()}
         
         WORKFLOW FOR SYSTEM LOGS:
         1. Select 1-3 relevant categories
         2. Call get_detailed_events_from_keys()
         3. Choose 5-15 most relevant event types
         4. Generate code with those events
         """
     ```
   
   - **Output:**
     ```python
     CodeGenerationOutput:
       - python_code: str (executable Python)
       - explanation: str
       - requirements: List[str]
       - estimated_execution_time: str
       - rate_limit_considerations: str
     ```

8. **Generated Code Structure**
   ```python
   # Generated code always follows this pattern:
   
   import os
   import requests
   from typing import List, Dict, Any
   
   # Environment variables
   OKTA_DOMAIN = os.getenv('OKTA_CLIENT_ORGURL')
   OKTA_TOKEN = os.getenv('OKTA_API_TOKEN')
   
   def execute() -> List[Dict[str, Any]]:
       # Access previous step data
       previous_data = execution_data.get('1_cypher', [])
       
       # API calls with limit=100 (mandatory)
       response = requests.get(
           f"{OKTA_DOMAIN}/api/v1/users",
           headers={"Authorization": f"SSWS {OKTA_TOKEN}"},
           params={"limit": 100}
       )
       
       # Pagination handling
       results = response.json()
       while 'next' in response.links:
           response = requests.get(response.links['next']['url'], ...)
           results.extend(response.json())
       
       return results
   
   # Execution
   result = execute()
   ```

9. **Code Safety Validation**
   ```python
   validate_generated_code(python_code)
   # Checks:
   # - No file system operations
   # - No subprocess/system calls
   # - No dangerous imports (eval, exec, compile)
   # - Only allowed HTTP methods (GET)
   # - Only whitelisted Okta endpoints
   ```

10. **Code Execution**
    ```python
    # Sandboxed execution with timeout
    process = await asyncio.create_subprocess_exec(
        sys.executable, '-c', python_code,
        env={
            'OKTA_CLIENT_ORGURL': settings.okta_client_orgurl,
            'OKTA_API_TOKEN': settings.okta_api_token,
            # ... other env vars
        },
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=API_EXECUTION_TIMEOUT  # 180 seconds
        )
        api_data = json.loads(stdout)
    except asyncio.TimeoutError:
        process.kill()
        raise TimeoutError("API execution exceeded timeout")
    ```

11. **Data Storage**
    ```python
    step_key = f"{step_number}_api"
    execution_data[step_key] = api_data  # List[Dict]
    
    step_metadata[step_key] = {
        "type": "api",
        "code": python_code,
        "record_count": len(api_data),
        "context": explanation
    }
    ```

---

### Phase 5: Results Formatting

**Component:** `results_formatter_agent.py`
**Prompts:** 
- `results_formatter_sample_data_prompt.txt` (for small datasets)
- `results_formatter_complete_data_prompt.txt` (for pattern-based formatting)

12. **Context Preparation**
    - **All Step Data Collected:**
      ```python
      all_step_contexts = {
          "1_cypher_data": [...],  # Full results
          "1_cypher_sample": [...],  # First 3 records
          "1_cypher_context": "Retrieved 150 users from GraphDB",
          "2_api_data": [...],
          "2_api_sample": [...],
          "2_api_context": "Fetched MFA factors for users"
      }
      ```

13. **Results Formatter Selection**
    - **Small Dataset (< 100 records):**
      - Uses `results_formatter_sample_data_prompt.txt`
      - Passes complete data to LLM
      - LLM formats each record individually
    
    - **Large Dataset (≥ 100 records):**
      - Uses `results_formatter_complete_data_prompt.txt`
      - Passes sample data (first 5 records)
      - LLM generates Polars transformation pattern
      - Pattern applied to full dataset (fast, deterministic)

14. **Results Formatter Execution**
    ```python
    # For small datasets
    result = await process_results_formatter(
        query=user_query,
        all_step_contexts=all_step_contexts,
        step_results=step_results,
        correlation_id=correlation_id,
        mode='sample_data'  # or 'complete_data'
    )
    
    # Output structure
    {
        "display_type": "table",
        "content": [...],  # List of formatted records
        "metadata": {
            "headers": [
                {"text": "User Name", "value": "user_name"},
                {"text": "Email", "value": "email"},
                ...
            ],
            "totalItems": 150,
            "execution_summary": "Retrieved 150 users with MFA details"
        }
    }
    ```

15. **Results Formatter Output**
    - **Table Format:**
      ```python
      {
          "display_type": "table",
          "content": [
              {
                  "user_name": "John Doe",
                  "email": "john.doe@company.com",
                  "status": "ACTIVE",
                  "groups": ["Admins", "Engineering"],
                  "applications": ["Slack", "Office365"]
              },
              ...
          ],
          "metadata": {
              "headers": [...],
              "data_source_type": "sql" | "hybrid" | "realtime",
              "last_sync": "2025-01-15T14:30:00Z"
          }
      }
      ```
    
    - **Markdown Format:**
      ```python
      {
          "display_type": "markdown",
          "content": "## Results\n\n1. **John Doe** ..."
      }
      ```

---

### Phase 6: Data Source Metadata & Streaming

16. **Data Source Type Determination**
    ```python
    # In realtime_hybrid.py
    used_sql = any(
        'SQL' in step.get('step_type', '').upper() or
        'CYPHER' in step.get('step_type', '').upper() or
        step.get('step_type', '').lower() == 'cypher'
        for step in step_results
    )
    used_api = any('API' in step.get('step_type', '').upper() 
                    for step in step_results)
    
    if used_sql and used_api:
        data_source_type = "hybrid"
    elif used_sql:
        data_source_type = "sql"
    else:
        data_source_type = "realtime"
    ```

17. **Last Sync Timestamp Retrieval**
    ```python
    if used_sql:
        sync_info = await get_last_sync_info_for_realtime()
        # Query: SELECT end_time FROM sync_history 
        #        WHERE tenant_id = ? AND success = 1 
        #        ORDER BY start_time DESC LIMIT 1
        
        last_sync_metadata = {
            "data_source_type": data_source_type,
            "last_sync": "2025-01-15T14:30:00.000000"
        }
    ```

18. **Response Streaming (SSE)**
    - **For Small Results (< 1000 records):**
      ```python
      # Single FINAL-RESULT event
      yield json.dumps({
          "type": "FINAL-RESULT",
          "content": {
              "formatted_response": {
                  "display_type": "table",
                  "content": [...],
                  "metadata": {
                      "data_source_type": "hybrid",
                      "last_sync": "2025-01-15T14:30:00Z",
                      ...
                  }
              }
          }
      })
      ```
    
    - **For Large Results (≥ 1000 records):**
      ```python
      # 1. METADATA event
      yield json.dumps({
          "type": "metadata",
          "content": {
              "total_batches": 5,
              "total_records": 5000,
              "display_type": "table",
              "base_data": {
                  "metadata": {
                      "headers": [...],
                      "data_source_type": "sql",
                      "last_sync": "..."
                  }
              }
          }
      })
      
      # 2. BATCH events (chunked)
      for batch in chunks:
          yield json.dumps({
              "type": "BATCH",
              "content": {
                  "formatted_response": {
                      "content": [...],  # 1000 records
                      "metadata": {"batch_number": 1}
                  }
              }
          })
      
      # 3. FINAL-RESULT event
      yield json.dumps({"type": "FINAL-RESULT", ...})
      ```

---

## Agent Responsibilities

### 1. Pre-Planning Agent (Optional)
- **File:** `src/core/agents/pre_planning_agent.py`
- **Prompt:** `preplan_agent_system_prompt.txt`
- **Purpose:** High-level query understanding
- **Input:** Raw user query
- **Output:** Initial approach thoughts
- **Model:** `ModelType.REASONING`

### 2. Planning Agent
- **File:** `src/core/agents/planning_agent.py`
- **Prompt:** `planning_agent_system_prompt.txt`
- **Purpose:** Break query into executable steps
- **Input:**
  - User query
  - Available tools (cypher, api, special_tool)
  - Entity metadata
  - Simple API reference
- **Output:** `ExecutionPlan` with steps
- **Model:** `ModelType.REASONING`
- **PydanticAI Features:**
  - Structured output validation (`ExecutionPlan`)
  - Dependency injection (`PlanningDependencies`)
  - Zero retries (cost optimization)

### 3. Cypher Code Generation Agent
- **File:** `src/core/agents/cypher_code_gen_agent.py`
- **Prompt:** `cypher_code_gen_agent_system_prompt.txt`
- **Purpose:** Generate safe, efficient Kuzu Cypher queries
- **Input:**
  - User query
  - Entity type
  - Operation type
  - Previous step data
- **Output:** `CypherQueryOutput` with validated query
- **Model:** `ModelType.CODING`
- **Key Rules:**
  - Read-only operations only (MATCH, RETURN, WHERE)
  - Use `any()` for array substring search
  - No default status filtering (unless user specifies)
  - UNION queries for app access (direct + group-based)
- **PydanticAI Features:**
  - Dynamic instructions with graph schema injection
  - Structured output (`CypherQueryOutput`)
  - Context from dependencies

### 4. API Code Generation Agent
- **File:** `src/core/agents/api_code_gen_agent.py`
- **Prompt:** `api_code_gen_agent_system_prompt.txt`
- **Purpose:** Generate executable Python code for Okta API calls
- **Input:**
  - User query
  - Filtered API endpoints (1-5 relevant)
  - Previous step data
  - Entity metadata
- **Output:** `CodeGenerationOutput` with Python code
- **Model:** `ModelType.CODING`
- **Key Rules:**
  - `limit=100` on ALL API calls (mandatory)
  - Use only provided endpoints
  - Handle pagination automatically
  - Validate HTTP methods (GET only)
- **PydanticAI Features:**
  - FunctionToolset for event type selection
  - Tool: `get_detailed_events_from_keys()`
  - Dynamic context injection
  - Structured output validation

### 5. Results Formatter Agent
- **File:** `src/core/agents/results_formatter_agent.py`
- **Prompts:**
  - `results_formatter_sample_data_prompt.txt`
  - `results_formatter_complete_data_prompt.txt`
- **Purpose:** Transform raw data into user-friendly format
- **Input:**
  - All step data
  - All step contexts
  - Original query
- **Output:** Formatted content with metadata
- **Model:** `ModelType.CODING`
- **Modes:**
  - **sample_data:** For < 100 records, formats all data
  - **complete_data:** For ≥ 100 records, generates Polars pattern
- **PydanticAI Features:**
  - Two-stage formatting (sample or pattern-based)
  - Dynamic context with all step results
  - Prevents hallucination with explicit rules

---

## Data Flow & Context Management

### Context Structure Throughout Execution

```python
# After Step 1 (Cypher)
all_step_contexts = {
    "1_cypher_data": pl.DataFrame([...]),  # Full Polars DataFrame
    "1_cypher_sample": [...],               # First 3 records as dicts
    "1_cypher_context": "Retrieved 150 active users from GraphDB",
    "1_cypher_query": "MATCH (u:User) WHERE ...",
    "1_cypher_record_count": 150
}

# After Step 2 (API)
all_step_contexts = {
    "1_cypher_data": pl.DataFrame([...]),
    "1_cypher_sample": [...],
    "1_cypher_context": "...",
    "2_api_data": [...],                    # List of API response dicts
    "2_api_sample": [...],                  # First 3 records
    "2_api_context": "Fetched MFA factors for 150 users",
    "2_api_code": "import requests\n...",
    "2_api_record_count": 150
}
```

### Step Metadata Storage

```python
step_metadata = {
    "1_cypher": {
        "type": "cypher",
        "query": "MATCH (u:User)...",
        "explanation": "Retrieve users from graph",
        "record_count": 150,
        "execution_time": 0.234,
        "context": "Retrieved 150 users"
    },
    "2_api": {
        "type": "api",
        "code": "import requests...",
        "explanation": "Fetch MFA factors",
        "record_count": 150,
        "execution_time": 45.2,
        "context": "Fetched MFA data"
    }
}
```

---

## Example Walkthrough

### User Query:
*"Find users in the group sso-super-admins and fetch all their groups and applications"*

### Step-by-Step Execution:

#### 1. Planning Phase
```json
{
  "steps": [
    {
      "tool_name": "cypher",
      "entity": "users",
      "operation": "list",
      "query_context": "Find users in group 'sso-super-admins' with their groups and applications",
      "critical": true,
      "reasoning": "GraphDB contains user-group-application relationships"
    }
  ],
  "reasoning": "Single Cypher query can retrieve all data from graph",
  "partial_success_acceptable": false
}
```

#### 2. Cypher Generation
**Generated Query:**
```cypher
MATCH (u:User)-[:MEMBER_OF]->(g:OktaGroup {name: 'sso-super-admins'})
OPTIONAL MATCH (u)-[:MEMBER_OF]->(allGroups:OktaGroup)
OPTIONAL MATCH (u)-[:HAS_ACCESS]->(directApps:Application)
OPTIONAL MATCH (u)-[:MEMBER_OF]->(:OktaGroup)-[:GROUP_HAS_ACCESS]->(groupApps:Application)
RETURN 
    u.okta_id,
    u.email,
    u.login,
    u.first_name,
    u.last_name,
    u.status,
    collect(DISTINCT allGroups.name) AS groups,
    collect(DISTINCT directApps.label) + collect(DISTINCT groupApps.label) AS applications
ORDER BY u.email
```

#### 3. Cypher Execution
**Results:** 2 users found
```python
[
    {
        "okta_id": "00u1...",
        "email": "admin1@company.com",
        "login": "admin1@company.com",
        "first_name": "John",
        "last_name": "Doe",
        "status": "ACTIVE",
        "groups": ["sso-super-admins", "IT-Team", "Admins"],
        "applications": ["Slack", "Office365", "AWS Console"]
    },
    {
        "okta_id": "00u2...",
        "email": "admin2@company.com",
        "login": "admin2@company.com",
        "first_name": "Jane",
        "last_name": "Smith",
        "status": "ACTIVE",
        "groups": ["sso-super-admins", "Engineering"],
        "applications": ["Slack", "GitHub"]
    }
]
```

#### 4. Results Formatting
**Input to Formatter:**
```python
all_step_contexts = {
    "1_cypher_data": pl.DataFrame([...]),
    "1_cypher_sample": [...],  # 2 records
    "1_cypher_context": "Found 2 users in group sso-super-admins"
}
```

**Formatted Output:**
```json
{
    "display_type": "table",
    "content": [
        {
            "User Name": "John Doe",
            "Email": "admin1@company.com",
            "Login": "admin1@company.com",
            "Status": "ACTIVE",
            "Groups": "sso-super-admins, IT-Team, Admins",
            "Applications": "Slack, Office365, AWS Console"
        },
        {
            "User Name": "Jane Smith",
            "Email": "admin2@company.com",
            "Login": "admin2@company.com",
            "Status": "ACTIVE",
            "Groups": "sso-super-admins, Engineering",
            "Applications": "Slack, GitHub"
        }
    ],
    "metadata": {
        "headers": [
            {"text": "User Name", "value": "user_name"},
            {"text": "Email", "value": "email"},
            {"text": "Login", "value": "login"},
            {"text": "Status", "value": "status"},
            {"text": "Groups", "value": "groups"},
            {"text": "Applications", "value": "applications"}
        ],
        "totalItems": 2,
        "data_source_type": "sql",
        "last_sync": "2025-01-15T14:30:00.000000",
        "execution_summary": "Found 2 users in group sso-super-admins with their groups and applications"
    }
}
```

#### 5. Frontend Display
**Web UI displays:**
- Table with 2 rows
- Download CSV button
- Sync info: "DB Last Updated: Jan 15, 2025, 2:30 PM"
- Search functionality
- Sortable columns

---

## Technical Implementation Details

### PydanticAI Integration

All agents use PydanticAI for:

1. **Structured Output Validation**
   ```python
   class CypherQueryOutput(BaseModel):
       cypher_query: str = Field(min_length=10)
       explanation: str
       expected_columns: List[str]
       requires_union: bool
       complexity: str
   ```

2. **Dependency Injection**
   ```python
   @dataclass
   class CypherGenDependencies:
       query: str
       entity: str
       operation: str
       previous_step_data: Dict[str, Any]
   
   agent = Agent(
       model=model,
       deps_type=CypherGenDependencies
   )
   ```

3. **Dynamic Instructions**
   ```python
   @agent.instructions
   def create_dynamic_instructions(ctx: RunContext[CypherGenDependencies]) -> str:
       deps = ctx.deps
       return f"Previous step data: {deps.previous_step_data}"
   ```

4. **Function Tools**
   ```python
   event_types_toolset = FunctionToolset()
   
   @event_types_toolset.tool
   def get_detailed_events_from_keys(category_keys: List[str]) -> Dict:
       return OKTA_EVENT_TYPES[category_keys]
   
   agent = Agent(
       toolsets=[event_types_toolset]
   )
   ```

### Security Validation Layers

1. **Cypher Query Validation:**
   ```python
   def is_safe_cypher(query: str) -> bool:
       forbidden = ['CREATE', 'DELETE', 'SET', 'MERGE', 'DROP', 'ALTER']
       return not any(word in query.upper() for word in forbidden)
   ```

2. **API Code Validation:**
   ```python
   def validate_generated_code(code: str) -> bool:
       # Check for dangerous operations
       forbidden_imports = ['subprocess', 'eval', 'exec', 'compile']
       forbidden_operations = ['open(', 'write(', 'system(']
       # ... validation logic
   ```

3. **HTTP Method Validation:**
   ```python
   def validate_http_method(method: str) -> bool:
       return method.upper() == 'GET'  # Only GET allowed
   ```

4. **Sandboxed Execution:**
   ```python
   # API code runs in subprocess with:
   # - Limited environment variables
   # - Timeout enforcement (180s)
   # - No file system access
   # - No network access except Okta API
   ```

### Performance Optimizations

1. **Polars DataFrames:**
   - In-memory columnar storage
   - 10-100x faster than Pandas for large datasets
   - Zero-copy operations

2. **Streaming Results:**
   - Chunked transmission for large datasets
   - Progress indicators
   - Memory-efficient

3. **Token Optimization:**
   - Sample data (first 3-5 records) instead of full datasets
   - Context summarization
   - 99% token reduction for large results

4. **Parallel Execution:**
   - Independent steps can run in parallel (future enhancement)
   - Async/await throughout

### Error Handling

1. **Step-Level Errors:**
   ```python
   try:
       result = await execute_step(step)
   except Exception as e:
       return StepResult(
           step_number=step_number,
           step_type=step.tool_name,
           success=False,
           error=str(e)
       )
   ```

2. **Partial Success:**
   ```python
   if plan.partial_success_acceptable:
       # Continue even if non-critical steps fail
   else:
       # Abort on first failure
   ```

3. **Timeout Handling:**
   ```python
   try:
       result = await asyncio.wait_for(
           execute_api_code(code),
           timeout=API_EXECUTION_TIMEOUT
       )
   except asyncio.TimeoutError:
       # Kill process, return error
   ```

---

## Key Takeaways

1. **Multi-Agent Coordination:** Each agent has a specific role - planning, code generation, or formatting

2. **Context Preservation:** All step data flows forward through `all_step_contexts`

3. **Safety First:** Multiple validation layers prevent dangerous operations

4. **Efficiency:** Polars DataFrames, streaming, token optimization

5. **Flexibility:** Supports GraphDB (Cypher) and real-time API data sources

6. **PydanticAI Benefits:**
   - Structured outputs
   - Dynamic context injection
   - Function tools
   - Type safety

7. **User Experience:** Real-time progress updates, streaming results, CSV downloads

---

**Document Version:** 1.0  
**Last Updated:** January 2025  
**Maintainer:** Tako Development Team
