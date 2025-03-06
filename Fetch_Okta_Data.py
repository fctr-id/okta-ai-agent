import asyncio
import sys
from datetime import datetime, timezone
from src.config.settings import settings
from src.okta_db_sync.sync.engine import SyncOrchestrator
from src.utils.logging import logger
from src.okta_db_sync.db.operations import DatabaseOperations
from src.okta_db_sync.db.models import SyncStatus, SyncHistory
from sqlalchemy import select, func, and_

VERSION = "1.0.1"

def get_utc_now():
    """Return current UTC datetime with timezone info"""
    return datetime.now(timezone.utc)

async def cleanup(db: DatabaseOperations):
    """Cleanup resources"""
    try:
        await db.close()
        logger.info("Database connections closed")
        return True
    except Exception as e:
        logger.error(f"Error during cleanup: {str(e)}")
        return False

async def run_sync(tenant_id: str, db: DatabaseOperations):
    """Run a single sync operation"""
    try:
        # Set the tenant_id attribute on db operations for compatibility with sync.py
        db.tenant_id = tenant_id
        
        # Create an overall sync history record like the API does
        overall_sync_id = None
        async with db.get_session() as session:
            # Assign the session for method compatibility
            db.session = session
            
            # Create sync history record
            sync_history = SyncHistory(
                tenant_id=tenant_id,
                status=SyncStatus.RUNNING,
                start_time=get_utc_now(),
                progress_percentage=25
            )
            session.add(sync_history)
            await session.commit()
            await session.refresh(sync_history)
            overall_sync_id = sync_history.id
            
            logger.info(f"Created sync history record with ID: {overall_sync_id}")
        
        # Run the sync operation
        orchestrator = SyncOrchestrator(tenant_id, db)
        await orchestrator.run_sync()
        
        # Update sync history with counts and completion status
        async with db.get_session() as session:
            db.session = session
            
            # Get entity counts
            from src.okta_db_sync.db.models import User, Group, Application, Policy
            
            users_count = await session.execute(
                select(func.count()).select_from(User).where(
                    and_(User.tenant_id == tenant_id, User.is_deleted == False)
                )
            )
            users_count = users_count.scalar() or 0
            
            groups_count = await session.execute(
                select(func.count()).select_from(Group).where(
                    and_(Group.tenant_id == tenant_id, Group.is_deleted == False)
                )
            )
            groups_count = groups_count.scalar() or 0
            
            apps_count = await session.execute(
                select(func.count()).select_from(Application).where(
                    and_(Application.tenant_id == tenant_id, Application.is_deleted == False)
                )
            )
            apps_count = apps_count.scalar() or 0
            
            policies_count = await session.execute(
                select(func.count()).select_from(Policy).where(
                    and_(Policy.tenant_id == tenant_id, Policy.is_deleted == False)
                )
            )
            policies_count = policies_count.scalar() or 0
            
            # Update sync history record
            stmt = select(SyncHistory).where(SyncHistory.id == overall_sync_id)
            result = await session.execute(stmt)
            sync_history = result.scalars().first()
            
            if sync_history:
                sync_history.status = SyncStatus.COMPLETED
                sync_history.end_time = get_utc_now()
                sync_history.success = True
                sync_history.progress_percentage = 100
                sync_history.users_count = users_count
                sync_history.groups_count = groups_count
                sync_history.apps_count = apps_count
                sync_history.policies_count = policies_count
                await session.commit()
            
        logger.info(f"Sync completed successfully for tenant: {tenant_id}")
        logger.info(f"Synced: {users_count} users, {groups_count} groups, {apps_count} apps, {policies_count} policies")
        return True
    except Exception as e:
        # Update sync history with error status if we have an ID
        if overall_sync_id:
            try:
                async with db.get_session() as session:
                    db.session = session
                    stmt = select(SyncHistory).where(SyncHistory.id == overall_sync_id)
                    result = await session.execute(stmt)
                    sync_history = result.scalars().first()
                    
                    if sync_history:
                        sync_history.status = SyncStatus.FAILED
                        sync_history.end_time = get_utc_now()
                        sync_history.success = False
                        sync_history.error_details = str(e)
                        await session.commit()
            except Exception as update_error:
                logger.error(f"Failed to update sync history with error: {str(update_error)}")
        
        logger.error(f"Sync failed for tenant {tenant_id}: {str(e)}")
        return False

async def startup_checks():
    """Verify all required configurations"""
    try:
        required_settings = ['OKTA_CLIENT_ORGURL', 'OKTA_CLIENT_TOKEN']
        missing = [setting for setting in required_settings if not getattr(settings, setting, None)]
        if missing:
            raise ValueError(f"Missing required settings: {', '.join(missing)}")
        return True
    except Exception as e:
        logger.error(f"Startup checks failed: {str(e)}")
        return False

async def main():
    logger.info(f"Starting Okta sync service v{VERSION} for tenant: {settings.tenant_id}")

    if not await startup_checks():
        sys.exit(1)

    db = DatabaseOperations()
    await db.init_db()

    try:
        if not await run_sync(settings.tenant_id, db):
            sys.exit(2)
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        sys.exit(2)
    finally:
        if not await cleanup(db):
            sys.exit(3)
    
    sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())