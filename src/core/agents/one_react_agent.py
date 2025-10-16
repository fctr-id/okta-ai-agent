"""
ReAct Agent for Okta Query Execution
Single agent with 7 tools for reasoning and acting on hybrid GraphDB + API queries

This agent follows the ReAct (Reasoning + Acting) pattern:
1. Reason about what data is needed
2. Act by calling tools to gather information
3. Observe results and decide next steps
4. Repeat until query is answered or max retries exceeded
"""

from pydantic_ai import Agent, RunContext
from pydantic_ai.toolsets import FunctionToolset
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Dict, Any, Optional, Literal
from dataclasses import dataclass
import logging
import json
import os
from pathlib import Path

from src.utils.logging import get_logger, set_correlation_id, get_default_log_dir

# Setup centralized logging
logger = get_logger("okta_ai_agent", log_dir=get_default_log_dir())

# Use the model picker approach for consistent model configuration
try:
    from src.core.models.model_picker import ModelConfig, ModelType
    model = ModelConfig.get_model(ModelType.CODING)
except ImportError:
    # Fallback to simple model configuration
    logger.warning("Could not import model_picker, using fallback model configuration")
    model = os.getenv('LLM_MODEL', 'openai:gpt-4o-mini')

# ============================================================================
# Dependencies (Dataclass for PydanticAI)
# ============================================================================

@dataclass
class ReactAgentDependencies:
    """Dependencies injected into ReAct agent"""
    correlation_id: str
    endpoints: List[Dict[str, Any]]  # Full endpoint details (for Tool 3)
    lightweight_entities: Dict[str, Any]  # Lightweight entity-operation mapping (for Tool 2)
    graph_schema: Dict[str, Any]
    okta_client: Any  # OktaClient instance
    kuzu_connection: Any  # Kuzu connection
    operation_mapping: Dict[str, Any]
    user_query: str  # Original user query for context

# ============================================================================
# Structured Outputs
# ============================================================================

class ExecutionResult(BaseModel):
    """Final execution result from ReAct agent"""
    success: bool
    results: Optional[Any] = None
    execution_plan: str
    steps_taken: List[str]
    error: Optional[str] = None
    complete_production_code: str = ""  # REQUIRED: The final, complete, runnable Python script to reproduce results

# ============================================================================
# Tool Implementations
# ============================================================================

def create_react_toolset(deps: ReactAgentDependencies) -> FunctionToolset:
    """Create function toolset with all 7 tools for the ReAct agent"""
    
    toolset = FunctionToolset()
    # ========================================================================
    # Tool 1: Load GraphDB Schema
    # ========================================================================
    
    async def load_graph_schema() -> Dict[str, Any]:
        """
        Load GraphDB schema to understand what data is available in the graph.
        
        Returns:
            Confirmation that schema is available (actual schema already in system prompt)
        """
        logger.info(f"[{deps.correlation_id}] Tool 1: Loading GraphDB schema")
        
        # Schema is already in the system prompt via dynamic instructions
        # Just confirm it's available - don't duplicate the large text
        return {
            "status": "Schema loaded and available in your system context",
            "note": "The complete GraphDB schema with all node types, relationships, and examples is already in your instructions. Use it to understand what data is available."
        }
    
    # ========================================================================
    # Tool 2: Load Comprehensive API Endpoints
    # ========================================================================
    
    async def load_comprehensive_api_endpoints() -> Dict[str, Any]:
        """
        Load lightweight summary of all API entities and operations.
        Does NOT include full endpoint details (parameters, descriptions).
        
        Returns:
            Dictionary with entity names, operation names, and counts
        """
        logger.info(f"[{deps.correlation_id}] Tool 2: Loading comprehensive API endpoints (lightweight)")
        
        # Use lightweight_entities directly instead of parsing endpoints
        entities = deps.lightweight_entities
        
        # Add operation counts
        result_entities = {}
        for entity_name, entity_data in entities.items():
            result_entities[entity_name] = {
                'operations': entity_data.get('operations', []),
                'methods': entity_data.get('methods', ['GET']),  # Default to GET if not specified
                'operation_count': len(entity_data.get('operations', []))
            }
        
        result = {
            "entities": result_entities,
            "total_entities": len(result_entities),
            "total_operations": sum(e['operation_count'] for e in result_entities.values())
        }
        
        logger.info(f"[{deps.correlation_id}] Loaded {result['total_entities']} entities with {result['total_operations']} operations")
        
        return result
    
    # ========================================================================
    # Tool 3: Filter Endpoints by Entities
    # ========================================================================
    
    async def filter_endpoints_by_entities(
        entity_names: List[str],
        include_operations: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Get FULL detailed endpoint information for specified entities.
        
        Args:
            entity_names: List of entity names to get details for
            include_operations: Optional list of specific operations to include
        
        Returns:
            Dictionary with full endpoint details for selected entities
        """
        logger.info(f"[{deps.correlation_id}] Tool 3: Filtering endpoints for entities: {entity_names}")
        
        endpoint_based_entities = {}
        filtered_entity_summary = {}
        all_endpoints = []
        
        for entity_name in entity_names:
            entity_lower = entity_name.lower()
            entity_endpoints = []
            
            # Get all endpoints for this entity
            for endpoint in deps.endpoints:
                if endpoint.get('entity', '').lower() == entity_lower:
                    # Apply operation filter if provided
                    if include_operations:
                        endpoint_op = endpoint.get('operation', '')
                        if endpoint_op not in include_operations:
                            continue
                    
                    # Security validation
                    from src.core.security import validate_api_endpoint
                    security_result = validate_api_endpoint(endpoint)
                    if security_result.is_valid:
                        entity_endpoints.append(endpoint)
                    else:
                        logger.warning(f"Endpoint filtered for security: {endpoint.get('id', 'unknown')} - {'; '.join(security_result.violations)}")
            
            if entity_endpoints:
                # Store full endpoint details
                endpoint_based_entities[entity_name] = {
                    'endpoints': entity_endpoints
                }
                
                # Build summary
                filtered_entity_summary[entity_name] = {
                    'operations': [],
                    'methods': []
                }
                
                for ep in entity_endpoints:
                    operation = ep.get('operation', '')
                    method = ep.get('method', 'GET')
                    
                    if operation and operation not in filtered_entity_summary[entity_name]['operations']:
                        filtered_entity_summary[entity_name]['operations'].append(operation)
                    if method and method not in filtered_entity_summary[entity_name]['methods']:
                        filtered_entity_summary[entity_name]['methods'].append(method)
                
                all_endpoints.extend(entity_endpoints)
        
        result = {
            "endpoint_based_entities": endpoint_based_entities,
            "filtered_entity_summary": filtered_entity_summary,
            "total_endpoints_returned": len(all_endpoints)
        }
        
        logger.info(f"[{deps.correlation_id}] Filtered to {len(all_endpoints)} endpoints for {len(entity_names)} entities")
        
        return result
    
    # ========================================================================
    # Tool 4: Get DB Code Generation Prompt (NOT a code generator!)
    # ========================================================================
    
    async def get_db_code_generation_prompt(
        query_description: str,
        limit: int = 3
    ) -> Dict[str, Any]:
        """
        Get the prompt template for generating Cypher queries.
        The ReAct agent itself will generate the code using this guidance.
        
        Args:
            query_description: Natural language description of what to query
            limit: Number of records to return (default 3 for testing)
        
        Returns:
            Dictionary with code generation prompt and guidelines (schema already in system context)
        """
        logger.info(f"[{deps.correlation_id}] Tool 4: Getting DB code generation prompt")
        
        # Load Cypher generation prompt from file
        cypher_prompt_file = Path(__file__).parent / "prompts" / "cypher_code_gen_agent_system_prompt.txt"
        try:
            with open(cypher_prompt_file, 'r', encoding='utf-8') as f:
                cypher_prompt = f.read()
        except FileNotFoundError:
            cypher_prompt = """Generate a Kuzu-compatible Cypher query.
            
Rules:
- Use MATCH for querying nodes and relationships
- Always include LIMIT clause for safety
- Use proper node labels from the schema in your system context
- Use proper relationship types from the schema in your system context
- Return only the data requested
"""
        
        # Schema is already in system prompt - don't duplicate it here
        return {
            "code_generation_prompt": cypher_prompt,
            "query_task": query_description,
            "limit": limit,
            "instructions": f"""
Based on the query task: "{query_description}"

The complete GraphDB schema is already in your system context above. Refer to it for:
- Exact node type names (e.g., User, OktaGroup, Application)
- Exact relationship type names (e.g., MEMBER_OF, HAS_ACCESS)
- Available properties for each node type
- Query examples

YOU MUST GENERATE A CYPHER QUERY that:
1. Uses ONLY the exact node and relationship names from the schema in your system context
2. Includes 'LIMIT {limit}' for testing
3. Returns the requested data fields
4. Uses proper MATCH patterns for graph traversal

DO NOT invent or assume node/relationship names. Use ONLY what you see in the schema above.

Your generated Cypher query should be executable directly on Kuzu GraphDB.
RETURN THE CYPHER QUERY IN YOUR RESPONSE.
""",
            "example_pattern": "MATCH (u:User)-[:MEMBER_OF]->(g:OktaGroup) WHERE g.name = 'group-name' RETURN u.email, u.login LIMIT 3"
        }
    
    # ========================================================================
    # Tool 5: Get API Code Generation Prompt (NOT a code generator!)
    # ========================================================================
    
    async def get_api_code_generation_prompt(
        query_description: str,
        endpoints: List[Dict[str, Any]],
        max_results: int = 3
    ) -> Dict[str, Any]:
        """
        Get the prompt template for generating Python API code.
        The ReAct agent itself will generate the code using this guidance.
        
        Args:
            query_description: Natural language description of what to fetch
            endpoints: List of endpoint details to use
            max_results: Maximum number of records to return (default 3 for testing)
        
        Returns:
            Dictionary with code generation prompt and guidelines
        """
        logger.info(f"[{deps.correlation_id}] Tool 5: Getting API code generation prompt")
        
        # Load API code generation prompt from file
        api_prompt_file = Path(__file__).parent / "prompts" / "api_code_gen_agent_system_prompt.txt"
        try:
            with open(api_prompt_file, 'r', encoding='utf-8') as f:
                api_prompt = f.read()
        except FileNotFoundError:
            api_prompt = """Generate Python code using the Okta SDK to fetch data from the API.
            
Rules:
- Use the OktaAPIClient available as deps.okta_client
- Always add max_results={max_results} to paginated calls for testing
- Use async/await for API calls
- Handle errors gracefully
- Return structured data (list of dicts)
"""
        
        return {
            "code_generation_prompt": api_prompt,
            "query_task": query_description,
            "max_results": max_results,
            "available_endpoints": endpoints,
            "okta_client_available": "YES - Use 'client' or 'okta_client' variable (pre-injected, DO NOT IMPORT)",
            "critical_instructions": """
🚨 CRITICAL EXECUTION REQUIREMENTS (MATCHES PRODUCTION API CODE GEN):

1. **NO IMPORTS** - All modules already available (client, asyncio, etc.)
2. **NO FUNCTION CALL** - Generate ONLY the async function definition
3. **USE PRE-INJECTED CLIENT** - Variable 'client' is already available
4. **RETURN DATA** - Your function must return the results
5. **NO GLOBALS/LOCALS** - Security violation!

EXECUTION ENVIRONMENT (PRE-INJECTED):
- client: OktaAPIClient instance (READY TO USE)
- okta_client: Alias for client
- asyncio: Already imported

YOUR CODE MUST BE EXACTLY THIS STRUCTURE:
```python
async def fetch_users_in_group():
    # Step 1: Find the group
    groups_response = await client.make_request(
        endpoint="/api/v1/groups",
        method="GET",
        params={"q": "sso-super-admins"}
    )
    
    if groups_response["status"] != "success":
        return []
    
    groups = groups_response.get("data", [])
    if not groups:
        return []
    
    group_id = groups[0]["id"]
    
    # Step 2: Get group members (use max_results for total limit)
    members_response = await client.make_request(
        endpoint=f"/api/v1/groups/{group_id}/users",
        method="GET",
        max_results=3  # Limit total results returned (handles pagination)
    )
    
    if members_response["status"] == "success":
        return members_response.get("data", [])
    
    return []
```
        return []
    
    group_id = groups[0]["id"]
    
    # Step 2: Get group members
    members_response = await client.make_request(
        endpoint=f"/api/v1/groups/{group_id}/users",
        method="GET"
    )
    
    if members_response["status"] == "success":
        return members_response.get("data", [])
    
    return []
```

FORBIDDEN IN YOUR CODE:
- import statements (asyncio, json, client imports)
- Function call line (results = await function_name())
- asyncio.run()
- globals(), locals()
- __file__, os.path, sys.path
""",
            "instructions": f"""
Generate Python code for: "{query_description}"

🚨 REACT AGENT MODE - CRITICAL INSTRUCTIONS:
- You are in a ReAct agent loop - each iteration is ONE API call
- If you observed data from a previous step, HARDCODE the values you saw
- DO NOT use 'full_results' or 'previous_step_key' - those are for other agents!
- Use SPECIFIC IDs/values from your observations in previous tool calls

REQUIREMENTS:
1. Define ONE async function (name it descriptively)
2. Use pre-injected 'client' variable (NO imports!)
3. If you have IDs from previous observations, HARDCODE them in the code
4. Return the final data as a list
5. For testing: Use max_results={max_results} parameter to limit total results returned
6. Handle errors gracefully (return empty list on failure)

📋 REQUIRED FIELDS MANDATE:
When fetching entities via API, you MUST request core fields for complete context:
- **Users**: id, profile.email, profile.login, profile.firstName, profile.lastName, status
- **Groups**: id, profile.name, profile.description
- **Applications**: id, label, name, status
- **Factors**: id, factorType, provider, status
*(If user requests specific fields, include those PLUS the core fields)*

CODE STRUCTURE TEMPLATE:
```python
async def your_descriptive_function_name():
    # If you observed group_id = "00g123..." in previous step, use it directly:
    group_id = "00g123..."  # Hardcoded from observation
    
    # Your API logic here using 'client'
    response = await client.make_request(
        endpoint=f"/api/v1/groups/{{group_id}}/users",
        method="GET",
        max_results={max_results}  # Use max_results parameter, NOT params={{"max_results": N}} or limit
    )
    
    if response["status"] == "success":
        return response.get("data", [])
    
    return []
```

REMEMBER:
- NO imports (client is pre-injected)
- NO function call (we'll call it)
- NO 'full_results' or 'previous_step_key' (not available!)
- HARDCODE observed values from previous steps
- JUST the async function definition
- RETURN the data

Your generated Python code will be executed with exec() where 'client' is already available.
""",
            "example_pattern": """
# Example pattern:
async def fetch_data():
    response = await client.make_request(
        endpoint="/api/v1/users",
        method="GET",
        max_results=3
    )
    if response["status"] == "success":
        return response.get("data", [])
    return []
"""
        }
    
    # ========================================================================
    # Tool 6: Execute Test Query (executes code generated by the agent)
    # ========================================================================
    
    async def execute_test_query(
        code: str,
        code_type: Literal["cypher", "python_sdk"]
    ) -> Dict[str, Any]:
        """
        Execute test query and return sample results.
        
        For python_sdk type:
        - Generate ONLY the async function with Okta API logic
        - We will wrap it with client setup and execution boilerplate
        - Use 'client' variable for OktaAPIClient calls
        - Store final data in 'results' variable
        
        Example - You generate this:
        ```python
        async def fetch_data():
            response = await client.make_request(
                endpoint="/api/v1/users",
                method="GET",
                params={"limit": 3}
            )
            return response.get('data', [])
        
        results = await fetch_data()
        ```
        
        Args:
            code: Generated code from Tool 4 or Tool 5
            code_type: Type of code to execute
        
        Returns:
            Dictionary with execution results and metadata
        """
        logger.info(f"[{deps.correlation_id}] Tool 6: Executing test query (type: {code_type})")
        
        # Log the generated code for debugging
        logger.debug(f"[{deps.correlation_id}] Generated code to execute:\n{code}")
        
        import time
        
        start_time = time.time()
        
        try:
            if code_type == "cypher":
                # Execute Cypher query against Kuzu
                cursor = deps.kuzu_connection.execute(code)
                results = cursor.get_as_pl()  # Returns Polars DataFrame
                
                # Convert to list of dicts
                if results is not None and len(results) > 0:
                    sample_results = results.to_dicts()
                    columns = results.columns
                else:
                    sample_results = []
                    columns = []
                
                execution_time_ms = int((time.time() - start_time) * 1000)
                
                return {
                    "success": True,
                    "sample_results": sample_results,
                    "total_records": len(sample_results),
                    "execution_time_ms": execution_time_ms,
                    "columns": columns,
                    "error": None
                }
            
            elif code_type == "python_sdk":
                # Execute Python SDK code
                # We're already in an async context
                import asyncio
                
                # Create namespace with okta_client available
                namespace = {
                    'client': deps.okta_client,
                    'okta_client': deps.okta_client,
                    'asyncio': asyncio
                }
                
                # Wrap code in async function to handle await statements
                # API/SDK code - extract function name and call it
                import re
                func_match = re.search(r'async\s+def\s+(\w+)\s*\(', code)
                if not func_match:
                    return ExecutionResult(
                        success=False,
                        error_message="Generated code must define an async function starting with 'async def function_name():'",
                        execution_time=0.0,
                        complete_production_code=""
                    )
                
                func_name = func_match.group(1)
                
                # Wrap: define the function inside a wrapper, call it, and return results
                wrapped_code = f"""async def __exec_wrapper__():
{chr(10).join('    ' + line for line in code.split(chr(10)))}
    return await {func_name}()
"""
                
                # Log the wrapped code for debugging
                logger.debug(f"[{deps.correlation_id}] Wrapped code:\n{wrapped_code}")
                
                # Execute to define the wrapper function in namespace
                exec(wrapped_code, namespace)
                
                # Now await the wrapper coroutine (we're in an async context)
                results = await namespace['__exec_wrapper__']()
                
                # Convert to list if needed
                if not isinstance(results, list):
                    results = [results]
                
                execution_time_ms = int((time.time() - start_time) * 1000)
                
                return {
                    "success": True,
                    "sample_results": results[:3],  # Limit to 3 for testing
                    "total_records": len(results),
                    "execution_time_ms": execution_time_ms,
                    "columns": list(results[0].keys()) if results and isinstance(results[0], dict) else [],
                    "error": None
                }
            
            else:
                return {
                    "success": False,
                    "sample_results": None,
                    "total_records": 0,
                    "execution_time_ms": 0,
                    "columns": [],
                    "error": f"Unknown code_type: {code_type}"
                }
        
        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            logger.error(f"[{deps.correlation_id}] Test execution failed: {e}", exc_info=True)
            
            return {
                "success": False,
                "sample_results": None,
                "total_records": 0,
                "execution_time_ms": execution_time_ms,
                "columns": [],
                "error": str(e)
            }
    
    # ========================================================================
    # Tool 7: Generate Production Code
    # ========================================================================
    
    async def generate_production_code(
        test_code: str,
        test_results: Dict[str, Any],
        code_type: Literal["cypher", "python_sdk"]
    ) -> Dict[str, Any]:
        """
        Generate production-ready code based on validated test code.
        
        Args:
            test_code: Validated test code from Tool 4 or Tool 5
            test_results: Results from Tool 6 execution
            code_type: Type of code to generate
        
        Returns:
            Dictionary with production code and optimizations applied
        """
        logger.info(f"[{deps.correlation_id}] Tool 7: Generating production code (type: {code_type})")
        
        import re
        
        production_code = test_code
        optimizations_applied = []
        
        if code_type == "cypher":
            # Remove LIMIT clause for full dataset
            limit_pattern = r'\s+LIMIT\s+\d+\s*$'
            if re.search(limit_pattern, production_code, re.IGNORECASE):
                production_code = re.sub(limit_pattern, '', production_code, flags=re.IGNORECASE)
                optimizations_applied.append("Removed LIMIT clause for full dataset")
        
        elif code_type == "python_sdk":
            # Remove max_results parameter from API calls for production (fetch all)
            max_results_pattern = r'max_results\s*=\s*\d+'
            if re.search(max_results_pattern, production_code):
                production_code = re.sub(max_results_pattern, '', production_code)
                # Clean up any trailing comma/whitespace issues
                production_code = re.sub(r',\s*\)', ')', production_code)
                optimizations_applied.append("Removed max_results limit for production (fetch all data)")
        
        return {
            "production_code": production_code,
            "code_explanation": f"Production version of test code with optimizations",
            "optimizations_applied": optimizations_applied,
            "original_test_code": test_code
        }
    
    # Add all tools to the toolset (6 tools total - Phase 1 & 2 only)
    toolset.tool(load_graph_schema)
    toolset.tool(load_comprehensive_api_endpoints)
    toolset.tool(filter_endpoints_by_entities)
    toolset.tool(get_db_code_generation_prompt)
    toolset.tool(get_api_code_generation_prompt)
    toolset.tool(execute_test_query)
    # Note: generate_production_code removed - agent synthesizes final script directly
    
    return toolset

# ============================================================================
# ReAct Agent Definition
# ============================================================================

# Load system prompt from file
PROMPT_FILE = Path(__file__).parent / "prompts" / "one_react_agent_prompt.txt"

try:
    with open(PROMPT_FILE, 'r', encoding='utf-8') as f:
        BASE_SYSTEM_PROMPT = f.read()
except FileNotFoundError:
    logger.warning(f"Prompt file not found: {PROMPT_FILE}. Using default prompt.")
    BASE_SYSTEM_PROMPT = "You are a ReAct agent for Okta query execution."

# Create the ReAct agent using the same pattern as api_code_gen_agent
react_agent = Agent(
    model,  # Use model from model_picker
    instructions=BASE_SYSTEM_PROMPT,  # Static base instructions
    output_type=ExecutionResult,
    deps_type=ReactAgentDependencies,
    retries=0  # No retries to avoid wasting money on failed attempts
)

@react_agent.instructions  
def create_dynamic_instructions(ctx: RunContext[ReactAgentDependencies]) -> str:
    """Create dynamic instructions with context from dependencies"""
    deps = ctx.deps
    
    # Get the full schema text for the LLM
    schema_text = deps.graph_schema.get("schema_text", "")
    
    # Build dynamic context with the FULL schema text
    dynamic_context = f"""

DYNAMIC CONTEXT FOR THIS REQUEST:
- User Query: {deps.user_query}
- Correlation ID: {deps.correlation_id}
- Available API Endpoints: {len(deps.endpoints)} total

COMPLETE GRAPHDB SCHEMA:
{schema_text}

⚠️ IMPORTANT REMINDER - CODE GENERATION WORKFLOW:
1. When you need to generate Cypher code:
   - FIRST: Call get_db_code_generation_prompt(query_description, limit=3) to get Cypher generation rules
   - SECOND: READ the returned guidance carefully
   - THIRD: WRITE your Cypher code using the SCHEMA ABOVE and the generation rules
   - FOURTH: Call execute_test_query(your_code, "cypher")

2. When you need to generate Python SDK code:
   - FIRST: Call get_api_code_generation_prompt(query_description, endpoints, max_results=3)
   - SECOND: READ the returned data carefully
   - THIRD: WRITE your Python code based on that guidance
   - FOURTH: Call execute_test_query(your_code, "python_sdk")

The schema above shows you EXACTLY what node types (User, OktaGroup, Application, etc.) and 
relationship types (MEMBER_OF, HAS_ACCESS, etc.) exist. DO NOT invent names - use only what you see above.

Remember to follow the workflow:
1. Load graph schema first (unless user says "API only")
2. Determine if data is in GraphDB or needs API
3. Load comprehensive API endpoints if needed
4. Filter to specific entities
5. Get code generation prompt (Tool 4 or 5)
6. Generate YOUR code using the prompt guidance
7. Execute and inspect results
8. Generate production code
9. Return ExecutionResult
"""
    
    return dynamic_context

# ============================================================================
# Main Execution Function
# ============================================================================

async def execute_react_query(
    user_query: str,
    deps: ReactAgentDependencies
) -> ExecutionResult:
    """
    Execute user query using ReAct agent with 7 tools.
    
    Args:
        user_query: Natural language query from user
        deps: Dependencies for agent (endpoints, schema, clients, etc.)
    
    Returns:
        ExecutionResult with success status and results
    """
    logger.info(f"[{deps.correlation_id}] Starting ReAct agent execution for query: {user_query}")
    
    # Create toolset with dependencies
    toolset = create_react_toolset(deps)
    
    # Run agent with toolset
    result = await react_agent.run(
        user_query,
        deps=deps,
        toolsets=[toolset]  # Pass toolset as list
    )
    
    # Access the output from the result (PydanticAI returns output, not data)
    execution_result = result.output
    
    # Log synthesis phase completion
    if execution_result.complete_production_code:
        logger.info(f"[{deps.correlation_id}] ✅ SYNTHESIS COMPLETE: Generated final production code ({len(execution_result.complete_production_code)} chars)")
    else:
        logger.warning(f"[{deps.correlation_id}] ⚠️ SYNTHESIS INCOMPLETE: No production code generated")
    
    logger.info(f"[{deps.correlation_id}] ReAct agent completed: success={execution_result.success}")
    
    return execution_result
