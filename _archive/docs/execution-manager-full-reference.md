# Execution Manager with Approval Workflow Specification

**Version:** 1.0  
**Date:** November 8, 2025  
**Status:** Draft Specification

---

## Executive Summary

This document specifies a minimal, lightweight execution manager for the Tako AI ReAct agent that:
1. **Stores validated working code** from multi-step operations
2. **Enables human-in-the-loop approvals** via sandbox testing and state persistence
3. **Executes on exact approved entities** without re-fetching data

**Core Philosophy:** The ReAct agent handles orchestration and reasoning. The execution manager is a **state storage and code library** - nothing more.

---

## Architecture Overview

### Components

```
┌─────────────────────────────────────────────────────────────────┐
│                        ReAct Agent                              │
│  (Orchestration, Reasoning, Tool Calling)                       │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         │ Uses
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│                  Code Library Manager                           │
│  (State Storage, Code Storage, Approval Tracking)               │
├─────────────────────────────────────────────────────────────────┤
│  • Store validated code from sandbox tests                      │
│  • Store entity IDs from READ operations                        │
│  • Track approval status                                        │
│  • Persist state to SQLite for pause/resume                     │
└─────────────────────────────────────────────────────────────────┘
```

### Design Principles

1. **Minimal Code** (~200 lines vs 3,900 lines)
2. **ReAct-First** - Agent decides, manager stores
3. **Immutable After Approval** - No re-fetching of entities
4. **Stateful** - Supports pause/resume for approvals

---

## Execution Workflow

### Phase 1: READ Operations (Production)

```
User Query: "Find all users reporting to John Smith and remove from Admin group"

┌─────────────────────────────────────────────────────────────────┐
│ Step 1.1: ReAct Agent Generates READ Code                      │
├─────────────────────────────────────────────────────────────────┤
│ SELECT u.id, u.email, u.first_name, u.last_name               │
│ FROM users u                                                    │
│ JOIN users manager ON u.manager_id = manager.id               │
│ WHERE manager.first_name = 'John'                              │
│   AND manager.last_name = 'Smith'                              │
│   AND u.status = 'ACTIVE'                                      │
└─────────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 1.2: Execute in PRODUCTION (Safe - READ Only)             │
├─────────────────────────────────────────────────────────────────┤
│ Result:                                                          │
│ [                                                                │
│   {"id": "00u1", "email": "alice@ex.com", "name": "Alice"},    │
│   {"id": "00u2", "email": "bob@ex.com", "name": "Bob"},        │
│   ... (25 total users)                                          │
│ ]                                                                │
└─────────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 1.3: Store in Code Library Manager                        │
├─────────────────────────────────────────────────────────────────┤
│ code_library.store_read_result(                                 │
│   step_id="step_1_find_users",                                  │
│   code="SELECT u.id, u.email...",                              │
│   entity_ids=["00u1", "00u2", ..., "00u25"],                  │
│   entity_data=[{...}, {...}, ...],  # Full records for display │
│   tested=True                                                   │
│ )                                                                │
└─────────────────────────────────────────────────────────────────┘
```

**Key Points:**
- ✅ READ operations execute immediately in production (safe)
- ✅ Entity IDs stored for later WRITE operations
- ✅ Entity data stored for approval UI display
- ✅ No re-fetching after approval

---

### Phase 2: WRITE Operations (Sandbox Testing)

```
┌─────────────────────────────────────────────────────────────────┐
│ Step 2.1: ReAct Agent Generates WRITE Code                     │
├─────────────────────────────────────────────────────────────────┤
│ def remove_users_from_group(user_ids, group_id):               │
│     for user_id in user_ids:                                   │
│         okta_api.remove_user_from_group(user_id, group_id)     │
│                                                                  │
│ # Target users from step 1                                      │
│ remove_users_from_group(                                        │
│     user_ids=["00u1", "00u2", ..., "00u25"],                  │
│     group_id="00g456xyz"  # Admin Access group                 │
│ )                                                                │
└─────────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 2.2: Create ONE Mock User in SANDBOX                      │
├─────────────────────────────────────────────────────────────────┤
│ mock_user = create_user_in_sandbox({                            │
│   "firstName": "Mock",                                          │
│   "lastName": "TestUser",                                       │
│   "email": "mock.test.1699459200@sandbox.example.com"          │
│ })                                                               │
│                                                                  │
│ mock_group = create_group_in_sandbox({                          │
│   "name": "Mock_Admin_Group_1699459200"                        │
│ })                                                               │
│                                                                  │
│ add_user_to_group(mock_user.id, mock_group.id)                 │
└─────────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 2.3: Test WRITE Code in SANDBOX                           │
├─────────────────────────────────────────────────────────────────┤
│ # Test the removal code                                         │
│ remove_user_from_group(mock_user.id, mock_group.id)            │
│                                                                  │
│ # Verify it worked                                              │
│ groups = get_user_groups(mock_user.id)                          │
│ assert mock_group.id not in [g.id for g in groups]  ✅         │
└─────────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 2.4: Cleanup Mock Entities                                │
├─────────────────────────────────────────────────────────────────┤
│ delete_user(mock_user.id)     ✅                                │
│ delete_group(mock_group.id)   ✅                                │
└─────────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 2.5: Store VALIDATED Write Code                           │
├─────────────────────────────────────────────────────────────────┤
│ code_library.store_write_code(                                  │
│   step_id="step_2_remove_from_group",                          │
│   code="def remove_users_from_group...",                       │
│   target_entity_ids=["00u1", "00u2", ..., "00u25"],  # From step 1│
│   action="REMOVE_FROM_GROUP",                                   │
│   tested=True,  # ✅ Validated in sandbox                       │
│   depends_on="step_1_find_users"                               │
│ )                                                                │
└─────────────────────────────────────────────────────────────────┘
```

**Key Points:**
- ✅ WRITE code tested with ONE mock entity in sandbox
- ✅ Code structure validated (not data)
- ✅ Mock entities always cleaned up
- ✅ Validated code stored for production execution
- ✅ Target entity IDs come from stored READ results

---

### Phase 3: Approval Request (Pause)

```
┌─────────────────────────────────────────────────────────────────┐
│ Step 3.1: ReAct Agent Requests Approval                        │
├─────────────────────────────────────────────────────────────────┤
│ raise ApprovalRequired(                                         │
│   "WRITE code validated in sandbox. "                          │
│   "25 entities will be affected. Awaiting approval..."         │
│ )                                                                │
└─────────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 3.2: Code Library Manager Persists State                  │
├─────────────────────────────────────────────────────────────────┤
│ code_library.save_state_to_db()                                 │
│                                                                  │
│ Saved to SQLite:                                                │
│ {                                                                │
│   "query_id": "uuid-123",                                       │
│   "status": "awaiting_approval",                               │
│   "read_steps": {                                               │
│     "step_1_find_users": {                                      │
│       "code": "SELECT ...",                                     │
│       "entity_ids": ["00u1", ..., "00u25"],                    │
│       "entity_data": [{...}, ...],                             │
│       "tested": true                                            │
│     }                                                            │
│   },                                                             │
│   "write_steps": {                                              │
│     "step_2_remove_from_group": {                              │
│       "code": "def remove_users...",                           │
│       "target_entity_ids": ["00u1", ..., "00u25"],            │
│       "action": "REMOVE_FROM_GROUP",                           │
│       "tested": true,                                           │
│       "depends_on": "step_1_find_users"                        │
│     }                                                            │
│   }                                                              │
│ }                                                                │
└─────────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 3.3: Frontend Displays Approval UI                        │
├─────────────────────────────────────────────────────────────────┤
│ Loads entity_data from step_1_find_users (already fetched!)    │
│                                                                  │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ 25 Users Will Be Removed from "Admin Access" Group         │ │
│ ├────────┬──────────┬──────────┬─────────────────────────────┤ │
│ │ Select │FirstName │LastName  │Email                        │ │
│ ├────────┼──────────┼──────────┼─────────────────────────────┤ │
│ │   ✓    │Alice     │Johnson   │alice@example.com            │ │
│ │   ✓    │Bob       │Williams  │bob@example.com              │ │
│ │   ✓    │Carol     │Davis     │carol@example.com            │ │
│ │   ✓    │... (25 total)                                     │ │
│ └────────┴──────────┴──────────┴─────────────────────────────┘ │
│                                                                  │
│ [✅ Approve All] [❌ Reject] [📝 Approve Selected]               │
└─────────────────────────────────────────────────────────────────┘
```

**Key Points:**
- ✅ Agent pauses execution (PydanticAI `ApprovalRequired`)
- ✅ State persisted to SQLite (can resume later)
- ✅ Frontend shows entity_data from READ step (no re-fetch!)
- ✅ User can approve all, reject, or cherry-pick

---

### Phase 4: Execute in Production (After Approval)

```
┌─────────────────────────────────────────────────────────────────┐
│ Step 4.1: User Approves                                        │
├─────────────────────────────────────────────────────────────────┤
│ User clicks "Approve All" in frontend                           │
│                                                                  │
│ Frontend sends:                                                 │
│ POST /api/approval/uuid-123/approve                             │
│ {                                                                │
│   "approved": true,                                             │
│   "approved_entity_ids": ["00u1", "00u2", ..., "00u25"]       │
│ }                                                                │
└─────────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 4.2: Resume ReAct Agent with Approval                     │
├─────────────────────────────────────────────────────────────────┤
│ # Load saved state                                              │
│ code_library = CodeLibraryManager.load_from_db("uuid-123")     │
│                                                                  │
│ # Create approval result                                        │
│ approval = DeferredToolResults()                                │
│ approval.approvals[tool_call_id] = True                         │
│                                                                  │
│ # Resume agent                                                  │
│ result = await agent.run(                                       │
│   message_history=original_messages,                           │
│   deferred_tool_results=approval                               │
│ )                                                                │
└─────────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 4.3: Execute WRITE Code on Approved Entity IDs            │
├─────────────────────────────────────────────────────────────────┤
│ # Get validated code                                            │
│ write_step = code_library.write_steps["step_2_remove_from_group"]│
│ validated_code = write_step["code"]                             │
│                                                                  │
│ # Get approved entity IDs (from approval, NOT re-fetching!)    │
│ approved_ids = approval_response["approved_entity_ids"]         │
│                                                                  │
│ # Execute in PRODUCTION                                         │
│ for entity_id in approved_ids:                                 │
│     remove_user_from_group(                                     │
│         user_id=entity_id,                                      │
│         group_id="00g456xyz"                                    │
│     )                                                            │
│                                                                  │
│ Result: ✅ 25 users removed from Admin Access group             │
└─────────────────────────────────────────────────────────────────┘
```

**Key Points:**
- ✅ Execute on STORED entity IDs (from approval)
- ✅ NO re-fetching of users
- ✅ Use VALIDATED code (tested in sandbox)
- ✅ User approved THESE SPECIFIC entities

---

## Code Library Manager Interface

### Core Data Structure

```python
from typing import Dict, List, Any, Optional, Literal
from pydantic import BaseModel
from datetime import datetime
import json
import sqlite3

class ReadStepResult(BaseModel):
    """Result from a READ operation"""
    step_id: str
    code: str                           # The SQL/API code executed (stored for refresh)
    entity_ids: List[str]               # IDs of entities found
    entity_data: List[Dict[str, Any]]   # Full entity data for display
    tested: bool = True                 # Always true for READ
    record_count: int
    timestamp: datetime                 # When data was fetched (for staleness check)
    
    def get_age_hours(self) -> float:
        """Get age of data in hours"""
        return (datetime.now() - self.timestamp).total_seconds() / 3600

class WriteStepCode(BaseModel):
    """Validated WRITE code from sandbox testing"""
    step_id: str
    code: str                           # The validated code
    target_entity_ids: List[str]        # From dependent READ step
    action: str                         # "CREATE", "UPDATE", "DELETE", "REMOVE_FROM_GROUP"
    tested: bool                        # True after sandbox validation
    depends_on: str                     # ID of READ step providing entities
    timestamp: datetime

class ApprovalState(BaseModel):
    """Approval status and approved entities"""
    approved: bool
    approved_entity_ids: List[str]      # Specific entities user approved
    rejected_entity_ids: List[str] = []
    timestamp: datetime
    notes: Optional[str] = None

class CodeLibraryManager:
    """
    Minimal state storage for ReAct agent multi-step operations.
    
    Responsibilities:
    1. Store validated code from sandbox tests
    2. Store entity IDs from READ operations
    3. Track approval status
    4. Persist state for pause/resume
    
    NOT Responsible For:
    - Orchestration (ReAct agent does this)
    - Code execution (tools do this)
    - Complex logic (ReAct agent decides)
    """
    
    def __init__(self, query_id: str, correlation_id: str):
        self.query_id = query_id
        self.correlation_id = correlation_id
        self.read_steps: Dict[str, ReadStepResult] = {}
        self.write_steps: Dict[str, WriteStepCode] = {}
        self.approval: Optional[ApprovalState] = None
        self.status: Literal["executing", "awaiting_approval", "approved", "rejected"] = "executing"
        
    # ================================================================
    # Core Storage Methods
    # ================================================================
    
    def store_read_result(
        self,
        step_id: str,
        code: str,
        entity_ids: List[str],
        entity_data: List[Dict[str, Any]]
    ) -> None:
        """Store READ operation result (executed in production)"""
        self.read_steps[step_id] = ReadStepResult(
            step_id=step_id,
            code=code,
            entity_ids=entity_ids,
            entity_data=entity_data,
            tested=True,
            record_count=len(entity_ids),
            timestamp=datetime.now()
        )
    
    def store_write_code(
        self,
        step_id: str,
        code: str,
        target_entity_ids: List[str],
        action: str,
        depends_on: str
    ) -> None:
        """Store WRITE code validated in sandbox"""
        self.write_steps[step_id] = WriteStepCode(
            step_id=step_id,
            code=code,
            target_entity_ids=target_entity_ids,
            action=action,
            tested=True,
            depends_on=depends_on,
            timestamp=datetime.now()
        )
    
    def store_approval(
        self,
        approved: bool,
        approved_entity_ids: List[str],
        rejected_entity_ids: List[str] = None,
        notes: str = None
    ) -> None:
        """Store approval decision"""
        self.approval = ApprovalState(
            approved=approved,
            approved_entity_ids=approved_entity_ids,
            rejected_entity_ids=rejected_entity_ids or [],
            timestamp=datetime.now(),
            notes=notes
        )
        self.status = "approved" if approved else "rejected"
    
    # ================================================================
    # Retrieval Methods
    # ================================================================
    
    def get_read_result(self, step_id: str) -> Optional[ReadStepResult]:
        """Get stored READ result"""
        return self.read_steps.get(step_id)
    
    def get_write_code(self, step_id: str) -> Optional[WriteStepCode]:
        """Get validated WRITE code"""
        return self.write_steps.get(step_id)
    
    def get_entities_for_approval(self) -> List[Dict[str, Any]]:
        """
        Get entity data for approval UI display.
        Combines READ results with WRITE actions.
        """
        approval_data = []
        
        for write_step in self.write_steps.values():
            # Get entity data from dependent READ step
            read_step = self.read_steps.get(write_step.depends_on)
            if not read_step:
                continue
            
            # Combine with action
            for entity_data in read_step.entity_data:
                approval_data.append({
                    "action": write_step.action,
                    "step_id": write_step.step_id,
                    **entity_data  # Include all entity fields
                })
        
        return approval_data
    
    def get_approved_entity_ids(self) -> List[str]:
        """Get list of entity IDs user approved"""
        if not self.approval:
            return []
        return self.approval.approved_entity_ids
    
    def refresh_read_result(
        self,
        step_id: str,
        new_entity_ids: List[str],
        new_entity_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Refresh READ result with new data and compute diff.
        Returns diff summary for user review.
        """
        old_result = self.read_steps.get(step_id)
        if not old_result:
            raise ValueError(f"No READ result found for {step_id}")
        
        # Compute diff
        old_ids = set(old_result.entity_ids)
        new_ids = set(new_entity_ids)
        
        added = new_ids - old_ids
        removed = old_ids - new_ids
        unchanged = old_ids & new_ids
        
        diff = {
            "old_count": len(old_ids),
            "new_count": len(new_ids),
            "added": list(added),
            "removed": list(removed),
            "unchanged": list(unchanged),
            "changed": len(added) > 0 or len(removed) > 0,
            "old_timestamp": old_result.timestamp,
            "new_timestamp": datetime.now()
        }
        
        # Update with new data
        old_result.entity_ids = new_entity_ids
        old_result.entity_data = new_entity_data
        old_result.record_count = len(new_entity_ids)
        old_result.timestamp = datetime.now()
        
        return diff
    
    # ================================================================
    # State Persistence (SQLite)
    # ================================================================
    
    def save_state_to_db(self, db_path: str = "sqlite_db/query_states.db") -> None:
        """Save current state to SQLite for pause/resume"""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Create table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS query_states (
                query_id TEXT PRIMARY KEY,
                correlation_id TEXT,
                status TEXT,
                read_steps TEXT,
                write_steps TEXT,
                approval TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        
        # Serialize state
        state_json = {
            "read_steps": {k: v.model_dump(mode='json') for k, v in self.read_steps.items()},
            "write_steps": {k: v.model_dump(mode='json') for k, v in self.write_steps.items()},
            "approval": self.approval.model_dump(mode='json') if self.approval else None
        }
        
        # Save
        cursor.execute("""
            INSERT OR REPLACE INTO query_states 
            (query_id, correlation_id, status, read_steps, write_steps, approval, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            self.query_id,
            self.correlation_id,
            self.status,
            json.dumps(state_json['read_steps']),
            json.dumps(state_json['write_steps']),
            json.dumps(state_json['approval']),
            datetime.now().isoformat()
        ))
        
        conn.commit()
        conn.close()
    
    @classmethod
    def load_from_db(cls, query_id: str, db_path: str = "sqlite_db/query_states.db") -> 'CodeLibraryManager':
        """Load saved state from SQLite"""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT correlation_id, status, read_steps, write_steps, approval 
            FROM query_states 
            WHERE query_id = ?
        """, (query_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            raise ValueError(f"No saved state found for query_id: {query_id}")
        
        correlation_id, status, read_steps_json, write_steps_json, approval_json = row
        
        # Create manager
        manager = cls(query_id=query_id, correlation_id=correlation_id)
        manager.status = status
        
        # Deserialize
        read_steps_dict = json.loads(read_steps_json)
        manager.read_steps = {k: ReadStepResult(**v) for k, v in read_steps_dict.items()}
        
        write_steps_dict = json.loads(write_steps_json)
        manager.write_steps = {k: WriteStepCode(**v) for k, v in write_steps_dict.items()}
        
        if approval_json:
            approval_dict = json.loads(approval_json)
            manager.approval = ApprovalState(**approval_dict)
        
        return manager
```

---

## ReAct Agent Integration

### Tool: store_read_result

```python
@agent.tool
async def store_read_result(
    ctx: RunContext[OneReactDependencies],
    step_id: str,
    code: str,
    entity_ids: List[str],
    entity_data: List[Dict[str, Any]]
) -> str:
    """
    Store READ operation result.
    Call this after executing a READ query to store entity IDs for later WRITE operations.
    """
    ctx.deps.code_library.store_read_result(
        step_id=step_id,
        code=code,
        entity_ids=entity_ids,
        entity_data=entity_data
    )
    
    return f"✅ Stored READ result for {step_id}: {len(entity_ids)} entities"
```

### Tool: store_write_code

```python
@agent.tool(requires_approval=True)  # ← Requires approval
async def store_write_code(
    ctx: RunContext[OneReactDependencies],
    step_id: str,
    code: str,
    target_entity_ids: List[str],
    action: str,
    depends_on: str
) -> str:
    """
    Store WRITE code validated in sandbox.
    This tool requires approval - agent will pause after calling this.
    """
    ctx.deps.code_library.store_write_code(
        step_id=step_id,
        code=code,
        target_entity_ids=target_entity_ids,
        action=action,
        depends_on=depends_on
    )
    
    # Save state for pause/resume
    ctx.deps.code_library.status = "awaiting_approval"
    ctx.deps.code_library.save_state_to_db()
    
    return f"✅ Stored WRITE code for {step_id} (validated in sandbox). Awaiting approval for {len(target_entity_ids)} entities."
```

### Tool: execute_validated_write

```python
@agent.tool
async def execute_validated_write(
    ctx: RunContext[OneReactDependencies],
    step_id: str
) -> str:
    """
    Execute validated WRITE code in production on approved entities.
    Only callable after approval.
    """
    # Get validated code
    write_step = ctx.deps.code_library.get_write_code(step_id)
    if not write_step:
        return f"❌ No write step found: {step_id}"
    
    if not write_step.tested:
        return f"❌ Write code not validated in sandbox: {step_id}"
    
    # Get approved entity IDs
    approved_ids = ctx.deps.code_library.get_approved_entity_ids()
    if not approved_ids:
        return f"❌ No approved entities for {step_id}"
    
    # Execute in production
    results = []
    for entity_id in approved_ids:
        result = await execute_code_in_production(
            code=write_step.code,
            entity_id=entity_id
        )
        results.append(result)
    
    return f"✅ Executed {step_id} on {len(approved_ids)} approved entities"
```

---

## Deployment Modes

### SaaS Mode (Your Sandbox)

```python
# Environment configuration
TAKO_SANDBOX_URL = "https://tako-ai-sandbox.okta.com"
TAKO_SANDBOX_TOKEN = "your_sandbox_token"

CUSTOMER_PRODUCTION_URL = os.getenv("OKTA_CLIENT_ORGURL")
CUSTOMER_PRODUCTION_TOKEN = os.getenv("OKTA_API_TOKEN")

# Workflow
READ → Execute in customer production (safe)
WRITE → Test in YOUR sandbox
WRITE → Execute in customer production (after approval)
```

### Self-Hosted Mode (Customer's Sandbox)

```python
# Environment configuration
CUSTOMER_SANDBOX_URL = os.getenv("OKTA_SANDBOX_URL")
CUSTOMER_SANDBOX_TOKEN = os.getenv("OKTA_SANDBOX_TOKEN")

CUSTOMER_PRODUCTION_URL = os.getenv("OKTA_CLIENT_ORGURL")
CUSTOMER_PRODUCTION_TOKEN = os.getenv("OKTA_API_TOKEN")

# Workflow
READ → Execute in customer production (safe)
WRITE → Test in customer sandbox
WRITE → Execute in customer production (after approval)
```

---

## API Endpoints

### GET /api/approval/:queryId

Get approval request for frontend display.

**Response:**
```json
{
  "query_id": "uuid-123",
  "status": "awaiting_approval",
  "data_age_hours": 5.2,
  "data_fetched_at": "2025-11-08T09:00:00Z",
  "entities": [
    {
      "action": "REMOVE_FROM_GROUP",
      "step_id": "step_2_remove_from_group",
      "id": "00u1",
      "firstName": "Alice",
      "lastName": "Johnson",
      "email": "alice@example.com"
    },
    ...
  ],
  "write_steps": [
    {
      "step_id": "step_2_remove_from_group",
      "action": "REMOVE_FROM_GROUP",
      "code": "def remove_users_from_group...",
      "tested": true,
      "target_count": 25
    }
  ]
}
```

### POST /api/approval/:queryId/approve

Submit approval decision.

**Request:**
```json
{
  "approved": true,
  "approved_entity_ids": ["00u1", "00u2", "00u3", ...],
  "rejected_entity_ids": [],
  "notes": "Approved all 25 users"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Approval stored. Resuming execution...",
  "approved_count": 25
}
```

### POST /api/approval/:queryId/refresh

Re-execute READ query to get fresh data and show diff.

**Request:**
```json
{
  "step_id": "step_1_find_users"
}
```

**Response:**
```json
{
  "success": true,
  "diff": {
    "old_count": 25,
    "new_count": 23,
    "added": [],
    "removed": ["00u24", "00u25"],
    "unchanged": ["00u1", "00u2", ..., "00u23"],
    "changed": true,
    "old_timestamp": "2025-11-08T09:00:00Z",
    "new_timestamp": "2025-11-08T14:00:00Z"
  },
  "message": "Data refreshed. 2 users removed (no longer match criteria).",
  "new_entities": [
    {"id": "00u1", "firstName": "Alice", ...},
    {"id": "00u2", "firstName": "Bob", ...},
    ...
  ]
}
```

---

## Frontend Integration

### Approval Table Component with Refresh

```typescript
interface ApprovalEntity {
  action: string;
  step_id: string;
  id: string;
  firstName: string;
  lastName: string;
  email: string;
  [key: string]: any;
}

interface ApprovalData {
  query_id: string;
  status: string;
  data_age_hours: number;
  data_fetched_at: string;
  entities: ApprovalEntity[];
}

export const ApprovalTable = ({ queryId }: { queryId: string }) => {
  const [data, setData] = useState<ApprovalData | null>(null);
  const [entities, setEntities] = useState<ApprovalEntity[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [showDiff, setShowDiff] = useState(false);
  const [diff, setDiff] = useState<any>(null);
  
  useEffect(() => {
    // Poll for approval request
    const poll = setInterval(async () => {
      const response = await fetch(`/api/approval/${queryId}`);
      const approvalData = await response.json();
      
      if (approvalData.status === "awaiting_approval") {
        setData(approvalData);
        setEntities(approvalData.entities);
        // Auto-select all
        setSelected(new Set(approvalData.entities.map(e => e.id)));
      }
    }, 1000);
    
    return () => clearInterval(poll);
  }, [queryId]);
  
  const handleRefresh = async () => {
    setIsRefreshing(true);
    try {
      const response = await fetch(`/api/approval/${queryId}/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          step_id: data?.entities[0]?.step_id
        })
      });
      
      const result = await response.json();
      
      if (result.diff.changed) {
        setDiff(result.diff);
        setShowDiff(true);
        setEntities(result.new_entities);
        setSelected(new Set(result.new_entities.map(e => e.id)));
      } else {
        alert("Data is still current. No changes detected.");
      }
    } finally {
      setIsRefreshing(false);
    }
  };
  
  const handleApprove = async () => {
    await fetch(`/api/approval/${queryId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        approved: true,
        approved_entity_ids: Array.from(selected),
        rejected_entity_ids: entities
          .filter(e => !selected.has(e.id))
          .map(e => e.id)
      })
    });
  };
  
  const formatDataAge = (hours: number) => {
    if (hours < 1) return `${Math.round(hours * 60)} minutes ago`;
    if (hours < 24) return `${Math.round(hours)} hours ago`;
    return `${Math.round(hours / 24)} days ago`;
  };
  
  return (
    <div>
      <div className="approval-header">
        <h2>{entities.length} Entities Require Approval</h2>
        
        {data && (
          <div className="data-age-banner">
            <span className={data.data_age_hours > 24 ? "warning" : ""}>
              ⏰ Data fetched: {formatDataAge(data.data_age_hours)}
            </span>
            <button 
              onClick={handleRefresh} 
              disabled={isRefreshing}
              className="btn-refresh"
            >
              {isRefreshing ? "Refreshing..." : "🔄 Refresh Data"}
            </button>
          </div>
        )}
      </div>
      
      {showDiff && diff && (
        <div className="diff-modal">
          <h3>Data Changed Since Last Fetch</h3>
          <ul>
            <li>Previous: {diff.old_count} entities</li>
            <li>Current: {diff.new_count} entities</li>
            {diff.added.length > 0 && (
              <li>✅ Added: {diff.added.length} entities</li>
            )}
            {diff.removed.length > 0 && (
              <li>❌ Removed: {diff.removed.length} entities</li>
            )}
          </ul>
          <button onClick={() => setShowDiff(false)}>
            Continue with New Data
          </button>
        </div>
      )}
      
      <table>
        <thead>
          <tr>
            <th><input type="checkbox" onChange={toggleSelectAll} /></th>
            <th>Action</th>
            <th>First Name</th>
            <th>Last Name</th>
            <th>Email</th>
          </tr>
        </thead>
        <tbody>
          {entities.map(entity => (
            <tr key={entity.id}>
              <td>
                <input 
                  type="checkbox" 
                  checked={selected.has(entity.id)}
                  onChange={() => toggleSelect(entity.id)}
                />
              </td>
              <td>
                <Badge variant={getActionVariant(entity.action)}>
                  {entity.action}
                </Badge>
              </td>
              <td>{entity.firstName}</td>
              <td>{entity.lastName}</td>
              <td>{entity.email}</td>
            </tr>
          ))}
        </tbody>
      </table>
      
      <div className="actions">
        <Button onClick={handleApprove} disabled={selected.size === 0}>
          ✅ Approve Selected ({selected.size})
        </Button>
        <Button variant="destructive" onClick={handleRejectAll}>
          ❌ Reject All
        </Button>
      </div>
    </div>
  );
};
```

---

## Testing Strategy

### Unit Tests

```python
def test_store_read_result():
    """Test storing READ operation result"""
    manager = CodeLibraryManager(query_id="test-123", correlation_id="corr-123")
    
    manager.store_read_result(
        step_id="step_1",
        code="SELECT * FROM users",
        entity_ids=["00u1", "00u2"],
        entity_data=[
            {"id": "00u1", "email": "user1@ex.com"},
            {"id": "00u2", "email": "user2@ex.com"}
        ]
    )
    
    result = manager.get_read_result("step_1")
    assert result.record_count == 2
    assert "00u1" in result.entity_ids

def test_store_write_code():
    """Test storing validated WRITE code"""
    manager = CodeLibraryManager(query_id="test-123", correlation_id="corr-123")
    
    # First store READ result
    manager.store_read_result(
        step_id="step_1",
        code="SELECT * FROM users",
        entity_ids=["00u1", "00u2"],
        entity_data=[...]
    )
    
    # Then store WRITE code
    manager.store_write_code(
        step_id="step_2",
        code="delete_user(user_id)",
        target_entity_ids=["00u1", "00u2"],
        action="DELETE",
        depends_on="step_1"
    )
    
    write_step = manager.get_write_code("step_2")
    assert write_step.tested == True
    assert write_step.depends_on == "step_1"

def test_state_persistence():
    """Test saving and loading state from SQLite"""
    manager = CodeLibraryManager(query_id="test-123", correlation_id="corr-123")
    
    manager.store_read_result(...)
    manager.store_write_code(...)
    manager.save_state_to_db()
    
    # Load in new instance
    loaded = CodeLibraryManager.load_from_db("test-123")
    
    assert loaded.query_id == "test-123"
    assert "step_1" in loaded.read_steps
    assert "step_2" in loaded.write_steps
```

### Integration Tests

```python
async def test_full_approval_workflow():
    """Test complete READ → WRITE → Approve → Execute workflow"""
    
    # Phase 1: READ
    result = await execute_read_query("SELECT * FROM users WHERE ...")
    code_library.store_read_result(
        step_id="step_1",
        code="SELECT ...",
        entity_ids=[r['id'] for r in result],
        entity_data=result
    )
    
    # Phase 2: Test WRITE in sandbox
    mock_user = await create_mock_user_in_sandbox()
    await test_delete_code(mock_user.id)
    await cleanup_mock_user(mock_user.id)
    
    code_library.store_write_code(
        step_id="step_2",
        code="delete_user(user_id)",
        target_entity_ids=[r['id'] for r in result],
        action="DELETE",
        depends_on="step_1"
    )
    
    # Phase 3: Approval
    code_library.store_approval(
        approved=True,
        approved_entity_ids=[r['id'] for r in result]
    )
    
    # Phase 4: Execute in production
    approved_ids = code_library.get_approved_entity_ids()
    for entity_id in approved_ids:
        await execute_write_in_production(entity_id)
    
    assert len(approved_ids) == len(result)
```

---

## Security Considerations

### 1. Entity ID Immutability

**Principle:** Once entities are approved, act ONLY on those exact IDs.

**Implementation:**
```python
def execute_validated_write(step_id: str):
    # Get approved IDs from stored approval
    approved_ids = code_library.get_approved_entity_ids()
    
    # NEVER re-fetch entities
    # Act only on approved_ids
    for entity_id in approved_ids:
        execute_write_code(entity_id)
```

### 2. Code Validation

**Principle:** Only execute code validated in sandbox.

**Implementation:**
```python
def execute_write_code(step_id: str):
    write_step = code_library.get_write_code(step_id)
    
    if not write_step.tested:
        raise SecurityError("Code not validated in sandbox")
    
    # Execute validated code
    ...
```

### 3. Approval Audit Trail

**Principle:** Every approval decision logged.

**Implementation:**
```python
class ApprovalState(BaseModel):
    approved: bool
    approved_entity_ids: List[str]
    rejected_entity_ids: List[str]
    timestamp: datetime
    user_id: str  # Who approved
    notes: Optional[str]
    
    def to_audit_log(self) -> Dict:
        return {
            "event": "approval_decision",
            "approved": self.approved,
            "entity_count": len(self.approved_entity_ids),
            "user_id": self.user_id,
            "timestamp": self.timestamp.isoformat()
        }
```

---

## Performance Considerations

### 1. Memory Management

**Challenge:** Large entity datasets in memory.

**Solution:**
```python
class ReadStepResult(BaseModel):
    entity_ids: List[str]           # Always in memory (small)
    entity_data: List[Dict]         # Full data for display
    
    def get_preview_data(self) -> List[Dict]:
        """Return only fields needed for approval UI"""
        return [
            {
                "id": e["id"],
                "firstName": e.get("firstName"),
                "lastName": e.get("lastName"),
                "email": e.get("email")
            }
            for e in self.entity_data
        ]
```

### 2. Database Indexing

```sql
CREATE TABLE query_states (
    query_id TEXT PRIMARY KEY,
    correlation_id TEXT,
    status TEXT,
    read_steps TEXT,
    write_steps TEXT,
    approval TEXT,
    created_at TEXT,
    updated_at TEXT
);

-- Index for fast lookups
CREATE INDEX idx_correlation_id ON query_states(correlation_id);
CREATE INDEX idx_status ON query_states(status);
```

### 3. Cleanup

**Strategy:** Delete old query states after 7 days.

```python
def cleanup_old_states(days: int = 7):
    """Delete query states older than N days"""
    conn = sqlite3.connect("sqlite_db/query_states.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        DELETE FROM query_states 
        WHERE datetime(updated_at) < datetime('now', '-7 days')
    """)
    
    conn.commit()
    conn.close()
```

---

## Data Staleness Handling

### Problem Statement

When users take hours/days to approve operations, the original READ data can become stale:
- Users may have been deactivated
- Group memberships may have changed
- Manager assignments may have been updated
- Users may no longer match the original criteria

### Solution: Refresh on Demand

**User-Controlled Refresh** rather than forced re-validation:

```
1. Show data age: "Data fetched: 5 hours ago"
2. User decides if refresh needed
3. On refresh: Re-execute stored READ code
4. Show diff: added/removed/unchanged entities
5. User approves fresh data or cancels
```

**Benefits:**
- ✅ User controls when to refresh (trust their judgment)
- ✅ Shows exact diff (added/removed entities)
- ✅ No forced re-validation (respects user's approval intent)
- ✅ Stored READ code ensures consistent query logic

**Implementation:**

```python
# In CodeLibraryManager
def refresh_read_result(
    self,
    step_id: str,
    new_entity_ids: List[str],
    new_entity_data: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Refresh and show diff"""
    old_result = self.read_steps[step_id]
    
    diff = {
        "old_count": len(old_result.entity_ids),
        "new_count": len(new_entity_ids),
        "added": list(set(new_entity_ids) - set(old_result.entity_ids)),
        "removed": list(set(old_result.entity_ids) - set(new_entity_ids)),
        "changed": len(added) > 0 or len(removed) > 0
    }
    
    # Update with fresh data
    old_result.entity_ids = new_entity_ids
    old_result.entity_data = new_entity_data
    old_result.timestamp = datetime.now()
    
    return diff
```

**Frontend Integration:**

```typescript
// Data age banner
<div className="data-age-banner">
  <span className={data_age_hours > 24 ? "warning" : ""}>
    ⏰ Data fetched: {formatDataAge(data_age_hours)}
  </span>
  <button onClick={handleRefresh}>
    🔄 Refresh Data
  </button>
</div>

// Diff modal after refresh
{showDiff && (
  <div className="diff-modal">
    <h3>Data Changed Since Last Fetch</h3>
    <ul>
      <li>Previous: {diff.old_count} entities</li>
      <li>Current: {diff.new_count} entities</li>
      <li>✅ Added: {diff.added.length}</li>
      <li>❌ Removed: {diff.removed.length}</li>
    </ul>
    <button>Continue with New Data</button>
  </div>
)}
```

**Design Decision:**
User controls refresh - no forced staleness checks. This respects their approval intent while giving them tools to validate freshness.

---

## Migration Path

### From Current Execution Manager (3,900 lines)

**Phase 1: Run in parallel**
- Keep existing execution manager
- Add CodeLibraryManager alongside
- Test with non-critical queries

**Phase 2: Gradual migration**
- Migrate simple queries first
- Validate approval workflow
- Collect user feedback

**Phase 3: Complete replacement**
- Deprecate old execution manager
- Full cutover to CodeLibraryManager
- Remove legacy code

---

## Success Metrics

1. **Code Size:** 3,900 lines → ~200 lines (95% reduction)
2. **Approval Accuracy:** 100% (user approves exact entities shown)
3. **Sandbox Test Success Rate:** >95%
4. **Resume After Approval:** <1 second latency
5. **User Satisfaction:** Approve/reject workflow clarity
6. **Data Freshness:** User-controlled refresh with diff display

---

## Future Enhancements

### 1. Scheduled Execution

```python
class ApprovalState(BaseModel):
    approved: bool
    approved_entity_ids: List[str]
    execute_at: Optional[datetime] = None  # Schedule for later
    
    # Example: Approve now, execute during maintenance window
    approval = ApprovalState(
        approved=True,
        approved_entity_ids=["00u1", ..., "00u100"],
        execute_at=datetime(2025, 11, 9, 2, 0, 0)  # 2 AM tomorrow
    )
```

### 2. Batch Size Control

```python
class WriteStepCode(BaseModel):
    code: str
    batch_size: int = 10  # Process 10 entities at a time
    delay_between_batches: float = 1.0  # 1 second delay
    
    # Prevents rate limiting for large operations
    # User can configure: "Remove 1000 users, 10 at a time"
```

### 3. Partial Failure Handling (API-Based Operations)

**Problem:** During production execution of 100 approved entities, some may fail.

**Solution:** Continue execution and report all failures at the end (no rollback for API operations).

```python
class ExecutionResult(BaseModel):
    """Result from production execution"""
    status: Literal["completed", "partial", "failed"]
    total: int
    success_count: int
    failed_count: int
    success_ids: List[str]
    failed_details: List[Dict[str, Any]]  # {"entity_id": "00u1", "error": "..."}

async def execute_validated_write(
    step_id: str,
    code_library: CodeLibraryManager
) -> ExecutionResult:
    """
    Execute validated WRITE code on approved entities.
    Continues on errors and reports all failures at end.
    """
    write_step = code_library.get_write_code(step_id)
    approved_ids = code_library.get_approved_entity_ids()
    
    results = {
        "success": [],
        "failed": []
    }
    
    # Execute on ALL approved entities (don't stop on errors)
    for entity_id in approved_ids:
        try:
            await execute_write_code(
                code=write_step.code,
                entity_id=entity_id
            )
            results["success"].append(entity_id)
            
        except Exception as e:
            results["failed"].append({
                "entity_id": entity_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
    
    # Determine overall status
    if len(results["failed"]) == 0:
        status = "completed"
    elif len(results["success"]) == 0:
        status = "failed"
    else:
        status = "partial"
    
    return ExecutionResult(
        status=status,
        total=len(approved_ids),
        success_count=len(results["success"]),
        failed_count=len(results["failed"]),
        success_ids=results["success"],
        failed_details=results["failed"]
    )
```

**Frontend Display:**

```typescript
// After execution completes
{result.status === "partial" && (
  <div className="execution-summary">
    <h3>⚠️ Partial Success</h3>
    <p>✅ Successfully processed: {result.success_count}/{result.total}</p>
    <p>❌ Failed: {result.failed_count}/{result.total}</p>
    
    <details>
      <summary>View Failed Entities</summary>
      <table>
        <thead>
          <tr>
            <th>Entity ID</th>
            <th>Email</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody>
          {result.failed_details.map(failure => (
            <tr key={failure.entity_id}>
              <td>{failure.entity_id}</td>
              <td>{getEntityEmail(failure.entity_id)}</td>
              <td>{failure.error}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
    
    <button onClick={handleRetryFailed}>
      🔄 Retry Failed Entities ({result.failed_count})
    </button>
  </div>
)}
```

**Why No Rollback:**
- ✅ API operations are atomic per entity (not transactional)
- ✅ Okta API doesn't support batch rollback
- ✅ User sees exactly which entities succeeded/failed
- ✅ Can retry failed entities individually
- ✅ Partial success is better than all-or-nothing failure

**Retry Failed Entities:**
```python
async def retry_failed_entities(
    step_id: str,
    failed_entity_ids: List[str]
) -> ExecutionResult:
    """
    Retry execution only on previously failed entities.
    User can attempt multiple retries until all succeed or they give up.
    """
    # Re-execute only on failed IDs
    # Return new ExecutionResult with updated success/failed counts
```

### 4. Audit Trail Export

```python
def export_audit_trail(query_id: str) -> Dict:
    """Export complete audit trail for compliance"""
    manager = CodeLibraryManager.load_from_db(query_id)
    
    return {
        "query_id": query_id,
        "read_operations": [...],
        "write_operations": [...],
        "approval_decision": {...},
        "execution_results": {...}
    }
```

---

## Appendix: File Structure

```
src/
├── core/
│   ├── agents/
│   │   └── one_react_agent.py          # ReAct agent with approval tools
│   ├── orchestration/
│   │   └── code_library_manager.py     # NEW: Minimal execution manager
│   └── tools/
│       ├── sandbox_testing.py          # Sandbox test helpers
│       └── approval_workflow.py        # Approval state management
├── api/
│   └── routers/
│       └── approval.py                 # NEW: Approval API endpoints
└── data/
    └── testing/
        └── mock_entity_generator.py    # Generate mock test entities

docs/
└── execution-manager-with-approval-workflow.md  # THIS DOCUMENT

sqlite_db/
└── query_states.db                      # Persisted query states
```

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-11-08 | AI Agent | Initial specification |

---

**END OF SPECIFICATION**
