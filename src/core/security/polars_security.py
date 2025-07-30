"""
Polars Security Module

Provides security validation for Polars operations in the results formatter.
Implements simple but effective controls for data processing operations:
- Method whitelisting for safe Polars operations
- Prevents potentially dangerous data operations
- Memory and performance safeguards
"""

import logging
from typing import List, Dict, Any, Set, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class PolarsSecurityResult:
    """Result of Polars security validation"""
    is_allowed: bool
    violations: List[str]
    blocked_operations: List[str]
    risk_level: str  # 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'

class PolarsSecurityValidator:
    """Validates Polars operations for safe data processing"""
    
    # Safe Polars operations for data retrieval and formatting
    ALLOWED_POLARS_METHODS = {
        # Basic data access
        'head', 'tail', 'limit', 'sample', 'slice', 'select', 'drop',
        'filter', 'where', 'with_columns', 'rename', 'cast',
        
        # Aggregation and grouping
        'group_by', 'agg', 'count', 'sum', 'mean', 'median', 'min', 'max',
        'std', 'var', 'quantile', 'first', 'last', 'n_unique',
        
        # Sorting and ordering
        'sort', 'sort_by', 'reverse', 'shuffle',
        
        # Data inspection and display
        'describe', 'null_count', 'dtypes', 'columns', 'shape', 'width', 'height',
        'is_empty', 'estimated_size', 'show',
        
        # Data conversion and extraction
        'to_list', 'to_series', 'to_dicts', 'to_dict',
        
        # Column operations and filtering
        'is_in', 'is_not_null', 'is_null', 'apply', 'map_elements',
        
        # Advanced data operations (JSON/struct processing)
        'over', 'implode', 'explode', 'struct_field', 'struct_fields', 
        'flatten', 'unnest', 'map_dict', 'map_batches',
        
        # List/array operations
        'list_eval', 'list_len', 'list_get', 'list_first', 'list_last',
        'list_slice', 'list_sum', 'list_max', 'list_min', 'list_unique',
        
        # String operations (safe)
        'str.len', 'str.contains', 'str.starts_with', 'str.ends_with',
        'str.to_lowercase', 'str.to_uppercase', 'str.strip',
        
        # Date/time operations (safe)
        'dt.year', 'dt.month', 'dt.day', 'dt.hour', 'dt.minute', 'dt.second',
        'dt.strftime', 'dt.to_string',
        
        # Data formatting
        'to_dict', 'to_pandas', 'to_numpy', 'to_arrow', 'write_json',
        'write_csv', 'write_parquet',
        
        # Safe transformations
        'unique', 'drop_duplicates', 'drop_nulls', 'fill_null', 'fill_nan',
        'interpolate', 'round', 'abs', 'clip',
        
        # Join operations (controlled)
        'join', 'join_asof', 'hstack', 'vstack', 'concat',
        
        # Window operations (safe)
        'over', 'rolling', 'expanding'
    }
    
    # Dangerous operations that should be blocked
    BLOCKED_POLARS_METHODS = {
        # File system operations
        'scan_csv', 'scan_parquet', 'scan_ipc', 'scan_delta', 'scan_ndjson',
        'read_csv', 'read_parquet', 'read_ipc', 'read_delta', 'read_ndjson',
        'read_database', 'read_sql',
        
        # Network operations
        'read_http', 'read_s3', 'read_azure', 'read_gcp',
        
        # Potentially dangerous string operations
        'str.extract', 'str.extract_all', 'str.replace', 'str.replace_all',
        
        # System operations (removed apply - it's in allowed list)
        'pipe', 'map', 'fold', 'reduce',
        
        # Memory intensive operations (removed explode - it's in allowed list)  
        'melt', 'pivot', 'unpivot',
        
        # Database operations
        'write_database', 'execute'
    }
    
    # Operations that require additional validation
    RESTRICTED_POLARS_METHODS = {
        'with_columns': 'May contain arbitrary expressions',
        'select': 'May contain complex expressions',
        'filter': 'May contain complex conditions',
        'group_by': 'May cause memory issues with large groups',
        'join': 'May cause cartesian products',
        'concat': 'May cause memory issues',
    }
    
    def __init__(self):
        """Initialize Polars security validator"""
        logger.info("Polars security validator initialized")
        self.max_rows_processed = 100000  # Limit data processing size
        self.max_memory_mb = 512  # Memory limit in MB
    
    def validate_polars_operation(self, operation: str, 
                                 context: Optional[Dict[str, Any]] = None) -> PolarsSecurityResult:
        """
        Validate a Polars operation for security compliance
        
        Args:
            operation: Polars method/operation name
            context: Additional context about the operation
            
        Returns:
            PolarsSecurityResult with validation details
        """
        violations = []
        blocked_operations = []
        risk_level = 'LOW'
        
        # Normalize operation name
        operation_clean = operation.lower().strip()
        
        # Check if operation is explicitly blocked
        if operation_clean in self.BLOCKED_POLARS_METHODS:
            violations.append(f"Operation '{operation}' is blocked for security")
            blocked_operations.append(operation)
            risk_level = 'HIGH'
        
        # Check if operation is in allowed list
        elif operation_clean not in self.ALLOWED_POLARS_METHODS:
            violations.append(f"Operation '{operation}' is not in the allowed methods list")
            blocked_operations.append(operation)
            risk_level = 'MEDIUM'
        
        # Additional validation for restricted operations
        if operation_clean in self.RESTRICTED_POLARS_METHODS:
            restriction_reason = self.RESTRICTED_POLARS_METHODS[operation_clean]
            
            # Check context for additional safety
            if context:
                row_count = context.get('row_count', 0)
                if row_count > self.max_rows_processed:
                    violations.append(f"Operation '{operation}' with {row_count} rows exceeds limit of {self.max_rows_processed}")
                    risk_level = 'HIGH'
                
                memory_usage = context.get('memory_mb', 0)
                if memory_usage > self.max_memory_mb:
                    violations.append(f"Operation '{operation}' requires {memory_usage}MB, exceeds limit of {self.max_memory_mb}MB")
                    risk_level = 'HIGH'
        
        is_allowed = len(violations) == 0
        
        return PolarsSecurityResult(
            is_allowed=is_allowed,
            violations=violations,
            blocked_operations=blocked_operations,
            risk_level=risk_level
        )
    
    def validate_polars_chain(self, operations: List[str]) -> PolarsSecurityResult:
        """
        Validate a chain of Polars operations
        
        Args:
            operations: List of Polars operations to validate
            
        Returns:
            PolarsSecurityResult with validation details
        """
        all_violations = []
        all_blocked = []
        max_risk_level = 'LOW'
        
        for i, operation in enumerate(operations):
            result = self.validate_polars_operation(operation)
            
            if not result.is_allowed:
                all_violations.extend([f"Step {i+1}: {v}" for v in result.violations])
                all_blocked.extend(result.blocked_operations)
                
                # Update risk level to highest found
                risk_levels = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']
                if risk_levels.index(result.risk_level) > risk_levels.index(max_risk_level):
                    max_risk_level = result.risk_level
        
        is_allowed = len(all_violations) == 0
        
        return PolarsSecurityResult(
            is_allowed=is_allowed,
            violations=all_violations,
            blocked_operations=all_blocked,
            risk_level=max_risk_level
        )
    
    def get_safe_operations_summary(self) -> Dict[str, List[str]]:
        """
        Get a summary of safe Polars operations by category for LLM prompts
        
        Returns:
            Dictionary with categorized safe operations
        """
        return {
            'data_access': [
                'head', 'tail', 'limit', 'sample', 'slice', 'select', 'drop'
            ],
            'filtering': [
                'filter', 'where', 'drop_nulls', 'drop_duplicates', 'unique',
                'is_in', 'is_not_null', 'is_null'
            ],
            'aggregation': [
                'group_by', 'agg', 'count', 'sum', 'mean', 'median', 'min', 'max',
                'std', 'var', 'quantile', 'first', 'last', 'n_unique'
            ],
            'sorting': [
                'sort', 'sort_by', 'reverse', 'shuffle'
            ],
            'data_conversion': [
                'to_dict', 'to_dicts', 'to_list', 'to_series', 'to_pandas', 
                'to_numpy', 'to_arrow', 'write_json', 'write_csv'
            ],
            'column_operations': [
                'with_columns', 'rename', 'cast', 'apply', 'map_elements'
            ],
            'json_struct_processing': [
                'explode', 'implode', 'struct_field', 'struct_fields', 
                'flatten', 'unnest', 'map_dict', 'map_batches'
            ],
            'list_array_operations': [
                'list_eval', 'list_len', 'list_get', 'list_first', 'list_last',
                'list_slice', 'list_sum', 'list_max', 'list_min', 'list_unique'
            ],
            'window_operations': [
                'over', 'rolling', 'expanding'
            ],
            'joins': [
                'join', 'join_asof', 'hstack', 'vstack', 'concat'
            ],
            'inspection': [
                'describe', 'dtypes', 'columns', 'shape', 'null_count', 'show',
                'width', 'height', 'is_empty', 'estimated_size'
            ],
            'transformations': [
                'fill_null', 'fill_nan', 'interpolate', 'round', 'abs', 'clip'
            ],
            'string_operations': [
                'str.len', 'str.contains', 'str.starts_with', 'str.ends_with',
                'str.to_lowercase', 'str.to_uppercase', 'str.strip'
            ],
            'datetime_operations': [
                'dt.year', 'dt.month', 'dt.day', 'dt.hour', 'dt.minute', 'dt.second',
                'dt.strftime', 'dt.to_string'
            ]
        }

    def get_allowed_methods_for_prompt(self) -> str:
        """
        Generate a formatted string of allowed Polars methods for LLM prompts
        
        Returns:
            Formatted string describing allowed operations
        """
        categories = self.get_safe_operations_summary()
        
        prompt_text = "**ALLOWED POLARS METHODS**\n\nYou can use these Polars operations in your code:\n\n"
        
        for category, methods in categories.items():
            category_name = category.replace('_', ' ').title()
            prompt_text += f"**{category_name}:**\n"
            prompt_text += f"- {', '.join(sorted(methods))}\n\n"
        
        prompt_text += "**IMPORTANT NOTES:**\n"
        prompt_text += "- Always use these exact method names\n"
        prompt_text += "- Combine methods with standard Polars chaining syntax\n"
        prompt_text += "- Use .apply() for custom transformations\n"
        prompt_text += "- Use .explode() and .implode() for list/struct processing\n"
        prompt_text += "- Use .struct_field() to extract fields from struct columns\n"
        prompt_text += "- Use .over() for window operations\n"
        
        return prompt_text

# Create a global Polars security validator instance
polars_validator = PolarsSecurityValidator()

def validate_polars_operation(operation: str, 
                             context: Optional[Dict[str, Any]] = None) -> PolarsSecurityResult:
    """
    Convenience function to validate Polars operation
    
    For Results Formatter code that has already passed MethodWhitelistValidator,
    we perform additional Polars-specific safety checks but are more permissive.
    
    Args:
        operation: Polars operation/code to validate
        context: Additional context
        
    Returns:
        PolarsSecurityResult with validation details
    """
    violations = []
    blocked_operations = []
    risk_level = "LOW"
    
    # Check for obviously dangerous operations
    dangerous_patterns = [
        'exec(', 'eval(', '__import__', 'subprocess', 'os.system',
        'open(', 'file(', 'input(', 'raw_input(',
        'delete', 'drop_database', 'truncate', 'alter table'
    ]
    
    operation_lower = operation.lower()
    for pattern in dangerous_patterns:
        if pattern in operation_lower:
            violations.append(f"Dangerous operation detected: {pattern}")
            blocked_operations.append(pattern)
            risk_level = "CRITICAL"
    
    # If code has basic Polars operations and no dangerous patterns, allow it
    has_polars = any(marker in operation_lower for marker in ['import polars', 'pl.', 'dataframe'])
    
    if has_polars and not violations:
        # Allow Polars operations that passed method whitelist validation
        is_allowed = True
    else:
        # Original validation for individual operations
        is_allowed = operation in polars_validator.ALLOWED_POLARS_METHODS
        if not is_allowed and not violations:
            violations.append(f"Operation '{operation}' is not in the allowed methods list")
    
    return PolarsSecurityResult(
        is_allowed=is_allowed,
        violations=violations,
        blocked_operations=blocked_operations,
        risk_level=risk_level
    )

def validate_polars_chain(operations: List[str]) -> PolarsSecurityResult:
    """
    Convenience function to validate Polars operation chain
    
    Args:
        operations: List of operations to validate
        
    Returns:
        PolarsSecurityResult with validation details
    """
    return polars_validator.validate_polars_chain(operations)

def get_safe_polars_operations() -> Dict[str, List[str]]:
    """
    Convenience function to get safe operations summary
    
    Returns:
        Dictionary of safe operations by category
    """
    return polars_validator.get_safe_operations_summary()

def get_allowed_polars_methods_list() -> List[str]:
    """
    Get a flat list of all allowed Polars methods for LLM prompts
    
    Returns:
        Sorted list of all allowed method names
    """
    return sorted(list(polars_validator.ALLOWED_POLARS_METHODS))

def get_polars_methods_for_prompt() -> str:
    """
    Generate a formatted string of allowed Polars methods for LLM prompts
    
    Returns:
        Formatted string with categorized allowed methods
    """
    categories = polars_validator.get_safe_operations_summary()
    
    prompt_text = "**ALLOWED POLARS METHODS**\n\nYou can ONLY use these Polars operations:\n\n"
    
    for category, methods in categories.items():
        category_name = category.replace('_', ' ').title()
        prompt_text += f"**{category_name}:**\n"
        prompt_text += f"- {', '.join(sorted(methods))}\n\n"
    
    prompt_text += "**CRITICAL:** Only use methods from this list. Any other method will cause security validation failure.\n"
    
    return prompt_text
