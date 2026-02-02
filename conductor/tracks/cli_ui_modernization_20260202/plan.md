# Implementation Plan: CLI Modernization & UI Query History

## Phase 1: Database & Backend Foundation
- [ ] Task: Create `query_history` table in SQLite.
    - [ ] Define SQLAlchemy model for `QueryHistory`.
    - [ ] Implement migration/table creation logic in `DatabaseOperations.init_db`.
- [ ] Task: Implement backend service for Query History.
    - [ ] Create `src/api/routers/history.py` to handle GET (list 10), POST (save), and PATCH (toggle favorite).
    - [ ] Add endpoint for "Direct Execution" of a saved script.
- [ ] Task: Conductor - User Manual Verification 'Phase 1: Database & Backend Foundation' (Protocol in workflow.md)

## Phase 2: CLI Tools Modernization
- [ ] Task: Update CLI Agent logic.
    - [ ] Modify `scripts/agent.py` to import and use `execute_multi_agent_query` from `src.core.agents.orchestrator`.
    - [ ] Implement the `--scriptonly` flag handling.
- [ ] Task: Validate CLI synchronization.
    - [ ] Ensure `scripts/fetch_data.py` (or equivalent) uses the v2.0 `DatabaseOperations`.
- [ ] Task: Conductor - User Manual Verification 'Phase 2: CLI Tools Modernization' (Protocol in workflow.md)

## Phase 3: UI Implementation (Vue.js)
- [ ] Task: Implement Sidebar Component.
    - [ ] Create `HistorySidebar.vue` to display the rolling queue.
    - [ ] Add "Favorite" toggle and "Execute" buttons.
- [ ] Task: Integrate Query Execution with History.
    - [ ] Update the main query execution flow in the UI to call the save-history endpoint upon success.
    - [ ] Link "Execute" button to the direct script execution endpoint.
- [ ] Task: Final UI/UX Polish.
    - [ ] Ensure "Max 10 Favorites" limit is enforced and visually indicated.
- [ ] Task: Conductor - User Manual Verification 'Phase 3: UI Implementation (Vue.js)' (Protocol in workflow.md)
