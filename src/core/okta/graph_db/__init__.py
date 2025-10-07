"""
GraphDB Module - Graph Database Operations for Okta Data

This module handles all graph database operations using the Kuzu engine.
Provides schema management, sync operations, query execution, and orchestration.

Location: src/core/okta/graph_db/
"""

# Import enhanced schema v2 (with all fields from models.py)
from .schema_v2_enhanced import initialize_enhanced_schema, ENHANCED_GRAPH_SCHEMA

# Backward-compatible exports (maintain existing API)
initialize_graph_schema = initialize_enhanced_schema
GRAPH_SCHEMA = ENHANCED_GRAPH_SCHEMA

from .sync_operations import GraphDBSyncOperations
from .engine import GraphDBOrchestrator
from .version_manager import GraphDBVersionManager, get_version_manager

__all__ = [
    'initialize_graph_schema',
    'GRAPH_SCHEMA',
    'initialize_enhanced_schema',
    'ENHANCED_GRAPH_SCHEMA',
    'GraphDBSyncOperations',
    'GraphDBOrchestrator',
    'GraphDBVersionManager',
    'get_version_manager'
]
