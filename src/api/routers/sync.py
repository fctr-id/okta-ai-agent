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

from config.settings import settings
from core.security.dependencies import get_current_user
from core.okta.sync.models import SyncHistory, SyncStatus
from core.okta.sync.operations import DatabaseOperations
from core.okta.client.client import OktaClientWrapper
from sqlalchemy.ext.asyncio import AsyncSession
from core.security.dependencies import get_db_session
from sqlalchemy import func, select, and_
from datetime import timezone, datetime
from asyncio import CancelledError
from utils.logging import get_logger

# Create a logger instance for this module
sync_logger = get_logger(__name__)

# Add this helper function
def get_utc_now():
    """Return current UTC datetime with timezone info"""
    return datetime.now(timezone.utc)


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

# Create a database operations instance
async def get_db_ops():
    """Get a database operations instance"""
    db_ops = DatabaseOperations()
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
            db = await get_db_ops()
            data = {
                "status": SyncStatus.RUNNING,
                "process_id": process_id
            }
            # Fix: Pass session and tenant_id explicitly
            await db.update_sync_history(session, sync_id, tenant_id, data)
        
        # Store process info for potential cancellation
        active_syncs[sync_id] = {
            "process_id": process_id,
            "tenant_id": tenant_id
        }
        
        # Initialize the database
        await db_ops.init_db()
        
        # Import the SyncOrchestrator
        from core.okta.sync.engine import SyncOrchestrator
        
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
        from core.okta.sync.models import User, Group, Application, Policy, Device
        
        # Check for cancellation again before counting entities
        if sync_cancellation_flags.get(sync_id, False):
            raise CancelledError("Sync was cancelled after completion")
            
        # Record the entity counts
        users_count = 0
        groups_count = 0
        apps_count = 0
        policies_count = 0
        devices_count = 0
        
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
                
                #count devices
                stmt = select(func.count()).select_from(Device).where(
                    and_(Device.tenant_id == tenant_id, Device.is_deleted == False)
                )
                result = await count_session.execute(stmt)
                devices_count = result.scalar() or 0
        except Exception as e:
            sync_logger.error(f"Error counting entities: {str(e)}", extra=extra)
        
        # Final cancellation check before updating status to completed
        if sync_cancellation_flags.get(sync_id, False):
            raise CancelledError("Sync was cancelled before final update")
            
        # Update final status with counts from database
        async with db_session as session:
            db = await get_db_ops()
            data = {
                "status": SyncStatus.COMPLETED,
                "end_time": get_utc_now(),
                "success": True,
                "progress_percentage": 100,
                "users_count": users_count,
                "groups_count": groups_count,
                "apps_count": apps_count,
                "policies_count": policies_count,
                "devices_count": devices_count
            }
            # Fix: Pass session and tenant_id explicitly
            await db.update_sync_history(session, sync_id, tenant_id, data)
           
            # Clean up old sync history records
            await db.cleanup_sync_history(tenant_id, keep_count=30)
        
        sync_logger.info("Sync completed successfully", extra=extra)
            
    except CancelledError as ce:
        sync_logger.info(f"Sync was cancelled: {str(ce)}", extra=extra)
        async with db_session as session:
            db = await get_db_ops()
            data = {
                "status": SyncStatus.CANCELED,
                "end_time": get_utc_now(),
                "success": False,
                "error_details": f"Sync operation was cancelled: {str(ce)}"
            }
            # Fix: Pass session and tenant_id explicitly
            await db.update_sync_history(session, sync_id, tenant_id, data)
    except Exception as e:
        sync_logger.error(f"Sync failed: {str(e)}", extra=extra)
        # Update sync history with error
        async with db_session as session:
            db = await get_db_ops()
            data = {
                "status": SyncStatus.FAILED,
                "end_time": get_utc_now(),
                "success": False,
                "error_details": str(e)
            }
            # Fix: Pass session and tenant_id explicitly
            await db.update_sync_history(session, sync_id, tenant_id, data)
    
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
    
    # Create an asyncio Event for cancellation that can be passed to the client
    cancellation_event = asyncio.Event()
    
    # DIAGNOSTIC: Log the initial state of the event - Fix: Use sync_logger instead of logger
    sync_logger.info(f"Created cancellation event for sync {sync_id}, is_set: {cancellation_event.is_set()}")
    
    # Create a checker task that monitors the sync_cancellation_flags dictionary
    async def cancellation_checker():
        # Fix: Use sync_logger instead of logger
        sync_logger.info(f"Starting cancellation checker for sync {sync_id}")
        while True:
            if sync_id in sync_cancellation_flags and sync_cancellation_flags[sync_id]:
                # Fix: Use sync_logger instead of logger
                sync_logger.info(f"Cancellation flag found for sync {sync_id}, setting event")
                cancellation_event.set()
                break
            await asyncio.sleep(0.5)  # Check every half second
    
    # Start the checker in the background
    checker_task = asyncio.create_task(cancellation_checker())
    
    try:
        # Set the cancellation flag on the orchestrator
        # Fix: Use sync_logger instead of logger
        sync_logger.info(f"Setting orchestrator.cancellation_flag for sync {sync_id}")
        orchestrator.cancellation_flag = cancellation_event
        
        # Run sync operation with cancellation support
        await orchestrator.run_sync()
        
    finally:
        # Clean up our checker task
        checker_task.cancel()
        try:
            await checker_task
        except asyncio.CancelledError:
            pass

@router.post("/start", response_model=SyncResponse)
async def start_sync(
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
    current_user: Any = Depends(get_current_user)  # Keep for auth check
):
    """Start Okta data synchronization"""
    tenant_id = get_tenant_id()
    db = await get_db_ops()
    
    # Check if sync is already running
    # Fix: Pass session and tenant_id explicitly
    active_sync = await db.get_active_sync(session, tenant_id)
    
    if active_sync:
        return SyncResponse(
            status="already_running",
            message="Sync operation already in progress",
            sync_id=active_sync.id,
            progress=active_sync.progress_percentage
        )
    
    # Create new sync history record
    # Fix: Pass session and tenant_id explicitly
    sync_history = await db.create_sync_history(session, tenant_id)
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
    tenant_id = get_tenant_id()
    db = await get_db_ops()
    
    # First check for active sync
    # Fix: Pass session and tenant_id explicitly 
    active_sync = await db.get_active_sync(session, tenant_id)
    
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
                "policies": active_sync.policies_count or 0,
                "devices": active_sync.devices_count or 0
            },
            start_time=active_sync.start_time
        )
    
    # If no active sync, get last completed sync
    # Fix: Pass session and tenant_id explicitly
    last_sync = await db.get_last_completed_sync(session, tenant_id)
    
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
                "policies": last_sync.policies_count or 0,
                "devices": last_sync.devices_count or 0
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
    tenant_id = get_tenant_id()
    db = await get_db_ops()
    
    # Get active sync
    # Fix: Pass session and tenant_id explicitly
    active_sync = await db.get_active_sync(session, tenant_id)
    
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
    data = {
        "status": SyncStatus.CANCELED,
        "end_time": get_utc_now(),
        "success": False,
        "error_details": "Cancellation requested by user"
    }
    # Fix: Pass session, sync_id and tenant_id explicitly
    await db.update_sync_history(session, sync_id, tenant_id, data)
    
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
    tenant_id = get_tenant_id()
    db = await get_db_ops()
    
    # Fix: Pass session, tenant_id and limit explicitly
    history = await db.get_sync_history(session, tenant_id, limit)
    
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
                "policies": entry.policies_count or 0,
                "devices": entry.devices_count or 0
            },
            start_time=entry.start_time,
            end_time=entry.end_time
        )
        for entry in history
    ]