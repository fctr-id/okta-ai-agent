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
        
        # Data inspection
        'describe', 'null_count', 'dtypes', 'columns', 'shape', 'width', 'height',
        'is_empty', 'estimated_size',
        
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
        
        # System operations
        'pipe', 'map', 'apply', 'fold', 'reduce',
        
        # Memory intensive operations
        'explode', 'melt', 'pivot', 'unpivot',
        
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
        Get a summary of safe Polars operations by category
        
        Returns:
            Dictionary with categorized safe operations
        """
        return {
            'data_access': [
                'head', 'tail', 'limit', 'sample', 'slice', 'select', 'drop'
            ],
            'filtering': [
                'filter', 'where', 'drop_nulls', 'drop_duplicates', 'unique'
            ],
            'aggregation': [
                'group_by', 'agg', 'count', 'sum', 'mean', 'median', 'min', 'max'
            ],
            'sorting': [
                'sort', 'sort_by', 'reverse'
            ],
            'formatting': [
                'to_dict', 'to_pandas', 'write_json', 'write_csv'
            ],
            'inspection': [
                'describe', 'dtypes', 'columns', 'shape', 'null_count'
            ]
        }

# Create a global Polars security validator instance
polars_validator = PolarsSecurityValidator()

def validate_polars_operation(operation: str, 
                             context: Optional[Dict[str, Any]] = None) -> PolarsSecurityResult:
    """
    Convenience function to validate Polars operation
    
    Args:
        operation: Polars operation to validate
        context: Additional context
        
    Returns:
        PolarsSecurityResult with validation details
    """
    return polars_validator.validate_polars_operation(operation, context)

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
