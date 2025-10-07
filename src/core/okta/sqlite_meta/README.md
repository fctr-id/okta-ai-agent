# SQLite Metadata Module

**Location:** `src/core/okta/sqlite_meta/`  
**Database:** `./sqlite_db/okta_meta.db` (project root)

## Purpose

Lightweight operational metadata storage for:
- ✅ User authentication (passwords, sessions)
- ✅ Sync status tracking (for both SQLite and GraphDB modes)
- ✅ Session management

**Key Point:** This is **NOT** for business data (users, groups, apps). Business data goes to GraphDB.

---

## Architecture

```
src/core/okta/sqlite_meta/          ← Code location
├── __init__.py                      ← Module exports
├── schema.sql                       ← Database schema definition
├── operations.py                    ← CRUD operations
└── README.md                        ← This file

./sqlite_db/okta_meta.db             ← Database file (actual data)
```

**Separation:**
- Code lives in `src/core/okta/sqlite_meta/` (versioned in git)
- Database lives in `./sqlite_db/okta_meta.db` (NOT in git)

---

## Tables

### 1. `local_users` - Authentication
```sql
CREATE TABLE local_users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE,
    password_hash TEXT,      -- Argon2 hashed
    email TEXT,
    is_active BOOLEAN,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

### 2. `sync_history` - Sync Status Tracking
```sql
CREATE TABLE sync_history (
    id INTEGER PRIMARY KEY,
    tenant_id TEXT,
    sync_type TEXT,          -- 'sqlite' or 'graphdb'
    status TEXT,             -- 'running', 'completed', 'failed', 'canceled'
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    success BOOLEAN,
    error_details TEXT,
    users_count INTEGER,
    groups_count INTEGER,
    apps_count INTEGER,
    policies_count INTEGER,
    devices_count INTEGER,
    progress_percentage INTEGER,
    process_id TEXT,
    graphdb_version INTEGER, -- GraphDB version number (if applicable)
    graphdb_promoted BOOLEAN -- Whether staging was promoted
);
```

### 3. `sessions` - User Sessions
```sql
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    user_id INTEGER,
    created_at TIMESTAMP,
    expires_at TIMESTAMP,
    data TEXT                -- JSON blob
);
```

---

## Usage

### Initialize Database

```python
from src.core.okta.sqlite_meta import get_metadata_ops

# Get singleton instance
meta_ops = get_metadata_ops()

# Initialize schema (creates tables if they don't exist)
await meta_ops.init_db()
```

### Track Sync Status (GraphDB Mode)

```python
from src.core.okta.sqlite_meta import get_metadata_ops

meta_ops = get_metadata_ops()

# Start sync
sync_id = await meta_ops.create_sync_record(
    tenant_id="my-tenant",
    sync_type="graphdb"  # or "sqlite"
)

# Update progress
await meta_ops.update_sync_record(sync_id, {
    "progress_percentage": 50,
    "users_count": 1500,
    "groups_count": 25
})

# Mark complete (success)
await meta_ops.update_sync_record(sync_id, {
    "status": "completed",
    "end_time": datetime.now(timezone.utc),
    "success": True,
    "graphdb_version": 2,
    "graphdb_promoted": True
})

# Mark failed
await meta_ops.update_sync_record(sync_id, {
    "status": "failed",
    "end_time": datetime.now(timezone.utc),
    "success": False,
    "error_details": "Connection timeout"
})
```

### Query Sync Status (API Endpoint)

```python
from src.core.okta.sqlite_meta import get_metadata_ops

meta_ops = get_metadata_ops()

# Get currently running sync
active = await meta_ops.get_active_sync("my-tenant")

# Get last completed sync
last = await meta_ops.get_last_completed_sync("my-tenant")

# Get history
history = await meta_ops.get_sync_history("my-tenant", limit=10)
```

---

## Integration Points

### Frontend
```javascript
// Polls /api/sync/status every 15 seconds
fetch('/api/sync/status')
  .then(res => res.json())
  .then(data => {
    // data.status: 'running', 'completed', 'failed'
    // data.progress: 0-100
    // data.entity_counts: { users, groups, apps }
  });
```

### Backend API (`src/api/routers/sync.py`)
```python
from src.core.okta.sqlite_meta import get_metadata_ops

@router.get("/status")
async def get_sync_status():
    meta_ops = get_metadata_ops()
    
    # Check for active sync first
    active = await meta_ops.get_active_sync(tenant_id)
    if active:
        return SyncResponse(
            status=active['status'],
            progress=active['progress_percentage'],
            entity_counts={...}
        )
    
    # Otherwise return last completed
    last = await meta_ops.get_last_completed_sync(tenant_id)
    return SyncResponse(...)
```

### GraphDB Orchestrator (`src/core/okta/graph_db/engine.py`)
```python
from src.core.okta.sqlite_meta import get_metadata_ops

class GraphDBOrchestrator:
    async def run_sync(self):
        meta_ops = get_metadata_ops()
        
        # Create sync record
        sync_id = await meta_ops.create_sync_record(
            self.tenant_id, 
            "graphdb"
        )
        
        try:
            # ... run sync to GraphDB ...
            counts = await self._sync_all_entities()
            
            # Report success
            await meta_ops.update_sync_record(sync_id, {
                "status": "completed",
                "users_count": counts['users'],
                "success": True
            })
            
        except Exception as e:
            # Report failure
            await meta_ops.update_sync_record(sync_id, {
                "status": "failed",
                "error_details": str(e),
                "success": False
            })
```

---

## Benefits

**Why SQLite for metadata?**
- ✅ Small dataset (~10MB max)
- ✅ Relational/tabular data (not graph)
- ✅ Low query volume
- ✅ ACID transactions for auth
- ✅ Familiar, battle-tested technology
- ✅ No external dependencies

**Why separate from business data?**
- ✅ Clear separation of concerns
- ✅ GraphDB optimized for graph queries
- ✅ SQLite optimized for operational metadata
- ✅ Independent scaling
- ✅ Different backup strategies

---

## File Locations

| Component | Location | Purpose |
|-----------|----------|---------|
| **Code** | `src/core/okta/sqlite_meta/` | Module implementation |
| **Schema** | `src/core/okta/sqlite_meta/schema.sql` | Table definitions |
| **Database** | `./sqlite_db/okta_meta.db` | Actual data storage |
| **Old DB** | `./sqlite_db/okta_sync.db` | Legacy (being phased out) |

---

## Security

**Sensitive Data:**
- Password hashes (Argon2)
- Session tokens
- User emails

**Protections:**
- ❌ Never commit `okta_meta.db` to git
- ✅ File permissions: 600 (owner read/write only)
- ✅ Use environment variables for sensitive config
- ✅ Regular backups recommended
- ✅ Encrypt database file in production (optional)

**.gitignore entries:**
```
sqlite_db/okta_meta.db
sqlite_db/okta_meta.db-wal
sqlite_db/okta_meta.db-shm
```

---

**Last Updated:** October 6, 2025  
**Module Version:** 1.0  
**Phase:** 3 (Infrastructure Complete)
