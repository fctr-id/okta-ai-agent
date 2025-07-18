# PydanticAI Migration Specification

## Overview
Migrate from custom hybrid executor to PydanticAI agent delegation pattern while keeping existing executor functional for comparison and fallback.

## Migration Strategy: Incremental Approach

### Phase 1: Results Processing Agent (LLM3 Replacement)
**Goal**: Replace LLM3 results processing with a dedicated PydanticAI agent

**Implementation**:
- Create `ProcessingAgent` using PydanticAI
- Define structured output types for processed results
- Implement side-by-side comparison with existing LLM3
- Test with existing data from hybrid executor

**Files to create**:
- `src/agents/processing_agent.py` - New processing agent
- `src/agents/types.py` - Pydantic models for outputs
- `src/agents/test_processing_agent.py` - Unit tests
- `scripts/test_processing_comparison.py` - Side-by-side comparison

**Success criteria**:
- ProcessingAgent produces equivalent or better output than LLM3
- Structured output validation works
- Performance is comparable

### Phase 2: SQL Agent (Part of LLM2 Replacement)
**Goal**: Replace SQL generation/execution with specialized agent

**Implementation**:
- Create `SQLAgent` for SQL query generation and execution
- Define SQL-specific output types
- Integrate with existing database connections
- Test with current SQL patterns

**Files to create**:
- `src/agents/sql_agent.py` - SQL specialized agent
- `src/agents/test_sql_agent.py` - Unit tests
- Update `src/agents/types.py` - Add SQL output types

### Phase 3: API Agent (Part of LLM2 Replacement)
**Goal**: Replace API execution with specialized agent

**Implementation**:
- Create `APIAgent` for Okta API calls
- Integrate with existing endpoint filtering
- Define API-specific output types

**Files to create**:
- `src/agents/api_agent.py` - API specialized agent
- `src/agents/test_api_agent.py` - Unit tests

### Phase 4: Orchestrating Agent (LLM1 Replacement)
**Goal**: Replace LLM1 planning with PydanticAI orchestrating agent

**Implementation**:
- Create `OktaOrchestratorAgent` that delegates to specialized agents
- Implement tool delegation pattern
- Maintain compatibility with existing query patterns

**Files to create**:
- `src/agents/orchestrator_agent.py` - Main orchestrating agent
- `src/agents/test_orchestrator.py` - Integration tests

### Phase 5: New Executor
**Goal**: Create new PydanticAI-based executor alongside existing one

**Implementation**:
- Create `PydanticAIExecutor` that uses agent delegation
- Provide same interface as `RealWorldHybridExecutor`
- Allow easy switching between implementations

**Files to create**:
- `src/executors/pydantic_ai_executor.py` - New executor
- `scripts/executor_comparison.py` - Compare both executors

## Data Models

### Dependencies
```python
@dataclass
class OktaDeps:
    db_connection: DatabaseConn
    api_data: dict
    okta_config: dict
```

### Output Types
```python
class ProcessedResults(BaseModel):
    summary: str
    data_table: Optional[list[dict]]
    recommendations: list[str]
    export_format: str

class SQLResult(BaseModel):
    query: str
    results: list[dict]
    execution_time: float
    row_count: int

class APIResult(BaseModel):
    endpoints_called: list[str]
    combined_data: list[dict]
    total_records: int
    api_usage: dict
```

## Testing Strategy

### Unit Tests
- Each agent tested independently
- Mock dependencies for isolation
- Validate structured outputs

### Integration Tests
- End-to-end query testing
- Compare outputs with existing executor
- Performance benchmarking

### Comparison Scripts
- Side-by-side output comparison
- Performance metrics comparison
- Usage tracking validation

## Success Metrics

### Functional
- ✅ Output quality matches or exceeds current executor
- ✅ All existing query patterns work
- ✅ Error handling is robust
- ✅ Type safety is maintained

### Performance
- ✅ Response time within 20% of current executor
- ✅ Token usage is optimized
- ✅ Memory usage is reasonable

### Maintainability
- ✅ Code is cleaner and more modular
- ✅ Testing is easier and more comprehensive
- ✅ New features can be added easily

## Implementation Schedule

**Week 1**: Phase 1 - Processing Agent
**Week 2**: Phase 2 - SQL Agent  
**Week 3**: Phase 3 - API Agent
**Week 4**: Phase 4 - Orchestrator Agent
**Week 5**: Phase 5 - New Executor + Comparison

## Rollback Plan
- Keep existing hybrid executor functional
- Feature flag to switch between implementations
- Gradual migration per query type
- Easy fallback if issues arise
