"""
API Code Generation Agent - Python Code Generation with PydanticAI

Converts Okta API plans and SQL data into executable Python code.
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
from typing import Optional, List, Dict, Any
import sys
import re
from dataclasses import dataclass
from pydantic import BaseModel, Field, ConfigDict
from pydantic_ai import Agent, RunContext
from pydantic_ai.toolsets import FunctionToolset

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
    model = ModelConfig.get_model(ModelType.CODING)
except ImportError:
    # Fallback to simple model configuration
    def get_simple_model():
        """Simple model configuration without complex imports"""
        model_name = os.getenv('LLM_MODEL', 'gpt-3.5-turbo')
        return model_name
    model = get_simple_model()

@dataclass
class ApiCodeGenDependencies:
    """Dependencies for the API Code Generation Agent with dynamic context"""
    query: str
    sql_record_count: int
    available_endpoints: List[Dict[str, Any]]
    entities_involved: List[str]
    step_description: str
    flow_id: str = ""  # Correlation ID for flow tracking
    all_step_contexts: Dict[str, Any] = None  # Enhanced context from all previous steps

class CodeGenerationOutput(BaseModel):
    """Structured output for API code generation"""
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "python_code": "import requests\n\n# Generated code here",
            "explanation": "This code fetches user data from Okta API",
            "requirements": ["requests", "python-dotenv"],
            "estimated_execution_time": "2-5 seconds",
            "rate_limit_considerations": "Uses limit=100 parameter to prevent timeouts"
        }
    })

    python_code: str = Field(
        description='Complete Python code that solves the user query by combining SQL data with API calls',
        min_length=5  # Relaxed minimum length for better LLM compatibility
    )
    explanation: str = Field(
        description='Clear explanation of what the code does and how it works',
        min_length=5  # Relaxed minimum length for better LLM compatibility
    )
    requirements: List[str] = Field(
        description='Python package requirements needed to run the code',
        default=[]
    )
    estimated_execution_time: str = Field(
        description='Estimated time to execute the code',
        default="Unknown"
    )
    rate_limit_considerations: str = Field(
        description='Notes about rate limiting and API usage',
        default="Standard Okta rate limits apply"
    )

# Load event types for enhanced toolset
EVENT_TYPES_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "schemas", "Okta_eventTypes.json")
OKTA_EVENT_TYPES = {}

try:
    with open(EVENT_TYPES_PATH, 'r', encoding='utf-8') as f:
        OKTA_EVENT_TYPES = json.load(f)
    logger.info(f"Loaded {len(OKTA_EVENT_TYPES)} event type categories")
except FileNotFoundError:
    logger.warning(f"Event types file not found at {EVENT_TYPES_PATH}")
except json.JSONDecodeError as e:
    logger.error(f"Error parsing event types JSON: {e}")

# Create event types toolset for intelligent event selection
event_types_toolset = FunctionToolset()

@event_types_toolset.tool
def get_detailed_events_from_keys(category_keys: List[str]) -> Dict[str, List[str]]:
    """
    Get detailed event types for selected categories.
    
    Args:
        category_keys: List of event category keys to retrieve
        
    Returns:
        Dict mapping category keys to their event type lists
    """
    result = {}
    all_event_types = []  # Flattened list for convenience
    
    logger.debug(f"Tool called with category_keys: {category_keys}")
    
    for key in category_keys:
        if key in OKTA_EVENT_TYPES:
            result[key] = OKTA_EVENT_TYPES[key]
            all_event_types.extend(OKTA_EVENT_TYPES[key])  # Add to flattened list
            logger.debug(f"Category '{key}': {len(OKTA_EVENT_TYPES[key])} event types")
        else:
            logger.warning(f"Category key '{key}' not found in event types schema")
    
    # Add flattened list for convenience
    if all_event_types:
        result['_all_event_types'] = all_event_types
    
    total_events = sum(len(events) for events in result.values() if not events == all_event_types)
    logger.info(f"Retrieved {total_events} total event types across {len(result)-1 if all_event_types else len(result)} categories")
    
    # Debug: Log the complete tool response
    logger.debug("=== TOOL RESPONSE DEBUG START ===")
    logger.debug(f"Tool: get_detailed_events_from_keys")
    logger.debug(f"Input category_keys: {category_keys}")
    logger.debug(f"Output structure:")
    for category, events in result.items():
        if category == '_all_event_types':
            logger.debug(f"  {category}: [{len(events)} flattened event types]")
            if len(events) <= 5:
                logger.debug(f"    Sample events: {events}")
            else:
                logger.debug(f"    Sample events: {events[:5]}... (+{len(events)-5} more)")
        else:
            logger.debug(f"  {category}: [{len(events)} event types]")
            if len(events) <= 3:
                logger.debug(f"    Events: {events}")
            else:
                logger.debug(f"    Events: {events[:3]}... (+{len(events)-3} more)")
    logger.debug("=== TOOL RESPONSE DEBUG END ===")
    
    return result

# Load system prompt from file
SYSTEM_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "api_code_gen_agent_system_prompt.txt")

try:
    with open(SYSTEM_PROMPT_PATH, 'r', encoding='utf-8') as f:
        BASE_SYSTEM_PROMPT = f.read()
except FileNotFoundError:
    logger.warning(f"System prompt file not found at {SYSTEM_PROMPT_PATH}, using fallback")
    BASE_SYSTEM_PROMPT = """You are an expert Python code generator for Okta API operations.

**GOLDEN RULES - NON-NEGOTIABLE**
1. **`limit=100` ON ALL API CALLS**: Every single API call MUST include `limit=100`. No exceptions.
2. **USE PROVIDED ENDPOINTS ONLY**: Use ONLY the exact API endpoints and methods provided in the context.
3. **FOLLOW THE PLAN**: Implement the execution plan EXACTLY as described.
4. **JSON OUTPUT ONLY**: Your entire response MUST be a single, valid JSON object.

Generate practical, executable Python code that combines SQL data with API calls to solve the user's query."""

# Create the PydanticAI agent with event types toolset
api_code_gen_agent = Agent(
    model,
    instructions=BASE_SYSTEM_PROMPT,  # Static base instructions
    output_type=CodeGenerationOutput,
    deps_type=ApiCodeGenDependencies,
    toolsets=[event_types_toolset],  # Add the event types toolset
    retries=0  # No retries to avoid wasting money on failed attempts
)

@api_code_gen_agent.instructions
def create_dynamic_instructions(ctx: RunContext[ApiCodeGenDependencies]) -> str:
    """Create dynamic instructions with context from dependencies"""
    deps = ctx.deps
    
    # Get available event type categories for the dynamic prompt
    event_type_categories = list(OKTA_EVENT_TYPES.keys()) if OKTA_EVENT_TYPES else ['No event types loaded']
    
    # Build dynamic context
    dynamic_context = f"""

DYNAMIC CONTEXT FOR THIS REQUEST:
- Task: {deps.step_description}
- SQL Records Available: {deps.sql_record_count}
- API Endpoints Available: {len(deps.available_endpoints)}
- Entities: {deps.entities_involved}

ENHANCED CONTEXT - PREVIOUS STEP DATA:
{json.dumps(deps.all_step_contexts, indent=2) if deps.all_step_contexts else 'No previous step data available'}

AVAILABLE API ENDPOINTS WITH COMPLETE DOCUMENTATION:
{json.dumps(deps.available_endpoints, indent=2)}

**AVAILABLE TOOLS FOR EVENT TYPE SELECTION**:
- get_detailed_events_from_keys(category_keys): Get specific event types for selected categories

**AVAILABLE EVENT TYPE CATEGORIES** (for system_log queries):
{event_type_categories}

**WORKFLOW FOR SYSTEM LOG QUERIES**:
1. Review the available event type categories above
2. Select 1-3 MOST relevant categories based on the user's query (e.g., "user-authentication-session" for login queries)
3. Call get_detailed_events_from_keys with your selected category keys
4. From the returned event types, choose only the 5-15 MOST RELEVANT ones for the user's specific query
5. Do NOT use all returned event types - be selective and focus on what the user actually needs

Generate practical, executable code that solves the user's query: {deps.query}"""
    
    return dynamic_context

async def generate_api_code(
    query: str,
    sql_record_count: int,
    available_endpoints: List[Dict[str, Any]],
    entities_involved: List[str],
    step_description: str,
    correlation_id: str,
    all_step_contexts: Dict[str, Any] = None,
    previous_step_key: str = None
) -> Dict[str, Any]:
    """
    Generate Python code for Okta API operations using PydanticAI
    
    Args:
        query: User's original query
        sql_record_count: Total count of SQL records
        available_endpoints: List of filtered API endpoints
        entities_involved: List of entities from planning
        step_description: Description of the step to implement
        correlation_id: Correlation ID for logging
        all_step_contexts: Enhanced context from all previous steps
        previous_step_key: Explicit key for previous step data (e.g., '1_sql')
        
    Returns:
        Dict containing success status, generated code, and metadata
    """
    # Set correlation ID for logging
    set_correlation_id(correlation_id)
    
    logger.info(f"[{correlation_id}] API Code Generation Agent: Starting code generation")
    logger.debug(f"[{correlation_id}] Task: {step_description}")
    logger.debug(f"[{correlation_id}] SQL records: {sql_record_count}, API endpoints: {len(available_endpoints)}")
    
    try:
        # Validate inputs - now using enhanced context instead of sql_data_sample
        if not all_step_contexts and not available_endpoints:
            logger.warning(f"[{correlation_id}] No step contexts or API endpoints available for code generation")
            return {
                'success': False,
                'error': 'No data available for code generation',
                'code': '',
                'explanation': 'No step contexts or API endpoints provided',
                'requirements': [],
                'correlation_id': correlation_id
            }
        
        # Create dependencies (removed sql_data_sample, now using enhanced context)
        dependencies = ApiCodeGenDependencies(
            query=query,
            sql_record_count=sql_record_count,
            available_endpoints=available_endpoints,
            entities_involved=entities_involved,
            step_description=step_description,
            flow_id=correlation_id,
            all_step_contexts=all_step_contexts or {}  # Enhanced context
        )
        
        # Create user message for code generation with enhanced context
        # Extract data structure from enhanced context instead of sql_data_sample
        data_structure = "Available from enhanced context"
        if all_step_contexts:
            # Look for sample data in previous steps
            for key, value in all_step_contexts.items():
                if key.endswith('_sample') and value:
                    if isinstance(value, list) and len(value) > 0:
                        if isinstance(value[0], dict):
                            data_structure = f"Sample data structure: {list(value[0].keys())}"
                        else:
                            data_structure = f"Sample data type: {type(value[0]).__name__}"
                        break
                    elif isinstance(value, dict):
                        data_structure = f"Sample data structure: {list(value.keys())}"
                        break
        
        # Build enhanced context string
        context_info = ""
        if all_step_contexts:
            context_info = "\n\nPREVIOUS STEP CONTEXTS:\n"
            for key, value in all_step_contexts.items():
                if key.endswith('_context'):
                    context_info += f"- {key}: {value}\n"
                elif key.endswith('_sample'):
                    sample_str = str(value)[:100] + "..." if len(str(value)) > 100 else str(value)
                    context_info += f"- {key}: {sample_str}\n"
        
        # Add explicit step key information if provided
        step_key_info = ""
        if previous_step_key:
            step_key_info = f"\n\nPREVIOUS STEP KEY: Use '{previous_step_key}' to access data from the previous step  dict."
        
        user_message = f"Generate Python code for: {step_description}\n\nCurrent Step Data Structure: {data_structure}\nAPI Endpoints: {len(available_endpoints)} available{context_info}{step_key_info}"
        
        logger.debug(f"[{correlation_id}] Running API code generation with PydanticAI agent")
        # Log enhanced context information
        if all_step_contexts:
            context_summary = {k: f"{type(v).__name__}({len(v) if isinstance(v, (list, dict)) else 'scalar'})" 
                             for k, v in all_step_contexts.items()}
            logger.debug(f"[{correlation_id}] Enhanced context received: {context_summary}")
        else:
            logger.debug(f"[{correlation_id}] No enhanced context provided")
        logger.debug(f"[{correlation_id}] Available endpoints: {len(available_endpoints)}")
        logger.debug(f"[{correlation_id}] Entities involved: {entities_involved}")
        
        # Run the agent
        result = await api_code_gen_agent.run(
            user_message,
            deps=dependencies
        )
        
        # Extract generated code
        code_output = result.output
        
        # Clean up markdown formatting from code
        python_code = code_output.python_code
        if python_code:
            # Remove markdown code blocks
            python_code = re.sub(r'^```(?:python)?\s*\n', '', python_code, flags=re.MULTILINE)
            python_code = re.sub(r'\n```\s*$', '', python_code, flags=re.MULTILINE)
            python_code = python_code.strip()
        
        # Log usage information in standardized format
        usage_info = result.usage()
        if usage_info:
            input_tokens = getattr(usage_info, 'input_tokens', 0)
            output_tokens = getattr(usage_info, 'output_tokens', 0)
            logger.info(f"[{correlation_id}] API code generation completed - {input_tokens} in, {output_tokens} out tokens")
        else:
            logger.info(f"[{correlation_id}] API code generation completed - no token usage available")
        logger.debug(f"[{correlation_id}] Generated code: {len(python_code)} characters")
        logger.debug(f"[{correlation_id}] Requirements: {code_output.requirements}")
        
        # Log metadata for debugging  
        #logger.debug(f"[{correlation_id}] COMPLETE API EXPLANATION:\n{code_output.explanation}")
        #logger.debug(f"[{correlation_id}] API SCRIPT REQUIREMENTS: {code_output.requirements}")
        #logger.debug(f"[{correlation_id}] API RATE LIMIT CONSIDERATIONS: {code_output.rate_limit_considerations}")
        
        return {
            'success': True,
            'code': python_code,
            'explanation': code_output.explanation,
            'requirements': code_output.requirements,
            'estimated_execution_time': code_output.estimated_execution_time,
            'rate_limit_considerations': code_output.rate_limit_considerations,
            'context_used': {
                'sql_records': sql_record_count,
                'api_endpoints': len(available_endpoints)
            },
            'correlation_id': correlation_id,
            'usage': str(usage_info),
            'code_length': len(python_code)
        }
        
    except ModelRetry as e:
        logger.error(f"[{correlation_id}] Model retry needed for API code generation: {e}")
        return {
            'success': False,
            'error': f'Model retry needed: {e}',
            'code': '',
            'explanation': 'Model retry needed',
            'requirements': [],
            'correlation_id': correlation_id
        }
        
    except UnexpectedModelBehavior as e:
        logger.error(f"[{correlation_id}] Unexpected model behavior in API code generation: {e}")
        return {
            'success': False,
            'error': f'Unexpected model behavior: {e}',
            'code': '',
            'explanation': 'Unexpected model behavior',
            'requirements': [],
            'correlation_id': correlation_id
        }
        
    except UsageLimitExceeded as e:
        logger.error(f"[{correlation_id}] Usage limit exceeded for API code generation: {e}")
        return {
            'success': False,
            'error': f'Usage limit exceeded: {e}',
            'code': '',
            'explanation': 'Usage limit exceeded',
            'requirements': [],
            'correlation_id': correlation_id
        }
        
    except Exception as e:
        logger.error(f"[{correlation_id}] API code generation failed: {e}")
        import traceback
        logger.debug(f"[{correlation_id}] Traceback: {traceback.format_exc()}")
        return {
            'success': False,
            'error': str(e),
            'code': '',
            'explanation': 'Code generation failed due to unexpected error',
            'requirements': [],
            'correlation_id': correlation_id
        }

# For backward compatibility and testing
async def execute_api_code_generation_legacy_wrapper(
    planning_result: Dict, 
    sql_result: Dict, 
    filter_result: Dict, 
    query: str, 
    correlation_id: str, 
    api_data_collected: List = None
) -> Dict[str, Any]:
    """
    Legacy wrapper for the old _execute_llm2_code_generation method signature
    This allows gradual migration from the old patterns
    """
    # Extract data from legacy format
    sql_data = sql_result.get('data', [])
    filtered_endpoints = filter_result.get('filtered_endpoints', [])
    
    # Extract planning info
    planning_plan = planning_result.get('execution_plan', {})
    if hasattr(planning_plan, 'model_dump'):
        planning_plan = planning_plan.model_dump()
    elif 'planning_output' in planning_result:
        planning_output = planning_result.get('planning_output', {})
        if hasattr(planning_output, 'execution_plan'):
            planning_plan = planning_output.execution_plan.model_dump()
    
    steps = planning_plan.get('plan', {}).get('steps', []) if 'plan' in planning_plan else planning_plan.get('steps', [])
    
    # Find the API step description
    step_description = "No specific step found"
    for step in steps:
        if step.get('tool_name') in ['role_assignment', 'role']:
            step_description = f"Step: {step.get('tool_name')} - {step.get('query_context', '')} - Reason: {step.get('reason', '')}"
            break
    
    entities_involved = planning_result.get('entities', [])
    
    # Call the new API code generation function
    return await generate_api_code(
        query=query,
        sql_record_count=len(sql_data),
        available_endpoints=[
            {
                'id': ep.get('id', ''),
                'name': ep.get('name', ''),
                'method': ep.get('method', ''),
                'url_pattern': ep.get('url_pattern', ''),
                'entity': ep.get('entity', ''),
                'operation': ep.get('operation', ''),
                'notes': ep.get('notes', ''),
                'folder_path': ep.get('folder_path', ''),
                'parameters': ep.get('parameters', {})
            }
            for ep in filtered_endpoints
        ],
        entities_involved=entities_involved,
        step_description=step_description,
        correlation_id=correlation_id
    )

if __name__ == "__main__":
    # Simple test
    async def test_api_code_gen():
        sample_data = [{"id": "test123", "login": "test@example.com"}]
        sample_endpoints = [{
            "id": "users_get",
            "name": "Get User",
            "method": "GET", 
            "url_pattern": "/api/v1/users/:userId",
            "entity": "users",
            "operation": "get",
            "description": "Get a user by ID",
            "parameters": {"required": ["userId"], "optional": ["expand"]}
        }]
        
        result = await generate_api_code(
            query="Get user details",
            sql_record_count=1,
            available_endpoints=sample_endpoints,
            entities_involved=["users"],
            step_description="Get user information from API",
            correlation_id="test_123"
        )
        
        print("Test Result:", result['success'])
        if result['success']:
            print("Generated Code Length:", len(result['code']))
        else:
            print("Error:", result['error'])
    
    asyncio.run(test_api_code_gen())
