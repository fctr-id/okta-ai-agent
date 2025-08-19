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

def _create_intelligent_samples(results: Dict[str, Any], total_records: int) -> Dict[str, Any]:
    """Create intelligent samples from each step's output - NEW structure only"""
    import random
    
    # Determine total sample target based on dataset size
    if total_records <= 10:
        target_samples = total_records  # Send all if very small
    elif total_records <= 100:
        target_samples = min(10, total_records)  # Sample 10 records
    else:
        target_samples = min(20, total_records)  # Sample 20 records for large datasets
    
    # Detect step keys (format: "1_api", "2_sql", "3_api", etc.)
    step_keys = [key for key in results.keys() if key.split('_')[0].isdigit()]
    
    if not step_keys:
        print(f"[STATS] No step keys found in results: {list(results.keys())}")
        return results  # Return as-is if no step structure detected
    
    print(f"[STATS] Creating samples: {target_samples} total from {total_records} records across {len(step_keys)} steps")
    print(f"[STATS] Detected step keys: {step_keys}")
    
    # Distribute samples across steps
    samples_per_step = max(1, target_samples // len(step_keys))
    remaining_samples = target_samples % len(step_keys)
    
    sampled_results = {}
    
    for i, step_key in enumerate(step_keys):
        step_data = results[step_key]
        
        if isinstance(step_data, list) and len(step_data) > 0:
            # Calculate samples for this step (distribute remainder to first steps)
            step_sample_count = samples_per_step + (1 if i < remaining_samples else 0)
            step_sample_count = min(step_sample_count, len(step_data))
            
            if len(step_data) <= step_sample_count:
                # Use all records if step has few records
                sampled_data = step_data
            else:
                # Random sampling from this step
                sampled_data = random.sample(step_data, step_sample_count)
            
            # Simplify the sampled records to reduce token usage
            simplified_samples = [_simplify_sample_record(record) for record in sampled_data]
            sampled_results[step_key] = simplified_samples
            
            print(f"   [STATS] {step_key}: {len(simplified_samples)} simplified samples from {len(step_data)} records")
        else:
            # Copy non-list data as-is
            sampled_results[step_key] = step_data
            print(f"   [STATS] {step_key}: copied non-list data as-is")
    
    # Copy any non-step keys as-is
    for key, value in results.items():
        if key not in step_keys:
            sampled_results[key] = value
    
    total_sampled = sum(len(data) for data in sampled_results.values() if isinstance(data, list))
    print(f"[STATS] Final sample result: {total_sampled} records total")
    
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
                              total_records: int, step_schemas: Optional[Dict[str, Any]] = None) -> str:
    """Create prompt for processing sample data and generating code"""
    
    plan_reasoning = original_plan if original_plan else "No plan provided"
    
    # Combine schema information with sample data for each step
    if step_schemas:
        enhanced_results = {}
        for step_key, step_data in sampled_results.items():
            if step_key in step_schemas and isinstance(step_data, list):
                enhanced_results[step_key] = {
                    "schema": step_schemas[step_key],
                    "data": step_data
                }
            else:
                enhanced_results[step_key] = step_data
        results_str = json.dumps(enhanced_results, default=str)
    else:
        results_str = json.dumps(sampled_results, default=str)
    
    # CRITICAL: Aggressively truncate to ensure we stay under token limits
    # Even with samples and simplification, complex nested data can be large
    max_results_chars = 20000  # Conservative limit for sample data
    if len(results_str) > max_results_chars:
        results_str = results_str[:max_results_chars] + "... [sample data truncated to fit context]"
        print(f"[STATS] Sample prompt truncated from {len(json.dumps(sampled_results, default=str))} to {max_results_chars} chars")
    
    # Also truncate plan if very long
    if len(plan_reasoning) > 3000:
        plan_reasoning = plan_reasoning[:3000] + "... [plan truncated]"
    
    schema_info = ""
    if step_schemas:
        schema_info = "\n\nDATA STRUCTURE INFORMATION:\nEach step now includes both 'schema' (data structure details) and 'data' (sample records).\nUse the schema information to understand column types, record counts, and whether data has nested structures."
    
    # Critical: Tell LLM the exact data keys available in full_results
    available_keys = list(sampled_results.keys())
    if 'metadata' in available_keys:
        available_keys.remove('metadata')  # Don't include metadata in processing
    
    available_keys_info = f"\n\nAVAILABLE DATA KEYS IN full_results:\nThe exact keys you must use in your processing_code are: {available_keys}\nExample usage: full_results.get('{available_keys[0] if available_keys else 'step_key'}', [])"
    
    return f"""Query: {query}
Dataset Size: {total_records} total records (LARGE DATASET - you're seeing samples)
Plan Context: {plan_reasoning}
Sample Data with Schema: {results_str}{schema_info}{available_keys_info}

IMPORTANT: You are seeing SAMPLES from a large dataset of {total_records} records.

Your tasks:
1. Analyze the data structure and patterns from these samples AND schema information
2. Create a user-friendly response based on the samples
3. For large datasets, include processing_code that can handle the full dataset efficiently
4. Use pure Python JSON processing for reliable and compatible data transformation
5. Focus on user-centric aggregation to reduce output complexity
6. Pay attention to schema 'has_nested_data' flags to use correct iteration patterns

Include performance optimizations and processing recommendations in your metadata."""

def _requires_aggregation(query: str) -> bool:
    """
    Check if the user's query explicitly requests grouping, aggregation, or summarization.
    If so, we should use LLM formatting instead of direct SQL formatting.
    """
    query_lower = query.lower()
    
    # Keywords that indicate the user wants data grouped/aggregated
    aggregation_keywords = [
        'group by', 'group them by', 'grouped by', 'organize by',
        'aggregate', 'summarize', 'summary', 'breakdown',
        'collapse', 'consolidate', 'merge', 'combine',
        'unique users', 'distinct users', 'each user',
        'per user', 'by user', 'for each user'
    ]
    
    for keyword in aggregation_keywords:
        if keyword in query_lower:
            return True
    
    return False

def _is_single_sql_query(results: Dict[str, Any], original_plan: Optional[str] = None) -> bool:
    """
    Check if this is a single SQL query that can be formatted directly without LLM processing.
    Returns True if:
    1. Only one data source (SQL)
    2. No API data
    3. Simple tabular data structure
    """
    try:
        # Check the results structure - should only have SQL data
        data_sources = []
        sql_data = None
        
        # Count different data sources
        if results.get('1_sql'):
            data_sources.append('sql')
            sql_data = results['1_sql']
        
        # Check for API data sources (numbered API results)
        for i in range(1, 10):  # Check up to 10 potential API steps
            if results.get(f'{i}_api'):
                data_sources.append('api')
                break
        
        # Should only have SQL data, no API data
        if len(data_sources) != 1 or 'sql' not in data_sources:
            return False
        
        # Check if SQL data is simple tabular structure  
        if not isinstance(sql_data, list) or not sql_data:
            return False
            return False
            
        # Check if all records have the same structure (simple table)
        first_row = sql_data[0]
        if not isinstance(first_row, dict):
            return False
            
        # All rows should have the same keys (consistent table structure)
        first_keys = set(first_row.keys())
        for row in sql_data[:5]:  # Check first 5 rows for consistency
            if set(row.keys()) != first_keys:
                return False
        
        # Check original plan if available - should be simple single step
        if original_plan:
            try:
                if isinstance(original_plan, str):
                    import json
                    plan_data = json.loads(original_plan) if original_plan.startswith('{') else {'steps': []}
                else:
                    plan_data = original_plan
                    
                steps = plan_data.get('steps', [])
                if len(steps) != 1:
                    return False
                    
                step = steps[0]
                if step.get('tool_name', '').lower() != 'sql':
                    return False
            except:
                # If plan parsing fails, still allow optimization based on data structure
                pass
        
        return True
        
    except Exception as e:
        # If detection fails, fall back to normal LLM processing
        return False

def _format_single_sql_directly(results: Dict[str, Any], flow_id: str, total_records: int) -> Dict[str, Any]:
    """
    Format single SQL query results directly using legacy ai_service.py pattern.
    Creates Vuetify table structure without LLM processing.
    """
    try:
        sql_data = results.get('1_sql', [])
        
        if not sql_data:
            return {
                'display_type': 'markdown',
                'content': {'text': 'Query executed successfully but returned no results.'},
                'metadata': {
                    'total_records': 0,
                    'query_type': 'sql',
                    'single_sql_optimization': True,
                    'bypassed_llm_processing': True,
                    'execution_summary': 'No data returned from SQL query',
                    'confidence_level': 'High',
                    'data_sources': ['sql'],
                    'processing_time': 'Instant (bypassed LLM)',
                    'limitations': 'None'
                },
                'usage_info': {'tokens': 0, 'model': 'direct_formatting'}
            }
        
        # Create Vuetify headers from first row keys (same as legacy ai_service.py)
        first_row = sql_data[0]
        headers = [{
            "text": key.replace('_', ' ').title(),
            "value": key,
            "align": 'start'
        } for key in first_row.keys()]
        
        logger.info(f"[{flow_id}] Direct SQL formatting: {len(sql_data)} records with {len(headers)} columns")
        logger.info(f"[{flow_id}] Bypassed LLM processing - using legacy ai_service.py pattern")
        
        # Return the SAME structure as complex queries (display_type: "table", not "vuetify_table")
        return {
            'display_type': 'table',  # Match complex queries - NOT 'vuetify_table'
            'content': sql_data,  # Will be chunked by realtime_hybrid.py if needed
            'metadata': {
                'total_records': len(sql_data),
                'query_type': 'sql',
                'single_sql_optimization': True,
                'bypassed_llm_processing': True,
                'execution_summary': f'Retrieved {len(sql_data)} records from database query',
                'confidence_level': 'High',
                'data_sources': ['sql'],
                'processing_time': 'Instant (bypassed LLM)',
                'limitations': 'None - direct database results',
                'column_count': len(headers),
                'columns': [h['value'] for h in headers]
            },
            'processing_code': None  # CRITICAL FIX: Set to None instead of string to avoid execution
        }
        
    except Exception as e:
        logger.error(f"[{flow_id}] Direct SQL formatting failed: {e}")
        # Fall back to normal processing if direct formatting fails
        raise e

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
    
    # SINGLE SQL OPTIMIZATION: Check if this is a simple single SQL query
    # BUT skip the optimization if user explicitly requests grouping/aggregation
    if _is_single_sql_query(results, original_plan) and not _requires_aggregation(query):
        logger.info(f"[{flow_id}] SINGLE SQL OPTIMIZATION: Detected single SQL query - using direct formatting")
        return _format_single_sql_directly(results, flow_id, total_records)
    elif _is_single_sql_query(results, original_plan):
        logger.info(f"[{flow_id}] SINGLE SQL OPTIMIZATION: Detected single SQL query but user requested grouping/aggregation - using LLM formatting")
    
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
        # Determine processing approach based on estimated token count only (LLM context-aware)
        estimated_tokens = _estimate_token_count(results)
        token_threshold = 1000  # Conservative threshold to stay within LLM context limits
        
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
    
    # Extract step schemas from metadata if available
    step_schemas = sampled_results.get('metadata', {}).get('step_schemas', {})
    if step_schemas:
        logger.debug(f"[{flow_id}] Schema information available for {len(step_schemas)} steps")
    
    prompt = _create_sample_data_prompt(query, sampled_results, original_plan, total_records, step_schemas)
    
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
            raw_response = str(result.output) if hasattr(result, 'output') else str(result)
            
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