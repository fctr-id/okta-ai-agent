"""
Database operations for Okta entity synchronization.
Provides async SQLAlchemy operations for managing Okta entities and relationships.

Key features:
- Async database operations
- Bulk upsert with relationship handling
- Soft delete support
- Sync history tracking
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, and_, not_, or_, update, func, text
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import List, Type, TypeVar, Optional, Dict, Any, AsyncGenerator, Union

# Note: Business data models (User, Device, etc.) are stub classes in GraphDB mode
# They exist for backward compatibility but raise NotImplementedError if instantiated
# Real business data is stored in Kuzu GraphDB, not SQLite
from .models import Base, User, UserFactor, group_application_assignments, AuthUser, UserRole, SyncHistory, SyncStatus, Device, UserDevice

from src.core.security.password_hasher import hash_password, verify_password, check_password_needs_rehash, calculate_lockout_time
from src.config.settings import settings
from src.utils.logging import logger


ModelType = TypeVar('ModelType', bound=Base)

class DatabaseOperations:
    def __init__(self):
        """Initialize async database engine with WAL mode"""
        self.engine = create_async_engine(
            settings.DATABASE_URL,
            connect_args={
                "timeout": 30,
                "check_same_thread": False,
            },
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True
        )
        self.SessionLocal = async_sessionmaker(
            self.engine,
            expire_on_commit=False
        )
        self._initialized = False

    async def init_db(self):
        """Initialize database with WAL mode and optimized settings"""
        if not self._initialized:
            async with self.engine.begin() as conn:
                # Enable WAL mode
                await conn.execute(text("PRAGMA journal_mode=WAL"))
                # Set synchronous mode for better performance
                await conn.execute(text("PRAGMA synchronous=NORMAL"))
                # Create tables
                await conn.run_sync(Base.metadata.create_all)
            self._initialized = True
            
    async def close(self):
        """Close database connection"""
        if self.engine:
            await self.engine.dispose()            

    @asynccontextmanager    
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Get async database session with automatic commit/rollback.
        
        Yields:
            AsyncSession: Database session
            
        Raises:
            Exception: On database errors, session is rolled back
            
        Usage:
            async with db.get_session() as session:
                await session.execute(stmt)
        """    
        async with self.SessionLocal() as session:
            try:
                yield session
                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.error(f"Database session error: {str(e)}")
                raise
    
    async def bulk_upsert(
        self,
        session: AsyncSession,
        model: Type[ModelType],
        records: List[dict],
        tenant_id: str
    ) -> bool:
        """
        Bulk upsert records with support for nested relationships.
        
        Args:
            session: Active database session
            model: SQLAlchemy model class (User, Group etc)
            records: List of record dictionaries from Okta
            tenant_id: Tenant identifier
            
        Returns:
            bool: True if successful
            
        Raises:
            Exception: On database errors
            
        Notes:
            - Handles nested user factors for User model
            - Updates existing records
            - Creates new records
            - Sets sync timestamps
            - Handles custom_attributes JSON column for User model
        """
        try:
            total_factors = 0
            total_user_devices = 0
            
            for record in records:
                # Extract factors if present (User model)
                factors = record.pop('factors', []) if model == User else None
                if model == User:
                    total_factors += len(factors) if factors else 0
                
                # Extract user_devices if present (Device model) 
                user_devices = record.pop('user_devices', []) if model == Device else None
                if model == Device:
                    total_user_devices += len(user_devices) if user_devices else 0
                
                # Process main record
                stmt = select(model).where(
                    and_(
                        model.okta_id == record['okta_id'],
                        model.tenant_id == tenant_id
                    )
                )
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()
    
                if existing:
                    for key, value in record.items():
                        if hasattr(existing, key):
                            # Handle JSON column properly
                            if key == 'custom_attributes' and isinstance(value, dict):
                                setattr(existing, key, value)
                            else:
                                setattr(existing, key, value)
                    existing.last_synced_at = datetime.utcnow()
                else:
                    record['tenant_id'] = tenant_id
                    record['last_synced_at'] = datetime.utcnow()
                    # Ensure custom_attributes is properly set for new records
                    if model == User and 'custom_attributes' not in record:
                        record['custom_attributes'] = {}
                    existing = model(**record)
                    session.add(existing)
                
                # Process factors if present
                if factors:
                    await self._process_user_factors(session, existing, factors, tenant_id)
                    
                # Process user-device relationships if present (Device model)
                if user_devices:
                    await self._process_device_user_relationships(session, existing, user_devices, tenant_id)                    
    
            # Logging
            if model == User:
                logger.debug(f"Processed {len(records)} users with {total_factors} factors")
            elif model == Device:
                logger.debug(f"Processed {len(records)} devices with {total_user_devices} user relationships")
            else:
                logger.info(f"Processed {len(records)} {model.__name__} records")
            return True
        except Exception as e:
            logger.error(f"Bulk upsert error for {model.__name__}: {str(e)}")
            raise
    
    async def mark_deleted(
        self,
        session: AsyncSession,
        model: Type[ModelType],
        okta_ids: List[str],
        tenant_id: str
    ) -> bool:
        """
        Soft delete records not present in Okta anymore.
        
        Args:
            session: Active database session
            model: SQLAlchemy model class
            okta_ids: List of active Okta IDs
            tenant_id: Tenant identifier
            
        Returns:
            bool: True if successful
            
        Notes:
            Sets is_deleted=True for records not in okta_ids
        """        
            
        try:
            stmt = select(model).where(
                and_(
                    model.tenant_id == tenant_id,
                    not_(model.okta_id.in_(okta_ids))
                )
            )
            result = await session.execute(stmt)
            records = result.scalars().all()
            
            for record in records:
                record.is_deleted = True
                record.last_synced_at = datetime.utcnow()
            
            return True
        except Exception as e:
            logger.error(f"Mark deleted error for {model.__name__}: {str(e)}")
            raise

        # Fix the get_last_sync_time method to use end_time instead of sync_end_time
    async def get_last_sync_time(
        self,
        session: AsyncSession,
        model: Type[ModelType],
        tenant_id: str
    ) -> Optional[datetime]:
        """
        Get timestamp of last successful sync for incremental updates.
        """
        try:
            from .models import SyncHistory, SyncStatus
            
            # Handle both SUCCESS and COMPLETED status values
            stmt = select(SyncHistory.end_time)\
                .where(
                    and_(
                        SyncHistory.tenant_id == tenant_id,
                        SyncHistory.entity_type == model.__name__,
                        SyncHistory.status.in_([SyncStatus.SUCCESS, SyncStatus.COMPLETED]),
                        SyncHistory.records_processed > 0
                    )
                )\
                .order_by(SyncHistory.end_time.desc())
                
            result = await session.execute(stmt)
            return result.scalar()
            
        except Exception as e:
            logger.error(f"Get last sync time error for {model.__name__}: {str(e)}")
            return None
        
    async def _process_user_factors(
        self,
        session: AsyncSession,
        user: User,
        factors: List[Dict[str, Any]],
        tenant_id: str
    ) -> None:
        """
        Process MFA factors for a user.
        
        Args:
            session: Active database session
            user: User model instance
            factors: List of factor dictionaries from Okta
            tenant_id: Tenant identifier
            
        Raises:
            Exception: On database errors
            
        Notes:
            - Creates/updates user factors
            - Marks removed factors as deleted
            - Maintains factor sync timestamps
        """        
        try:
            logger.debug(f"Processing {len(factors)} factors for user {user.okta_id}")
            factor_ids = []
            logger.debug(f"factor data: {factors}")
            for factor in factors:
                # Add tenant context
                factor['tenant_id'] = tenant_id
                factor['user_okta_id'] = user.okta_id
                
                # Find existing factor
                stmt = select(UserFactor).where(
                    and_(
                        UserFactor.okta_id == factor['okta_id'],
                        UserFactor.tenant_id == tenant_id,
                        UserFactor.user_okta_id == user.okta_id
                    )
                )
                result = await session.execute(stmt)
                existing_factor = result.scalar_one_or_none()
    
                if existing_factor:
                    # Update existing factor
                    for key, value in factor.items():
                        if hasattr(existing_factor, key):
                            setattr(existing_factor, key, value)
                    existing_factor.last_synced_at = datetime.utcnow()
                else:
                    # Create new factor
                    new_factor = UserFactor(**factor)
                    session.add(new_factor)
                
                factor_ids.append(factor['okta_id'])
    
            # Mark deleted factors
            stmt = select(UserFactor).where(
                and_(
                    UserFactor.user_okta_id == user.okta_id,
                    UserFactor.tenant_id == tenant_id,
                    not_(UserFactor.okta_id.in_(factor_ids))
                )
            )
            result = await session.execute(stmt)
            deleted_factors = result.scalars().all()
            
            for factor in deleted_factors:
                factor.is_deleted = True
                factor.last_synced_at = datetime.utcnow()
    
            await session.commit()
    
        except Exception as e:
            logger.error(f"Error processing factors for user {user.okta_id}: {str(e)}")
            raise  
               
    async def _process_group_relationships(
        self,
        session: AsyncSession,
        group_data: Dict,
        tenant_id: str  # Added tenant_id parameter
    ) -> None:
        """
        Process group application assignments.
        
        Args:
            session: Active database session
            group_data: Group data with relationships
            tenant_id: Tenant identifier
            
        Raises:
            Exception: On database errors
            
        Notes:
            - Handles group-application assignments
            - Updates assignment metadata
            - Maintains sync timestamps
        """ 
        try:
            # Process application assignments
            app_assignments = group_data.pop('applications', [])
            if app_assignments:
                for assignment in app_assignments:
                    stmt = group_application_assignments.insert().values(
                        tenant_id=tenant_id,  # Using the passed tenant_id parameter
                        group_okta_id=assignment['group_okta_id'],
                        application_okta_id=assignment['application_okta_id'],
                        assignment_id=assignment['assignment_id']
                    ).on_conflict_do_update(
                        index_elements=['tenant_id', 'group_okta_id', 'application_okta_id'],
                        set_=dict(
                            assignment_id=assignment['assignment_id'],
                            updated_at=datetime.utcnow()
                        )
                    )
                    await session.execute(stmt)
            
        except Exception as e:
            logger.error(f"Error processing group relationships: {str(e)}")
            raise     
        
    async def _process_device_user_relationships(
        self,
        session: AsyncSession,
        device: Device,
        user_devices: List[Dict[str, Any]],
        tenant_id: str
    ) -> None:
        """
        Process user-device relationships for a device.
        
        Args:
            session: Active database session
            device: Device model instance
            user_devices: List of user-device relationship dictionaries
            tenant_id: Tenant identifier
            
        Raises:
            Exception: On database errors
            
        Notes:
            - Creates/updates user-device relationships
            - Validates that users exist before creating relationships
            - Marks removed relationships as deleted
            - Maintains relationship sync timestamps
        """        
        try:
            logger.debug(f"Processing {len(user_devices)} user relationships for device {device.okta_id}")
            relationship_keys = []
            
            for user_device_data in user_devices:
                user_okta_id = user_device_data['user_okta_id']
                
                # Validate that user exists before creating relationship
                user_exists_stmt = select(User).where(
                    and_(
                        User.okta_id == user_okta_id,
                        User.tenant_id == tenant_id,
                        User.is_deleted == False
                    )
                )
                user_result = await session.execute(user_exists_stmt)
                if not user_result.scalar_one_or_none():
                    logger.warning(f"Skipping device-user relationship: user {user_okta_id} not found for device {device.okta_id}")
                    continue
                
                # Add context
                user_device_data['tenant_id'] = tenant_id
                user_device_data['device_okta_id'] = device.okta_id
                
                # Find existing relationship
                stmt = select(UserDevice).where(
                    and_(
                        UserDevice.user_okta_id == user_okta_id,
                        UserDevice.device_okta_id == device.okta_id,
                        UserDevice.tenant_id == tenant_id
                    )
                )
                result = await session.execute(stmt)
                existing_relationship = result.scalar_one_or_none()
    
                if existing_relationship:
                    # Update existing relationship
                    for key, value in user_device_data.items():
                        if hasattr(existing_relationship, key):
                            setattr(existing_relationship, key, value)
                    existing_relationship.last_synced_at = datetime.utcnow()
                else:
                    # Create new relationship
                    new_relationship = UserDevice(**user_device_data)
                    session.add(new_relationship)
                
                relationship_keys.append((user_okta_id, device.okta_id))
    
            # Mark deleted relationships (soft delete)
            if relationship_keys:
                # Build the condition for relationships that should remain active
                active_conditions = [
                    and_(
                        UserDevice.user_okta_id == user_id,
                        UserDevice.device_okta_id == device_id
                    )
                    for user_id, device_id in relationship_keys
                ]
                
                # Find relationships to mark as deleted
                stmt = select(UserDevice).where(
                    and_(
                        UserDevice.device_okta_id == device.okta_id,
                        UserDevice.tenant_id == tenant_id,
                        not_(or_(*active_conditions))
                    )
                )
            else:
                # No active relationships - mark all as deleted
                stmt = select(UserDevice).where(
                    and_(
                        UserDevice.device_okta_id == device.okta_id,
                        UserDevice.tenant_id == tenant_id
                    )
                )
            
            result = await session.execute(stmt)
            deleted_relationships = result.scalars().all()
            
            for relationship in deleted_relationships:
                relationship.is_deleted = True
                relationship.last_synced_at = datetime.utcnow()
    
            await session.commit()
    
        except Exception as e:
            logger.error(f"Error processing user relationships for device {device.okta_id}: {str(e)}")
            raise                  
        
    #Authentication methods:

    async def get_auth_user(self, session: AsyncSession, username: str) -> Optional[AuthUser]:
        """Get a user by username"""
        result = await session.execute(select(AuthUser).where(AuthUser.username == username))
        return result.scalars().first()

    async def create_auth_user(self, session: AsyncSession, username: str, password: str, 
                            role: UserRole = UserRole.ADMIN) -> AuthUser:
        """Create a new authentication user"""
        password_hash = hash_password(password)
        
        user = AuthUser(
            username=username,
            password_hash=password_hash,
            role=role,
            setup_completed=True
        )
        
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user

    async def check_setup_completed(self, session: AsyncSession) -> bool:
        """Check if the initial setup has been completed"""
        result = await session.execute(select(func.count(AuthUser.id)).where(AuthUser.setup_completed == True))
        count = result.scalar()
        return count > 0

    async def update_password(self, session: AsyncSession, username: str, new_password: str) -> bool:
        """Update a user's password"""
        password_hash = hash_password(new_password)
        
        stmt = (
            update(AuthUser)
            .where(AuthUser.username == username)
            .values(
                password_hash=password_hash,
                updated_at=datetime.now(timezone.utc)
            )
        )
        
        result = await session.execute(stmt)
        await session.commit()
        
        return result.rowcount > 0

    async def verify_user_credentials(self, session: AsyncSession, username: str, 
                                    password: str) -> Union[AuthUser, None]:
        """Verify user credentials and handle login attempts"""
        user = await self.get_auth_user(session, username)
        
        if not user:
            logger.warning(f"Login attempt for non-existent user: {username}")
            return None
        
        if not user.is_active:
            logger.warning(f"Login attempt for inactive user: {username}")
            return None
            
        # Check if the account is temporarily locked
        now = datetime.now(timezone.utc)
        if user.locked_until and user.locked_until > now:
            logger.warning(f"Login attempt for locked account: {username}")
            return None
        
        # Verify password
        if verify_password(user.password_hash, password):
            # Successful login - reset attempts and update last login
            user.login_attempts = 0
            user.last_login = now
            user.locked_until = None
            
            # Check if password needs rehashing
            if check_password_needs_rehash(user.password_hash):
                user.password_hash = hash_password(password)
                
            await session.commit()
            return user
        else:
            # Failed login - increment attempts and possibly lock account
            user.login_attempts += 1
            
            # After 5 failed attempts, lock the account temporarily
            if user.login_attempts >= 5:
                user.locked_until = calculate_lockout_time(user.login_attempts)
                logger.warning(f"Account locked due to failed attempts: {username}")
                
            await session.commit()
            return None        
        
    # Fixed sync history methods to take session and tenant_id as parameters

    async def get_active_sync(self, session: AsyncSession, tenant_id: str) -> Optional[SyncHistory]:
        """
        Get currently running sync if any
        Returns SyncHistory object or None
        
        Args:
            session: Active database session
            tenant_id: Tenant identifier
        """
        query = select(SyncHistory).where(
            and_(
                SyncHistory.tenant_id == tenant_id,
                SyncHistory.status.in_([SyncStatus.RUNNING, SyncStatus.IDLE])
            )
        ).order_by(SyncHistory.start_time.desc()).limit(1)
        
        result = await session.execute(query)
        return result.scalars().first()

    async def get_last_completed_sync(self, session: AsyncSession, tenant_id: str) -> Optional[SyncHistory]:
        """
        Get the most recently completed sync
        Returns SyncHistory object or None
        
        Args:
            session: Active database session
            tenant_id: Tenant identifier
        """
        query = select(SyncHistory).where(
            and_(
                SyncHistory.tenant_id == tenant_id,
                SyncHistory.status.in_([SyncStatus.COMPLETED, SyncStatus.FAILED, SyncStatus.CANCELED])
            )
        ).order_by(SyncHistory.end_time.desc()).limit(1)
        
        result = await session.execute(query)
        return result.scalars().first()

    async def create_sync_history(self, session: AsyncSession, tenant_id: str) -> SyncHistory:
        """
        Create a new sync history entry
        Returns the created SyncHistory object
        
        Args:
            session: Active database session
            tenant_id: Tenant identifier
        """
        sync_history = SyncHistory(
            tenant_id=tenant_id,
            status=SyncStatus.IDLE,
            start_time=datetime.utcnow()
        )
        
        session.add(sync_history)
        await session.commit()
        await session.refresh(sync_history)
        return sync_history

    async def update_sync_history(self, session: AsyncSession, sync_id: int, tenant_id: str, data: Dict) -> Optional[SyncHistory]:
        """
        Update an existing sync history entry
        Returns the updated SyncHistory object
        
        Args:
            session: Active database session
            sync_id: ID of the sync history entry
            tenant_id: Tenant identifier
            data: Dictionary of fields to update
        """
        query = select(SyncHistory).where(
            and_(
                SyncHistory.id == sync_id,
                SyncHistory.tenant_id == tenant_id
            )
        )
        
        result = await session.execute(query)
        sync_history = result.scalars().first()
        
        if not sync_history:
            logger.error(f"Sync history with ID {sync_id} not found for tenant {tenant_id}")
            return None
            
        for key, value in data.items():
            if hasattr(sync_history, key):
                setattr(sync_history, key, value)
        
        await session.commit()
        await session.refresh(sync_history)
        return sync_history

    async def get_sync_history(self, session: AsyncSession, tenant_id: str, limit: int = 5) -> List[SyncHistory]:
        """
        Get recent sync history entries
        Returns a list of SyncHistory objects
        
        Args:
            session: Active database session
            tenant_id: Tenant identifier
            limit: Maximum number of entries to return
        """
        query = select(SyncHistory).where(
            SyncHistory.tenant_id == tenant_id
        ).order_by(SyncHistory.start_time.desc()).limit(limit)
        
        result = await session.execute(query)
        return result.scalars().all()        
    
    # Clean up sync history table
    async def cleanup_sync_history(self, tenant_id: str, keep_count: int = 30):
        """
        Keep only the most recent sync history entries per tenant.
        Groups by day and entity_type to maintain a complete picture of recent syncs.
        
        Args:
            tenant_id: The tenant ID to clean up
            keep_count: Number of days of history to keep per entity type
        """
        async with self.get_session() as session:
            # First, identify the dates we want to keep (most recent N days with sync activity)
            from sqlalchemy import func, select, delete, distinct
            
            # Get the distinct dates (truncated to day) with sync activity, ordered by most recent
            date_query = select(
                distinct(func.date(SyncHistory.start_time)).label("sync_date")
            ).where(
                SyncHistory.tenant_id == tenant_id
            ).order_by(
                text("sync_date DESC")
            ).limit(keep_count)
            
            result = await session.execute(date_query)
            dates_to_keep = [row[0] for row in result]
            
            if not dates_to_keep:
                return  # No sync history to clean up
            
            # Get the cutoff date (oldest date we want to keep)
            cutoff_date = min(dates_to_keep)
            
            # Delete all records older than the cutoff date
            delete_stmt = delete(SyncHistory).where(
                SyncHistory.tenant_id == tenant_id,
                func.date(SyncHistory.start_time) < cutoff_date
            )
            
            await session.execute(delete_stmt)
            await session.commit()
            
            logger.info(f"Cleaned up sync history for tenant {tenant_id}, keeping records since {cutoff_date}")