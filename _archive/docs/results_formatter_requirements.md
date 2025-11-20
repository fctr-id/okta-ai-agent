# Results Formatter Agent - Pattern-Based Polars Processing

## MAJOR ARCHITECTURE UPDATE (August 2025)

### 🚀 Revolutionary Multi-Agent Architecture v1.0

**BREAKING CHANGE**: Tako has been completely rebuilt with a sophisticated multi-agent architecture featuring advanced context engineering and intelligent data source selection.

**New Architecture Components**:
- **Planning Agent (PydanticAI)**: Natural language to structured ExecutionPlan conversion
- **Modern Execution Manager**: Workflow orchestration with Polars DataFrames  
- **SQL Agent**: Complex database relationships and joins
- **API Agent**: Real-time Okta API operations (107+ endpoints)
- **Results Formatter Agent**: Structured output processing

**Enhanced Context System**:
- **Automatic Variable Injection**: Previous step data flows seamlessly between agents
- **Enhanced Context Engineering**: Complete execution context with metadata and relationships
- **Multi-Step Processing**: Complex queries broken into coordinated, manageable steps

**Key Technical Improvements**:
- **302-Line Security Framework**: Comprehensive system prompt for secure code generation
- **Intelligent Endpoint Selection**: Smart dependency resolution with 107+ supported Okta GET endpoints
- **Polars DataFrames**: High-performance data operations replacing traditional SQL temp tables
- **Context-Aware Decision Making**: Automatic SQL vs API selection based on query requirements

---

## RECENT UPDATES (August 2025)

### ✅ Planning Agent Expand Parameter Optimization (COMPLETED)

**Issue**: Planning agent parameter hints contained expand parameters not available in our GET_ONLY.json endpoints
- **Problem**: Planning agent hints referenced expand parameters (scope, group) from full Postman collection but not available in our curated GET endpoints
- **Discovery**: Comprehensive analysis of GET_ONLY.json revealed exact expand parameters available in our 107 endpoints
- **Solution**: 
  - ✅ **Updated GET_ONLY.json**: Added missing expand documentation for `devices_list` (expand=user) and `yubikey_tokens_list` (expand for token details)
  - ✅ **Corrected Planning Hints**: Removed unavailable expand parameters (scope, group) and focused on documented ones
  - ✅ **Enhanced Documentation**: Updated all expand parameter hints with precise usage requirements

**Available Expand Parameters (GET_ONLY Endpoints)**:
- `application_list`: `expand=user/{userId}` (requires user.id filter)
- `application_get`: `expand=user/{userId}` (specific user assignment details)
- `application_user_list`: `expand=user` (full user objects)
- `group_list`: `expand=stats|app` (user counts or application details)
- `user_list`: `expand=classification` (user metadata)
- `user_get`: `expand=blocks|classification` (access blocks or classification)
- `user_list_roles`: `expand=targets/groups|targets/catalog/apps` (role targets)
- `devices_list`: `expand=user` (associated user details)
- `policy_get`: `expand=rules` (include all policy rules)
- `yubikey_tokens_list`: `expand` (additional token details)

**Impact**: Planning agent now provides accurate expand parameter efficiency hints based on actual available endpoints, improving API call optimization.

### ✅ System Prompt DateTime Modernization (COMPLETED)

**Issue**: API Code Generation Agent was using deprecated `datetime.utcnow()` causing warnings in generated code
- **Problem**: `datetime.utcnow()` is deprecated in Python 3.12+, generates warnings in execution logs
- **Solution**: Updated system prompt examples to use `datetime.now(datetime.UTC)` instead
- **Files Updated**: `src/core/agents/prompts/api_code_gen_agent_system_prompt.txt`
- **Impact**: Eliminates deprecation warnings in LLM-generated code, modern Python syntax

### ✅ Docker Modernization & API Client Fixes (COMPLETED)

**Docker Modernization**:
- ✅ **Python 3.13-slim**: Updated from Python 3.12 to latest 3.13-slim for better performance
- ✅ **Proper Image Tags**: Built with correct tags `fctrid/ai-agent-for-okta:0.6.6-beta` and `fctrid/ai-agent-for-okta:latest`
- ✅ **Legacy Cleanup**: Removed old AI service dependencies, created modern security modules
- ✅ **Security Modernization**: Exact Argon2 password hashing implementation from legacy code

**Critical API Client Fixes**:
- ✅ **Pagination Bug Fixed**: Discovered Okta sends multiple Link headers (`rel="self"` and `rel="next"`)
  - **Problem**: `response.headers.get('Link')` only returned first header
  - **Solution**: Changed to `', '.join(response.headers.getall('Link', []))` to capture all Link headers
  - **Result**: Pagination now works correctly (tested: 254 groups across 26 pages)

- ✅ **Rate Limiting Corrected**: Removed unnecessary exponential backoff multiplier
  - **Problem**: Code was applying 1.0x multiplier to Okta's Retry-After header values
  - **Solution**: Use exact Retry-After timing as Okta specifies (no multiplier needed)
  - **Result**: Log now shows "Waiting 60 seconds as specified by Okta Retry-After header"

**Validation Testing**:
- ✅ **Pagination Verified**: Successfully retrieved all 254 groups with automatic pagination
- ✅ **Rate Limiting Tested**: Triggered org-wide rate limit, verified proper 60-second wait and recovery
- ✅ **Production Ready**: Base Okta API client now fully functional with proper Okta behavior

**Impact**: All Okta API operations now work correctly with proper pagination and rate limiting compliance.

---

### ⚡ NEW: Universal Retry Strategy for All AI Agents

**Enhancement**: Implemented comprehensive retry strategy for ALL AI agents using centralized retry utilities module to handle rate limits consistently across the entire application.

**Architecture**:
```python
# Centralized retry utilities in src/utils/retry_utils.py
from src.utils.retry_utils import (
    create_planning_agent_retry,
    create_sql_agent_retry,
    create_api_agent_retry,
    create_api_sql_agent_retry,
    create_results_formatter_retry
)

# Usage in Modern Execution Manager:
planning_retry_decorator = create_planning_agent_retry(correlation_id, self.retry_callback)

@planning_retry_decorator
async def run_planning_with_retry():
    return await planning_agent.run(modified_query, deps=planning_deps)
```

**Implementation Benefits**:
- **Intelligent Rate Limit Handling**: Respects HTTP 429 Retry-After headers when present (especially for Anthropic)
- **Smart Fallback**: Uses exponential backoff (15s → 30s → 60s) when Retry-After headers are missing
- **Frontend Integration**: Real-time retry notifications via SSE streaming to frontend
- **Provider Agnostic**: Works with OpenAI, Anthropic, Vertex AI, and Bedrock
- **Modular Design**: Centralized retry logic in dedicated module instead of cluttering execution manager
- **Consistent Behavior**: All agents use identical retry timing and logic

**Applied To**: 
- ✅ Planning Agent (`planning_agent.run()`)
- ✅ SQL Agent (`generate_sql_query_with_logging()`)
- ✅ API Code Gen Agent (`generate_api_code()`)
- ✅ API-SQL Agent (`api_sql_code_gen_agent.process_api_data()`)
- ✅ Results Formatter Agent (`process_results_formatter()`)

**Integration Status**: ✅ **COMPLETE** - All retry decorators integrated into Modern Execution Manager

**Frontend Integration**:
- New SSE event type: `retry_status` with attempt number, wait time, and agent type
- Real-time user notifications: "Rate limit reached. Waiting 15 seconds before retry 1/3..."
- Seamless user experience during rate limit events

**Ready for Production**: System now handles rate limits gracefully with intelligent timing and user notifications!

### Key Improvements Made:

1. **Enhanced SQL+API Joining**: Added explicit guidance for LLM to recognize and join SQL+API data sources
2. **Pattern Selection Prompt Enhancement**: Updated prompt with SQL+API joining examples and decision criteria
3. **Left Join Pattern Emphasis**: Clarified when and how to use left_join for rich data display
4. **Enhanced Error Handling**: Added robust column validation to prevent `ColumnNotFoundError`
5. **Smart Dataframe Selection**: New pattern for intelligently selecting best available dataframe
6. **Improved Pattern Execution**: Added validation before executing each pattern step
7. **Better Prompt Engineering**: Updated LLM prompts with clearer instructions and examples
8. **Fallback Mechanisms**: Enhanced fallback logic when complex operations fail

### Critical Enhancement: Multi-Step Data Joining

**Problem Solved**: Queries showing incomplete data because multi-step execution results weren't being properly joined for complete data enrichment.

**Root Cause**: Results Formatter Agent in Sample Mode (≥1000 tokens) was not recognizing when to join related dataframes from different execution steps.

**Solution**: Enhanced pattern selection prompt with:
- **Multi-Step Data Recognition**: Generic criteria for detecting when dataframes have related data that should be joined
- **Left Join Examples**: Complete examples showing how to join any related datasets for data enrichment
- **Decision Criteria**: Clear guidance that ANY related dataframes should be joined for complete data display
- **Processing Strategy**: Updated strategy to detect related data patterns before choosing processing approach
- **No Entity Hardcoding**: Completely generic approach that works for ANY Okta entities

### Pattern Updates:

#### New Pattern: `smart_dataframe_selection`
```json
{
  "pattern": "smart_dataframe_selection",
  "params": {
    "preference_order": ["2_api_sql", "3_api", "1_api"],
    "required_fields": ["email", "okta_id"],
    "fallback_to_largest": true
  }
}
```

#### Enhanced Column Validation
- All `select_columns` operations now validate column existence before execution
- Joins validate both left and right key fields exist
- Array operations check for column presence before exploding

#### Error Recovery
- Pattern execution failures now fallback to simpler operations
- Missing columns are filtered out rather than causing failures
- Smart dataframe selection as fallback when complex joins fail

## Original Vision: Moving Away from Hardcoded Templates

We are completely redesigning the Results Formatter Agent to move from the current **rigid hardcoded template system** to a **flexible pattern-based Polars processing system**.

### Problems with Current Template System
1. **Hardcoded Templates**: Only supports 5 predefined templates (SIMPLE_TABLE, USER_LOOKUP, AGGREGATION, HIERARCHY, LIST_CONSOLIDATION)
2. **Rigid Field Mappings**: Cannot adapt to new entity types or field structures
3. **Entity-Specific Logic**: Hardcoded for users, groups, apps - cannot handle new Okta entities
4. **Limited Flexibility**: Cannot handle complex queries or custom data structures
5. **Maintenance Overhead**: Every new entity type requires code changes

## New Approach: Pattern-Based Polars Processing (Not Code Generation)

**IMPORTANT**: We will NOT ask LLMs to generate arbitrary Polars code due to version compatibility issues and unreliable syntax generation.

Instead, we use a **structured pattern-based approach**:
- **Pre-defined, tested Polars patterns** for common data operations
- **LLM selects appropriate pattern + provides parameters**
- **Safe execution of only validated patterns**

### Why This Approach?
1. **LLM Version Issues**: LLMs trained on older Polars versions generate outdated syntax
2. **Syntax Reliability**: Free code generation is unreliable for specific library syntax
3. **Security**: Pre-validated patterns are safer than arbitrary code execution
4. **Maintainability**: Easy to update patterns when Polars syntax changes

### Pattern-Based Architecture
```
1. Sample Data Input → LLM Analysis
2. LLM Selects → Pattern + Parameters (not code)
3. Pattern Engine → Executes validated Polars operations
4. Format Output → Vuetify Compatible JSON
```
        "params": ["left_key", "right_key"]
    },
    
    # List Processing
    "split_comma_list": {
        "template": "df.with_columns([pl.col('{field}').str.split(',').alias('{alias}')])",
        "safe": True,
        "params": ["field", "alias"]
    },
    
    # Array Processing - NEW PATTERNS FOR CERTIFICATE/NESTED DATA
    "explode_array_column": {
        "template": "df.explode('{array_column}')",
        "safe": True,
        "params": ["array_column"]
    },
    
    "extract_nested_field": {
        "template": "df.with_columns([pl.col('{json_column}').struct.field('{field_path}').alias('{alias}')])",
        "safe": True,
        "params": ["json_column", "field_path", "alias"]
    },
    
    "explode_and_extract": {
        "template": "df.explode('{array_column}').with_columns([expressions_for_field_extraction])",
        "safe": True,
        "params": ["array_column", "extract_fields"]
    },
    
    # Aggregation
    "group_and_aggregate": {
        "template": "df.group_by('{group_field}').agg([{aggregations}])",
        "safe": True,
        "params": ["group_field", "aggregations"]
    }
}
```

### LLM Task: Pattern Selection + Parameters
Instead of generating code, LLM returns:
```json
{
  "processing_plan": [
    {
      "pattern": "select_columns",
      "params": {
        "columns": ["pl.col('id').alias('user_id')", "pl.col('email')", "pl.col('name')"]
      }
    },
    {
      "pattern": "left_join", 
      "params": {
        "left_key": "user_id",
        "right_key": "id"
      }
    }
  ],
  "entity_type": "users",
  "display_fields": ["user_id", "email", "name", "applications"]
}
```

## Core Benefits

### 1. Entity-Agnostic Processing
✅ Works with any Okta entity without hardcoding  
✅ Handles new entities automatically  
✅ Processes any JSON structure  
✅ No code changes needed for new entity types  

### 2. Dynamic Adaptation
✅ LLM analyzes actual data structure and selects appropriate patterns  
✅ Smart field detection and mapping  
✅ Automatic relationship handling  
✅ Context-aware processing based on query intent  

### 3. Future-Proof Architecture
✅ New Okta entities work automatically  
✅ API changes handled gracefully  
✅ No maintenance overhead for new entity types  
✅ Scalable to any data structure  

## Technical Architecture

### Pattern-Based Processing Workflow
```
1. Sample Data Input → LLM Analysis
2. LLM Selects → Pattern + Parameters (not code)
3. Pattern Engine → Executes validated Polars operations
4. Format Output → Vuetify Compatible JSON
```

### Pattern Engine Execution
```python
def execute_polars_pattern(data: Dict[str, Any], processing_plan: List[Dict]) -> Dict[str, Any]:
    """Execute validated Polars patterns safely"""
    
    # Convert data to Polars DataFrames
    dataframes = {}
    for key, records in data.items():
        if records:
            dataframes[key] = pl.DataFrame(records)
    
    # Execute patterns in sequence
    result_df = None
    for step in processing_plan:
        pattern_name = step["pattern"]
        params = step["params"]
        
        if pattern_name in VALIDATED_PATTERNS:
            pattern = VALIDATED_PATTERNS[pattern_name]
            result_df = pattern.execute(dataframes, params)
    
    # Convert to Vuetify format
    return format_for_vuetify(result_df, processing_plan)
```

### Security & Reliability Benefits
- **No arbitrary code execution** - only pre-tested patterns
- **Version safe** - we control exact Polars syntax used
- **Easy updates** - change patterns in one place when Polars updates
- **Predictable behavior** - patterns are thoroughly tested
- **LLM focuses on logic** - not syntax generation

### Security Framework
- **Pattern Validation**: Execute only pre-validated Polars patterns
- **Parameter Sanitization**: Validate all LLM-provided parameters
- **Safe Operations**: No arbitrary code execution, only known patterns
- **Timeout Protection**: Prevent infinite loops or long-running operations
- **Resource Limits**: Memory and processing constraints

## Implementation Requirements

### 1. Enhanced LLM Prompt
Create a comprehensive prompt that can:
- Analyze any data structure automatically
- Select appropriate Polars processing patterns
- Handle missing/null values gracefully
- Create user-friendly field names
- Generate proper table headers
- Return Vuetify-compatible format

### 2. Secure Pattern Execution Framework
- **Pattern Library**: Pre-validated Polars operation patterns
- **Parameter Validation**: Sanitize all LLM-provided parameters
- **Resource Limits**: Memory and time constraints
- **Error Handling**: Robust fallback mechanisms
- **Logging**: Comprehensive execution logging

### 3. Entity Detection System
- **Automatic Detection**: Identify entity type from data structure
- **Smart Field Mapping**: Common patterns (id, name, email, status, etc.)
- **Relationship Handling**: Detect joins and aggregations needed
- **List Processing**: Handle array/list fields appropriately

## Output Format Specification

### Vuetify Data Table Compatible
```json
{
  "display_type": "table",
  "content": [
    {"user_id": "123", "email": "user@example.com", "applications": "App1, App2"},
    {"user_id": "456", "email": "user2@example.com", "applications": "App3"}
  ],
  "metadata": {
    "headers": [
      {"value": "user_id", "text": "User ID", "sortable": true},
      {"value": "email", "text": "Email Address", "sortable": true},
      {"value": "applications", "text": "Applications", "sortable": false}
    ],
    "total_records": 2,
    "processing_method": "pattern_based_polars",
    "entity_type": "users",
    "is_sample": false
  }
}
```

### Sample vs Complete Data Handling
- **is_sample=False**: Process complete datasets directly
- **is_sample=True**: Use intelligent sampling for large dataset preview
- **Consistent Format**: Same output structure regardless of mode

## Test Cases Required

### Multi-Entity Coverage
1. **Users**: Profile + applications + groups + roles
2. **Groups**: Members + applications + policies + compliance
3. **Applications**: Assignments + users + groups + usage stats
4. **Policies**: Rules + assignments + compliance status
5. **Devices**: Compliance + users + policies + status
6. **Custom Entities**: Any new Okta entity type

### Query Complexity
1. **Simple Queries**: "List all users"
2. **Join Queries**: "Users with their applications"
3. **Aggregation Queries**: "Group membership counts"
4. **Complex Queries**: "Users logged in last 30 days with risky app access"

### Data Scenarios
1. **Small Datasets**: < 100 records
2. **Large Datasets**: 1000+ records
3. **Missing Data**: Null/empty fields
4. **Complex Structures**: Nested objects, arrays
5. **Edge Cases**: Single records, empty results

## Implementation Phases

### Phase 1: Core Pattern System (Current)
- ✅ Create enhanced Polars pattern library
- ✅ Build secure pattern execution framework
- ✅ Implement entity-agnostic processing
- ✅ Add proper error handling and fallbacks

### Phase 2: Integration & Testing
- 🔄 End-to-end testing with real query data
- 🔄 Frontend integration validation
- 🔄 Performance testing with large datasets
- 🔄 Security audit of pattern execution

### Phase 3: Production Deployment
- 📋 Remove old template system dependencies
- 📋 Update documentation
- 📋 Monitor performance and accuracy
- 📋 Continuous improvement based on usage

## Success Metrics

### Technical Success
- ✅ Handles any Okta entity type without code changes
- ✅ Processes any JSON structure dynamically
- ✅ Returns Vuetify-compatible format consistently
- ✅ Maintains performance with large datasets
- ✅ Secure pattern execution with no vulnerabilities

### User Experience Success
- ✅ Frontend displays results correctly for all entity types
- ✅ Table headers are user-friendly and sortable
- ✅ Data is properly formatted and readable
- ✅ Fast response times even with complex queries
- ✅ Graceful error handling with meaningful messages

## Files to Update

### Core Implementation
- `src/core/agents/results_formatter_agent.py` - Replace with LLM-generated approach
- `src/core/agents/prompts/results_formatter_polars_template_prompt.txt` - Enhanced prompt

### Remove Dependencies
- Remove imports to `results_template_agent.py`
- Clean up hardcoded template logic
- Simplify codebase architecture

### Testing
- `src/data/testing/test_llm_polars_formatter.py` - Comprehensive test suite
- Test with multiple entity types and query scenarios

This approach will create a truly dynamic, maintainable, and future-proof Results Formatter Agent that can handle any Okta entity or query structure without requiring code changes.
