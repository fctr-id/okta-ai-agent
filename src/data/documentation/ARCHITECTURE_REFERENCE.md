# OKTA AI AGENT - ARCHITECTURE REFERENCE

## 📋 QUICK REFERENCE - WHEN SOMETHING GOES WRONG

### 🔍 Where to Look Based on Issue Type:

| **Issue Type** | **Check These Files** | **Key Functions** |
|---|---|---|
| **Planning Problems** | `planning_agent.py`, `planning_agent_system_prompt.txt` | `planning_agent.run()` |
| **API Code Generation** | `api_code_gen_agent.py`, `api_code_gen_agent_system_prompt.txt` | `api_code_gen_agent.run()` |
| **API Code Execution Issues** | `modern_execution_manager.py` | `_execute_generated_code()`, `_generate_data_injection_code()` |
| **Python Syntax Errors in Generated Code** | `modern_execution_manager.py` | `_generate_data_injection_code()` - check `repr()` vs `json.dumps()` |
| **Data Injection Problems** | `modern_execution_manager.py` | `_generate_data_injection_code()` |
| **Variable Access in Generated Code** | API generated scripts | Check for `step_N_sample` variables availability |
| **SQL Generation** | `sql_agent.py`, `api_sql_agent.py`, `api_sql_agent_system_prompt.txt` | `generate_sql_query_with_logging()`, `api_sql_agent.process_api_data()` |
| **Step Execution Flow** | `modern_execution_manager.py` | `execute_query()`, `execute_steps()` |
| **Database Issues** | `modern_execution_manager.py` | `_execute_raw_sql_query()`, `_insert_api_data_into_temp_table()` |
| **Data Flow Issues** | `modern_execution_manager.py` | `_store_step_data()`, `_get_full_data_from_previous_step()`, `_get_all_previous_step_contexts_and_samples()` |
| **Enhanced Context Issues** | `modern_execution_manager.py` | `_get_all_previous_step_contexts_and_samples()` |
| **Temp Table Schema Problems** | `api_sql_agent.py` | `process_api_data()` with enhanced context |
| **Results Formatting** | `results_formatter_agent.py` | `results_formatter.run()`, `_estimate_token_count()` |
| **Token-Based Processing Decisions** | `results_formatter_agent.py` | `_estimate_token_count()` - check 5000 token threshold |
| **File Saving Issues** | `modern_execution_manager.py` | `_save_results_to_file()` - check string vs list content handling |
| **Future Custom Tools** | `modern_execution_manager.py` | Look for placeholder in `execute_steps()` elif block |

---

## 🏗️ ARCHITECTURE OVERVIEW

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   USER QUERY    │ -> │ PLANNING AGENT  │ -> │ EXECUTION PLAN  │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                                        │
                                                        v
┌─────────────────────────────────────────────────────────────────┐
│                  MODERN EXECUTION MANAGER                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │ API STEP    │  │  SQL STEP   │  │ API STEP    │   (repeat) │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
└─────────────────────────────────────────────────────────────────┘
                                │
                                v
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ RESULTS FORMAT  │ <- │ COLLECTED DATA  │ <- │ STEP RESULTS    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

---

## 📁 FILE-BY-FILE BREAKDOWN

### 🎯 **modern_execution_manager.py** - MAIN ORCHESTRATOR
**Purpose**: Central execution engine that coordinates all agents and manages data flow

**Key Classes:**
- `ModernExecutionManager` - Main orchestrator class

**Critical Functions:**
- `execute_query(query)` - **ENTRY POINT** - Main execution function
- `execute_steps(steps, correlation_id)` - Executes individual steps in sequence
- `_execute_api_step(step, correlation_id, step_number)` - Handles API code generation and execution
- `_execute_sql_step(step, correlation_id, step_number)` - Handles SQL query execution
- `_execute_api_sql_step(step, correlation_id, step_number)` - Handles API-SQL processing

**Data Management Functions:**
- `_store_step_data(step_number, step_type, data, metadata)` - Stores results from each step
- `_get_full_data_from_previous_step(step_number)` - Retrieves complete data from previous step
- `_get_all_previous_step_contexts_and_samples()` - **ENHANCED** - Gets all previous step contexts and samples for enhanced LLM decision-making

**Code Execution Functions:** ⭐ **NEW**
- `_execute_generated_code(python_code, correlation_id, step, current_step_number)` - Executes API code with data injection
- `_generate_data_injection_code(current_step_number, correlation_id)` - **CRITICAL** - Injects previous step data as variables for generated code access

**Database Functions:**
- `_execute_raw_sql_query(sql_query, correlation_id)` - Executes SQL with async/WAL mode
- `_insert_api_data_into_temp_table(api_data, correlation_id)` - Inserts API data into temp tables
- `_cleanup_temp_table(correlation_id)` - Cleans up temporary tables

**File Management Functions:** ⭐ **NEW**
- `_save_results_to_file(formatted_response, raw_step_data, query, correlation_id)` - Saves query results and raw data to files

**Data Storage:**
- `self.data_variables` - Stores full datasets: `{"api_data_step_1": [data], "sql_data_step_2": [data]}`
- `self.step_metadata` - Stores metadata about each step including context and samples

**Enhanced Context System:**
- **ALL agents now receive complete workflow history** for intelligent decision-making
- Context includes: previous step contexts, data samples, and metadata
- Enables LLMs to make smart decisions about data types, temp table schemas, and processing logic

**Data Injection Architecture:** ⭐ **NEW CRITICAL FEATURE**
- **Problem Solved**: API generated code couldn't access previous step data during execution
- **Solution**: Dynamic variable injection using `repr()` for Python-compatible serialization
- **Key Fix**: Uses `repr(data)` instead of `json.dumps(data)` to avoid `null` vs `None` syntax errors
- **Benefit**: Generated code can directly access `step_2_sample`, `step_3_sample`, etc. during runtime
- **Python Compatibility**: Ensures `None`, `True`, `False` instead of JSON `null`, `true`, `false`
- **Extensibility**: Works automatically for any new code-generating tools (Python scripts, ML pipelines, etc.)

---

### 🧠 **planning_agent.py** - QUERY DECOMPOSER
**Purpose**: Analyzes user queries and creates execution plans

**Key Classes:**
- `PlanningAgentDependencies` - Input structure
- `PlanStep` - Individual step definition  
- `ExecutionPlan` - Complete plan structure

**Critical Functions:**
- `planning_agent.run(query, deps)` - **MAIN FUNCTION** - Generates execution plan
- `load_planning_agent_system_prompt()` - Loads system prompt

**Input**: User query string
**Output**: ExecutionPlan with list of PlanStep objects

---

### 🔧 **api_code_gen_agent.py** - API CODE GENERATOR
**Purpose**: Generates Python code for Okta API calls

**Key Classes:**
- `ApiCodeGenDependencies` - Input dependencies with enhanced context support
- `CodeGenerationOutput` - Generated code output

**Critical Functions:**
- `api_code_gen_agent.run(context, deps)` - **MAIN FUNCTION** - Generates API code with enhanced context awareness
- `load_api_code_gen_agent_system_prompt()` - Loads system prompt

**Input**: Query context + available API endpoints + **all previous step contexts and samples**
**Output**: Executable Python code as string

**Enhanced Context Features:**
- Receives complete workflow history for intelligent code generation
- Can make smart decisions based on previous step data types and structures
- System prompt updated to inform LLM about enhanced context capabilities
- **NEW**: System prompt includes explicit instructions for accessing injected variables (`step_N_sample`)

**Data Injection Integration:** ⭐ **NEW CRITICAL FEATURE**
- Generated code automatically has access to `step_1_sample`, `step_2_sample`, etc. variables
- No need for hardcoded data assumptions - code can directly reference previous step data
- Enables complex multi-step API workflows where each step builds on previous data
- Example: `user_ids = [record['user_okta_id'] for record in step_2_sample]`

---

### 🗃️ **sql_agent.py** - SQL QUERY GENERATOR  
**Purpose**: Generates SQL queries for database operations

**Key Classes:**
- `SQLDependencies` - Input dependencies
- `SQLAgentOutput` - Generated SQL output

**Critical Functions:**
- `generate_sql_query_with_logging(question, tenant_id, include_deleted, flow_id, all_step_contexts)` - **MAIN FUNCTION** with enhanced context support
- `sql_agent.run(question, deps)` - Core SQL generation
- `load_sql_agent_system_prompt()` - Loads system prompt

**Input**: Natural language question + **all previous step contexts and samples**
**Output**: SQL query string + explanation

**Enhanced Context Features:**
- Receives complete workflow history for context-aware SQL generation
- Can reference data from previous steps when generating queries
- System prompt updated to inform LLM about enhanced context capabilities

---

### 🔄 **api_sql_agent.py** - API-TO-SQL BRIDGE
**Purpose**: Processes API data against SQL database using temp tables with intelligent schema decisions

**Key Classes:**
- `ApiSqlDependencies` - Input dependencies (flexible data types) with enhanced context support
- `ApiSqlOutput` - Generated SQL output

**Critical Functions:**
- `process_api_data(api_data, processing_context, correlation_id, use_temp_table, all_step_contexts)` - **MAIN FUNCTION** with enhanced context
- `load_api_sql_agent_system_prompt()` - Loads system prompt

**Input**: API data (any format) + processing context + **all previous step contexts and samples**
**Output**: Temp table schema + processing query

**Enhanced Context Features:**
- Receives complete workflow history for intelligent temp table schema decisions
- Can analyze actual data types from previous steps to create compatible schemas
- Makes smart decisions about data type handling and temp table structure
- System prompt updated to inform LLM about enhanced context and intelligent decision-making

---

### 📊 **results_formatter_agent.py** - RESULTS PRESENTER
**Purpose**: Formats final results for user presentation with intelligent token-based processing decisions

**Key Classes:**
- `ResultsFormatterDependencies` - Input dependencies
- `FormattedResults` - Output structure

**Critical Functions:**
- `results_formatter.run(context, deps)` - **MAIN FUNCTION** - Formats results
- `_estimate_token_count(data)` - **NEW** - Estimates LLM token count for processing decisions
- `load_results_formatter_system_prompt()` - Loads system prompt

**Token-Based Processing Logic:** ⭐ **NEW CRITICAL FEATURE**
```python
estimated_tokens = _estimate_token_count(results)
token_threshold = 5000  # Conservative threshold for LLM context limits

if estimated_tokens <= token_threshold:
    # Small dataset - direct LLM processing
    return await _process_complete_data(...)
else:
    # Large dataset - sampling and code generation
    return await _process_sample_data(...)
```

**Input**: Raw data + query context + execution plan
**Output**: Formatted markdown response OR generated processing code

**Intelligence Improvements:**
- **Token Estimation**: ~4 characters = 1 token (JSON string length / 4)
- **Smart Threshold**: 5,000 tokens (~3,750 words) for optimal LLM performance
- **Content-Aware**: Considers actual data complexity, not just record count
- **Performance**: Avoids LLM context overflow with large datasets like 250+ groups

**File Output Features:** ⭐ **UPDATED**
- Automatically saves formatted results to `src/data/results/` directory
- Generates both formatted results and raw step data files
- Files include timestamp and correlation ID for easy tracking
- JSON format for structured data access, markdown summaries for human readability
- **Fixed**: Handles both string content (code generation) and list content (direct processing)

---

## 🔄 DATA FLOW DIAGRAM

```
USER QUERY
    │
    v
┌───────────────────────────────────────────────────────────────┐
│ PLANNING AGENT                                                │
│ Input: "find users who logged in last 7 days"                │
│ Output: [API step, SQL step, API step]                       │
└───────────────────────────────────────────────────────────────┘
    │
    v
┌───────────────────────────────────────────────────────────────┐
│ MODERN EXECUTION MANAGER - ENHANCED CONTEXT SYSTEM           │
│                                                               │
│ Step 1: API STEP                                             │
│ ┌─────────────────────────────────────────────────────────┐   │
│ │ API CODE GEN AGENT                                      │   │
│ │ Input: "get login events" + enhanced_context={}         │   │
│ │ Output: Python code                                     │   │
│ └─────────────────────────────────────────────────────────┘   │
│ ↓ Execute Python code + Store context & sample             │
│ data_variables["api_data_step_1"] = ["user1", "user2", ...]  │
│ step_metadata["step_1"] = {context: "...", sample: [...]}   │
│                                                               │
│ Step 2: API-SQL STEP                                         │
│ ┌─────────────────────────────────────────────────────────┐   │
│ │ API-SQL AGENT                                           │   │
│ │ Input: ["user1", "user2"] + "find apps"                │   │
│ │ + enhanced_context={step_1_context, step_1_sample}     │   │
│ │ Output: INTELLIGENT temp table schema + SQL            │   │
│ └─────────────────────────────────────────────────────────┘   │
│ ↓ Execute SQL with smart schema + Store context & sample   │
│ data_variables["api_sql_data_step_2"] = [{user, apps}]     │
│                                                               │
│ Step 3: API STEP                                             │
│ ┌─────────────────────────────────────────────────────────┐   │
│ │ API CODE GEN AGENT                                      │   │
│ │ Input: "get roles" + enhanced_context={step_1_context,  │   │
│ │        step_1_sample, step_2_context, step_2_sample}   │   │
│ │ Output: CONTEXT-AWARE Python code                      │   │
│ └─────────────────────────────────────────────────────────┘   │
│ ↓ ⭐ DATA INJECTION + Execute with full workflow awareness │
│ ┌─────────────────────────────────────────────────────────┐   │
│ │ EXECUTION ENVIRONMENT                                   │   │
│ │ • step_1_sample = ["user1", "user2"] (injected)        │   │
│ │ • step_2_sample = [{"user_okta_id": "user1", ...}]     │   │
│ │ • Generated code can access: step_2_sample directly    │   │
│ │ • Example: user_ids = [r['user_okta_id'] for r in      │   │
│ │            step_2_sample]                               │   │
│ └─────────────────────────────────────────────────────────┘   │
│ data_variables["api_data_step_3"] = [{user, roles, ...}]     │
└───────────────────────────────────────────────────────────────┘
    │
    v
┌───────────────────────────────────────────────────────────────┐
│ RESULTS FORMATTER AGENT                                       │
│ ✅ **CORRECTED**: Token-based processing with 5000 token threshold │
│ Input: All raw step data + original query + original plan           │
│ Logic: ≤5000 tokens = send complete data to LLM                     │
│        >5000 tokens = create samples and generate processing code   │
│ Output: Formatted markdown response OR executable processing code    │
│ Note: Does NOT need enhanced context - processes final data         │
└───────────────────────────────────────────────────────────────┘
    │
    v  
┌───────────────────────────────────────────────────────────────┐
│ ⭐ FILE PERSISTENCE SYSTEM (NEW)                             │
│ • Saves formatted results to src/data/results/               │
│ • Generates timestamped JSON and markdown files              │
│ • Includes raw step data for debugging                       │
│ • Auto-creates results directory structure                   │
└───────────────────────────────────────────────────────────────┘
```

### **🐛 RESOLVED ISSUES** ✅

#### **Python Syntax Error in Data Injection** - **FIXED** ⭐ **NEW**
- **Problem**: `json.dumps()` converted Python `None` to JSON `null`, causing `NameError: name 'null' is not defined`
- **Impact**: Step 3 API code execution consistently failed with Python syntax errors
- **Root Cause**: Data injection used JSON serialization instead of Python-compatible serialization
- **Fix Applied**: Changed from `json.dumps(data)` to `repr(data)` in `_generate_data_injection_code()`
- **Status**: ✅ **RESOLVED** - All multi-step API workflows now execute without syntax errors
- **Fix Location**: `modern_execution_manager.py` lines 322-324

#### **Token-Based Processing Logic** - **IMPLEMENTED** ⭐ **NEW**
- **Problem**: Record count threshold (≤200) ignored actual data complexity (e.g., 5 records with 250+ groups)
- **Impact**: Large datasets incorrectly processed manually, causing LLM context overflow and truncation
- **Solution**: Implemented token estimation (~4 chars = 1 token) with 5,000 token threshold
- **Benefit**: Smart processing decisions based on actual data size, not record count
- **Status**: ✅ **IMPLEMENTED** - System now properly triggers code generation for complex datasets
- **Fix Location**: `results_formatter_agent.py` lines 331-350

#### **File Saving Content Type Error** - **FIXED** ⭐ **NEW**
- **Problem**: `'str' object has no attribute 'get'` when saving results from code generation mode
- **Impact**: File saving failed when Results Formatter generated code (large datasets)
- **Root Cause**: Code generation returns string content, manual processing returns list content
- **Fix Applied**: Added string content handling in `_save_results_to_file()` method
- **Status**: ✅ **RESOLVED** - File saving works for both processing modes
- **Fix Location**: `modern_execution_manager.py` lines 1798-1830

#### **Results Formatter Record Count Bug** - **FIXED**
- **Problem**: `_count_total_records()` expected `results['raw_results']` structure but Modern Execution Manager passed `step_results_for_processing` directly
- **Impact**: Showed "Processing 0 total records" instead of actual count (e.g., 4 records)
- **Symptom**: Complete data processing vs token-based processing decision was affected by inaccurate record counts
- **Fix Applied**: Updated `_count_total_records()` to handle both data structures
- **Status**: ✅ **RESOLVED** - Now properly counts records for accurate token-based processing decisions
- **Fix Location**: `results_formatter_agent.py` lines 85-110

## 🧠 ENHANCED CONTEXT SYSTEM

### **Key Innovation: LLM Intelligence Instead of Hardcoded Logic**

**Problem Solved**: Previous system had temp table data type mismatches because SQL agent created schemas for one data type but received different data for insertion.

**Solution**: Enhanced context system where EXECUTION agents receive complete workflow history to make intelligent decisions.

**Benefits**:
- 🎯 **Smart Schema Generation**: API-SQL agent sees actual data types from previous steps
- 🔄 **Context-Aware Code**: API code gen agent understands workflow progression  
- 🧠 **Intelligent Decisions**: LLMs make smart choices instead of hardcoded assumptions
- 🏗️ **Clean Architecture**: Zero backward compatibility, unified data flow

**Who Gets Enhanced Context:**
- ✅ SQL Agent (understands workflow context)
- ✅ API-SQL Agent (sees previous data types for temp table schemas)  
- ✅ API Code Generation Agent (writes code referencing previous step variables)
- ❌ Results Formatter (gets ALL raw data, makes size-based processing decisions only)

### **Enhanced Context Flow**:
```
Step N Agent Input = {
    "query_context": "Current step description",
    "all_step_contexts": {
        "step_1_context": "What step 1 did",
        "step_1_sample": [actual_data_from_step_1],
        "step_2_context": "What step 2 did", 
        "step_2_sample": [actual_data_from_step_2],
        // ... all previous steps
    }
}
```

## ⚡ DATA INJECTION ARCHITECTURE (NEW)

### **Critical Problem Solved: Variable Access in Generated Code**

**The Issue**: 
- Enhanced context provides `step_N_sample` data to LLMs for planning
- LLMs generate code referencing `step_2_sample`, `step_3_sample`, etc.
- But execution environment had NO access to these variables
- Result: `NameError: name 'step_2_sample' is not defined`

**The Solution**: Dynamic Data Injection
```python
# _generate_data_injection_code() creates:
step_1_sample = [actual_sample_data_from_step_1]
step_1_context = "Step 1: Get login events from last 7 days"
step_2_sample = [actual_sample_data_from_step_2] 
step_2_context = "Step 2: Find users and applications"
# ... for ALL previous steps
```

**How It Works**:
1. **Planning Phase**: LLM sees enhanced context with `step_N_sample` data
2. **Code Generation**: LLM generates code using `step_N_sample` variables
3. **Data Injection**: System injects actual variables into execution environment
4. **Execution**: Generated code finds the exact variables it expects

**Extensibility**: 
- ✅ Works with ANY number of API steps (scales infinitely)
- ✅ Works with future code-generating tools (Python scripts, ML pipelines)
- ✅ Automatic - no changes needed for new tools that follow code execution pattern

**Example Generated Code**:
```python
# This code now works because variables are injected:
user_ids = [record['user_okta_id'] for record in step_2_sample]
for user_id in user_ids:
    result = await client.make_request(f'/api/v1/users/{user_id}/roles')
```
    │
    v
┌───────────────────────────────────────────────────────────────┐
│ RESULTS FORMATTER AGENT                                       │
│ Input: All data_variables + original query                   │
│ Output: Formatted markdown response                           │
└───────────────────────────────────────────────────────────────┘
```

---

## 🛠️ FUNCTION REFERENCE BY PURPOSE

### **Planning & Orchestration**
| Function | File | Purpose |
|----------|------|---------|
| `execute_query()` | modern_execution_manager.py | Main entry point |
| `planning_agent.run()` | planning_agent.py | Generate execution plan |
| `execute_steps()` | modern_execution_manager.py | Execute plan steps |

### **Code Generation & Execution**
| Function | File | Purpose |
|----------|------|---------|
| `api_code_gen_agent.run()` | api_code_gen_agent.py | Generate API Python code with enhanced context |
| `_execute_generated_code()` | modern_execution_manager.py | **NEW** - Execute API code with data injection |
| `_generate_data_injection_code()` | modern_execution_manager.py | **NEW** - Inject step variables for code access |
| `generate_sql_query_with_logging()` | sql_agent.py | Generate SQL queries |
| `api_sql_agent.process_api_data()` | api_sql_agent.py | Generate API-SQL bridge |

### **Data Management**
| Function | File | Purpose |
|----------|------|---------|
| `_store_step_data()` | modern_execution_manager.py | Store step results |
| `_get_full_data_from_previous_step()` | modern_execution_manager.py | Retrieve full datasets |
| `_get_all_previous_step_contexts_and_samples()` | modern_execution_manager.py | **ENHANCED** - Get enhanced context for intelligent LLM decisions |

### **Database Operations**
| Function | File | Purpose |
|----------|------|---------|
| `_execute_raw_sql_query()` | modern_execution_manager.py | Execute SQL with async |
| `_insert_api_data_into_temp_table()` | modern_execution_manager.py | Insert into temp tables |
| `_cleanup_temp_table()` | modern_execution_manager.py | Clean up temp tables |

### **Result Processing & File Management**
| Function | File | Purpose |
|----------|------|---------|
| `results_formatter.run()` | results_formatter_agent.py | Format final results |
| `_save_results_to_file()` | modern_execution_manager.py | **NEW** - Save results and raw data to files |

---

## 🔧 TROUBLESHOOTING GUIDE

### **Step Execution Fails**
1. Check `modern_execution_manager.py` → `execute_steps()`
2. Look at specific step function: `_execute_api_step()` or `_execute_sql_step()`
3. Check logs for correlation_id to trace the issue

### **API Code Generation Problems**
1. Check `api_code_gen_agent_system_prompt.txt` for prompt issues
2. Check `api_code_gen_agent.py` → `run()` method
3. Verify endpoint data being passed to agent
4. **NEW** - Check if enhanced context (`all_step_contexts`) is properly formatted

### **API Code Execution Issues** ⭐ **NEW SECTION**
1. **Variable Not Defined Errors**: Check `_generate_data_injection_code()` output
2. **Missing step_N_sample**: Verify previous steps completed successfully and stored data
3. **Data Type Issues**: Check that injected sample data matches expected structure
4. **Execution Environment**: Verify `_execute_generated_code()` properly injects variables
5. **Generated Code**: Check if code references variables that should be available (`step_1_sample`, etc.)

### **Data Injection Problems** ⭐ **NEW SECTION**
1. Check `_generate_data_injection_code()` function in `modern_execution_manager.py`
2. Verify `self.step_metadata` and `self.data_variables` have correct data
3. Check correlation_id in logs to trace data injection execution
4. Verify JSON serialization of sample data doesn't break in injection code
5. Check that `current_step_number` parameter is passed correctly to code execution

### **Results Formatter Issues** ⭐ **UPDATED**
1. **Record Count Shows 0**: ✅ **FIXED** - `_count_total_records()` now handles both data structures
   - Modern structure: `results` contains step data directly
   - Legacy structure: `results['raw_results']['sql_execution']['data']`
   - Both patterns now supported for backward compatibility
2. **Token-Based Processing Logic**: ✅ **WORKING** 
   - ≤5,000 tokens = complete data processing (direct LLM processing)
   - >5,000 tokens = code generation mode (sampling + processing script)
   - Now correctly estimates data complexity and makes intelligent processing decisions
   - Handles complex datasets (e.g., 5 records with 250+ groups) appropriately
3. **File Saving Errors**: Check `_save_results_to_file()` method for proper data structure

### **SQL Generation Issues**
1. Check `sql_agent.py` → `generate_sql_query_with_logging()`
2. Check `api_sql_agent.py` → `process_api_data()` for API-SQL bridge
3. Verify database schema in system prompts

### **Data Flow Issues**
1. Check `_store_step_data()` and `_get_full_data_from_previous_step()`
2. Verify `data_variables` and `step_metadata` structures
3. **ENHANCED** - Check `_get_all_previous_step_contexts_and_samples()` for enhanced context
4. Check Pydantic validation in agent input classes

### **Enhanced Context System Issues**
1. Verify `_get_all_previous_step_contexts_and_samples()` returns complete workflow history
2. Check that all agents receive `all_step_contexts` parameter correctly
3. Verify system prompts inform LLMs about enhanced context capabilities
4. Check context and sample data structure in step_metadata

### **Temp Table Schema Problems**
1. Check `api_sql_agent.py` → `process_api_data()` with enhanced context
2. Verify LLM receives actual data types from previous steps
3. Check temp table schema generation against actual API data structure
4. Verify enhanced context enables intelligent schema decisions

### **Token-Based Processing Decisions** ⭐ **NEW SECTION**
1. **Threshold Logic**: Check `_estimate_token_count()` function returns reasonable estimates
2. **Token Calculation**: Verify JSON string conversion and division by 4 for token estimation
3. **Threshold Setting**: Current threshold is 5,000 tokens (~3,750 words)
4. **Decision Logic**: `estimated_tokens <= 5000` determines processing mode
5. **Large Dataset Handling**: Verify system triggers code generation for complex data (e.g., 250+ groups)
6. **Performance**: Check that large datasets avoid LLM context overflow

### **File Saving Issues** ⭐ **UPDATED SECTION**
1. Check `_save_results_to_file()` in `modern_execution_manager.py`
2. **Content Type Handling**: Verify both string (code generation) and list (manual processing) content types
3. **String Content**: Check code generation mode produces description + processing code
4. **List Content**: Check manual processing mode produces record arrays
5. Verify `src/data/results/` directory exists and is writable
6. Check file naming patterns with timestamp and correlation_id
7. Verify JSON serialization of results and raw data
8. Check file permissions and disk space

### **Database Execution Problems**
1. Check `_execute_raw_sql_query()` for async/WAL mode issues
2. Check temp table functions for cleanup issues
3. Verify database connection and timeout settings

### **Future Custom Tools Issues** ⭐ **NEW SECTION**
1. **Python Script Tools**: Verify they follow code execution pattern to benefit from data injection
2. **Direct Processing Tools**: Ensure they receive `full_previous_data` and `all_step_contexts` parameters
3. **Tool Registration**: Check placeholder in `execute_steps()` elif block
4. **Data Access**: Verify new tools can access previous step data via appropriate method

---

## 📝 CONFIGURATION FILES

| File | Purpose | Key Settings |
|------|---------|--------------|
| `planning_agent_system_prompt.txt` | Planning agent instructions | Step decomposition rules |
| `api_code_gen_agent_system_prompt.txt` | API code generation rules | **UPDATED** - Enhanced context awareness, intelligent decision-making, **data injection variable access instructions** |
| `api_sql_agent_system_prompt.txt` | API-SQL bridge instructions | **UPDATED** - Smart temp table schema generation based on actual data |
| `results_formatter_complete_data_prompt.txt` | Results formatting rules | Output format specifications |

**Recent Updates**: 
- ✅ All system prompts updated to inform LLMs about enhanced context capabilities
- ✅ API Code Gen Agent prompt includes explicit instructions for accessing injected variables
- ✅ Enhanced context enables intelligent decision-making instead of hardcoded logic
- ⭐ **NEW**: Data injection architecture documented in API Code Gen Agent system prompt

---

## ⚡ RECENT MODERNIZATION (2025)

### **Major Architectural Changes**

**🔧 Enhanced Context System**:
- ✅ Added `_get_all_previous_step_contexts_and_samples()` for complete workflow awareness
- ✅ All agents now receive full workflow history for intelligent decisions
- ✅ Eliminated temp table data type mismatches through LLM intelligence

**⚡ Token-Based Processing Architecture** ⭐ **NEW CRITICAL FEATURE**:
- ✅ Added `_estimate_token_count()` for intelligent processing decisions
- ✅ Implemented 5,000 token threshold (~3,750 words) for optimal LLM performance  
- ✅ Fixed record-based logic that ignored data complexity (5 records with 250+ groups)
- ✅ Smart detection triggers code generation for complex datasets
- ✅ Prevents LLM context overflow and response truncation

**⚡ Data Injection Architecture** ⭐ **ENHANCED**:
- ✅ Fixed Python syntax errors by replacing `json.dumps()` with `repr()` 
- ✅ Resolved `NameError: name 'null' is not defined` in generated API code
- ✅ Ensures Python-compatible serialization (`None` vs `null`, `True` vs `true`)
- ✅ Enhanced `_execute_generated_code()` with proper Python variable injection
- ✅ Updated API Code Gen Agent system prompt with variable access instructions
- ✅ Automatic scaling for any number of API steps

**💾 File Persistence System** ⭐ **ENHANCED**:
- ✅ Added `_save_results_to_file()` for automatic result persistence
- ✅ Fixed content type handling for both string (code generation) and list (manual processing) modes
- ✅ Creates timestamped JSON and markdown files in `src/data/results/`
- ✅ Includes both formatted results and raw step data for debugging
- ✅ Auto-creates directory structure

**🧹 Code Cleanup**:
- ✅ Removed `accumulated_data` system (legacy sample storage)
- ✅ Eliminated all backward compatibility code
- ✅ Consolidated duplicate `MockSQLResult` classes
- ✅ Removed redundant `_extract_sample()` and `_get_sample_data_for_llm()` methods
- ✅ Cleaned up unused imports and variables

**🏗️ Clean Architecture**:
- ✅ Unified data flow using `data_variables` and enhanced `step_metadata`
- ✅ Single source of truth for all data structures
- ✅ Zero redundant code or duplicate functionality
- ✅ Streamlined agent function signatures

**🎯 Intelligent Decision Making**:
- ✅ API-SQL agent makes smart temp table schema decisions based on actual data
- ✅ API code gen agent understands workflow progression
- ✅ SQL agent generates context-aware queries
- ✅ Results formatter has complete workflow visibility

**🔮 Extensibility Framework**:
- ✅ Placeholder architecture for future custom tools
- ✅ Data injection works automatically for any code-generating tools
- ✅ Enhanced context system supports unlimited tool types
- ✅ Clean separation between code-executing and direct-processing tools

---

## 🔄 DATA STRUCTURES

### **Key Data Storage**
```python
# In ModernExecutionManager
self.data_variables = {
    "api_data_step_1": [raw_api_results],
    "api_sql_data_step_2": [sql_query_results], 
    "api_data_step_3": [more_api_results]
}

# Enhanced step_metadata now includes context and samples for intelligent LLM decisions
self.step_metadata = {
    "step_1": {
        "type": "api", 
        "success": True, 
        "record_count": 100,
        "variable_name": "api_data_step_1",  # NEW - tracks storage location
        "context": "Step 1: Get login events from last 7 days",
        "sample": [first_3_records_from_step_1]
    },
    "step_2": {
        "type": "api_sql", 
        "success": True, 
        "record_count": 50,
        "variable_name": "api_sql_data_step_2",  # NEW - tracks storage location
        "context": "Step 2: Find users and their applications", 
        "sample": [first_3_records_from_step_2]
    }
}
```

### **Data Injection Variables** ⭐ **NEW**
```python
# During API code execution, these variables are automatically injected:
step_1_sample = [actual_sample_data_from_step_1]
step_1_context = "Step 1: Get login events from last 7 days"
step_2_sample = [actual_sample_data_from_step_2] 
step_2_context = "Step 2: Find users and their applications"
# Generated code can access these directly!
```

## 🔮 FUTURE EXTENSIBILITY

### **Adding New Tools Pattern**
```python
# In execute_steps() method:
elif step.tool_name == "python_script":
    result = await self._execute_python_script_step(step, correlation_id, step_num)
elif step.tool_name == "ml_pipeline":
    result = await self._execute_ml_pipeline_step(step, correlation_id, step_num)
elif step.tool_name == "access_checker":  # Example: complex access evaluation
    result = await self._execute_access_checker_step(step, correlation_id, step_num)
```

### **Two Tool Categories**

**1. Code-Executing Tools** (Benefit from Data Injection):
- ✅ Python script generators
- ✅ ML pipeline tools  
- ✅ Custom API orchestrators
- ✅ Data transformation scripts
- **Pattern**: Generate code → Execute in subprocess → Data injection provides variable access

**2. Direct-Processing Tools** (Get Data as Parameters):
- ✅ Database query tools
- ✅ File processors
- ✅ Direct API callers
- **Pattern**: Receive full data + enhanced context as function parameters

### **Implementation Template for New Tools**:
```python
async def _execute_new_tool_step(self, step, correlation_id, step_number):
    # Get enhanced context from all previous steps
    all_step_contexts = self._get_all_previous_step_contexts_and_samples(step_number, max_samples=3)
    
    # Get full data from previous step
    full_previous_data = self._get_full_data_from_previous_step(step_number)
    
    # Generate/execute with tool agent
    result = await tool_agent.process(
        query=step.query_context,
        data=full_previous_data,
        all_step_contexts=all_step_contexts
    )
    
    # Store results for next steps
    variable_name = self._store_step_data(
        step_number=step_number,
        step_type="new_tool",
        data=result.data,
        metadata=result.metadata,
        step_context=step.query_context
    )
    
    return StepResult(...)
```

### **Enhanced Context System**
```python
# _get_all_previous_step_contexts_and_samples() returns:
{
    "step_1_context": "Step 1: Get login events from last 7 days",
    "step_1_sample": [first_3_records],
    "step_2_context": "Step 2: Find users and their applications",
    "step_2_sample": [first_3_records],
    # ... all previous steps
}
```

### **Step Result Structure**
```python
StepResult(
    step_number=1,
    step_type="api",
    success=True,
    result=data,
    error=None,
    metadata={"record_count": 100}
)
```

This document should help you quickly identify where to look when something goes wrong!

---

## 📜 MODERNIZATION HISTORY

### **Recent Architectural Changes** 

**🎯 Data Injection Architecture** - *Critical Enhancement*
- **Problem Solved**: API code execution couldn't access previous step data (`name 'step_2_sample' is not defined`)
- **Solution**: `_generate_data_injection_code()` creates accessible variables matching enhanced context patterns
- **Impact**: Seamless data flow between planning context and execution environment
- **Files Modified**: `modern_execution_manager.py`, `api_code_gen_agent_system_prompt.txt`

**📁 File Persistence System** - *New Feature*
- **Enhancement**: Automatic saving of formatted results and raw data to timestamped files
- **Location**: `src/data/results/` with JSON (raw) and Markdown (formatted) outputs
- **Benefit**: Complete audit trail and easy result sharing
- **Files Modified**: `results_formatter_agent.py`, `modern_execution_manager.py`

**🔍 Enhanced Context System** - *Intelligence Upgrade*
- **Enhancement**: All agents now receive complete workflow history with context and samples
- **Pattern**: `step_N_context` and `step_N_sample` for intelligent decision making
- **Scope**: SQL Agent, API-SQL Agent, API Code Generation Agent, Results Formatter
- **Benefit**: Agents understand full workflow for better code generation and formatting

**🚀 Future Tool Framework** - *Extensibility Ready*
- **Architecture**: Placeholder patterns for custom Python script tools and complex operations
- **Categories**: Code-executing tools (with data injection) vs direct-processing tools (with parameters)
- **Design**: Template methods ready for rapid tool integration
- **Vision**: Custom access checkers, ML pipelines, complex data transformations

### **Legacy vs Modern Patterns**

**Old Pattern** (Limited Context):
```python
# Agents only saw current step data
result = agent.process(query=step.query, data=current_data)
```

**New Pattern** (Full Workflow Awareness):
```python
# Agents see complete workflow history
all_contexts = self._get_all_previous_step_contexts_and_samples(step_num)
result = await agent.process(
    query=step.query_context,
    data=full_data,
    all_step_contexts=all_contexts  # NEW: Complete awareness
)
```

**Old Execution** (Variable Access Issues):
```python
# Generated code failed: step_2_sample not defined
user_apps = analyze_user_applications(step_2_sample)  # ❌ Error
```

**New Execution** (Data Injection):
```python
# Data injection makes variables available
injection_code = f"""
step_1_sample = {json.dumps(sample_1, default=str)}
step_2_sample = {json.dumps(sample_2, default=str)}
"""
# Generated code works: step_2_sample available! ✅
```

### **Architecture Maturity Timeline**

1. **Foundation Phase**: Basic SQL and API agents
2. **Integration Phase**: Multi-step workflow coordination  
3. **Intelligence Phase**: Enhanced context system for workflow awareness
4. **Execution Phase**: Data injection architecture for seamless variable access
5. **Persistence Phase**: File output system for complete audit trails
6. **Extensibility Phase**: Future tool framework for unlimited expansion

**Current Status**: ✅ Production-ready with complete data flow architecture

---

*Last Updated: December 2024 - Complete architecture reference with all modern enhancements*
