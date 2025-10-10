"""
Pre-Planning Agent for Entity and Operation Selection

This agent handles the initial phase of query planning by:
1. Analyzing the natural language query 
2. Selecting relevant entities and operations from available options
3. Returning focused entity-operation pairs for endpoint filtering

Uses the same PydanticAI patterns as planning_agent for consistency.
"""

import asyncio
import json
import os
from typing import Optional, List, Dict, Any
import sys
import re
from dataclasses import dataclass
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import ModelRetry, UnexpectedModelBehavior, UsageLimitExceeded
from dotenv import load_dotenv

# Add src path for importing utils
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from src.utils.logging import get_logger, get_default_log_dir

load_dotenv()

# Setup centralized logging
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
class PrePlanDependencies:
    """Dependencies for the Pre-Planning Agent with dynamic context"""
    query: str
    entity_summary: Dict[str, Any]      # Entity summary for analysis
    graph_schema: str                   # GraphDB schema documentation (full text from get_graph_schema_description)
    available_entities: Optional[List[str]] = None  # Available entity list
    entities: Optional[Dict[str, Any]] = None  # New entity-grouped format
    flow_id: str = ""

class EntityOperation(BaseModel):
    """Individual entity and operation pair - matches ExecutionStep format"""
    entity: str = Field(
        description='The actual entity/table name (e.g., "users", "system_log", "groups")',
        min_length=1
    )
    operation: Optional[str] = Field(
        description='Exact operation name for API steps, null for SQL steps',
        default=None
    )

class PrePlanResult(BaseModel):
    """Result from pre-planning agent - focused entity and operation selection"""
    selected_entity_operations: List[EntityOperation] = Field(
        description='List of entity and operation pairs relevant to the query (empty list if only SQL is needed)',
        min_items=0
    )
    reasoning: str = Field(
        description='Explanation of why these entities and operations were selected, or why only SQL is sufficient',
        min_length=10
    )

class PrePlanOutput(BaseModel):
    """Output structure for the Pre-Planning Agent"""
    result: PrePlanResult = Field(
        description='The entity and operation selection result with reasoning'
    )

# Load base system prompt for static instructions
def load_base_system_prompt() -> str:
    """Load the base system prompt from file for static instructions"""
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        prompt_path = os.path.join(script_dir, "prompts", "preplan_agent_system_prompt.txt")
        
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        logger.error(f"Failed to load base system prompt file: {e}")
        return """You are an entity and operation selection agent for an Okta AI system. 
Analyze the user query and select the most relevant entity and operation pairs from the available entities.
Return focused entity-operation pairs that are directly needed to answer the user's question.
Focus on the specific operations (list, get, etc.) that will be required."""

# Create the Pre-Planning Agent with PydanticAI
preplan_agent = Agent(
    model,
    output_type=PrePlanOutput,
    deps_type=PrePlanDependencies,
    retries=0,  # No retries to avoid wasting money
    instructions=load_base_system_prompt()  # Static base instruction from file
)

@preplan_agent.instructions
def get_preplan_dynamic_instructions(ctx: RunContext[PrePlanDependencies]) -> str:
    """Dynamic instructions that include current context as clean JSON - API entities only"""
    deps = ctx.deps
    
    # NEW: Handle entity-grouped format with entity-first naming (same as planning agent)
    # Check if we have the new entities format
    if hasattr(deps, 'entities') and deps.entities:
        # New format: entity-grouped with entity-first operations
        api_entities = deps.entities
    else:
        # Fallback: build from entity_summary (legacy format)
        api_entities = {}
        for entity, details in deps.entity_summary.items():
            operations = details.get('operations', [])
            
            # Include ALL operations for broader selection (don't limit to 8)
            # This encourages more comprehensive entity-operation selection
            api_entities[entity] = {"operations": operations}

    return f"""

CURRENT EXECUTION CONTEXT - HYBRID API + GRAPHDB DECISION MAKING:

API_ENTITIES:
{json.dumps(api_entities, indent=2)}

GRAPHDB_SCHEMA:
{deps.graph_schema}

SELECTION CRITERIA FOR HYBRID APPROACH:
- FIRST: Check if data exists in GraphDB nodes/relationships - if YES, DO NOT select API entities for that data
- ONLY select API entities for data NOT available in GraphDB or requiring real-time access
- GraphDB schema above shows ALL available nodes, relationships, and properties
- If ALL required data is in GraphDB nodes/relationships, return EMPTY selected_entity_operations array
- Be BROAD and INCLUSIVE in your API selection for qualifying data (data not in GraphDB)
- Include entity-operation pairs that might provide context or supporting data
- NEVER select API entities if the same data is available in GraphDB nodes/relationships
- Focus on comprehensive coverage for API-only data rather than minimal selection
"""

async def select_relevant_entities(
    query: str,
    entity_summary: Dict[str, Any],
    graph_schema: str,
    flow_id: str,
    available_entities: Optional[List[str]] = None,
    entities: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Select relevant entity-operation pairs using PydanticAI Pre-Planning Agent
    
    Args:
        query: User query to analyze
        entity_summary: Summary of entity operations and methods
        graph_schema: GraphDB schema documentation (full text string)
        flow_id: Flow ID for tracking
        available_entities: Available entity list (optional)
        entities: Entity-grouped format (optional)
        
    Returns:
        Dict with success status and selected entity-operation pairs or error details
    """
    logger.info(f"[{flow_id}] Pre-Planning Agent: Starting entity-operation selection")
    logger.debug(f"[{flow_id}] Input query: {query}")
    logger.debug(f"[{flow_id}] Available entities: {len(entity_summary)}")
    logger.debug(f"[{flow_id}] GraphDB schema: {len(graph_schema)} characters")
    logger.debug(f"[{flow_id}] GraphDB schema preview: {graph_schema[:500]}...")
    
    # Check if User node information is in schema
    if 'User' in graph_schema and 'created_at' in graph_schema:
        logger.info(f"[{flow_id}] ✓ GraphDB schema includes User node with created_at property")
    elif 'User' in graph_schema:
        logger.warning(f"[{flow_id}] GraphDB schema includes User node but created_at not found in text")
    else:
        logger.warning(f"[{flow_id}] GraphDB schema does not mention User node")
    
    try:
        # Set up dependencies with current context
        deps = PrePlanDependencies(
            query=query,
            entity_summary=entity_summary,
            graph_schema=graph_schema,
            available_entities=available_entities,
            entities=entities,
            flow_id=flow_id
        )
        
        logger.info(f"[{flow_id}] Calling pre-planning agent with query: {query}")
        
        # Generate entity-operation selection using PydanticAI
        result = await preplan_agent.run(query, deps=deps)
        
        # Extract selected entity-operation pairs
        selected_entity_operations = result.output.result.selected_entity_operations
        reasoning = result.output.result.reasoning
        
        # Convert to simple format for logging
        entity_op_pairs = [f"{eo.entity}::{eo.operation or 'null'}" for eo in selected_entity_operations]
        
        logger.info(f"[{flow_id}] Pre-planning completed - selected {len(selected_entity_operations)} entity-operation pairs: {entity_op_pairs}")
        logger.debug(f"[{flow_id}] Selection reasoning: {reasoning}")
        
        # Token usage tracking
        if hasattr(result, 'usage') and result.usage():
            usage = result.usage()
            input_tokens = getattr(usage, 'request_tokens', getattr(usage, 'input_tokens', 0))
            output_tokens = getattr(usage, 'response_tokens', getattr(usage, 'output_tokens', 0))
            logger.info(f"[{flow_id}] Pre-planning completed - {input_tokens} in, {output_tokens} out tokens")
        
        return {
            'success': True,
            'selected_entity_operations': selected_entity_operations,
            'reasoning': reasoning,
            'usage': {
                'input_tokens': getattr(result.usage(), 'request_tokens', 0) if result.usage() else 0,
                'output_tokens': getattr(result.usage(), 'response_tokens', 0) if result.usage() else 0,
                'total_tokens': getattr(result.usage(), 'total_tokens', 0) if result.usage() else 0
            } if result.usage() else None
        }
        
    except ModelRetry as e:
        logger.error(f"[{flow_id}] Pre-planning retry needed: {e}")
        return {'success': False, 'error': f'Pre-planning retry needed: {e}', 'error_type': 'retry'}
        
    except UnexpectedModelBehavior as e:
        logger.error(f"[{flow_id}] Pre-planning unexpected behavior: {e}")
        return {'success': False, 'error': f'Pre-planning unexpected behavior: {e}', 'error_type': 'behavior'}
        
    except UsageLimitExceeded as e:
        logger.error(f"[{flow_id}] Pre-planning usage limit exceeded: {e}")
        return {'success': False, 'error': f'Pre-planning usage limit exceeded: {e}', 'error_type': 'usage_limit'}
        
    except Exception as e:
        logger.error(f"[{flow_id}] Pre-planning failed: {e}")
        return {'success': False, 'error': f'Pre-planning failed: {e}', 'error_type': 'general'}
