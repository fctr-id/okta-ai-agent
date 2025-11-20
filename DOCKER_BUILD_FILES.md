# Docker Build Files - React Agent Architecture

This file lists the essential files and directories required to build the Docker image for the current "React Agent" architecture.

## Root Directory
- `Dockerfile`
- `docker-compose.yml`
- `requirements.txt`
- `.env` (Template/Example)
- `VERSION.md`
- `LICENSE`
- `README.md`

## Backend Source (`src/`)

### API Layer
- `src/api/` (Entire directory)
  - `src/api/main.py`
  - `src/api/routers/`
    - `src/api/routers/auth.py`
    - `src/api/routers/react_stream.py`
    - `src/api/routers/realtime_hybrid.py` (Check if still needed or legacy)
    - `src/api/routers/sync.py`
  - `src/api/services/`
  - `src/api/static/`

### Core Logic
- `src/core/__init__.py`
- `src/core/agents/__init__.py`
- `src/core/agents/one_react_agent.py` (Main Agent Logic)
- `src/core/agents/one_react_agent_executor.py` (Agent Executor)
- `src/core/agents/prompts/one_react_agent_prompt.txt` (System Prompt)
- `src/core/models/` (Model Configuration)
- `src/core/okta/` (Okta Client & Sync Logic)
- `src/core/tools/` (Agent Tools)

### Configuration & Utils
- `src/config/` (Settings)
- `src/utils/` (Logging, Error Handling, etc.)
- `src/backend/certs/` (SSL Certificates)

## Frontend Source (`src/frontend/`)
- `src/frontend/package.json`
- `src/frontend/vite.config.mjs`
- `src/frontend/index.html`
- `src/frontend/jsconfig.json`
- `src/frontend/public/`
- `src/frontend/src/` (Vue Components, Stores, Router, etc.)

## Notes
- The `src/api/routers/realtime_hybrid.py` might be a remnant of the previous architecture. Verify if `react_stream.py` fully replaces it.
- `src/backend/certs/` is assumed to be the location for SSL certs used by the backend.
