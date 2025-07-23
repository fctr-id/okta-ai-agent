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
from pydantic_ai.exceptions import ModelRetry, UnexpectedModelBehavior, UsageLimitExceeded
from dotenv import load_dotenv

# Add src path for importing utils
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from utils.logging import get_logger, generate_correlation_id, set_correlation_id, get_default_log_dir

load_dotenv()

# Setup centralized logging with file output
logger = get_logger("okta_ai_agent.api_code_gen_agent", log_dir=get_default_log_dir())

# Use the model picker approach for consistent model configuration
try:
    from src.core.model_picker import ModelConfig, ModelType
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
    sql_data_sample: List[Dict[str, Any]]
    sql_record_count: int
    available_endpoints: List[Dict[str, Any]]
    entities_involved: List[str]
    step_description: str
    flow_id: str = ""  # Correlation ID for flow tracking

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

# Load system prompt from file
SYSTEM_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "api_code_gen_agent_system_prompt.txt")

try:
    with open(SYSTEM_PROMPT_PATH, 'r', encoding='utf-8') as f:
        BASE_SYSTEM_PROMPT = f.read()
except FileNotFoundError:
    logger.warning(f"System prompt file not found at {SYSTEM_PROMPT_PATH}, using fallback")
    BASE_SYSTEM_PROMPT = """You are an expert Python code generator for Okta API operations.

🚨 **GOLDEN RULES - NON-NEGOTIABLE** 🚨
1. **`limit=100` ON ALL API CALLS**: Every single API call MUST include `limit=100`. No exceptions.
2. **USE PROVIDED ENDPOINTS ONLY**: Use ONLY the exact API endpoints and methods provided in the context.
3. **FOLLOW THE PLAN**: Implement the execution plan EXACTLY as described.
4. **JSON OUTPUT ONLY**: Your entire response MUST be a single, valid JSON object.

Generate practical, executable Python code that combines SQL data with API calls to solve the user's query."""

# Create the PydanticAI agent
api_code_gen_agent = Agent(
    model,
    system_prompt=BASE_SYSTEM_PROMPT,
    output_type=CodeGenerationOutput,
    retries=0  # No retries to avoid wasting money on failed attempts
)

@api_code_gen_agent.system_prompt
def create_dynamic_system_prompt(ctx: RunContext[ApiCodeGenDependencies]) -> str:
    """Create dynamic system prompt with context from dependencies"""
    deps = ctx.deps
    
    # Build dynamic context
    dynamic_context = f"""

DYNAMIC CONTEXT FOR THIS REQUEST:
- Task: {deps.step_description}
- SQL Records Available: {deps.sql_record_count}
- API Endpoints Available: {len(deps.available_endpoints)}
- Entities: {deps.entities_involved}

AVAILABLE SQL DATA SAMPLE:
{json.dumps(deps.sql_data_sample[:2], indent=2) if deps.sql_data_sample else 'No SQL data available'}

AVAILABLE API ENDPOINTS WITH COMPLETE DOCUMENTATION:
{json.dumps(deps.available_endpoints, indent=2)}

🚨 CRITICAL API GUIDELINES - FOLLOW STRICTLY:

1. **PARAMETER COMPLIANCE**:
   - ALWAYS use ONLY the parameters listed in 'parameters.required' and 'parameters.optional'
   - NEVER use parameters not in the API specification (like 'published' for system logs)
   - For system_log endpoints, use 'since', 'until', 'filter', 'q', 'limit', 'sortOrder' ONLY
   
2. **URL CONSTRUCTION**:
   - Use the exact 'url_pattern' provided
   - Replace :paramName with actual values (e.g., :userId with actual user ID)
   - Build full URLs: https://{{{{okta_domain}}}}/api/v1/...
   
3. **METHOD COMPLIANCE**:
   - Use the exact HTTP method specified ('method' field)
   - GET for retrieving data, POST for creating, PUT for updating, DELETE for removing
   
4. **DESCRIPTION ADHERENCE**:
   - Read the 'description' field carefully for API-specific guidance
   - Follow any special notes, limitations, or requirements mentioned
   - Pay attention to default values, pagination, and rate limits
   
5. **TIME FILTERING** (Critical for logs/events):
   - Use 'since' and 'until' parameters for time-based filtering
   - Format: ISO 8601 with Z suffix (e.g., "2025-07-09T00:00:00.000Z")
   - NEVER use 'published' in filter expressions - use 'since'/'until' instead
   
6. **FILTER EXPRESSIONS**:
   - Follow SCIM filter syntax as documented
   - Use correct operators: eq, ne, gt, lt, sw, co, ew
   - Quote string values properly
   
7. **ERROR HANDLING**:
   - Include proper error handling for API calls
   - Handle rate limits, timeouts, and authentication errors
   - Provide meaningful error messages

Generate practical, executable code that solves the user's query: {deps.query}"""
    
    return BASE_SYSTEM_PROMPT + dynamic_context

async def generate_api_code(
    query: str,
    sql_data_sample: List[Dict[str, Any]],
    sql_record_count: int,
    available_endpoints: List[Dict[str, Any]],
    entities_involved: List[str],
    step_description: str,
    correlation_id: str
) -> Dict[str, Any]:
    """
    Generate Python code for Okta API operations using PydanticAI
    
    Args:
        query: User's original query
        sql_data_sample: Sample of SQL data to work with
        sql_record_count: Total count of SQL records
        available_endpoints: List of filtered API endpoints
        entities_involved: List of entities from planning
        step_description: Description of the step to implement
        correlation_id: Correlation ID for logging
        
    Returns:
        Dict containing success status, generated code, and metadata
    """
    # Set correlation ID for logging
    set_correlation_id(correlation_id)
    
    logger.info(f"[{correlation_id}] API Code Generation Agent: Starting code generation")
    logger.debug(f"[{correlation_id}] Task: {step_description}")
    logger.debug(f"[{correlation_id}] SQL records: {sql_record_count}, API endpoints: {len(available_endpoints)}")
    
    try:
        # Validate inputs
        if not sql_data_sample and not available_endpoints:
            logger.warning(f"[{correlation_id}] No SQL data or API endpoints available for code generation")
            return {
                'success': False,
                'error': 'No data available for code generation',
                'code': '',
                'explanation': 'No SQL data or API endpoints provided',
                'requirements': [],
                'correlation_id': correlation_id
            }
        
        # Create dependencies
        dependencies = ApiCodeGenDependencies(
            query=query,
            sql_data_sample=sql_data_sample,
            sql_record_count=sql_record_count,
            available_endpoints=available_endpoints,
            entities_involved=entities_involved,
            step_description=step_description,
            flow_id=correlation_id
        )
        
        # Create user message for code generation
        user_message = f"Generate Python code for: {step_description}\n\nSQL Data Structure: {list(sql_data_sample[0].keys()) if sql_data_sample else []}\nAPI Endpoints: {len(available_endpoints)} available"
        
        logger.debug(f"[{correlation_id}] Running API code generation with PydanticAI agent")
        # Log complete first 2 sample records for debugging (not truncated fields)
        if sql_data_sample:
            logger.debug(f"[{correlation_id}] Complete SQL sample received (first 2 records): {sql_data_sample[:2]}")
        else:
            logger.debug(f"[{correlation_id}] SQL sample received: None")
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
        
        # Log usage information
        usage_info = result.usage()
        logger.info(f"[{correlation_id}] API code generation completed - {usage_info}")
        logger.debug(f"[{correlation_id}] Generated code: {len(python_code)} characters")
        logger.debug(f"[{correlation_id}] Requirements: {code_output.requirements}")
        
        # Log metadata for debugging  
        logger.debug(f"[{correlation_id}] COMPLETE API EXPLANATION:\n{code_output.explanation}")
        logger.debug(f"[{correlation_id}] API SCRIPT REQUIREMENTS: {code_output.requirements}")
        logger.debug(f"[{correlation_id}] API RATE LIMIT CONSIDERATIONS: {code_output.rate_limit_considerations}")
        
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
        sql_data_sample=sql_data[:3] if sql_data else [],
        sql_record_count=len(sql_data),
        available_endpoints=[
            {
                'id': ep.get('id', ''),
                'name': ep.get('name', ''),
                'method': ep.get('method', ''),
                'url_pattern': ep.get('url_pattern', ''),
                'entity': ep.get('entity', ''),
                'operation': ep.get('operation', ''),
                'description': ep.get('description', ''),
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
            sql_data_sample=sample_data,
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
