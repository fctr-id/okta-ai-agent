"""
Sampling Utilities for Modern Execution Manager

Functions for intelligent data sampling and token estimation
to determine processing strategy for large datasets.
"""

import json
import random
from typing import Dict, Any

def estimate_token_count(data: Any) -> int:
    """
    Estimate token count for LLM processing.
    Rough estimation: 1 token ≈ 4 characters for English text
    """
    try:
        data_str = json.dumps(data, ensure_ascii=False, default=str)
        # Rough token estimation: 1 token ≈ 4 characters
        estimated_tokens = len(data_str) // 4
        return estimated_tokens
    except:
        # Fallback to string length estimation
        data_str = str(data)
        return len(data_str) // 4

def count_total_records(results: Dict[str, Any]) -> int:
    """Count total records across all data sources"""
    total = 0
    
    # Handle direct step data structure from Modern Execution Manager
    for step_name, step_data in results.items():
        if isinstance(step_data, list):
            total += len(step_data)
    
    return total

def simplify_sample_record(record: Any) -> Any:
    """Simplify individual records for token efficiency"""
    if not isinstance(record, dict):
        return record
    
    optimized = {}
    for key, value in record.items():
        # Handle comma-separated grouped fields by detecting pattern
        if isinstance(value, str) and ',' in value:
            # Split and check if we have multiple items (likely a grouped field)
            items = [item.strip() for item in value.split(',')]
            # Only limit if we have more than 4 items and they look like entity names
            if len(items) > 4 and all(len(item.strip()) > 0 for item in items):
                limited_items = items[:3] + [f"... and {len(items) - 3} more"]
                optimized[key] = ", ".join(limited_items)
            else:
                optimized[key] = value
        # Truncate long strings to save tokens in sample analysis
        elif isinstance(value, str) and len(value) > 150:
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

def create_intelligent_samples(results: Dict[str, Any], max_records_per_step: int = 5) -> Dict[str, Any]:
    """
    Create minimal samples for relationship analysis.
    
    Args:
        results: Full dataset results
        max_records_per_step: Maximum records to sample per step
        
    Returns:
        Sampled data dictionary
    """
    
    # Detect step keys (format: "1_api", "2_sql", "3_api", etc.)
    step_keys = [key for key in results.keys() if key.split('_')[0].isdigit()]
    
    if not step_keys:
        return results  # Return as-is if no step structure detected
    
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
        
        # Optimize records for tokens
        optimized_records = []
        for record in sample_records:
            optimized_record = simplify_sample_record(record)
            optimized_records.append(optimized_record)
        
        samples[step_key] = optimized_records
    
    # Copy any non-step keys as-is
    for key, value in results.items():
        if key not in step_keys:
            samples[key] = value

    return samples
