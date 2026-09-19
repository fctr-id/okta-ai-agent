"""
Sync Engine for Okta Integration

Orchestrates synchronization of Okta entities:
- Users with factors and relationships
- Groups with memberships
- Applications and policies
- Sync history tracking
- Error handling and logging

Core Components:
- SyncOrchestrator: Main sync coordinator
- Sync History: Tracks sync operations
- Relationship Processing: Handles entity relationships
"""

from typing import List, Optional, Type, TypeVar, Any, Dict, Callable
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.okta.client.client import OktaClientWrapper
from src.core.okta.sync.operations import DatabaseOperations
from src.core.okta.sync.models import (
    User, Group, Authenticator, Application, Policy, Base, 
    SyncHistory, SyncStatus, UserFactor, Device,
    user_application_assignments, group_application_assignments,
    user_group_memberships
)
from src.utils.logging import logger
import asyncio
from sqlalchemy import insert, text, select, and_, bindparam
from datetime import datetime
import time

ModelType = TypeVar('ModelType', bound=Base)


def format_duration(seconds: float) -> str:
    """Format duration in seconds to human-readable string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m {secs:.1f}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"

class SyncOrchestrator:
    """
    Orchestrates Okta entity synchronization with database.
    
    Features:
    - Incremental sync support
    - Relationship handling
    - Sync history tracking
    - Error recovery
    """    
    def __init__(self, tenant_id: str, db: DatabaseOperations = None, cancellation_flag=None):
        self.tenant_id = tenant_id
        self.db = db or DatabaseOperations()
        self._initialized = False
        self.cancellation_flag = cancellation_flag
        self._pending_group_relationships: List[Dict[str, Any]] = []
        self._pending_application_policy_links: List[Dict[str, Any]] = []

    async def _initialize(self) -> None:
        if not self._initialized:
            await self.db.init_db()
            self._initialized = True

    async def _create_sync_history(
        self,
        session: AsyncSession,
        entity_type: str,
        last_sync: Optional[datetime]
    ) -> SyncHistory:
        """
        Create sync history record for tracking operation.
        
        Args:
            session: Database session
            entity_type: Entity being synced (User, Group etc)
            last_sync: Previous successful sync time
        """        
        sync_history = SyncHistory(
            tenant_id=self.tenant_id,
            entity_type=entity_type,
            last_successful_sync=last_sync,
            status=SyncStatus.STARTED
        )
        session.add(sync_history)
        await session.commit()
        return sync_history

    async def _update_sync_history(
        self,
        session: AsyncSession,
        sync_history: SyncHistory,
        status: SyncStatus,
        records_processed: int = 0,
        error_message: str = None
    ):
        sync_history.status = status
        # Set both end_time and sync_end_time for compatibility
        now = datetime.now(timezone.utc)
        sync_history.end_time = now
        sync_history.sync_end_time = now
        sync_history.records_processed = records_processed
        # Set both error_details and error_message
        if error_message:
            sync_history.error_details = error_message
            sync_history.error_message = error_message
        await session.commit()

    def _get_authenticator_name(self, factor_type: str, provider: str) -> str:
        """
        Map factor type and provider to authenticator name.
        Based on your actual Okta authenticator data.
        """
        authenticator_mappings = {
            # Okta Verify handles multiple factor types
            ('signed_nonce', 'OKTA'): 'Okta FastPass',      # FastPass
            ('push', 'OKTA'): 'Okta Verify',               # Push notifications  
            ('token:software:totp', 'OKTA'): 'Okta Verify', # TOTP in Okta Verify
            
            # Google Authenticator
            ('token:software:totp', 'GOOGLE'): 'Google Authenticator',
            
            # Other authenticators
            ('sms', 'OKTA'): 'Phone',
            ('email', 'OKTA'): 'Email',
            ('password', 'OKTA'): 'Password',
            ('security_key', 'OKTA'): 'Security Key or Biometric',
            ('security_question', 'OKTA'): 'Security Question',
        }
        
        mapping_key = (factor_type, provider)
        return authenticator_mappings.get(mapping_key, f"Unknown ({factor_type}, {provider})")

    async def _process_user_relationships(
        self,
        session: AsyncSession,
        user_data: Dict,
    ) -> None:
        """Process all user relationships with upsert handling plus removal of
        memberships/factors no longer present in Okta for this user."""
        try:
            user_okta_id = user_data['okta_id']
            now = datetime.now(timezone.utc)
            logger.debug(f"Starting relationship sync for user {user_okta_id}")

            # Handle group memberships with upsert
            group_memberships = user_data.pop('group_memberships', [])
            if group_memberships:
                for membership in group_memberships:
                    stmt = text("""
                        INSERT INTO user_group_memberships
                        (tenant_id, user_okta_id, group_okta_id, created_at, updated_at)
                        VALUES (:tenant_id, :user_okta_id, :group_okta_id, :created_at, :updated_at)
                        ON CONFLICT (tenant_id, user_okta_id, group_okta_id)
                        DO UPDATE SET
                            updated_at = excluded.updated_at
                    """)

                    await session.execute(stmt, {
                        'tenant_id': self.tenant_id,
                        'user_okta_id': user_okta_id,
                        'group_okta_id': membership['group_okta_id'],
                        'created_at': now,
                        'updated_at': now
                    })

            # Remove memberships for this user that no longer exist in Okta
            current_group_ids = [str(m['group_okta_id']) for m in group_memberships]
            if current_group_ids:
                delete_stale_memberships = text("""
                    DELETE FROM user_group_memberships
                    WHERE tenant_id = :tenant_id
                    AND user_okta_id = :user_okta_id
                    AND group_okta_id NOT IN :current_group_ids
                """).bindparams(bindparam('current_group_ids', expanding=True))
                await session.execute(delete_stale_memberships, {
                    'tenant_id': self.tenant_id,
                    'user_okta_id': user_okta_id,
                    'current_group_ids': current_group_ids
                })
            else:
                await session.execute(text("""
                    DELETE FROM user_group_memberships
                    WHERE tenant_id = :tenant_id
                    AND user_okta_id = :user_okta_id
                """), {'tenant_id': self.tenant_id, 'user_okta_id': user_okta_id})

            # Handle factors with upsert
            factors = user_data.pop('factors', [])
            if factors:
                for factor in factors:
                    authenticator_name = self._get_authenticator_name(
                        factor.get('factor_type'), 
                        factor.get('provider')
                    )                    
                    stmt = text("""
                        INSERT INTO user_factors
                        (tenant_id, user_okta_id, okta_id, factor_type, provider, status,
                        authenticator_name, email, phone_number, device_type, device_name, platform,
                        created_at, last_updated_at, updated_at)
                        VALUES (
                            :tenant_id, :user_okta_id, :okta_id, :factor_type, :provider, :status,
                            :authenticator_name, :email, :phone_number, :device_type, :device_name, :platform,
                            :created_at, :last_updated_at, :updated_at
                        )
                        ON CONFLICT (tenant_id, user_okta_id, okta_id) 
                        DO UPDATE SET
                            factor_type = excluded.factor_type,
                            provider = excluded.provider,
                            status = excluded.status,
                            authenticator_name = excluded.authenticator_name,
                            email = excluded.email,
                            phone_number = excluded.phone_number,
                            device_type = excluded.device_type,
                            device_name = excluded.device_name,
                            platform = excluded.platform,
                            last_updated_at = excluded.last_updated_at,
                            updated_at = excluded.updated_at
                    """)
                    
                    now = datetime.now(timezone.utc)
                    await session.execute(stmt, {
                        'tenant_id': self.tenant_id,
                        'user_okta_id': user_okta_id,
                        'okta_id': factor['okta_id'],
                        'factor_type': factor['factor_type'],
                        'provider': factor['provider'],
                        'status': factor['status'],
                        'authenticator_name': authenticator_name,
                        'email': factor.get('email'),
                        'phone_number': factor.get('phone_number'),
                        'device_type': factor.get('device_type'),
                        'device_name': factor.get('device_name'),
                        'platform': factor.get('platform'),
                        'created_at': factor.get('created_at'),
                        'last_updated_at': factor.get('last_updated_at'),
                        'updated_at': now
                    })

            # Remove factors for this user that no longer exist in Okta
            current_factor_ids = [str(f['okta_id']) for f in factors]
            if current_factor_ids:
                delete_stale_factors = text("""
                    DELETE FROM user_factors
                    WHERE tenant_id = :tenant_id
                    AND user_okta_id = :user_okta_id
                    AND okta_id NOT IN :current_factor_ids
                """).bindparams(bindparam('current_factor_ids', expanding=True))
                await session.execute(delete_stale_factors, {
                    'tenant_id': self.tenant_id,
                    'user_okta_id': user_okta_id,
                    'current_factor_ids': current_factor_ids
                })
            else:
                await session.execute(text("""
                    DELETE FROM user_factors
                    WHERE tenant_id = :tenant_id
                    AND user_okta_id = :user_okta_id
                """), {'tenant_id': self.tenant_id, 'user_okta_id': user_okta_id})

            logger.debug(f"Completed relationship sync for user {user_okta_id}")
                
        except Exception as e:
            logger.error(f"Error processing user relationships for {user_okta_id}: {str(e)}")
            raise

    async def _process_group_relationships(
        self,
        session: AsyncSession,
        group_data: Dict,
    ) -> None:
        """
        Process group-to-application assignments using upserts, then remove
        assignments for this group that are no longer present in Okta.
        Avoids the previous delete-all-then-reinsert pattern which was slow
        on subsequent syncs.
        """
        try:
            # Get current assignments from Okta response
            if 'applications' not in group_data:
                return  # Not fetched is different from a confirmed empty snapshot.
            current_app_assignments = group_data.pop('applications')
            current_app_ids = [str(a['application_okta_id']) for a in current_app_assignments]
            group_okta_id = str(group_data['okta_id'])
            now = datetime.now(timezone.utc)

            # Upsert current assignments
            for assignment in current_app_assignments:
                upsert_stmt = text("""
                    INSERT INTO group_application_assignments
                    (tenant_id, group_okta_id, application_okta_id, assignment_id, created_at, updated_at)
                    VALUES (:tenant_id, :group_okta_id, :application_okta_id, :assignment_id, :created_at, :updated_at)
                    ON CONFLICT (tenant_id, group_okta_id, application_okta_id)
                    DO UPDATE SET
                        assignment_id = excluded.assignment_id,
                        updated_at = excluded.updated_at
                """)

                await session.execute(upsert_stmt, {
                    'tenant_id': str(self.tenant_id),
                    'group_okta_id': str(assignment['group_okta_id']),
                    'application_okta_id': str(assignment['application_okta_id']),
                    'assignment_id': str(assignment['assignment_id']),
                    'created_at': now,
                    'updated_at': now
                })

            # Remove assignments for this group that no longer exist in Okta
            if current_app_ids:
                delete_stale_stmt = text("""
                    DELETE FROM group_application_assignments
                    WHERE tenant_id = :tenant_id
                    AND group_okta_id = :group_okta_id
                    AND application_okta_id NOT IN :current_app_ids
                """).bindparams(bindparam('current_app_ids', expanding=True))

                await session.execute(delete_stale_stmt, {
                    'tenant_id': str(self.tenant_id),
                    'group_okta_id': group_okta_id,
                    'current_app_ids': current_app_ids
                })
            else:
                # Group has no app assignments left in Okta - remove all for this group
                delete_all_stmt = text("""
                    DELETE FROM group_application_assignments
                    WHERE tenant_id = :tenant_id
                    AND group_okta_id = :group_okta_id
                """)
                await session.execute(delete_all_stmt, {
                    'tenant_id': str(self.tenant_id),
                    'group_okta_id': group_okta_id
                })

            await session.commit()
            logger.debug(f"Processed {len(current_app_assignments)} assignments for group {group_okta_id}")

        except Exception as e:
            logger.error(f"Error processing group relationships: {str(e)}")
            raise

    async def _flush_group_relationships(self) -> None:
        """Replay staged group-to-application assignments after applications exist."""
        if not self._pending_group_relationships:
            return

        try:
            async with self.db.get_session() as session:
                for relationship_payload in self._pending_group_relationships:
                    await self._process_group_relationships(session, relationship_payload)

            logger.debug(
                f"Processed staged application assignments for {len(self._pending_group_relationships)} groups"
            )
            self._pending_group_relationships = []
        except Exception:
            self._pending_group_relationships = []
            raise

    async def _flush_application_policy_links(self) -> None:
        """Replay staged application-to-policy links after policies exist."""
        if not self._pending_application_policy_links:
            return

        try:
            async with self.db.get_session() as session:
                for policy_link in self._pending_application_policy_links:
                    result = await session.execute(
                        text("""
                            UPDATE applications
                            SET policy_id = :policy_id,
                                updated_at = :updated_at
                            WHERE tenant_id = :tenant_id
                            AND okta_id = :application_okta_id
                            AND (:policy_id IS NULL OR EXISTS (
                                SELECT 1
                                FROM policies
                                WHERE tenant_id = :tenant_id
                                AND okta_id = :policy_id
                            ))
                        """),
                        {
                            'tenant_id': str(self.tenant_id),
                            'application_okta_id': policy_link['application_okta_id'],
                            'policy_id': policy_link['policy_id'],
                            'updated_at': datetime.now(timezone.utc),
                        }
                    )

                    if result.rowcount == 0:
                        raise RuntimeError(
                            f"Cannot reconcile application {policy_link['application_okta_id']} "
                            f"with policy {policy_link['policy_id']}: application or policy missing"
                        )

                await session.commit()

            logger.debug(
                f"Processed staged policy links for {len(self._pending_application_policy_links)} applications"
            )
            self._pending_application_policy_links = []
        except Exception:
            self._pending_application_policy_links = []
            raise

    async def _process_app_relationships(
        self,
        session: AsyncSession,
        app_data: Dict,
    ) -> None:
        """
        Process application user assignments using batched upserts, then remove
        assignments for this app that are no longer present in Okta.
        Avoids the previous delete-all-then-reinsert pattern which was slow
        on subsequent syncs with large apps (10K+ users).
        """
        try:
            # Get current assignments from Okta response
            user_assignments = app_data.pop('user_assignments', [])
            app_okta_id = str(app_data['okta_id'])
            now = datetime.now(timezone.utc)

            # Upsert current assignments with batched execution for performance
            if user_assignments:
                BATCH_SIZE = 1000

                upsert_stmt = text("""
                    INSERT INTO user_application_assignments
                    (tenant_id, user_okta_id, application_okta_id,
                     assignment_id, assignment_type, group_name, group_okta_id,
                     assignment_status, credentials_setup, hidden,
                     created_at, updated_at)
                    VALUES (:tenant_id, :user_okta_id, :application_okta_id,
                            :assignment_id, :assignment_type, :group_name, :group_okta_id,
                            :assignment_status, :credentials_setup, :hidden,
                            :created_at, :updated_at)
                    ON CONFLICT (tenant_id, user_okta_id, application_okta_id)
                    DO UPDATE SET
                        assignment_id = excluded.assignment_id,
                        assignment_type = excluded.assignment_type,
                        group_name = excluded.group_name,
                        group_okta_id = excluded.group_okta_id,
                        assignment_status = excluded.assignment_status,
                        credentials_setup = excluded.credentials_setup,
                        hidden = excluded.hidden,
                        updated_at = excluded.updated_at
                """)

                total_upserted = 0
                for i in range(0, len(user_assignments), BATCH_SIZE):
                    batch = user_assignments[i:i + BATCH_SIZE]

                    batch_params = []
                    for assignment in batch:
                        batch_params.append({
                            'tenant_id': str(self.tenant_id),
                            'user_okta_id': str(assignment['user_okta_id']),
                            'application_okta_id': app_okta_id,
                            'assignment_id': str(assignment['assignment_id']),
                            'assignment_type': str(assignment['assignment_type']),
                            'group_name': assignment.get('group_name'),
                            'group_okta_id': assignment.get('group_okta_id'),
                            'assignment_status': str(assignment['status']),
                            'credentials_setup': assignment.get('credentials_setup', False),
                            'hidden': assignment.get('hidden', False),
                            'created_at': assignment.get('created_at', now),
                            'updated_at': now
                        })

                    await session.execute(upsert_stmt, batch_params)
                    total_upserted += len(batch)

                    if len(user_assignments) > BATCH_SIZE:
                        logger.debug(f"Upserted batch {i//BATCH_SIZE + 1}: {len(batch)} assignments for app {app_okta_id}")

            # Remove assignments for this app that no longer exist in Okta
            current_user_ids = [str(a['user_okta_id']) for a in user_assignments]
            if current_user_ids:
                delete_stale_stmt = text("""
                    DELETE FROM user_application_assignments
                    WHERE tenant_id = :tenant_id
                    AND application_okta_id = :app_okta_id
                    AND user_okta_id NOT IN :current_user_ids
                """).bindparams(bindparam('current_user_ids', expanding=True))

                await session.execute(delete_stale_stmt, {
                    'tenant_id': str(self.tenant_id),
                    'app_okta_id': app_okta_id,
                    'current_user_ids': current_user_ids
                })
            else:
                # App has no user assignments left in Okta - remove all for this app
                delete_all_stmt = text("""
                    DELETE FROM user_application_assignments
                    WHERE tenant_id = :tenant_id
                    AND application_okta_id = :app_okta_id
                """)
                await session.execute(delete_all_stmt, {
                    'tenant_id': str(self.tenant_id),
                    'app_okta_id': app_okta_id
                })

            logger.debug(f"Processed {len(user_assignments)} assignments for app {app_okta_id}")

        except Exception as e:
            logger.error(f"Error processing app relationships: {str(e)}")
            raise
        
    async def _delete_stale_entity_data(self, session: AsyncSession, model: Type[ModelType], sync_started_at: datetime) -> None:
        """
        Delete rows for this entity type that were not updated during the
        current sync (i.e. their last_synced_at predates the sync start).
        These represent entities removed in Okta since the previous sync.

        This replaces the old wipe-everything-then-reinsert approach with a
        single indexed delete per entity type. Related child rows are removed
        via FK cascade (ondelete='CASCADE') or explicitly where no FK exists.
        """
        try:
            table = model.__tablename__

            if model == User:
                # Clean user-related child rows for stale users first (no FK on user_factors)
                await session.execute(text("""
                    DELETE FROM user_factors
                    WHERE tenant_id = :tenant_id
                    AND user_okta_id IN (
                        SELECT okta_id FROM users
                        WHERE tenant_id = :tenant_id
                        AND (last_synced_at IS NULL OR last_synced_at < :sync_started_at)
                    )
                """), {'tenant_id': self.tenant_id, 'sync_started_at': sync_started_at})

            elif model == Device:
                await session.execute(text("""
                    DELETE FROM user_devices
                    WHERE tenant_id = :tenant_id
                    AND device_okta_id IN (
                        SELECT okta_id FROM devices
                        WHERE tenant_id = :tenant_id
                        AND (last_synced_at IS NULL OR last_synced_at < :sync_started_at)
                    )
                """), {'tenant_id': self.tenant_id, 'sync_started_at': sync_started_at})

            # Delete the stale main entity rows (relationship join tables have
            # FK ondelete='CASCADE' so they are cleaned up automatically)
            result = await session.execute(text(f"""
                DELETE FROM {table}
                WHERE tenant_id = :tenant_id
                AND (last_synced_at IS NULL OR last_synced_at < :sync_started_at)
            """), {'tenant_id': self.tenant_id, 'sync_started_at': sync_started_at})

            await session.commit()
            deleted = result.rowcount if result.rowcount is not None else 0
            if deleted:
                logger.info(f"Removed {deleted} stale {model.__name__} records no longer present in Okta")
            else:
                logger.debug(f"No stale {model.__name__} records to remove")

        except Exception as e:
            logger.error(f"Error removing stale {model.__name__} data: {str(e)}")
            raise
        
        
    async def sync_model_streaming(self, model: Type[ModelType], list_method: Callable, batch_size: int = 100) -> None:
        """Sync model with direct API-to-DB streaming (no memory accumulation).

        Uses upserts instead of wiping the table first, then reconciles stale
        rows (records no longer present in Okta) at the end via a single
        timestamp-based delete. This avoids expensive full-table deletes on
        every sync while keeping the local copy accurate.
        """
        import time
        start_time = time.time()
        sync_started_at = datetime.now(timezone.utc)
        logger.info(f"Starting sync for {model.__name__}")
        try:
            # Make sure the database operations object has the tenant_id set
            self.db.tenant_id = self.tenant_id
            
            # Get sync history ID for updates
            async with self.db.get_session() as session:
                # Find active sync
                from src.core.okta.sync.models import SyncHistory, SyncStatus
                stmt = select(SyncHistory).where(
                    and_(
                        SyncHistory.tenant_id == self.tenant_id,
                        SyncHistory.status.in_([SyncStatus.RUNNING, SyncStatus.IDLE])
                    )
                ).order_by(SyncHistory.start_time.desc()).limit(1)
                
                result = await session.execute(stmt)
                active_sync = result.scalars().first()
                
                if not active_sync:
                    raise RuntimeError("No active sync record found for updates")
                    
                sync_id = active_sync.id
                
                try:
                    # Create processor function for handling batches directly from API to DB
                    total_records = 0
                    
                    async def process_batch_directly(batch_data):
                        nonlocal total_records
                        
                        if not batch_data:
                            return
                        
                        # Process this batch immediately to DB
                        batch_count = await self._process_batch_to_db(session, model, batch_data)
                        
                        # Update total count
                        total_records += batch_count
                        
                        # Update entity count in the sync history record
                        sync_history = await session.get(SyncHistory, sync_id)
                        if sync_history:
                            # Update the appropriate counter based on model type
                            if model.__name__ == 'User':
                                sync_history.users_count = total_records
                            elif model.__name__ == 'Group':
                                sync_history.groups_count = total_records
                            elif model.__name__ == 'Application':
                                sync_history.apps_count = total_records
                            elif model.__name__ == 'Policy':
                                sync_history.policies_count = total_records
                            elif model.__name__ == 'Device': 
                                sync_history.devices_count = total_records
                                
                        # Entity rows, relationships and polling counters become
                        # visible together after each bounded batch.
                        await session.commit()
                        
                        logger.info(f"Processed {batch_count} {model.__name__} records, total: {total_records}")
                    
                    # Call list method with direct processor function 
                    await list_method(processor_func=process_batch_directly)

                    if self.cancellation_flag and self.cancellation_flag.is_set():
                        raise asyncio.CancelledError("Sync cancelled before reconciliation")

                    # Reconcile: remove rows that were not touched during this sync
                    # (i.e. entities deleted in Okta since the last sync)
                    await self._delete_stale_entity_data(session, model, sync_started_at)

                    duration = time.time() - start_time
                    logger.info(f"Processed {total_records} {model.__name__} records in {format_duration(duration)}")
                    
                except Exception as e:
                    logger.error(f"Error during {model.__name__} sync: {str(e)}")
                    raise
                    
        except Exception as e:
            logger.error(f"Sync error for {model.__name__}: {str(e)}")
            raise      

    async def run_sync(self) -> None:
        """
        Run entity syncs in sequential order to manage dependencies.
        
        Flow:
        1. Groups first (no dependencies)
        2. Users second (depends on groups for memberships)
        3. Applications third (depends on users for FK constraint on user_application_assignments)
        4. Authenticators fourth (no dependencies)
        5. Devices fifth (conditional sync, no dependencies) 
        6. Policies last (depends on apps)
        
        CRITICAL: Users MUST be synced before Applications because _process_app_relationships()
        inserts into user_application_assignments table which has FK constraint on users.okta_id.
        
        Supports cancellation via cancellation_flag attribute.
        """
        try:
            import time
            overall_start_time = time.time()
            await self._initialize()
            self._pending_group_relationships = []
            self._pending_application_policy_links = []
            
            # Pass the cancellation flag to the OktaClientWrapper
            async with OktaClientWrapper(self.tenant_id, self.cancellation_flag) as okta:
                logger.info(f"Starting sync in dependency order for tenant {self.tenant_id}")
                
                # Check cancellation before each major step
                # 1. Groups first (no dependencies)
                if not self.cancellation_flag or (hasattr(self.cancellation_flag, 'is_set') and not self.cancellation_flag.is_set()):
                    logger.info("Step 1: Syncing Groups")
                    await self.sync_model_streaming(Group, okta.list_groups)
                else:
                    logger.info("Sync cancelled - skipping Groups")
                    return
                    
                # 2. Users second (depends on groups, must be before apps for FK constraint)
                if not self.cancellation_flag or (hasattr(self.cancellation_flag, 'is_set') and not self.cancellation_flag.is_set()):
                    logger.info("Step 2: Syncing Users")
                    await self.sync_model_streaming(User, okta.list_users)
                else:
                    logger.info("Sync cancelled - skipping remaining steps")
                    return
    
                # 3. Applications third (depends on users for user_application_assignments FK)
                if not self.cancellation_flag or (hasattr(self.cancellation_flag, 'is_set') and not self.cancellation_flag.is_set()):
                    logger.info("Step 3: Syncing Applications")
                    await self.sync_model_streaming(Application, okta.list_applications)
                    await self._flush_group_relationships()
                else:
                    logger.info("Sync cancelled - skipping remaining steps")
                    return
                
                # 4. Authenticators fourth (no dependencies)
                if not self.cancellation_flag or (hasattr(self.cancellation_flag, 'is_set') and not self.cancellation_flag.is_set()):
                    logger.info("Step 4: Syncing Authenticators")
                    await self.sync_model_streaming(Authenticator, okta.list_authenticators)
                else:
                    logger.info("Sync cancelled - skipping remaining steps")
                    return                
                
                # 5. Devices fifth (conditional sync)
                if not self.cancellation_flag or (hasattr(self.cancellation_flag, 'is_set') and not self.cancellation_flag.is_set()):
                    # Check if device sync is enabled
                    from src.config.settings import settings
                    if settings.SYNC_OKTA_DEVICES:
                        logger.info("Step 5: Syncing Devices")
                        await self.sync_model_streaming(Device, okta.list_devices)
                    else:
                        logger.info("Step 5: Skipping Devices (SYNC_OKTA_DEVICES=false)")
                else:
                    logger.info("Sync cancelled - skipping remaining steps")
                    return                
    
    
                # 6. Policies last (depends on apps)
                if not self.cancellation_flag or (hasattr(self.cancellation_flag, 'is_set') and not self.cancellation_flag.is_set()):
                    logger.info("Step 6: Syncing Policies")
                    await self.sync_model_streaming(Policy, okta.list_policies)
                    await self._flush_application_policy_links()
                    
                    # Check if there were authentication errors
                    if okta.auth_errors:
                        error_msg = "Okta authentication failed: " + "; ".join(okta.auth_errors[:3])  # Limit to first 3 errors
                        logger.error(f"Sync completed with auth errors: {error_msg}")
                        raise Exception(error_msg)
                    
                    # Log total duration
                    total_duration = time.time() - overall_start_time
                    logger.info(f"Sync completed for tenant {self.tenant_id} in {format_duration(total_duration)}")
                else:
                    logger.info("Sync cancelled - skipping remaining steps")
                    return
                
        except asyncio.CancelledError:
            duration = time.time() - overall_start_time
            logger.info(f"Sync for tenant {self.tenant_id} was cancelled after {format_duration(duration)}")
            raise
        except Exception as e:
            logger.error(f"Sync orchestration error: {str(e)}")
            raise
    

    async def _process_batch_to_db(self, session: AsyncSession, model: Type[ModelType], batch: List[Dict]) -> int:
        """
        Process a batch of records directly to database.
        
        Args:
            session: Database session
            model: SQLAlchemy model class
            batch: List of record dictionaries
            
        Returns:
            Number of records processed
        """
        if not batch:
            return 0
            
        try:
            if model == User:
                relationship_payloads = []
                for record in batch:
                    relationship_payloads.append({
                        'okta_id': record['okta_id'],
                        'group_memberships': record.pop('group_memberships', []),
                        'factors': record.pop('factors', []),
                    })

                await self.db.bulk_upsert(session, model, batch, self.tenant_id)
                await session.flush()

                for relationship_payload in relationship_payloads:
                    await self._process_user_relationships(session, relationship_payload)

                return len(batch)

            if model == Group:
                for record in batch:
                    if 'applications' in record:
                        self._pending_group_relationships.append({
                            'okta_id': record['okta_id'],
                            'applications': record.pop('applications'),
                        })

                await self.db.bulk_upsert(session, model, batch, self.tenant_id)
                return len(batch)

            if model == Application:
                relationship_payloads = []
                for record in batch:
                    if 'policy_id' in record:
                        policy_id = record.pop('policy_id')
                        self._pending_application_policy_links.append({
                            'application_okta_id': record['okta_id'],
                            'policy_id': str(policy_id) if policy_id is not None else None,
                        })

                    relationship_payloads.append({
                        'okta_id': record['okta_id'],
                        'user_assignments': record.pop('user_assignments', []),
                    })

                await self.db.bulk_upsert(session, model, batch, self.tenant_id)
                await session.flush()

                for relationship_payload in relationship_payloads:
                    await self._process_app_relationships(session, relationship_payload)

                return len(batch)

            # Process relationships for users and groups
            for record in batch:
                if model == Application:
                    await self._process_app_relationships(session, record)                    
    
            # Process main records
            await self.db.bulk_upsert(session, model, batch, self.tenant_id)
            
            # Return batch count
            return len(batch)
            
        except Exception as e:
            logger.error(f"Error processing batch of {model.__name__}: {str(e)}")
            raise
