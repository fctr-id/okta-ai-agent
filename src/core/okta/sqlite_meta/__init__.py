"""
SQLite Metadata Module

Operational metadata storage for authentication and sync status tracking.

This module is used by BOTH SQLite and GraphDB sync modes to track:
- User authentication (local_users table)
- Sync operation status (sync_history table)
- User sessions (sessions table)

Database Location: ./sqlite_db/okta_meta.db
"""

from .operations import MetadataOperations, get_metadata_ops

__all__ = [
    'MetadataOperations',
    'get_metadata_ops',
]
