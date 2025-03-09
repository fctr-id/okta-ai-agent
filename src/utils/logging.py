import logging
import sys
import os
from logging.handlers import RotatingFileHandler
from src.config.settings import settings
import datetime

# Cache for loggers to prevent multiple configuration
_loggers = {}

def setup_logging(tenant_id=None, component=None):
    """
    Set up a logger with proper handlers and formatting
    
    Args:
        tenant_id: The tenant ID to include in logs
        component: Optional component name for dedicated logging
    """
    # Use tenant_id from settings if not provided
    if tenant_id is None:
        tenant_id = getattr(settings, 'tenant_id', 'default')
        
    # Determine logger name and cache key
    if component:
        logger_name = f"okta_sync.{component}"
        cache_key = f"{tenant_id}:{component}"
    else:
        logger_name = "okta_sync"
        cache_key = tenant_id
    
    # Return cached logger if exists
    if cache_key in _loggers:
        return _loggers[cache_key]
        
    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)
    
    # Create logger
    logger = logging.getLogger(logger_name)
    
    # Clear existing handlers
    if logger.hasHandlers():
        logger.handlers.clear()
        
    # Prevent propagation to root logger
    logger.propagate = False
    
    # Set log level, default to INFO if not in settings
    log_level = getattr(settings, 'LOG_LEVEL', 'INFO')
    logger.setLevel(getattr(logging, log_level))

    # Format for logs with explicit date format for consistency
    log_format = logging.Formatter(
        '%(asctime)s - %(name)s - tenant:[%(tenant_id)s] - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'  # Explicit date format for consistency
    )

    # Console handler with consistent format
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_format)
    logger.addHandler(console_handler)
    
    # Determine log file name - changed default to "okta-ai-agent"
    if component:
        log_file = f"logs/{component}_{tenant_id}.log"
    else:
        log_file = f"logs/okta-ai-agent_{tenant_id}.log"  # Changed from ai_agent to okta-ai-agent
    
    # File handler with consistent format
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10485760,  # 10MB
        backupCount=5
    )
    file_handler.setFormatter(log_format)
    logger.addHandler(file_handler)

    # Create adapter with tenant context
    logger_adapter = logging.LoggerAdapter(logger, {"tenant_id": tenant_id})
    
    # Cache the logger
    _loggers[cache_key] = logger_adapter
    
    return logger_adapter

# Create a function to replace print statements
def log_print(*args, **kwargs):
    """
    Function to replace standard print() calls with logger.info() calls
    that maintain the same consistent timestamp formatting
    """
    message = " ".join(map(str, args))
    logger.info(message)
    
# Function to install the print wrapper globally
def install_print_wrapper():
    """
    Replace the built-in print function with our logging version
    Call this in your main script to ensure all print statements use consistent formatting
    """
    import builtins
    builtins.print = log_print
    return True

# Helper function to get component-specific logger
def get_component_logger(component_name, tenant_id=None):
    """Get a logger for a specific component"""
    return setup_logging(tenant_id=tenant_id, component=component_name)

# Configure root logger for any uncaught logs to maintain consistency
def configure_root_logger():
    """Configure the root logger to use the same format for consistency"""
    root = logging.getLogger()
    if root.handlers:
        # Clear existing handlers to avoid duplication
        root.handlers = []
        
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    
# Create main logger instance
logger = setup_logging()

# Create sync logger for convenience
sync_logger = get_component_logger('sync')

# Configure root logger for consistency
configure_root_logger()