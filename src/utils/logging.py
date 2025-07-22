"""
Centralized Logging Configuration

Provides unified logging configuration with optional correlation ID support.
"""

import os
import sys
import uuid
import socket
import time
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, Optional, Any
from dotenv import load_dotenv

load_dotenv(override=True)

# Default log levels - Use standard LOG_LEVEL variable with fallbacks
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
DEFAULT_CONSOLE_LEVEL = os.getenv("RLTIME_CONSOLE_LOG_LEVEL", LOG_LEVEL).upper()
# Default file log level - Always DEBUG for file logging unless explicitly overridden
DEFAULT_FILE_LEVEL = os.getenv("RLTIME_FILE_LOG_LEVEL", "DEBUG").upper()

# Store correlation ID (simple global variable approach)
_CORRELATION_ID = None

# Track configured loggers to prevent duplicate handlers
_CONFIGURED_LOGGERS = set()


def generate_correlation_id(prefix="cli"):
    """
    Generate a globally unique correlation ID.
    
    Args:
        prefix: Identifier prefix (default: 'cli')
        
    Returns:
        Unique correlation ID string
    """
    # Get unique machine identifier (last part of hostname)
    hostname = socket.gethostname().split('.')[-1]
    # Get timestamp
    timestamp = int(time.time())
    # Get random component
    random_part = uuid.uuid4().hex[:6]
    # Combine components
    return f"{prefix}-{hostname}-{timestamp}-{random_part}"


def set_correlation_id(correlation_id: str) -> None:
    """Set a correlation ID for the current context."""
    global _CORRELATION_ID
    _CORRELATION_ID = correlation_id


def get_correlation_id() -> Optional[str]:
    """Get the current correlation ID."""
    return _CORRELATION_ID


def get_project_root() -> Path:
    """Get the project root directory."""
    file_dir = Path(__file__).resolve().parent
    current = file_dir
    while current.name != "src" and not (current / ".git").exists():
        parent = current.parent
        if parent == current:
            return file_dir.parent
        current = parent
    return current.parent if current.name == "src" else current


def get_default_log_dir() -> Path:
    """Get the default log directory."""
    project_root = get_project_root()
    logs_dir = project_root / "logs"
    os.makedirs(logs_dir, exist_ok=True)
    return logs_dir


def get_logger(name: str, log_dir: Optional[Path] = None) -> logging.Logger:
    """
    Get a properly configured logger.
    
    Args:
        name: Logger name (typically __name__)
        log_dir: Directory for log files
        
    Returns:
        Configured logger
    """
    # Get logger
    logger = logging.getLogger(name)
    
    # If already configured, return it
    if name in _CONFIGURED_LOGGERS:
        return logger
    
    # Mark as configured
    _CONFIGURED_LOGGERS.add(name)
    
    # Set level to capture all messages; filtering happens at handlers
    logger.setLevel(logging.DEBUG)
    
    # Remove any existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Add console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(DEFAULT_CONSOLE_LEVEL)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        '%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # Add file handler if log_dir is provided
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        # Use unified okta_ai_agent.log for all agents
        log_file = os.path.join(log_dir, "okta_ai_agent.log")
        file_handler = RotatingFileHandler(
            log_file, 
            maxBytes=10*1024*1024, 
            backupCount=5,
            encoding='utf-8'  # Fix for Windows Unicode/emoji logging
        )
        file_handler.setLevel(DEFAULT_FILE_LEVEL)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(pathname)s:%(lineno)d - %(message)s',
            '%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    
    # Prevent duplicate logs
    if name != "root":
        logger.propagate = False
    
    # Create wrapped logging methods
    original_debug = logger.debug
    original_info = logger.info
    original_warning = logger.warning
    original_error = logger.error
    original_critical = logger.critical
    
    # Replace methods with correlation-aware versions
    def debug_with_correlation(msg, *args, **kwargs):
        """Add correlation ID to debug logs if available."""
        correlation_id = get_correlation_id()
        if correlation_id:
            msg = f"[{correlation_id}] {msg}"
        return original_debug(msg, *args, **kwargs)
    
    def info_with_correlation(msg, *args, **kwargs):
        """Add correlation ID to info logs if available."""
        correlation_id = get_correlation_id()
        if correlation_id:
            msg = f"[{correlation_id}] {msg}"
        return original_info(msg, *args, **kwargs)
    
    def warning_with_correlation(msg, *args, **kwargs):
        """Add correlation ID to warning logs if available."""
        correlation_id = get_correlation_id()
        if correlation_id:
            msg = f"[{correlation_id}] {msg}"
        return original_warning(msg, *args, **kwargs)
    
    def error_with_correlation(msg, *args, **kwargs):
        """Add correlation ID to error logs if available."""
        correlation_id = get_correlation_id()
        if correlation_id:
            msg = f"[{correlation_id}] {msg}"
        return original_error(msg, *args, **kwargs)
    
    def critical_with_correlation(msg, *args, **kwargs):
        """Add correlation ID to critical logs if available."""
        correlation_id = get_correlation_id()
        if correlation_id:
            msg = f"[{correlation_id}] {msg}"
        return original_critical(msg, *args, **kwargs)
    
    # Replace the logger methods
    logger.debug = debug_with_correlation
    logger.info = info_with_correlation
    logger.warning = warning_with_correlation
    logger.error = error_with_correlation
    logger.critical = critical_with_correlation
    
    return logger


# Initialize default logging
logs_dir = get_default_log_dir()
logger = get_logger(__name__, logs_dir)

# Expose module-level logging functions
debug = logger.debug
info = logger.info
warning = logger.warning
error = logger.error
critical = logger.critical

# Set a default correlation ID for the main process
set_correlation_id(generate_correlation_id("main"))