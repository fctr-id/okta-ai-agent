# Okta AI Agent: LLM-Optimized API Reference Architecture with Modern Execution Flow

## Overview

This document describes the sophisticated multi-stage LLM system designed to generate accurate Okta API code through intelligent workflow orchestration, precise endpoint selection, and secure code generation.

## The Problem Being Solved

### Traditional LLM API Challenges

When working with complex APIs like Okta's Management API, LLMs face several critical challenges:

1. **Semantic vs Technical Mismatch**: LLMs often pick endpoints that "sound right" semantically but are technically incorrect
2. **Overwhelming Context**: The full Okta API has 190K+ lines, far exceeding LLM context limits
3. **Complex Dependencies**: Multi-step operations require understanding relationships between endpoints
4. **Hidden Technical Requirements**: Some operations require specific endpoints that aren't obvious from the query
5. **Workflow Orchestration**: Complex queries require multi-step data flow between different agents and operations

### Real-World Example: The SAML Certificate Problem

**User Query**: "Get expiry dates for all SAML applications"

**LLM's Intuitive Choice**: `get-saml-metadata` (sounds related to SAML)
**Correct Technical Choice**: `list-application-keys` (contains actual expiry dates)

This represents a fundamental challenge where semantic similarity doesn't match technical reality.

## The Solution: Multi-Stage LLM Architecture with Modern Execution Flow

### Stage 1: Planning Agent (Natural Language to Execution Plan)
- **Framework**: PydanticAI v0.4.3 with structured output validation
- **Input**: Natural language query + lightweight API reference
- **Processing**: Entity recognition, operation mapping, multi-step workflow planning
- **Output**: Structured ExecutionPlan with ordered ExecutionSteps
- **Dependencies**: Uses simplified entity-operation reference for fast planning

### Stage 2: Modern Execution Manager (Workflow Orchestration)
- **Framework**: Polars DataFrames for high-performance data operations
- **Input**: ExecutionPlan from Planning Agent
- **Processing**: Step-by-step execution with intelligent data flow
- **Output**: Structured results with comprehensive metadata
- **Dependencies**: Coordinates all specialized agents and manages execution state

### Stage 3: Endpoint Filtering (Precise API Selection)
- **Input**: ExecutionStep with entity-operation requirements
- **Processing**: Comprehensive endpoint filtering with dependency resolution
- **Output**: Filtered endpoint list with complete documentation
- **Dependencies**: Uses full endpoint reference with security validation

### Stage 4: API Code Generation Agent (Technical Implementation)
- **Framework**: PydanticAI v0.4.3 with 302-line comprehensive system prompt
- **Input**: Filtered endpoints + execution context + previous step data
- **Processing**: Secure Python code generation with OktaAPIClient integration
- **Output**: Executable Python code with comprehensive error handling
- **Dependencies**: Enforces security constraints and client standardization

## Modern Execution Flow Architecture

### Complete Data Flow:

```
Natural Language Query
        ↓
Planning Agent (PydanticAI)
        ↓
ExecutionPlan (Structured Steps)
        ↓
Modern Execution Manager
        ↓
┌─────────────────────────────────────┐
│ Step Execution Loop:                │
│                                     │
│ Step N: SQL/API/API_SQL Agent       │
│    ↓                                │
│ Polars DataFrame Storage            │
│    ↓                                │
│ Enhanced Context Injection          │
│    ↓                                │
│ Step N+1 Execution                  │
│    ↓                                │
│ Repeat until completion             │
└─────────────────────────────────────┘
        ↓
Results Formatter Agent
        ↓
Structured Response (JSON/Table/Chart)
```

### Execution Manager Integration:

1. **Planning Integration**: Receives structured ExecutionPlan from Planning Agent
2. **Agent Coordination**: Routes steps to appropriate specialized agents (SQL, API, API_SQL)
3. **Data Flow Management**: Polars DataFrames provide high-performance data operations
4. **Context Enhancement**: Previous step data automatically available to subsequent steps
5. **Security Enforcement**: All generated code validated before execution
6. **Results Processing**: Complete workflow data passed to Results Formatter Agent

### Enhanced Context System

**Problem Solved**: LLMs need access to previous step results for intelligent decision-making and data processing.

**Solution**: Automatic variable injection system that creates accessible data context:

```python
# Automatically injected variables for each step
step_1_sample = [{"id": "user123", "name": "John"}]  # Sample data for context
step_1_context = "Retrieved active users from database"  # Step description
step_2_sample = [{"user_id": "user123", "groups": ["admins"]}]  # Next step sample
full_results = {"1_sql": [...], "2_api": [...]}  # Complete data structure
```

**Context Flow**:
1. Planning Agent generates execution steps
2. Modern Execution Manager executes steps sequentially  
3. Each step result stored in Polars DataFrame
4. Context automatically injected into subsequent steps
5. Results Formatter Agent processes complete workflow

## Core Components

### 1. Entity Summary Structure

```json
{
  "entity_summary": {
    "application": {
      "aliases": ["app", "integration", "client"],
      "operations": ["list", "get"],
      "methods": ["GET"],
      "endpoint_count": 2
    }
  }
}
```

**Purpose**: Provides high-level mapping between natural language concepts and technical entities.

**Key Features**:
- **Aliases**: Handle natural language variations ("app" → "application")
- **Operations**: Clear action mapping (list, get, create, etc.)
- **Endpoint Count**: Indicates complexity level

### 2. Endpoint Structure

```json
{
  "id": "list-application-keys",
  "method": "GET",
  "url_pattern": "/api/v1/apps/{appId}/credentials/keys",
  "name": "List all key credentials",
  "entity": "application_credential",
  "operation": "list_keys",
  "description": "Lists all key credentials for an application.",
  "folder_path": "Application Key Credentials",
  "parameters": { 
    "required": ["appId"], 
    "optional": [] 
  },
  "depends_on": ["list-applications"],
  "notes": "You MUST use this to get expiry dates for SAML applications keys."
}
```

**Key Features**:
- **Clear Identification**: Unique ID and descriptive name
- **Parameter Specification**: Required vs optional parameters
- **Dependency Chain**: Shows prerequisite endpoints
- **LLM-Friendly Notes**: Explicit technical guidance

### 3. API Code Generation Agent (Technical Implementation)

**Framework**: PydanticAI v0.4.3 with comprehensive 302-line system prompt

**System Prompt Features**:
- **Security Whitelisting**: Only approved Python modules (asyncio, json, sys, datetime, pathlib, dotenv)
- **Blocked Patterns**: Prevents globals(), eval(), exec(), subprocess, requests module usage
- **OktaAPIClient Enforcement**: Mandatory usage of standardized API client for all operations
- **JSON Output Mandate**: All code must output structured JSON format only
- **Enhanced Context Awareness**: Access to all previous step data through injected variables
- **Dynamic Date Calculation**: Built-in support for relative time expressions

**System Prompt Sections** (302 lines total):
1. **Security Compliance** (50+ lines): Whitelisted modules, blocked patterns, security rules
2. **OktaAPIClient Integration** (40+ lines): Mandatory client usage, method signatures, authentication
3. **Code Structure Requirements** (30+ lines): Async function structure, import requirements
4. **Context & Data Handling** (60+ lines): Previous step data access, variable injection system
5. **Okta API Guidelines** (50+ lines): Endpoint compliance, parameter validation, time filtering
6. **Error Handling & Output** (40+ lines): Status checking, JSON output enforcement
7. **Quality & Performance** (30+ lines): Concurrent calls, memory efficiency, rate limiting

**Enhanced Context Awareness**: The agent automatically receives previous step data through variable injection:

```python
# Security Compliance: Direct variable access (no globals() allowed)
if step_1_sample:
    user_ids = [user['id'] for user in step_1_sample]

# Previous step contexts automatically available
step_1_context = "Retrieved active users from database"
step_2_sample = [{"user_id": "user123", "groups": ["admins"]}]
```

**Security Enforcement**:
- **NO** direct `requests` or `aiohttp` calls - Must use OktaAPIClient
- **NO** manual pagination, rate limiting, or authentication - Client handles automatically
- **NO** `globals()`, `locals()`, or `eval()` functions - Security violations
- **YES** Structured JSON output with error handling
- **YES** Direct variable access to previous step data

### 4. Modern Execution Manager (Workflow Orchestration)

**Framework**: Polars DataFrames for high-performance data operations

**Core Features**:
- **Full Polars Architecture**: All data operations use Polars DataFrames for maximum performance
- **Enhanced Context System**: Previous step data automatically injected as variables  
- **Intelligent Data Flow**: Step results flow seamlessly between different agent types
- **Security Integration**: Comprehensive code validation and whitelisting enforcement
- **Error Recovery**: Graceful handling of step failures with detailed diagnostics

**Data Flow Management**:
```python
# Polars DataFrame storage for high-performance operations
self.polars_dataframes[variable_name] = pl.DataFrame(step_data)

# Automatic variable injection for enhanced context
step_1_sample = df.head(3).to_dicts()  # Sample for context
step_1_context = "Step description"    # Context for LLM
full_results = {"1_sql": [...]}        # Complete data structure
```

**Agent Coordination**:
- **SQL Agent**: Database queries and schema operations
- **API Agent**: Direct Okta API calls and data retrieval  
- **API-SQL Agent**: Internal hybrid operations combining API and database
- **Results Formatter Agent**: Final output processing and visualization

**Execution Flow**:
1. Receives ExecutionPlan from Planning Agent
2. Executes steps sequentially with data persistence
3. Injects previous step data into subsequent steps
4. Validates all generated code before execution
5. Manages timeouts and error recovery
6. Passes complete workflow data to Results Formatter

### 5. Comprehensive Security Framework

**Multi-layered security validation across all components**:

#### Planning Agent Security
- **Structured Output Validation**: PydanticAI ensures valid execution plans
- **Entity Whitelisting**: Only approved entities and operations allowed
- **SQL Table Validation**: Database schema compliance checking

#### Execution Manager Security  
- **Code Validation**: All generated code validated before execution
- **Subprocess Isolation**: Timeout-controlled execution environment
- **Resource Limits**: Memory and execution time constraints
- **Input Sanitization**: Parameter validation and injection prevention

#### API Code Generation Security
- **System Prompt Enforcement**: 302-line security specification
- **Import Whitelisting**: Only approved Python modules accessible
- **Pattern Detection**: Real-time scanning for dangerous code patterns
- **Client Standardization**: Mandatory OktaAPIClient usage prevents direct API access

#### Runtime Security
- **Environment Isolation**: Subprocess execution with timeouts (API: 180s, SQL: 60s)
- **Error Sanitization**: Safe error message handling without sensitive data exposure
- **Audit Logging**: Comprehensive security event tracking with correlation IDs
- **Rate Limit Compliance**: Automatic rate limiting through standardized client

## Optimization Strategies

### 1. Context Window Management
- **Original**: 190,856 lines (full Postman collection)
- **Optimized**: 1,565 lines (107 GET-only endpoints)
- **Reduction**: ~99% size reduction while maintaining functionality

### 2. GET-Only Philosophy
- **Safety**: Eliminates risk of destructive operations
- **Focus**: Read-only operations cover 80% of common use cases
- **Simplicity**: Reduces cognitive load for LLMs

### 3. Smart Dependency Resolution

The `depends_on` field serves as a "safety net" that ensures LLMs get the correct endpoints even when their initial selection is suboptimal.

#### Dependency Categories:

1. **Sequential Dependencies**: Operations that must happen in order
   ```json
   "depends_on": ["list-applications", "list-application-keys"]
   ```

2. **Alternative Path Dependencies**: Guides toward better technical choices
   ```json
   // get-saml-metadata includes list-application-keys
   // So LLM gets both even if it picks the wrong one initially
   ```

3. **Comprehensive Analysis Dependencies**: Ensures complete data gathering
   ```json
   // get-user includes app-links, groups, and roles
   // For complete access analysis
   ```

### 4. Smart Filtering Process
- **Stage 1**: Semantic filtering by entity/operation in Planning Agent
- **Stage 2**: Precise endpoint selection with dependency resolution in Execution Manager
- **Stage 3**: Include dependencies to ensure completeness in API Code Generation
- **Result**: Relevant subset with technical correctness and comprehensive coverage

## Enhanced Dependencies Added to the System

### Strategic Dependency Additions (15+ enhancements)

#### User MFA and Authentication Analysis
```json
// Problem: "List users with MFA" might pick get-user instead of authenticator endpoints
"get-user-factors": {
  "depends_on": ["list-users"],
  "notes": "For comprehensive MFA analysis, start with user discovery"
}

"list-user-roles": {
  "depends_on": ["get-user"],
  "notes": "User context needed for role analysis"
}
```

#### Application Security Analysis  
```json
// Problem: "Check app certificates" might pick get-application instead of credential endpoints
"get-saml-metadata": {
  "depends_on": ["list-application-keys"],
  "notes": "For certificate details and expiry dates, use list-application-keys endpoint"
}

"list-application-users": {
  "depends_on": ["list-applications"],
  "notes": "Application discovery needed before user assignment analysis"
}
```

#### User Access Analysis
```json
// Problem: Role analysis needs comprehensive context
"list-user-assigned-roles": {
  "depends_on": ["list-roles"],
  "notes": "Role definitions needed for comprehensive access analysis"
}

"get-user-groups": {
  "depends_on": ["list-groups"],
  "notes": "Group information needed for complete membership analysis"
}
```

#### Group Access Management
```json
// Problem: Group analysis needs membership and role context
"get-group": {
  "depends_on": ["get-group-users"],
  "notes": "Group membership analysis needed for comprehensive group review"
}

"list-group-roles": {
  "depends_on": ["list-group-users"],
  "notes": "Group membership needed for comprehensive access review"
}
```

#### Policy and Compliance
```json
// Problem: Policy effectiveness needs user and application context
"list-user-roles": {
  "depends_on": ["list-application-users"],
  "notes": "Application-specific role analysis for policy compliance"
}
```

#### Device and Session Security
```json
// Problem: Device queries need user context for comprehensive security analysis
// Session analysis needs application usage patterns
```

#### Administrative Role Analysis
```json
// Problem: Role analysis needs usage patterns
"list-roles": {
  "depends_on": ["list-user-assigned-roles"],
  "notes": "Role usage analysis needed for administrative review"
}
```

### Benefits of Enhanced Dependencies

1. **Improved Accuracy**: Dependencies ensure correct endpoints are always available
2. **Reduced Hallucination**: Structured constraints guide LLM behavior  
3. **Enhanced Security**: Multi-layered validation prevents unsafe operations
4. **Better Performance**: Optimized reference reduces token usage and improves response times
5. **Comprehensive Coverage**: Related endpoints included automatically
6. **Context Awareness**: Previous step data seamlessly flows between operations
7. **Workflow Intelligence**: Complex multi-step operations handled automatically

## Technical Implementation Details

### PydanticAI Integration (v0.4.3)
- **Structured Output Validation**: Guaranteed JSON schema compliance
- **Dependency Injection**: Dynamic context passing between components
- **Token Counting**: Cost tracking and optimization
- **Model Retries**: Automatic retry logic with backoff strategies
- **Exception Handling**: Comprehensive error recovery mechanisms

### Modern Execution Manager Features
- **Polars Optimization**: High-performance DataFrame operations replacing SQL temp tables
- **Variable Injection**: Automatic creation of accessible previous step data
- **Security Integration**: Code validation before execution
- **Timeout Management**: Configurable execution timeouts (API: 180s, SQL: 60s)
- **Error Recovery**: Graceful handling of step failures with detailed diagnostics

### API Code Generation Security
- **System Prompt**: 302-line comprehensive security and behavior specification
- **OktaAPIClient Enforcement**: Standardized client with automatic pagination, rate limiting
- **Input Sanitization**: Parameter validation and SQL injection prevention
- **Output Standardization**: JSON-only responses with error handling
- **Code Pattern Detection**: Real-time scanning for security violations

## Benefits

1. **Enhanced Intelligence**: Multi-stage architecture enables complex workflow understanding
2. **Improved Accuracy**: Dependencies and context ensure correct endpoint selection
3. **Performance Optimization**: Polars DataFrames provide high-speed data operations
4. **Comprehensive Security**: Multi-layered validation prevents unsafe operations
5. **Workflow Automation**: End-to-end automation from natural language to results
6. **Context Awareness**: Previous step data seamlessly available to subsequent steps
7. **Error Resilience**: Graceful handling of failures with detailed diagnostics
8. **Cost Efficiency**: Optimized token usage through staged processing

## Future Enhancements

- **Dynamic Dependency Learning**: ML-based analysis of query patterns for automatic dependency suggestions
- **Advanced Workflow Patterns**: Support for conditional logic and parallel execution  
- **Enhanced Security Intelligence**: Behavioral analysis for anomaly detection
- **Performance Analytics**: Real-time monitoring and optimization recommendations
- **Extended API Coverage**: Include POST/PUT/DELETE operations with enhanced safeguards
- **Cross-Platform Integration**: Support for additional identity platforms beyond Okta

#### User Access Analysis
```json
// Problem: "What can user X access?" misses multiple access sources
"get-user": {
  "depends_on": ["list-users", "list-user-app-links", "list-user-groups", "list-user-roles"]
}
```

#### Application Access Mapping
```json
// Problem: "Who can access app X?" misses user assignments or policies
"list-application-group-assignments": {
  "depends_on": ["list-applications", "list-application-user-assignments", "list-policies"]
}
```

#### Device Compliance
```json
// Problem: "Get device compliance" picks basic device info instead of policy checks
"get-device": {
  "depends_on": ["list-devices", "list-device-assurance-policies", "list-device-posture-checks"]
}
```

#### Role Effectiveness
```json
// Problem: "What can admin X manage?" shows roles but not targets
"list-user-roles": {
  "depends_on": ["list-users", "list-app-targets-for-user-role", "list-group-targets-for-user-role"]
}
```

## Usage Flow

### 1. User Query Processing
```
User: "Find all users with no MFA enrolled"
```

### 2. Stage 1: Entity Selection
```json
Selected Entities: ["user", "user_authenticator"]
Selected Operations: ["list", "list_enrollments"]
```

### 3. Stage 2: Endpoint Filtering
```json
Base Endpoints: ["list-users", "list-user-authenticator-enrollments"]
Dependencies Added: [] // Already included
Final Endpoints: ["list-users", "list-user-authenticator-enrollments"]
```

### 4. LLM Code Generation
```python
# LLM generates code using both endpoints
users = okta_client.list_users()
for user in users:
    enrollments = okta_client.list_user_authenticator_enrollments(user.id)
    if not enrollments:
        print(f"User {user.profile.email} has no MFA enrolled")
```

## Benefits Achieved

### 1. Accuracy Improvements
- **Semantic Guidance**: Dependencies guide toward technically correct endpoints
- **Complete Operations**: Multi-step processes become reliable
- **Reduced Errors**: Common LLM mistakes are automatically corrected

### 2. Efficiency Gains
- **Focused Context**: Only relevant endpoints sent to LLM
- **Faster Processing**: Smaller context = faster response times
- **Resource Optimization**: Better use of LLM context window

### 3. Safety Enhancements
- **Read-Only**: GET-only operations prevent accidental modifications
- **Validated Paths**: Dependencies ensure proper operation sequences
- **Error Reduction**: Technical notes prevent common implementation mistakes

## Technical Implementation

### File Structure
```
src/data/schemas/
├── full_postman_collection_sfasfd.json     # Original 190K+ lines
├── Okta_API_entitity_endpoint_reference_GET_ONLY.json  # Optimized 1.5K lines
└── testing/
    └── suggested_dependencies_analysis.md   # Dependency analysis
```

### Key Metrics
- **Total Endpoints**: 107 GET-only operations
- **Entity Categories**: 25 major entity types
- **Dependencies Added**: 15+ strategic dependency enhancements
- **Size Reduction**: 99%+ from original

## Common Use Cases Improved

### 1. User Access Analysis
**Before**: LLM picks `get-user` → incomplete access picture
**After**: LLM gets user + app-links + groups + roles → complete analysis

### 2. Application Security
**Before**: LLM picks `get-application` → no certificate info
**After**: LLM gets application + keys + secrets → comprehensive security view

### 3. MFA Compliance
**Before**: LLM tries user profile → no MFA enrollment data
**After**: LLM gets user + authenticator enrollments → accurate MFA status

### 4. Device Compliance
**Before**: LLM gets basic device info → no compliance status
**After**: LLM gets device + policies + posture checks → full compliance picture

## Future Enhancements

### 1. Dynamic Dependency Resolution
- Context-aware dependency selection
- Query-specific dependency weights
- Adaptive filtering based on complexity

### 2. Performance Monitoring
- Track LLM endpoint selection accuracy
- Measure dependency effectiveness
- Optimize based on real usage patterns

### 3. Extended Coverage
- Add more specialized dependencies
- Include write operations with safety guards
- Support for complex multi-entity queries

## Conclusion

This LLM-optimized Okta API reference represents a sophisticated approach to bridging the gap between natural language queries and technical API operations. By combining semantic understanding with technical guidance through strategic dependencies, the system achieves high accuracy while maintaining efficiency and safety.

The two-stage architecture allows LLMs to leverage their natural language strengths while compensating for their technical knowledge gaps, resulting in a robust system for generating accurate Okta API code.

---

*Document Version: 1.0*  
*Last Updated: August 5, 2025*  
*Generated during dependency enhancement analysis*
