"""
Results Formatter Agent - User-Centric Data Aggregation with PydanticAI

Enhanced architecture following the proven results_processor_agent.py pattern:
- Conditional processing based on is_sample parameter
- Intelligent sampling for large datasets
- Code generation for processing complete datasets using pure Python
- Robust JSON parsing with fallbacks
- Centralized logging with correlation ID support

Model Configuration:
- Complete Data Formatter: Uses REASONING model for data understanding and formatting
- Sample Data Formatter: Uses CODING model for Python JSON code generation (better for syntax)
"""

import asyncio
import json
import logging
import time
import re
import sys
import os
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelRetry, UnexpectedModelBehavior, UsageLimitExceeded

# Add src path for importing utils
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from src.utils.logging import get_logger, generate_correlation_id, set_correlation_id, get_default_log_dir
from src.utils.security_config import get_allowed_methods_for_prompt

# Setup centralized logging with file output  
# Using main "okta_ai_agent" namespace for unified logging across all agents
logger = get_logger("okta_ai_agent", log_dir=get_default_log_dir())

# Use the model picker approach for consistent model configuration
try:
    from src.core.models.model_picker import ModelConfig, ModelType
    reasoning_model = ModelConfig.get_model(ModelType.REASONING)
    coding_model = ModelConfig.get_model(ModelType.CODING)
except ImportError:
    # Fallback to simple model configuration
    def get_simple_model():
        """Simple model configuration without complex imports"""
        model_name = os.getenv('LLM_MODEL', 'openai:gpt-4o')
        return model_name
    reasoning_model = get_simple_model()
    coding_model = get_simple_model()

# Configuration
# Simple configuration placeholder (extend if pydantic_ai adds runtime options later)
config = {
    'enable_token_reporting': True  # Currently not passed to Agent.run (no supported kwarg)
}

# Structured output model for the Results Formatter Agent
class FormattedOutput(BaseModel):
    """Structured output model ensuring consistent response format"""
    display_type: str = Field(description="Display format: 'table' or 'markdown'")
    content: Any = Field(description="Formatted content for display - string for markdown, array for table")
    metadata: Dict[str, Any] = Field(description="Execution summary and processing info")
    processing_code: Optional[str] = Field(default=None, description="Python code for processing large datasets")

# Load the system prompts for pure Python JSON processing
def _load_complete_data_prompt() -> str:
    """Load system prompt for complete data processing with dynamic allowed methods"""
    try:
        prompt_file = os.path.join(os.path.dirname(__file__), "prompts", "results_formatter_complete_data_prompt.txt")
        with open(prompt_file, 'r', encoding='utf-8') as f:
            prompt_content = f.read()
        
        # Inject current allowed methods dynamically
        allowed_methods_section = get_allowed_methods_for_prompt()
        
        # Replace placeholder in prompt with actual allowed methods
        if "{{ALLOWED_METHODS_PLACEHOLDER}}" in prompt_content:
            prompt_content = prompt_content.replace("{{ALLOWED_METHODS_PLACEHOLDER}}", allowed_methods_section)
        
        logger.debug("Loaded complete data prompt with dynamic allowed methods for pure Python processing")
        return prompt_content
        
    except FileNotFoundError:
        logger.warning("Complete data prompt file not found, using fallback")
        return """You are a Results Formatter Agent that processes complete datasets.
CRITICAL: AGGREGATE DATA BY USER/ENTITY - Don't show repetitive rows!
For user queries: Group by user_id and concatenate groups/apps into comma-separated lists.
Create comprehensive, user-friendly data presentations with all records included."""

def _load_sample_data_prompt() -> str:
    """Load system prompt for sample data processing and code generation with dynamic allowed methods"""
    try:
        prompt_file = os.path.join(os.path.dirname(__file__), "prompts", "results_formatter_sample_data_prompt.txt")
        with open(prompt_file, 'r', encoding='utf-8') as f:
            prompt_content = f.read()
        
        # Inject current allowed methods dynamically
        allowed_methods_section = get_allowed_methods_for_prompt()
        
        # Replace placeholder in prompt with actual allowed methods
        if "{{ALLOWED_METHODS_PLACEHOLDER}}" in prompt_content:
            prompt_content = prompt_content.replace("{{ALLOWED_METHODS_PLACEHOLDER}}", allowed_methods_section)
        
        logger.debug("Loaded sample data prompt with dynamic allowed methods for pure Python processing")
        return prompt_content
        
    except FileNotFoundError:
        logger.warning("Sample data prompt file not found, using fallback")
        return """You are a Results Formatter Agent that processes sample data and generates processing code.
Analyze samples and create efficient code for processing complete datasets."""

# Create Results Formatter Agents with PydanticAI (2 specialized agents)
# Create PydanticAI agents with string output to avoid validation issues
# Complete data formatter uses REASONING model for data understanding and formatting
complete_data_formatter = Agent(
    reasoning_model,
    system_prompt=_load_complete_data_prompt(),
    # No output_type - will return raw string which we can parse manually
    retries=0  # No retries to avoid wasting money on failed attempts
)

# Sample data formatter uses CODING model for Python JSON code generation
sample_data_formatter = Agent(
    coding_model, 
    system_prompt=_load_sample_data_prompt(),
    # No output_type - will return raw string which we can parse manually
    retries=0  # No retries to avoid wasting money on failed attempts
)

def _parse_raw_llm_response(raw_response: str, flow_id: str) -> Dict[str, Any]:
    """Parse raw LLM response string into structured format"""
    try:
        # Log the raw response we're trying to parse
        logger.debug(f"[{flow_id}] Raw LLM Response to parse: {raw_response[:1000]}...")
        
        # Try to find JSON in the response
        raw_str = str(raw_response).strip()
        
        # Look for JSON block markers
        if '```json' in raw_str:
            start = raw_str.find('```json') + 7
            end = raw_str.find('```', start)
            if end != -1:
                json_str = raw_str[start:end].strip()
            else:
                json_str = raw_str[start:].strip()
        elif raw_str.startswith('{') and raw_str.endswith('}'):
            json_str = raw_str
        else:
            # Try to find JSON anywhere in the response
            import re
            json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
            matches = re.findall(json_pattern, raw_str, re.DOTALL)
            if matches:
                json_str = matches[-1]  # Take the last/largest match
            else:
                raise ValueError("No JSON found in response")
        
        # Parse the JSON
        parsed = json.loads(json_str)
        logger.debug(f"[{flow_id}] Successfully parsed JSON: {list(parsed.keys())}")
        
        # Ensure required fields exist with defaults
        # CRITICAL: Don't wrap content - frontend expects direct values
        result = {
            'display_type': parsed.get('display_type', 'markdown'),
            'content': parsed.get('content', 'Processing completed'),
            'metadata': parsed.get('metadata', {'status': 'completed'}),
            'processing_code': parsed.get('processing_code', None)
        }
        
        return result
        
    except Exception as e:
        logger.error(f"[{flow_id}] Failed to parse raw LLM response: {e}")
        logger.error(f"[{flow_id}] Raw response was: {raw_response}")
        
        # For Results Formatter parsing failures, we should throw an exception
        # so the upstream error handling can provide a clean user-friendly message
        raise ValueError(f"Results formatting failed: Unable to parse LLM response. The AI model returned malformed output. Please try your query again.")
        
        # This fallback should never be reached due to the exception above
        # but keeping it as a safety net
        return {
            'display_type': 'markdown',
            'content': 'Results processing failed: The AI model returned malformed output. Please try your query again.',
            'metadata': {'status': 'parsing_failed', 'error': str(e)},
            'processing_code': None
        }

def _count_total_records(results: Dict[str, Any]) -> int:
    """Count total records across all data sources - NEW structure only"""
    total = 0
    
    # Handle direct step data structure from Modern Execution Manager
    # Modern Execution Manager passes step_results_for_processing directly as results
    for step_name, step_data in results.items():
        if isinstance(step_data, list):
            total += len(step_data)
    
    return total

def _simplify_sample_record(record: Any) -> Any:
    """Simplify individual records to reduce token usage in samples"""
    if not isinstance(record, dict):
        return record
    
    simplified = {}
    for key, value in record.items():
        # Remove heavy nested metadata that's not essential for analysis
        if key == '_links':
            simplified[key] = '[removed_for_sampling]'
        elif isinstance(value, dict) and len(str(value)) > 200:
            simplified[key] = '[large_object_simplified]'
        elif isinstance(value, list) and len(value) > 5:
            # Keep first few items in lists
            simplified[key] = value[:3] + ['[...truncated]']
        else:
            simplified[key] = value
    
    return simplified

def _create_complete_data_prompt(query: str, results: Dict[str, Any], original_plan: Optional[str], 
                               dataset_size_context: str, total_records: int) -> str:
    """Create prompt for processing complete data"""
    
    plan_reasoning = original_plan if original_plan else "No plan provided"
    results_str = json.dumps(results, default=str)
    
    # Truncate very large results to prevent token overflow
    if len(results_str) > 15000:
        results_str = results_str[:15000] + "... [truncated for size]"
    
    return f"""Query: {query}
Dataset Size: {total_records} total records{dataset_size_context}
Plan Context: {plan_reasoning}
Complete Results: {results_str}

You are processing the COMPLETE dataset. Create a comprehensive, user-friendly response that directly answers the user's query.
Focus on clear presentation and include performance recommendations in your metadata if this is a large dataset."""

def _create_sample_data_prompt(query: str, sampled_results: Dict[str, Any], relationship_analysis: Optional[Dict[str, Any]], 
                              total_records: int, execution_journey: str) -> str:
    """Create prompt for processing sample data and generating code with relationship analysis"""
    
    # Use relationship analysis instead of plan reasoning
    analysis_info = ""
    if relationship_analysis:
        analysis_info = f"RELATIONSHIP ANALYSIS:\n{json.dumps(relationship_analysis, indent=2)}\n\n"
    else:
        analysis_info = "No relationship analysis provided - use dynamic field discovery.\n\n"
    results_str = json.dumps(sampled_results, default=str)
    
    # CRITICAL: Aggressively truncate to ensure we stay under token limits
    # Even with samples and simplification, complex nested data can be large
    max_results_chars = 20000  # Conservative limit for sample data
    if len(results_str) > max_results_chars:
        results_str = results_str[:max_results_chars] + "... [sample data truncated to fit context]"
        print(f"[STATS] Sample prompt truncated from {len(json.dumps(sampled_results, default=str))} to {max_results_chars} chars")
    
    # Also truncate relationship analysis if very long
    if len(analysis_info) > 3000:
        analysis_info = analysis_info[:3000] + "... [analysis truncated]"
    
    available_keys = list(sampled_results.keys())
    # Keep this dynamic block lean; core rules live in system prompt file to avoid drift.
    return (
        "=== DYNAMIC CONTEXT START ===\n"
        f"Query: {query}\n"
        f"Dataset Size: {total_records} total records (SAMPLES ONLY SHOWN)\n"
        f"{analysis_info}"
        "Execution Journey (authoritative step -> key mapping):\n"
        f"{execution_journey}\n"
        f"Available Result Keys: {available_keys}\n"
        "Sample Data (intelligent subset JSON): " + results_str + "\n\n"
        "Use only the Available Result Keys verbatim; see system prompt for all aggregation & safety rules. "
        "processing_code must access data via full_results.get('<key>', []) and never invent or shorten keys.\n"
        "If relationship analysis is provided, use its join keys and field mappings to generate accurate processing code.\n"
        "Return JSON per system prompt spec.\n"
        "=== DYNAMIC CONTEXT END ==="
    )



def _condense_plan(original_plan: Optional[str]):
    """Produce a condensed JSON string of the execution plan to lower token usage.

    Keeps only: step index, tool_name, entity, operation, and truncated query_context.
    If parsing fails, returns the original input.
    """
    if not original_plan:
        return original_plan
    try:
        plan_obj = json.loads(original_plan) if isinstance(original_plan, str) else original_plan
        steps = plan_obj.get('steps', [])
        condensed_steps = []
        for idx, s in enumerate(steps, start=1):
            qc = (s.get('query_context') or '')
            if len(qc) > 160:
                qc = qc[:160] + '…'
            condensed_steps.append({
                'step': idx,
                'tool': s.get('tool_name'),
                'entity': s.get('entity'),
                'operation': s.get('operation'),
                'context': qc
            })
        reasoning = plan_obj.get('reasoning', '')
        if isinstance(reasoning, str) and len(reasoning) > 350:
            reasoning = reasoning[:350] + '…'
        return json.dumps({'reasoning': reasoning, 'steps': condensed_steps}, ensure_ascii=False)
    except Exception:
        return original_plan


def _dump_full_results_data(query: str, results: Dict[str, Any], flow_id: str, 
                           original_plan: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
    """Dump full results data to JSON file for relationship analysis"""
    try:
        import datetime
        from pathlib import Path
        
        # Create json_results directory under logs
        log_dir = Path(get_default_log_dir())
        json_results_dir = log_dir / "json_results"
        json_results_dir.mkdir(exist_ok=True)
        
        # Create filename with timestamp and flow_id
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"full_results_{timestamp}_{flow_id}.json"
        filepath = json_results_dir / filename
        
        # Prepare data to dump
        dump_data = {
            "timestamp": datetime.datetime.now().isoformat(),
            "flow_id": flow_id,
            "query": query,
            "original_plan": original_plan,
            "metadata": metadata,
            "total_records": _count_total_records(results),
            "results": results
        }
        
        # Write to file
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(dump_data, f, indent=2, ensure_ascii=False, default=str)
        
        logger.info(f"[{flow_id}] Full results data dumped to: {filepath}")
        
    except Exception as e:
        logger.error(f"[{flow_id}] Failed to dump full results data: {e}")


async def format_results(query: str, results: Dict[str, Any], is_sample: bool = False, 
                         relationship_analysis: Optional[Dict[str, Any]] = None, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Simplified results formatting - Modern Execution Manager handles all routing decisions"""
    
    # Count total records to inform the LLM about dataset size
    total_records = _count_total_records(results)
    flow_id = metadata.get("flow_id", "unknown") if metadata else "unknown"
    
    logger.info(f"[{flow_id}] Results Formatter Agent: Starting processing")
    logger.info(f"[{flow_id}] Processing {total_records} total records (is_sample: {is_sample})")
    logger.debug(f"[{flow_id}] Query: {query}")
    
    # DUMP FULL RESULTS DATA FOR DEBUGGING - COMMENTED OUT TO REDUCE FILE I/O
    # _dump_full_results_data(query, results, flow_id, None, metadata)
    
    # Log relationship analysis availability
    if relationship_analysis:
        logger.debug(f"[{flow_id}] Relationship Analysis available: {len(str(relationship_analysis))} chars")
    else:
        logger.debug(f"[{flow_id}] No relationship analysis provided")

    try:
        # SIMPLIFIED FLOW: Modern Execution Manager already made the routing decision
        if is_sample:
            # Large dataset: Process samples + relationship analysis → Generate code
            logger.info(f"[{flow_id}] Large dataset processing: samples + relationship analysis → code generation")
            return await _process_sample_data(query, results, relationship_analysis, flow_id, total_records)
        else:
            # Small dataset: Process complete data directly
            logger.info(f"[{flow_id}] Small dataset processing: complete data → direct formatting")
            return await _process_complete_data(query, results, None, flow_id, total_records)
            
    except Exception as e:
        logger.error(f"[{flow_id}] Results Formatter Agent Error: {e}")
        return {
            'display_type': 'markdown', 
            'content': f'**Error**: {e}',
            'metadata': {
                'execution_summary': f'Formatting failed: {e}',
                'confidence_level': 'Low',
                'data_sources': ['error'],
                'total_records': 0,
                'processing_time': 'N/A',
            }
        }

async def _process_complete_data(query: str, results: Dict[str, Any], original_plan: Optional[str], 
                                flow_id: str, total_records: int) -> Dict[str, Any]:
    """Process complete dataset directly without sampling"""
    
    logger.info(f"[{flow_id}] Starting complete data processing")
    
    # Create enhanced prompt for complete data processing
    dataset_size_context = ""
    if total_records >= 1000:
        dataset_size_context = f"""

LARGE DATASET DETECTED ({total_records} records):
- Use efficient Python JSON processing patterns for reliable data transformation
- Use efficient aggregation patterns to avoid memory issues
- Focus on user-centric aggregation to reduce output size"""
    
    prompt = _create_complete_data_prompt(query, results, original_plan, dataset_size_context, total_records)
    
    # Log the prompt being sent to LLM
    logger.debug(f"[{flow_id}] Prompt to LLM (length: {len(prompt)} chars):")
    logger.debug(f"[{flow_id}] Prompt Content: {prompt[:1000]}..." if len(prompt) > 1000 else f"[{flow_id}] Prompt Content: {prompt}")
    
    try:
        logger.info(f"[{flow_id}] Sending prompt to PydanticAI complete data formatter...")
        
        # Run formatter with flexible validation
        try:
            result = await complete_data_formatter.run(prompt)
            
            # Since we're not using structured output, result should be a string
            raw_response = str(result.output) if hasattr(result, 'output') else str(result)
            
            # Parse the raw response manually
            formatted_result = _parse_raw_llm_response(raw_response, flow_id)
            
        except Exception as validation_error:
            logger.error(f"[{flow_id}] Complete data processing failed: {validation_error}")
            # Re-raise the error to be caught by outer exception handler
            raise validation_error
        
        # Log the final formatted result
        logger.info(f"[{flow_id}] Complete data processing finished")
        
        return formatted_result
        
    except Exception as e:
        logger.error(f"[{flow_id}] Complete data processing failed: {e}")
        # Return fallback response instead of re-raising
        return {
            'display_type': 'markdown',
            'content': {'text': f'**Processing Error**: {str(e)}'},
            'metadata': {
                'execution_summary': f'Complete data processing failed: {e}',
                'confidence_level': 'Low',
                'total_records_processed': total_records,
                'processing_mode': 'complete'
            },
            'usage_info': {'error': 'Complete data processing failed'}
        }

async def _process_sample_data(query: str, sampled_results: Dict[str, Any], relationship_analysis: Optional[Dict[str, Any]], 
                              flow_id: str, total_records: int) -> Dict[str, Any]:
    """Process sample data and generate code for full dataset processing using relationship analysis"""
    
    # Debug logging for samples received
    logger.debug(f"[{flow_id}] Sample Data Processing - Samples received:")
    if 'raw_results' in sampled_results and 'sql_execution' in sampled_results['raw_results']:
        logger.debug(f"[{flow_id}] SQL execution results (sample): {json.dumps(sampled_results['raw_results']['sql_execution'][:2], indent=2)}")

    # Build the Execution Journey string to guide the LLM
    execution_journey = ""
    try:
        # Get step keys from the data (no original plan needed)
        step_keys = sorted([key for key in sampled_results.keys() if key.split('_')[0].isdigit()])

        journey_lines = []
        for key in step_keys:
            parts = key.split('_')
            step_num = parts[0]
            tool_type = '_'.join(parts[1:]) if len(parts) > 1 else 'unknown'
            
            # Determine entity from the step data if possible
            entity = "unknown"
            if key in sampled_results and sampled_results[key]:
                # Try to infer entity from data structure
                if 'user' in str(sampled_results[key][0]).lower():
                    entity = "users"
                elif 'role' in str(sampled_results[key][0]).lower():
                    entity = "role_assignment"
                elif 'log' in str(sampled_results[key][0]).lower():
                    entity = "system_log"
            
            line = f"- Step {step_num}: Executed '{tool_type}' for entity '{entity}'. The data is in `full_results['{key}']`."
            journey_lines.append(line)
        execution_journey = "\n".join(journey_lines)
        logger.info(f"[{flow_id}] Generated Execution Journey:\n{execution_journey}")
    except Exception as e:
        logger.warning(f"[{flow_id}] Could not build execution journey: {e}")
        execution_journey = "Could not parse execution plan."
    
    prompt = _create_sample_data_prompt(query, sampled_results, relationship_analysis, total_records, execution_journey)
    
    # Debug logging for prompt being sent
    logger.debug(f"[{flow_id}] Sample Data Prompt (length: {len(prompt)} chars):")
    #logger.debug(f"[{flow_id}] Sample Prompt Content: {prompt[:1500]}..." if len(prompt) > 1500 else f"[{flow_id}] Sample Prompt Content: {prompt}")
    
    try:
        # Run formatter with flexible validation
        # pydantic_ai Agent.run does not accept 'config' kwarg; align with complete path handling
        result = await sample_data_formatter.run(prompt)
        raw_response = str(result.output) if hasattr(result, 'output') else str(result)
        formatted_result = _parse_raw_llm_response(raw_response, flow_id)

        # Log the final formatted result
        logger.debug(f"[{flow_id}] Sample Data Final Result Keys: {list(formatted_result.keys())}")

        # Log the generated processing code for debugging
        if formatted_result.get('processing_code'):
            logger.debug(f"[{flow_id}] Final Processing Code Generated: {formatted_result['processing_code'][:500]}...")
            logger.debug(f"[{flow_id}] COMPLETE FINAL PROCESSING CODE GENERATED:\n{formatted_result['processing_code']}")

        return formatted_result
        
    except Exception as e:
        logger.error(f"[{flow_id}] Sample data processing failed: {e}")
        # Return fallback response instead of re-raising
        raise ValueError(f"Results formatting failed during sample processing: {e}")

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
    return await format_results(query, results, is_sample, original_plan, metadata)