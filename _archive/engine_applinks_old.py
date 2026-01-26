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
from sqlalchemy import insert, text, select, and_
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
        """Process all user relationships with upsert handling"""
        try:
            user_okta_id = user_data['okta_id']
            logger.debug(f"Starting relationship sync for user {user_okta_id}")
    
            # Handle app assignments with upsert
            app_links = user_data.pop('app_links', [])
            if app_links:
                for link in app_links:
                    stmt = text("""
                        INSERT INTO user_application_assignments 
                        (tenant_id, user_okta_id, application_okta_id, assignment_id, 
                        app_instance_id, credentials_setup, hidden, created_at, updated_at)
                        VALUES (:tenant_id, :user_okta_id, :application_okta_id, :assignment_id,
                                :app_instance_id, :credentials_setup, :hidden, :created_at, :updated_at)
                        ON CONFLICT (tenant_id, user_okta_id, application_okta_id) 
                        DO UPDATE SET
                            assignment_id = excluded.assignment_id,
                            app_instance_id = excluded.app_instance_id,
                            credentials_setup = excluded.credentials_setup,
                            hidden = excluded.hidden,
                            updated_at = excluded.updated_at
                    """)
                    
                    now = datetime.now(timezone.utc)
                    await session.execute(stmt, {
                        'tenant_id': self.tenant_id,
                        'user_okta_id': user_okta_id,
                        'application_okta_id': link['application_okta_id'],
                        'assignment_id': link['assignment_id'],
                        'app_instance_id': link['app_instance_id'],
                        'credentials_setup': link['credentials_setup'],
                        'hidden': link['hidden'],
                        'created_at': now,
                        'updated_at': now
                    })
    
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
                    
                    now = datetime.now(timezone.utc)
                    await session.execute(stmt, {
                        'tenant_id': self.tenant_id,
                        'user_okta_id': user_okta_id,
                        'group_okta_id': membership['group_okta_id'],
                        'created_at': now,
                        'updated_at': now
                    })
    
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
    
            await session.commit()
            logger.debug(f"Completed relationship sync for user {user_okta_id}")
                
        except Exception as e:
            logger.error(f"Error processing user relationships for {user_okta_id}: {str(e)}")
            raise

    async def _process_group_relationships(
        self,
        session: AsyncSession,
        group_data: Dict,
    ) -> None:
        """Process group relationships with cleanup of removed assignments"""
        try:
            # Get current assignments from Okta response
            current_app_assignments = group_data.pop('applications', [])
            current_app_ids = [str(a['application_okta_id']) for a in current_app_assignments]
            group_okta_id = str(group_data['okta_id'])
    
            # Delete all existing assignments for this group first
            delete_all_stmt = text("""
                DELETE FROM group_application_assignments 
                WHERE tenant_id = :tenant_id 
                AND group_okta_id = :group_okta_id
            """)
            
            await session.execute(delete_all_stmt, {
                'tenant_id': str(self.tenant_id),
                'group_okta_id': group_okta_id
            })
    
            # Insert current assignments
            if current_app_assignments:
                for assignment in current_app_assignments:
                    insert_stmt = text("""
                        INSERT INTO group_application_assignments 
                        (tenant_id, group_okta_id, application_okta_id, assignment_id, created_at, updated_at)
                        VALUES (:tenant_id, :group_okta_id, :application_okta_id, :assignment_id, :created_at, :updated_at)
                    """)
                    
                    now = datetime.now(timezone.utc)
                    await session.execute(insert_stmt, {
                        'tenant_id': str(self.tenant_id),
                        'group_okta_id': str(assignment['group_okta_id']),
                        'application_okta_id': str(assignment['application_okta_id']),
                        'assignment_id': str(assignment['assignment_id']),
                        'created_at': now,
                        'updated_at': now
                    })
    
            await session.commit()
            logger.debug(f"Processed {len(current_app_assignments)} assignments for group {group_okta_id}")
            
        except Exception as e:
            logger.error(f"Error processing group relationships: {str(e)}")
            raise

    async def _process_app_relationships(
        self,
        session: AsyncSession,
        app_data: Dict,
    ) -> None:
        """Process application relationships with cleanup of removed assignments"""
        try:
            # Get current assignments from Okta response
            current_group_assignments = app_data.pop('app_group_assignments', [])
            app_okta_id = str(app_data['okta_id'])
            
            # Delete all existing assignments for this application first
            delete_all_stmt = text("""
                DELETE FROM group_application_assignments 
                WHERE tenant_id = :tenant_id 
                AND application_okta_id = :app_okta_id
            """)
            
            await session.execute(delete_all_stmt, {
                'tenant_id': str(self.tenant_id),
                'app_okta_id': app_okta_id
            })
    
            # Insert current assignments
            if current_group_assignments:
                for assignment in current_group_assignments:
                    insert_stmt = text("""
                        INSERT INTO group_application_assignments 
                        (tenant_id, group_okta_id, application_okta_id, assignment_id, created_at, updated_at)
                        VALUES (:tenant_id, :group_okta_id, :application_okta_id, :assignment_id, :created_at, :updated_at)
                    """)
                    
                    now = datetime.now(timezone.utc)
                    await session.execute(insert_stmt, {
                        'tenant_id': str(self.tenant_id),
                        'group_okta_id': str(assignment['group_okta_id']),
                        'application_okta_id': str(assignment['application_okta_id']),
                        'assignment_id': str(assignment['assignment_id']),
                        'created_at': now,
                        'updated_at': now
                    })
    
            logger.debug(f"Processed {len(current_group_assignments)} group assignments for app {app_okta_id}")
            
        except Exception as e:
            logger.error(f"Error processing app relationships: {str(e)}")
            raise
        
    async def _clean_entity_data(self, session: AsyncSession, model: Type[ModelType]) -> None:
        """Clean existing data for entity type"""
        try:
            # Delete data based on model type
            if model == User:
                # Clean user-related tables first
                await session.execute(text("""
                    DELETE FROM user_factors 
                    WHERE tenant_id = :tenant_id
                """), {'tenant_id': self.tenant_id})
                
                await session.execute(text("""
                    DELETE FROM user_application_assignments 
                    WHERE tenant_id = :tenant_id
                """), {'tenant_id': self.tenant_id})
                
                await session.execute(text("""
                    DELETE FROM user_group_memberships 
                    WHERE tenant_id = :tenant_id
                """), {'tenant_id': self.tenant_id})
                
                await session.execute(text("""
                    DELETE FROM users 
                    WHERE tenant_id = :tenant_id
                """), {'tenant_id': self.tenant_id})
                
            elif model == Group:
                await session.execute(text("""
                    DELETE FROM group_application_assignments 
                    WHERE tenant_id = :tenant_id
                """), {'tenant_id': self.tenant_id})
                
                await session.execute(text("""
                    DELETE FROM groups 
                    WHERE tenant_id = :tenant_id
                """), {'tenant_id': self.tenant_id})
                
            elif model == Application:
                await session.execute(text("""
                    DELETE FROM applications 
                    WHERE tenant_id = :tenant_id
                """), {'tenant_id': self.tenant_id})

            elif model == Device: 
                # Clean device-related tables first (user_devices relationships)
                await session.execute(text("""
                    DELETE FROM user_devices 
                    WHERE tenant_id = :tenant_id
                """), {'tenant_id': self.tenant_id})
                
                # Then clean devices themselves
                await session.execute(text("""
                    DELETE FROM devices 
                    WHERE tenant_id = :tenant_id
                """), {'tenant_id': self.tenant_id})                
                
                
            await session.commit()
            logger.info(f"Cleaned {model.__name__} data for tenant {self.tenant_id}")
            
        except Exception as e:
            logger.error(f"Error cleaning {model.__name__} data: {str(e)}")
            raise 
        
        
    async def sync_model_streaming(self, model: Type[ModelType], list_method: Callable, batch_size: int = 100) -> None:
        """Sync model with direct API-to-DB streaming (no memory accumulation)."""
        import time
        start_time = time.time()
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
                    logger.error("No active sync record found for updates")
                    return
                    
                sync_id = active_sync.id
                
                try:
                    # Clean existing data first
                    await self._clean_entity_data(session, model)
                    logger.info(f"Cleaned existing {model.__name__} data")
                    
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
                                
                            await session.commit()
                        
                        logger.info(f"Processed {batch_count} {model.__name__} records, total: {total_records}")
                    
                    # Call list method with direct processor function 
                    await list_method(processor_func=process_batch_directly)
                    
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
        1. Groups first (for initial sync)
        2. Applications second
        3. Authenticators third (no dependencies)
        4. Devices fourth (conditional sync, no dependencies) 
        5. Users fifth (depends on groups and apps)
        6. Policies last (depends on apps)
        
        Supports cancellation via cancellation_flag attribute.
        """
        try:
            import time
            overall_start_time = time.time()
            await self._initialize()
            
            # Pass the cancellation flag to the OktaClientWrapper
            async with OktaClientWrapper(self.tenant_id, self.cancellation_flag) as okta:
                logger.info(f"Starting sync in dependency order for tenant {self.tenant_id}")
                
                # Check cancellation before each major step
                # 1. Groups first (for initial sync)
                if not self.cancellation_flag or (hasattr(self.cancellation_flag, 'is_set') and not self.cancellation_flag.is_set()):
                    logger.info("Step 1: Syncing Groups")
                    await self.sync_model_streaming(Group, okta.list_groups)
                else:
                    logger.info("Sync cancelled - skipping Groups")
                    return
                    
                # 2. Applications second
                if not self.cancellation_flag or (hasattr(self.cancellation_flag, 'is_set') and not self.cancellation_flag.is_set()):
                    logger.info("Step 2: Syncing Applications")
                    await self.sync_model_streaming(Application, okta.list_applications)
                else:
                    logger.info("Sync cancelled - skipping remaining steps")
                    return
    
                # 3. Authenticators third (no dependencies)
                if not self.cancellation_flag or (hasattr(self.cancellation_flag, 'is_set') and not self.cancellation_flag.is_set()):
                    logger.info("Step 3: Syncing Authenticators")
                    await self.sync_model_streaming(Authenticator, okta.list_authenticators)
                else:
                    logger.info("Sync cancelled - skipping remaining steps")
                    return
                
                # 4. Users last (depends on groups and apps)
                if not self.cancellation_flag or (hasattr(self.cancellation_flag, 'is_set') and not self.cancellation_flag.is_set()):
                    logger.info("Step 4: Syncing Users")
                    await self.sync_model_streaming(User, okta.list_users)
                else:
                    logger.info("Sync cancelled - skipping remaining steps")
                    return                
                
                # 5. Devices fourth (conditional sync)
                if not self.cancellation_flag or (hasattr(self.cancellation_flag, 'is_set') and not self.cancellation_flag.is_set()):
                    # Check if device sync is enabled
                    from src.config.settings import settings
                    if settings.SYNC_OKTA_DEVICES:
                        logger.info("Step 4: Syncing Devices")
                        await self.sync_model_streaming(Device, okta.list_devices)
                    else:
                        logger.info("Step 4: Skipping Devices (SYNC_OKTA_DEVICES=false)")
                else:
                    logger.info("Sync cancelled - skipping remaining steps")
                    return                
    
    
                # 6. Policies (depends on apps)
                if not self.cancellation_flag or (hasattr(self.cancellation_flag, 'is_set') and not self.cancellation_flag.is_set()):
                    logger.info("Step 5: Syncing Policies")
                    await self.sync_model_streaming(Policy, okta.list_policies)
                    
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
            # Process relationships for users and groups
            for record in batch:
                if model == User:
                    await self._process_user_relationships(session, record)
                elif model == Group:
                    await self._process_group_relationships(session, record)
                elif model == Application:
                    await self._process_app_relationships(session, record)                    
    
            # Process main records
            await self.db.bulk_upsert(session, model, batch, self.tenant_id)
            
            # Return batch count
            return len(batch)
            
        except Exception as e:
            logger.error(f"Error processing batch of {model.__name__}: {str(e)}")
            raise       