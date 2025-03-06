"""
Router for Okta data synchronization operations.
Provides endpoints to:
- Start sync process
- Check sync status
- Cancel running sync
- Get sync history
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Dict, Optional, List, Any
import asyncio
import uuid
import os
import signal
from datetime import datetime
import logging

from src.config.settings import settings
from src.core.auth.dependencies import get_current_user
from src.okta_db_sync.db.models import SyncHistory, SyncStatus
from src.okta_db_sync.db.operations import DatabaseOperations
from src.okta_db_sync.okta_client.client import OktaClientWrapper
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.auth.dependencies import get_db_session
from sqlalchemy import func, select, and_
from datetime import timezone, datetime
from asyncio import CancelledError
from src.utils.logging import sync_logger

# Add this helper function
def get_utc_now():
    """Return current UTC datetime with timezone info"""
    return datetime.now(timezone.utc)

# Set up dedicated sync logger
#sync_logger = logging.getLogger("okta_sync")
#if not sync_logger.handlers:
#    sync_log_file = os.path.join(settings.LOG_DIR, "okta_sync.log")
#    file_handler = logging.FileHandler(sync_log_file)
#    file_handler.setFormatter(logging.Formatter(
#        '%(asctime)s - %(name)s - tenant:[%(tenant_id)s] - %(levelname)s - %(message)s'
#    ))
#    sync_logger.addHandler(file_handler)
#    sync_logger.setLevel(logging.INFO)
#    sync_logger.propagate = False

router = APIRouter(prefix="/sync", tags=["sync"])

# Store active sync processes for cancellation
active_syncs = {}

class SyncResponse(BaseModel):
    status: str
    message: str
    sync_id: Optional[int] = None
    progress: Optional[int] = None
    entity_counts: Optional[Dict[str, int]] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

# Get tenant ID from the application settings
def get_tenant_id():
    return settings.tenant_id

# Create a database operations instance with tenant ID
async def get_db_ops(session: AsyncSession):
    """Get a database operations instance with tenant ID set"""
    db_ops = DatabaseOperations()
    # We need to set tenant_id as an attribute since the methods use self.tenant_id
    db_ops.tenant_id = get_tenant_id()
    # Also set the session since the methods use self.session
    db_ops.session = session
    return db_ops

# Modify the active_syncs global to store task objects
active_syncs = {}

# Need a shared cancellation flag mechanism
sync_cancellation_flags = {}

async def run_sync_operation(sync_id: int, db_session: AsyncSession):
    """Run the Okta data sync operation in background"""
    tenant_id = get_tenant_id()
    extra = {"tenant_id": tenant_id}
    sync_logger.info(f"Starting sync for sync_id: {sync_id}", extra=extra)
    process_id = str(uuid.uuid4())
    
    # Create a separate DatabaseOperations for the orchestrator
    db_ops = DatabaseOperations()
    
    # Set up cancellation flag
    sync_cancellation_flags[sync_id] = False
    
    try:
        # Update sync history with process ID and status
        async with db_session as session:
            db = await get_db_ops(session)
            await db.update_sync_history(sync_id, {
                "status": SyncStatus.RUNNING,
                "process_id": process_id
            })
        
        # Store process info for potential cancellation
        active_syncs[sync_id] = {
            "process_id": process_id,
            "tenant_id": tenant_id
        }
        
        # Initialize the database
        await db_ops.init_db()
        
        # Import the SyncOrchestrator
        from src.okta_db_sync.sync.engine import SyncOrchestrator
        
        # Create the orchestrator
        orchestrator = SyncOrchestrator(tenant_id, db_ops)
        
        # Run the sync operation
        sync_logger.info("Starting data synchronization via orchestrator", extra=extra)
        
        # Check for cancellation before starting sync
        if sync_cancellation_flags.get(sync_id, False):
            raise CancelledError("Sync was cancelled before it could start")
            
        # Run the sync with cancellation checks
        await run_sync_with_cancellation_check(orchestrator, sync_id)
        
        # Get counts from database after sync is complete
        from src.okta_db_sync.db.models import User, Group, Application, Policy
        
        # Check for cancellation again before counting entities
        if sync_cancellation_flags.get(sync_id, False):
            raise CancelledError("Sync was cancelled after completion")
            
        # Record the entity counts
        users_count = 0
        groups_count = 0
        apps_count = 0
        policies_count = 0
        
        try:
            async with db_ops.get_session() as count_session:
                # Count users
                stmt = select(func.count()).select_from(User).where(
                    and_(User.tenant_id == tenant_id, User.is_deleted == False)
                )
                result = await count_session.execute(stmt)
                users_count = result.scalar() or 0
                
                # Count groups
                stmt = select(func.count()).select_from(Group).where(
                    and_(Group.tenant_id == tenant_id, Group.is_deleted == False)
                )
                result = await count_session.execute(stmt)
                groups_count = result.scalar() or 0
                
                # Count applications
                stmt = select(func.count()).select_from(Application).where(
                    and_(Application.tenant_id == tenant_id, Application.is_deleted == False)
                )
                result = await count_session.execute(stmt)
                apps_count = result.scalar() or 0
                
                # Count policies
                stmt = select(func.count()).select_from(Policy).where(
                    and_(Policy.tenant_id == tenant_id, Policy.is_deleted == False)
                )
                result = await count_session.execute(stmt)
                policies_count = result.scalar() or 0
        except Exception as e:
            sync_logger.error(f"Error counting entities: {str(e)}", extra=extra)
        
        # Final cancellation check before updating status to completed
        if sync_cancellation_flags.get(sync_id, False):
            raise CancelledError("Sync was cancelled before final update")
            
        # Update final status with counts from database
        async with db_session as session:
            db = await get_db_ops(session)
            await db.update_sync_history(sync_id, {
                "status": SyncStatus.COMPLETED,
                "end_time": get_utc_now(),
                "success": True,
                "progress_percentage": 100,
                "users_count": users_count,
                "groups_count": groups_count,
                "apps_count": apps_count,
                "policies_count": policies_count
            })
        
        sync_logger.info("Sync completed successfully", extra=extra)
            
    except CancelledError as ce:
        sync_logger.info(f"Sync was cancelled: {str(ce)}", extra=extra)
        async with db_session as session:
            db = await get_db_ops(session)
            await db.update_sync_history(sync_id, {
                "status": SyncStatus.CANCELED,
                "end_time": get_utc_now(),
                "success": False,
                "error_details": f"Sync operation was cancelled: {str(ce)}"
            })
    except Exception as e:
        sync_logger.error(f"Sync failed: {str(e)}", extra=extra)
        # Update sync history with error
        async with db_session as session:
            db = await get_db_ops(session)
            await db.update_sync_history(sync_id, {
                "status": SyncStatus.FAILED,
                "end_time": get_utc_now(),
                "success": False,
                "error_details": str(e)
            })
    
    finally:
        # Clean up resources
        await db_ops.close()
        
        # Remove from active syncs and cancellation flags
        if sync_id in active_syncs:
            del active_syncs[sync_id]
        if sync_id in sync_cancellation_flags:
            del sync_cancellation_flags[sync_id]

# Add this helper function to implement the cancellation checks
async def run_sync_with_cancellation_check(orchestrator, sync_id):
    """Run the sync operation with periodic cancellation checks"""
    # Create a wrapper for the sync_model method that checks for cancellation
    original_sync_model = orchestrator.sync_model
    
    async def sync_model_with_cancellation_check(*args, **kwargs):
        # Check if sync has been cancelled
        if sync_cancellation_flags.get(sync_id, False):
            raise CancelledError(f"Sync {sync_id} was cancelled during operation")
        return await original_sync_model(*args, **kwargs)
    
    # Replace the method with our cancellation-aware version
    orchestrator.sync_model = sync_model_with_cancellation_check
    
    # Now run the sync
    await orchestrator.run_sync()

@router.post("/start", response_model=SyncResponse)
async def start_sync(
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
    current_user: Any = Depends(get_current_user)  # Keep for auth check
):
    """Start Okta data synchronization"""
    db = await get_db_ops(session)
    
    # Check if sync is already running
    active_sync = await db.get_active_sync()
    
    if active_sync:
        return SyncResponse(
            status="already_running",
            message="Sync operation already in progress",
            sync_id=active_sync.id,
            progress=active_sync.progress_percentage
        )
    
    # Create new sync history record
    sync_history = await db.create_sync_history()
    sync_id = sync_history.id
    
    # Start sync process in background
    background_tasks.add_task(
        run_sync_operation,
        sync_id, 
        session
    )
    
    return SyncResponse(
        status="started",
        message="Sync operation started",
        sync_id=sync_id,
        progress=0
    )

@router.get("/status", response_model=SyncResponse)
async def get_sync_status(
    session: AsyncSession = Depends(get_db_session),
    current_user: Any = Depends(get_current_user)  # Keep for auth check
):
    """Get current sync status or last completed sync"""
    db = await get_db_ops(session)
    
    # First check for active sync
    active_sync = await db.get_active_sync()
    if active_sync:
        return SyncResponse(
            status=active_sync.status.value,
            message=f"Sync in progress: {active_sync.progress_percentage}% complete",
            sync_id=active_sync.id,
            progress=active_sync.progress_percentage,
            entity_counts={
                "users": active_sync.users_count or 0,
                "groups": active_sync.groups_count or 0,
                "applications": active_sync.apps_count or 0,
                "policies": active_sync.policies_count or 0
            },
            start_time=active_sync.start_time
        )
    
    # If no active sync, get last completed sync
    last_sync = await db.get_last_completed_sync()
    if last_sync:
        return SyncResponse(
            status=last_sync.status.value,
            message="Latest sync information",
            sync_id=last_sync.id,
            progress=100 if last_sync.status == SyncStatus.COMPLETED else None,
            entity_counts={
                "users": last_sync.users_count or 0,
                "groups": last_sync.groups_count or 0,
                "applications": last_sync.apps_count or 0,
                "policies": last_sync.policies_count or 0
            },
            start_time=last_sync.start_time,
            end_time=last_sync.end_time
        )
    
    return SyncResponse(
        status="none",
        message="No sync history available"
    )

@router.post("/cancel", response_model=SyncResponse)
async def cancel_sync(
    session: AsyncSession = Depends(get_db_session),
    current_user: Any = Depends(get_current_user)  # Keep for auth check
):
    """Cancel currently running sync operation"""
    db = await get_db_ops(session)
    
    # Get active sync
    active_sync = await db.get_active_sync()
    if not active_sync:
        return SyncResponse(
            status="not_running",
            message="No sync operation currently running"
        )
    
    sync_id = active_sync.id
    
    # Set cancellation flag
    sync_cancellation_flags[sync_id] = True
    sync_logger.info(f"Cancellation requested for sync {sync_id}")
    
    # Update sync history to mark as cancellation requested
    await db.update_sync_history(sync_id, {
        "status": SyncStatus.CANCELED,
        "end_time": get_utc_now(),
        "success": False,
        "error_details": "Cancellation requested by user"
    })
    
    return SyncResponse(
        status="canceled",
        message="Sync operation cancellation requested - may take a moment to stop",
        sync_id=sync_id
    )

@router.get("/history", response_model=List[SyncResponse])
async def get_sync_history(
    limit: int = 5,
    session: AsyncSession = Depends(get_db_session),
    current_user: Any = Depends(get_current_user)  # Keep for auth check
):
    """Get sync history for the tenant"""
    db = await get_db_ops(session)
    
    history = await db.get_sync_history(limit)
    return [
        SyncResponse(
            status=entry.status.value,
            message=f"Sync {'completed successfully' if entry.success else 'failed' if entry.status == SyncStatus.FAILED else entry.status.value}",
            sync_id=entry.id,
            progress=100 if entry.status == SyncStatus.COMPLETED else entry.progress_percentage,
            entity_counts={
                "users": entry.users_count or 0,
                "groups": entry.groups_count or 0,
                "applications": entry.apps_count or 0,
                "policies": entry.policies_count or 0
            },
            start_time=entry.start_time,
            end_time=entry.end_time
        )
        for entry in history
    ]