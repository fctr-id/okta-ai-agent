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
from utils.logging import get_logger, generate_correlation_id, set_correlation_id, get_default_log_dir

load_dotenv()

# Setup centralized logging with file output
logger = get_logger("okta_ai_agent.planning_agent", log_dir=get_default_log_dir())

# Use the model picker approach for consistent model configuration
try:
    from src.core.model_picker import ModelConfig, ModelType
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

class ExecutionStep(BaseModel):
    """Individual execution step in the plan"""
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "tool_name": "api",
            "entity": "system_log",
            "operation": "list_events",
            "method": "GET",
            "query_context": "Get login events for the last 7 days to identify active users",
            "critical": True,
            "reasoning": "Identify users who have logged in recently"
        }
    })
    
    tool_name: str = Field(
        description='Execution method: "sql" or "api"',
        min_length=1
    )
    entity: str = Field(
        description='Entity name for API calls or table name for SQL operations',
        min_length=1
    )
    operation: Optional[str] = Field(
        description='Exact operation name for API calls (null for SQL steps)',
        default=None
    )
    method: Optional[str] = Field(
        description='HTTP method for API calls (GET, POST, PUT, DELETE). Auto-derived from operation if not specified.',
        default=None
    )
    query_context: str = Field(
        description='Detailed context for this step describing what data to collect',
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
    """Complete execution plan structure"""
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "entities": ["users", "system_log"],
            "steps": [
                {
                    "tool_name": "system_log", 
                    "query_context": "Get login events for the last 7 days to identify active users",
                    "critical": True,
                    "reasoning": "Identify users who have logged in recently"
                },
                {
                    "tool_name": "users",
                    "query_context": "Find applications and groups for the specified users",
                    "critical": True, 
                    "reasoning": "Retrieve user application and group data from SQL"
                }
            ],
            "reasoning": "Break user query into: API for recent login events, SQL for fetching applications and groups for those users",
            "confidence": 85
        }
    })
    
    entities: List[str] = Field(
        description='List of entities/tables involved in the execution plan',
        min_items=1
    )
    steps: List[ExecutionStep] = Field(
        description='Ordered list of execution steps',
        min_items=1
    )
    reasoning: str = Field(
        description='High-level reasoning for the chosen approach',
        min_length=10
    )
    confidence: int = Field(
        description='Confidence level in the execution plan (0-100)',
        ge=0,
        le=100
    )

class PlanningOutput(BaseModel):
    """Output structure for the Planning Agent"""
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "plan": {
                "entities": ["users", "system_log"],
                "steps": [
                    {
                        "tool_name": "system_log",
                        "query_context": "Get login events for the last 7 days to identify active users", 
                        "critical": True,
                        "reasoning": "Identify users who have logged in recently"
                    }
                ],
                "reasoning": "Break user query into API and SQL components",
                "confidence": 85
            }
        }
    })
    
    plan: ExecutionPlan = Field(
        description='The complete execution plan for the user query'
    )

# Load system prompt from file
def load_system_prompt(deps: PlanningDependencies) -> str:
    """Load and customize system prompt with dynamic context"""
    system_prompt_path = os.path.join(os.path.dirname(__file__), "planning_agent_system_prompt.txt")
    
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
            
            # Add custom attributes info if available
            custom_attrs_info = ""
            if table_name == 'users' and 'custom_attributes' in table_info:
                custom_attrs_data = table_info['custom_attributes']
                available_attrs = custom_attrs_data.get('available_attributes', [])
                if available_attrs:
                    custom_attrs_info = f" | custom_attributes available: {', '.join(available_attrs)}"
            
            sql_schema_text.append(f"  • {table_name}: columns=[{', '.join(column_names[:10])}{'...' if len(column_names) > 10 else ''}]{custom_attrs_info}")
        
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
        
        # Print complete system prompt for verification (only when DEBUG level)
        if logger.isEnabledFor(10):  # DEBUG level = 10
            logger.debug(f"[{deps.flow_id}] COMPLETE SYSTEM PROMPT (START)")
            logger.debug(f"[{deps.flow_id}] " + "="*80)
            # Split into lines and log each line with prefix for readability
            for i, line in enumerate(updated_prompt.split('\n'), 1):
                logger.debug(f"[{deps.flow_id}] {i:3d}: {line}")
            logger.debug(f"[{deps.flow_id}] " + "="*80)
            logger.debug(f"[{deps.flow_id}] COMPLETE SYSTEM PROMPT (END)")
        
        return updated_prompt
        
    except Exception as e:
        logger.error(f"[{deps.flow_id}] Failed to load system prompt: {e}")
        # Return a basic fallback prompt
        return """You are a hybrid query planner. Create execution plans with 'plan' containing 'entities', 'steps', 'reasoning', and 'confidence'."""

# Load the base system prompt at module level
def load_base_system_prompt() -> str:
    """Load the base system prompt from file"""
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        prompt_path = os.path.join(script_dir, "planning_agent_system_prompt.txt")
        
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        logger.error(f"Failed to load system prompt file: {e}")
        # Return a basic fallback prompt
        return """You are a hybrid query planner. Create execution plans with 'plan' containing 'entities', 'steps', 'reasoning', and 'confidence'."""

# Load base prompt at import time
BASE_SYSTEM_PROMPT = load_base_system_prompt()

# Create the Planning Agent with PydanticAI using dynamic system prompt
planning_agent = Agent(
    model,
    output_type=PlanningOutput,  # ✅ MODERN: Use output_type not deprecated result_type
    deps_type=PlanningDependencies,
    retries=2,  # Allow retries for better reliability
)

@planning_agent.system_prompt
def dynamic_system_prompt(ctx: RunContext[PlanningDependencies]) -> str:
    """Dynamic system prompt that includes current entities and SQL schema"""
    logger.debug(f"[{ctx.deps.flow_id}] Planning Agent: Building dynamic system prompt")
    logger.debug(f"[{ctx.deps.flow_id}] Available entities count: {len(ctx.deps.available_entities)}")
    logger.debug(f"[{ctx.deps.flow_id}] Entity summary keys: {list(ctx.deps.entity_summary.keys())}")
    logger.debug(f"[{ctx.deps.flow_id}] SQL tables count: {len(ctx.deps.sql_tables)}")
    
    # Check for custom attributes specifically
    if 'users' in ctx.deps.sql_tables and 'custom_attributes' in ctx.deps.sql_tables['users']:
        custom_attrs = ctx.deps.sql_tables['users']['custom_attributes'].get('available_attributes', [])
        logger.debug(f"[{ctx.deps.flow_id}] Custom attributes found: {custom_attrs}")
    else:
        logger.debug(f"[{ctx.deps.flow_id}] No custom attributes found in users table")
    
    prompt = load_system_prompt(ctx.deps)
    logger.debug(f"[{ctx.deps.flow_id}] Dynamic system prompt generated, length: {len(prompt)} characters")
    return prompt

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
        
        # Generate plan using PydanticAI
        result = await planning_agent.run(query, deps=deps)
        
        # Pretty print the execution plan for better readability
        plan_dict = result.output.plan.model_dump()
        logger.debug(f"[{flow_id}] Generated execution plan (pretty printed):")
        logger.debug(f"[{flow_id}] {json.dumps(plan_dict, indent=2)}")
        logger.debug(f"[{flow_id}] Plan confidence: {result.output.plan.confidence}%")
        logger.debug(f"[{flow_id}] Plan entities: {result.output.plan.entities}")
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

# For testing the agent directly
async def test_planning_agent():
    """Simple test function for the planning agent"""
    flow_id = generate_correlation_id("test")
    set_correlation_id(flow_id)
    
    # Mock data for testing
    mock_entities = ["user", "group", "application", "system_log"]
    mock_entity_summary = {
        "user": {"operations": ["list_users", "get_user"], "methods": ["GET"]},
        "system_log": {"operations": ["list_events"], "methods": ["GET"]}
    }
    mock_sql_tables = {
        "users": {"columns": ["id", "email", "status"]},
        "groups": {"columns": ["id", "name", "description"]}
    }
    
    test_query = "Find users who logged in the last 7 days and their applications"
    
    result = await generate_execution_plan(
        query=test_query,
        available_entities=mock_entities,
        entity_summary=mock_entity_summary,
        sql_tables=mock_sql_tables,
        flow_id=flow_id
    )
    
    print(f"Planning Agent Test Result: {result}")
    return result

if __name__ == "__main__":
    asyncio.run(test_planning_agent())
