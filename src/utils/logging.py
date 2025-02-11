import logging
import sys
import os
from logging.handlers import RotatingFileHandler
from src.config.settings import settings

def setup_logging(tenant_id: str = None):
    # Use tenant_id from settings if not provided
    if tenant_id is None:
        tenant_id = settings.tenant_id

    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)
    
    # Get or create logger
    logger = logging.getLogger("okta_sync")
    
    # Clear existing handlers
    if logger.hasHandlers():
        logger.handlers.clear()
    
    # Prevent propagation to root logger
    logger.propagate = False
    
    # Set log level
    logger.setLevel(getattr(logging, settings.LOG_LEVEL))

    # Format for logs
    log_format = logging.Formatter(
        '%(asctime)s - %(name)s - tenant:[%(tenant_id)s] - %(levelname)s - %(message)s'
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_format)
    logger.addHandler(console_handler)

    # File handler
    file_handler = RotatingFileHandler(
        f"logs/okta_sync_{tenant_id}.log",
        maxBytes=10485760,  # 10MB
        backupCount=5
    )
    file_handler.setFormatter(log_format)
    logger.addHandler(file_handler)

    # Add tenant context
    return logging.LoggerAdapter(logger, {"tenant_id": tenant_id})

# Create single logger instance
logger = setup_logging(settings.tenant_id)