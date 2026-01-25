"""
Synthesis Agent - Phase 3 of Multi-Agent Architecture

Responsibilities:
- Read all artifacts from SQL and API phases
- Generate final production Python script
- Format output (table vs markdown)

Input: All artifacts from previous phases
Output: SynthesisResult with script code
"""

from pydantic_ai import Agent, RunContext, FunctionToolset
from pydantic import BaseModel
from typing import Optional, Callable, Awaitable
from dataclasses import dataclass, field
from pathlib import Path
import json
import time

from src.utils.logging import get_logger
from src.core.agents.agent_callbacks import (
    notify_progress_to_user,
    notify_step_start_to_user,
    notify_step_end_to_user
)

logger = get_logger("okta_ai_agent")

# ============================================================================
# Output Models
# ============================================================================

class SynthesisResult(BaseModel):
    """Output from Synthesis Agent"""
    success: bool
    script_code: Optional[str] = None
    display_type: str = "table"  # "table" or "markdown"
    error: Optional[str] = None


# ============================================================================
# Dependencies
# ============================================================================

@dataclass
class SynthesisDeps:
    """Dependencies for Synthesis Agent"""
    correlation_id: str
    artifacts_file: Path
    current_step: int = field(default=0)
    step_start_callback: Optional[Callable[[dict], Awaitable[None]]] = None
    step_end_callback: Optional[Callable[[dict], Awaitable[None]]] = None
    tool_call_callback: Optional[Callable[[dict], Awaitable[None]]] = None
    progress_callback: Optional[Callable[[dict], Awaitable[None]]] = None


# ============================================================================
# Synthesis Agent Definition
# ============================================================================

# Load system prompt (from existing final_script_synthesis_prompt.txt)
PROMPT_FILE = Path(__file__).parent / "prompts" / "synthesis_prompt.txt"
try:
    with open(PROMPT_FILE, 'r', encoding='utf-8') as f:
        BASE_SYSTEM_PROMPT = f.read()
except FileNotFoundError:
    logger.error(f"Synthesis prompt not found: {PROMPT_FILE}")
    BASE_SYSTEM_PROMPT = """You are a Python script synthesis specialist.
Read artifacts, generate production code using OktaAPIClient patterns."""


# Model selection
try:
    from src.core.models.model_picker import ModelConfig, ModelType
    model = ModelConfig.get_model(ModelType.CODING)
except ImportError:
    import os
    model = os.getenv('LLM_MODEL', 'openai:gpt-4o-mini')


# Create agent (NO TOOLS - synthesis doesn't need progress reporting during generation)
# Progress is reported by OktaAPIClient when the generated script EXECUTES
synthesis_agent = Agent(
    model,
    instructions=BASE_SYSTEM_PROMPT,
    output_type=SynthesisResult,
    deps_type=SynthesisDeps,
    retries=0
)


# ============================================================================
# Main Execution Function
# ============================================================================

async def execute_synthesis(
    user_query: str,
    deps: SynthesisDeps
) -> SynthesisResult:
    """
    Execute synthesis phase - generate final script.
    
    Args:
        user_query: Original user query
        deps: Synthesis dependencies with artifacts file path
    
    Returns:
        SynthesisResult with generated script code
    """
    logger.info(f"[{deps.correlation_id}] Starting synthesis phase")
    
    # Helper functions for notifications
    async def notify_step_start(title: str, reasoning: str):
        """Notify orchestrator of step start"""
        if deps.step_start_callback:
            deps.current_step += 1
            await deps.step_start_callback({
                "step": deps.current_step,
                "title": title,
                "text": reasoning,
                "timestamp": time.time()
            })
    
    async def notify_step_end(title: str, result: str):
        """Notify orchestrator of step end"""
        if deps.step_end_callback:
            await deps.step_end_callback({
                "step": deps.current_step,
                "title": title,
                "text": result,
                "timestamp": time.time()
            })
    
    try:
        # Load all artifacts
        if not deps.artifacts_file.exists():
            logger.error(f"[{deps.correlation_id}] Artifacts file not found: {deps.artifacts_file}")
            return SynthesisResult(
                success=False,
                error="No artifacts found from previous phases"
            )
        
        # Notify: Loading artifacts
        if deps.tool_call_callback:
            await deps.tool_call_callback({
                "name": "load_artifacts",
                "arguments": {"source": "memory"},
                "description": "Loading memory artifacts from previous phases",
                "timestamp": time.time()
            })
        
        with open(deps.artifacts_file, 'r', encoding='utf-8') as f:
            artifacts = json.load(f)
        
        logger.info(f"[{deps.correlation_id}] Loaded {len(artifacts)} artifacts")
        
        # Build context for agent
        context = f"""Original Query: {user_query}

Artifacts from Discovery Phases:
{json.dumps(artifacts, indent=2, default=str)}

Generate the final production Python script using the artifacts above.
Follow all patterns from synthesis_prompt.txt."""
        
        # Run agent
        result = await synthesis_agent.run(context, deps=deps)
        
        logger.info(f"[{deps.correlation_id}] Synthesis complete: success={result.output.success}")
        
        # Post-process script code: unescape quotes if LLM escaped them
        if result.output.script_code:
            # Fix common escaping issues
            result.output.script_code = result.output.script_code.replace('\\"', '"')
        
        # Log generated script summary
        if result.output.script_code:
            script_length = len(result.output.script_code)
            script_lines = result.output.script_code.split('\n')
            total_lines = len(script_lines)
            logger.info(f"[{deps.correlation_id}] ✅ SYNTHESIS COMPLETE: Generated final production code ({script_length} chars, {total_lines} lines)")
            
            # Log script preview (first 10 and last 10 lines)
            if total_lines > 20:
                preview_lines = script_lines[:10] + ['...'] + script_lines[-10:]
                logger.debug(f"[{deps.correlation_id}] 📝 Script preview:\n" + '\n'.join(preview_lines))
            else:
                logger.debug(f"[{deps.correlation_id}] 📝 Complete script:\n{result.output.script_code}")
        
        # Log token usage
        if result.usage():
            usage = result.usage()
            avg_per_call = usage.input_tokens / usage.requests if usage.requests > 0 else 0
            logger.info(
                f"[{deps.correlation_id}] 📊 Synthesis Agent Token Usage: "
                f"{usage.input_tokens:,} input, {usage.output_tokens:,} output, "
                f"{usage.total_tokens:,} total (across {usage.requests} API calls, "
                f"avg {avg_per_call:,.0f} input/call)"
            )
        
        # Notify phase complete
        if result.output.success:
            script_lines = len(result.output.script_code.split('\n')) if result.output.script_code else 0
            await notify_step_end(
                "Synthesis Complete",
                f"Successfully generated production script ({script_lines} lines). Ready for validation and execution."
            )
        else:
            await notify_step_end(
                "Synthesis Failed",
                f"Script generation failed: {result.output.error or 'Unknown error'}"
            )
        
        return result.output, result.usage()
        
    except Exception as e:
        logger.error(f"[{deps.correlation_id}] Synthesis failed: {e}", exc_info=True)
        return SynthesisResult(
            success=False,
            error=str(e)
        )
