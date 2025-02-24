from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import query  # Changed from app.routers to relative import
from src.utils.logging import logger

app = FastAPI(
    title="Okta AI Agent",
    description="API for Okta AI Agent with SQL Generation capabilities",
    version="1.0.0"
)

# Log application startup
logger.info("Initializing Okta AI Agent API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register router - only one registration needed
app.include_router(query.router, prefix="/api")

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "Okta AI Agent API"
    }