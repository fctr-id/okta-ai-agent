import asyncio
import sys
import os
import argparse
# Add parent directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Change working directory to root so .env file can be found
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone
from src.config.settings import settings
from src.core.okta.sync.engine import SyncOrchestrator
from src.utils.logging import logger
from src.core.okta.sync.operations import DatabaseOperations
from src.core.okta.sync.models import SyncStatus, SyncHistory
from sqlalchemy import select, func, and_

VERSION = "1.1.0"

# GraphDB support
GRAPHDB_ENABLED = False
try:
    from src.core.okta.graph_db import GraphDBOrchestrator
    GRAPHDB_ENABLED = True
    logger.info("GraphDB support available")
except ImportError:
    logger.warning("GraphDB not available (kuzu not installed)")

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

async def run_sync(tenant_id: str, db: DatabaseOperations, enable_graphdb: bool = False) -> bool:
    """Run the sync operation with optional GraphDB-only mode
    
    Args:
        tenant_id: The tenant ID to sync
        db: Database operations instance
        enable_graphdb: If True, sync to GraphDB only (no SQLite). If False, sync to SQLite only.
        
    Returns:
        True if sync was successful, False otherwise
    """
    
    graph_db_path = os.getenv('GRAPH_DB_PATH', './graph_db/okta_graph.db')
    
    try:
        # ========== GraphDB-ONLY mode ==========
        if enable_graphdb and GRAPHDB_ENABLED:
            logger.info("🎯 GraphDB-ONLY mode: Syncing directly from Okta to GraphDB (no SQLite)")
            
            orchestrator = GraphDBOrchestrator(
                tenant_id=tenant_id,
                graph_db_path=graph_db_path
            )
            
            # Run direct Okta → GraphDB sync
            counts = await orchestrator.run_sync()
            logger.info(f"✅ GraphDB sync complete: {counts}")
            
            # Clean up
            orchestrator.close()
            return True
        
        # If GraphDB was requested but not available
        if enable_graphdb and not GRAPHDB_ENABLED:
            logger.error("❌ GraphDB mode requested but kuzu not installed. Install with: pip install kuzu")
            return False
        
        # ========== SQLite mode (existing behavior) ==========
        logger.info("💾 SQLite mode: Syncing to SQLite database")
        
        # Set the tenant_id attribute on db operations for compatibility
        db.tenant_id = tenant_id
        
        # Create sync history record
        overall_sync_id = None
        async with db.get_session() as session:
            db.session = session
            
            from src.core.okta.sync.models import SyncType
            
            sync_history = SyncHistory(
                tenant_id=tenant_id,
                sync_type=SyncType.FULL,
                status=SyncStatus.IN_PROGRESS,
                start_time=get_utc_now(),
                progress_percentage=0,
                success=False
            )
            session.add(sync_history)
            await session.commit()
            overall_sync_id = sync_history.id
            
            logger.info(f"Created sync history record with ID: {overall_sync_id}")
        
        # Run the SQLite sync operation
        orchestrator = SyncOrchestrator(tenant_id, db)
        await orchestrator.run_sync()
        
        # Update sync history with counts and completion status
        async with db.get_session() as session:
            db.session = session
            
            # Get entity counts
            from src.core.okta.sync.models import User, Group, Application, Policy
            
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
                
            # Clean up old sync history records
            await db.cleanup_sync_history(tenant_id, keep_count=30)    
            
        logger.info(f"Sync completed successfully for tenant: {tenant_id}")
        logger.info(f"Synced: {users_count} users, {groups_count} groups, {apps_count} apps, {policies_count} policies")
        return True
        
    except Exception as e:
        # GraphDB mode error handling
        if enable_graphdb:
            logger.error(f"❌ GraphDB sync failed for tenant {tenant_id}: {str(e)}")
            return False
        
        # SQLite mode error handling - update sync history
        if 'overall_sync_id' in locals() and overall_sync_id:
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
        required_settings = ['OKTA_CLIENT_ORGURL', 'OKTA_API_TOKEN']
        missing = [setting for setting in required_settings if not getattr(settings, setting, None)]
        if missing:
            raise ValueError(f"Missing required settings: {', '.join(missing)}")
        return True
    except Exception as e:
        logger.error(f"Startup checks failed: {str(e)}")
        return False

async def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Okta Data Sync Service')
    parser.add_argument('--graphdb', action='store_true', 
                       help='Enable parallel sync to GraphDB (requires kuzu installed)')
    args = parser.parse_args()
    
    logger.info(f"Starting Okta sync service v{VERSION} for tenant: {settings.tenant_id}")
    if args.graphdb:
        if GRAPHDB_ENABLED:
            logger.info("GraphDB parallel sync: ENABLED")
        else:
            logger.warning("GraphDB requested but not available (install kuzu: pip install kuzu)")
            args.graphdb = False

    if not await startup_checks():
        sys.exit(1)

    db = DatabaseOperations()
    await db.init_db()

    try:
        if not await run_sync(settings.tenant_id, db, enable_graphdb=args.graphdb):
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