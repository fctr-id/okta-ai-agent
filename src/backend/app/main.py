import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
from .routers import query, auth
from src.utils.logging import logger
from src.okta_db_sync.db.operations import DatabaseOperations
from src.okta_db_sync.db.models import AuthUser
from sqlalchemy import inspect, create_engine

# Security Headers Middleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        
        # CSP - Content Security Policy with Google Fonts support
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "  # Allow inline scripts for Vue
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "  # Added Google Fonts
            "img-src 'self' data:; "
            "font-src 'self' https://fonts.gstatic.com data:; "  # Added Google Fonts
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )
        response.headers["Content-Security-Policy"] = csp
        
        # Additional security headers
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        
        return response

# Modern lifespan approach (replacing on_event)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup code - runs on application startup
    logger.info("Initializing Okta AI Agent API")
    logger.info("Initializing authentication database...")
    db = DatabaseOperations()
    
    # Initialize the database (this will create all tables)
    await db.init_db()
    
    # Check if we need to create the AuthUser table specifically
    from src.config.settings import settings
    
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
    
    yield  # This is where FastAPI serves requests
    
    # Shutdown code (if any) would go here
    logger.info("Shutting down Okta AI Agent API")

# Create FastAPI app with lifespan manager
app = FastAPI(
    title="Okta AI Agent",
    description="API for Okta AI Agent with SQL Generation capabilities",
    version="1.0.0",
    lifespan=lifespan
)

# Add security headers middleware (add this before CORS middleware)
app.add_middleware(SecurityHeadersMiddleware)

allowed_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:*,http://127.0.0.1:*").split(",")
logger.info(f"Configuring CORS with allowed origins: {allowed_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:[0-9]+)?",  # Regex for any localhost port
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "X-CSRF-Token"],  # Add CSRF token header support
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