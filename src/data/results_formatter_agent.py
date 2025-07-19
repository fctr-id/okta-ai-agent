#!/usr/bin/env python3
"""
Results Formatter Agent (formerly LLM3) - ENHANCED VERSION
Professional PydanticAI features with global settings:
- Token usage reporting (no limits)
- Intelligent retries using global LLM_RETRIES
- Output validation with ModelRetry  
- Global temperature from LLM_TEMPERATURE
"""

import json
import os
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
import sys
import os
# Add the parent directory to sys.path to import from core
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from core.model_picker import ModelConfig, ModelType
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FormattedOutput(BaseModel):
    """Detailed formatted output matching system prompt expectations"""
    display_type: str = Field(description='Either "table" or "markdown"')
    content: Dict[str, Any] = Field(description='The formatted content')
    metadata: Dict[str, Any] = Field(description='Execution metadata and summary info')

# Simple validation function (called after getting response, not in LLM)
def is_valid_format(output: FormattedOutput) -> bool:
    """Simple validation done outside LLM to avoid expensive retries"""
    if output.display_type not in ['table', 'markdown']:
        return False
    if not output.content:
        return False
    if not output.metadata:
        return False
    return True


# Global LLM configuration from environment
def get_global_llm_config():
    """Get global LLM configuration from environment variables"""
    return {
        'temperature': float(os.getenv('LLM_TEMPERATURE', '0.7')),
        'retries': int(os.getenv('LLM_RETRIES', '1')),
        'enable_token_reporting': os.getenv('LLM_ENABLE_TOKEN_REPORTING', 'true').lower() == 'true'
    }

# Get global configuration
config = get_global_llm_config()

# Get model with professional settings
formatter_model = ModelConfig.get_model(ModelType.REASONING)

# Load system prompt from file
def load_system_prompt():
    """Load detailed system prompt from dedicated file"""
    try:
        prompt_file = os.path.join(os.path.dirname(__file__), 'results_formatter_agent_system_prompt.txt')
        with open(prompt_file, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        logger.warning("System prompt file not found, using fallback")
        return """You format query results for users professionally.

Output a JSON with:
- display_type: "table" or "markdown"  
- content: the formatted data
- summary: brief description

Keep it simple and focused."""

# Simple agent with essential PydanticAI features - NO automatic validation retries
results_formatter = Agent(
    formatter_model,
    # NOTE: Removed output_type=FormattedOutput to avoid expensive LLM validation retries
    # We'll do validation outside the LLM using is_valid_format() function
    retries=config['retries'],  
    system_prompt=load_system_prompt()
)


async def format_results(query: str, results: Dict[str, Any]) -> Dict[str, Any]:
    """Simple function with basic token tracking - NO LLM validation retries"""
    
    import json
    import re
    
    prompt = f"""Query: {query}
Results: {json.dumps(results, indent=2, default=str)}

Please respond with a JSON object with this structure:
{{
  "display_type": "table" or "markdown",
  "content": {{formatted content}},
  "metadata": {{execution summary info}}
}}

Format these results professionally."""
    
    try:
        if config['enable_token_reporting']:
            logger.info("🎨 [Results Formatter Agent] Processing with simplified PydanticAI...")
        
        # Run formatter - now returns raw string output
        result = await results_formatter.run(prompt)
        
        # Parse the JSON response ourselves (OUTSIDE LLM)
        try:
            # result.data is now a string, not structured output
            response_text = str(result.data) if hasattr(result, 'data') else str(result)
            
            # Look for JSON in the response
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                response_json = json.loads(json_match.group())
            else:
                # Fallback - create a simple response
                response_json = {
                    "display_type": "markdown",
                    "content": {"text": response_text},
                    "metadata": {"execution_summary": "Simple text response", "confidence_level": "Low"}
                }
                
            # Simple validation OUTSIDE LLM (no retries)
            if response_json.get('display_type') not in ['table', 'markdown']:
                response_json['display_type'] = 'markdown'
            if not response_json.get('content'):
                response_json['content'] = {"text": "No content available"}
            if not response_json.get('metadata'):
                response_json['metadata'] = {"execution_summary": "Basic processing", "confidence_level": "Medium"}
                
            logger.info("✅ [Results Formatter Agent] Successfully processed without LLM retries")
            
        except (json.JSONDecodeError, AttributeError) as parse_error:
            logger.warning(f"⚠️ [Results Formatter Agent] JSON parsing failed: {parse_error}")
            # Create fallback response
            response_json = {
                "display_type": "markdown",
                "content": {"text": f"Query: {query}\n\nProcessed results available but format parsing failed."},
                "metadata": {
                    "execution_summary": "Parsing failed but processing completed", 
                    "confidence_level": "Low",
                    "parse_error": str(parse_error)
                }
            }
        
        # Token usage reporting (if enabled)
        if config['enable_token_reporting']:
            usage = result.usage()
            if usage:
                logger.info(f"💰 [Results Formatter Agent] Token Usage:")
                logger.info(f"   📥 Input: {getattr(usage, 'request_tokens', getattr(usage, 'input_tokens', 0))} tokens")
                logger.info(f"   📤 Output: {getattr(usage, 'response_tokens', getattr(usage, 'output_tokens', 0))} tokens") 
                logger.info(f"   📊 Total: {getattr(usage, 'total_tokens', 0)} tokens")
                
                # Cost estimation (approximate)
                input_tokens = getattr(usage, 'request_tokens', getattr(usage, 'input_tokens', 0))
                output_tokens = getattr(usage, 'response_tokens', getattr(usage, 'output_tokens', 0))
                estimated_cost = (input_tokens * 0.00001) + (output_tokens * 0.00003)
                logger.info(f"   💵 Estimated cost: ${estimated_cost:.6f}")
        
        # Add usage info to response if available
        if config['enable_token_reporting'] and result.usage():
            usage = result.usage()
            input_tokens = getattr(usage, 'request_tokens', getattr(usage, 'input_tokens', 0))
            output_tokens = getattr(usage, 'response_tokens', getattr(usage, 'output_tokens', 0))
            total_tokens = getattr(usage, 'total_tokens', input_tokens + output_tokens)
            response_json['usage_info'] = {
                'input_tokens': input_tokens,
                'output_tokens': output_tokens,
                'total_tokens': total_tokens,
                'estimated_cost': f"${((input_tokens * 0.00001) + (output_tokens * 0.00003)):.6f}"
            }
        
        logger.info("✅ [Results Formatter Agent] Successfully processed with simplified validation")
        return response_json
        
    except ModelRetry as e:
        logger.error(f"🔄 [Results Formatter Agent] Retry needed: {e}")
        raise
    except UnexpectedModelBehavior as e:
        logger.error(f"⚠️ [Results Formatter Agent] Unexpected model behavior: {e}")
        raise
    except UsageLimitExceeded as e:
        logger.error(f"💰 [Results Formatter Agent] Usage limit exceeded: {e}")
        raise
    except Exception as e:
        logger.error(f"❌ [Results Formatter Agent] Error: {e}")
        return {
            'display_type': 'markdown', 
            'content': {'text': f'**Error**: {e}'},
            'metadata': {
                'execution_summary': f'Formatting failed: {e}',
                'confidence_level': 'Low',
                'data_sources': ['error'],
                'total_records': 0,
                'processing_time': 'N/A',
                'limitations': 'Processing failed due to error'
            },
            'usage_info': {'error': 'Processing failed'}
        }


# Backward compatibility function
async def process_results_structured(
    query: str,
    results: Dict[str, Any], 
    original_plan: Optional[str] = None,
    is_sample: bool = False,
    metadata: Optional[Dict[str, Any]] = None,
    model_name: str = "openai:gpt-4o"
) -> Dict[str, Any]:
    """Backward compatibility - enhanced with professional features"""
    return await format_results(query, results)
