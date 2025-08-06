"""
Centralized registry for all tools across the application.

This module provides:
1. Simple registration of tools using decorators
2. Registry of tools by name, alias, and entity type
3. Access to tool documentation and metadata
"""

import importlib
from typing import List, Dict, Optional, Any, Callable, Union
import logging
from src.utils.logging import get_logger

# Configure logging
logger = get_logger(__name__)

class Tool:
    """Base class for all tool definitions."""
    name: str
    entity_type: str
    description: str
    aliases: List[str] = []
    function: Callable = None
    
    def __init__(self, name: str, entity_type: str, description: str = "", aliases: List[str] = None):
        self.name = name
        self.entity_type = entity_type
        self.description = description
        self.aliases = aliases or []
        
    def __str__(self):
        return f"Tool({self.name}, entity={self.entity_type})"


# Global registry data structures
_TOOLS: Dict[str, Tool] = {}
_TOOL_ALIASES: Dict[str, str] = {}
_TOOLS_BY_ENTITY: Dict[str, List[Tool]] = {}


def register_tool(name: str, entity_type: str, description: str = None, aliases: List[str] = None) -> Callable:
    """
    Decorator to register a tool function.
    
    Args:
        name: Tool name (must be unique)
        entity_type: Type of entity this tool works with (user, group, etc)
        description: Tool description (defaults to function docstring)
        aliases: Alternative names for the tool
        
    Returns:
        Decorator function
    """
    def decorator(func):
        # Extract description from docstring if not provided
        tool_description = description or func.__doc__ or ""
        
        # Create tool object
        tool = Tool(
            name=name,
            entity_type=entity_type,
            description=tool_description,
            aliases=aliases or []
        )
        
        # Add function to the tool
        tool.function = func
        
        # Register the tool
        _register_tool_object(tool)
        
        return func
    
    return decorator


def _normalize_name(name: str) -> str:
    """
    Normalize a name for consistent lookup.
    
    Args:
        name: Name to normalize
        
    Returns:
        Normalized name (lowercase, no spaces or underscores)
    """
    if not name:
        return ""
    return name.lower().replace(" ", "").replace("-", "").replace("_", "")


def _register_tool_object(tool: Tool) -> bool:
    """
    Register a tool object in the registry.
    
    Args:
        tool: Tool object to register
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Check for required attributes
        if not tool.name:
            logger.warning("Cannot register tool with empty name")
            return False
        
        if not tool.entity_type:
            logger.warning(f"Tool '{tool.name}' missing entity_type")
            return False
        
        # Skip if already registered
        if tool.name in _TOOLS:
            logger.debug(f"Tool '{tool.name}' already registered, skipping")
            return False
        
        # Register by name
        _TOOLS[tool.name] = tool
        
        # Register by entity type
        if tool.entity_type not in _TOOLS_BY_ENTITY:
            _TOOLS_BY_ENTITY[tool.entity_type] = []
        _TOOLS_BY_ENTITY[tool.entity_type].append(tool)
        
        # Register aliases
        if tool.aliases:
            for alias in tool.aliases:
                if not alias or alias == tool.name:
                    continue
                    
                normalized_alias = _normalize_name(alias)
                _TOOL_ALIASES[normalized_alias] = tool.name
                
        logger.debug(f"Registered tool: {tool.name} (entity: {tool.entity_type})")
        return True
        
    except Exception as e:
        logger.error(f"Error registering tool '{getattr(tool, 'name', 'unknown')}': {str(e)}")
        return False


def get_tool(tool_name: str) -> Optional[Tool]:
    """
    Get a tool by name or alias.
    
    Args:
        tool_name: Name or alias of the tool
        
    Returns:
        Tool object or None if not found
    """
    # Direct lookup
    if tool_name in _TOOLS:
        return _TOOLS[tool_name]
    
    # Try normalized name
    normalized = _normalize_name(tool_name)
    
    # Check aliases
    if normalized in _TOOL_ALIASES:
        canonical_name = _TOOL_ALIASES[normalized]
        return _TOOLS.get(canonical_name)
    
    # Not found
    return None


def get_tool_prompt(tool_name: str) -> Optional[str]:
    """
    Get the documentation for a tool.
    
    Args:
        tool_name: Name of the tool
        
    Returns:
        Tool documentation or None if not found
    """
    tool = get_tool(tool_name)
    if tool and hasattr(tool, 'description') and tool.description:
        return tool.description
    
    return None


def get_all_tools() -> List[Tool]:
    """
    Get all registered tools.
    
    Returns:
        List of all tools
    """
    return list(_TOOLS.values())


def get_tools_by_entity(entity_type: str) -> List[Tool]:
    """
    Get all tools for a specific entity type.
    
    Args:
        entity_type: Entity type to filter by
        
    Returns:
        List of tools for that entity
    """
    return _TOOLS_BY_ENTITY.get(entity_type, [])


def clear_registry() -> None:
    """Clear the registry for testing."""
    _TOOLS.clear()
    _TOOL_ALIASES.clear()
    _TOOLS_BY_ENTITY.clear()


def is_registry_initialized() -> bool:
    """
    Check if the registry has tools registered.
    
    Returns:
        True if tools are registered, False otherwise
    """
    return len(_TOOLS) > 0


import json

def build_tools_documentation() -> str:
    """
    Build comprehensive documentation for all available tools in JSON format.
    
    Now uses Modern Execution Manager instead of legacy tool registry.
    
    Returns:
        JSON string containing all tool names and descriptions
    """
    try:
        # Import Modern Execution Manager to get current tools
        from src.core.orchestration.modern_execution_manager import ModernExecutionManager
        
        # Create a temporary instance to get available entities and endpoints
        modern_executor = ModernExecutionManager()
        
        tools_list = []
        
        # Add API tools based on available entities and endpoints
        for entity in modern_executor.available_entities:
            # Create API tool entry
            api_tool = {
                "tool_name": f"api_{entity}",
                "description": f"API operations for {entity} including list, get, and manage operations"
            }
            tools_list.append(api_tool)
        
        # Add SQL tools based on available SQL tables
        for table_name in modern_executor.sql_tables.keys():
            # Create SQL tool entry
            sql_tool = {
                "tool_name": f"sql_{table_name}",
                "description": f"SQL queries for {table_name} table with filtering and analysis capabilities"
            }
            tools_list.append(sql_tool)
        
        # Sort tools by name for consistency
        tools_list.sort(key=lambda x: x["tool_name"])
        
        logger.info(f"Built tools documentation with {len(tools_list)} tools from Modern Execution Manager")
        return json.dumps(tools_list, indent=2)
        
    except Exception as e:
        logger.error(f"Error building tools documentation from Modern Execution Manager: {e}")
        
        # Fallback to empty list if Modern Execution Manager fails
        fallback_tools = [{
            "tool_name": "modern_execution_manager",
            "description": "Modern execution manager with API and SQL capabilities"
        }]
        
        return json.dumps(fallback_tools, indent=2)


def load_tools() -> bool:
    """
    Load all tool modules.
    
    NOTE: Disabled for Modern Execution Manager mode.
    Legacy realtime mode tools are no longer needed as we use the Modern Execution Manager.
    
    Returns:
        True if successful, False otherwise
    """
    # DISABLED: Legacy tool loading no longer needed with Modern Execution Manager
    logger.info("Tool registry loading disabled - using Modern Execution Manager instead")
    return True


# DON'T initialize the registry automatically anymore since we use Modern Execution Manager
# The old approach would automatically load legacy tools which we no longer need
try:
    # load_tools()  # COMMENTED OUT - no longer needed
    logger.info("Tool registry initialization skipped - Modern Execution Manager provides all functionality")
except Exception as e:
    # Never let initialization errors propagate up to the importer
    logger.error(f"Error during tool registry initialization: {str(e)}")