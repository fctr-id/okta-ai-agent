"""
Results Formatter Agent V2 - Unified Sampling Strategy
API Schema + Limited Samples for all response sizes

Enhanced architecture following the proven results_formatter_agent.py pattern:
- Unified sampling strategy for all dataset sizes
- API Schema + Limited Samples approach
- Code generation for processing complete datasets using pure Python
- Robust JSON parsing with fallbacks
- Centralized logging with correlation ID support

Model Configuration:
- Complete Data Formatter: Uses REASONING model for data understanding and formatting
- Sample Data Formatter: Uses CODING model for Python JSON code generation
"""

import asyncio
import json
import logging
import time
import re
import sys
import os
import subprocess
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelRetry, UnexpectedModelBehavior, UsageLimitExceeded

# Add Polars for enhanced sampling - required dependency
import polars as pl

# Add src path for importing utils
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from src.utils.logging import get_logger, generate_correlation_id, set_correlation_id, get_default_log_dir
from src.utils.security_config import get_allowed_methods_for_prompt

# Setup centralized logging with file output  
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

# Agent Configuration - Dual Agent Approach
def _load_complete_data_prompt():
    """Load system prompt for complete data processing and presentation"""
    allowed_methods = get_allowed_methods_for_prompt()
    try:
        # Look for the same prompt file as original
        prompt_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'documentation', 'complete_data_prompt.md')
        if os.path.exists(prompt_path):
            with open(prompt_path, 'r', encoding='utf-8') as f:
                prompt_template = f.read()
            # Replace placeholder with actual allowed methods
            return prompt_template.format(allowed_methods=allowed_methods)
        logger.debug("Loaded complete data prompt with dynamic allowed methods for pure Python processing")
    except Exception as e:
        logger.warning(f"Complete data prompt file not found: {e}, using fallback")
    
    # Fallback inline prompt - allowed_methods is available here
    return f"""You are an expert data formatter. Process the provided complete dataset and return a properly formatted JSON response.

{allowed_methods}

Return a JSON object with:
- display_type: "table" or "markdown"
- content: formatted data
- metadata: additional information including headers for tables

Ensure all data is included without truncation."""

def _load_sample_data_prompt():
    """Load system prompt for sample data processing and code generation with dynamic allowed methods"""
    allowed_methods = get_allowed_methods_for_prompt()
    try:
        # Look for the same prompt file as original  
        prompt_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'documentation', 'sample_data_prompt.md')
        if os.path.exists(prompt_path):
            with open(prompt_path, 'r', encoding='utf-8') as f:
                prompt_template = f.read()
            # Replace placeholder with actual allowed methods
            return prompt_template.format(allowed_methods=allowed_methods)
        logger.debug("Loaded sample data prompt with dynamic allowed methods for pure Python processing")
    except Exception as e:
        logger.warning(f"Sample data prompt file not found: {e}, using fallback")
    
    # V2 Unified Polars-Enhanced fallback prompt
    return f"""
# Results Processing Task - UNIFIED POLARS ENHANCEMENT V2

## Your Task
You will receive data in a unified Polars-enhanced format for BOTH API and SQL data sources:
1. **Complete schemas** - Full field schemas with type information extracted via Polars
2. **Rich statistics** - Column stats, null counts, unique values, sample values for all data types
3. **Consistent sampling** - 2 examples for API steps, 5 examples for SQL steps
4. **Unified metadata** - Consistent structure regardless of API vs SQL source

Write Python code WITHOUT function definitions that processes the complete dataset.

Your code will be executed with the FULL dataset (available as variable 'full_results') 
to transform it into a user-friendly format.

IMPORTANT: Place your code between <CODE> and </CODE> tags.

## Unified Polars-Enhanced Data Structure

### API Steps (e.g., "1_api", "3_api"):
```json
{{
  "data_type": "api_response_polars",
  "step_type": "api",
  "total_records": 139,
  "schema": {{
    "actor.id": "String",
    "actor.type": "String", 
    "eventType": "String",
    "outcome.result": "String"
  }},
  "column_stats": {{
    "actor.type": {{"type": "string", "unique_values": 3, "null_count": 0, "sample_values": ["User", "Admin", "Service"]}},
    "outcome.result": {{"type": "string", "unique_values": 2, "null_count": 0, "sample_values": ["SUCCESS", "FAILURE"]}}
  }},
  "examples": [
    // 2 real records for pattern learning
  ],
  "polars_enhanced": true
}}
```

### SQL Steps (e.g., "2_sql", "4_api_sql"):
```json
{{
  "data_type": "sql_response_polars",
  "step_type": "sql",
  "total_records": 89,
  "schema": {{
    "user_id": "String",
    "email": "String",
    "app_name": "String",
    "status": "String"
  }},
  "column_stats": {{
    "status": {{"type": "string", "unique_values": 3, "null_count": 2, "sample_values": ["ACTIVE", "INACTIVE", "PENDING"]}},
    "email": {{"type": "string", "unique_values": 89, "null_count": 0}}
  }},
  "examples": [
    // 5 records for tabular data understanding
  ],
  "polars_enhanced": true
}}
```

## Code Generation Guidelines

### Understanding Enhanced API Data Structure:
- **Schema**: Complete Polars-detected field types (String, Int64, Float64, Boolean, etc.)
- **Column Stats**: Data quality insights (null counts, unique values, min/max for numerics)
- **Examples**: Learn patterns, data types, and relationships from real examples
- **Processing**: Your code will access the FULL dataset with all records

### Example Processing Pattern with Enhanced Metadata:
```python
# For API steps - access full data, use enhanced schema knowledge
api_data = full_results.get('1_api', [])  # This contains ALL records, not samples!

# Use schema and stats to make intelligent decisions
# Schema shows "actor.type" has only 3 unique values - good for grouping
# Stats show "actor.alternateId" has 12 nulls out of 139 - handle nulls
for record in api_data:
    # Schema shows field types for safe processing
    user_id = record.get('actor', {{}}).get('id', '')  # String type
    
    # Use stats knowledge - outcome.result has only 2 unique values
    success = record.get('outcome', {{}}).get('result') == 'SUCCESS'
    
    # Handle nulls intelligently based on column_stats
    user_email = record.get('actor', {{}}).get('alternateId')  # Might be null (12/139 are null)
    if user_email is None:
        user_email = 'Unknown'
```

## Security Restrictions & Requirements
- DO NOT USE 'import' statements - modules like json are already available
- DO NOT define any functions - no 'def' statements allowed
- DO NOT use eval(), exec() or similar unsafe functions
- NEVER use Python sets - use lists instead
- ALL data structures must be JSON serializable
- Your result MUST include 'display_type' and proper structure

## Allowed Methods
{allowed_methods}

## Critical Instructions
- NEVER limit the number of items in results
- DO NOT use slice operations like items[:200] 
- Return ALL items regardless of dataset size
- ALWAYS start by debugging the data structure
- Extract entity names dynamically, never hardcode
- Use enhanced schema and stats knowledge for intelligent data handling
- Handle null values based on column_stats information

IMPORTANT: Place your code ONLY between <CODE> and </CODE> tags.
"""

# Create PydanticAI agents
complete_data_formatter = Agent(reasoning_model, system_prompt=_load_complete_data_prompt())
sample_data_formatter = Agent(coding_model, system_prompt=_load_sample_data_prompt())

def _count_total_records(results: Dict[str, Any]) -> int:
    """Count total records across all steps"""
    total = 0
    
    for key, value in results.items():
        if isinstance(value, list):
            total += len(value)
    
    return total

def _clean_api_data_for_polars(step_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Clean API data by removing _links metadata before Polars processing - keep all other data intact"""
    cleaned_data = []
    for record in step_data:
        if isinstance(record, dict):
            cleaned_record = {}
            for key, value in record.items():
                # Only remove _links metadata - keep everything else for rich Polars analysis
                if key == '_links':
                    continue  # Skip _links entirely
                else:
                    cleaned_record[key] = value  # Keep all other data as-is
            cleaned_data.append(cleaned_record)
        else:
            cleaned_data.append(record)
    return cleaned_data

def _extract_polars_data_and_schema(step_data: List[Dict[str, Any]], step_type: str, step_key: str) -> Dict[str, Any]:
    """Unified Polars-based data extraction and schema analysis for both API and SQL steps"""
    
    try:
        # Clean API data by removing _links metadata before Polars processing
        if 'api' in step_type:
            cleaned_data = _clean_api_data_for_polars(step_data)
            print(f"[STATS] {step_key}: Cleaned API data - removed _links metadata only")
        else:
            # SQL data typically doesn't need cleaning
            cleaned_data = step_data
        
        # Convert to Polars DataFrame for unified processing
        df = pl.from_dicts(cleaned_data)
        
        # Extract complete schema with type information (works for both API and SQL)
        schema_info = {}
        for col_name, dtype in df.schema.items():
            schema_info[col_name] = str(dtype)
        
        # Get statistical summary for better LLM context (unified for all data types)
        column_stats = {}
        for col in df.columns:
            if df[col].dtype in [pl.Utf8, pl.String]:
                # String columns: unique count and null information
                unique_count = df[col].n_unique()
                column_stats[col] = {
                    "type": "string",
                    "unique_values": unique_count,
                    "null_count": df[col].null_count(),
                    "sample_values": df[col].drop_nulls().unique().head(3).to_list()  # Show sample values
                }
            elif df[col].dtype in [pl.Int64, pl.Int32, pl.Float64, pl.Float32]:
                # Numeric columns: basic stats
                column_stats[col] = {
                    "type": "numeric", 
                    "null_count": df[col].null_count(),
                    "min": df[col].min(),
                    "max": df[col].max(),
                    "unique_values": df[col].n_unique()
                }
            elif df[col].dtype == pl.Boolean:
                # Boolean columns: unique values and distribution
                column_stats[col] = {
                    "type": "boolean",
                    "null_count": df[col].null_count(),
                    "true_count": df[col].sum(),
                    "false_count": df.height - df[col].sum() - df[col].null_count()
                }
            else:
                # Other data types: basic info
                column_stats[col] = {
                    "type": str(df[col].dtype), 
                    "null_count": df[col].null_count(),
                    "unique_values": df[col].n_unique()
                }
        
        # Determine sample size based on step type and data size
        # CRITICAL FIX: Check for SQL data type first, since api_sql contains both 'api' and 'sql'
        if 'sql' in step_type:
            # SQL steps (including api_sql): 5 samples for tabular data (more samples needed)
            sample_size = 5
            data_type = "sql_response_polars"
        elif 'api' in step_type:
            # Pure API steps: 2 examples for pattern learning (schema is the main value)
            sample_size = 2
            data_type = "api_response_polars"
        else:
            # Fallback for unknown step types: treat as SQL
            sample_size = 5
            data_type = "sql_response_polars"
        
        # Handle large datasets efficiently
        if df.height > 1000:
            # Large datasets: random sampling
            examples = df.sample(n=min(sample_size, df.height)).to_dicts()
            sampling_method = "random_sampling"
        else:
            # Small datasets: head sampling
            examples = df.head(sample_size).to_dicts()
            sampling_method = "head_sampling"
        
        result = {
            "data_type": data_type,
            "step_type": step_type,
            "total_records": df.height,
            "schema": schema_info,
            "column_stats": column_stats,
            "examples": examples,
            "sampling_method": sampling_method,
            "polars_enhanced": True
        }
        
        print(f"[STATS] {step_key}: Unified Polars processing - {len(schema_info)} fields, {len(examples)} examples, {df.height} total records ({sampling_method})")
        return result
        
    except Exception as e:
        # Fallback to simple approach if Polars processing fails
        logger.warning(f"Unified Polars processing failed for {step_key}: {e}, using simple fallback")
        
        # Simple fallback that works for both API and SQL
        # CRITICAL FIX: Check for SQL data type first, since api_sql contains both 'api' and 'sql'
        if 'sql' in step_type:
            sample_size = 5
        elif 'api' in step_type:
            sample_size = 2
        else:
            sample_size = 5  # Default to SQL-like sampling
        return {
            "data_type": f"{step_type}_response_fallback",
            "step_type": step_type,
            "total_records": len(step_data),
            "schema": _extract_all_field_paths(step_data) if 'api' in step_type else {},
            "examples": step_data[:sample_size],
            "polars_enhanced": False,
            "fallback_reason": str(e)
        }

def _create_unified_samples(results: Dict[str, Any], total_records: int) -> Dict[str, Any]:
    """V2 Unified sampling using single Polars-based extraction for all step types"""
    
    step_keys = [key for key in results.keys() if key.split('_')[0].isdigit()]
    processed_results = {}
    
    print(f"[STATS] V2 Unified Polars Sampling: Processing {len(step_keys)} steps for {total_records} total records")
    
    for step_key in step_keys:
        step_data = results[step_key]
        
        if isinstance(step_data, list) and len(step_data) > 0:
            # Determine step type from the key pattern: {number}_{type}
            step_parts = step_key.split('_', 1)  # Split on first underscore only
            if len(step_parts) > 1:
                step_type = step_parts[1]  # Everything after the number
                
                # UNIFIED APPROACH: Use single function for both API and SQL
                processed_results[step_key] = _extract_polars_data_and_schema(step_data, step_type, step_key)
                
            else:
                # Fallback for unexpected key format
                processed_results[step_key] = step_data[:5]
                print(f"[STATS] {step_key}: Fallback sampling (unexpected key format)")
        else:
            # Non-list data, copy as-is
            processed_results[step_key] = step_data
            print(f"[STATS] {step_key}: copied non-list data as-is")
    
    # Count total processed samples
    total_processed = 0
    for data in processed_results.values():
        if isinstance(data, dict) and 'examples' in data:
            total_processed += len(data['examples'])
        elif isinstance(data, list):
            total_processed += len(data)
    
    print(f"[STATS] V2 Unified Polars Final result: {total_processed} sample records total")
    
    return processed_results

def _extract_all_field_paths(data: list) -> dict:
    """Extract all possible field paths from API data"""
    paths = {}
    
    # Check first 10 records to find all possible fields
    sample_size = min(10, len(data))
    for record in data[:sample_size]:
        _collect_field_paths(record, paths, "")
    
    return paths

def _collect_field_paths(obj: any, paths: dict, prefix: str):
    """Recursively collect all field paths with type information"""
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else key
            
            if value is None:
                paths[path] = "null_or_unknown"
            elif isinstance(value, dict):
                paths[path] = "object"
                _collect_field_paths(value, paths, path)
            elif isinstance(value, list):
                paths[path] = "array"
                if value and isinstance(value[0], dict):
                    # For arrays of objects, show structure of first element
                    _collect_field_paths(value[0], paths, f"{path}[0]")
                elif value:
                    # For arrays of primitives, show type
                    paths[f"{path}[0]"] = type(value[0]).__name__
            else:
                paths[path] = type(value).__name__

def _is_single_sql_query(results: Dict[str, Any], original_plan: Optional[str] = None) -> bool:
    """Check if this is a single SQL query that can be formatted directly without LLM processing"""
    try:
        # Check the results structure - should only have SQL data
        data_sources = []
        sql_data = None
        
        # Find SQL and API data sources dynamically
        for key, value in results.items():
            if key.split('_')[0].isdigit():  # Step key pattern: {number}_{type}
                step_parts = key.split('_', 1)
                if len(step_parts) > 1:
                    step_type = step_parts[1]
                    if step_type == 'sql':  # Pure SQL step
                        data_sources.append('sql')
                        sql_data = value
                    elif 'api' in step_type:  # Any API-containing step
                        data_sources.append('api')
        
        # Should only have SQL data, no API data
        if len(data_sources) != 1 or 'sql' not in data_sources:
            return False
        
        # Check if SQL data is simple tabular structure  
        if not isinstance(sql_data, list) or not sql_data:
            return False
            
        # Check if all records have the same structure (simple table)
        first_row = sql_data[0]
        if not isinstance(first_row, dict):
            return False
            
        # All rows should have the same keys (consistent table structure)
        first_keys = set(first_row.keys())
        for row in sql_data[1:5]:  # Check first few rows
            if not isinstance(row, dict) or set(row.keys()) != first_keys:
                return False
        
        return True
        
    except Exception:
        return False

def _requires_aggregation(query: str) -> bool:
    """Check if the user's query explicitly requests grouping, aggregation, or summarization"""
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

def _format_single_sql_directly(results: Dict[str, Any], flow_id: str, total_records: int) -> Dict[str, Any]:
    """Direct formatting for single SQL queries without LLM processing"""
    try:
        # Find the SQL data dynamically
        sql_data = None
        for key, value in results.items():
            if key.split('_')[0].isdigit():  # Step key pattern: {number}_{type}
                step_parts = key.split('_', 1)
                if len(step_parts) > 1 and step_parts[1] == 'sql':  # Pure SQL step
                    sql_data = value
                    break
        
        if not sql_data or not isinstance(sql_data, list):
            raise ValueError("No valid SQL data found")
        
        # Generate headers from the first record
        first_record = sql_data[0]
        if not isinstance(first_record, dict):
            raise ValueError("SQL data is not in expected dictionary format")
        
        # Create headers with proper formatting
        headers = []
        for key in first_record.keys():
            # Convert snake_case to Title Case for display
            display_name = key.replace('_', ' ').title()
            headers.append({
                'text': display_name,
                'value': key,
                'sortable': True,
                'align': 'start'
            })
        
        logger.info(f"[{flow_id}] SINGLE SQL OPTIMIZATION: Bypassed LLM processing for {len(sql_data)} records")
        
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
                'columns': [h['value'] for h in headers],
                'headers': headers
            },
            'processing_code': None  # CRITICAL FIX: Set to None instead of string to avoid execution
        }
        
    except Exception as e:
        logger.error(f"[{flow_id}] Direct SQL formatting failed: {e}")
        # Fall back to normal processing if direct formatting fails
        raise e

async def format_results_v2(query: str, results: Dict[str, Any], is_sample: bool = False, 
                           original_plan: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """V2 Enhanced results formatting with unified sampling strategy"""
    
    # Count total records to inform the LLM about dataset size
    total_records = _count_total_records(results)
    flow_id = metadata.get("flow_id", "unknown") if metadata else "unknown"
    
    logger.info(f"[{flow_id}] Results Formatter V2 Starting")
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
    
    # Determine processing approach based on dataset size and sample flag
    if is_sample or total_records > 50:  # Use sample processing for large datasets
        logger.info(f"[{flow_id}] Processing samples for large dataset (estimated {_estimate_token_count(results)} tokens, {total_records} records)")
        return await _process_sample_data_v2(query, results, total_records, original_plan, flow_id)
    else:
        logger.info(f"[{flow_id}] Processing complete small dataset ({total_records} records)")
        return await _process_complete_data_v2(query, results, total_records, original_plan, flow_id)

def _estimate_token_count(results: Dict[str, Any]) -> int:
    """Estimate token count for results data"""
    results_str = json.dumps(results, default=str)
    # Rough estimate: 4 characters per token
    return len(results_str) // 4

async def _process_complete_data_v2(query: str, results: Dict[str, Any], total_records: int, 
                                   original_plan: Optional[str], flow_id: str) -> Dict[str, Any]:
    """Process complete data for small datasets using REASONING model"""
    
    prompt = _create_complete_data_prompt_v2(query, results, original_plan, total_records)
    
    logger.debug(f"[{flow_id}] Complete data prompt length: {len(prompt)} chars")
    
    try:
        result = await complete_data_formatter.run(prompt)
        raw_response = str(result.output) if hasattr(result, 'output') else str(result)
        
        # Parse the JSON response
        formatted_result = _parse_raw_llm_response(raw_response, flow_id)
        
        logger.info(f"[{flow_id}] Complete data processing successful")
        return formatted_result
        
    except Exception as e:
        logger.error(f"[{flow_id}] Complete data processing failed: {e}")
        return _create_fallback_response(str(e), total_records, 'complete')

async def _process_sample_data_v2(query: str, results: Dict[str, Any], total_records: int,
                                 original_plan: Optional[str], flow_id: str) -> Dict[str, Any]:
    """Process sample data for large datasets using CODING model with V2 unified sampling"""
    
    # Apply V2 unified sampling strategy
    sampled_results = _create_unified_samples(results, total_records)
    
    # Create prompt with new unified format
    prompt = _create_sample_data_prompt_v2(query, sampled_results, original_plan, total_records)
    
    logger.debug(f"[{flow_id}] V2 Sample data prompt length: {len(prompt)} chars")
    logger.debug(f"[{flow_id}] V2 Sample prompt content preview: {prompt[:500]}...")
    
    try:
        logger.info(f"[{flow_id}] Processing V2 samples and generating code with specialized PydanticAI agent...")
        
        result = await sample_data_formatter.run(prompt)
        raw_response = str(result.output) if hasattr(result, 'output') else str(result)
        
        # Parse the raw response manually
        formatted_result = _parse_raw_llm_response(raw_response, flow_id)
        
        logger.debug(f"[{flow_id}] V2 Sample Data Final Result Keys: {list(formatted_result.keys())}")
        
        # Execute the generated code if present
        if 'processing_code' in formatted_result and formatted_result['processing_code']:
            logger.info(f"[{flow_id}] V2 Results Formatter generated processing code - executing with security validation")
            executed_result = await _execute_processing_code_v2(formatted_result['processing_code'], results, flow_id)
            
            if executed_result:
                # Update the formatted result with actual processed data
                formatted_result['content'] = executed_result
                logger.info(f"[{flow_id}] V2 Processing code execution successful - updating formatted response with actual data")
        
        return formatted_result
        
    except Exception as e:
        logger.error(f"[{flow_id}] V2 Sample data processing failed: {e}")
        return _create_fallback_response(str(e), total_records, 'sample')

def _create_complete_data_prompt_v2(query: str, results: Dict[str, Any], original_plan: Optional[str], 
                                   total_records: int) -> str:
    """Create prompt for processing complete data with V2 format awareness"""
    
    plan_reasoning = original_plan if original_plan else "No plan provided"
    results_str = json.dumps(results, default=str)
    
    # Truncate very large results to prevent token overflow
    if len(results_str) > 15000:
        results_str = results_str[:15000] + "... [truncated for size]"
    
    return f"""Query: {query}
Dataset Size: {total_records} total records (COMPLETE DATASET)
Plan Context: {plan_reasoning}
Complete Results: {results_str}

You are processing the COMPLETE dataset. Create a comprehensive, user-friendly response that directly answers the user's query.
Focus on clear presentation and include performance recommendations in your metadata if this is a large dataset."""

def _create_sample_data_prompt_v2(query: str, sampled_results: Dict[str, Any], original_plan: Optional[str], 
                                 total_records: int) -> str:
    """Create prompt for processing V2 unified sample data and generating code"""
    
    plan_reasoning = original_plan if original_plan else "No plan provided"
    results_str = json.dumps(sampled_results, default=str)
    
    # CRITICAL: Aggressively truncate to ensure we stay under token limits
    max_results_chars = 20000  # Conservative limit for sample data
    if len(results_str) > max_results_chars:
        results_str = results_str[:max_results_chars] + "... [V2 sample data truncated to fit context]"
        print(f"[STATS] V2 Sample prompt truncated from {len(json.dumps(sampled_results, default=str))} to {max_results_chars} chars")
    
    # Also truncate plan if very long
    if len(plan_reasoning) > 3000:
        plan_reasoning = plan_reasoning[:3000] + "... [plan truncated]"
    
    return f"""Query: {query}
Dataset Size: {total_records} total records (V2 UNIFIED SCHEMA + SAMPLES APPROACH)
Plan Context: {plan_reasoning}
V2 Sample Data: {results_str}

IMPORTANT: You are seeing V2 UNIFIED SAMPLES from a large dataset of {total_records} records.

This new V2 format provides:
1. Complete API schemas with ALL possible field paths
2. Real examples (2 per API step) for pattern learning  
3. SQL samples (up to 5 per step) as before

Your tasks:
1. Use schema knowledge to understand ALL available fields
2. Learn patterns from the real examples provided
3. Create processing code that handles the full dataset efficiently
4. Use pure Python JSON processing for reliable data transformation
5. Focus on user-centric aggregation to reduce output complexity

Include performance optimizations and processing recommendations in your metadata."""

def _parse_raw_llm_response(response: str, flow_id: str) -> Dict[str, Any]:
    """Parse raw LLM response into structured format"""
    
    logger.debug(f"[{flow_id}] Parsing raw response: {response[:500]}...")
    
    # Try to extract and parse JSON
    try:
        # Look for JSON content between CODE tags first
        code_match = re.search(r'<CODE>(.*?)</CODE>', response, re.DOTALL)
        if code_match:
            # This is code, not JSON - return it as processing code
            code_content = code_match.group(1).strip()
            return {
                'display_type': 'table',
                'content': [],
                'metadata': {'processing_mode': 'code_generation'},
                'processing_code': code_content
            }
        
        # Try to extract JSON from markdown code blocks
        json_match = re.search(r'```(?:json)?\s*\n(.*?)\n\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            # Look for JSON object directly
            json_obj_match = re.search(r'(\{.*\})', response, re.DOTALL)
            if json_obj_match:
                json_str = json_obj_match.group(1).strip()
            else:
                json_str = response.strip()
        
        # Parse the JSON
        parsed = json.loads(json_str)
        logger.debug(f"[{flow_id}] Successfully parsed JSON response")
        return parsed
        
    except json.JSONDecodeError as e:
        logger.warning(f"[{flow_id}] JSON parsing failed: {e}, treating as markdown")
        return {
            'display_type': 'markdown',
            'content': response,
            'metadata': {'parsing_fallback': 'raw_text'}
        }

async def _execute_processing_code_v2(code: str, full_results: Dict[str, Any], flow_id: str) -> Optional[List[Dict[str, Any]]]:
    """Execute generated processing code with security validation"""
    
    # Security validation
    if not _validate_code_security(code, flow_id):
        logger.error(f"[{flow_id}] V2 Code security validation failed")
        return None
    
    try:
        # Create execution environment
        exec_globals = {
            'full_results': full_results,
            'json': json,
            'len': len,
            'isinstance': isinstance,
            'dict': dict,
            'list': list,
            'str': str,
            'int': int,
            'float': float,
            'bool': bool,
            'print': print,
            'range': range,
            'enumerate': enumerate
        }
        
        # Execute the code
        exec(code, exec_globals)
        
        # Get the result
        if 'result' in exec_globals:
            result_data = exec_globals['result']
            if isinstance(result_data, dict) and 'content' in result_data:
                logger.info(f"[{flow_id}] V2 Code execution successful")
                return result_data['content']
        
        logger.warning(f"[{flow_id}] V2 Code execution completed but no result found")
        return None
        
    except Exception as e:
        logger.error(f"[{flow_id}] V2 Code execution failed: {e}")
        return None

def _validate_code_security(code: str, flow_id: str) -> bool:
    """Validate that generated code is safe to execute"""
    
    # Forbidden patterns
    forbidden_patterns = [
        'import', 'exec', 'eval', 'open', 'file', '__import__',
        'globals', 'locals', 'vars', 'dir', 'getattr', 'setattr',
        'subprocess', 'os.', 'sys.', 'builtins'
    ]
    
    code_lower = code.lower()
    for pattern in forbidden_patterns:
        if pattern in code_lower:
            logger.error(f"[{flow_id}] Code security violation: forbidden pattern '{pattern}'")
            return False
    
    logger.info(f"[{flow_id}] Code security validation passed")
    return True

def _create_fallback_response(error_msg: str, total_records: int, processing_mode: str) -> Dict[str, Any]:
    """Create fallback response for errors"""
    return {
        'display_type': 'markdown',
        'content': f'**Processing Error**: {error_msg}',
        'metadata': {
            'execution_summary': f'V2 {processing_mode} data processing failed: {error_msg}',
            'confidence_level': 'Low',
            'total_records_processed': total_records,
            'processing_mode': f'v2_{processing_mode}'
        },
        'usage_info': {'error': f'V2 {processing_mode} data processing failed'}
    }

# Backward compatibility function
async def process_results_structured_v2(
    query: str,
    results: Dict[str, Any], 
    original_plan: Optional[str] = None,
    is_sample: bool = False,
    metadata: Optional[Dict[str, Any]] = None,
    model_name: str = "openai:gpt-4o"
) -> Dict[str, Any]:
    """V2 Backward compatibility - enhanced with unified sampling"""
    return await format_results_v2(query, results, is_sample, original_plan, metadata)

# Example usage for testing
if __name__ == "__main__":
    # Test the V2 unified sampling approach
    sample_results = {
        "1_api": [
            {"actor": {"id": "user1", "type": "User"}, "eventType": "auth", "outcome": {"result": "SUCCESS"}},
            {"actor": {"id": "user2", "type": "User"}, "eventType": "login", "outcome": {"result": "FAILURE"}},
            # ... 137 more records would be here in real scenario
        ] * 70,  # Simulate 140 records
        "2_sql": [
            {"user_id": "user1", "app_name": "App1", "status": "ACTIVE"},
            {"user_id": "user2", "app_name": "App2", "status": "INACTIVE"}
        ]
    }
    
    processed = _create_unified_samples(sample_results, 142)
    
    print("V2 Unified Sampling Output:")
    print(json.dumps(processed, indent=2, default=str)[:1000] + "...")

# Export the V2 function as the main format_results for compatibility
format_results = format_results_v2