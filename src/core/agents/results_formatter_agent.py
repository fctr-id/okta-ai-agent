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

# Import template system for sample data processing
from src.core.agents.results_template_agent import generate_results_template, execute_results_template

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
    """Load system prompt for sample data processing using template system"""
    try:
        # NEW: Use template-based prompt for sample data processing
        prompt_file = os.path.join(os.path.dirname(__file__), "prompts", "results_formatter_sample_data_template_prompt.txt")
        with open(prompt_file, 'r', encoding='utf-8') as f:
            prompt_content = f.read()
        
        logger.debug("Loaded sample data template prompt - will use template system for large datasets")
        return prompt_content
        
    except FileNotFoundError:
        logger.warning("Sample data template prompt file not found, using fallback")
        return """You are a Results Template Agent that analyzes data structures and selects the most appropriate formatting template for large datasets that need to be presented in tabular format.

## CORE MISSION
Your job is to analyze the structure of SAMPLE DATA from large query results and generate a ResultsTemplate configuration that will properly format the complete dataset for display.

## AVAILABLE TEMPLATE PATTERNS
1. SIMPLE_TABLE - Single dataset with direct field mapping
2. USER_LOOKUP - Join user IDs with user profile data (most common)  
3. AGGREGATION - Group records by entity and aggregate list fields
4. HIERARCHY - Nested parent-child relationships
5. LIST_CONSOLIDATION - Merge multiple list fields

Remember to respond with a valid ResultsTemplate JSON object."""

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
    
    print(f"[STATS] Creating samples: {sample_size} records from {total_records} total")
    
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
                print(f"   [STATS] SQL data: {len(sampled_sql.get('data', []))} samples from {len(sql_exec.get('data', []))} records")
            
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
                    print(f"   [STATS] {step.get('step_type', 'Unknown')} step: {len(sampled_step.get('data', []))} samples from {len(step.get('data', []))} records")
                
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
4. Use pure Python JSON processing for reliable and compatible data transformation
5. Focus on user-centric aggregation to reduce output complexity

Include performance optimizations and processing recommendations in your metadata."""

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
    """
    Main function for the Results Formatter Agent.
    - For large datasets, uses a template-based system for robust processing.
    - For small datasets, uses a direct LLM call for formatting.
    """
    flow_id = metadata.get('correlation_id') if metadata else generate_correlation_id()
    set_correlation_id(flow_id)
    
    logger.info(f"Results Formatter Agent Starting")
    
    total_records = _count_total_records(results)
    logger.info(f"Processing {total_records} total records (is_sample: {is_sample})")
    
    # Simplified logic: Always use the template system for consistency and reliability.
    # This avoids generating Python code for the final step, which was causing the ModuleNotFoundError.
    
    logger.debug(f"Query: {query}")
    logger.debug(f"Original Plan: {original_plan}")

    # 1. Create intelligent samples to determine data structure for the template agent.
    sampled_results = _create_intelligent_samples(results, total_records)
    logger.info(f"Using template system for dataset processing ({total_records} total records)")

    # 2. Generate the template configuration based on the sample data structure.
    logger.info("Template System: Starting template generation")
    template_config = await generate_results_template(
        query=query,
        data_structure=sampled_results,
        original_plan=original_plan,
        correlation_id=flow_id
    )
    logger.info(f"Template generated: {template_config.template_name}")
    logger.debug(f"Template config: {len(template_config.field_mappings)} field mappings")

    # 3. Execute the generated template on the FULL dataset.
    # This is the core of the fix: direct execution instead of code generation.
    logger.info("Template System: Executing template on full dataset")
    formatted_results = execute_results_template(template_config, results)
    logger.info("Template System: Formatting complete")

    # The formatted_results from the executor is the final content.
    # We just need to wrap it in the standard response structure.
    return {
        "display_type": template_config.display_type,
        "content": formatted_results,
        "metadata": {
            "headers": template_config.headers,
            "total_records": len(formatted_results),
            "data_source": "template_executor"
        },
        "processing_code": None  # No code generated, so this is None
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
    """Process sample data using template system for large dataset formatting"""
    
    # Debug logging for samples received
    logger.debug(f"[{flow_id}] Sample Data Processing - Samples received:")
    if 'raw_results' in sampled_results and 'sql_execution' in sampled_results['raw_results']:
        sql_data = sampled_results['raw_results']['sql_execution'].get('data', [])
        logger.debug(f"[{flow_id}] SQL Sample Data: {len(sql_data)} records")
        if sql_data:
            # Log complete first 2 records for debugging (not truncated fields)
            logger.debug(f"[{flow_id}] Complete first 2 SQL sample records: {sql_data[:2]}")
    
    logger.info(f"[{flow_id}] Using template system for large dataset processing ({total_records} total records)")
    
    try:
        # NEW: Use template system for sample data processing
        logger.info(f"[{flow_id}] Template System: Starting template-based formatting for large dataset")
        
        # Convert sampled data structure to format expected by template system
        # Template system expects step_results format like: {'1_sql': [...], '2_api': [...]}
        template_data_structure = {}
        
        # Extract step data from sampled_results format
        if 'raw_results' in sampled_results:
            raw_data = sampled_results['raw_results']
            step_counter = 1
            
            # Handle SQL data
            if 'sql_execution' in raw_data and raw_data['sql_execution'].get('data'):
                template_data_structure[f'{step_counter}_sql'] = raw_data['sql_execution']['data']
                step_counter += 1
            
            # Handle API data
            if 'api_execution' in raw_data and raw_data['api_execution'].get('data'):
                template_data_structure[f'{step_counter}_api'] = raw_data['api_execution']['data']
                step_counter += 1
            
            # Handle step results if present
            if 'step_results' in raw_data:
                for i, step in enumerate(raw_data['step_results'], 1):
                    if step.get('data'):
                        step_type = step.get('step_type', 'unknown')
                        template_data_structure[f'{i}_{step_type}'] = step['data']
        
        # If no proper structure found, try direct sampled_results
        if not template_data_structure:
            # Look for direct step data in sampled_results
            for key, value in sampled_results.items():
                if isinstance(value, list) and value:
                    template_data_structure[key] = value
        
        logger.debug(f"[{flow_id}] Template data structure keys: {list(template_data_structure.keys())}")
        
        # Generate template configuration using sample data
        template_config = await generate_results_template(
            query=query,
            data_structure=template_data_structure,
            original_plan=original_plan,
            correlation_id=flow_id
        )
        
        logger.info(f"[{flow_id}] Template generated: {template_config.template_name}")
        logger.debug(f"[{flow_id}] Template config: {len(template_config.field_mappings)} field mappings")
        
        # NOTE: For sample processing, we should return the template configuration as processing_code
        # This allows the execution manager to apply the template to the full dataset
        
        # Convert template config to Python dict format (not JSON) to avoid true/false vs True/False issues
        import pprint
        template_dict = template_config.model_dump()
        template_dict_str = pprint.pformat(template_dict, indent=2, width=120)
        
        template_code = f"""
# Template-based processing for large dataset
import json

# Template configuration
template_config = {template_dict_str}

# Execute template on full dataset
from src.core.agents.results_template_agent import execute_results_template_from_dict
result = execute_results_template_from_dict(template_config, full_results)
print(json.dumps(result))
"""
        
        # Return template-based response with processing code
        formatted_response = {
            'display_type': 'table',
            'content': 'Template-based processing configured for large dataset',
            'metadata': {
                'template_system_used': True,
                'template_name': template_config.template_name,
                'total_records': total_records,
                'processing_mode': 'sample_with_template',
                'execution_summary': f'Generated {template_config.template_name} template for {total_records} records',
                'confidence_level': 'High',
                'data_sources': list(template_data_structure.keys()),
                'field_mappings': len(template_config.field_mappings)
            },
            'processing_code': template_code.strip()
        }
        
        logger.info(f"[{flow_id}] Template-based sample processing completed")
        return formatted_response
        
    except Exception as e:
        logger.error(f"[{flow_id}] Template-based sample processing failed: {e}")
        # Fallback to traditional LLM processing
        logger.warning(f"[{flow_id}] Falling back to traditional LLM sample processing")
        
        prompt = _create_sample_data_prompt(query, sampled_results, original_plan, total_records)
        
        try:
            result = await sample_data_formatter.run(prompt)
            raw_response = str(result.data) if hasattr(result, 'data') else str(result)
            formatted_result = _parse_raw_llm_response(raw_response, flow_id)
            
            # Add fallback metadata
            if 'metadata' not in formatted_result:
                formatted_result['metadata'] = {}
            formatted_result['metadata']['template_system_used'] = False
            formatted_result['metadata']['fallback_reason'] = str(e)
            
            return formatted_result
            
        except Exception as fallback_error:
            logger.error(f"[{flow_id}] Fallback sample processing also failed: {fallback_error}")
            return {
                'display_type': 'markdown',
                'content': {'text': f'**Processing Error**: Both template and LLM processing failed'},
                'metadata': {
                    'execution_summary': f'All sample processing methods failed',
                    'confidence_level': 'Low',
                    'total_records_processed': total_records,
                    'processing_mode': 'sample_failed',
                    'template_error': str(e),
                    'llm_error': str(fallback_error)
                },
                'usage_info': {'error': 'All processing methods failed'}
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
