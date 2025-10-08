"""
SQLite Metadata Operations

Handles operational metadata for:
- Authentication (auth_users)
- Sync status tracking (sync_history)
- Session management (sessions)

This is separate from business data operations and is used for both
SQLite and GraphDB sync modes.

Database Location: ./db/tako-ai.db (consolidated with business data)
Schema Location: src/core/okta/sqlite_meta/schema.sql
"""

import sqlite3
import asyncio
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime, timezone
from contextlib import asynccontextmanager
import aiosqlite

from src.utils.logging import get_logger

logger = get_logger(__name__)


class MetadataOperations:
    """
    Manages operational metadata stored in SQLite.
    
    Used for:
    - User authentication (auth_users table)
    - Sync status tracking (sync_history table) 
    - Session management (sessions table)
    
    This operates independently of business data storage (SQLite or GraphDB).
    
    Database file: ./db/tako-ai.db (consolidated database)
    Schema file: src/core/okta/sqlite_meta/schema.sql
    """
    
    def __init__(self, db_path: str = "./db/tako-ai.db"):
        """
        Initialize metadata operations.
        
        Args:
            db_path: Path to SQLite database (default: ./db/tako-ai.db)
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Schema file is in src/core/okta/sqlite_meta/
        self.schema_path = Path(__file__).parent / "schema.sql"
        
        logger.info(f"MetadataOperations initialized")
        logger.info(f"  Database: {self.db_path.absolute()}")
        logger.info(f"  Schema: {self.schema_path.absolute()}")
    
    async def init_db(self) -> None:
        """Initialize the metadata database with schema"""
        try:
            if not self.schema_path.exists():
                logger.error(f"Schema file not found: {self.schema_path}")
                raise FileNotFoundError(f"Schema file not found: {self.schema_path}")
            
            # Read schema file
            with open(self.schema_path, 'r') as f:
                schema_sql = f.read()
            
            # Execute schema
            async with aiosqlite.connect(self.db_path) as db:
                await db.executescript(schema_sql)
                await db.commit()
            
            logger.info(f"✅ Metadata database initialized: {self.db_path}")
            
        except Exception as e:
            logger.error(f"Failed to initialize metadata database: {e}")
            raise
    
    # ========================================================================
    # Sync History Operations
    # ========================================================================
    
    async def create_sync_record(
        self, 
        tenant_id: str, 
        sync_type: str = "graphdb"
    ) -> int:
        """
        Create a new sync history record.
        
        Args:
            tenant_id: Okta tenant ID
            sync_type: Type of sync ('sqlite' or 'graphdb')
            
        Returns:
            Sync record ID
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    """
                    INSERT INTO sync_history (tenant_id, sync_type, status, start_time)
                    VALUES (?, ?, 'running', CURRENT_TIMESTAMP)
                    """,
                    (tenant_id, sync_type)
                )
                await db.commit()
                sync_id = cursor.lastrowid
                
            logger.info(f"Created sync record: {sync_id} (type: {sync_type})")
            return sync_id
            
        except Exception as e:
            logger.error(f"Failed to create sync record: {e}")
            raise
    
    async def update_sync_record(
        self, 
        sync_id: int, 
        data: Dict[str, Any]
    ) -> None:
        """
        Update sync history record.
        
        Args:
            sync_id: Sync record ID
            data: Dictionary of fields to update
        """
        try:
            # Build SET clause dynamically
            set_clauses = []
            values = []
            
            for key, value in data.items():
                set_clauses.append(f"{key} = ?")
                values.append(value)
            
            values.append(sync_id)  # For WHERE clause
            
            sql = f"""
                UPDATE sync_history 
                SET {', '.join(set_clauses)}
                WHERE id = ?
            """
            
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(sql, values)
                await db.commit()
            
        except Exception as e:
            logger.error(f"Failed to update sync record {sync_id}: {e}")
            raise
    
    async def get_active_sync(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """
        Get currently active sync for tenant.
        
        Args:
            tenant_id: Okta tenant ID
            
        Returns:
            Sync record dict or None
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """
                    SELECT * FROM sync_history
                    WHERE tenant_id = ? AND status IN ('running', 'idle')
                    ORDER BY start_time DESC
                    LIMIT 1
                    """,
                    (tenant_id,)
                )
                row = await cursor.fetchone()
                
                if row:
                    return dict(row)
                return None
                
        except Exception as e:
            logger.error(f"Failed to get active sync: {e}")
            return None
    
    async def get_last_completed_sync(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """
        Get last completed sync for tenant.
        
        Args:
            tenant_id: Okta tenant ID
            
        Returns:
            Sync record dict or None
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """
                    SELECT * FROM sync_history
                    WHERE tenant_id = ? AND status IN ('completed', 'failed', 'canceled')
                    ORDER BY end_time DESC
                    LIMIT 1
                    """,
                    (tenant_id,)
                )
                row = await cursor.fetchone()
                
                if row:
                    return dict(row)
                return None
                
        except Exception as e:
            logger.error(f"Failed to get last completed sync: {e}")
            return None
    
    async def get_sync_history(
        self, 
        tenant_id: str, 
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get sync history for tenant.
        
        Args:
            tenant_id: Okta tenant ID
            limit: Maximum records to return
            
        Returns:
            List of sync record dicts
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """
                    SELECT * FROM sync_history
                    WHERE tenant_id = ?
                    ORDER BY start_time DESC
                    LIMIT ?
                    """,
                    (tenant_id, limit)
                )
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
                
        except Exception as e:
            logger.error(f"Failed to get sync history: {e}")
            return []
    
    async def cleanup_old_sync_records(
        self, 
        tenant_id: str, 
        keep_count: int = 100
    ) -> int:
        """
        Clean up old sync history records, keeping the most recent N.
        
        Args:
            tenant_id: Okta tenant ID
            keep_count: Number of records to keep
            
        Returns:
            Number of records deleted
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    """
                    DELETE FROM sync_history
                    WHERE tenant_id = ? AND id NOT IN (
                        SELECT id FROM sync_history
                        WHERE tenant_id = ?
                        ORDER BY start_time DESC
                        LIMIT ?
                    )
                    """,
                    (tenant_id, tenant_id, keep_count)
                )
                await db.commit()
                deleted = cursor.rowcount
                
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} old sync records for tenant {tenant_id}")
            
            return deleted
            
        except Exception as e:
            logger.error(f"Failed to cleanup sync records: {e}")
            return 0
    
    # ========================================================================
    # Authentication Operations (for Phase 7)
    # ========================================================================
    
    async def create_user(
        self, 
        username: str, 
        password_hash: str, 
        email: Optional[str] = None
    ) -> int:
        """
        Create a new local user.
        
        Args:
            username: Username
            password_hash: Hashed password (use Argon2)
            email: User email (optional)
            
        Returns:
            User ID
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    """
                    INSERT INTO local_users (username, password_hash, email)
                    VALUES (?, ?, ?)
                    """,
                    (username, password_hash, email)
                )
                await db.commit()
                user_id = cursor.lastrowid
                
            logger.info(f"Created local user: {username} (id: {user_id})")
            return user_id
            
        except Exception as e:
            logger.error(f"Failed to create user {username}: {e}")
            raise
    
    async def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """
        Get user by username.
        
        Args:
            username: Username to look up
            
        Returns:
            User dict or None
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT * FROM local_users WHERE username = ?",
                    (username,)
                )
                row = await cursor.fetchone()
                
                if row:
                    return dict(row)
                return None
                
        except Exception as e:
            logger.error(f"Failed to get user {username}: {e}")
            return None


# Singleton instance
_metadata_ops: Optional[MetadataOperations] = None


def get_metadata_ops(db_path: str = "./db/tako-ai.db") -> MetadataOperations:
    """
    Get singleton MetadataOperations instance.
    
    Args:
        db_path: Path to consolidated database (default: ./db/tako-ai.db)
        
    Returns:
        MetadataOperations instance
    """
    global _metadata_ops
    
    if _metadata_ops is None:
        _metadata_ops = MetadataOperations(db_path)
    
    return _metadata_ops
