### **Okta AI Agent: System Workflow and Architecture**

This document outlines the operational workflow of the Okta AI Agent, from receiving a user query to delivering a final result. The system is designed as a sophisticated, multi-agent framework that intelligently combines the speed of local SQL database queries with the real-time accuracy of direct API calls.

#### **1. High-Level Overview**

The agent's primary function is to interpret complex, natural-language questions about an Okta environment and answer them by executing a series of tasks. The entire process can be broken down into four main phases:

1.  **Planning Phase:** A strategic plan is created to determine the most efficient steps to answer the user's query.
2.  **Enhancement Phase:** The initial plan is analyzed and optimized using full Okta API context and architectural knowledge.
3.  **Execution Phase:** The enhanced plan is executed step-by-step, orchestrating different specialized agents to perform SQL queries and API calls.
4.  **Formatting Phase:** The raw data from the execution phase is consolidated, processed, and presented in a user-friendly format.

#### **2. Key Components**

The workflow is managed by several key components:

*   **Orchestrator (`ModernExecutionManager`):** The central "brain" of the operation. It manages the entire lifecycle of a query, from planning to final output.
*   **Specialized Agents:**
    *   **Planning Agent:** Creates the high-level, multi-step strategy.
    *   **Step Enhancer Agent:** Analyzes and optimizes the initial plan using full API context and Okta architectural knowledge.
    *   **API Code Gen Agent:** Writes Python code to make Okta API calls.
    *   **SQL Code Gen Agent:** Writes SQL queries to run against the local database.
    *   **Internal API-SQL Agent:** A specialized agent that processes data from an API call and uses it to generate a subsequent SQL query.
    *   **Results Formatter Agent:** Consolidates data from all steps and formats the final output.
*   **Data Schema Files:** A series of JSON files are used to provide context to the agents, each with a specific purpose:
    *   `full_postman_collection_sfasfd.json`: The comprehensive "source of truth" containing all possible details about the Okta API, including sample requests and responses. It is used as the master reference.
    *   `Okta_API_entitity_endpoint_reference_GET_ONLY.json`: A structured, intermediate reference file generated from the Postman collection. It is used by the **Execution Manager** and **API Code Gen Agent** as it contains the necessary details for making API calls (URL patterns, parameters, dependencies, etc.). A key feature is the `depends_on` field, which allows the coding agent to see related, necessary endpoints that the planning agent might have missed.
    *   `lightweight_api_reference.json`: A highly simplified file generated dynamically. It contains only a list of available API operations and SQL table schemas. This is passed to the **Planning Agent** to allow it to create a strategy quickly without being overwhelmed by implementation details.

#### **3. Detailed Step-by-Step Workflow & Data Flow**

The following is a detailed breakdown of the workflow, using the example query: *"Find users logged in the last 10 days and fetch me their applications and groups and role assignments"*

1.  **Query Ingestion & Health Check:**
    *   The `ModernExecutionManager` receives the query.
    *   It first performs a health check on the local SQLite database to ensure it's available and populated. This determines if SQL-based steps are possible.

2.  **Phase 1: Planning**
    *   The `ModernExecutionManager` sends the user's query and the `lightweight_api_reference.json` to the **Planning Agent**.
    *   The Planning Agent returns an `ExecutionPlan` JSON object. For the example query, the plan is:
        1.  **API:** Get recent user login events.
        2.  **SQL:** Use the user IDs from step 1 to get their apps and groups.
        3.  **API:** Use the user IDs again to get role assignments.

3.  **Phase 1.5: Plan Enhancement**
    *   The `ModernExecutionManager` sends the initial plan, original query, and enriched endpoint context to the **Step Enhancer Agent**.
    *   The Step Enhancer Agent analyzes the plan with full Okta architectural knowledge and may optimize, reorder, or restructure steps.
    *   For example, it might recognize that role assignments could be retrieved more efficiently through a different endpoint pattern or combined with another step.
    *   The enhanced plan is returned for execution.

4.  **Phase 2: Execution & Context Passing**
    *   The `ModernExecutionManager` executes the plan step-by-step. This is where the critical data flow occurs.
    *   **Data Management:** The orchestrator uses an in-memory **Polars DataFrame** to store the results of each step. The output of one step is made available as input for the next.
    *   **Context Injection:** Before executing the code for a step, the orchestrator automatically "injects" the data from all previous steps into the execution environment. This data is made available as predefined variables (e.g., `step_1_sample`, `step_2_sample`).

    *   **Step 1 (API - Get Logins):**
        *   The **API Code Gen Agent** is invoked. It has no previous steps, so it just gets the query context ("get recent logins").
        *   It generates Python code to call the `/api/v1/logs` endpoint.
        *   The code is executed in a secure, isolated subprocess.
        *   The result (a list of user IDs) is stored in the orchestrator's Polars DataFrame, internally labeled as the result of `step_1`.

    *   **Step 2 (SQL - Get Apps/Groups):**
        *   The **Internal API-SQL Agent** is invoked.
        *   **Context Injection:** The orchestrator provides the data from the previous step as the `step_1_sample` variable.
        *   The agent generates a SQL query that uses the user IDs from `step_1_sample` to find their associated apps and groups.
        *   The query is executed, and the results are stored, labeled as the result of `step_2`.

    *   **Step 3 (API - Get Roles):**
        *   The **API Code Gen Agent** is invoked again.
        *   **Context Injection:** The orchestrator provides the data from **both** previous steps (`step_1_sample` and `step_2_sample`). The generated code can now access the original user IDs from step 1.
        *   The agent generates Python code that loops through the user IDs in `step_1_sample` and calls the `/api/v1/users/{userId}/roles` endpoint for each one.
        *   The results are stored, labeled as the result of `step_3`.

4.  **Phase 3: Formatting & Final Output**
    *   The **Results Formatter Agent** is invoked.
    *   It receives the complete, raw data from all three successful execution steps, along with the original query and the execution plan for full context.
    *   It analyzes all this information to generate a final, user-friendly output.
    *   The final result is a structured JSON object containing the display type (e.g., "table"), the formatted content, and metadata including headers for presentation.

#### **4. Architectural Solution for Agent Coordination**

A key challenge in this multi-agent system is ensuring the `API Code Gen Agent` has enough context to write correct code, even when the `Planning Agent`'s plan is high-level and lacks detail. The system solves this with a sophisticated, multi-layered approach that avoids the latency of an extra LLM call.

*   **Challenge: The Planner's "Context Gap"**
    *   The **Planning Agent** uses a lightweight schema to stay fast. This means it might choose a plausible but suboptimal API endpoint because it doesn't see detailed notes or dependencies. For example, it might choose a generic app metadata endpoint instead of the more specific `list_credentials` endpoint required for a task.

*   **Implemented Solution: A Hybrid Programmatic + "Smarter Coder" Approach**
    *   The system's current architecture elegantly solves this challenge by combining programmatic enhancement with a more context-aware coding agent.

    1.  **Programmatic Enhancement by the Orchestrator:** This is the first and most critical layer. When the `ModernExecutionManager` receives a step from the planner, it acts as a "Programmatic Enhancer."
        *   It looks up the endpoint chosen by the planner in the detailed `Okta_API_entitity_endpoint_reference_GET_ONLY.json`.
        *   It then reads the `depends_on` key for that endpoint and programmatically fetches the full details for all linked dependency endpoints.
        *   This creates a complete, enriched bundle of context containing the original endpoint *and* all its necessary companions.

    2.  **Context-Aware Coding:** The `API Code Gen Agent` receives this full bundle of related endpoints.
        *   Even if the planner originally chose a less optimal endpoint, the coder now has the full context for the *correct* one (e.g., `list_credentials`) because it was included as a dependency.
        *   This allows the coder to make an intelligent, informed decision and use the best endpoint from the provided context.

    3.  **Restrictive Coder Prompt:** To prevent the coder from "hallucinating" or inventing parsing logic even with this enhanced context, its system prompt has been made highly restrictive. It is explicitly instructed to act as a pass-through for the API data, returning the raw results without transformation unless the query explicitly requires it.

*   **Current Implementation: The `Step Enhancer Agent`**
    *   The system now includes a `Step Enhancer Agent` that operates between the Planning Agent and execution phases. This agent provides an advanced level of autonomous problem-solving by not only adding context but also intelligently *correcting* and *optimizing* flawed plans.
    *   **Status**: ✅ **IMPLEMENTED** - Agent and prompt created, ready for integration into `ModernExecutionManager`

***

#### **5. Step Enhancer Agent Implementation Plan**

The Step Enhancer Agent represents the next evolution of the system's architecture, providing intelligent plan optimization between planning and execution phases.

**5.1 Architectural Integration**

The Step Enhancer Agent will be executed **once** in the `ModernExecutionManager` workflow - immediately after the Planning Agent completes but before any step execution begins:

```
User Query → Planning Agent → Step Enhancer Agent → Modern Execution Manager → Execute All Steps → Results Formatter
```

**Key Point:** The Step Enhancer Agent operates at the **plan level**, not the individual step level. It receives the complete initial plan, analyzes it holistically, and returns an optimized plan that is then executed step-by-step by the existing agents.

**Injection Point in `execute_query()` method:**
*   **Current:** Planning Agent → Store Plan → Execute Steps
*   **Enhanced:** Planning Agent → **Step Enhancer Agent** → Store Enhanced Plan → Execute Steps

This requires minimal code changes to the existing `ModernExecutionManager.execute_query()` method, specifically between lines 997-998 where the plan is stored.

**Implementation Files:**
- ✅ `src/core/agents/step_enhancer_agent.py` - Complete agent implementation
- ✅ `src/core/agents/prompts/step_enhancer_agent_system_prompt.txt` - Optimization-focused system prompt
- 🔄 Integration pending in `ModernExecutionManager.execute_query()` method

**5.2 Input Context for Step Enhancer Agent**

The Step Enhancer Agent will receive comprehensive context to make intelligent decisions:

1.  **Original User Query:** The natural language query to understand intent
2.  **Initial Execution Plan:** The plan generated by the Planning Agent (same `ExecutionPlan` structure)
3.  **Full Endpoint Context:** Complete API endpoint details with `depends_on` relationships from `Okta_API_entitity_endpoint_reference_GET_ONLY.json`
4.  **Okta Architectural Knowledge:** Understanding of Okta entity relationships and best practices
5.  **Database Health Status:** Whether SQL operations are available

**Input/Output Structure:**
- **Input:** `ExecutionPlan` from Planning Agent + enriched endpoint context
- **Output:** Enhanced `ExecutionPlan` with same structure but optimized steps, better endpoint selection, and improved reasoning

The Step Enhancer Agent maintains full compatibility with the existing execution system by using the exact same `ExecutionPlan` and `ExecutionStep` data models.

**5.3 Step Enhancer Agent Capabilities**

The agent is designed as an **Okta API specialist** with comprehensive architectural intelligence to analyze execution plans and rewrite them for optimal performance. The agent's core mission is to **read full endpoint documentation** and **intelligently upgrade** the initial plan based on API capabilities.

**Core Okta Architecture Knowledge:**
- **Entity Understanding:** Deep knowledge of Users, Groups, Applications, Roles, Factors, System Logs, and Sessions
- **Relationship Mapping:** Understanding of data relationships (Users ↔ Groups, Users ↔ Applications, etc.)
- **API Intelligence:** Ability to read endpoint descriptions, parameters, and dependencies to make smart upgrades

**Intelligent Plan Enhancement:**
1.  **Endpoint Intelligence Analysis:** Reads full endpoint context to discover better alternatives
2.  **Smart Upgrades:** Generic → Specific (e.g., `user_list` → `user_list_with_profile` when user details needed)
3.  **Dependency Chain Optimization:** Uses `depends_on` relationships to find endpoints with richer context
4.  **Batch Operation Detection:** Single → Batch operations for efficiency
5.  **Okta-Aware Patterns:** Applies proven patterns for user activity, group membership, application access queries

**Enhancement Decision Process:**
For each step, the agent asks:
1. **What data does this step actually need?** (from original query)
2. **What endpoints are available?** (reads full context descriptions)  
3. **Which endpoint best matches the data need?** (upgrades from generic)
4. **Are there dependency opportunities?** (checks `depends_on` relationships)
5. **Can this be combined with other steps?** (batch operations)

**Key Enhancement Examples:**
- **Endpoint Upgrades:** `application_list` → `application_list_credentials` when credential information is needed
- **Intelligent Batching:** Multiple individual user API calls → Single filtered user list call
- **Dependency Utilization:** Using endpoints that provide enriched context through `depends_on` relationships
- **Query Pattern Recognition:** Applying Okta-specific optimization patterns for common query types

The enhanced plan maintains identical `ExecutionPlan` structure while providing more intelligent endpoint selection and improved execution reasoning.

**5.4 Implementation Strategy**

**✅ Phase 1: Core Agent Development - COMPLETED**
*   ✅ Created `step_enhancer_agent.py` in `src/core/agents/` directory  
*   ✅ **REDESIGNED** system prompt in `step_enhancer_agent_system_prompt.txt` - Changed from complex optimization to simple API endpoint validation
*   ✅ **NEW FOCUS:** Agent now validates API endpoints only, preserves SQL steps unchanged, and uses conservative approach
*   ✅ Agent now acts as **API endpoint validator** that ensures correct endpoint usage without modifying plan structure
*   ✅ Added input/output models compatible with existing ExecutionPlan structure
*   ✅ Comprehensive error handling and fallback mechanisms
*   ✅ **Updated methodology:** Validates that API operations use correct endpoints from filtered context without removing or changing SQL steps

**✅ Phase 2: ModernExecutionManager Integration - COMPLETED**
*   ✅ Added `_enhance_execution_plan()` method to `ModernExecutionManager` with precise endpoint filtering
*   ✅ Integrated precise endpoint filtering using existing `_get_entity_endpoints_for_step()` method
*   ✅ Enhanced to only provide relevant endpoints for API steps in the execution plan
*   ✅ Added deduplication logic to prevent endpoint redundancy
*   ✅ Integrated into `execute_query()` method at Phase 1.5 injection point
*   ✅ Ensured input/output uses identical `ExecutionPlan` and `ExecutionStep` data structures for seamless integration

**🔄 Phase 3: Testing and Validation - READY FOR TESTING**
*   🔄 Test Step Enhancer Agent with validation-focused prompt (no longer optimizes, only validates API endpoints)
*   🔄 Validate that enhanced plans preserve SQL steps and only correct invalid API operations
*   🔄 Test precise endpoint filtering to ensure only relevant endpoints are provided to Step Enhancer
*   ⏳ Performance testing to ensure enhancement doesn't add significant latency

**5.5 Benefits of Step Enhancement**

1.  **Strategic Optimization:** Plans are optimized holistically rather than step-by-step during execution
2.  **Okta-Aware Intelligence:** Deep understanding of Okta relationships and dependencies
3.  **Proactive Problem Solving:** Fixes potential issues before execution begins
4.  **Performance Gains:** Better endpoint selection and step ordering improve overall efficiency
5.  **Future-Proofing:** Provides framework for increasingly sophisticated planning logic

**5.6 Backward Compatibility**

The implementation will maintain full backward compatibility:
*   If Step Enhancer Agent fails, the system falls back to the original plan
*   Existing agents and execution logic remain unchanged
*   No breaking changes to APIs or data flow patterns

This Step Enhancer Agent represents a significant advancement in the system's intelligence while maintaining the proven, high-performance architecture that leverages the right tool for each job.

**Current Status**: The Step Enhancer Agent is **fully implemented and integrated** with precise endpoint filtering. The core agent, validation-focused system prompt, and ModernExecutionManager integration have been completed following established patterns. The system now uses precise endpoint filtering to provide only relevant endpoints to the Step Enhancer Agent, which validates API endpoints without modifying SQL steps. Ready for comprehensive testing to ensure the validation-focused approach works correctly.
