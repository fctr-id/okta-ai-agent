# Implementation Plan: CLI Modernization & UI Query History

## Phase 1: Database & Backend Foundation
- [x] Task: Create `query_history` table in SQLite.
    - [x] Define SQLAlchemy model for `QueryHistory`.
    - [x] Implement migration/table creation logic in `DatabaseOperations.init_db`.
- [x] Task: Implement backend service for Query History.
    - [x] Create `src/api/routers/history.py` to handle GET (list 10), POST (save), and PATCH (toggle favorite).
    - [x] Add endpoint for "Direct Execution" of a saved script.
- [x] Task: Conductor - User Manual Verification 'Phase 1: Database & Backend Foundation' (Protocol in workflow.md)

## Phase 2: CLI Tools Modernization
- [x] Task: Update CLI Agent logic.
    - [x] Modify `scripts/agent.py` to import and use `execute_multi_agent_query` from `src.core.agents.orchestrator`.
    - [x] Implement the `--scriptonly` flag handling.
- [x] Task: Validate CLI synchronization.
    - [x] Ensure `scripts/fetch_data.py` (or equivalent) uses the v2.0 `DatabaseOperations`.
- [x] Task: Conductor - User Manual Verification 'Phase 2: CLI Tools Modernization' (Protocol in workflow.md)

## Phase 3: UI Implementation (Vue.js)
- [x] Task: Implement Sidebar Component.
    - [x] Create `HistorySidebar.vue` to display the rolling queue.
    - [x] Add "Favorite" toggle and "Execute" buttons.
- [x] Task: Integrate Query Execution with History.
    - [x] Update the main query execution flow in the UI to call the save-history endpoint upon success.
    - [x] Link "Execute" button to the direct script execution endpoint.
- [x] Task: Final UI/UX Polish.
    - [x] Ensure "Max 10 Favorites" limit is enforced and visually indicated.
- [x] Task: Conductor - User Manual Verification 'Phase 3: UI Implementation (Vue.js)' (Protocol in workflow.md)
