"""
Error Handling Module

Provides a unified approach to error handling across the application with:
- Hierarchical exception classes
- Error context enrichment
- Standardized error formatting
- Error classification
- Integration with logging
"""

import logging
import traceback
import json
from enum import Enum
from typing import Optional, Dict, Any, List, Union, Tuple, Type
from typing import Optional, Dict, Any
import traceback
from datetime import datetime

# Import logging for integration
from src.utils.logging import get_logger

# Setup logger
logger = get_logger(__name__)

# Error classification enum
class ErrorSeverity(Enum):
    """Classification of error severity."""
    INFO = "info"           # Informational, not a true error
    WARNING = "warning"     # Warning, operation continued but with issues
    ERROR = "error"         # Error, operation failed but application can continue
    CRITICAL = "critical"   # Critical error, may require application restart
    FATAL = "fatal"         # Fatal error, application cannot continue


class BaseError(Exception):
    """
    Base exception for all application errors.
    
    Provides common functionality for error handling, context enrichment,
    and standardized formatting.
    """
    
    def __init__(
        self,
        message: str,
        original_exception: Optional[Exception] = None,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        context: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the error.
        
        Args:
            message: Human-readable error message
            original_exception: Original exception if this wraps another error
            severity: Error severity level
            context: Additional context information
        """
        self.message = message
        self.original_exception = original_exception
        self.severity = severity
        self.context = context or {}
        self.traceback = traceback.format_exc() if original_exception else None
        
        # Call parent constructor
        super().__init__(self.message)
    
    def add_context(self, **kwargs) -> 'BaseError':
        """
        Add additional context to the error.
        
        Args:
            **kwargs: Key-value pairs to add to context
            
        Returns:
            Self for method chaining
        """
        self.context.update(kwargs)
        return self
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the error to a dictionary representation.
        
        Returns:
            Dictionary representation of the error
        """
        result = {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "severity": self.severity.value
        }
        
        # Add context if present
        if self.context:
            result["context"] = self.context
        
        # Add original exception info if present
        if self.original_exception:
            result["original_error"] = str(self.original_exception)
            result["original_error_type"] = self.original_exception.__class__.__name__
        
        return result
    
    def to_json(self) -> str:
        """
        Convert the error to a JSON string.
        
        Returns:
            JSON representation of the error
        """
        return json.dumps(self.to_dict())
    
    def log(self, logger: Optional[logging.Logger] = None) -> None:
        """
        Log the error with appropriate severity.
        
        Args:
            logger: Logger to use, defaults to module logger
        """
        log = logger or globals()["logger"]
        
        # Map severity to log level
        if self.severity == ErrorSeverity.INFO:
            log_method = log.info
        elif self.severity == ErrorSeverity.WARNING:
            log_method = log.warning
        elif self.severity == ErrorSeverity.ERROR:
            log_method = log.error
        else:  # CRITICAL or FATAL
            log_method = log.critical
        
        # Log the error with context
        context_str = f" Context: {self.context}" if self.context else ""
        log_method(f"{self.__class__.__name__}: {self.message}{context_str}")
        
        # Log traceback for non-info errors if available
        if self.traceback and self.severity != ErrorSeverity.INFO:
            log.debug(f"Traceback for {self.__class__.__name__}:\n{self.traceback}")


class ValidationError(BaseError):
    """Error raised when input validation fails."""
    
    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        value: Any = None,
        **kwargs
    ):
        """
        Initialize validation error.
        
        Args:
            message: Error message
            field: Field that failed validation
            value: Invalid value (will be safely stringified)
            **kwargs: Additional context
        """
        context = kwargs.pop("context", {})
        if field:
            context["field"] = field
        if value is not None:
            # Safe stringification to avoid exposing sensitive data
            try:
                if isinstance(value, (str, int, float, bool, type(None))):
                    context["value"] = str(value)
                else:
                    context["value"] = f"{type(value).__name__} instance"
            except:
                context["value"] = "unstringifiable value"
        
        super().__init__(
            message,
            severity=ErrorSeverity.WARNING,
            context=context,
            **kwargs
        )


class ConfigurationError(BaseError):
    """Error raised when configuration is invalid or missing."""
    
    def __init__(
        self,
        message: str,
        config_key: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize configuration error.
        
        Args:
            message: Error message
            config_key: Configuration key that caused the error
            **kwargs: Additional arguments
        """
        context = kwargs.pop("context", {})
        if config_key:
            context["config_key"] = config_key
            
        super().__init__(
            message,
            severity=ErrorSeverity.ERROR,
            context=context,
            **kwargs
        )


class SecurityError(BaseError):
    """Error raised for security-related issues."""
    
    def __init__(
        self,
        message: str,
        security_type: str = "general",
        **kwargs
    ):
        """
        Initialize security error.
        
        Args:
            message: Error message
            security_type: Type of security issue
            **kwargs: Additional arguments
        """
        context = kwargs.pop("context", {})
        context["security_type"] = security_type
        
        super().__init__(
            message,
            severity=ErrorSeverity.CRITICAL,
            context=context,
            **kwargs
        )
        
        # Security errors should always be logged
        self.log()


class DependencyError(BaseError):
    """Error raised when a dependency fails."""
    
    def __init__(
        self,
        message: str,
        dependency: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize dependency error.
        
        Args:
            message: Error message
            dependency: Name of the dependency that failed
            **kwargs: Additional arguments
        """
        context = kwargs.pop("context", {})
        if dependency:
            context["dependency"] = dependency
            
        super().__init__(
            message,
            severity=ErrorSeverity.ERROR,
            context=context,
            **kwargs
        )


# API-related errors (moved from client_errors.py)
class ApiError(BaseError):
    """Base class for API interaction errors."""
    
    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        endpoint: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize API error.
        
        Args:
            message: Error message
            status_code: HTTP status code
            endpoint: API endpoint that was called
            **kwargs: Additional arguments
        """
        context = kwargs.pop("context", {})
        if status_code:
            context["status_code"] = status_code
        if endpoint:
            context["endpoint"] = endpoint
            
        super().__init__(
            message,
            context=context,
            **kwargs
        )


class RateLimitError(ApiError):
    """Error raised when an API rate limit is hit."""
    
    def __init__(
        self,
        message: str,
        endpoint: Optional[str] = None,
        reset_seconds: Optional[int] = None,
        **kwargs
    ):
        """
        Initialize rate limit error.
        
        Args:
            message: Error message
            endpoint: API endpoint that was rate limited
            reset_seconds: Seconds until the rate limit resets
            **kwargs: Additional arguments
        """
        context = kwargs.pop("context", {})
        if reset_seconds is not None:
            context["reset_seconds"] = reset_seconds
            
        super().__init__(
            message,
            endpoint=endpoint,
            context=context,
            **kwargs
        )


class AuthenticationError(ApiError):
    """Error raised for API authentication failures."""
    
    def __init__(
        self,
        message: str,
        **kwargs
    ):
        """
        Initialize authentication error.
        
        Args:
            message: Error message
            **kwargs: Additional arguments
        """
        super().__init__(
            message,
            severity=ErrorSeverity.ERROR,
            **kwargs
        )


class ExecutionError(BaseError):
    """Error raised during execution of generated code."""
    
    def __init__(
        self,
        message: str,
        step_name: Optional[str] = None,
        code_snippet: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize execution error.
        
        Args:
            message: Error message
            step_name: Name of the execution step that failed
            code_snippet: Relevant code snippet (safely truncated)
            **kwargs: Additional arguments
        """
        context = kwargs.pop("context", {})
        if step_name:
            context["step_name"] = step_name
        if code_snippet:
            # Safely truncate code snippet to avoid huge error messages
            max_length = 200
            if len(code_snippet) > max_length:
                context["code_snippet"] = f"{code_snippet[:max_length]}... [truncated]"
            else:
                context["code_snippet"] = code_snippet
                
        super().__init__(
            message,
            severity=ErrorSeverity.ERROR,
            context=context,
            **kwargs
        )


# Utility functions for error handling
def safe_execute(
    func: callable,
    *args,
    error_message: str = "Operation failed",
    default_return: Any = None,
    log_error: bool = True,
    reraise: bool = False,
    **kwargs
) -> Tuple[Any, Optional[BaseError]]:
    """
    Safely execute a function and handle exceptions.
    
    Args:
        func: Function to execute
        *args: Arguments to pass to the function
        error_message: Message for the error if the function fails
        default_return: Value to return in case of error
        log_error: Whether to log the error
        reraise: Whether to reraise the exception
        **kwargs: Keyword arguments to pass to the function
        
    Returns:
        Tuple of (result, error) where error is None if no error occurred
    """
    try:
        result = func(*args, **kwargs)
        return result, None
    except Exception as e:
        # Convert to BaseError if not already
        if isinstance(e, BaseError):
            error = e
        else:
            error = BaseError(
                message=error_message,
                original_exception=e,
                context={
                    "function": func.__name__,
                    "args": str(args),
                    "kwargs": str(kwargs)
                }
            )
        
        # Log the error if requested
        if log_error:
            error.log()
        
        # Reraise if requested
        if reraise:
            raise error
            
        return default_return, error
    
    
async def safe_execute_async(
    func: callable,
    *args,
    error_message: str = "Operation failed",
    default_return: Any = None,
    log_error: bool = True,
    reraise: bool = False,
    **kwargs
) -> Tuple[Any, Optional[BaseError]]:
    """
    Safely execute an async function and handle exceptions.
    
    Args:
        func: Async function to execute
        *args: Arguments to pass to the function
        error_message: Message for the error if the function fails
        default_return: Value to return in case of error
        log_error: Whether to log the error
        reraise: Whether to reraise the exception
        **kwargs: Keyword arguments to pass to the function
        
    Returns:
        Tuple of (result, error) where error is None if no error occurred
    """
    try:
        result = await func(*args, **kwargs)
        return result, None
    except Exception as e:
        # Convert to BaseError if not already
        if isinstance(e, BaseError):
            error = e
        else:
            error = BaseError(
                message=error_message,
                original_exception=e,
                context={
                    "function": func.__name__,
                    "args": str(args),
                    "kwargs": str(kwargs)
                }
            )
        
        # Log the error if requested
        if log_error:
            error.log()
        
        # Reraise if requested
        if reraise:
            raise error
            
        return default_return, error    


def format_error_for_user(error: Union[BaseError, Exception]) -> str:
    """
    Format an error into a user-friendly message.
    
    Args:
        error: The error to format
        
    Returns:
        User-friendly error message
    """
    if isinstance(error, BaseError):
        # Use the error's message directly
        return error.message
    else:
        # Generic message for unexpected errors
        return f"An unexpected error occurred: {str(error)}"


def format_error_for_response(
    error: Union[BaseError, Exception],
    include_details: bool = False
) -> Dict[str, Any]:
    """
    Format an error for API responses.
    
    Args:
        error: Error to format
        include_details: Whether to include detailed information
        
    Returns:
        Formatted error dictionary
    """
    if isinstance(error, BaseError):
        result = {
            "success": False,
            "error": error.message,
            "error_type": error.__class__.__name__
        }
        
        # Include additional context if requested
        if include_details and error.context:
            result["details"] = error.context
            
        return result
    else:
        # Generic format for unexpected errors
        return {
            "success": False,
            "error": str(error),
            "error_type": error.__class__.__name__
        }


async def capture_detailed_error(
    error: Exception,
    correlation_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Capture detailed error information for debugging
    
    This function is prepared for future use with PydanticAI's capture_run_messages
    but currently just provides enhanced error details.
    
    Args:
        error: The exception that was raised
        correlation_id: Optional correlation ID for tracing
        context: Optional context about the error
        
    Returns:
        Dictionary with detailed error information
    """
    # Get the current traceback
    tb = traceback.format_exc()
    
    error_info = {
        "error_type": error.__class__.__name__,
        "error_message": str(error),
        "timestamp": datetime.now().isoformat(),
        "correlation_id": correlation_id,
        "traceback": tb,
        "context": context or {}
    }
    
    # In the future, we could integrate with capture_run_messages here
    # For now, just return the error details
    return error_info

# Add this class for future retry capabilities
class RetryableError(BaseError):
    """
    Error type for operations that could be retried.
    
    This is prepared for future integration with PydanticAI's ModelRetry.
    """
    def __init__(
        self,
        message: str,
        retry_after: Optional[float] = None,
        max_retries: int = 3,
        **kwargs
    ):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after
        self.max_retries = max_retries
        self.current_retry = 0

# Legacy aliases for backward compatibility with client_errors.py
OktaRealtimeError = BaseError