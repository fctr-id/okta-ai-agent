# Product Guidelines: Tako AI Agent for Okta

## Development Principles
- **Minimal Intervention:** Prioritize code changes that integrate naturally with the existing multi-agent architecture.
- **Backward Compatibility:** Ensure that new features (CLI, Sidebar) do not break the core ReAct or sync logic.
- **Deterministic First:** All AI-generated outputs must be validated or "self-healed" before being presented to the user or stored.

## User Experience (UI)
- **Context Preservation:** The UI should help users recall and reuse successful queries (Sidebar/History).
- **Transparency:** Clearly distinguish between "Real-time Discovery" (ReAct) and "Cached Execution" (Saved Scripts).
- **Efficiency:** Minimize clicks for repetitive tasks (Execute button).

## CLI Experience
- **Utility over Ornament:** The CLI tools should be fast, stable, and support pipeline-friendly flags (like `--scriptonly`).
- **Parity:** Command-line utilities must leverage the same specialized agents (Router, SQL, API) as the Web UI to ensure consistent results.

## Quality Standards
- **Silent Security:** All database operations and API calls must adhere to the existing read-only-by-default and security validation layers.
- **Data Integrity:** Saved queries and scripts in SQLite must be structured to prevent corruption or runaway execution.
