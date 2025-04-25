"""
Centralized registry for all tools across the application.

This module provides:
1. Auto-discovery of tools in *_tools.py files
2. Registry of tools by name, alias, and entity type
3. Simple access to tool documentation and metadata
4. Generation of comprehensive tool documentation
"""

import os
import sys
import importlib.util
import inspect
import glob
from typing import List, Dict, Set, Optional, Any, Callable, Tuple, Union
import logging
from pydantic import BaseModel, Field
from pathlib import Path
import traceback
import re

# Configure logging
logger = logging.getLogger(__name__)

class ToolNotFoundError(Exception):
    """Exception raised when a requested tool is not found in the registry."""
    pass

class ImportError(Exception):
    """Exception raised when a tool module cannot be imported."""
    pass

class ToolRegistry:
    """
    Centralized registry for all tools across the application.
    
    This class provides methods to:
    1. Register tools manually or by discovery
    2. Retrieve tools by name, alias, or entity type
    3. Generate documentation for available tools
    """
    
    def __init__(self):
        """Initialize an empty tool registry."""
        # Core registry data structures
        self.tools: Dict[str, Any] = {}
        self.tool_by_alias: Dict[str, str] = {}
        self.tools_by_entity: Dict[str, List[Any]] = {}
        
        # Import tracking
        self._imported_modules: Set[str] = set()
        self._failed_imports: Dict[str, str] = {}
        
        # Initialization state
        self._registry_initialized: bool = False
        self._original_sys_path: List[str] = list(sys.path)
        
        # Module import cache to avoid re-importing
        self._module_cache: Dict[str, Any] = {}
        
    def register_tool(self, tool: Any) -> bool:
        """
        Register a single tool with the registry.
        
        Args:
            tool: Tool object to register
            
        Returns:
            True if registration succeeded, False otherwise
        """
        # Validate tool has required attributes
        if not hasattr(tool, 'name'):
            logger.warning(f"Cannot register tool without name attribute: {str(tool)[:100]}")
            return False
        
        if not hasattr(tool, 'entity_type'):
            logger.warning(f"Tool '{tool.name}' missing entity_type attribute")
            return False
            
        # Register by name (skip if already registered)
        name = tool.name
        if name in self.tools:
            logger.debug(f"Tool '{name}' already registered, skipping")
            return False
            
        self.tools[name] = tool
        
        # Register by entity type
        entity_type = tool.entity_type
        if entity_type not in self.tools_by_entity:
            self.tools_by_entity[entity_type] = []
        self.tools_by_entity[entity_type].append(tool)
        
        # Register aliases if available
        if hasattr(tool, 'aliases') and tool.aliases:
            for alias in tool.aliases:
                try:
                    normalized_alias = self._normalize_tool_name(alias)
                    if normalized_alias != self._normalize_tool_name(name):  # Skip if alias matches name
                        self.tool_by_alias[normalized_alias] = name
                except Exception as e:
                    logger.warning(f"Error registering alias '{alias}' for tool '{name}': {str(e)}")
                
        logger.debug(f"Registered tool: {name} (entity: {entity_type})")
        return True
        
    def discover_tools(self, tools_directory: Optional[str] = None) -> None:
        """
        Auto-discover and register tools from all *_tools.py files.
        
        Args:
            tools_directory: Directory to search for tool modules
        """
        # Reset the system path to avoid conflicts from previous imports
        sys.path = list(self._original_sys_path)
        
        # Resolve tools directory path
        resolved_directory = self._resolve_tools_directory(tools_directory)
        if not resolved_directory:
            return
            
        logger.info(f"Discovering tools in: {resolved_directory}")
        
        # Track how many tools were registered
        initial_tool_count = len(self.tools)
        
        # Setup Python path for imports
        self._prepare_import_paths(resolved_directory)
        
        # Discover and import tool modules
        self._import_tool_modules(resolved_directory)
        
        # Log results
        new_tools = len(self.tools) - initial_tool_count
        logger.info(f"Discovered and registered {new_tools} tools")
        
        # If in debug mode, list all registered tools
        if new_tools > 0 and logger.isEnabledFor(logging.DEBUG):
            self._log_registered_tools()
            
        # Mark registry as initialized
        self._registry_initialized = True
        
    def get_tool(self, tool_name: str) -> Optional[Any]:
        """
        Get a tool by name or alias.
        
        Args:
            tool_name: Name or alias of the tool
            
        Returns:
            Tool object or None if not found
        """
        self._ensure_initialized()
        
        # Direct lookup by name
        if tool_name in self.tools:
            return self.tools[tool_name]
        
        # Lookup by alias
        try:
            normalized_name = self._normalize_tool_name(tool_name)
            if normalized_name in self.tool_by_alias:
                canonical_name = self.tool_by_alias[normalized_name]
                return self.tools[canonical_name]
        except Exception:
            pass  # Silently continue if normalization fails
        
        # Not found
        return None
        
    def get_tool_prompt(self, tool_name: str) -> Optional[str]:
        """
        Get the prompt for a tool by name or alias.
        
        Args:
            tool_name: Name or alias of the tool
            
        Returns:
            Tool prompt or None if not found
        """
        self._ensure_initialized()
        
        tool = self.get_tool(tool_name)
        if tool and hasattr(tool, 'prompt'):
            return tool.prompt
        
        return None
        
    def get_all_tools(self) -> List[Any]:
        """
        Get all registered tools.
        
        Returns:
            List of all registered tools
        """
        self._ensure_initialized()
        return list(self.tools.values())
        
    def get_tools_by_entity(self, entity_type: str) -> List[Any]:
        """
        Get tools for a specific entity type.
        
        Args:
            entity_type: Type of entity (e.g., "user", "group")
            
        Returns:
            List of tools for that entity type
        """
        self._ensure_initialized()
        return self.tools_by_entity.get(entity_type, [])
        
    def build_tools_documentation(self) -> str:
        """
        Build comprehensive documentation for all available tools.
        
        Returns:
            Formatted string containing all tool documentation
        """
        self._ensure_initialized()
        
        if not self.tools:
            logger.warning("No tools registered when building documentation")
            return "# No tools available\n\nNo tools have been registered with the system."
        
        tools_docs = "# Available Tools\n\n"
        
        # Group tools by entity type
        for entity_type, tools in sorted(self.tools_by_entity.items()):
            tools_docs += f"\n## {entity_type.capitalize()} Tools\n\n"
            
            for tool in sorted(tools, key=lambda t: t.name):
                # Format aliases if present
                aliases = getattr(tool, 'aliases', [])
                if isinstance(aliases, (list, set, tuple)) and aliases:
                    alias_str = f" (aliases: {', '.join(sorted(aliases))})"
                else:
                    alias_str = ""
                tools_docs += f"### {tool.name}{alias_str}\n"
                
                # Add description if available
                if hasattr(tool, 'description'):
                    tools_docs += f"- Description: {tool.description}\n"
                    
                # Add usage if available
                if hasattr(tool, 'usage'):
                    tools_docs += f"- Usage: {tool.usage}\n"
                    
                # Add parameters if available
                if hasattr(tool, 'parameters'):
                    # Handle both list and string parameters
                    params = tool.parameters
                    if isinstance(params, (list, tuple)):
                        params_str = ", ".join(params)
                    else:
                        params_str = str(params)
                    tools_docs += f"- Parameters: {params_str}\n"
                
                tools_docs += "\n"
        
        return tools_docs
    
    def clear(self) -> None:
        """Clear all registered tools and reset the registry state."""
        self.tools = {}
        self.tool_by_alias = {}
        self.tools_by_entity = {}
        self._registry_initialized = False
        self._imported_modules = set()
        self._failed_imports = {}
        self._module_cache = {}
        logger.debug("Tool registry cleared")
    
    def _resolve_tools_directory(self, tools_directory: Optional[str]) -> Optional[Path]:
        """
        Resolve the tools directory path using multiple strategies.
        
        Args:
            tools_directory: User-provided directory or None
            
        Returns:
            Resolved Path object or None if directory not found
        """
        if tools_directory:
            # User provided a specific directory
            path = Path(tools_directory).resolve()
            if path.exists() and path.is_dir():
                return path
            else:
                logger.warning(f"Specified tools directory not found: {tools_directory}")
                return None
                
        # Strategy 1: Use path relative to this file
        this_file = Path(__file__).resolve()
        project_root = this_file.parent.parent  # src/ directory
        path = project_root / 'core' / 'realtime' / 'tools'
        
        if path.exists() and path.is_dir():
            return path
            
        # Strategy 2: Check relative to current working directory
        cwd = Path.cwd()
        for relative_path in [
            Path('src/core/realtime/tools'),
            Path('core/realtime/tools'),
            Path('realtime/tools'),
            Path('tools')
        ]:
            path = cwd / relative_path
            if path.exists() and path.is_dir():
                return path
                
        logger.warning("Could not resolve tools directory. Please specify tools_directory explicitly.")
        return None
    
    def _prepare_import_paths(self, tools_directory: Path) -> None:
        """
        Add necessary paths to sys.path to enable imports.
        
        Args:
            tools_directory: Path to the tools directory
        """
        # Add the tools directory to sys.path
        tools_dir_str = str(tools_directory)
        if tools_dir_str not in sys.path:
            sys.path.insert(0, tools_dir_str)
        
        # Add the tools' parent directory
        parent_dir = str(tools_directory.parent)
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
            
        # Add grandparent directory (likely 'src')
        grandparent_dir = str(tools_directory.parent.parent)
        if grandparent_dir not in sys.path:
            sys.path.insert(0, grandparent_dir)
            
        logger.debug(f"Import paths: {', '.join(sys.path[:3])}")
    
    def _import_tool_modules(self, tools_directory: Path) -> None:
        """
        Import all tool modules in the given directory.
        
        Args:
            tools_directory: Path to the tools directory
        """
        # Find all tool module files
        tool_files = list(tools_directory.glob("*_tools.py"))
        if not tool_files:
            logger.warning(f"No tool files found in {tools_directory}")
            return
            
        logger.debug(f"Found {len(tool_files)} tool files: {', '.join(f.name for f in tool_files)}")
        
        # Import each tool module
        for file_path in tool_files:
            self._import_and_register_module(file_path)
    
    def _import_and_register_module(self, file_path: Path) -> None:
        """
        Import a module by file path and register its tools.
        
        Args:
            file_path: Path to the module file
        """
        module_name = file_path.stem  # Remove .py extension
        module_path = str(file_path)
        
        try:
            # Import the module using spec to avoid import system issues
            module = self._import_module_from_path(module_path, module_name)
            
            if not module:
                logger.error(f"Failed to import {module_name} from {module_path}")
                return
                
            # Register tools from the module
            self._register_tools_from_module(module)
            
        except Exception as e:
            logger.error(f"Error importing {module_name} from {module_path}: {str(e)}")
            logger.debug(traceback.format_exc())
            self._failed_imports[module_name] = str(e)
    
    def _import_module_from_path(self, file_path: str, module_name: str) -> Optional[Any]:
        """
        Import a module directly from a file path.
        
        Args:
            file_path: Full path to the module file
            module_name: Name to assign to the module
            
        Returns:
            The imported module or None if import failed
        """
        # Check if already imported
        if module_name in self._module_cache:
            return self._module_cache[module_name]
            
        try:
            # Use importlib.util for more reliable imports
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if not spec or not spec.loader:
                logger.error(f"Could not create spec for {module_name} at {file_path}")
                return None
                
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            
            # Cache the imported module
            self._module_cache[module_name] = module
            self._imported_modules.add(module_name)
            
            return module
            
        except Exception as e:
            logger.error(f"Failed to import {module_name} from {file_path}: {str(e)}")
            return None
    
    def _register_tools_from_module(self, module: Any) -> int:
        """
        Register all tools found in a module.
        
        Args:
            module: Imported module containing tools
            
        Returns:
            Number of tools registered
        """
        tools_registered = 0
        
        # Approach 1: Use register_tools function if available
        if hasattr(module, 'register_tools'):
            try:
                module.register_tools(self)
                # Count how many new tools were registered
                tool_count_before = len(self.tools)
                module.register_tools(self)
                tools_registered = len(self.tools) - tool_count_before
                logger.info(f"Registering tools from: {module.__name__}")
                return tools_registered
            except Exception as e:
                logger.error(f"Error calling register_tools in {module.__name__}: {str(e)}")
        
        # Approach 2: Look for *_TOOLS list constants
        for attr_name in dir(module):
            if attr_name.endswith('_TOOLS') and isinstance(getattr(module, attr_name), (list, tuple)):
                tools_list = getattr(module, attr_name)
                logger.debug(f"Found tools list: {attr_name} with {len(tools_list)} tools")
                
                for tool in tools_list:
                    if self.register_tool(tool):
                        tools_registered += 1
        
        # Log results
        if tools_registered > 0:
            logger.info(f"Registered {tools_registered} tools from {module.__name__}")
        else:
            logger.warning(f"No tools found in {module.__name__}")
            
        return tools_registered
    
    def _normalize_tool_name(self, name: str) -> str:
        """
        Normalize a tool name for consistent lookup.
        
        Args:
            name: Tool name or alias to normalize
            
        Returns:
            Normalized name string
        """
        if not name:
            return ""
            
        # Convert to lowercase and remove spaces, underscores, and hyphens
        return re.sub(r'[_\s-]', '', name.lower())
    
    def _log_registered_tools(self) -> None:
        """Log information about all registered tools."""
        tool_names = sorted(self.tools.keys())
        logger.debug(f"Registered tools: {', '.join(tool_names)}")
        
        entity_counts = {entity: len(tools) for entity, tools in self.tools_by_entity.items()}
        logger.debug(f"Entity counts: {entity_counts}")
        
        alias_count = len(self.tool_by_alias)
        logger.debug(f"Registered aliases: {alias_count}")
    
    def _ensure_initialized(self) -> None:
        """Ensure the registry is initialized by discovering tools if not done yet."""
        if not self._registry_initialized:
            self.discover_tools()


# Create a singleton instance of the registry
registry = ToolRegistry()

# Convenience functions that use the singleton instance

def register_tool(tool: Any) -> bool:
    """
    Register a single tool with the registry.
    
    Args:
        tool: Tool object to register
        
    Returns:
        True if registration succeeded, False otherwise
    """
    return registry.register_tool(tool)

def get_tool(tool_name: str) -> Optional[Any]:
    """
    Get a tool by name or alias.
    
    Args:
        tool_name: Name or alias of the tool
        
    Returns:
        Tool object or None if not found
    """
    return registry.get_tool(tool_name)

def get_tool_prompt(tool_name: str) -> Optional[str]:
    """
    Get the prompt for a tool by name or alias.
    
    Args:
        tool_name: Name or alias of the tool
        
    Returns:
        Tool prompt or None if not found
    """
    return registry.get_tool_prompt(tool_name)

def get_all_tools() -> List[Any]:
    """
    Get all registered tools.
    
    Returns:
        List of all registered tools
    """
    return registry.get_all_tools()

def get_tools_by_entity(entity_type: str) -> List[Any]:
    """
    Get tools for a specific entity type.
    
    Args:
        entity_type: Type of entity (e.g., "user", "group")
        
    Returns:
        List of tools for that entity type
    """
    return registry.get_tools_by_entity(entity_type)

def build_tools_documentation() -> str:
    """
    Build comprehensive documentation for all available tools.
    
    Returns:
        Formatted string containing all tool documentation
    """
    return registry.build_tools_documentation()

def discover_tools(tools_directory: str = None) -> None:
    """
    Manually trigger tool discovery.
    
    Args:
        tools_directory: Optional directory path to search in
    """
    registry.discover_tools(tools_directory)

def clear_registry() -> None:
    """Clear all registered tools and reset the registry state."""
    registry.clear()


# Initialize the registry when this module is imported
try:
    discover_tools()
    logger.info(f"Tool registry initialized with {len(get_all_tools())} tools")
except Exception as e:
    logger.error(f"Error initializing tool registry: {str(e)}")
    logger.error(traceback.format_exc())