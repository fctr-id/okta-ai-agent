from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.backend.app.routers.query import router as query_router
from src.utils.logging import logger

app = FastAPI(
    title="Okta AI Agent",
    description="API for Okta AI Agent with SQL Generation capabilities",
    version="1.0.0"
)

# Log application startup
logger.info("Initializing Okta AI Agent API")
logger.debug(f"FastAPI Configuration: title={app.title}, version={app.version}")

# Configure CORS for future frontend integration
logger.info("Configuring CORS middleware")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.debug("CORS middleware configured with allow_origins=['http://localhost:3000']")

# Include routers
logger.info("Registering API routers")
app.include_router(query_router, prefix="/api/v1", tags=["queries"])
logger.debug("Query router registered with prefix='/api/v1'")

@app.get("/health")
async def health_check():
    logger.debug("Health check endpoint called")
    return {
        "status": "healthy",
        "service": "Okta AI Agent API"
    }

# Log application startup complete
logger.info("Okta AI Agent API initialization complete")