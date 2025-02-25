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
from sqlalchemy import select, and_, not_
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Type, TypeVar, Optional, Dict, Any, AsyncGenerator
from .models import Base, User, UserFactor, group_application_assignments
from src.config.settings import settings
from src.utils.logging import logger


ModelType = TypeVar('ModelType', bound=Base)

class DatabaseOperations:
    """
    Handles all database operations for Okta entity synchronization.
    Uses SQLAlchemy async engine with SQLite backend.
    
    Usage:
        db = DatabaseOperations()
        await db.init_db()
        
        async with db.get_session() as session:
            await db.bulk_upsert(session, User, users_data, tenant_id)
    """    
    def __init__(self):
        """Initialize async database engine and session factory"""
        self.engine = create_async_engine(settings.DATABASE_URL)
        self.SessionLocal = async_sessionmaker(self.engine, expire_on_commit=False)
        self._initialized = False

    async def init_db(self):
        """
        Initialize database by creating all defined tables.
        Should be called once at application startup.
        
        Raises:
            SQLAlchemyError: If table creation fails
        """
        if not self._initialized:
            async with self.engine.begin() as conn:
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
        """
        try:
            total_factors = 0
            for record in records:
                # Extract factors if present
                factors = record.pop('factors', []) if model == User else None
                if model == User:
                    total_factors += len(factors) if factors else 0
                
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
                            setattr(existing, key, value)
                    existing.last_synced_at = datetime.utcnow()
                else:
                    record['tenant_id'] = tenant_id
                    record['last_synced_at'] = datetime.utcnow()
                    existing = model(**record)
                    session.add(existing)
                
                # Process factors if present
                if factors:
                    await self._process_user_factors(session, existing, factors, tenant_id)
    
            if model == User:
                logger.info(f"Processed {len(records)} users with {total_factors} factors")
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

    async def get_last_sync_time(
        self,
        session: AsyncSession,
        model: Type[ModelType],
        tenant_id: str
    ) -> Optional[datetime]:
        """
        Get timestamp of last successful sync for incremental updates.
        
        Args:
            session: Active database session  
            model: SQLAlchemy model class
            tenant_id: Tenant identifier
            
        Returns:
            datetime: Last successful sync time or None
            
        Notes:
            Only returns time from successful syncs with records
        """
        try:
            from .models import SyncHistory, SyncStatus
            
            # Only get time from successful syncs
            stmt = select(SyncHistory.sync_end_time)\
                .where(
                    and_(
                        SyncHistory.tenant_id == tenant_id,
                        SyncHistory.entity_type == model.__name__,
                        SyncHistory.status == SyncStatus.SUCCESS,
                        SyncHistory.records_processed > 0  # Ensure records were processed
                    )
                )\
                .order_by(SyncHistory.sync_end_time.desc())
                
            result = await session.execute(stmt)
            return result.scalar()
            
        except Exception as e:
            logger.error(f"Get last sync time error for {model.__name__}: {str(e)}")
            raise
        
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
    ) -> None:
        """
        Process group application assignments.
        
        Args:
            session: Active database session
            group_data: Group data with relationships
            
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
                        tenant_id=self.tenant_id,
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

            await session.commit()
            
        except Exception as e:
            logger.error(f"Error processing group relationships: {str(e)}")
            raise               