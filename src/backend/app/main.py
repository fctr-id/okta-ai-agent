import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
from .routers import query, auth, sync, realtime
from src.utils.logging import logger
from src.okta_db_sync.db.operations import DatabaseOperations
from src.okta_db_sync.db.models import AuthUser
from sqlalchemy import inspect, create_engine

# Security Headers Middleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Basic security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # HTTPS enforcement with HSTS header
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        # Permissions policy (formerly Feature-Policy)
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=(), payment=()"
        
        # Content Security Policy - updated to prefer HTTPS
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "  # Allow inline scripts for Vue
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "img-src 'self' data:; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "connect-src 'self' https:; "  # Only allow HTTPS connections
            "frame-ancestors 'none';"
        )
        response.headers["Content-Security-Policy"] = csp
        
        return response

# Modern lifespan approach (replacing on_event)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup code
    logger.info("Initializing Okta AI Agent API")
    logger.info("Initializing authentication database...")
    db = DatabaseOperations()
    
    await db.init_db()
    
    from src.config.settings import settings
    
    engine = create_engine(f"sqlite:///{settings.SQLITE_PATH}")
    inspector = inspect(engine)
    if 'auth_users' not in inspector.get_table_names():
        logger.info("Creating auth_users table...")
        from sqlalchemy.schema import CreateTable
        with engine.begin() as conn:
            conn.execute(CreateTable(AuthUser.__table__))
        logger.info("Auth users table created successfully")
    else:
        logger.debug("Auth users table already exists. Do not have to create a new one")
    
    yield
    
    logger.info("Shutting down Okta AI Agent API")

# Create FastAPI app with lifespan manager
app = FastAPI(
    title="Okta AI Agent",
    description="API for Okta AI Agent with SQL Generation capabilities",
    version="1.0.0",
    lifespan=lifespan
)

# Add security headers middleware first
app.add_middleware(SecurityHeadersMiddleware)

# Configure CORS - update default to HTTPS
default_origins = "https://localhost:*,https://127.0.0.1:*"
allowed_origins = os.environ.get("ALLOWED_ORIGINS", default_origins).split(",")
logger.info(f"Configuring CORS with allowed origins: {allowed_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"https://(localhost|127\.0\.0\.1)(:[0-9]+)?",  # Only allow HTTPS
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register router for API endpoints
app.include_router(query.router, prefix="/api")
app.include_router(auth.router) 
app.include_router(sync.router, prefix="/api")
app.include_router(realtime.router, prefix="/api/realtime")

# Mount static files
app.mount("/assets", StaticFiles(directory="src/backend/app/static/assets"), name="assets")

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "Okta AI Agent API"
    }

@app.get("/{full_path:path}")
async def serve_frontend(request: Request, full_path: str):
    # Define the base directory for static files (using absolute path)
    static_dir = os.path.abspath("src/backend/app/static")
    
    # Clean the path to prevent directory traversal
    # Remove any '..' path segments and normalize
    sanitized_path = os.path.normpath(full_path)
    
    # If path attempts to traverse up directories or is absolute, reject it
    if sanitized_path.startswith("..") or sanitized_path.startswith("/") or "\\" in sanitized_path:
        return JSONResponse(
            status_code=403,
            content={"detail": "Access denied"}
        )
    
    # Securely join paths and resolve to absolute path
    file_path = os.path.abspath(os.path.join(static_dir, sanitized_path))
    
    # Ensure the final path is still within the static directory
    if not file_path.startswith(static_dir):
        return JSONResponse(
            status_code=403,
            content={"detail": "Access denied"}
        )
    
    # Finally serve the file if it exists
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    
    # Default to index.html
    return FileResponse(os.path.join(static_dir, "index.html"))
