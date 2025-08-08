"""
Planning Agent - Hybrid Query Planning with PydanticAI

Converts user queries into structured execution plans for the Okta AI system.
Enhanced architecture with PydanticAI v0.4.3 integration:
- Dependency injection for dynamic context
- Structured output validation 
- Token counting and cost tracking
- Model retries and exception handling
- Centralized logging with correlation ID support
"""

import asyncio
import json
import os
from typing import Optional
import sys
import re
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from pydantic import BaseModel, Field, ConfigDict
from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import ModelRetry, UnexpectedModelBehavior, UsageLimitExceeded
from dotenv import load_dotenv

# Add src path for importing utils
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from src.utils.logging import get_logger, generate_correlation_id, set_correlation_id, get_default_log_dir

load_dotenv()

# Setup centralized logging with file output
# Using main "okta_ai_agent" namespace for unified logging across all agents
logger = get_logger("okta_ai_agent", log_dir=get_default_log_dir())

# Use the model picker approach for consistent model configuration
try:
    from src.core.models.model_picker import ModelConfig, ModelType
    model = ModelConfig.get_model(ModelType.REASONING)
except ImportError:
    # Fallback to simple model configuration
    def get_simple_model():
        """Simple model configuration without complex imports"""
        model_name = os.getenv('LLM_MODEL', 'gpt-4')
        return model_name
    model = get_simple_model()

@dataclass
class PlanningDependencies:
    """Dependencies for the Planning Agent with dynamic context"""
    available_entities: List[str]
    entity_summary: Dict[str, Any]
    sql_tables: Dict[str, Any]
    flow_id: str = ""  # Correlation ID for flow tracking
    entities: Optional[Dict[str, Any]] = None  # New entity-grouped format

class ExecutionStep(BaseModel):
    """Individual execution step in the plan"""
    
    tool_name: str = Field(
        description='Execution method: "sql" or "api"',
        pattern=r'^(sql|api)$'
    )
    entity: str = Field(
        description='The actual entity/table name (e.g., "users", "system_log", "groups")',
        min_length=1
    )
    operation: Optional[str] = Field(
        description='Exact operation name for API steps, null for SQL steps',
        default=None
    )
    query_context: str = Field(
        description='Detailed description of what data to collect',
        min_length=1
    )
    critical: bool = Field(
        description='Whether this step is critical for the overall execution',
        default=True
    )
    reasoning: str = Field(
        description='Why this step is needed in the overall execution plan',
        min_length=1
    )

class ExecutionPlan(BaseModel):
    """Execution plan within the response"""
    steps: List[ExecutionStep] = Field(
        description='Ordered list of execution steps',
        min_items=1
    )
    reasoning: str = Field(
        description='High-level reasoning for the chosen approach',
        min_length=10
    )
    partial_success_acceptable: Optional[bool] = Field(
        description='Whether partial success is acceptable',
        default=True
    )

class PlanningResponse(BaseModel):
    """Complete planning response structure that matches system prompt format"""
    plan: ExecutionPlan = Field(
        description='Execution plan with steps and reasoning'
    )
    confidence: int = Field(
        description='Confidence level in the execution plan (0-100)',
        ge=0,
        le=100
    )

class PlanningOutput(BaseModel):
    """Output structure for the Planning Agent - matches system prompt format"""
    plan: ExecutionPlan = Field(
        description='The complete execution plan for the user query'
    )
    confidence: int = Field(
        description='Confidence level in the execution plan (0-100)',
        ge=0,
        le=100
    )

# Load system prompt from file
def load_system_prompt(deps: PlanningDependencies) -> str:
    """Load and customize system prompt with dynamic context"""
    system_prompt_path = os.path.join(os.path.dirname(__file__), "prompts", "planning_agent_system_prompt.txt")
    
    try:
        with open(system_prompt_path, 'r', encoding='utf-8') as f:
            base_prompt = f.read()
        
        # Build dynamic entity operations text
        entity_operations_text = []
        for entity, details in deps.entity_summary.items():
            operations = details.get('operations', [])
            methods = details.get('methods', [])
            entity_operations_text.append(f"  • {entity}: operations=[{', '.join(operations)}], methods=[{', '.join(methods)}]")
        
        entities_with_operations = "\n".join(entity_operations_text)
        
        # Build SQL schema information
        sql_table_names = list(deps.sql_tables.keys())
        sql_schema_text = []
        for table_name, table_info in deps.sql_tables.items():
            columns = table_info.get('columns', [])
            column_names = [col['name'] if isinstance(col, dict) else str(col) for col in columns]
            sql_schema_text.append(f"  • {table_name}: columns=[{', '.join(column_names[:10])}{'...' if len(column_names) > 10 else ''}]")
        
        sql_schema_info = "\n".join(sql_schema_text)
        
        # Create complete dynamic section
        complete_section = f"""

AVAILABLE ENTITIES AND OPERATIONS:
{entities_with_operations}

AVAILABLE SQL TABLES AND SCHEMAS:
{sql_schema_info}

API ENTITIES: {deps.available_entities}
SQL TABLES: {sql_table_names}"""
        
        # Replace the placeholder section with dynamic content
        pattern = r"AVAILABLE ENTITIES AND OPERATIONS:.*?(?=\n\n[A-Z]|\Z)"
        if re.search(pattern, base_prompt, flags=re.DOTALL):
            updated_prompt = re.sub(pattern, complete_section.strip(), base_prompt, flags=re.DOTALL)
            logger.debug(f"[{deps.flow_id}] Updated AVAILABLE ENTITIES section with dynamic content")
        else:
            # Fallback: append dynamic content
            updated_prompt = base_prompt + f"\n{complete_section}"
            logger.debug(f"[{deps.flow_id}] Appended dynamic content to system prompt")
        
        logger.debug(f"[{deps.flow_id}] System prompt built with {len(deps.available_entities)} entities, {len(deps.sql_tables)} SQL tables")
        
        return updated_prompt
        
    except Exception as e:
        logger.error(f"[{deps.flow_id}] Failed to load system prompt: {e}")
        # Return a basic fallback prompt
        return """You are a hybrid query planner. Create execution plans with 'plan' containing 'entities', 'steps', 'reasoning', and 'confidence'."""

# Load base system prompt for static instructions
def load_base_system_prompt() -> str:
    """Load the base system prompt from file for static instructions"""
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        prompt_path = os.path.join(script_dir, "prompts", "planning_agent_system_prompt.txt")
        
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        logger.error(f"Failed to load base system prompt file: {e}")
        return "You are a HYBRID query planner for an Okta system."

# Create the Planning Agent with PydanticAI
planning_agent = Agent(
    model,
    output_type=PlanningOutput,  # ✅ MODERN: Use output_type not deprecated result_type
    deps_type=PlanningDependencies,
    retries=0,  # No retries to avoid wasting money on failed attempts
    instructions=load_base_system_prompt()  # Static base instruction from file
)

@planning_agent.instructions
def get_dynamic_instructions(ctx: RunContext[PlanningDependencies]) -> str:
    """Dynamic instructions that include current context with full endpoint details"""
    deps = ctx.deps
    
    # ALWAYS extract full endpoint details for planning decisions
    api_entities = {}
    
    # Primary: Use filtered entities with full endpoint details
    if hasattr(deps, 'entities') and deps.entities and isinstance(deps.entities, dict):
        logger.debug(f"[{deps.flow_id}] Using filtered entities with full endpoint details: {len(deps.entities)} entities")
        # Extract full endpoint information for each entity
        for entity_name, entity_data in deps.entities.items():
            endpoints = entity_data.get('endpoints', [])
            
            # Build comprehensive endpoint details for planning
            entity_endpoints = []
            for endpoint in endpoints:
                # Extract ALL endpoint information for planning decisions
                endpoint_info = {
                    "id": endpoint.get('id', ''),
                    "operation": endpoint.get('operation', ''),
                    "method": endpoint.get('method', 'GET'),
                    "url_pattern": endpoint.get('url_pattern', ''),
                    "name": endpoint.get('name', ''),
                    "description": endpoint.get('description', ''),
                    "parameters": endpoint.get('parameters', {}),
                    "depends_on": endpoint.get('depends_on', []),
                    "notes": endpoint.get('notes', '')  # Include FULL notes for planning
                }
                entity_endpoints.append(endpoint_info)
            
            # Store full endpoint details for this entity
            api_entities[entity_name] = {
                "endpoints": entity_endpoints,
                "total_endpoints": len(endpoints)
            }
        logger.debug(f"[{deps.flow_id}] Built comprehensive endpoint details for {len(api_entities)} entities")
    
    # Fallback: Use available_entities if they have endpoint details
    elif hasattr(deps, 'available_entities') and deps.available_entities and isinstance(deps.available_entities, dict):
        logger.debug(f"[{deps.flow_id}] FALLBACK: Using available_entities for endpoint details")
        for entity_name, entity_data in deps.available_entities.items():
            if isinstance(entity_data, dict) and 'endpoints' in entity_data:
                endpoints = entity_data.get('endpoints', [])
                
                # Build comprehensive endpoint details
                entity_endpoints = []
                for endpoint in endpoints:
                    endpoint_info = {
                        "id": endpoint.get('id', ''),
                        "operation": endpoint.get('operation', ''),
                        "method": endpoint.get('method', 'GET'),
                        "url_pattern": endpoint.get('url_pattern', ''),
                        "name": endpoint.get('name', ''),
                        "description": endpoint.get('description', ''),
                        "parameters": endpoint.get('parameters', {}),
                        "depends_on": endpoint.get('depends_on', []),
                        "notes": endpoint.get('notes', '')  # Include FULL notes
                    }
                    entity_endpoints.append(endpoint_info)
                
                api_entities[entity_name] = {
                    "endpoints": entity_endpoints,
                    "total_endpoints": len(endpoints)
                }
    
    # Last resort: Extract from entity_summary with warning
    if not api_entities and hasattr(deps, 'entity_summary') and deps.entity_summary:
        logger.warning(f"[{deps.flow_id}] FALLBACK: Using simplified entity_summary format - endpoint details missing!")
        # This should NOT happen in the new architecture
        # but kept for backward compatibility
        for entity, details in deps.entity_summary.items():
            operations = details.get('operations', [])
            # Convert to simplified format only as absolute fallback
            entity_operations = [f"{entity}_{op}" for op in operations[:8]]
            api_entities[entity] = {"operations": entity_operations}
    
    # Build SQL tables in clean JSON format
    sql_tables = {}
    for table_name, table_info in deps.sql_tables.items():
        columns = table_info.get('columns', [])
        
        # Show key columns for planning
        key_columns = []
        priority_cols = ['id', 'okta_id', 'name', 'email', 'login', 'status', 'user_okta_id', 'group_okta_id', 'application_okta_id']
        
        for col in columns:
            col_name = col['name'] if isinstance(col, dict) else str(col)
            if col_name in priority_cols or 'okta_id' in col_name.lower():
                key_columns.append(col_name)
        
        # Add other important columns
        for col in columns:
            col_name = col['name'] if isinstance(col, dict) else str(col)
            if col_name not in key_columns:
                key_columns.append(col_name)
        
        # Simple clean format - just the columns list
        sql_tables[table_name] = key_columns
    
    # Add parameter efficiency hints for planning decisions
    parameter_hints = {
        "group_list": "supports expand=stats for user counts (avoids separate group_list_members calls) or expand=app for application details",
        "application_list": "supports expand=user/{userId} for user assignment details (REQUIRES user.id eq '{userId}' filter)",
        "application_get": "supports expand=user/{userId} to return specific application user in _embedded (avoids separate user lookup)",
        "application_grants_list": "supports expand=scope to include OAuth scope details in grants (avoids separate scope lookups)",
        "application_grants_get": "supports expand=scope to include OAuth scope details for specific grant",
        "application_groups_list": "supports expand=group to include full group objects instead of just assignment references",
        "application_groups_get": "supports expand=group to include full group object for specific assignment",
        "application_tokens_list": "supports expand=scope to include OAuth scope details in token listings",
        "application_tokens_get": "supports expand=scope to include OAuth scope details for specific token",
        "application_user_list": "supports expand=user for full user objects instead of just assignment references (reduces API calls)",
        "application_user_get": "supports expand=user for full user object instead of just assignment reference",
        "user_list": "supports expand=classification for user metadata (compliance/risk data) without extra calls",
        "user_get": "supports expand=blocks for access restrictions or expand=classification for metadata", 
        "user_list_roles": "supports expand=targets/groups for group targets or expand=targets/catalog/apps for app targets (avoids separate target lookups)",
        "devices_list": "supports expand=user to include associated user details and device management status in _embedded",
        "user_list_devices": "lists devices enrolled by a specific user - available via /users/{userId}/devices endpoint",
        "device_list_users": "lists all users for a specific device - available via /devices/{deviceId}/users endpoint",
        "policy_get": "supports expand=rules to include all policy rules in same response (avoids separate list_policy_rules call)",
        "policy_list": "supports expand=rules to include all policies with their rules in same response (significant efficiency gain)",
        "group_rules_list": "supports expand for additional rule condition and action details",
        "group_rules_get": "supports expand for additional rule condition and action details",
        "group_list_roles": "supports expand for role targets in group role assignments (avoids separate target queries)",
        "yubikey_tokens_list": "supports expand for additional YubiKey token metadata and status details",
        "group_list_members": "INEFFICIENT - prefer expand=stats on group_list for counts instead of fetching all members"
    }
    
    # Create context data with SQL tables, detailed API endpoints, and efficiency hints
    context_data = {
        "sql_tables": sql_tables,
        "api_endpoints": api_entities,  # Changed from api_entities to api_endpoints for clarity
        "parameter_efficiency_hints": parameter_hints
    }
    
    # Debug: Log final context structure
    logger.debug(f"[{deps.flow_id}] Final planning context: {len(context_data['sql_tables'])} SQL tables, {len(context_data['api_endpoints'])} API entities")
    for entity_name, entity_info in context_data['api_endpoints'].items():
        if 'endpoints' in entity_info:
            logger.debug(f"[{deps.flow_id}]   {entity_name}: {len(entity_info['endpoints'])} detailed endpoints")
        else:
            logger.debug(f"[{deps.flow_id}]   {entity_name}: simplified format")
    
    # Custom JSON formatting: readable structure with proper endpoint details
    def format_endpoint_data(data):
        """Format JSON with detailed endpoint information"""
        result = "{\n"
        for i, (key, value) in enumerate(data.items()):
            result += f'  "{key}": {{\n'
            
            if key == "api_endpoints":
                # Special formatting for endpoint details
                for j, (entity_name, entity_data) in enumerate(value.items()):
                    result += f'    "{entity_name}": {{\n'
                    
                    if "endpoints" in entity_data:
                        result += f'      "endpoints": [\n'
                        for k, endpoint in enumerate(entity_data["endpoints"]):
                            result += '        {\n'
                            for attr_name, attr_value in endpoint.items():
                                if isinstance(attr_value, str):
                                    # Escape quotes and handle multi-line strings
                                    escaped_value = attr_value.replace('"', '\\"').replace('\n', '\\n')
                                    result += f'          "{attr_name}": "{escaped_value}",\n'
                                else:
                                    result += f'          "{attr_name}": {json.dumps(attr_value)},\n'
                            result = result.rstrip(',\n') + '\n'  # Remove trailing comma
                            result += '        }'
                            if k < len(entity_data["endpoints"]) - 1:
                                result += ','
                            result += '\n'
                        result += '      ],\n'
                        result += f'      "total_endpoints": {entity_data.get("total_endpoints", 0)}\n'
                    else:
                        # Legacy format fallback
                        for attr_name, attr_value in entity_data.items():
                            array_str = json.dumps(attr_value, separators=(', ', ': '))
                            result += f'      "{attr_name}": {array_str}'
                            if attr_name != list(entity_data.keys())[-1]:
                                result += ","
                            result += "\n"
                    
                    result += '    }'
                    if j < len(value) - 1:
                        result += ","
                    result += "\n"
            else:
                # Standard formatting for other sections
                for j, (sub_key, sub_value) in enumerate(value.items()):
                    array_str = json.dumps(sub_value, separators=(', ', ': '))
                    result += f'    "{sub_key}": {array_str}'
                    if j < len(value) - 1:
                        result += ","
                    result += "\n"
            
            result += "  }"
            if i < len(data) - 1:
                result += ","
            result += "\n"
        result += "}"
        return result
    
    # Return JSON context with detailed endpoint information
    return f"""
AVAILABLE DATA SOURCES (JSON Format):
```json
{format_endpoint_data(context_data)}
```
"""

async def generate_execution_plan(
    query: str,
    available_entities: List[str],
    entity_summary: Dict[str, Any], 
    sql_tables: Dict[str, Any],
    flow_id: str
) -> Dict[str, Any]:
    """
    Generate execution plan using PydanticAI Planning Agent
    
    Args:
        query: User query to plan for
        available_entities: List of available API entities
        entity_summary: Summary of entity operations and methods
        sql_tables: Available SQL tables and schemas
        flow_id: Correlation ID for tracking
        
    Returns:
        Dict with success status and plan or error details
    """
    logger.info(f"[{flow_id}] Planning Agent: Starting execution plan generation")
    logger.debug(f"[{flow_id}] Input query: {query}")
    logger.debug(f"[{flow_id}] Available entities: {len(available_entities)}")
    logger.debug(f"[{flow_id}] SQL tables: {len(sql_tables)}")
    
    try:
        # Set up dependencies with current context
        deps = PlanningDependencies(
            available_entities=available_entities,
            entity_summary=entity_summary,
            sql_tables=sql_tables,
            flow_id=flow_id
        )
        
        # Debug: Log what we're about to send to the agent
        logger.info(f"[{flow_id}] About to call planning agent with query: {query}")
        logger.debug(f"[{flow_id}] Dependencies: entities={len(available_entities)}, sql_tables={len(sql_tables)}")
        
        # Debug: Capture and log the complete system prompt BEFORE calling the agent
        try:
            # Get the static base prompt
            static_prompt = load_base_system_prompt()
            
            # Get the dynamic instructions by creating a mock context
            class MockContext:
                def __init__(self, deps):
                    self.deps = deps
            
            mock_ctx = MockContext(deps)
            dynamic_instructions = get_dynamic_instructions(mock_ctx)
            
            # Log the complete prompt
            logger.info(f"[{flow_id}] === COMPLETE SYSTEM PROMPT START ===")
            logger.info(f"[{flow_id}] STATIC PROMPT:")
            logger.info(f"[{flow_id}] {static_prompt}")
            logger.info(f"[{flow_id}] DYNAMIC INSTRUCTIONS:")
            logger.info(f"[{flow_id}] {dynamic_instructions}")
            logger.info(f"[{flow_id}] === COMPLETE SYSTEM PROMPT END ===")
        except Exception as e:
            logger.error(f"[{flow_id}] Failed to capture system prompt for debugging: {e}")
        
        # Generate plan using PydanticAI
        result = await planning_agent.run(query, deps=deps)
        
        # Debug: Dump the complete system prompt and messages
        if hasattr(result, 'all_messages') and result.all_messages():
            logger.info(f"[{flow_id}] FULL SYSTEM PROMPT DEBUG:")
            for i, message in enumerate(result.all_messages()):
                if hasattr(message, 'role') and hasattr(message, 'content'):
                    logger.info(f"[{flow_id}] Message {i} ({message.role}):")
                    logger.info(f"[{flow_id}] Content: {message.content}")
                    logger.info(f"[{flow_id}] ---")
                else:
                    logger.info(f"[{flow_id}] Message {i}: {message}")
        else:
            logger.warning(f"[{flow_id}] Could not access all_messages for prompt debugging")
        
        # Pretty print the execution plan for debugging
        import json
        logger.info(f"[{flow_id}] Generated execution plan:\n{json.dumps(result.output.plan.model_dump(), indent=2)}")
        logger.debug(f"[{flow_id}] Plan confidence: {result.output.confidence}%")
        logger.debug(f"[{flow_id}] Plan steps: {len(result.output.plan.steps)}")
        
        # Token usage tracking
        if hasattr(result, 'usage') and result.usage():
            usage = result.usage()
            input_tokens = getattr(usage, 'request_tokens', getattr(usage, 'input_tokens', 0))
            output_tokens = getattr(usage, 'response_tokens', getattr(usage, 'output_tokens', 0))
            logger.info(f"[{flow_id}] Planning completed - {input_tokens} in, {output_tokens} out tokens")
        
        return {
            'success': True,
            'plan': result.output.plan.model_dump(),
            'confidence': result.output.confidence,
            'usage': {
                'input_tokens': getattr(result.usage(), 'request_tokens', 0) if result.usage() else 0,
                'output_tokens': getattr(result.usage(), 'response_tokens', 0) if result.usage() else 0,
                'total_tokens': getattr(result.usage(), 'total_tokens', 0) if result.usage() else 0
            } if result.usage() else None
        }
        
    except ModelRetry as e:
        logger.error(f"[{flow_id}] Planning retry needed: {e}")
        return {'success': False, 'error': f'Planning retry needed: {e}', 'error_type': 'retry'}
        
    except UnexpectedModelBehavior as e:
        logger.error(f"[{flow_id}] Planning unexpected behavior: {e}")
        return {'success': False, 'error': f'Planning unexpected behavior: {e}', 'error_type': 'behavior'}
        
    except UsageLimitExceeded as e:
        logger.error(f"[{flow_id}] Planning usage limit exceeded: {e}")
        return {'success': False, 'error': f'Planning usage limit exceeded: {e}', 'error_type': 'usage_limit'}
        
    except Exception as e:
        logger.error(f"[{flow_id}] Planning failed: {e}")
        return {'success': False, 'error': f'Planning failed: {e}', 'error_type': 'general'}

# Utility function for extracting JSON (keeping existing functionality)
def extract_json_from_text(text: str) -> dict:
    """Extract JSON from text that might contain markdown code blocks"""
    # Remove markdown code blocks if present
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*$', '', text, flags=re.MULTILINE)
    
    # Find JSON object
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if json_match:
        json_str = json_match.group()
        return json.loads(json_str)
    else:
        # Try to parse the entire text as JSON
        return json.loads(text)