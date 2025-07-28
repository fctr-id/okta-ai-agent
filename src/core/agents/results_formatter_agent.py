"""
Results Formatter Agent - User-Centric Data Aggregation with PydanticAI

Enhanced architecture following the proven results_processor_agent.py pattern:
- Conditional processing based on is_sample parameter
- Intelligent sampling for large datasets
- Code generation for processing complete datasets
- Robust JSON parsing with fallbacks
- Centralized logging with correlation ID support
"""

import asyncio
import json
import logging
import json
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

# Setup centralized logging with file output  
# Using main "okta_ai_agent" namespace for unified logging across all agents
logger = get_logger("okta_ai_agent", log_dir=get_default_log_dir())# Configuration
config = {
    'enable_token_reporting': True
}

# Structured output model for the Results Formatter Agent
class FormattedOutput(BaseModel):
    """Structured output model ensuring consistent response format"""
    display_type: str = Field(description="Display format: 'table' or 'markdown'")
    content: Any = Field(description="Formatted content for display - string for markdown, array for table")
    metadata: Dict[str, Any] = Field(description="Execution summary and processing info")
    processing_code: Optional[str] = Field(default=None, description="Python code for processing large datasets")

# Load the system prompts
def _load_complete_data_prompt() -> str:
    """Load system prompt for complete data processing"""
    try:
        prompt_file = os.path.join(os.path.dirname(__file__), "prompts", "results_formatter_complete_data_prompt.txt")
        with open(prompt_file, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        logger.warning("Complete data prompt file not found, using fallback")
        return """You are a Results Formatter Agent that processes complete datasets.
CRITICAL: AGGREGATE DATA BY USER/ENTITY - Don't show repetitive rows!
For user queries: Group by user_id and concatenate groups/apps into comma-separated lists.
Create comprehensive, user-friendly data presentations with all records included."""

def _load_sample_data_prompt() -> str:
    """Load system prompt for sample data processing and code generation"""
    try:
        prompt_file = os.path.join(os.path.dirname(__file__), "prompts", "results_formatter_sample_data_prompt.txt")
        with open(prompt_file, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        logger.warning("Sample data prompt file not found, using fallback")
        return """You are a Results Formatter Agent that processes sample data and generates processing code.
Analyze samples and create efficient code for processing complete datasets."""

# Create Results Formatter Agents with PydanticAI (2 specialized agents)
# Create PydanticAI agents with string output to avoid validation issues
complete_data_formatter = Agent(
    'openai:gpt-4o',
    system_prompt=_load_complete_data_prompt(),
    # No output_type - will return raw string which we can parse manually
    retries=0  # No retries to avoid wasting money on failed attempts
)

sample_data_formatter = Agent(
    'openai:gpt-4o', 
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
        
        # Return a minimal fallback structure compatible with frontend
        return {
            'display_type': 'markdown',
            'content': f'**Processing Error**: {raw_response}',
            'metadata': {'status': 'parsing_failed', 'error': str(e)},
            'processing_code': None
        }

def _count_total_records(results: Dict[str, Any]) -> int:
    """Count total records across all data sources"""
    total = 0
    
    # NEW: Handle direct step data structure from Modern Execution Manager
    # Modern Execution Manager passes step_results_for_processing directly as results
    for step_name, step_data in results.items():
        if isinstance(step_data, list):
            total += len(step_data)
            continue
    
    # LEGACY: Keep old structure support for backward compatibility
    if 'raw_results' in results:
        raw_results = results['raw_results']
        sql_data = raw_results.get('sql_execution', {}).get('data', [])
        total += len(sql_data)
        
        # Count API records
        step_results = raw_results.get('step_results', [])
        for step in step_results:
            if step.get('step_type') == 'api' and step.get('data'):
                total += len(step.get('data', []))
    
    return total

def _create_intelligent_samples(results: Dict[str, Any], total_records: int) -> Dict[str, Any]:
    """Create intelligent samples from each step's output instead of sending all data"""
    
    # Determine sample size based on total records
    if total_records <= 10:
        sample_size = total_records  # Send all if very small
    elif total_records <= 100:
        sample_size = min(10, total_records)  # Sample 10 records
    elif total_records <= 1000:
        sample_size = min(20, total_records)  # Sample 20 records  
    else:
        sample_size = min(50, total_records)  # Sample 50 records for large datasets
    
    print(f"📊 Creating samples: {sample_size} records from {total_records} total")
    
    sampled_results = {}
    
    # Copy non-data fields as-is
    for key, value in results.items():
        if key != 'raw_results':
            sampled_results[key] = value
    
    # Sample from raw_results if it exists
    if 'raw_results' in results:
        raw_results = results['raw_results']
        sampled_raw = {}
        
        # Copy non-data fields from raw_results
        for key, value in raw_results.items():
            if key not in ['sql_execution', 'step_results']:
                sampled_raw[key] = value
        
        # Sample SQL execution data
        if 'sql_execution' in raw_results:
            sql_exec = raw_results['sql_execution']
            sampled_sql = {}
            
            # Copy metadata
            for key, value in sql_exec.items():
                if key != 'data':
                    sampled_sql[key] = value
            
            # Sample the data
            if 'data' in sql_exec and sql_exec['data']:
                original_data = sql_exec['data']
                if len(original_data) <= sample_size:
                    sampled_sql['data'] = original_data
                else:
                    # Take first few, last few, and some middle records for variety
                    first_records = original_data[:sample_size//3]
                    last_records = original_data[-sample_size//3:]
                    middle_start = len(original_data) // 2 - (sample_size//3)//2
                    middle_records = original_data[middle_start:middle_start + (sample_size//3)]
                    
                    sampled_sql['data'] = first_records + middle_records + last_records
                    sampled_sql['sample_info'] = {
                        'total_records': len(original_data),
                        'sampled_records': len(sampled_sql['data']),
                        'sampling_strategy': 'first_middle_last'
                    }
                print(f"   📊 SQL data: {len(sampled_sql.get('data', []))} samples from {len(sql_exec.get('data', []))} records")
            
            sampled_raw['sql_execution'] = sampled_sql
        
        # Sample step_results data
        if 'step_results' in raw_results:
            sampled_steps = []
            for step in raw_results['step_results']:
                sampled_step = {}
                
                # Copy metadata
                for key, value in step.items():
                    if key != 'data':
                        sampled_step[key] = value
                
                # Sample the data if it exists
                if 'data' in step and step['data']:
                    original_data = step['data']
                    if len(original_data) <= sample_size:
                        sampled_step['data'] = original_data
                    else:
                        # Take diverse samples
                        step_sample_size = min(sample_size, len(original_data))
                        import random
                        sampled_step['data'] = random.sample(original_data, step_sample_size)
                        sampled_step['sample_info'] = {
                            'total_records': len(original_data),
                            'sampled_records': len(sampled_step['data']),
                            'sampling_strategy': 'random'
                        }
                    print(f"   📊 {step.get('step_type', 'Unknown')} step: {len(sampled_step.get('data', []))} samples from {len(step.get('data', []))} records")
                
                sampled_steps.append(sampled_step)
            
            sampled_raw['step_results'] = sampled_steps
        
        sampled_results['raw_results'] = sampled_raw
    
    return sampled_results

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

def _create_sample_data_prompt(query: str, sampled_results: Dict[str, Any], original_plan: Optional[str], 
                              total_records: int) -> str:
    """Create prompt for processing sample data and generating code"""
    
    plan_reasoning = original_plan if original_plan else "No plan provided"
    results_str = json.dumps(sampled_results, default=str)
    
    return f"""Query: {query}
Dataset Size: {total_records} total records (LARGE DATASET - you're seeing samples)
Plan Context: {plan_reasoning}
Sample Data: {results_str}

IMPORTANT: You are seeing SAMPLES from a large dataset of {total_records} records.

Your tasks:
1. Analyze the data structure and patterns from these samples
2. Create a user-friendly response based on the samples
3. For large datasets, include processing_code that can handle the full dataset efficiently
4. Recommend Polars for datasets > 1000 records for 5-10x performance improvement
5. Focus on user-centric aggregation to reduce output complexity

Include performance optimizations and processing recommendations in your metadata."""

async def format_results(query: str, results: Dict[str, Any], is_sample: bool = False, 
                         original_plan: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Enhanced results formatting with conditional processing based on dataset size"""
    
    
    # Count total records to inform the LLM about dataset size
    total_records = _count_total_records(results)
    flow_id = metadata.get("flow_id", "unknown") if metadata else "unknown"
    
    logger.info(f"[{flow_id}] Results Formatter Agent Starting")
    logger.info(f"[{flow_id}] Processing {total_records} total records (is_sample: {is_sample})")
    logger.debug(f"[{flow_id}] Query: {query}")
    logger.debug(f"[{flow_id}] Original Plan: {original_plan}")
    
    # Log the input data structure for debugging
    if 'raw_results' in results:
        raw_results = results['raw_results']
        if 'sql_execution' in raw_results:
            sql_data = raw_results['sql_execution'].get('data', [])
            logger.debug(f"[{flow_id}] SQL Data: {len(sql_data)} records")
            if sql_data:
                sample_record = sql_data[0]
                logger.debug(f"[{flow_id}] Sample SQL Record Keys: {list(sample_record.keys())}")
                # Log the complete first record for debugging (not truncated fields)
                logger.debug(f"[{flow_id}] Complete Sample SQL Record: {sample_record}")
    
    def _estimate_token_count(data):
        """
        Estimate token count for LLM processing.
        Rough estimation: 1 token ≈ 4 characters for English text
        """
        try:
            import json
            data_str = json.dumps(data, ensure_ascii=False)
            # Rough token estimation: 1 token ≈ 4 characters
            estimated_tokens = len(data_str) // 4
            return estimated_tokens
        except:
            # Fallback to string length estimation
            data_str = str(data)
            return len(data_str) // 4

    try:
        # Determine processing approach based on estimated token count (LLM context-aware)
        estimated_tokens = _estimate_token_count(results)
        token_threshold = 5000  # Conservative threshold to stay within LLM context limits
        
        if estimated_tokens <= token_threshold:  # Process if within token limits
            # Small-to-medium dataset - process directly with aggregation  
            logger.info(f"[{flow_id}] Processing complete dataset directly (estimated {estimated_tokens} tokens, {total_records} records)")
            return await _process_complete_data(query, results, original_plan, flow_id, total_records)
        else:
            # Large dataset - use sampling for efficiency and to avoid token limits
            logger.info(f"[{flow_id}] Processing samples for large dataset (estimated {estimated_tokens} tokens, {total_records} records)")
            sampled_results = _create_intelligent_samples(results, total_records)
            return await _process_sample_data(query, sampled_results, original_plan, flow_id, total_records)
            
    except Exception as e:
        logger.error(f"[{flow_id}] Results Formatter Agent Error: {e}")
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

async def _process_complete_data(query: str, results: Dict[str, Any], original_plan: Optional[str], 
                                flow_id: str, total_records: int) -> Dict[str, Any]:
    """Process complete dataset directly without sampling"""
    
    logger.info(f"[{flow_id}] Starting complete data processing")
    
    # Create enhanced prompt for complete data processing
    dataset_size_context = ""
    if total_records >= 1000:
        dataset_size_context = f"""

🚀 LARGE DATASET DETECTED ({total_records} records):
- Consider recommending Polars for 5-10x faster processing than pandas
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
            raw_response = str(result.data) if hasattr(result, 'data') else str(result)
            
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

async def _process_sample_data(query: str, sampled_results: Dict[str, Any], original_plan: Optional[str], 
                              flow_id: str, total_records: int) -> Dict[str, Any]:
    """Process sample data and generate code for full dataset processing"""
    
    # Debug logging for samples received
    logger.debug(f"[{flow_id}] Sample Data Processing - Samples received:")
    if 'raw_results' in sampled_results and 'sql_execution' in sampled_results['raw_results']:
        sql_data = sampled_results['raw_results']['sql_execution'].get('data', [])
        logger.debug(f"[{flow_id}] SQL Sample Data: {len(sql_data)} records")
        if sql_data:
            # Log complete first 2 records for debugging (not truncated fields)
            logger.debug(f"[{flow_id}] Complete first 2 SQL sample records: {sql_data[:2]}")
    
    prompt = _create_sample_data_prompt(query, sampled_results, original_plan, total_records)
    
    # Debug logging for prompt being sent
    logger.debug(f"[{flow_id}] Sample Data Prompt (length: {len(prompt)} chars):")
    logger.debug(f"[{flow_id}] Sample Prompt Content: {prompt[:1000]}..." if len(prompt) > 1000 else f"[{flow_id}] Sample Prompt Content: {prompt}")
    
    try:
        if config['enable_token_reporting']:
            logger.info(f"[{flow_id}] Processing samples and generating code with specialized PydanticAI agent...")
        
        # Run formatter with flexible validation
        try:
            result = await sample_data_formatter.run(prompt)
            
            # Since we're not using structured output, result should be a string
            raw_response = str(result.data) if hasattr(result, 'data') else str(result)
            
            # Parse the raw response manually
            formatted_result = _parse_raw_llm_response(raw_response, flow_id)
            
        except Exception as validation_error:
            logger.error(f"[{flow_id}] Sample data processing failed: {validation_error}")
            # Re-raise the error to be caught by outer exception handler
            raise validation_error
        
        # Debug logging for final formatted output
        logger.debug(f"[{flow_id}] Sample Data Final Result Keys: {list(formatted_result.keys())}")
        if 'processing_code' in formatted_result:
            logger.debug(f"[{flow_id}] Final Processing Code Generated: {formatted_result['processing_code'][:300] if formatted_result['processing_code'] else 'None'}...")
            # Log the complete final processing code for debugging
            if formatted_result['processing_code']:
                logger.debug(f"[{flow_id}] COMPLETE FINAL PROCESSING CODE GENERATED:\n{formatted_result['processing_code']}")
        
        return formatted_result
        
    except Exception as e:
        logger.error(f"[{flow_id}] Sample data processing failed: {e}")
        # Return fallback response instead of re-raising
        return {
            'display_type': 'markdown',
            'content': {'text': f'**Processing Error**: {str(e)}'},
            'metadata': {
                'execution_summary': f'Sample data processing failed: {e}',
                'confidence_level': 'Low',
                'total_records_processed': total_records,
                'processing_mode': 'sample'
            },
            'usage_info': {'error': 'Sample data processing failed'}
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
    return await format_results(query, results, is_sample, original_plan, metadata)
