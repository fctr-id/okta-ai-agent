"""
Relationship Analysis Agent - Standalone Data Structure Analyzer

This agent analyzes sample data to determine:
1. Cross-step joins and relationships
2. Primary business entities 
3. Aggregation rules for data processing
4. Field mappings for output formatting
5. Processing templates for code generation

Used by Modern Execution Manager before Results Formatter for large datasets.
"""

import json
import logging
import sys
import os
from typing import Dict, Any
from pydantic_ai import Agent

# Add src path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from src.utils.logging import get_logger, get_default_log_dir

# Setup centralized logging
logger = get_logger("okta_ai_agent", log_dir=get_default_log_dir())

# Use the model picker approach for consistent model configuration
try:
    from src.core.models.model_picker import ModelConfig, ModelType
    analysis_model = ModelConfig.get_model(ModelType.CODING)
except ImportError:
    # Fallback to simple model configuration
    analysis_model = os.getenv('LLM_MODEL', 'openai:gpt-4o')

# Import the proven deterministic prompt and validation from simple_pipeline components
def get_deterministic_prompt() -> str:
    """Load the proven deterministic prompt from file"""
    try:
        prompt_file = os.path.join(os.path.dirname(__file__), "prompts", "relationship_analysis_agent_prompt.txt")
        with open(prompt_file, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        logger.warning("Relationship analysis prompt file not found, using fallback")
        return """You are a data relationship analyzer for multi-step API execution results. 
        Analyze sample data and provide structured relationship mapping with cross_step_joins, 
        primary_entity, aggregation_rules, field_mappings, validation_results, and processing_template."""

def validate_deterministic_output(analysis_result: dict) -> dict:
    """Validate that the LLM output follows the deterministic structure"""
    validation_results = {
        "structure_valid": True,
        "missing_fields": [],
        "extra_fields": [], 
        "format_issues": []
    }
    
    required_fields = [
        "cross_step_joins", 
        "primary_entity",
        "aggregation_rules",
        "field_mappings", 
        "validation_results",
        "processing_template"
    ]
    
    # Check required fields
    for field in required_fields:
        if field not in analysis_result:
            validation_results["missing_fields"].append(field)
            validation_results["structure_valid"] = False
    
    # Check primary entity is from allowed list
    allowed_entities = ["user", "group", "application", "device", "event", "organization"]
    if "primary_entity" in analysis_result:
        if analysis_result["primary_entity"].lower() not in allowed_entities:
            validation_results["format_issues"].append(f"Invalid primary_entity: {analysis_result['primary_entity']}")
    
    return validation_results

def extract_json_from_response(response_text: str) -> dict:
    """Extract JSON from LLM response text, handling various formats"""
    import re
    
    # Try to find JSON in the response
    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
    if json_match:
        json_str = json_match.group()
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass
    
    # Fallback: try to parse the entire response as JSON
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        logger.error(f"Failed to extract JSON from response: {response_text[:200]}...")
        return {}

def create_minimal_samples(results: Dict[str, Any], max_records_per_step: int = 2) -> Dict[str, Any]:
    """
    Create minimal samples - enhanced logic from simple_sampler.py for token efficiency
    
    This function:
    1. Takes first N records per step for structure analysis
    2. Truncates long arrays and strings to save tokens
    3. Preserves data structure for relationship analysis
    4. Ensures model can focus on relationships, not overwhelming data volume
    """
    samples = {}
    
    for step_name, step_data in results.items():
        if not isinstance(step_data, list) or not step_data:
            logger.warning(f"Skipping step {step_name} - not a list or empty (type: {type(step_data)})")
            continue
            
        # Take minimal sample (first N records for structure analysis)
        sample_count = min(len(step_data), max_records_per_step)
        sample_records = step_data[:sample_count]
        
        # Optimize records for tokens - truncate arrays to 2-3 items, long strings to reasonable length
        optimized_records = []
        for record in sample_records:
            if isinstance(record, dict):
                optimized = {}
                for key, value in record.items():
                    # Truncate long strings to save tokens in sample analysis
                    if isinstance(value, str) and len(value) > 150:
                        optimized[key] = value[:150] + "..."
                    elif isinstance(value, list) and len(value) > 3:
                        # Truncate arrays to 2-3 items but keep structure visible
                        optimized[key] = value[:3] + ["...more items"]
                    elif isinstance(value, dict) and len(str(value)) > 200:
                        # For nested objects, keep essential fields only
                        if 'id' in value:
                            optimized[key] = {'id': value['id'], '...': 'truncated object'}
                        elif 'name' in value:
                            optimized[key] = {'name': value['name'], '...': 'truncated object'}
                        elif 'label' in value:
                            optimized[key] = {'label': value['label'], '...': 'truncated object'}
                        else:
                            optimized[key] = {'...': 'truncated object'}
                    else:
                        optimized[key] = value
                optimized_records.append(optimized)
            else:
                optimized_records.append(record)
        
        samples[step_name] = optimized_records
        logger.info(f"Step {step_name}: sampled {len(optimized_records)} records from {len(step_data)} total")
    
    logger.info(f"Created minimal samples for relationship analysis: {list(samples.keys())}")
    return samples

async def analyze_data_relationships(sample_data: Dict[str, Any], correlation_id: str = "unknown", query: str = "", execution_plan: Dict = None) -> Dict[str, Any]:
    """
    Analyze sample data using proven approach from simple_pipeline.py
    
    Args:
        sample_data: Dictionary with step keys and sample data
        correlation_id: Flow correlation ID for logging
        query: Original user query to understand intent and context
        execution_plan: Execution plan with step details for context
        
    Returns:
        Dictionary with relationship analysis results in deterministic format
        
    Raises:
        Exception: If analysis fails (no fallbacks per requirements)
    """
    logger.info(f"[{correlation_id}] Starting relationship analysis with PROVEN simple_pipeline approach")
    
    # DEBUG: Log what sample_data we received
    logger.info(f"[{correlation_id}] DEBUG: Received sample_data keys: {list(sample_data.keys())}")
    for key, value in sample_data.items():
        if isinstance(value, list):
            logger.info(f"[{correlation_id}] DEBUG: {key} has {len(value)} items")
        else:
            logger.info(f"[{correlation_id}] DEBUG: {key} has type {type(value)}")
    
    try:
        # Step 1: Pre-process sample data using proven minimal sampling approach
        processed_samples = create_minimal_samples(sample_data, max_records_per_step=2)
        logger.info(f"[{correlation_id}] Pre-processed samples: {list(processed_samples.keys())}")
        
        # Step 2: Build execution journey with context for each step
        execution_journey = {
            "user_query": query,
            "execution_steps": {}
        }
        
        # Add step context if execution plan is available
        if execution_plan and 'steps' in execution_plan:
            for i, step in enumerate(execution_plan['steps']):
                step_key = f"{i+1}_{'api' if step['tool_name'] == 'api' else step['tool_name']}"
                if step_key.endswith('_sql'):
                    step_key = f"{i+1}_api_sql"  # Match the actual step naming
                
                if step_key in processed_samples:
                    execution_journey["execution_steps"][step_key] = {
                        "step_purpose": step.get('query_context', step.get('reasoning', 'Data collection step')),
                        "step_output_sample": processed_samples[step_key]
                    }
        
        # Fallback: add steps without context if execution plan not available
        for step_key in processed_samples.keys():
            if step_key not in execution_journey["execution_steps"]:
                execution_journey["execution_steps"][step_key] = {
                    "step_purpose": f"Data collection for {step_key}",
                    "step_output_sample": processed_samples[step_key]
                }
        
        # Step 3: Use proven deterministic prompt and REASONING model (exactly like simple_pipeline.py)
        system_prompt = get_deterministic_prompt()
        
        relationship_analyzer = Agent(
            analysis_model,
            system_prompt=system_prompt,
            retries=0
        )
        
        # Step 4: Create analysis context with execution journey
        analysis_context = f"""User Query: {query}

Execution Journey - From User Intent to Data Collection:

{json.dumps(execution_journey, indent=2)}

Analyze the relationships between these execution steps and provide structured output for data joining and aggregation."""
        
        # Step 5: Run relationship analysis
        logger.info(f"[{correlation_id}] Executing relationship analysis ...")
        result = await relationship_analyzer.run(analysis_context)
        
        # Step 6: Extract and validate JSON using proven extraction logic
        logger.info(f"[{correlation_id}] 🔍 RAW RELATIONSHIP ANALYSIS OUTPUT:")
        logger.info(f"[{correlation_id}] {result.output}")
        logger.info(f"[{correlation_id}] 🔍 END RAW OUTPUT")
        
        relationships_json = extract_json_from_response(result.output)
        
        if not relationships_json:
            raise ValueError("Failed to extract valid JSON from relationship analysis response")
        
        logger.info(f"[{correlation_id}] 🔍 PARSED RELATIONSHIP ANALYSIS JSON:")
        logger.info(f"[{correlation_id}] {json.dumps(relationships_json, indent=2)}")
        logger.info(f"[{correlation_id}] 🔍 END PARSED JSON")
        
        # Step 7: Validate using proven validation logic
        validation = validate_deterministic_output(relationships_json)
        
        logger.info(f"[{correlation_id}] ✅ Relationship analysis complete!")
        logger.info(f"[{correlation_id}] 🎯 Primary Entity: {relationships_json.get('primary_entity', 'unknown')}")
        logger.info(f"[{correlation_id}] 🔗 Cross-Step Joins: {len(relationships_json.get('cross_step_joins', {}))}")
        logger.info(f"[{correlation_id}] 📊 Field Mappings: {len(relationships_json.get('field_mappings', {}))}")
        logger.info(f"[{correlation_id}] 📋 Aggregation Rules: {len(relationships_json.get('aggregation_rules', {}))}")
        
        if validation["structure_valid"]:
            logger.info(f"[{correlation_id}] ✅ Structure validation: PASSED")
        else:
            logger.warning(f"[{correlation_id}] ⚠️ Structure validation issues: {validation}")
        
        # Step 8: Add step_inventory for compatibility with existing interface
        if 'step_inventory' not in relationships_json:
            relationships_json['step_inventory'] = {
                'total_steps': len(processed_samples),
                'step_names': list(processed_samples.keys()),
                'step_record_counts': {step: len(data) for step, data in processed_samples.items()},
                'analysis_timestamp': correlation_id
            }
        
        # Step 9: Log successful analysis details for debugging
        cross_step_joins = relationships_json.get('cross_step_joins', {})
        aggregation_rules = relationships_json.get('aggregation_rules', {})
        logger.info(f"[{correlation_id}] Cross-step joins found: {list(cross_step_joins.keys())}")
        logger.info(f"[{correlation_id}] Aggregation rules found: {list(aggregation_rules.keys())}")
        
        return relationships_json
        
    except Exception as e:
        logger.error(f"[{correlation_id}] Relationship analysis failed with proven approach: {e}")
        logger.error(f"[{correlation_id}] Sample data keys: {list(sample_data.keys())}")
        logger.error(f"[{correlation_id}] This should work - same logic as simple_pipeline.py!")
        raise Exception(f"Relationship analysis failed: {e}")
