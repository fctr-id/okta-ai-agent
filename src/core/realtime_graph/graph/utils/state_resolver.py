from typing import Any, Dict, List, Optional
import logging
import re

class StateReferenceError(Exception):
    """Error raised when a state reference cannot be resolved."""
    pass

class StateReferenceResolver:
    """
    Resolves references to state values in parameter strings.
    
    Supports syntax like:
    - state.users_list (simple attribute access)
    - state.users[0] (array indexing)
    - state.user.profile (property access)
    - state.groups['group_name'] (dictionary key access)
    """
    
    # Maximum recursion depth to prevent security issues
    MAX_RECURSION_DEPTH = 10
    
    # Patterns for parsing state references
    ARRAY_INDEX_PATTERN = re.compile(r'\[(\d+)\]')
    DICT_KEY_PATTERN = re.compile(r"\[[\"\'](.+?)[\"\']\]")
    PROPERTY_ACCESS_PATTERN = re.compile(r'\.([a-zA-Z0-9_]+)')
    
    @classmethod
    def resolve_reference(
        cls,
        reference: str,
        state: Any,
        logger: Optional[logging.Logger] = None,
        query_id: str = "unknown"
    ) -> Any:
        """
        Resolve a state reference to its actual value.
        
        Args:
            reference: Reference string (e.g., "state.users_list", "state.users[0]")
            state: State object containing attributes
            logger: Optional logger instance
            query_id: Query identifier for logging
            
        Returns:
            Resolved value from state
            
        Raises:
            StateReferenceError: If the reference cannot be resolved
        """
        if not isinstance(reference, str):
            return reference
            
        # Debug logging
        if logger:
            logger.error(f"[{query_id}] Resolving reference: '{reference}'")
            
        # Special case for simple users_list access
        if reference == "state.users_list":
            if hasattr(state, "users_list"):
                if logger:
                    logger.error(f"[{query_id}] Direct access to users_list successful")
                return state.users_list
            else:
                if logger:
                    logger.error(f"[{query_id}] users_list not found on state object")
                    attrs = [a for a in dir(state) if not a.startswith('_')]
                    logger.error(f"[{query_id}] Available attributes: {attrs}")
        
        # Handle plain "users_list" without state prefix
        if reference == "users_list":
            if hasattr(state, "users_list"):
                if logger:
                    logger.error(f"[{query_id}] Direct access to users_list successful (no prefix)")
                return state.users_list
            else:
                if logger:
                    logger.error(f"[{query_id}] users_list not found on state object")
        
        try:
            # Call internal implementation with depth tracking
            return cls._resolve_reference_inner(reference, state, logger, query_id, 0)
        except StateReferenceError as e:
            if logger:
                logger.error(f"[{query_id}] {str(e)}")
            raise
    
    @classmethod
    def _resolve_reference_inner(
        cls,
        reference: str,
        state: Any,
        logger: Optional[logging.Logger] = None,
        query_id: str = "unknown",
        depth: int = 0
    ) -> Any:
        """Internal implementation with depth tracking for security."""
        # Security check: prevent excessive nesting
        if depth > cls.MAX_RECURSION_DEPTH:
            raise StateReferenceError(
                f"Reference too complex: max depth of {cls.MAX_RECURSION_DEPTH} exceeded for '{reference}'"
            )
        
        if not reference.startswith("state."):
            # If missing state. prefix, add it and retry
            if logger:
                logger.error(f"[{query_id}] Adding state. prefix to reference: '{reference}'")
            return cls._resolve_reference_inner(f"state.{reference}", state, logger, query_id, depth + 1)
        
        # Remove "state." prefix
        reference = reference[6:]  # len("state.") == 6
        
        # Handle the simplest case: direct attribute access with no additional syntax
        if "." not in reference and "[" not in reference:
            # Direct attribute access
            attr_name = reference
            if logger:
                logger.error(f"[{query_id}] Simple direct attribute access: '{attr_name}'")
                logger.error(f"[{query_id}] Has attribute: {hasattr(state, attr_name)}")
                
            if not hasattr(state, attr_name):
                attrs = [a for a in dir(state) if not a.startswith('_')]
                if logger:
                    logger.error(f"[{query_id}] Available state attributes: {attrs}")
                raise StateReferenceError(f"Attribute '{attr_name}' not found on state object")
            
            return getattr(state, attr_name)
        
        # Start with the root state object
        current = state
        path_so_far = "state"
        
        # Process reference parts
        remaining = reference
        
        while remaining:
            # Try to match array index: [0], [1], etc.
            array_match = cls.ARRAY_INDEX_PATTERN.match(remaining)
            if array_match:
                index = int(array_match.group(1))
                match_length = array_match.end()
                
                if not isinstance(current, (list, tuple)):
                    raise StateReferenceError(
                        f"Cannot index non-sequence at '{path_so_far}'"
                    )
                
                if index < 0 or index >= len(current):
                    raise StateReferenceError(
                        f"Index {index} out of range at '{path_so_far}'"
                    )
                
                current = current[index]
                path_so_far += f"[{index}]"
                remaining = remaining[match_length:]
                continue
            
            # Try to match dictionary key: ['key'], ["key"], etc.
            dict_match = cls.DICT_KEY_PATTERN.match(remaining)
            if dict_match:
                key = dict_match.group(1)
                match_length = dict_match.end()
                
                if not isinstance(current, dict):
                    raise StateReferenceError(
                        f"Cannot access key on non-dict at '{path_so_far}'"
                    )
                
                if key not in current:
                    raise StateReferenceError(
                        f"Key '{key}' not found at '{path_so_far}'"
                    )
                
                current = current[key]
                path_so_far += f"['{key}']"
                remaining = remaining[match_length:]
                continue
            
            # Try to match property access: .property
            prop_match = cls.PROPERTY_ACCESS_PATTERN.match(remaining)
            if prop_match:
                prop = prop_match.group(1)
                match_length = prop_match.end()
                
                # Handle property access based on current object type
                if isinstance(current, dict):
                    if prop not in current:
                        raise StateReferenceError(
                            f"Key '{prop}' not found at '{path_so_far}'"
                        )
                    current = current[prop]
                else:
                    if not hasattr(current, prop):
                        raise StateReferenceError(
                            f"Attribute '{prop}' not found at '{path_so_far}'"
                        )
                    current = getattr(current, prop)
                
                path_so_far += f".{prop}"
                remaining = remaining[match_length:]
                continue
            
            # If we get here, we couldn't parse the reference format
            raise StateReferenceError(
                f"Invalid reference format at '{remaining}' in '{reference}'"
            )
        
        return current