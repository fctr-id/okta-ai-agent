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
import warnings
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import ModelRetry, UnexpectedModelBehavior, UsageLimitExceeded

# Suppress Gemini additionalProperties warnings - these are harmless and tools work correctly
warnings.filterwarnings("ignore", message=".*additionalProperties.*not supported by Gemini.*", category=UserWarning)

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
        
        logger.debug("Loaded sample data prompt with tool-first workflow")
        return prompt_content
        
    except FileNotFoundError:
        logger.error("Sample data prompt file not found - this is required")
        raise FileNotFoundError("results_formatter_sample_data_prompt.txt not found")

# Create Results Formatter Agent with PydanticAI (single unified agent)
# Complete data formatter uses REASONING model for data understanding and formatting
complete_data_formatter = Agent(
    reasoning_model,
    system_prompt=_load_complete_data_prompt(),
    # No output_type - will return raw string which we can parse manually
    retries=0  # No retries to avoid wasting money on failed attempts
)

# Sample data formatter uses REASONING model for both relationship analysis AND code generation
# This allows us to use tools while still being capable of generating Python code
sample_data_formatter = Agent(
    coding_model,  # Back to coding_model - it was working fine
    system_prompt=_load_sample_data_prompt(),
    # No output_type - will return raw string which we can parse manually
    retries=0  # No retries to avoid wasting money on failed attempts
)

# Deterministic relationship analysis prompt with enhanced reflective thinking (same functionality as simple_pipeline.py)
DETERMINISTIC_ANALYSIS_PROMPT = """You are a data relationship analyzer for multi-step API execution results with enhanced reflective thinking capabilities.

## CRITICAL OUTPUT REQUIREMENT: RAW JSON ONLY

**YOUR OUTPUT WILL BE PARSED BY json.loads() - ANY NON-JSON CONTENT WILL CRASH THE SYSTEM.**

**ABSOLUTE PROHIBITIONS:**
- **ZERO COMMENTS**: The characters `//` anywhere in your response will crash the system
- **ZERO MARKDOWN**: No ```json blocks - raw JSON only  
- **ZERO EXPLANATIONS**: Only the JSON object, nothing else
- **NO TEXT**: Nothing before `{` or after `}` will crash the parser

**YOUR FIRST CHARACTER MUST BE `{` AND YOUR LAST CHARACTER MUST BE `}`**

## MANDATORY TOOL-BASED ANALYSIS PROCESS

**REQUIRED WORKFLOW:**
You MUST use the `analyze_sample_data_structure` tool before generating any JSON output.

**STEP-BY-STEP REQUIREMENT:**
1. **CALL THE TOOL**: First call `analyze_sample_data_structure` tool with the sample data
2. **USE TOOL RESULTS**: Use the tool's comprehensive analysis to understand data structure and relationships
3. **GENERATE OUTPUT**: Use the tool's findings to create accurate JSON output with proper field mappings

## TOOL-PROVIDED ANALYSIS

The `analyze_sample_data_structure` tool will provide you with:

### 1. CROSS-STEP JOINS
Exact join relationships between steps:
"step_X_to_step_Y": {
    "left_key": "exact_field_name",
    "right_key": "exact_field_name", 
    "join_type": "one-to-one|one-to-many|many-to-many",
    "reliability": "high|medium|low"
}

### 2. PRIMARY ENTITY
Main business entity (user, group, application, device, event, organization)

### 3. AGGREGATION RULES  
How to group data for each step:
"step_X_aggregation": {
    "group_by_field": "exact_field_name",
    "aggregate_fields": ["field1", "field2"],
    "method": "distinct_list|count|first|last|concat"
}

### 4. FIELD MAPPINGS  
Mapping from source fields to output names:
"stepX.source_field": "output_field_name"

### 5. PROCESSING TEMPLATE
Recommended processing approach (ENTITY_AGGREGATION, CROSS_REFERENCE, etc.)

## CRITICAL SUCCESS FACTORS WITH REFLECTIVE THINKING
1. **EXAMINE ACTUAL SAMPLE DATA** - Look at provided samples to find real field names
2. **ANALYZE NESTED STRUCTURES** - Don't just say "data", examine what's inside complex fields  
3. **IDENTIFY DISPLAY FIELDS** - For user-facing data, find appropriate display field (label, name, title)
4. **BE SPECIFIC WITH FIELD PATHS** - Use precise field references for nested data extraction
5. **THINK STEP-BY-STEP** - Reflect on relationship quality before finalizing the analysis
6. **VALIDATE COMPLETENESS** - Ensure your analysis will capture all data the user requested (groups, roles, applications)

Return JSON with this EXACT structure (NO MARKDOWN, NO COMMENTS):
{
    "cross_step_joins": {},
    "primary_entity": "user",
    "aggregation_rules": {},
    "field_mappings": {},
    "processing_template": "ENTITY_AGGREGATION - Description"
}

Use exact field names from sample data, not assumptions."""

# Create dedicated relationship analysis agent 
relationship_analysis_agent = Agent(
    coding_model,
    system_prompt=DETERMINISTIC_ANALYSIS_PROMPT,
    retries=0
)

# Data Structure Analysis Tool (exactly like simple_pipeline.py)
@sample_data_formatter.tool
async def analyze_sample_data_structure(ctx: RunContext[Dict[str, Any]], sample_data: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze sample data structure using the proven deterministic relationship analysis prompt"""
    
    # Prepare analysis data (first 2 records per step for structure analysis)
    analysis_data = {}
    for step_key, step_data in sample_data.items():
        if isinstance(step_data, list) and step_data:
            sample_records = step_data[:2] if len(step_data) > 2 else step_data
            analysis_data[step_key] = {
                "record_count": len(step_data),
                "sample_records": sample_records
            }
    
    prompt = f"Analyze this sample data:\n{json.dumps(analysis_data, indent=2, default=str)[:4000]}"
    
    try:
        # Run relationship analysis using dedicated agent
        result = await relationship_analysis_agent.run(prompt, deps=ctx.deps, usage=ctx.usage)
        raw_response = str(result.output) if hasattr(result, 'output') else str(result)
        
        # ALWAYS LOG RAW OUTPUT FOR DEBUGGING
        logger.info(f"RAW LLM OUTPUT FOR RELATIONSHIP ANALYSIS:")
        logger.info(f"Raw response length: {len(raw_response)}")
        logger.info(f"Raw response: {raw_response}")
        
        # Parse JSON response with better error handling
        json_str = raw_response.strip()
        
        # Handle markdown blocks if present
        if '```json' in json_str:
            start = json_str.find('```json') + 7
            end = json_str.find('```', start)
            if end != -1:
                json_str = json_str[start:end].strip()
            else:
                json_str = json_str[start:].strip()
        
        # Ensure it starts and ends with braces
        if not json_str.startswith('{'):
            # Find the first { and last }
            start_idx = json_str.find('{')
            end_idx = json_str.rfind('}')
            if start_idx != -1 and end_idx != -1:
                json_str = json_str[start_idx:end_idx+1]
            else:
                raise ValueError("No valid JSON structure found")
        
        analysis_result = json.loads(json_str)
        
        # DEBUG LOGGING: Log the complete relationship analysis output
        logger.debug(f"RELATIONSHIP ANALYSIS TOOL OUTPUT:")
        logger.debug(f"   Cross-step joins: {analysis_result.get('cross_step_joins', {})}")
        logger.debug(f"   Primary entity: {analysis_result.get('primary_entity', 'unknown')}")
        logger.debug(f"   Aggregation rules: {analysis_result.get('aggregation_rules', {})}")
        logger.debug(f"   Field mappings: {analysis_result.get('field_mappings', {})}")
        logger.debug(f"   Processing template: {analysis_result.get('processing_template', 'unknown')}")
        logger.debug(f"COMPLETE RELATIONSHIP ANALYSIS:\n{json.dumps(analysis_result, indent=2)}")
        
        return analysis_result
        
    except Exception as e:
        logger.error(f"Tool analyze_sample_data_structure failed: {e}")
        logger.error(f"Raw response was: {raw_response[:500]}...")
        
        # Return a basic fallback analysis
        fallback_result = {
            "cross_step_joins": {},
            "primary_entity": "user", 
            "aggregation_rules": {},
            "field_mappings": {},
            "processing_template": "ENTITY_AGGREGATION - Basic fallback analysis due to tool error"
        }
        
        logger.debug(f"FALLBACK RELATIONSHIP ANALYSIS: {fallback_result}")
        return fallback_result

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
    """Simplify individual records using simple_sampler.py approach for token efficiency"""
    if not isinstance(record, dict):
        return record
    
    optimized = {}
    for key, value in record.items():
        # Truncate long strings to save tokens in sample analysis
        if isinstance(value, str) and len(value) > 150:
            optimized[key] = value[:150] + "..."
        elif isinstance(value, list) and len(value) > 3:
            # Truncate arrays to 3 items but keep structure visible
            optimized[key] = value[:3] + ["...more items"]
        elif isinstance(value, dict) and len(str(value)) > 200:
            # Simplify large nested objects
            optimized[key] = "[large_object_simplified]"
        else:
            optimized[key] = value
    
    return optimized

def _create_intelligent_samples(results: Dict[str, Any], total_records: int, max_records_per_step: int = 5) -> Dict[str, Any]:
    """Create minimal samples using simple_sampler.py approach - entity-agnostic for ANY data relationships
    
    Approach: Take up to N random records per step, truncate arrays within records to 2-3 items
    Final results formatter will never truncate - this is only for sample analysis
    """
    import random
    
    # Detect step keys (format: "1_api", "2_sql", "3_api", etc.)
    step_keys = [key for key in results.keys() if key.split('_')[0].isdigit()]
    
    if not step_keys:
        print(f"[STATS] No step keys found in results: {list(results.keys())}")
        return results  # Return as-is if no step structure detected
    
    print(f"[STATS] Creating simple samples: max {max_records_per_step} random per step across {len(step_keys)} steps")
    print(f"[STATS] Detected step keys: {step_keys}")
    
    samples = {}
    
    for step_key in step_keys:
        step_data = results[step_key]
        
        if not isinstance(step_data, list) or not step_data:
            samples[step_key] = step_data
            continue
            
        # Take random sample (up to N records for structure analysis)
        if len(step_data) <= max_records_per_step:
            # Use all records if step has few records
            sample_records = step_data
        else:
            # Random sampling from this step
            sample_records = random.sample(step_data, max_records_per_step)
        
        # Optimize records for tokens - truncate arrays to 2-3 items, long strings to reasonable length
        optimized_records = []
        for record in sample_records:
            optimized_record = _simplify_sample_record(record)
            optimized_records.append(optimized_record)
        
        samples[step_key] = optimized_records
        print(f"   [STATS] {step_key}: sampled {len(optimized_records)} records from {len(step_data)} total")
    
    # Copy any non-step keys as-is
    for key, value in results.items():
        if key not in step_keys:
            samples[key] = value

    return samples

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

def _create_sample_data_prompt(query: str, sampled_results: Dict[str, Any], total_records: int) -> str:
    """Create simplified prompt for sample data processing - tool-first approach"""
    
    results_str = json.dumps(sampled_results, default=str)
    
    # Aggressively truncate to ensure we stay under token limits
    max_results_chars = 20000
    if len(results_str) > max_results_chars:
        results_str = results_str[:max_results_chars] + "... [sample data truncated to fit context]"
    
    available_keys = list(sampled_results.keys())
    
    # Minimal prompt - just query and samples (tool does the rest)
    return (
        f"User Query: {query}\n"
        f"Dataset Size: {total_records} total records (SAMPLES ONLY SHOWN)\n"
        f"Available Result Keys: {available_keys}\n"
        "Sample Data (for analysis): " + results_str + "\n\n"
        "WORKFLOW:\n"
        "1. ANALYZE DIRECTLY: Examine sample data structure without tool calls\n"
        "2. THEN: Use relationship analysis to generate Python code for full dataset\n"
        "3. Code must use full_results.get('<key>', []) with exact keys from Available Result Keys\n"
        "Return JSON per system prompt format.\n"
    )

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
        # Re-raise so caller can decide fallback path
        raise

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
                         original_plan: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Enhanced results formatting with conditional processing based on dataset size"""
    
    
    # Count total records to inform the LLM about dataset size
    total_records = _count_total_records(results)
    flow_id = metadata.get("flow_id", "unknown") if metadata else "unknown"
    
    logger.info(f"[{flow_id}] Results Formatter Agent Starting")
    logger.info(f"[{flow_id}] Processing {total_records} total records (is_sample: {is_sample})")
    logger.debug(f"[{flow_id}] Query: {query}")
    
    # DUMP FULL RESULTS DATA FOR RELATIONSHIP ANALYSIS
    _dump_full_results_data(query, results, flow_id, original_plan, metadata)
    
    # Condense plan before logging / injection to reduce token footprint
    condensed_plan = _condense_plan(original_plan)
    logger.debug(f"[{flow_id}] Original Plan (condensed for prompt): {condensed_plan}")
    
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
            return await _process_complete_data(query, results, condensed_plan, flow_id, total_records)
        else:
            # Large dataset - use sampling for efficiency and to avoid token limits
            logger.info(f"[{flow_id}] Processing samples for large dataset (estimated {estimated_tokens} tokens, {total_records} records)")
            sampled_results = _create_intelligent_samples(results, total_records)
            return await _process_sample_data(query, sampled_results, flow_id, total_records)
            
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

async def _process_sample_data(query: str, sampled_results: Dict[str, Any], flow_id: str, total_records: int) -> Dict[str, Any]:
    """Process sample data and generate code for full dataset processing"""
    
    prompt = _create_sample_data_prompt(query, sampled_results, total_records)
    
    logger.debug(f"[{flow_id}] Sample Data Prompt (length: {len(prompt)} chars)")
    logger.debug(f"[{flow_id}] Available data keys: {list(sampled_results.keys())}")
    
    try:
        # Run formatter
        result = await sample_data_formatter.run(prompt)
        raw_response = str(result.output) if hasattr(result, 'output') else str(result)
        formatted_result = _parse_raw_llm_response(raw_response, flow_id)

        logger.debug(f"[{flow_id}] Sample Data Final Result Keys: {list(formatted_result.keys())}")

        # Log the generated processing code for debugging
        if formatted_result.get('processing_code'):
            logger.debug(f"[{flow_id}] Final Processing Code Generated: {formatted_result['processing_code'][:500]}...")

        return formatted_result
        
    except Exception as e:
        logger.error(f"[{flow_id}] Sample data processing failed: {e}")
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