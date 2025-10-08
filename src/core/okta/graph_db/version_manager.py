"""
GraphDB Version Manager

Manages multiple database versions for zero-downtime updates:
- Sync writes to new version while queries use current version
- Atomic version promotion after sync completes
- Immediate cleanup keeping latest 2 versions (current + previous)

Architecture:
    ./db/tenant_graph_v1.db  ← Current (queries use this)
    ./db/tenant_graph_v2.db  ← Staging (sync writes here)
    
After sync:
    version_manager.promote_staging()  # Instant switch!
    ./db/tenant_graph_v1.db  ← Previous (kept for old connections)
    ./db/tenant_graph_v2.db  ← Current (queries NOW use this)
    
Database naming: tenant_graph_v{version}.db
- Consistent naming regardless of Okta tenant
- .db extension for clarity (even though Kuzu may store as file or directory)
- Stored in ./db/ alongside SQLite metadata database
"""

import os
import threading
from pathlib import Path
from typing import Optional

from src.utils.logging import get_logger

logger = get_logger(__name__)


class GraphDBVersionManager:
    """
    Thread-safe version manager for GraphDB instances.
    
    Allows zero-downtime database updates by managing versioned database files.
    Queries always use the current version while syncs write to the next version.
    
    Database naming: tenant_graph_v{version}.db
    - Simple, consistent naming
    - .db extension for clarity
    - Stored in ./db/ folder alongside SQLite metadata
    """
    
    def __init__(self, db_dir: str = "./db", keep_versions: int = 2):
        """
        Initialize version manager
        
        Args:
            db_dir: Directory containing database files (default: "./db")
            keep_versions: Number of versions to keep (default: 2 = current + previous)
        """
        self.db_dir = Path(db_dir)
        self.db_dir.mkdir(parents=True, exist_ok=True)
        
        self.keep_versions = keep_versions
        self._lock = threading.Lock()
        
        # Find current version or start at 1
        self.current_version = self._detect_current_version()
        
        logger.info(f"GraphDB Version Manager initialized at version {self.current_version}")
        logger.info(f"Database directory: {self.db_dir.absolute()}")
    
    def _detect_current_version(self) -> int:
        """
        Detect the highest version number from existing database files.
        
        Looks for files matching pattern: tenant_graph_v{number}.db
        
        Returns:
            Highest version number found, or 1 if no databases exist
        """
        max_version = 0
        
        if not self.db_dir.exists():
            return 1
        
        # Pattern to match: tenant_graph_v{number}.db
        prefix = "tenant_graph_v"
        suffix = ".db"
        
        for file in self.db_dir.iterdir():
            if file.name.startswith(prefix) and file.name.endswith(suffix):
                try:
                    # Extract version number from "tenant_graph_v2.db" -> "2"
                    version_str = file.name.replace(prefix, "").replace(suffix, "")
                    version = int(version_str)
                    max_version = max(max_version, version)
                except ValueError:
                    continue
        
        return max_version if max_version > 0 else 1
    
    def get_current_db_path(self) -> str:
        """
        Get path to current ACTIVE database (for queries)
        
        Returns:
            Absolute path to current database (e.g., "./db/tenant_graph_v2.db")
        """
        with self._lock:
            current_path = self.db_dir / f"tenant_graph_v{self.current_version}.db"
            return str(current_path.absolute())
    
    def get_staging_db_path(self) -> str:
        """
        Get path to STAGING database (for sync writes)
        
        Returns:
            Absolute path to staging database (e.g., "./db/tenant_graph_v3.db")
        """
        with self._lock:
            staging_version = self.current_version + 1
            staging_path = self.db_dir / f"tenant_graph_v{staging_version}.db"
            return str(staging_path.absolute())
    
    def promote_staging(self, validate_metadata: bool = True) -> bool:
        """
        Atomically promote staging database to current.
        
        This is an instant operation - just increments the version counter.
        New connections will immediately use the new version.
        Old connections will continue to work until they close naturally.
        
        Args:
            validate_metadata: If True, check for SyncMetadata before promoting
        
        Returns:
            True if promotion successful, False otherwise
        """
        with self._lock:
            staging_version = self.current_version + 1
            staging_path = self.db_dir / f"tenant_graph_v{staging_version}.db"
            
            # Verify staging database exists
            if not staging_path.exists():
                logger.error(f"Cannot promote: staging database not found at {staging_path}")
                return False
            
            # Kuzu stores databases as a single file or directory depending on data
            # No need to check for specific internal structure - just verify it exists
            
            # Validate sync metadata if requested
            if validate_metadata:
                if not self._validate_staging_metadata(staging_version):
                    logger.error(f"❌ Cannot promote: staging v{staging_version} failed metadata validation")
                    return False
            
            # Record old version for cleanup
            old_version = self.current_version
            
            # ATOMIC PROMOTION: Just increment the version number!
            self.current_version = staging_version
            
            logger.info(f"✅ Database promoted: tenant_graph_v{old_version}.db → tenant_graph_v{self.current_version}.db")
            logger.info(f"   Active database: {staging_path}")
            
            # Immediate cleanup: keep only the configured number of versions
            self._cleanup_old_versions_keep_n(keep=self.keep_versions)
            
            return True
    
    def _validate_staging_metadata(self, staging_version: int) -> bool:
        """
        Validate that staging database has successful sync metadata.
        
        Checks for SyncMetadata node with:
        - success = true
        - users_count > 0 (at least some data exists)
        
        Args:
            staging_version: Version number to validate
            
        Returns:
            True if staging has valid sync metadata, False otherwise
        """
        try:
            import kuzu
            
            staging_path = self.db_dir / f"tenant_graph_v{staging_version}.db"
            
            # Open database in read-only mode for validation
            db = kuzu.Database(str(staging_path), read_only=True)
            conn = kuzu.Connection(db)
            
            # Check for successful sync metadata
            result = conn.execute("""
                MATCH (s:SyncMetadata)
                WHERE s.version = $version
                  AND s.success = true
                  AND s.users_count > 0
                RETURN s.success, s.users_count, s.groups_count, s.apps_count, s.end_time
                LIMIT 1
            """, {"version": staging_version})
            
            rows = result.get_as_pl()
            
            if len(rows) > 0:
                logger.info(f"✅ Staging v{staging_version} metadata validation passed:")
                logger.info(f"   Users: {rows['s.users_count'][0]}, Groups: {rows['s.groups_count'][0]}, Apps: {rows['s.apps_count'][0]}")
                return True
            else:
                logger.warning(f"⚠️  Staging v{staging_version} has no successful sync metadata")
                return False
                
        except Exception as e:
            logger.error(f"❌ Failed to validate staging metadata: {e}")
            return False
    
    def _cleanup_old_versions_keep_n(self, keep: int = 2) -> int:
        """
        Keep only the latest N versions, delete older ones.
        
        Safe to call immediately after promotion because we keep current + previous version.
        Old connections can still use previous version until they close naturally.
        
        Args:
            keep: Number of versions to keep (default: 2 = current + previous)
            
        Returns:
            Number of versions cleaned up
        """
        import shutil
        
        cleaned = 0
        
        try:
            # Find all version files
            versions = []
            prefix = "tenant_graph_v"
            suffix = ".db"
            
            for file in self.db_dir.iterdir():
                if file.name.startswith(prefix) and file.name.endswith(suffix):
                    try:
                        version_str = file.name.replace(prefix, "").replace(suffix, "")
                        version_num = int(version_str)
                        versions.append((version_num, file))
                    except ValueError:
                        continue
            
            # Sort by version number (newest first)
            versions.sort(reverse=True, key=lambda x: x[0])
            
            # Delete versions beyond keep count
            for version_num, path in versions[keep:]:
                try:
                    # Handle both file and directory (Kuzu can create either)
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                    logger.info(f"🗑️  Cleaned up old version: tenant_graph_v{version_num}.db")
                    cleaned += 1
                except Exception as e:
                    logger.error(f"Failed to cleanup tenant_graph_v{version_num}.db: {e}")
            
            if cleaned > 0:
                logger.info(f"✅ Cleanup complete: removed {cleaned} old version(s), kept latest {keep}")
            
        except Exception as e:
            logger.error(f"Error during version cleanup: {e}")
        
        return cleaned
    
    def get_version_info(self) -> dict:
        """
        Get information about database versions
        
        Returns:
            Dict with version information
        """
        with self._lock:
            current_path = self.db_dir / f"tenant_graph_v{self.current_version}.db"
            staging_path = self.db_dir / f"tenant_graph_v{self.current_version + 1}.db"
            
            return {
                "current_version": self.current_version,
                "current_path": str(current_path),
                "current_exists": current_path.exists(),
                "staging_version": self.current_version + 1,
                "staging_path": str(staging_path),
                "staging_exists": staging_path.exists(),
                "db_directory": str(self.db_dir.absolute())
            }
    
    def force_cleanup_all_old_versions(self) -> int:
        """
        Force immediate cleanup of all old database versions.
        
        Use with caution - only call when you're sure no connections are using old versions.
        
        Returns:
            Number of versions cleaned up
        """
        import shutil
        
        cleaned = 0
        with self._lock:
            current_version = self.current_version
            
            for file in self.db_dir.iterdir():
                if file.is_dir() and file.name.startswith("okta_v"):
                    try:
                        version = int(file.name.replace("okta_v", ""))
                        if version < current_version:
                            shutil.rmtree(file)
                            logger.info(f"Cleaned up old version: v{version}")
                            cleaned += 1
                    except (ValueError, Exception) as e:
                        logger.error(f"Error cleaning up {file}: {e}")
        
        logger.info(f"Force cleanup complete: {cleaned} old versions removed")
        return cleaned


# Global singleton instance
_version_manager: Optional[GraphDBVersionManager] = None


def get_version_manager() -> GraphDBVersionManager:
    """
    Get or create the global GraphDB version manager singleton
    
    Returns:
        GraphDBVersionManager instance
    """
    global _version_manager
    if _version_manager is None:
        _version_manager = GraphDBVersionManager()
    return _version_manager
