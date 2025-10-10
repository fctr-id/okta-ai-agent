"""
GraphDB Sync Engine for Okta Integration

Orchestrates synchronization from Okta API directly to GraphDB:
- Users with relationships
- Groups with memberships  
- Applications
- Direct Okta → GraphDB pipeline (no SQLite)
- Atomic database swapping for zero-downtime updates

Core Components:
- GraphDBOrchestrator: Main sync coordinator
- Reuses OktaClientWrapper for API calls
- Uses GraphDBSyncOperations for database writes
- Dual-database strategy: sync to staging, atomic swap to production
"""

from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import asyncio
import os
import shutil
from pathlib import Path

from src.core.okta.client.client import OktaClientWrapper
from src.core.okta.graph_db.sync_operations import GraphDBSyncOperations
from src.core.okta.sqlite_meta import get_metadata_ops
from src.utils.logging import get_logger

logger = get_logger(__name__)


class GraphDBOrchestrator:
    """
    Orchestrates Okta entity synchronization directly to GraphDB.
    
    Features:
    - Direct Okta API → GraphDB sync
    - No SQLite dependency
    - Parallel entity syncing
    - Error recovery
    - Relationship handling
    - Zero-downtime updates via version manager
    """
    
    def __init__(self, tenant_id: str, graph_db_path: str = None, cancellation_flag=None, use_versioning: bool = True):
        """
        Initialize GraphDB sync orchestrator
        
        Args:
            tenant_id: Tenant identifier for Okta org
            graph_db_path: Path to GraphDB database file (optional if using versioning)
            cancellation_flag: Optional asyncio.Event for cancellation
            use_versioning: If True, use version manager for zero-downtime updates
        """
        self.tenant_id = tenant_id
        self.cancellation_flag = cancellation_flag
        self.use_versioning = use_versioning
        self.sync_id = None  # Track current sync record ID
        self._metadata_initialized = False  # Track if metadata DB is ready
        
        # Initialize metadata operations for sync status tracking
        self.meta_ops = get_metadata_ops()
        
        # Determine database path
        if use_versioning:
            from src.core.okta.graph_db.version_manager import get_version_manager
            self.version_manager = get_version_manager()
            self.graph_db_path = self.version_manager.get_staging_db_path()
            logger.info(f"Using version manager: writing to staging v{self.version_manager.current_version + 1}")
        else:
            self.graph_db_path = graph_db_path or "./db/tenant_graph_v1.db"
            self.version_manager = None
        
        self.graph_db = GraphDBSyncOperations(self.graph_db_path)
        
        # Schema is automatically initialized when GraphDBSyncOperations connects
        
    async def run_sync(self, auto_promote: bool = True, sync_id: Optional[int] = None) -> Dict[str, int]:
        """
        Run complete Okta → GraphDB sync operation
        
        Args:
            auto_promote: If True and using versioning, automatically promote staging after successful sync
            sync_id: Optional existing sync record ID (if None, creates new record)
        
        Returns:
            Dict with entity counts: {'users': N, 'groups': N, 'apps': N, ...}
            
        Raises:
            Exception: On sync failures
        """
        logger.info(f"Starting GraphDB sync for tenant: {self.tenant_id}")
        
        # Initialize metadata database on first sync
        if not self._metadata_initialized:
            logger.info("Initializing metadata database...")
            await self.meta_ops.init_db()
            self._metadata_initialized = True
            logger.info("Metadata database initialized")
        
        # Use existing sync_id or create new one
        if sync_id is not None:
            self.sync_id = sync_id
            logger.info(f"Using existing sync record ID: {self.sync_id}")
        else:
            # Create sync record in metadata database
            self.sync_id = await self.meta_ops.create_sync_record(
                tenant_id=self.tenant_id,
                sync_type="graphdb"
            )
            logger.info(f"Created sync record ID: {self.sync_id}")
        
        try:
            # Use OktaClientWrapper as async context manager
            async with OktaClientWrapper(self.tenant_id, self.cancellation_flag) as okta_client:
                # Check for cancellation before starting
                if self.cancellation_flag and self.cancellation_flag.is_set():
                    raise asyncio.CancelledError("Sync cancelled before start")
                
                # Sync groups first (needed for relationships)
                await self._sync_groups(okta_client)
                
                # Check cancellation
                if self.cancellation_flag and self.cancellation_flag.is_set():
                    raise asyncio.CancelledError("Sync cancelled after groups")
                
                # Sync applications
                await self._sync_applications(okta_client)
                
                # Check cancellation
                if self.cancellation_flag and self.cancellation_flag.is_set():
                    raise asyncio.CancelledError("Sync cancelled after applications")
                
                # Sync users (with relationships) - MUST be before devices
                await self._sync_users(okta_client)
                
                # Check cancellation
                if self.cancellation_flag and self.cancellation_flag.is_set():
                    raise asyncio.CancelledError("Sync cancelled after users")
                
                # Sync devices (depends on users for OWNS relationships)
                await self._sync_devices(okta_client)
                
                # Check cancellation
                if self.cancellation_flag and self.cancellation_flag.is_set():
                    raise asyncio.CancelledError("Sync cancelled after devices")
                
                # Sync policies (depends on applications for GOVERNED_BY relationships)
                await self._sync_policies(okta_client)
                
                # Check cancellation
                if self.cancellation_flag and self.cancellation_flag.is_set():
                    raise asyncio.CancelledError("Sync cancelled after policies")
            
            # Get final counts
            counts = self.graph_db.get_entity_counts(self.tenant_id)
            logger.info(f"GraphDB sync complete: {counts}")
            
            # Create sync metadata node for validation
            if self.use_versioning and self.version_manager:
                self._create_sync_metadata(counts)
            
            # CRITICAL: Close the GraphDB connection before promotion to release file lock
            self.graph_db.close()
            logger.info("Closed GraphDB connection for promotion")
            
            # Auto-promote staging to current if using versioning
            promoted = False
            if self.use_versioning and auto_promote and self.version_manager:
                # Skip metadata validation since we track sync metadata in SQLite instead
                if self.version_manager.promote_staging(validate_metadata=False):
                    logger.info("✅ Staging database promoted to current - queries now use new data!")
                    promoted = True
                else:
                    logger.warning("⚠️  Failed to promote staging database")
            
            # Update sync record with success
            await self.meta_ops.update_sync_record(self.sync_id, {
                "status": "completed",
                "end_time": datetime.now(timezone.utc),
                "success": True,
                "progress_percentage": 100,  # Mark as 100% complete
                "users_count": counts.get('users', 0),
                "groups_count": counts.get('groups', 0),
                "apps_count": counts.get('apps', 0),
                "policies_count": counts.get('policies', 0),
                "devices_count": counts.get('devices', 0),
                "graphdb_version": self.version_manager.current_version if self.version_manager else None,
                "graphdb_promoted": promoted
            })
            logger.info(f"✅ Sync record {self.sync_id} marked as completed")
            
            return counts
            
        except asyncio.CancelledError:
            logger.warning("GraphDB sync was cancelled")
            # Update sync record with cancellation
            if self.sync_id:
                await self.meta_ops.update_sync_record(self.sync_id, {
                    "status": "canceled",
                    "end_time": datetime.now(timezone.utc),
                    "success": False,
                    "error_details": "Sync cancelled by user"
                })
            raise
        except Exception as e:
            logger.error(f"GraphDB sync failed: {e}", exc_info=True)
            # Update sync record with failure
            if self.sync_id:
                await self.meta_ops.update_sync_record(self.sync_id, {
                    "status": "failed",
                    "end_time": datetime.now(timezone.utc),
                    "success": False,
                    "error_details": str(e)
                })
            raise
    
    async def _sync_groups(self, okta_client) -> None:
        """Fetch groups from Okta and sync to GraphDB"""
        logger.info("Syncing groups from Okta API...")
        
        try:
            # Fetch all groups from Okta
            groups_data = await okta_client.list_groups()
            
            if not groups_data:
                logger.warning("No groups found in Okta")
                return
            
            # Groups already have okta_id from client, just use them directly
            logger.info(f"Syncing {len(groups_data)} groups to GraphDB (first group sample: {groups_data[0] if groups_data else 'none'})")
            
            # Sync to GraphDB
            self.graph_db.sync_groups(groups_data, self.tenant_id)
            logger.info(f"Synced {len(groups_data)} groups to GraphDB")
            
            # Update progress in metadata
            if self.sync_id:
                await self.meta_ops.update_sync_record(self.sync_id, {
                    "groups_count": len(groups_data),
                    "progress_percentage": 33
                })
            
        except Exception as e:
            logger.error(f"Error syncing groups: {e}", exc_info=True)
            raise
    
    async def _sync_applications(self, okta_client) -> None:
        """Fetch applications from Okta and sync to GraphDB"""
        logger.info("Syncing applications from Okta API...")
        
        try:
            # Fetch all applications from Okta (already transformed with 'okta_id' field)
            apps_data = await okta_client.list_applications()
            
            if not apps_data:
                logger.warning("No applications found in Okta")
                return
            
            logger.info(f"Retrieved {len(apps_data)} applications from Okta")
            
            # Filter out None entries (failed transformations)
            valid_apps = [app for app in apps_data if app is not None and app.get('okta_id')]
            
            if len(valid_apps) < len(apps_data):
                skipped = len(apps_data) - len(valid_apps)
                logger.warning(f"Skipped {skipped} applications with missing or invalid data")
            
            if not valid_apps:
                logger.warning("No valid applications after filtering")
                return
            
            # Apps are already in the correct format from the client
            # Just sync them directly to GraphDB
            self.graph_db.sync_applications(valid_apps, self.tenant_id)
            logger.info(f"Synced {len(valid_apps)} applications to GraphDB")
            
            # Update progress in metadata
            if self.sync_id:
                await self.meta_ops.update_sync_record(self.sync_id, {
                    "apps_count": len(valid_apps),
                    "progress_percentage": 66
                })
            
        except Exception as e:
            logger.error(f"Error syncing applications: {e}", exc_info=True)
            raise
    
    async def _sync_policies(self, okta_client) -> None:
        """Fetch policies from Okta and sync to GraphDB"""
        logger.info("Syncing policies from Okta API...")
        
        try:
            # Fetch all policies from Okta
            policies_data = await okta_client.list_policies()
            
            if not policies_data:
                logger.warning("No policies found in Okta")
                return
            
            logger.info(f"Retrieved {len(policies_data)} policies from Okta")
            
            # Filter out None entries (failed transformations)
            valid_policies = [p for p in policies_data if p is not None and p.get('okta_id')]
            
            if len(valid_policies) < len(policies_data):
                skipped = len(policies_data) - len(valid_policies)
                logger.warning(f"Skipped {skipped} policies with missing or invalid data")
            
            if not valid_policies:
                logger.warning("No valid policies after filtering")
                return
            
            # Sync policies to GraphDB
            self.graph_db.sync_policies(valid_policies, self.tenant_id)
            logger.info(f"Synced {len(valid_policies)} policies to GraphDB")
            
            # Update progress in metadata
            if self.sync_id:
                await self.meta_ops.update_sync_record(self.sync_id, {
                    "policies_count": len(valid_policies),
                    "progress_percentage": 90
                })
            
        except Exception as e:
            logger.error(f"Error syncing policies: {e}", exc_info=True)
            raise
    
    async def _sync_devices(self, okta_client) -> None:
        """Fetch devices from Okta and sync to GraphDB"""
        logger.info("Syncing devices from Okta API...")
        
        try:
            # Fetch all devices from Okta
            devices_data = await okta_client.list_devices()
            
            if not devices_data:
                logger.warning("No devices found in Okta")
                return
            
            logger.info(f"Retrieved {len(devices_data)} devices from Okta")
            
            # Filter out None entries (failed transformations)
            valid_devices = [d for d in devices_data if d is not None and d.get('okta_id')]
            
            if len(valid_devices) < len(devices_data):
                skipped = len(devices_data) - len(valid_devices)
                logger.warning(f"Skipped {skipped} devices with missing or invalid data")
            
            if not valid_devices:
                logger.warning("No valid devices after filtering")
                return
            
            # Sync devices to GraphDB
            self.graph_db.sync_devices(valid_devices, self.tenant_id)
            logger.info(f"Synced {len(valid_devices)} devices to GraphDB")
            
            # Update progress in metadata
            if self.sync_id:
                await self.meta_ops.update_sync_record(self.sync_id, {
                    "devices_count": len(valid_devices),
                    "progress_percentage": 83
                })
            
        except Exception as e:
            logger.error(f"Error syncing devices: {e}", exc_info=True)
            raise
    
    async def _sync_users(self, okta_client) -> None:
        """
        Fetch users from Okta and sync to GraphDB with TRUE STREAMING.
        
        Uses processor callback to write users to GraphDB as they arrive from API.
        Zero memory accumulation - each batch of 11 users is written immediately.
        """
        logger.info("Starting TRUE STREAMING user sync from Okta API to GraphDB...")
        
        # Track progress for metadata updates
        self.user_sync_count = 0
        self.user_sync_errors = 0
        
        # Define streaming processor callback
        async def stream_users_to_graphdb(user_batch: List[Dict]) -> None:
            """
            Callback invoked by client for each batch of users fetched from API.
            Writes batch immediately to GraphDB (streaming pattern).
            """
            # Filter out None entries and users without IDs
            valid_batch = [u for u in user_batch if u is not None and u.get('okta_id')]
            
            if len(valid_batch) < len(user_batch):
                skipped = len(user_batch) - len(valid_batch)
                self.user_sync_errors += skipped
                logger.debug(f"Skipped {skipped} users with missing/invalid data in batch")
            
            if valid_batch:
                # Write this batch to GraphDB immediately (no accumulation!)
                self.graph_db.sync_users(valid_batch, self.tenant_id)
                self.user_sync_count += len(valid_batch)
                
                # Update metadata after EVERY batch so frontend polling sees real-time progress
                if self.sync_id:
                    await self.meta_ops.update_sync_record(self.sync_id, {
                        "users_count": self.user_sync_count,
                        "progress_percentage": min(33 + int((self.user_sync_count / 500) * 40), 73)  # 33-73% for users phase
                    })
                
                # Log progress every 50 users to avoid log spam
                if self.user_sync_count % 50 == 0:
                    logger.info(f"Streamed {self.user_sync_count} users to GraphDB so far...")
        
        try:
            # Stream users with callback - returns count of processed users
            total_processed = await okta_client.list_users(processor_func=stream_users_to_graphdb)
            
            logger.info(f"✅ Streaming sync complete: {self.user_sync_count} users written to GraphDB")
            
            if self.user_sync_errors > 0:
                logger.warning(f"⚠️  {self.user_sync_errors} users skipped due to missing/invalid data")
            
            # Update progress in metadata
            if self.sync_id:
                await self.meta_ops.update_sync_record(self.sync_id, {
                    "users_count": self.user_sync_count,
                    "progress_percentage": 75
                })
            
        except Exception as e:
            logger.error(f"Error syncing users: {e}", exc_info=True)
            raise
    
    async def _sync_user_relationships(self, okta_client, users_data: List[Dict]) -> None:
        """
        Sync user relationships (group memberships, app assignments)
        
        Args:
            okta_client: Okta client wrapper
            users_data: Transformed user data (already has 'okta_id' field)
        """
        logger.info("Syncing user relationships...")
        
        total_users = len(users_data)
        for idx, user in enumerate(users_data, 1):
            try:
                user_id = user.get('okta_id')  # Changed from 'id' to 'okta_id'
                
                if not user_id:
                    logger.warning(f"Skipping relationships for user without ID at index {idx}")
                    continue
                
                # Check cancellation periodically
                if idx % 10 == 0 and self.cancellation_flag and self.cancellation_flag.is_set():
                    raise asyncio.CancelledError(f"Sync cancelled during user relationships at {idx}/{total_users}")
                
                # Fetch and sync group memberships
                groups = await okta_client.get_user_groups(user_id)
                if groups:
                    # Sync relationships using existing method in sync_operations
                    # We'll need to pass this data to the sync_users method
                    pass  # TODO: Implement relationship sync in next iteration
                
                if idx % 50 == 0:
                    logger.debug(f"Synced relationships for {idx}/{total_users} users")
                    
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Error syncing relationships for user {user.get('id')}: {e}")
                # Continue with other users
                continue
        
        logger.info(f"Completed relationship sync for {total_users} users")
    
    def _parse_okta_timestamp(self, timestamp_str: Optional[str]) -> Optional[datetime]:
        """
        Parse Okta timestamp string to datetime object
        
        Args:
            timestamp_str: ISO 8601 timestamp string from Okta
            
        Returns:
            datetime object or None
        """
        if not timestamp_str:
            return None
        
        try:
            # Okta uses ISO 8601 format: "2024-01-15T10:30:00.000Z"
            return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        except Exception as e:
            logger.warning(f"Failed to parse timestamp '{timestamp_str}': {e}")
            return None
    
    def _create_sync_metadata(self, counts: dict) -> None:
        """
        DEPRECATED: Sync metadata is now tracked in SQLite (okta_meta.db) instead.
        
        GraphDB can provide counts via Cypher queries:
        - MATCH (u:User) RETURN count(u) AS user_count
        - MATCH (g:OktaGroup) RETURN count(g) AS group_count
        - etc.
        
        This method is kept for backward compatibility but does nothing.
        """
        # No-op: Metadata tracking moved to SQLite
        pass
    
    def close(self):
        """Close GraphDB connection"""
        if self.graph_db:
            self.graph_db.close()
