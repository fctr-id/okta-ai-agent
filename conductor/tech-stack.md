# Tech Stack: Tako AI Agent for Okta

## Backend
- **Language:** Python 3.x
- **Framework:** FastAPI (Asynchronous API)
- **AI Orchestration:** Pydantic AI (Multi-agent ReAct pattern)
- **Libraries:** `pydantic`, `python-dotenv`, `okta`, `sqlalchemy`, `aiosqlite`

## Frontend
- **Framework:** Vue.js 3
- **Styling:** CSS (Bootstrap/Material Design principles)
- **State Management:** Integrated with FastAPI via streaming (SSE)

## Database
- **Engine:** SQLite
- **ORM:** SQLAlchemy (with `aiosqlite` for async support)

## Infrastructure
- **Containerization:** Docker & Docker Compose
- **Security:** OAuth 2.0 & API Token support, Read-only permissions by default
