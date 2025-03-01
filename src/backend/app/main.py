from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from .routers import query, auth
from src.utils.logging import logger
from src.okta_db_sync.db.operations import DatabaseOperations
from src.okta_db_sync.db.models import AuthUser
from sqlalchemy import inspect, create_engine
import asyncio

app = FastAPI(
    title="Okta AI Agent",
    description="API for Okta AI Agent with SQL Generation capabilities",
    version="1.0.0"
)

# Log application startup
logger.info("Initializing Okta AI Agent API")

# Initialize auth database on startup
@app.on_event("startup")
async def initialize_auth_database():
    logger.info("Initializing authentication database...")
    db = DatabaseOperations()
    
    # Initialize the database (this will create all tables)
    await db.init_db()
    
    # Check if we need to create the AuthUser table specifically
    # This is a fallback in case only the auth tables need to be created
    from src.config.settings import settings
    import os
    
    engine = create_engine(f"sqlite:///{settings.SQLITE_PATH}")
    inspector = inspect(engine)
    if 'auth_users' not in inspector.get_table_names():
        logger.info("Creating auth_users table...")
        from sqlalchemy.schema import CreateTable
        # Create only the AuthUser table
        with engine.begin() as conn:
            conn.execute(CreateTable(AuthUser.__table__))
        logger.info("Auth users table created successfully")
    else:
        logger.info("Auth users table already exists")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register router for API endpoints
app.include_router(query.router, prefix="/api")
app.include_router(auth.router) 

# Mount static files
app.mount("/assets", StaticFiles(directory="src/backend/app/static/assets"), name="assets")

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "Okta AI Agent API"
    }

# Serve the frontend app for all other routes
@app.get("/{full_path:path}")
async def serve_frontend(request: Request, full_path: str):
    # Check if the path is for a static asset first
    static_file_path = f"src/backend/app/static/{full_path}"
    if os.path.isfile(static_file_path):
        return FileResponse(static_file_path)
    
    # Otherwise serve the index.html for client-side routing
    return FileResponse("src/backend/app/static/index.html")