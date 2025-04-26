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


def build_tools_documentation() -> str:
    """
    Build comprehensive documentation for all available tools.
    
    Returns:
        Formatted string containing all tool documentation
    """
    if not _TOOLS:
        logger.warning("No tools registered when building documentation")
        return "# No tools available\n\nNo tools have been registered with the system."
    
    tools_docs = "# Available Tools\n\n"
    
    # Group tools by entity type
    for entity_type, tools in sorted(_TOOLS_BY_ENTITY.items()):
        tools_docs += f"\n## {entity_type.capitalize()} Tools\n\n"
        
        for tool in sorted(tools, key=lambda t: t.name):
            # Format aliases if present
            aliases = getattr(tool, 'aliases', [])
            if aliases:
                alias_str = f" (aliases: {', '.join(sorted(aliases))})"
            else:
                alias_str = ""
            tools_docs += f"### {tool.name}{alias_str}\n"
            
            # Add description (truncated for brevity in overall docs)
            if tool.description:
                # Get first paragraph or first 200 chars
                desc_lines = tool.description.strip().split("\n\n")
                brief_desc = desc_lines[0].strip()
                if len(brief_desc) > 200:
                    brief_desc = brief_desc[:197] + "..."
                tools_docs += f"{brief_desc}\n\n"
    
    return tools_docs


def load_tools() -> bool:
    """
    Load all tool modules.
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # Import tool modules
        packages_to_try = [
            "src.core.realtime.tools.user_tools",
            "src.core.realtime.tools.group_tools",
            "src.core.realtime.tools.datetime_tools",
            # Add more tool modules as they become available
        ]
        
        loaded_modules = []
        for package in packages_to_try:
            try:
                module = importlib.import_module(package)
                loaded_modules.append(module.__name__)
            except ImportError as e:
                # This is expected for optional modules
                logger.warning(f"Could not import {package}: {str(e)}")
            except Exception as e:
                # Log other errors but continue importing other modules
                logger.error(f"Error loading {package}: {str(e)}")
        
        # Note that we don't need to explicitly register the tools,
        # because they register themselves when their modules are imported
        # via the @register_tool decorator
        
        # Log success even if some modules failed - as long as we have some tools
        if is_registry_initialized():
            logger.info(f"Loaded {len(_TOOLS)} tools across {len(_TOOLS_BY_ENTITY)} entity types")
            return True
        else:
            logger.warning("No tools were loaded")
            return False
            
    except Exception as e:
        logger.error(f"Unexpected error loading tools: {str(e)}")
        return False


# Initialize the registry when this module is imported
try:
    load_tools()
except Exception as e:
    # Never let initialization errors propagate up to the importer
    logger.error(f"Error during tool registry initialization: {str(e)}")