"""
Special Tools module for complex, multi-step operations.

Special tools are self-contained, comprehensive tools that perform
multiple Okta API operations in a single execution to provide
complete analysis and results.
"""

import importlib
import os
from typing import Dict, List, Any
from pathlib import Path

# Registry of available special tools
_SPECIAL_TOOLS_REGISTRY = {}


def discover_special_tools() -> Dict[str, Any]:
    """
    Dynamically discover all special tools in this directory.
    
    Returns:
        Dict mapping tool names to their metadata and functions
    """
    global _SPECIAL_TOOLS_REGISTRY
    
    if _SPECIAL_TOOLS_REGISTRY:
        return _SPECIAL_TOOLS_REGISTRY
    
    tools_dir = Path(__file__).parent
    
    for file_path in tools_dir.glob("*.py"):
        if file_path.name.startswith("_") or file_path.name == "__init__.py":
            continue
            
        module_name = file_path.stem
        try:
            # Import the module
            module = importlib.import_module(f"src.core.tools.special_tools.{module_name}")
            
            # Check if it has the required attributes
            if hasattr(module, 'TOOL_METADATA') and hasattr(module, 'get_tool_metadata') and hasattr(module, 'get_tool_function'):
                tool_metadata = module.get_tool_metadata()
                tool_function = module.get_tool_function()
                code_template = getattr(module, 'get_code_template', lambda: None)()
                
                # Extract entity names from lightweight reference
                lightweight_ref = tool_metadata.get("lightweight_reference", {})
                entities = lightweight_ref.get("entities", {})
                
                # Register tool for each entity it provides
                for entity_name in entities.keys():
                    _SPECIAL_TOOLS_REGISTRY[entity_name] = {
                        "module_name": module_name,
                        "metadata": tool_metadata,
                        "function": tool_function,
                        "code_template": code_template,
                        "get_metadata": module.get_tool_metadata,
                        "get_function": module.get_tool_function
                    }
                
        except Exception as e:
            # Log but don't fail discovery for one bad tool
            print(f"Warning: Could not load special tool {module_name}: {e}")
    
    return _SPECIAL_TOOLS_REGISTRY


def get_lightweight_references() -> List[Dict[str, Any]]:
    """
    Get lightweight metadata for all special tools (for pre-planning agent).
    
    Returns:
        List of lightweight tool references
    """
    tools = discover_special_tools()
    return [tool["metadata"]["lightweight_reference"] for tool in tools.values()]


def get_detailed_references() -> Dict[str, Dict[str, Any]]:
    """
    Get detailed metadata for all special tools (for planning agent).
    
    Returns:
        Dict mapping tool names to detailed references
    """
    tools = discover_special_tools()
    return {
        name: tool["metadata"]["detailed_reference"] 
        for name, tool in tools.items()
    }


def get_special_tool(tool_name: str) -> Dict[str, Any]:
    """
    Get a specific special tool by name.
    
    Args:
        tool_name: Name of the tool to retrieve
        
    Returns:
        Dict containing tool metadata and function, or None if not found
    """
    tools = discover_special_tools()
    return tools.get(tool_name)


def execute_special_tool(tool_name: str, **kwargs):
    """
    Execute a special tool with given parameters.
    
    Args:
        tool_name: Name of the tool to execute
        **kwargs: Parameters to pass to the tool function
        
    Returns:
        Tool execution result
    """
    tool = get_special_tool(tool_name)
    if not tool:
        raise ValueError(f"Special tool '{tool_name}' not found")
    
    return tool["function"](**kwargs)
