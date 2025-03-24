import asyncio
import sys, os
import argparse
from datetime import datetime, timezone
from pathlib import Path
import copy

# Change to project root directory
os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Make sure we can import from src
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
sys.path.append(str(project_root))

from src.config.settings import settings
from src.okta_db_sync.db.operations import DatabaseOperations
from src.okta_db_sync.db.models import SyncStatus, SyncHistory, User, UserFactor
from src.okta_db_sync.okta_client.client import OktaClientWrapper
from src.utils.logging import logger
from sqlalchemy import select, func, and_, text
from sqlalchemy.inspection import inspect

VERSION = "1.0.0"

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

def filter_model_attributes(model_class, data_dict):
    """Filter a dictionary to only include valid model attributes"""
    # Get valid column names for the model
    valid_columns = {column.key for column in inspect(model_class).columns}
    
    # Create a new dict with only valid columns
    filtered_dict = {k: v for k, v in data_dict.items() if k in valid_columns}
    
    return filtered_dict

async def process_user_factors_only(session, tenant_id, user_data):
    """Process only user factors, skipping group and app relationships"""
    try:
        user_okta_id = user_data['okta_id']
        
        # Only handle factors with upsert, skip other relationships
        factors = user_data.get('factors', [])
        
        # Count factors for logging
        factor_count = len(factors)
        
        if factors:
            for factor in factors:
                stmt = text("""
                    INSERT INTO user_factors
                    (tenant_id, user_okta_id, okta_id, factor_type, provider, status,
                    email, phone_number, device_type, device_name, platform,
                    created_at, last_updated_at, updated_at)
                    VALUES (
                        :tenant_id, :user_okta_id, :okta_id, :factor_type, :provider, :status,
                        :email, :phone_number, :device_type, :device_name, :platform,
                        :created_at, :last_updated_at, :updated_at
                    )
                    ON CONFLICT (tenant_id, user_okta_id, okta_id) 
                    DO UPDATE SET
                        factor_type = excluded.factor_type,
                        provider = excluded.provider,
                        status = excluded.status,
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
                    'tenant_id': tenant_id,
                    'user_okta_id': user_okta_id,
                    'okta_id': factor['okta_id'],
                    'factor_type': factor['factor_type'],
                    'provider': factor['provider'],
                    'status': factor['status'],
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
        return factor_count
        
    except Exception as e:
        logger.error(f"Error processing user factors for {user_data.get('okta_id')}: {str(e)}")
        raise

async def clean_users_and_factors(session, tenant_id):
    """Clean only users and factors tables"""
    try:
        # Delete factors first (foreign key dependency)
        await session.execute(text("""
            DELETE FROM user_factors 
            WHERE tenant_id = :tenant_id
        """), {'tenant_id': tenant_id})
        
        # Then delete users
        await session.execute(text("""
            DELETE FROM users 
            WHERE tenant_id = :tenant_id
        """), {'tenant_id': tenant_id})
        
        await session.commit()
        logger.info(f"Cleaned users and factors data for tenant {tenant_id}")
    except Exception as e:
        logger.error(f"Error cleaning users and factors data: {str(e)}")
        raise

async def process_batch_to_db(session, db, tenant_id, batch):
    """Process a batch of users and their factors only"""
    if not batch:
        return 0, 0
        
    try:
        total_factors = 0
        
        # Process factors for each user
        for record in batch:
            factors_count = await process_user_factors_only(session, tenant_id, record)
            total_factors += factors_count
        
        # Filter out relationship fields and process main user records
        filtered_batch = []
        for user_data in batch:
            # Create a clean copy without modifying the original
            user_copy = user_data.copy()
            
            # Remove relationship fields explicitly
            user_copy.pop('factors', None)
            user_copy.pop('app_links', None) 
            user_copy.pop('group_memberships', None)
            
            # Filter to only include valid model fields
            filtered_user = filter_model_attributes(User, user_copy)
            filtered_batch.append(filtered_user)
        
        # Process the cleaned user records
        await db.bulk_upsert(session, User, filtered_batch, tenant_id)
        
        # Return batch count and factors count
        logger.info(f"Processed {len(batch)} users with {total_factors} factors")
        return len(batch), total_factors
        
    except Exception as e:
        logger.error(f"Error processing batch of users: {str(e)}")
        raise

async def run_users_sync_only(tenant_id: str, db: DatabaseOperations, user_limit: int):
    """
    Run a sync operation for users and factors only
    
    Args:
        tenant_id: The Okta tenant ID
        db: Database operations instance
        user_limit: Maximum number of users to sync
    """
    sync_id = None
    okta_client = None
    
    try:
        # Create sync history record
        async with db.get_session() as session:
            sync_history = SyncHistory(
                tenant_id=tenant_id,
                status=SyncStatus.RUNNING,
                start_time=get_utc_now(),
                progress_percentage=0,
                entity_type=f"Users only sync (limited to {user_limit} users)"
            )
            session.add(sync_history)
            await session.commit()
            await session.refresh(sync_history)
            sync_id = sync_history.id
            
            logger.info(f"Created users-only sync record with ID: {sync_id}")
            
            # Clean only users and factors tables
            await clean_users_and_factors(session, tenant_id)
        
        # Initialize Okta client
        okta_client = OktaClientWrapper(tenant_id=tenant_id)
        await okta_client.__aenter__()
        
        # Create a counter for total users processed
        total_users = 0
        total_factors = 0
        
        # Create a processor function for handling batches directly from API to DB
        async def process_users_and_factors_only(batch_data):
            nonlocal total_users, total_factors
            
            if not batch_data:
                return
            
            # Process this batch with users and factors only
            async with db.get_session() as batch_session:
                users_count, factors_count = await process_batch_to_db(
                    batch_session, db, tenant_id, batch_data
                )
                
                # Update totals
                total_users += users_count
                total_factors += factors_count
                
                # Update sync history
                sync_history = await batch_session.get(SyncHistory, sync_id)
                if sync_history:
                    sync_history.users_count = total_users
                    sync_history.records_processed = total_users
                    await batch_session.commit()
                
                logger.info(f"Processed {users_count} User records, total: {total_users}")
        
        # Apply the limit for streaming processing
        original_list_users = okta_client.list_users
        
        async def limited_list_users(*args, **kwargs):
            if 'processor_func' in kwargs:
                original_processor = kwargs['processor_func']
                processed_count = [0]
                
                async def limited_processor(batch):
                    if processed_count[0] >= user_limit:
                        return
                    if processed_count[0] + len(batch) > user_limit:
                        limited_batch = batch[:user_limit - processed_count[0]]
                        processed_count[0] = user_limit
                        await original_processor(limited_batch)
                    else:
                        processed_count[0] += len(batch)
                        await original_processor(batch)
                
                kwargs['processor_func'] = limited_processor
                return await original_list_users(*args, **kwargs)
            else:
                users = await original_list_users(*args, **kwargs)
                return users[:user_limit] if isinstance(users, list) else users
        
        okta_client.list_users = limited_list_users
        logger.info(f"Limited sync to first {user_limit} users")
        
        # Call list_users with our custom processor
        await okta_client.list_users(processor_func=process_users_and_factors_only)
        
        # Update sync history with results
        async with db.get_session() as session:
            stmt = select(SyncHistory).where(SyncHistory.id == sync_id)
            result = await session.execute(stmt)
            sync_history = result.scalars().first()
            
            if sync_history:
                sync_history.status = SyncStatus.COMPLETED
                sync_history.end_time = get_utc_now()
                sync_history.success = True
                sync_history.progress_percentage = 100
                sync_history.users_count = total_users
                await session.commit()
        
        logger.info(f"Users sync completed successfully. Synced {total_users} users with {total_factors} factors")
        return True
    
    except Exception as e:
        # Update sync history with error
        if sync_id:
            try:
                async with db.get_session() as session:
                    stmt = select(SyncHistory).where(SyncHistory.id == sync_id)
                    result = await session.execute(stmt)
                    sync_history = result.scalars().first()
                    
                    if sync_history:
                        sync_history.status = SyncStatus.FAILED
                        sync_history.end_time = get_utc_now()
                        sync_history.success = False
                        sync_history.error_details = str(e)
                        await session.commit()
            except Exception as update_error:
                logger.error(f"Failed to update sync history: {str(update_error)}")
        
        logger.error(f"Users sync failed: {str(e)}")
        return False
    
    finally:
        # Always clean up the Okta client
        if okta_client:
            await okta_client.__aexit__(None, None, None)

async def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Sync Okta users only')
    parser.add_argument('--limit', type=int, help='Limit the number of users to sync (REQUIRED)')
    args = parser.parse_args()
    
    # Require --limit parameter
    if args.limit is None:
        print("ERROR: You must specify a user limit with --limit")
        print("Example: python Fetch_okta_users_only.py --limit 20")
        sys.exit(1)
        
    if args.limit <= 0:
        print("ERROR: User limit must be a positive number")
        sys.exit(1)
    
    user_limit = args.limit
    logger.info(f"Starting Okta USERS ONLY sync v{VERSION} (limited to {user_limit} users) for tenant: {settings.tenant_id}")

    # Initialize database
    db = DatabaseOperations()
    await db.init_db()

    try:
        if not await run_users_sync_only(settings.tenant_id, db, user_limit):
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