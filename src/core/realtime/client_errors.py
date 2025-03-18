class OktaRealtimeError(Exception):
    """Base exception for Okta realtime client errors."""
    
    def __init__(self, message: str, original_exception: Exception = None):
        self.message = message
        self.original_exception = original_exception
        super().__init__(message)


class RateLimitError(OktaRealtimeError):
    """Exception raised when Okta API rate limits are hit."""
    
    def __init__(self, message: str, reset_seconds: int = None):
        self.reset_seconds = reset_seconds
        super().__init__(message)