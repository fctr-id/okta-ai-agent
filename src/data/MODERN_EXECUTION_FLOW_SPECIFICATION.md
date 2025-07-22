# Modern Execution Manager - Complete Flow Specification

## 🎯 Executive Summary & Vision

### **Our Vision: Simplified AI Agent Orchestration**
Replace the complex 2000+ line `real_world_hybrid_executor.py` with a modern, simple 500-line step-walking orchestrator that trusts specialized AI agents to do their jobs while providing clear debugging and error handling.

### **Key Principles**
- **🧠 Trust the Agents**: Let Planning Agent make decisions, Executor just walks steps
- **🔄 Simple Flow**: Query → Plan → Execute Steps → Format Results  
- **🐛 Complete Debugging**: Log full records, complete code, JSON plans
- **⚡ Fail Fast**: Stop on step 1 failure to prevent wasted API calls
- **📊 Smart Sampling**: Pass small samples between steps for context

## 🏗️ System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     OKTA AI AGENT ARCHITECTURE                   │
├─────────────────────────────────────────────────────────────────┤
│  User Query: "Find users logged in last 7 days + their apps"    │
│                               │                                  │
│                               ▼                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │              MODERN EXECUTION MANAGER                        │ │
│  │           (Simple Step Walker - 500 lines)                  │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                               │                                  │
│                               ▼                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ PHASE 1: PLANNING AGENT                                     │ │
│  │ • Receives: User query + entities + SQL schema              │ │
│  │ • Generates: ExecutionPlan with ordered steps               │ │
│  │ • Output: [Step1: SQL users], [Step2: API apps/groups]     │ │
│  │          OR [Step1: API data], [Step2: SQL analysis]       │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                               │                                  │
│                               ▼                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ PHASE 2: STEP EXECUTION (For Loop)                         │ │
│  │                                                             │ │
│  │  Step 1 (SQL): User Query → SQL Agent → Execute → Sample   │ │
│  │       ▼                                                     │ │
│  │  Step 2 (API): Sample + Query → API Agent → Execute        │ │
│  │       ▼                                                     │ │
│  │  Step N: Continue pattern...                               │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                               │                                  │
│                               ▼                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ PHASE 3: RESULTS FORMATTING                                 │ │
│  │ • Small Data (≤200): Direct LLM formatting                 │ │
│  │ • Large Data (>200): Sample → Code → Process All           │ │
│  │ • Output: Formatted markdown/tables                        │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## 🔄 Complete 7-Step Execution Flow

### **Step 1: Query Reception**
```
User Input: "Find users logged in the last 7 days and fetch me their applications and groups"
↓
Modern Execution Manager: execute_query(query)
```

### **Step 2: Planning Phase** 
```
Planning Agent receives:
• Query: Natural language user request
• Dependencies: Available entities, SQL schema, endpoints
• Context: Flow ID for correlation

Planning Agent generates:
• ExecutionPlan with ordered steps
• Each step has: entity, tool_name, query_context, reasoning
• Example: [Step1: SQL users query], [Step2: API fetch apps/groups]
• OR: [Step1: API fetch all users], [Step2: SQL analyze patterns]
• Planning Agent decides optimal order based on query complexity
```

### **Step 3: Step Execution Loop**
```python
# Modern Executor walks through each step:
for i, step in enumerate(execution_plan.steps):
    if step.tool_name == "sql":
        # Execute SQL step
        result = await sql_agent.run(step.query_context, deps=sql_deps)
        sample = extract_sample(result)  # Get 2-3 records for next step
        
    elif step.tool_name == "api":  
        # Execute API step with context from previous step
        result = await api_code_gen_agent.run(step.query_context, deps=api_deps)
        # api_deps includes previous_sample for context
```

### **Step 4: Sample Passing**
```
After each step completion:
• Extract 2-3 sample records from step result
• Pass sample to next step as context
• Example: SQL returns 100 users → Extract 3 user samples → Pass to API step
• API step knows what user data looks like for better code generation
```

### **Step 5: Error Handling** ⚠️ **(PLANNED FEATURE)**
```
If Step 1 fails or returns zero results:
• Stop execution immediately  
• Return early error response
• Prevent wasted API calls
• Provide clear user feedback
```

### **Step 6: Results Collection**
```
All step results collected in ExecutionResults:
• step_results: List of all step outputs
• final_result: Last step's output  
• success metrics: total/successful/failed steps
• correlation_id: For debugging and tracing
```

### **Step 7: Results Formatting**
```
Results Formatter Agent processes all step outputs:

Small Dataset Strategy (≤200 records):
• Pass all data directly to LLM
• Generate formatted markdown/tables
• Direct processing without code generation

Large Dataset Strategy (>200 records):  
• Create intelligent samples from each step
• LLM generates processing code based on samples
• Execute code on full dataset
• Return both formatted results and processing code
```

## 🎯 Agent Responsibilities Matrix

| **Agent** | **Input** | **Output** | **Responsibility** |
|-----------|-----------|------------|-------------------|
| **Planning Agent** | User query + entities + schema | ExecutionPlan with steps | Decide SQL/API order, generate step descriptions |
| **SQL Agent** | SQL query context + previous sample | SQL query + explanation | Generate optimized SQL for database queries |
| **API Code Gen Agent** | API context + sample + endpoints | Python code + explanation | Generate API scripts with precise endpoint filtering |
| **Results Formatter** | All step results + query | Formatted output | Smart formatting based on dataset size |
| **Modern Executor** | User query | Complete results | Orchestrate all agents, handle errors, extract samples |

## 🏗️ Core Architecture

### **Modern Execution Manager**
- **File**: `src/data/modern_execution_manager.py`
- **Purpose**: Simple pass-through orchestrator that walks through planning agent steps
- **Philosophy**: Trust the agents to do their jobs. Just orchestrate the steps.

### **Modern Execution Manager**
- **File**: `src/data/modern_execution_manager.py`
- **Purpose**: Simple pass-through orchestrator that walks through planning agent steps
- **Philosophy**: Trust the agents to do their jobs. Just orchestrate the steps.

## 📋 Implementation Roadmap & Vision

### **🎯 What We've Built (COMPLETED)**
```
✅ Modern Execution Manager (500 lines)
   ├── execute_query() - Main entry point matching old executor interface
   ├── execute_steps() - Step walking orchestrator  
   ├── _execute_sql_step() - SQL Agent integration
   ├── _execute_api_step() - API Agent integration with precise endpoint filtering
   ├── _extract_sample() - Sample extraction for step context
   └── Error handling with correlation ID tracking

✅ All 4 Agents Standardized with PydanticAI
   ├── Planning Agent - ExecutionPlan generation
   ├── SQL Agent - Database query generation  
   ├── API Code Gen Agent - Python API script generation
   └── Results Formatter Agent - Smart formatting (small/large datasets)

✅ Complete Debug Logging System
   ├── JSON execution plans logged
   ├── Complete SQL queries logged
   ├── Full API scripts logged
   ├── Sample records logged (complete records, limited quantity)
   └── Correlation ID tracking throughout

✅ Endpoint Filtering Logic
   ├── Copied exact logic from old executor
   ├── _get_entity_operation_matches() 
   ├── _is_precise_match()
   └── Dynamic filtering from API JSON (no hardcoding)

✅ Results Formatter Integration  
   ├── process_results_structured() integration
   ├── Two-strategy processing (small vs large datasets)
   ├── Compatible output format with old executor
   └── Complete sample logging for debugging

✅ Test Validation
   ├── test_query_1.py successfully modernized
   ├── 100% success rate achieved
   ├── 7-step flow validated
   └── Same interface as RealWorldHybridExecutor
```

### **🚀 What's Next (PLANNED)**
```
⏳ Early Termination Feature
   ├── Step 1 failure detection
   ├── Zero results detection  
   ├── Early execution stop
   └── Prevent wasted API calls

⏳ Test Suite Modernization
   ├── test_query_2.py modernization
   ├── test_query_3.py modernization  
   ├── Multi-query test validation
   └── Performance comparison analysis

⏳ Advanced Error Handling
   ├── Retry logic for transient failures
   ├── Fallback strategies
   ├── Recovery workflows
   └── Enhanced user feedback

⏳ Performance Enhancements
   ├── Execution timing metrics
   ├── Token usage tracking
   ├── Memory optimization
   └── Parallel step execution (where safe)
```

### **🎯 Success Metrics We're Targeting**
```
Architecture Simplicity:
• 500 lines vs 2000+ lines (Old Executor)
• Clear separation of concerns
• No complex state management

Debugging Excellence:
• Complete record logging (not truncated)
• Full code generation visibility
• JSON plan transparency  
• Correlation ID tracing

Error Handling:
• Graceful step failure handling
• Early termination on critical failures
• Clear user error messages
• Detailed debugging information

Performance:
• Same or better success rates vs old executor
• Faster execution through simplified logic
• Reduced API calls via early termination
• Better resource utilization
```

## 🔧 Key Technical Decisions & Rationale

### **Why Simple Step Walking?**
```
Old Executor Problems:
❌ 2000+ lines of complex state management
❌ Hard to debug execution flow
❌ Complex phase-based logic
❌ Difficult to add new features

Our Solution:
✅ Simple for loop: for step in plan.steps
✅ Trust Planning Agent to make decisions
✅ Each agent handles its own domain
✅ Clear debugging with correlation IDs
```

### **Why Trust the Planning Agent?**
```
Design Philosophy:
• Planning Agent has full context (entities, schema, endpoints)
• Planning Agent makes smart SQL/API ordering decisions
• Planning Agent can choose: SQL→API, API→SQL, or even API-only flows
• Executor just walks the steps blindly (tool-agnostic)
• No second-guessing or validation layers

Benefits:
• Simplified executor logic
• Planning Agent can evolve independently  
• Clear separation of concerns
• Supports any step order/combination
• Easier to debug and maintain
```

### **Why Sample Passing Between Steps?**
```
Problem:
• API steps need context about SQL data structure
• Without samples, API Agent generates generic code
• Generic code often fails on real data

Solution:  
• Extract 2-3 sample records from each step
• Pass samples to next step as context
• API Agent sees actual data structure
• Generates precise, working code

Example Flow 1 (SQL→API):
SQL Step → Returns 100 users → Extract 3 samples
API Step → Receives samples → Knows user structure → Generates precise API code

Example Flow 2 (API→SQL):  
API Step → Returns user data → Extract 3 samples
SQL Step → Receives samples → Knows data structure → Generates precise SQL queries
```

### **Why Two Results Formatting Strategies?**
```
Small Dataset (≤200 records):
• Direct LLM processing
• Fast and simple
• Good for quick queries

Large Dataset (>200 records):
• Sample-based code generation
• Process full dataset programmatically
• Handle enterprise-scale data

Benefits:
• Scalable to any dataset size
• Efficient LLM usage
• Maintains quality for both scenarios
```

### **Why Copy Endpoint Filtering Logic?**
```
User Feedback: "Don't reinvent the wheel"

Action Taken:
• Copied exact _get_entity_operation_matches() logic
• Copied _is_precise_match() algorithm  
• Copied _semantic_operation_match() patterns
• Preserved all existing filtering behavior

Result:
• No regression in endpoint selection
• Proven logic maintained
• No hardcoded endpoints
• API JSON-driven filtering
```

### **Key Components**
1. **Planning Agent** (`planning_agent.py`) - Generates execution steps
2. **SQL Agent** (`sql_agent.py`) - Executes SQL queries  
3. **API Code Gen Agent** (`api_code_gen_agent.py`) - Generates Python API code
4. **Results Formatter Agent** (`results_formatter_agent.py`) - Formats final results

## Complete Execution Flow

### **Phase 1: Query Reception & Planning**
```
User Query → execute_query(query) → Planning Agent
```

1. **User asks a query** (natural language)
2. **Planning Agent generates steps** with SQL/API order decisions
   - Uses `planning_agent.run(query, deps=planning_deps)`
   - Receives planning dependencies (entities, SQL tables, etc.)
   - Returns `ExecutionPlan` with ordered steps

### **Phase 2: Step Execution**
```
Planning Steps → execute_steps() → Step Walker → Individual Agents
```

3. **Modern Executor takes steps and starts at step 1**
   - `execute_steps()` walks through `plan.steps` in order
   - Each step calls appropriate agent (SQL or API)

4. **Step Failure Handling** ⚠️ **(PLANNED - NOT YET IMPLEMENTED)**
   - If step 1 fails or has zero results → stop execution
   - This prevents wasted API calls and provides early feedback

5. **Sample Passing Between Steps**
   - After step 1 completes → extract sample via `_extract_sample()`
   - Pass sample + query to step 2 agent
   - Sample provides context for next step execution

6. **Repeat for All Steps**
   - Continue `for i, step in enumerate(plan.steps)` loop
   - Each step receives `previous_sample` from prior step
   - Build up execution context through the pipeline

### **Phase 3: Results Processing**
```
Step Results → Results Formatter Agent → Final Output
```

7. **Results Formatting with Two Strategies**:

   **a. Small Dataset (≤200 records)**
   - Pass all data to LLM 
   - Format as markdown or table
   - Direct processing without code generation

   **b. Large Dataset (>200 records)**
   - Take sample records from each step's output
   - Pass samples to LLM to generate processing code
   - Use generated code to process entire dataset
   - Return both sample results and processing code

## Agent Integration Details

### **Planning Agent Integration**
```python
# Create dependencies for Planning Agent
planning_deps = PlanningDependencies(
    available_entities=self.available_entities,
    entity_summary=self.entity_summary,
    sql_tables=self.sql_tables,
    flow_id=correlation_id
)

# Execute Planning Agent
planning_result = await planning_agent.run(query, deps=planning_deps)
execution_plan = planning_result.output.plan
```

### **SQL Agent Integration**
```python
# Create dependencies for SQL Agent
sql_deps = SQLDependencies(
    tenant_id="test_tenant",
    flow_id=correlation_id
)

# Execute SQL step
sql_result = await sql_agent.run(step.query_context, deps=sql_deps)
```

### **API Code Gen Agent Integration**
```python
# Get filtered endpoints for this specific step
available_endpoints = self._get_entity_endpoints_for_step(step)

# Create dependencies with precisely filtered endpoints
api_deps = ApiCodeGenDependencies(
    query=step.query_context,
    sql_data_sample=previous_sample,
    sql_record_count=len(previous_sample),
    available_endpoints=available_endpoints,  # Precisely filtered from API JSON
    entities_involved=[step.entity],
    step_description=step.reasoning,
    flow_id=correlation_id
)

# Execute API step
api_result = await api_code_gen_agent.run(step.query_context, deps=api_deps)
```

### **Results Formatter Integration**
```python
# Build step results for processing
step_results_for_processing = {}
for i, step_result in enumerate(execution_results.steps, 1):
    step_name = f"step_{i}_{step_result.step_type.lower()}"
    if step_result.success and step_result.result:
        if step_result.step_type == "SQL":
            sql_data = step_result.result.get('data', [])
            step_results_for_processing[step_name] = sql_data
        elif step_result.step_type == "API":
            api_data = step_result.result.get('stdout', '')
            step_results_for_processing[step_name] = [{'raw_output': api_data}]

# Call Results Formatter Agent
formatted_response = await process_results_structured(
    query=query,
    results=step_results_for_processing,
    original_plan=str(execution_plan.model_dump()),
    is_sample=False,
    metadata={'flow_id': correlation_id}
)
```

## Data Sampling Strategy

### **Sample Extraction Logic**
The `_extract_sample()` method in Modern Execution Manager:

```python
def _extract_sample(self, step_result: Any) -> Any:
    """Extract a small sample from step result for next step context"""
    
    # Handle list results - take first 3 items
    if isinstance(step_result, list):
        sample_size = min(3, len(step_result))
        return step_result[:sample_size] if sample_size > 0 else []
    
    # Handle dict results with nested data
    if isinstance(step_result, dict):
        # Check for common list keys
        for key in ['items', 'data', 'results', 'users', 'groups', 'applications']:
            if key in step_result and isinstance(step_result[key], list):
                sample_size = min(3, len(step_result[key]))
                return step_result[key][:sample_size] if sample_size > 0 else []
        
        # If no list found, return the dict as-is (single entity)
        return step_result
    
    # For other types, return as-is
    return step_result
```

### **Results Formatter Sampling**
For large datasets (>200 records), Results Formatter uses intelligent sampling:

```python
def _create_intelligent_samples(results, total_records):
    """Create intelligent samples from each step's output"""
    
    # Determine sample size based on total records
    if total_records <= 10:
        sample_size = total_records  # Send all if very small
    elif total_records <= 100:
        sample_size = min(10, total_records)  # Sample 10 records
    elif total_records <= 1000:
        sample_size = min(20, total_records)  # Sample 20 records  
    else:
        sample_size = min(50, total_records)  # Sample 50 records for large datasets
    
    # Take first few, last few, and some middle records for variety
    first_records = original_data[:sample_size//3]
    last_records = original_data[-sample_size//3:]
    middle_start = len(original_data) // 2 - (sample_size//3)//2
    middle_records = original_data[middle_start:middle_start + (sample_size//3)]
    
    return first_records + middle_records + last_records
```

## Debug Logging Strategy

### **Logging Principles**
1. **Quantity Control**: Log only 1-2 sample records (not full datasets)
2. **Quality Control**: Log complete records (not truncated fields)  
3. **Complete Code Logging**: Log full generated code/SQL for debugging
4. **Structured Information**: Log JSON plans, explanations, metadata

### **Planning Agent Logging**
```python
# Log complete execution plan for debugging
logger.debug(f"[{flow_id}] Generated execution plan: {result.output.plan.model_dump()}")
logger.debug(f"[{flow_id}] Plan confidence: {result.output.plan.confidence}%")
logger.debug(f"[{flow_id}] Plan entities: {result.output.plan.entities}")

# Log the complete JSON plan
complete_plan_json = json.dumps(result.output.plan.model_dump(), indent=2)
logger.debug(f"[{flow_id}] COMPLETE EXECUTION PLAN JSON:\n{complete_plan_json}")
```

### **SQL Agent Logging**
```python
# Log complete SQL query and explanation
logger.debug(f"[{flow_id}] Generated SQL: {result.output.sql}")
logger.debug(f"[{flow_id}] SQL Explanation: {result.output.explanation}")

# Enhanced logging for debugging
logger.debug(f"[{flow_id}] COMPLETE SQL QUERY:\n{result.output.sql}")
logger.debug(f"[{flow_id}] COMPLETE SQL EXPLANATION:\n{result.output.explanation}")
```

### **API Code Gen Agent Logging**
```python
# Log complete sample records (not truncated fields)
if sql_data_sample:
    logger.debug(f"[{correlation_id}] Complete SQL sample received (first 2 records): {sql_data_sample[:2]}")

# Log complete generated API script
logger.debug(f"[{correlation_id}] COMPLETE API SCRIPT GENERATED:\n{python_code}")
logger.debug(f"[{correlation_id}] COMPLETE API EXPLANATION:\n{code_output.explanation}")
logger.debug(f"[{correlation_id}] API SCRIPT REQUIREMENTS: {code_output.requirements}")
```

### **Results Formatter Agent Logging**
```python
# Log complete sample records for debugging
if sql_data:
    sample_record = sql_data[0]
    logger.debug(f"[{flow_id}] Sample SQL Record Keys: {list(sample_record.keys())}")
    logger.debug(f"[{flow_id}] Complete Sample SQL Record: {sample_record}")

# Log complete processing code if generated
if hasattr(result.data, 'processing_code') and result.data.processing_code:
    logger.debug(f"[{flow_id}] COMPLETE RESULTS FORMATTER PROCESSING CODE:\n{result.data.processing_code}")
```

## Endpoint Filtering Logic

### **Precise Endpoint Matching**
The Modern Execution Manager copies the exact filtering logic from the old executor:

```python
def _get_entity_endpoints_for_step(self, step: ExecutionStep) -> List[Dict[str, Any]]:
    """Get filtered endpoints for a specific API step (copied from old executor)"""
    entity = step.entity.lower()
    operation = getattr(step, 'operation', None) or 'list'
    operations = [operation.lower()]
    methods = ['GET']  # Default to GET for most operations
    
    return self._get_entity_operation_matches(entity, operations, methods)

def _is_precise_match(self, endpoint: Dict, target_entity: str, operations: List[str], methods: List[str]) -> bool:
    """Check if endpoint matches entity + operation + method criteria"""
    
    # 1. Method must match exactly
    endpoint_method = endpoint.get('method', '').upper()
    if endpoint_method not in methods:
        return False
    
    # 2. Entity must match exactly  
    endpoint_entity = endpoint.get('entity', '').lower()
    if endpoint_entity != target_entity.lower():
        return False
    
    # 3. Operation must match (with semantic flexibility)
    endpoint_operation = endpoint.get('operation', '').lower()
    if not self._operation_matches(endpoint_operation, operations):
        return False
    
    return True
```

## Error Handling Strategy

### **Step-Level Error Handling**
```python
class BasicErrorHandler:
    @staticmethod
    def handle_step_error(step: ExecutionStep, error: Exception, correlation_id: str, step_number: int) -> StepResult:
        """Handle individual step errors with simple logging"""
        error_msg = str(error)
        logger.error(f"[{correlation_id}] Step {step_number} ({step.tool_name}) failed: {error_msg}")
        
        return StepResult(
            step_number=step_number,
            step_type=step.tool_name,
            success=False,
            error=error_msg
        )
```

### **Execution-Level Error Handling**
```python
# Track success/failure during step execution
if result.success:
    successful_steps += 1
    sample = self._extract_sample(result.result)
    result.sample_extracted = sample
    previous_sample = sample
else:
    failed_steps += 1
    previous_sample = None  # No sample for failed steps
```

## Data Structures

### **StepResult Model**
```python
class StepResult(BaseModel):
    step_number: int
    step_type: str
    success: bool
    result: Any = None
    error: Optional[str] = None
    sample_extracted: Any = None
```

### **ExecutionResults Model**
```python
class ExecutionResults(BaseModel):
    steps: List[StepResult]
    final_result: Any = None
    correlation_id: str
    total_steps: int
    successful_steps: int
    failed_steps: int
```

### **Compatible Output Format**
The Modern Execution Manager returns results in the same format as the old executor:

```python
result = {
    'success': overall_success,
    'correlation_id': correlation_id,
    'query': query,
    'execution_plan': execution_plan.model_dump(),
    'step_results': [step.model_dump() for step in execution_results.steps],
    'final_result': execution_results.final_result,
    'total_steps': len(execution_results.steps),
    'successful_steps': successful_steps,
    'failed_steps': failed_steps,
    'success_rate': success_rate,
    'phase': 'completed',
    # Results formatter output (like old executor)
    'raw_results': raw_results,
    'processed_summary': formatted_response,
    'processing_method': 'results_formatter_structured_pydantic'
}
```

## Testing Interface

### **Main Entry Point**
```python
# Same interface as RealWorldHybridExecutor
result = await modern_executor.execute_query("Find users logged in the last 7 days and fetch me their applications and groups")
```

### **Success Criteria**
- `result['success']` = True/False
- `result['success_rate']` = percentage of successful steps  
- `result['total_steps']` = number of steps executed
- `result['processed_summary']` = formatted results from Results Formatter Agent

## Key Improvements Over Old Executor

### **Simplified Architecture**
- ✅ **500+ lines vs 2000+ lines** - Much simpler codebase
- ✅ **Clear step walking** - No complex state management
- ✅ **Trust agents** - Let each agent handle its domain

### **Better Error Handling**
- ✅ **Step-level failures** - Continue execution where possible
- ✅ **Detailed error logging** - Full correlation ID tracking
- ✅ **Graceful degradation** - Return partial results on failure

### **Enhanced Debugging**
- ✅ **Complete sample logging** - See full records for debugging
- ✅ **Code generation logging** - See all generated SQL/API code
- ✅ **JSON plan logging** - Understand planning decisions

### **Precise Endpoint Filtering**
- ✅ **Copied proven logic** - Uses exact same filtering as old executor
- ✅ **API JSON precision** - Filters endpoints from API specification
- ✅ **No hardcoding** - Dynamic endpoint selection

### **Results Formatting Integration**
- ✅ **Same Results Formatter** - Uses proven `process_results_structured`
- ✅ **Two-strategy processing** - Small datasets direct, large datasets with code
- ✅ **Compatible output** - Same format as old executor

## Implementation Status

### **✅ Completed**
- Modern Execution Manager with execute_query interface
- Planning Agent integration with proper dependencies
- SQL Agent integration with correlation ID support
- API Code Gen Agent integration with endpoint filtering
- Results Formatter Agent integration
- Sample extraction and passing between steps
- Debug logging for all agents
- Error handling and graceful degradation
- Test compatibility with existing test files

### **⏳ Planned (Not Yet Implemented)**
- Early termination on step 1 failure/zero results
- Advanced retry logic for transient failures
- Performance metrics and timing analysis
- Modernization of test_query_2 and test_query_3

### **🔄 Testing Status**
- ✅ test_query_1.py - Successfully modernized and tested (100% success rate)
- ⏳ test_query_2.py - Needs modernization
- ⏳ test_query_3.py - Needs modernization

This specification provides the complete blueprint for understanding and maintaining the Modern Execution Manager system.
