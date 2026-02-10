#!/usr/bin/env python3
"""
CLI Sync Utility for Okta AI Agent v2.0
Synchronizes Okta data (Users, Groups, Apps, Policies, Devices) to local SQLite.
"""

import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime, timezone

# Setup project paths
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

# Load environment variables
from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from urllib.parse import urlparse
from src.core.okta.sync.engine import SyncOrchestrator
from src.core.okta.sync.operations import DatabaseOperations
from src.core.okta.sync.models import SyncStatus, SyncHistory, User, Group, Application, Policy, Device
from src.utils.logging import get_logger
from sqlalchemy import select, func, and_

logger = get_logger("cli_sync")

def get_utc_now():
    """Return current UTC datetime with timezone info"""
    return datetime.now(timezone.utc)

async def run_sync():
    # Get tenant_id from OKTA_CLIENT_ORGURL (same logic as Settings.tenant_id)
    okta_url = os.getenv("OKTA_CLIENT_ORGURL")
    if not okta_url:
        logger.error("OKTA_CLIENT_ORGURL environment variable not set")
        print("Error: OKTA_CLIENT_ORGURL not found in .env file")
        sys.exit(1)
    
    # Extract tenant_id from URL (e.g., "https://dev-12345.okta.com" -> "dev-12345")
    parsed_url = urlparse(okta_url)
    tenant_id = parsed_url.netloc.split('.')[0]
    
    logger.info(f"Starting Okta sync for tenant: {tenant_id}")
    
    db = DatabaseOperations()
    await db.init_db()
    
    sync_id = None
    
    try:
        # 1. Create Sync History record
        async with db.get_session() as session:
            sync_history = SyncHistory(
                tenant_id=tenant_id,
                status=SyncStatus.RUNNING,
                start_time=get_utc_now(),
                progress_percentage=0
            )
            session.add(sync_history)
            await session.commit()
            await session.refresh(sync_history)
            sync_id = sync_history.id
            logger.info(f"Created sync history entry (ID: {sync_id})")

        # 2. Run Sync Orchestrator
        orchestrator = SyncOrchestrator(tenant_id, db)
        # Note: In a CLI we don't easily have a cancellation event, but we can pass a dummy one
        orchestrator.cancellation_flag = asyncio.Event()
        
        await orchestrator.run_sync()
        
        # 3. Finalize and count results
        async with db.get_session() as session:
            # Count entities
            users_count = (await session.execute(select(func.count()).select_from(User).where(and_(User.tenant_id == tenant_id, User.is_deleted == False)))).scalar() or 0
            groups_count = (await session.execute(select(func.count()).select_from(Group).where(and_(Group.tenant_id == tenant_id, Group.is_deleted == False)))).scalar() or 0
            apps_count = (await session.execute(select(func.count()).select_from(Application).where(and_(Application.tenant_id == tenant_id, Application.is_deleted == False)))).scalar() or 0
            policies_count = (await session.execute(select(func.count()).select_from(Policy).where(and_(Policy.tenant_id == tenant_id, Policy.is_deleted == False)))).scalar() or 0
            devices_count = (await session.execute(select(func.count()).select_from(Device).where(and_(Device.tenant_id == tenant_id, Device.is_deleted == False)))).scalar() or 0
            
            # Update history
            stmt = select(SyncHistory).where(SyncHistory.id == sync_id)
            result = await session.execute(stmt)
            history_entry = result.scalars().first()
            
            if history_entry:
                history_entry.status = SyncStatus.COMPLETED
                history_entry.end_time = get_utc_now()
                history_entry.success = True
                history_entry.progress_percentage = 100
                history_entry.users_count = users_count
                history_entry.groups_count = groups_count
                history_entry.apps_count = apps_count
                history_entry.policies_count = policies_count
                history_entry.devices_count = devices_count
                await session.commit()
            
            # Cleanup old history
            await db.cleanup_sync_history(tenant_id, keep_count=30)
            
        print(f"\n✅ Sync Completed Successfully!")
        print(f"📊 Results:")
        print(f"  • Users: {users_count}")
        print(f"  • Groups: {groups_count}")
        print(f"  • Apps: {apps_count}")
        print(f"  • Policies: {policies_count}")
        print(f"  • Devices: {devices_count}")
        
    except Exception as e:
        logger.error(f"Sync failed: {e}", exc_info=True)
        if sync_id:
            async with db.get_session() as session:
                stmt = select(SyncHistory).where(SyncHistory.id == sync_id)
                result = await session.execute(stmt)
                history_entry = result.scalars().first()
                if history_entry:
                    history_entry.status = SyncStatus.FAILED
                    history_entry.end_time = get_utc_now()
                    history_entry.success = False
                    history_entry.error_details = str(e)
                    await session.commit()
        print(f"\n❌ Sync failed: {e}")
        sys.exit(1)
    finally:
        await db.close()

if __name__ == "__main__":
    print("🔄 Starting Okta Data Sync...")
    try:
        asyncio.run(run_sync())
    except KeyboardInterrupt:
        print("\n⚠️  Sync interrupted by user.")
        sys.exit(1)
