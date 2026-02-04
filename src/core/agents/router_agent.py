"""
Router Agent - Query Classification for Multi-Agent Orchestrator

Decides which phase(s) to execute based on query analysis.
"""

from pydantic_ai import Agent, RunContext
from pydantic import BaseModel
from typing import Literal, Any
from dataclasses import dataclass
from pathlib import Path

from src.utils.logging import get_logger

logger = get_logger("okta_ai_agent")


# ============================================================================
# Schema Helper Function
# ============================================================================

def get_sqlite_schema_description() -> str:
    """
    Generate a comprehensive LLM-optimized description of the SQLite database schema.
    Uses the centralized shared schema definition.
    
    Returns:
        Formatted schema description string with complete table details
    """
    from src.data.schemas.shared_schema import get_okta_database_schema
    return get_okta_database_schema()


# ============================================================================
# Output Model
# ============================================================================

class RouterDecision(BaseModel):
    """Router decision for query execution path"""
    phase: Literal["SQL", "API", "SPECIAL", "NOT_RELEVANT"]
    reasoning: str


# ============================================================================
# Dependencies
# ============================================================================

@dataclass
class RouterDeps:
    """Dependencies for router agent"""
    correlation_id: str
    progress_callback: callable = None  # Optional callback for streaming progress
    step_start_callback: callable = None  # For STEP-START events


# ============================================================================
# Router Agent Definition
# ============================================================================

# Load system prompt
PROMPT_FILE = Path(__file__).parent / "prompts" / "router_prompt.txt"
try:
    with open(PROMPT_FILE, 'r', encoding='utf-8') as f:
        BASE_SYSTEM_PROMPT = f.read()
except FileNotFoundError:
    logger.error(f"Router prompt not found: {PROMPT_FILE}")
    BASE_SYSTEM_PROMPT = """Classify Okta query into: SQL, API, SQL+API, SPECIAL, or NOT_RELEVANT."""


# Model selection
try:
    from src.core.models.model_picker import ModelConfig, ModelType
    model = ModelConfig.get_model(ModelType.CODING)
except ImportError:
    import os
    model = os.getenv('LLM_MODEL', 'openai:gpt-4o-mini')


# Create agent with progress reporting tool
router_agent = Agent(
    model,
    instructions=BASE_SYSTEM_PROMPT,  # Static base instructions
    output_type=RouterDecision,
    deps_type=RouterDeps,
    retries=0
)


# ============================================================================
# Tool: Notify Progress
# ============================================================================

@router_agent.tool
async def notify_progress_to_user(
    ctx: RunContext[RouterDeps],
    message: str,
    details: str = ""
) -> str:
    """
    Report progress to the user. Call this to keep users informed of your analysis.
    
    Args:
        message: Progress message (e.g., "🎯 STARTING: Analyzing query structure")
        details: Optional additional details
    
    Returns:
        Confirmation that progress was logged
    """
    deps = ctx.deps
    
    # Log to server with full details
    logger.info(f"[{deps.correlation_id}] 📊 Progress: {message}")
    if details:
        logger.info(f"[{deps.correlation_id}] 📊 Details: {details}")
    
    # Send to frontend via step_start callback (creates STEP-START events)
    if deps.step_start_callback:
        await deps.step_start_callback({
            "title": "",
            "text": message,  # Frontend displays text field
            "timestamp": __import__('time').time()
        })
    
    return f"✅ Progress reported: {message}"


@router_agent.instructions
def create_dynamic_instructions(ctx: RunContext[RouterDeps]) -> str:
    """Create dynamic instructions with database schema from shared schema"""
    deps = ctx.deps
    
    # Load shared schema dynamically
    schema_description = get_sqlite_schema_description()
    
    # Build dynamic context with actual schema
    dynamic_context = f"""

===========================================
DYNAMIC CONTEXT - DATABASE SCHEMA (SHARED)
===========================================

{schema_description}

CORRELATION ID: {deps.correlation_id}

⚠️ IMPORTANT: This schema is loaded dynamically from the shared schema definition.
Use this to understand what data is available in the database vs what requires API calls.
"""
    
    return dynamic_context


# ============================================================================
# Main Execution Function
# ============================================================================

async def route_query(user_query: str, correlation_id: str, progress_callback: callable = None, step_start_callback: callable = None) -> tuple[RouterDecision, Any]:
    """
    Classify query to determine execution path.
    
    Args:
        user_query: User's question
        correlation_id: Request tracking ID
    
    Returns:
        RouterDecision with phase and reasoning
    """
    logger.info(f"Routing query: {user_query}")
    
    try:
        deps = RouterDeps(correlation_id=correlation_id, progress_callback=progress_callback, step_start_callback=step_start_callback)
        result = await router_agent.run(user_query, deps=deps)
        
        logger.info(f"Route decision: {result.output.phase} - {result.output.reasoning}")
        
        # Log token usage
        if result.usage():
            usage = result.usage()
            logger.info(
                f"[{correlation_id}] 📊 Router Agent Token Usage: "
                f"{usage.input_tokens:,} input, {usage.output_tokens:,} output, "
                f"{usage.total_tokens:,} total"
            )
        
        return result.output, result.usage()
        
    except Exception as e:
        logger.error(f"Router failed: {e}", exc_info=True)
        # Default to PROCEED on error (safe fallback - let SQL handle it)
        return RouterDecision(
            phase="PROCEED",
            reasoning=f"Router error, proceeding to SQL phase: {str(e)}"
        ), None
