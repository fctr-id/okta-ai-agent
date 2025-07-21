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
from utils.logging import get_logger, generate_correlation_id, set_correlation_id

# Setup centralized logging
logger = get_logger(__name__)

# Configuration
config = {
    'enable_token_reporting': True
}

# Structured output model for the Results Formatter Agent
class FormattedOutput(BaseModel):
    """Structured output model ensuring consistent response format"""
    display_type: str = Field(description="Display format: 'table' or 'markdown'")
    content: Dict[str, Any] = Field(description="Formatted content for display")
    metadata: Dict[str, Any] = Field(description="Execution summary and processing info")
    processing_code: Optional[str] = Field(default=None, description="Python code for processing large datasets")

# Load the system prompts
def _load_complete_data_prompt() -> str:
    """Load system prompt for complete data processing"""
    try:
        prompt_file = r"c:\Users\Dharanidhar\Desktop\github-repos\okta-ai-agent\src\data\results_formatter_complete_data_prompt.txt"
        with open(prompt_file, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        logger.warning("⚠️ Complete data prompt file not found, using fallback")
        return """You are a Results Formatter Agent that processes complete datasets.
CRITICAL: AGGREGATE DATA BY USER/ENTITY - Don't show repetitive rows!
For user queries: Group by user_id and concatenate groups/apps into comma-separated lists.
Create comprehensive, user-friendly data presentations with all records included."""

def _load_sample_data_prompt() -> str:
    """Load system prompt for sample data processing and code generation"""
    try:
        prompt_file = r"c:\Users\Dharanidhar\Desktop\github-repos\okta-ai-agent\src\data\results_formatter_sample_data_prompt.txt"
        with open(prompt_file, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        logger.warning("⚠️ Sample data prompt file not found, using fallback")
        return """You are a Results Formatter Agent that processes sample data and generates processing code.
Analyze samples and create efficient code for processing complete datasets."""

# Create Results Formatter Agents with PydanticAI (2 specialized agents)
# SIMPLIFIED: Use more flexible validation to avoid retry issues
complete_data_formatter = Agent(
    'openai:gpt-4o',
    system_prompt=_load_complete_data_prompt(),
    retries=1  # Allow 1 retry but use more flexible validation
)

sample_data_formatter = Agent(
    'openai:gpt-4o', 
    system_prompt=_load_sample_data_prompt(),
    retries=1  # Allow 1 retry but use more flexible validation
)

def _count_total_records(results: Dict[str, Any]) -> int:
    """Count total records across all data sources"""
    total = 0
    
    # Count SQL records
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

async def _parse_and_enhance_response(result, flow_id: str, total_records: int, is_complete: bool) -> Dict[str, Any]:
    """Parse PydanticAI response and enhance with metadata - flexible parsing"""
    
    try:
        # Try structured output first, then fall back to string parsing
        if hasattr(result, 'output') and hasattr(result.output, 'display_type'):
            # Structured output (PydanticAI with output_type)
            response_data = result.output
            response_json = {
                "display_type": response_data.display_type,
                "content": response_data.content,
                "metadata": response_data.metadata
            }
            if hasattr(response_data, 'processing_code') and response_data.processing_code:
                response_json['processing_code'] = response_data.processing_code
                
        elif hasattr(result, 'data'):
            # String output - parse JSON
            raw_text = result.data
            # Try to extract JSON from the response
            import re
            json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
            if json_match:
                response_json = json.loads(json_match.group())
            else:
                # Fallback to simple response
                response_json = {
                    "display_type": "markdown",
                    "content": {"text": raw_text},
                    "metadata": {"execution_summary": "Simple text response"}
                }
        else:
            # Direct string result
            raw_text = str(result)
            response_json = {
                "display_type": "markdown", 
                "content": {"text": raw_text},
                "metadata": {"execution_summary": "Direct string response"}
            }
        
        # Enhance metadata with dataset info
        if 'metadata' not in response_json:
            response_json['metadata'] = {}
            
        response_json['metadata']['total_records_processed'] = total_records
        response_json['metadata']['processing_mode'] = 'complete' if is_complete else 'sample'
        
        if total_records >= 1000:
            response_json['metadata']['performance_recommendation'] = "Consider Polars for enterprise-scale processing"
        
        # Token usage reporting (if enabled)
        if config['enable_token_reporting'] and hasattr(result, 'usage'):
            usage = result.usage()
            if usage:
                logger.info(f"[{flow_id}] 💰 Token Usage:")
                logger.info(f"   📥 Input: {getattr(usage, 'request_tokens', getattr(usage, 'input_tokens', 0))} tokens")
                logger.info(f"   📤 Output: {getattr(usage, 'response_tokens', getattr(usage, 'output_tokens', 0))} tokens") 
                logger.info(f"   📊 Total: {getattr(usage, 'total_tokens', 0)} tokens")
                
                # Add to response
                input_tokens = getattr(usage, 'request_tokens', getattr(usage, 'input_tokens', 0))
                output_tokens = getattr(usage, 'response_tokens', getattr(usage, 'output_tokens', 0))
                total_tokens = getattr(usage, 'total_tokens', input_tokens + output_tokens)
                response_json['usage_info'] = {
                    'input_tokens': input_tokens,
                    'output_tokens': output_tokens,
                    'total_tokens': total_tokens,
                    'estimated_cost': f"${((input_tokens * 0.00001) + (output_tokens * 0.00003)):.6f}"
                }
        
        logger.info(f"[{flow_id}] ✅ Successfully processed with flexible parsing")
        return response_json
        
    except Exception as e:
        logger.error(f"[{flow_id}] ❌ Response parsing failed: {e}")
        # Create fallback response
        return {
            'display_type': 'markdown',
            'content': {'text': f'Processing completed but response parsing failed: {e}'},
            'metadata': {
                'execution_summary': f'Parsing failed: {e}',
                'confidence_level': 'Low',
                'total_records_processed': total_records,
                'processing_mode': 'complete' if is_complete else 'sample'
            },
            'usage_info': {'error': 'Response parsing failed'}
        }

async def format_results(query: str, results: Dict[str, Any], is_sample: bool = False, 
                         original_plan: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Enhanced results formatting with conditional processing based on dataset size"""
    
    
    # Count total records to inform the LLM about dataset size
    total_records = _count_total_records(results)
    flow_id = metadata.get("flow_id", "unknown") if metadata else "unknown"
    
    logger.info(f"[{flow_id}] 🎯 Results Formatter Agent Starting")
    logger.info(f"[{flow_id}] 📊 Processing {total_records} total records (is_sample: {is_sample})")
    logger.debug(f"[{flow_id}] 📝 Query: {query}")
    logger.debug(f"[{flow_id}] 📋 Original Plan: {original_plan}")
    
    # Log the input data structure for debugging
    if 'raw_results' in results:
        raw_results = results['raw_results']
        if 'sql_execution' in raw_results:
            sql_data = raw_results['sql_execution'].get('data', [])
            logger.debug(f"[{flow_id}] 💾 SQL Data: {len(sql_data)} records")
            if sql_data:
                sample_record = sql_data[0]
                logger.debug(f"[{flow_id}] 📑 Sample SQL Record Keys: {list(sample_record.keys())}")
                logger.debug(f"[{flow_id}] 📑 Sample SQL Record: {sample_record}")
    
    try:
        # Determine processing approach based on dataset size (prioritize complete processing for medium datasets)
        if total_records <= 200:  # Process up to 200 records directly to ensure aggregation works
            # Small-to-medium dataset - process directly with aggregation
            logger.info(f"[{flow_id}] 🔄 Processing complete dataset directly")
            return await _process_complete_data(query, results, original_plan, flow_id, total_records)
        else:
            # Large dataset - use sampling for efficiency and to avoid token limits
            logger.info(f"[{flow_id}] 🔄 Processing samples for large dataset ({total_records} records)")
            sampled_results = _create_intelligent_samples(results, total_records)
            return await _process_sample_data(query, sampled_results, original_plan, flow_id, total_records)
            
    except Exception as e:
        logger.error(f"[{flow_id}] ❌ Results Formatter Agent Error: {e}")
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
    
    logger.info(f"[{flow_id}] 🎨 Starting complete data processing")
    
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
    logger.debug(f"[{flow_id}] 📝 Prompt to LLM (length: {len(prompt)} chars):")
    logger.debug(f"[{flow_id}] 📝 Prompt Content: {prompt[:1000]}..." if len(prompt) > 1000 else f"[{flow_id}] 📝 Prompt Content: {prompt}")
    
    try:
        logger.info(f"[{flow_id}] 🤖 Sending prompt to PydanticAI complete data formatter...")
        
        # Run formatter with flexible validation
        result = await complete_data_formatter.run(prompt)
        
        # Log the LLM response
        logger.debug(f"[{flow_id}] 🤖 LLM Response Type: {type(result)}")
        if hasattr(result, 'data'):
            logger.debug(f"[{flow_id}] 🤖 LLM Response Data: {str(result.data)[:500]}...")
        elif hasattr(result, 'message'):
            logger.debug(f"[{flow_id}] 🤖 LLM Response Message: {str(result.message)[:500]}...")
        else:
            logger.debug(f"[{flow_id}] 🤖 LLM Response: {str(result)[:500]}...")
        
        formatted_result = await _parse_and_enhance_response(result, flow_id, total_records, is_complete=True)
        
        # Log the final formatted result
        logger.info(f"[{flow_id}] ✅ Complete data processing finished")
        logger.debug(f"[{flow_id}] 📊 Final Result Keys: {list(formatted_result.keys())}")
        if 'content' in formatted_result:
            content = formatted_result['content']
            if isinstance(content, list):
                logger.info(f"[{flow_id}] 📊 Final Content: {len(content)} items")
                if content:
                    logger.debug(f"[{flow_id}] 📊 Sample Content Item: {content[0]}")
            else:
                logger.debug(f"[{flow_id}] 📊 Final Content: {str(content)[:200]}...")
        
        return formatted_result
        
    except Exception as e:
        logger.error(f"[{flow_id}] ❌ Complete data processing failed: {e}")
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
    
    prompt = _create_sample_data_prompt(query, sampled_results, original_plan, total_records)
    
    try:
        if config['enable_token_reporting']:
            logger.info(f"[{flow_id}] 🎨 Processing samples and generating code with specialized PydanticAI agent...")
        
        # Run formatter with flexible validation
        result = await sample_data_formatter.run(prompt)
        return await _parse_and_enhance_response(result, flow_id, total_records, is_complete=False)
        
    except Exception as e:
        logger.error(f"[{flow_id}] ❌ Sample data processing failed: {e}")
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
