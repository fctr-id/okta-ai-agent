import asyncio
import sys
from src.config.settings import settings
from src.okta_db_sync.sync.engine import SyncOrchestrator
from src.utils.logging import logger
from src.okta_db_sync.db.operations import DatabaseOperations


# Add parent directory to path for imports
#sys.path.insert(0, str(Path(__file__).parent.parent))

VERSION = "1.0.0"


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
        orchestrator = SyncOrchestrator(tenant_id, db)
        await orchestrator.run_sync()
        logger.info(f"Sync completed successfully for tenant: {tenant_id}")
        return True
    except Exception as e:
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