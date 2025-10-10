"""
Router for Okta data synchronization operations (GraphDB only).
Provides endpoints to:
- Start GraphDB sync process
- Check sync status
- Cancel running sync
- Get sync history
"""
from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel
from typing import Dict, Optional, List, Any
import asyncio
from datetime import datetime, timezone

from src.config.settings import settings
from src.core.security.dependencies import get_current_user
from src.core.okta.sqlite_meta import get_metadata_ops
from src.utils.logging import get_logger

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

# Store active sync processes for cancellation
active_syncs = {}
sync_cancellation_flags = {}

async def run_graphdb_sync_operation(sync_id: int):
    """Run the Okta → GraphDB sync operation in background"""
    tenant_id = get_tenant_id()
    extra = {"tenant_id": tenant_id}
    sync_logger.info(f"Starting GraphDB sync for sync_id: {sync_id}", extra=extra)
    
    # Get metadata operations
    meta_ops = get_metadata_ops()
    
    # Create cancellation event
    cancellation_event = asyncio.Event()
    sync_cancellation_flags[sync_id] = cancellation_event
    
    try:
        # Update sync status to running
        await meta_ops.update_sync_record(sync_id, {"status": "running"})
        
        # Store in active syncs
        active_syncs[sync_id] = {
            "tenant_id": tenant_id,
            "cancellation_event": cancellation_event
        }
        
        # Import GraphDB orchestrator
        from src.core.okta.graph_db.engine import GraphDBOrchestrator
        
        # Create orchestrator with cancellation support
        orchestrator = GraphDBOrchestrator(
            tenant_id=tenant_id,
            cancellation_flag=cancellation_event,
            use_versioning=True
        )
        
        sync_logger.info("Starting GraphDB sync via orchestrator", extra=extra)
        
        # Run the sync - pass the sync_id so orchestrator updates the same record
        counts = await orchestrator.run_sync(auto_promote=True, sync_id=sync_id)
        
        sync_logger.info(f"GraphDB sync completed: {counts}", extra=extra)
        
        # Note: The orchestrator already marked the sync as completed in metadata
        # No need to update here - it's already done
            
    except asyncio.CancelledError:
        sync_logger.info(f"GraphDB sync was cancelled for sync_id: {sync_id}", extra=extra)
        await meta_ops.update_sync_record(sync_id, {
            "status": "canceled",
            "end_time": get_utc_now(),
            "success": False,
            "error_details": "Sync cancelled by user"
        })
        
    except Exception as e:
        sync_logger.error(f"GraphDB sync failed for sync_id {sync_id}: {str(e)}", extra=extra, exc_info=True)
        await meta_ops.update_sync_record(sync_id, {
            "status": "failed",
            "end_time": get_utc_now(),
            "success": False,
            "error_details": str(e)
        })
    
    finally:
        # Clean up
        if sync_id in active_syncs:
            del active_syncs[sync_id]
        if sync_id in sync_cancellation_flags:
            del sync_cancellation_flags[sync_id]

@router.post("/start", response_model=SyncResponse)
async def start_sync(
    background_tasks: BackgroundTasks,
    current_user: Any = Depends(get_current_user)
):
    """Start Okta → GraphDB data synchronization"""
    try:
        tenant_id = get_tenant_id()
        sync_logger.info(f"Sync start requested for tenant: {tenant_id}")
        
        meta_ops = get_metadata_ops()
        
        # Check if sync is already running
        active_sync = await meta_ops.get_active_sync(tenant_id)
        
        if active_sync:
            sync_logger.warning(f"Sync already running: {active_sync['id']}")
            return SyncResponse(
                status="already_running",
                message="GraphDB sync operation already in progress",
                sync_id=active_sync["id"],
                progress=active_sync.get("progress_percentage", 0)
            )
        
        # Create new sync history record
        sync_id = await meta_ops.create_sync_record(tenant_id, sync_type="graphdb")
        sync_logger.info(f"Created sync record: {sync_id}")
        
        # Start sync process in background
        background_tasks.add_task(run_graphdb_sync_operation, sync_id)
        sync_logger.info(f"Added background task for sync_id: {sync_id}")
        
        return SyncResponse(
            status="started",
            message="GraphDB sync operation started",
            sync_id=sync_id,
            progress=0
        )
    except Exception as e:
        sync_logger.error(f"Failed to start sync: {e}", exc_info=True)
        raise

@router.get("/status", response_model=SyncResponse)
async def get_sync_status(
    current_user: Any = Depends(get_current_user)
):
    """Get current GraphDB sync status or last completed sync"""
    tenant_id = get_tenant_id()
    meta_ops = get_metadata_ops()
    
    # First check for active sync
    active_sync = await meta_ops.get_active_sync(tenant_id)
    
    sync_logger.debug(f"Active sync query result: {active_sync}")
    
    if active_sync:
        sync_logger.debug(f"Returning active sync: {active_sync['id']}, status: {active_sync['status']}")
        return SyncResponse(
            status=active_sync["status"],
            message=f"GraphDB sync in progress: {active_sync.get('progress_percentage', 0)}% complete",
            sync_id=active_sync["id"],
            progress=active_sync.get("progress_percentage", 0),
            entity_counts={
                "users": active_sync.get("users_count") or 0,
                "groups": active_sync.get("groups_count") or 0,
                "applications": active_sync.get("apps_count") or 0,
                "policies": active_sync.get("policies_count") or 0,
                "devices": active_sync.get("devices_count") or 0
            },
            start_time=active_sync.get("start_time")
        )
    
    # If no active sync, get last completed sync
    last_sync = await meta_ops.get_last_completed_sync(tenant_id)
    
    sync_logger.debug(f"Last completed sync query result: {last_sync}")
    
    if last_sync:
        sync_logger.info(f"Returning last completed sync: {last_sync['id']}, status: {last_sync['status']}, counts: users={last_sync.get('users_count')}, groups={last_sync.get('groups_count')}")
        return SyncResponse(
            status=last_sync["status"],
            message="Latest GraphDB sync information",
            sync_id=last_sync["id"],
            progress=100 if last_sync["status"] == "completed" else None,
            entity_counts={
                "users": last_sync.get("users_count") or 0,
                "groups": last_sync.get("groups_count") or 0,
                "applications": last_sync.get("apps_count") or 0,
                "policies": last_sync.get("policies_count") or 0,
                "devices": last_sync.get("devices_count") or 0
            },
            start_time=last_sync.get("start_time"),
            end_time=last_sync.get("end_time")
        )
    
    sync_logger.warning("No sync history found")
    return SyncResponse(
        status="none",
        message="No GraphDB sync history available"
    )

@router.post("/cancel", response_model=SyncResponse)
async def cancel_sync(
    current_user: Any = Depends(get_current_user)
):
    """Cancel currently running GraphDB sync operation"""
    tenant_id = get_tenant_id()
    meta_ops = get_metadata_ops()
    
    # Get active sync
    active_sync = await meta_ops.get_active_sync(tenant_id)
    
    if not active_sync:
        return SyncResponse(
            status="not_running",
            message="No GraphDB sync operation currently running"
        )
    
    sync_id = active_sync["id"]
    
    # Set cancellation flag
    if sync_id in sync_cancellation_flags:
        cancellation_event = sync_cancellation_flags[sync_id]
        cancellation_event.set()
        sync_logger.info(f"Cancellation requested for GraphDB sync {sync_id}")
    
    # Update sync history to mark as cancellation requested
    await meta_ops.update_sync_record(sync_id, {
        "status": "canceled",
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
    current_user: Any = Depends(get_current_user)  # Keep for auth check
):
    """Get sync history for the tenant"""
    tenant_id = get_tenant_id()
    meta_ops = await get_metadata_ops()
    
    history = await meta_ops.get_sync_history(tenant_id, limit)
    
    return [
        SyncResponse(
            status=entry["status"],
            message=f"Sync {'completed successfully' if entry.get('success') else 'failed' if entry['status'] == 'failed' else entry['status']}",
            sync_id=entry["id"],
            progress=100 if entry["status"] == "completed" else entry.get("progress_percentage", 0),
            entity_counts={
                "users": entry.get("users_count") or 0,
                "groups": entry.get("groups_count") or 0,
                "applications": entry.get("apps_count") or 0,
                "policies": entry.get("policies_count") or 0,
                "devices": entry.get("devices_count") or 0
            },
            start_time=entry.get("start_time"),
            end_time=entry.get("end_time")
        )
        for entry in history
    ]