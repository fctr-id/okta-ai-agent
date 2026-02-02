# Specification: CLI Modernization & UI Query History

## Overview
This track aims to bring existing CLI utilities up to parity with the v2.0 multi-agent architecture and introduce a "Query History & Favorites" feature in the Web UI.

## Feature 1: CLI Utilities Update
- **Parity:** Update `scripts/` (e.g., `agent.py`) to use the `Orchestrator` and its specialized agents (Router, SQL, API, Synthesis).
- **New Flag:** Add `--scriptonly` to the CLI. When enabled, the agent should perform discovery, generate the final execution script, and print it to `stdout` (or save to file) without executing it against the Okta tenant.
- **Sync Support:** Ensure CLI sync scripts leverage the latest `DatabaseOperations` and parallel processing logic.

## Feature 2: UI Query History & Sidebar
- **Storage:** Create a new SQLite table `query_history` to store:
    - `id`, `query_text`, `final_script`, `results_summary`, `is_favorite` (boolean), `created_at`.
- **Sidebar (Vue.js):**
    - Implement a sidebar showing a rolling queue of the last 10 unique queries.
    - Sort by `created_at` descending.
- **Actions:**
    - **Favorite:** A button to toggle `is_favorite`. Limit favorites to 10 (validation required).
    - **Re-execute:** A button that retrieves the `final_script` from the database and executes it directly, bypassing the multi-agent discovery phase.
- **Integration:** After every successful UI query execution, save the query, script, and summary to the `query_history` table.

## Constraints
- **Minimal Code Changes:** Use existing `src/core/agents/orchestrator.py` logic.
- **Data Integrity:** Favorites must be protected from being overwritten in the rolling queue.
- **Security:** Re-executing saved scripts must still pass through the existing security validation layer.
