# Code Library Manager - LLM Implementation Spec

**Version:** 1.0  
**Date:** November 8, 2025  
**Purpose:** Minimal execution manager for ReAct agent with approval workflow

---

## 📚 Pydantic-AI Native Capabilities Used

This design leverages **built-in Pydantic-AI features** (no custom code needed):

| Feature | Pydantic-AI Documentation | Use Case in Tako |
|---------|--------------------------|------------------|
| **Deferred Tools - Human Approval** | [Docs](https://ai.pydantic.dev/deferred-tools/#human-in-the-loop-tool-approval) | Pause agent before executing WRITE operations |
| **Dependencies (RunContext)** | [Docs](https://ai.pydantic.dev/dependencies/) | Share CodeLibraryManager, Okta clients across tools |
| **Message History** | [Docs](https://ai.pydantic.dev/message-history/) | Resume agent from exact pause point after approval |
| **Tool Returns** | [Docs](https://ai.pydantic.dev/tools-advanced/#advanced-tool-returns) | Return structured responses from tools |

**Key Pattern:**
1. Mark tool with `@agent.tool(requires_approval=True)`
2. Agent returns `DeferredToolRequests` when tool is called
3. User approves/denies in UI
4. Resume with `agent.run(message_history=msgs, deferred_tool_results=approval)`

---

## 🎯 Core Objective

Build a **lightweight state storage system** (~200 lines) that:
1. Stores validated working code from sandbox tests
2. Stores entity IDs from READ operations (no re-fetching after approval)
3. Enables pause/resume for human-in-the-loop approvals
4. Executes on exact approved entities in production

**Philosophy:** ReAct agent orchestrates, Code Library Manager only stores state.

---

## 📐 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     ReAct Agent                             │
│  • Generates SQL/API code                                   │
│  • Calls tools (execute queries, test in sandbox)          │
│  • Requests approval when needed                            │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ↓ uses
┌─────────────────────────────────────────────────────────────┐
│              Code Library Manager                           │
│  • store_read_result(step_id, code, entity_ids, data)      │
│  • store_write_code(step_id, code, target_ids, action)     │
│  • store_approval(approved, entity_ids)                     │
│  • save_state_to_db() / load_from_db()                     │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔄 Execution Flow

### Phase 1: READ Operations (Production - Safe)
```
1. User Query: "Find users reporting to John Smith and remove from Admin group"
2. ReAct agent generates SQL query
3. Execute in PRODUCTION (read-only, safe)
4. Store results:
   code_library.store_read_result(
       step_id="step_1_find_users",
       code="SELECT u.id, u.email FROM users u JOIN...",
       entity_ids=["00u1", "00u2", ..., "00u25"],
       entity_data=[{full user objects for display}]
   )
```

### Phase 2: WRITE Code Testing (Sandbox)
```
5. ReAct agent generates WRITE code (remove from group)
6. Create ONE mock user in sandbox
7. Add mock user to test group
8. Test removal code on mock user
9. Verify it worked
10. Cleanup mock user
11. Store validated code:
    code_library.store_write_code(
        step_id="step_2_remove_from_group",
        code="remove_user_from_group(user_id, group_id)",
        target_entity_ids=["00u1", ..., "00u25"],  # From step 1
        action="REMOVE_FROM_GROUP",
        depends_on="step_1_find_users"
    )
```

### Phase 3: Approval (Pause)
```
12. ReAct agent raises ApprovalRequired exception
13. Code library saves state to SQLite
14. Frontend shows approval UI:
    - Entity data from step 1 (already fetched!)
    - Data age: "Fetched 5 hours ago"
    - Refresh button (optional)
    - Approve/Reject buttons
15. User approves
16. Approval stored:
    code_library.store_approval(
        approved=True,
        approved_entity_ids=["00u1", ..., "00u25"]
    )
```

### Phase 4: Execute (Production)
```
17. Load saved state from SQLite
18. Resume ReAct agent with approval
19. Execute validated WRITE code on approved entity IDs:
    for entity_id in approved_entity_ids:
        remove_user_from_group(entity_id, group_id)
20. Return results (success/failed counts)
```

---

## 📦 Data Models

```python
from typing import Dict, List, Any, Optional, Literal
from pydantic import BaseModel
from datetime import datetime

class ReadStepResult(BaseModel):
    """Stored result from READ operation"""
    step_id: str
    code: str                           # SQL/API code (stored for refresh)
    entity_ids: List[str]               # IDs for WRITE operations
    entity_data: List[Dict[str, Any]]   # Full data for approval UI
    record_count: int
    timestamp: datetime                 # For staleness check
    
    def get_age_hours(self) -> float:
        """Calculate data age in hours"""
        return (datetime.now() - self.timestamp).total_seconds() / 3600

class WriteStepCode(BaseModel):
    """Validated WRITE code from sandbox testing"""
    step_id: str
    code: str                           # Tested and validated
    target_entity_ids: List[str]        # From READ step
    action: str                         # "CREATE", "UPDATE", "DELETE", "REMOVE_FROM_GROUP"
    tested: bool = True                 # Always true after sandbox test
    depends_on: str                     # READ step ID
    timestamp: datetime

class ApprovalState(BaseModel):
    """User approval decision"""
    approved: bool
    approved_entity_ids: List[str]      # Specific entities approved
    rejected_entity_ids: List[str] = []
    timestamp: datetime
    notes: Optional[str] = None

class ExecutionResult(BaseModel):
    """Result from production execution"""
    status: Literal["completed", "partial", "failed"]
    total: int
    success_count: int
    failed_count: int
    success_ids: List[str]
    failed_details: List[Dict[str, Any]]  # [{"entity_id": "00u1", "error": "..."}]
```

---

## 🛠️ Core Class

```python
class CodeLibraryManager:
    """
    Minimal state storage for ReAct agent multi-step operations.
    File: src/core/orchestration/code_library_manager.py
    """
    
    def __init__(self, query_id: str, correlation_id: str):
        self.query_id = query_id
        self.correlation_id = correlation_id
        self.read_steps: Dict[str, ReadStepResult] = {}
        self.write_steps: Dict[str, WriteStepCode] = {}
        self.approval: Optional[ApprovalState] = None
        self.status: Literal["executing", "awaiting_approval", "approved", "rejected"] = "executing"
    
    # ================================================================
    # STORAGE METHODS
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
        """Store user approval decision"""
        self.approval = ApprovalState(
            approved=approved,
            approved_entity_ids=approved_entity_ids,
            rejected_entity_ids=rejected_entity_ids or [],
            timestamp=datetime.now(),
            notes=notes
        )
        self.status = "approved" if approved else "rejected"
    
    # ================================================================
    # RETRIEVAL METHODS
    # ================================================================
    
    def get_entities_for_approval(self) -> List[Dict[str, Any]]:
        """
        Get entity data for approval UI.
        Combines READ results with WRITE actions.
        """
        approval_data = []
        for write_step in self.write_steps.values():
            read_step = self.read_steps.get(write_step.depends_on)
            if not read_step:
                continue
            
            for entity_data in read_step.entity_data:
                approval_data.append({
                    "action": write_step.action,
                    "step_id": write_step.step_id,
                    **entity_data
                })
        return approval_data
    
    def get_approved_entity_ids(self) -> List[str]:
        """Get entity IDs user approved"""
        return self.approval.approved_entity_ids if self.approval else []
    
    # ================================================================
    # REFRESH (Data Staleness Handling)
    # ================================================================
    
    def refresh_read_result(
        self,
        step_id: str,
        new_entity_ids: List[str],
        new_entity_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Re-execute READ query and compute diff.
        Returns: {"old_count": 25, "new_count": 23, "added": [], "removed": [...], "changed": True}
        """
        old_result = self.read_steps[step_id]
        old_ids = set(old_result.entity_ids)
        new_ids = set(new_entity_ids)
        
        diff = {
            "old_count": len(old_ids),
            "new_count": len(new_ids),
            "added": list(new_ids - old_ids),
            "removed": list(old_ids - new_ids),
            "unchanged": list(old_ids & new_ids),
            "changed": len(new_ids - old_ids) > 0 or len(old_ids - new_ids) > 0,
            "old_timestamp": old_result.timestamp,
            "new_timestamp": datetime.now()
        }
        
        # Update with fresh data
        old_result.entity_ids = new_entity_ids
        old_result.entity_data = new_entity_data
        old_result.record_count = len(new_entity_ids)
        old_result.timestamp = datetime.now()
        
        return diff
    
    # ================================================================
    # PERSISTENCE (SQLite)
    # ================================================================
    
    def save_state_to_db(self, db_path: str = "sqlite_db/query_states.db") -> None:
        """Save state for pause/resume"""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS query_states (
                query_id TEXT PRIMARY KEY,
                correlation_id TEXT,
                status TEXT,
                read_steps TEXT,
                write_steps TEXT,
                approval TEXT,
                updated_at TEXT
            )
        """)
        
        cursor.execute("""
            INSERT OR REPLACE INTO query_states 
            (query_id, correlation_id, status, read_steps, write_steps, approval, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            self.query_id,
            self.correlation_id,
            self.status,
            json.dumps({k: v.model_dump(mode='json') for k, v in self.read_steps.items()}),
            json.dumps({k: v.model_dump(mode='json') for k, v in self.write_steps.items()}),
            json.dumps(self.approval.model_dump(mode='json')) if self.approval else None,
            datetime.now().isoformat()
        ))
        
        conn.commit()
        conn.close()
    
    @classmethod
    def load_from_db(cls, query_id: str, db_path: str = "sqlite_db/query_states.db") -> 'CodeLibraryManager':
        """Load saved state for resume"""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT correlation_id, status, read_steps, write_steps, approval 
            FROM query_states WHERE query_id = ?
        """, (query_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            raise ValueError(f"No saved state found for {query_id}")
        
        correlation_id, status, read_steps_json, write_steps_json, approval_json = row
        
        manager = cls(query_id, correlation_id)
        manager.status = status
        manager.read_steps = {k: ReadStepResult(**v) for k, v in json.loads(read_steps_json).items()}
        manager.write_steps = {k: WriteStepCode(**v) for k, v in json.loads(write_steps_json).items()}
        
        if approval_json:
            manager.approval = ApprovalState(**json.loads(approval_json))
        
        return manager
```

---

## 🔌 ReAct Agent Integration

### Tool 1: store_read_result

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
    Call after executing a READ query to store entity IDs for later WRITE operations.
    """
    ctx.deps.code_library.store_read_result(step_id, code, entity_ids, entity_data)
    return f"✅ Stored READ result for {step_id}: {len(entity_ids)} entities"
```

### Tool 2: store_write_code (Requires Approval)

> **📚 Pydantic-AI Native Feature**: This uses [Deferred Tools - Human-in-the-Loop Approval](https://ai.pydantic.dev/deferred-tools/#human-in-the-loop-tool-approval)  
> Agent automatically pauses when `requires_approval=True`, returns `DeferredToolRequests`, then resumes with `deferred_tool_results`.

```python
@agent.tool(requires_approval=True)  # ← PydanticAI pauses here
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
    Agent will pause after calling this - awaiting user approval.
    """
    ctx.deps.code_library.store_write_code(
        step_id, code, target_entity_ids, action, depends_on
    )
    
    ctx.deps.code_library.status = "awaiting_approval"
    ctx.deps.code_library.save_state_to_db()
    
    return f"✅ Stored WRITE code for {step_id}. Awaiting approval for {len(target_entity_ids)} entities."
```

### Tool 3: execute_validated_write

```python
@agent.tool
async def execute_validated_write(
    ctx: RunContext[OneReactDependencies],
    step_id: str
) -> ExecutionResult:
    """
    Execute validated WRITE code in production on approved entities.
    Only callable after approval.
    """
    write_step = ctx.deps.code_library.get_write_code(step_id)
    approved_ids = ctx.deps.code_library.get_approved_entity_ids()
    
    results = {"success": [], "failed": []}
    
    # Continue on errors, report all failures at end
    for entity_id in approved_ids:
        try:
            await execute_code_in_production(write_step.code, entity_id)
            results["success"].append(entity_id)
        except Exception as e:
            results["failed"].append({
                "entity_id": entity_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
    
    # Determine status
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

---

## 🌐 API Endpoints

### GET /api/approval/:queryId

```python
@router.get("/approval/{query_id}")
async def get_approval_request(query_id: str):
    """Get approval request for frontend display"""
    manager = CodeLibraryManager.load_from_db(query_id)
    
    # Get first read step for data age
    first_read = list(manager.read_steps.values())[0] if manager.read_steps else None
    
    return {
        "query_id": query_id,
        "status": manager.status,
        "data_age_hours": first_read.get_age_hours() if first_read else 0,
        "data_fetched_at": first_read.timestamp.isoformat() if first_read else None,
        "entities": manager.get_entities_for_approval()
    }
```

### POST /api/approval/:queryId/approve

> **📚 Pydantic-AI Native Feature**: Resume agent with [DeferredToolResults](https://ai.pydantic.dev/deferred-tools/#human-in-the-loop-tool-approval)  
> Maps tool_call_id to approval decision (True/False or ToolApproved/ToolDenied objects).

```python
@router.post("/approval/{query_id}/approve")
async def approve_request(query_id: str, request: ApprovalRequest):
    """Store approval and resume execution"""
    manager = CodeLibraryManager.load_from_db(query_id)
    
    manager.store_approval(
        approved=request.approved,
        approved_entity_ids=request.approved_entity_ids,
        rejected_entity_ids=request.rejected_entity_ids,
        notes=request.notes
    )
    manager.save_state_to_db()
    
    # Resume ReAct agent with approval (Pydantic-AI pattern)
    approval = DeferredToolResults()
    approval.approvals[tool_call_id] = True  # or ToolDenied("reason")
    
    result = await agent.run(
        message_history=original_messages,
        deferred_tool_results=approval
    )
    
    return {
        "success": True,
        "message": "Approval stored. Execution resumed.",
        "approved_count": len(request.approved_entity_ids)
    }
```

### POST /api/approval/:queryId/refresh

```python
@router.post("/approval/{query_id}/refresh")
async def refresh_data(query_id: str, request: RefreshRequest):
    """Re-execute READ query and show diff"""
    manager = CodeLibraryManager.load_from_db(query_id)
    
    # Get stored READ code
    read_step = manager.read_steps[request.step_id]
    
    # Re-execute in production
    new_result = await execute_read_query(read_step.code)
    
    # Compute diff
    diff = manager.refresh_read_result(
        request.step_id,
        [r['id'] for r in new_result],
        new_result
    )
    
    manager.save_state_to_db()
    
    return {
        "success": True,
        "diff": diff,
        "message": f"Data refreshed. {len(diff['removed'])} entities removed.",
        "new_entities": new_result
    }
```

---

## 🎨 Frontend (Key Components)

### Approval UI Structure

```typescript
interface ApprovalData {
  query_id: string;
  status: string;
  data_age_hours: number;
  entities: Array<{
    action: string;
    id: string;
    firstName: string;
    lastName: string;
    email: string;
  }>;
}

// Key UI Elements:
// 1. Data age banner: "⏰ Fetched 5 hours ago" + Refresh button
// 2. Entity table with checkboxes (select all/individual)
// 3. Action buttons: Approve All / Approve Selected / Reject
// 4. Diff modal (after refresh): Shows added/removed entities
```

### Example Display

```
┌─────────────────────────────────────────────────────────────┐
│ 25 Users Will Be Removed from "Admin Access" Group         │
│                                                              │
│ ⏰ Data fetched: 5 hours ago  [🔄 Refresh Data]            │
│                                                              │
│ ┌──────┬──────────┬──────────┬────────────────────┐        │
│ │  ✓   │ Action   │ Name     │ Email              │        │
│ ├──────┼──────────┼──────────┼────────────────────┤        │
│ │  ✓   │ REMOVE   │ Alice J. │ alice@example.com  │        │
│ │  ✓   │ REMOVE   │ Bob W.   │ bob@example.com    │        │
│ │  ✓   │ ...      │ ...      │ ...                │        │
│ └──────┴──────────┴──────────┴────────────────────┘        │
│                                                              │
│ [✅ Approve All] [📝 Approve Selected (25)] [❌ Reject]     │
└─────────────────────────────────────────────────────────────┘
```

---

## ⚙️ Configuration

### Environment Setup

```python
# Deployment Mode: SaaS (your sandbox) or Self-Hosted (customer's sandbox)

# SaaS Mode
TAKO_SANDBOX_URL = "https://tako-ai-sandbox.okta.com"
TAKO_SANDBOX_TOKEN = "your_sandbox_token"

# Customer Production (both modes)
CUSTOMER_PRODUCTION_URL = os.getenv("OKTA_CLIENT_ORGURL")
CUSTOMER_PRODUCTION_TOKEN = os.getenv("OKTA_API_TOKEN")

# Self-Hosted Mode (optional)
CUSTOMER_SANDBOX_URL = os.getenv("OKTA_SANDBOX_URL")  # Customer provides
CUSTOMER_SANDBOX_TOKEN = os.getenv("OKTA_SANDBOX_TOKEN")
```

### Workflow by Mode

```
SaaS Mode:
  READ  → Customer production (safe)
  WRITE → Your sandbox (test)
  WRITE → Customer production (after approval)

Self-Hosted Mode:
  READ  → Customer production (safe)
  WRITE → Customer sandbox (test)
  WRITE → Customer production (after approval)
```

---

## 🚨 Critical Design Decisions

### 1. No Re-Fetching After Approval
**Rule:** Once user approves entities, execute on THOSE EXACT entity IDs.

**Rationale:**
- User approved what they saw
- Data might change between approval and execution
- User controls refresh (optional)

### 2. No Rollback for API Operations
**Rule:** Continue on errors, report all failures at end.

**Rationale:**
- Okta API operations are atomic per entity (not transactional)
- Partial success better than all-or-nothing
- User sees exactly what failed and can retry

**Implementation:**
```python
# Execute on all approved entities
for entity_id in approved_ids:
    try:
        execute_write(entity_id)
        success.append(entity_id)
    except Exception as e:
        failed.append({"entity_id": entity_id, "error": str(e)})

# Return results (never rollback)
return ExecutionResult(
    status="partial" if failed else "completed",
    success_count=len(success),
    failed_count=len(failed),
    failed_details=failed
)
```

### 3. Stored READ Code for Refresh
**Rule:** Store READ code along with results for user-controlled refresh.

**Rationale:**
- Data may become stale (hours/days between fetch and approval)
- User decides if refresh needed
- Consistent query logic (re-execute same code)
- Show diff (added/removed entities)

### 4. Sandbox Testing with ONE Mock Entity
**Rule:** Test WRITE code with ONE mock entity, not all production entities.

**Rationale:**
- Validates code structure/syntax
- Prevents sandbox pollution
- Fast (1 entity vs 100)
- Cleanup simple (delete 1 entity)

---

## 📋 Implementation Checklist

### Phase 1: Core Library (Day 1-2)
- [ ] Create `CodeLibraryManager` class
- [ ] Implement data models (ReadStepResult, WriteStepCode, ApprovalState)
- [ ] Implement storage methods (store_read_result, store_write_code, store_approval)
- [ ] Implement SQLite persistence (save_state_to_db, load_from_db)
- [ ] Add refresh_read_result method

### Phase 2: ReAct Integration (Day 3)
- [ ] Add CodeLibraryManager to OneReactDependencies
- [ ] Create store_read_result tool
- [ ] Create store_write_code tool (with requires_approval=True)
- [ ] Create execute_validated_write tool
- [ ] Test approval pause/resume flow

### Phase 3: API Endpoints (Day 4)
- [ ] GET /api/approval/:queryId
- [ ] POST /api/approval/:queryId/approve
- [ ] POST /api/approval/:queryId/refresh
- [ ] Test with Postman/curl

### Phase 4: Frontend (Day 5-6)
- [ ] Approval table component
- [ ] Data age banner with refresh button
- [ ] Diff modal (after refresh)
- [ ] Approval buttons (approve all/selected, reject)
- [ ] Execution result display (partial failures)

### Phase 5: Testing (Day 7)
- [ ] Unit tests for CodeLibraryManager
- [ ] Integration test: READ → Test → Approve → Execute
- [ ] Test data refresh flow
- [ ] Test partial failure handling
- [ ] Test state persistence/resume

---

## 🔍 Design Q&A

### Q1: What happens if user takes days to approve?

**Answer:** User-controlled refresh (not forced).
- Show data age: "Fetched 5 hours ago"
- User clicks "Refresh Data" if concerned
- Show diff: added/removed entities
- User approves fresh data

**Design:** Trust user judgment, give tools for validation.

### Q2: What if some entities fail during production execution?

**Answer:** Continue on errors, report all failures at end (no rollback).
- Execute on ALL approved entities
- Track success/failed separately
- Show failure details: entity ID + error message
- User can retry failed entities

**Design:** Partial success better than all-or-nothing for API operations.

### Q3: How do we test WRITE code without affecting production?

**Answer:** Sandbox testing with ONE mock entity.
- Create mock user/group in sandbox
- Test WRITE code on mock entity
- Verify it worked
- Always cleanup mock entity
- Store validated code for production

**Design:** Validates code structure without sandbox pollution.

### Q4: How do we ensure user approves exact entities that get executed?

**Answer:** Store entity IDs, never re-fetch after approval.
- READ query stores entity IDs immediately
- User approves THOSE specific IDs
- Production execution uses stored IDs (not re-fetched)
- User controls refresh (optional, before approval)

**Design:** Immutable after approval = exact approval intent respected.

---

## 📁 File Structure

```
src/core/orchestration/
  └── code_library_manager.py          # Main implementation (~200 lines)

src/core/agents/
  └── one_react_agent.py                # Add 3 tools

src/api/routers/
  └── approval.py                       # 3 endpoints

src/frontend/src/components/
  └── ApprovalTable.tsx                 # Main UI component

sqlite_db/
  └── query_states.db                   # State persistence

docs/
  └── execution-manager-implementation-spec.md  # THIS DOCUMENT
```

---

## 📊 Success Metrics

- **Code Size:** 3,900 lines → ~200 lines (95% reduction)
- **Approval Accuracy:** 100% (exact entities approved = exact entities executed)
- **Sandbox Test Rate:** >95% success
- **Resume Latency:** <1 second after approval
- **Partial Failure Handling:** Clear reporting of success/failed entities

---

## 🚀 Future Extensions

Add to this section as new questions arise:

### Extension 1: Scheduled Execution
```python
# Approve now, execute during maintenance window
approval = ApprovalState(
    approved=True,
    approved_entity_ids=[...],
    execute_at=datetime(2025, 11, 9, 2, 0, 0)  # 2 AM tomorrow
)
```

### Extension 2: Batch Size Control
```python
# Process 10 entities at a time (prevent rate limiting)
write_step = WriteStepCode(
    code="...",
    batch_size=10,
    delay_between_batches=1.0  # 1 second delay
)
```

---

**END OF IMPLEMENTATION SPEC**

*This document is designed to be extended with additional Q&A sections as implementation questions arise.*
