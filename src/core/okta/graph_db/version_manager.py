"""
GraphDB Version Manager

Manages multiple database versions for zero-downtime updates:
- Sync writes to new version while queries use current version
- Atomic version promotion after sync completes
- Immediate cleanup keeping latest 2 versions (current + previous)

Architecture:
    ./graph_db/okta_v1.db  ← Current (queries use this)
    ./graph_db/okta_v2.db  ← Staging (sync writes here)
    
After sync:
    version_manager.promote_staging()  # Instant switch!
    ./graph_db/okta_v1.db  ← Previous (kept for old connections)
    ./graph_db/okta_v2.db  ← Current (queries NOW use this)
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
    """
    
    def __init__(self, db_dir: str = "./graph_db", keep_versions: int = 2):
        """
        Initialize version manager
        
        Args:
            db_dir: Directory containing database files
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
        """Detect the highest version number from existing database files"""
        max_version = 0
        
        if not self.db_dir.exists():
            return 1
        
        for file in self.db_dir.iterdir():
            if file.is_dir() and file.name.startswith("okta_v"):
                try:
                    version = int(file.name.replace("okta_v", ""))
                    max_version = max(max_version, version)
                except ValueError:
                    continue
        
        return max_version if max_version > 0 else 1
    
    def get_current_db_path(self) -> str:
        """
        Get path to current ACTIVE database (for queries)
        
        Returns:
            Absolute path to current database directory
        """
        with self._lock:
            current_path = self.db_dir / f"okta_v{self.current_version}"
            return str(current_path.absolute())
    
    def get_staging_db_path(self) -> str:
        """
        Get path to STAGING database (for sync writes)
        
        Returns:
            Absolute path to staging database directory
        """
        with self._lock:
            staging_version = self.current_version + 1
            staging_path = self.db_dir / f"okta_v{staging_version}"
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
            staging_path = self.db_dir / f"okta_v{staging_version}"
            
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
            old_version_path = self.db_dir / f"okta_v{old_version}"
            
            # ATOMIC PROMOTION: Just increment the version number!
            self.current_version = staging_version
            
            logger.info(f"✅ Database promoted: v{old_version} → v{self.current_version}")
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
            
            staging_path = self.db_dir / f"okta_v{staging_version}"
            
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
            # Find all version directories
            versions = []
            for file in self.db_dir.iterdir():
                if file.is_dir() and file.name.startswith("okta_v"):
                    try:
                        version_num = int(file.name.replace("okta_v", ""))
                        versions.append((version_num, file))
                    except ValueError:
                        continue
            
            # Sort by version number (newest first)
            versions.sort(reverse=True, key=lambda x: x[0])
            
            # Delete versions beyond keep count
            for version_num, path in versions[keep:]:
                try:
                    shutil.rmtree(path)
                    logger.info(f"🗑️  Cleaned up old version: v{version_num}")
                    cleaned += 1
                except Exception as e:
                    logger.error(f"Failed to cleanup v{version_num}: {e}")
            
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
            current_path = self.db_dir / f"okta_v{self.current_version}"
            staging_path = self.db_dir / f"okta_v{self.current_version + 1}"
            
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
