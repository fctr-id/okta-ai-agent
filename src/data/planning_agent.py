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
        prompt_path = os.path.join(script_dir, "planning_agent_system_prompt.txt")
        
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        logger.error(f"Failed to load base system prompt file: {e}")
        return "You are a HYBRID query planner for an Okta system."

def get_dynamic_instructions_text(deps: PlanningDependencies) -> str:
    """Get dynamic instructions text for debugging (same logic as @planning_agent.instructions)"""
    # Build entity operations in clean JSON format
    api_entities = {}
    for entity, details in deps.entity_summary.items():
        operations = details.get('operations', [])
        
        # Filter to most relevant operations for planning (max 8 per entity)
        key_operations = []
        
        # Priority operations based on common query patterns
        priority_ops = ['list', 'get', 'list_by_user', 'list_members', 'list_user_assignments', 'list_group_assignments', 'list_events']
        
        # Add priority operations first
        for op in priority_ops:
            if op in operations:
                key_operations.append(op)
        
        # Add other operations up to limit
        for op in operations:
            if op not in key_operations and len(key_operations) < 8:
                key_operations.append(op)
        
        # Simple clean format - just the operations list
        api_entities[entity] = key_operations
    
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
            if col_name not in key_columns and len(key_columns) < 6:
                key_columns.append(col_name)
        
        # Simple clean format - just the columns list
        sql_tables[table_name] = key_columns
    
    # Create minimal JSON context
    context_data = {
        "api_entities": api_entities,
        "sql_tables": sql_tables
    }
    
    # Return JSON context with ultra-compact formatting to save context tokens
    return f"""
AVAILABLE DATA SOURCES (JSON Format):
```json
{json.dumps(context_data, separators=(',', ':'))}
```
DATA AVAILABILITY SUMMARY:"""

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
    """Dynamic instructions that include current context as clean JSON"""
    deps = ctx.deps
    
    # Build entity operations in clean JSON format
    api_entities = {}
    for entity, details in deps.entity_summary.items():
        operations = details.get('operations', [])
        
        # Filter to most relevant operations for planning (max 8 per entity)
        key_operations = []
        
        # Priority operations based on common query patterns
        priority_ops = ['list', 'get', 'list_by_user', 'list_members', 'list_user_assignments', 'list_group_assignments', 'list_events']
        
        # Add priority operations first
        for op in priority_ops:
            if op in operations:
                key_operations.append(op)
        
        # Add other operations up to limit
        for op in operations:
            if op not in key_operations and len(key_operations) < 8:
                key_operations.append(op)
        
        # Simple clean format - just the operations list
        api_entities[entity] = key_operations
    
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
            if col_name not in key_columns and len(key_columns) < 6:
                key_columns.append(col_name)
        
        # Simple clean format - just the columns list
        sql_tables[table_name] = key_columns
    
    # Create minimal JSON context
    context_data = {
        "api_entities": api_entities,
        "sql_tables": sql_tables
    }
    
    # Return JSON context with ultra-compact formatting to save context tokens
    return f"""
AVAILABLE DATA SOURCES (JSON Format):
```json
{json.dumps(context_data, separators=(',', ':'))}
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
            
            # Get the dynamic instructions
            dynamic_instructions = get_dynamic_instructions_text(deps)
            
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
