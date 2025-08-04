"""
Unified Results Formatter Agent - Token-Based Processing Decision

Token-based architecture:
- < 1000 tokens: Send complete data to LLM for direct processing
- ≥ 1000 tokens: Send samples + let LLM generate Polars code dynamically

Processing Modes:
1. COMPLETE MODE: LLM processes all data directly and returns formatted JSON
2. SAMPLE MODE: LLM analyzes samples and generates Polars code for execution

Model Configuration:
- Uses REASONING model for both complete data processing and code generation
"""

import asyncio
import json
import logging
import sys
import os
from typing import Dict, Any, Optional
from pydantic_ai import Agent

# Add src path for importing utils
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from src.utils.logging import get_logger, get_default_log_dir

# Setup centralized logging
logger = get_logger("okta_ai_agent", log_dir=get_default_log_dir())

# Use the model picker approach for consistent model configuration
try:
    from src.core.models.model_picker import ModelConfig, ModelType
    reasoning_model = ModelConfig.get_model(ModelType.REASONING)
except ImportError:
    def get_simple_model():
        model_name = os.getenv('LLM_MODEL', 'openai:gpt-4o')
        return model_name
    reasoning_model = get_simple_model()

def _load_complete_data_prompt() -> str:
    """Load system prompt for complete data processing"""
    try:
        prompt_file = os.path.join(os.path.dirname(__file__), "prompts", "results_formatter_complete_data_prompt.txt")
        with open(prompt_file, 'r', encoding='utf-8') as f:
            prompt_content = f.read()
        
        logger.debug("Loaded complete data processing prompt")
        return prompt_content
    except Exception as e:
        logger.error(f"Failed to load complete data prompt: {e}")
        return """You are an expert Results Formatter Agent. Process the provided data and return properly formatted JSON response with display_type, content, and metadata fields."""

def _load_sample_data_prompt() -> str:
    """Load system prompt for sample data processing with Polars pattern selection"""
    try:
        prompt_file = os.path.join(os.path.dirname(__file__), "prompts", "results_formatter_pattern_selection_prompt.txt")
        with open(prompt_file, 'r', encoding='utf-8') as f:
            prompt_content = f.read()
        
        logger.debug("Loaded pattern selection prompt for sample data processing")
        return prompt_content
    except Exception as e:
        logger.error(f"Failed to load pattern selection prompt: {e}")
        return """You are an expert Results Formatter Agent. Analyze the sample data and select appropriate Polars patterns to process the complete dataset."""

# Create agents for both processing modes
complete_data_agent = Agent(
    reasoning_model,
    system_prompt=_load_complete_data_prompt(),
    retries=0
)

sample_data_agent = Agent(
    reasoning_model,
    system_prompt=_load_sample_data_prompt(),
    retries=0
)

def _count_tokens(data: Dict[str, Any]) -> int:
    """Count approximate tokens in the data"""
    try:
        # Convert data to JSON string and estimate tokens
        # Rough approximation: 1 token ≈ 4 characters
        json_str = json.dumps(data, default=str)
        estimated_tokens = len(json_str) // 4
        logger.debug(f"Data size: {len(json_str)} chars, estimated tokens: {estimated_tokens}")
        return estimated_tokens
    except Exception as e:
        logger.error(f"Token counting failed: {e}")
        return 999999  # Default to large number to trigger sample mode

def _parse_raw_llm_response(raw_response: str, flow_id: str) -> Dict[str, Any]:
    """Parse raw LLM response string into structured format"""
    try:
        logger.debug(f"[{flow_id}] Raw LLM Response type: {type(raw_response)}")
        logger.debug(f"[{flow_id}] Raw LLM Response length: {len(str(raw_response))}")
        logger.debug(f"[{flow_id}] Raw LLM Response to parse: {str(raw_response)}")
        
        raw_str = str(raw_response).strip()
        
        # Look for JSON block markers
        if '```json' in raw_str:
            start = raw_str.find('```json') + 7
            end = raw_str.find('```', start)
            if end > start:
                json_str = raw_str[start:end].strip()
            else:
                json_str = raw_str[start:].strip()
        elif '```' in raw_str:
            start = raw_str.find('```') + 3
            end = raw_str.find('```', start)
            if end > start:
                json_str = raw_str[start:end].strip()
            else:
                json_str = raw_str[start:].strip()
        else:
            json_str = raw_str
        
        # Try to parse as JSON
        try:
            parsed = json.loads(json_str)
            logger.debug(f"[{flow_id}] Successfully parsed JSON response")
            return parsed
        except json.JSONDecodeError as e:
            logger.warning(f"[{flow_id}] JSON parse failed: {e}")
            
            # Try to extract JSON from the middle of the response
            lines = json_str.split('\n')
            for i, line in enumerate(lines):
                if line.strip().startswith('{'):
                    remaining = '\n'.join(lines[i:])
                    try:
                        parsed = json.loads(remaining)
                        logger.debug(f"[{flow_id}] Successfully parsed JSON from line {i}")
                        return parsed
                    except:
                        continue
            
            # Last resort: return error structure
            return {
                "analysis": "Failed to parse LLM response",
                "entity_type": "unknown", 
                "steps": [],
                "field_mappings": {},
                "error": f"JSON parse error: {str(e)}"
            }
            
    except Exception as e:
        logger.error(f"[{flow_id}] Error parsing LLM response: {e}")
        return {
            "analysis": "Error processing response",
            "entity_type": "unknown",
            "steps": [],
            "field_mappings": {},
            "error": str(e)
        }

def _count_total_records(results: Dict[str, Any]) -> int:
    """Count total records across all data sources"""
    total = 0
    for step_name, step_data in results.items():
        if isinstance(step_data, list):
            total += len(step_data)
        elif isinstance(step_data, dict) and 'data' in step_data:
            if isinstance(step_data['data'], list):
                total += len(step_data['data'])
    return total

def _create_sample_data(results: Dict[str, Any], max_samples: int = 2) -> Dict[str, Any]:
    """Create sample data for LLM analysis"""
    samples = {}
    for step_name, step_data in results.items():
        if isinstance(step_data, list) and step_data:
            samples[step_name] = step_data[:max_samples]
        elif isinstance(step_data, dict) and 'data' in step_data:
            if isinstance(step_data['data'], list) and step_data['data']:
                samples[step_name] = step_data['data'][:max_samples]
    return samples

async def process_results_formatter(
    results: Dict[str, Any], 
    query: str, 
    plan: Dict[str, Any], 
    flow_id: str,
    is_sample: bool = False
) -> Dict[str, Any]:
    """
    Unified Results Formatter Agent with Token-Based Processing Decision
    
    Args:
        results: Dictionary with step results from execution
        query: Original user query
        plan: Original execution plan
        flow_id: Unique identifier for logging correlation
        is_sample: Legacy parameter, ignored (token count determines mode)
        
    Returns:
        Formatted results compatible with frontend
    """
    try:
        logger.info(f"[{flow_id}] Unified Results Formatter Agent Starting")
        
        # Count total records and tokens
        total_records = _count_total_records(results)
        token_count = _count_tokens(results)
        
        logger.info(f"[{flow_id}] Processing {total_records} total records")
        logger.info(f"[{flow_id}] Estimated tokens: {token_count}")
        
        if total_records == 0:
            logger.warning(f"[{flow_id}] No data to process")
            return {
                "display_type": "table",
                "content": [],
                "metadata": {
                    "headers": [],
                    "total_records": 0,
                    "processing_method": "no_data",
                    "entity_type": "unknown",
                    "is_sample": False,
                    "message": "No data found for your query"
                }
            }
        
        # DECISION LOGIC: < 1000 tokens = complete mode, >= 1000 tokens = sample mode
        if token_count < 1000:
            logger.info(f"[{flow_id}] Using COMPLETE MODE (tokens: {token_count} < 1000)")
            return await _process_complete_mode(results, query, plan, flow_id)
        else:
            logger.info(f"[{flow_id}] Using SAMPLE MODE (tokens: {token_count} >= 1000)")
            return await _process_sample_mode(results, query, plan, flow_id)
            
    except Exception as e:
        logger.error(f"[{flow_id}] Unified Results Formatter Agent failed: {e}")
        return _create_fallback_result(results, flow_id, error=str(e))

async def _process_complete_mode(results: Dict[str, Any], query: str, plan: Dict[str, Any], flow_id: str) -> Dict[str, Any]:
    """Process complete data by sending all data to LLM for direct formatting"""
    try:
        logger.info(f"[{flow_id}] COMPLETE MODE: Processing all data directly")
        
        # Create context with complete data
        context = f"""
Query: {query}

Plan Summary: {plan.get('reasoning', 'Multi-step data processing')}

Complete Results Data:
{json.dumps(results, indent=2, default=str)}

Process this complete dataset and return properly formatted JSON response with:
- display_type: "table" or "markdown"
- content: formatted data array (for table) or markdown string
- metadata: headers array with value/text pairs and other metadata

Ensure all records are included - do not truncate or sample any data.
"""
        
        logger.debug(f"[{flow_id}] Complete mode context: {len(context)} characters")
        
        # Call LLM with complete data
        raw_response = await complete_data_agent.run(context)
        response_text = getattr(raw_response, 'output', str(raw_response))
        
        # Parse response
        formatted_result = _parse_formatted_response(str(response_text), flow_id)
        formatted_result['metadata']['processing_method'] = 'complete_data_direct'
        formatted_result['metadata']['is_sample'] = False
        
        logger.info(f"[{flow_id}] Complete mode processing completed")
        return formatted_result
        
    except Exception as e:
        logger.error(f"[{flow_id}] Complete mode processing failed: {e}")
        return _create_fallback_result(results, flow_id, error=str(e))

async def _process_sample_mode(results: Dict[str, Any], query: str, plan: Dict[str, Any], flow_id: str) -> Dict[str, Any]:
    """Process large datasets by analyzing samples and generating Polars code"""
    try:
        logger.info(f"[{flow_id}] SAMPLE MODE: Analyzing samples and generating Polars code")
        
        # Create sample data for analysis
        sample_data = _create_sample_data(results, max_samples=3)
        
        # Create context for sample analysis and code generation
        context = f"""
Query: {query}

Plan Summary: {plan.get('reasoning', 'Multi-step data processing')}

AVAILABLE DATAFRAMES: {list(results.keys())}

Sample Data Structure (for analysis):
{json.dumps(sample_data, indent=2, default=str)}

Generate a template configuration or Polars processing code that can handle the complete dataset.
Analyze the sample structure and create appropriate field mappings and processing logic.

Return JSON response with template configuration that can process all records in the complete dataset.
"""
        
        logger.debug(f"[{flow_id}] Sample mode context: {len(context)} characters")
        
        # Call LLM for pattern selection and analysis
        raw_response = await sample_data_agent.run(context)
        response_text = getattr(raw_response, 'output', str(raw_response))
        
        # Parse pattern selection response
        pattern_plan = _parse_pattern_response(str(response_text), flow_id)
        
        # Execute using Polars Pattern Engine
        from src.data.polars_patterns import PolarsPatternEngine
        pattern_engine = PolarsPatternEngine()
        template_result = pattern_engine.execute_processing_plan(results, pattern_plan)
        template_result['metadata']['processing_method'] = 'sample_data_template'
        template_result['metadata']['is_sample'] = True
        
        logger.info(f"[{flow_id}] Sample mode processing completed")
        return template_result
        
    except Exception as e:
        logger.error(f"[{flow_id}] Sample mode processing failed: {e}")
        return _create_fallback_result(results, flow_id, error=str(e))

def _parse_formatted_response(response_text: str, flow_id: str) -> Dict[str, Any]:
    """Parse formatted response from complete mode processing"""
    try:
        # Extract JSON from response
        response_text = response_text.strip()
        
        # Handle markdown code blocks
        if '```json' in response_text:
            start = response_text.find('```json') + 7
            end = response_text.find('```', start)
            if end != -1:
                response_text = response_text[start:end].strip()
        elif '```' in response_text:
            start = response_text.find('```') + 3
            end = response_text.rfind('```')
            if end != -1 and end > start:
                response_text = response_text[start:end].strip()
        
        # Parse JSON
        parsed_response = json.loads(response_text)
        
        # Validate required fields
        if not isinstance(parsed_response, dict):
            raise ValueError("Response must be a JSON object")
        
        if 'display_type' not in parsed_response:
            parsed_response['display_type'] = 'table'
        
        if 'content' not in parsed_response:
            parsed_response['content'] = []
        
        if 'metadata' not in parsed_response:
            parsed_response['metadata'] = {}
        
        logger.debug(f"[{flow_id}] Successfully parsed complete mode response")
        return parsed_response
        
    except Exception as e:
        logger.error(f"[{flow_id}] Failed to parse complete mode response: {e}")
        return {
            "display_type": "markdown",
            "content": f"**Processing Error**: {str(e)}\n\nRaw response: {response_text[:500]}...",
            "metadata": {"error": str(e)}
        }

def _parse_pattern_response(response_text: str, flow_id: str) -> Dict[str, Any]:
    """Parse pattern selection response from sample mode processing"""
    try:
        # Extract JSON from response
        response_text = response_text.strip()
        
        # Handle markdown code blocks
        if '```json' in response_text:
            start = response_text.find('```json') + 7
            end = response_text.find('```', start)
            if end != -1:
                response_text = response_text[start:end].strip()
        elif '```' in response_text:
            start = response_text.find('```') + 3
            end = response_text.rfind('```')
            if end != -1 and end > start:
                response_text = response_text[start:end].strip()
        
        # Parse JSON pattern response
        pattern_plan = json.loads(response_text)
        
        # Validate required fields for pattern execution
        if not isinstance(pattern_plan, dict):
            raise ValueError("Pattern response must be a JSON object")
        
        if 'steps' not in pattern_plan:
            pattern_plan['steps'] = []
        
        if 'entity_type' not in pattern_plan:
            pattern_plan['entity_type'] = 'unknown'
        
        logger.debug(f"[{flow_id}] Successfully parsed pattern selection response")
        return pattern_plan
        
    except Exception as e:
        logger.error(f"[{flow_id}] Failed to parse pattern response: {e}")
        raise  # No fallback, let it fail upstream

def _create_fallback_result(results: Dict[str, Any], flow_id: str, error: str = None) -> Dict[str, Any]:
    """Create a simple fallback result when pattern processing fails"""
    try:
        # Try to find the largest dataset and return it as-is
        largest_data = []
        largest_key = ""
        
        for key, data in results.items():
            if isinstance(data, list) and len(data) > len(largest_data):
                largest_data = data
                largest_key = key
            elif isinstance(data, dict) and 'data' in data:
                if isinstance(data['data'], list) and len(data['data']) > len(largest_data):
                    largest_data = data['data']
                    largest_key = key
        
        if largest_data:
            # Create simple headers from first record
            headers = []
            if largest_data and isinstance(largest_data[0], dict):
                for key in largest_data[0].keys():
                    headers.append({
                        "value": key,
                        "text": key.replace("_", " ").title(),
                        "sortable": True
                    })
        else:
            headers = []
            largest_data = []
        
        logger.info(f"[{flow_id}] Fallback processing: {len(largest_data)} records from {largest_key}")
        
        return {
            "display_type": "table",
            "content": largest_data,
            "metadata": {
                "headers": headers,
                "total_records": len(largest_data),
                "processing_method": "fallback_simple",
                "entity_type": "unknown",
                "is_sample": False,
                "source": largest_key,
                "error": error
            }
        }
        
    except Exception as e:
        logger.error(f"[{flow_id}] Fallback processing also failed: {e}")
        return {
            "display_type": "table", 
            "content": [],
            "metadata": {
                "headers": [],
                "total_records": 0,
                "processing_method": "error_fallback",
                "entity_type": "unknown",
                "is_sample": False,
                "error": f"Complete processing failure: {error or str(e)}"
            }
        }

def _count_total_records(results: Dict[str, Any]) -> int:
    """Count total records across all data sources"""
    total = 0
    for key, data in results.items():
        if isinstance(data, list):
            total += len(data)
        elif isinstance(data, dict) and 'data' in data and isinstance(data['data'], list):
            total += len(data['data'])
    return total

def _create_sample_data(results: Dict[str, Any], max_samples: int = 2) -> Dict[str, Any]:
    """Create sample data for LLM analysis"""
    sample_data = {}
    
    for key, data in results.items():
        if isinstance(data, list) and len(data) > 0:
            # Take first few records as samples
            sample_data[key] = data[:max_samples]
        elif isinstance(data, dict):
            sample_data[key] = data
        else:
            sample_data[key] = data
    
    return sample_data
