from fastapi import Response, Request
from config.settings import settings
import time
from typing import Optional

def set_auth_cookie(response: Response, token: str) -> None:
    """
    Set secure authentication cookie with appropriate security attributes.
    
    Args:
        response: FastAPI Response object
        token: JWT token to store in cookie
    """
    # Security attributes:
    # - httponly: Prevents JavaScript access (XSS protection)
    # - secure: Requires HTTPS (except in development)
    # - samesite: Controls when cookies are sent (CSRF protection)
    # - max_age: Cookie lifetime
    # - path: Cookie is valid for all paths
    response.set_cookie(
        key="fctr_session",
        value=token,
        httponly=True,
        secure=settings.COOKIE_SECURE,  # True in production, can be False in development
        samesite=settings.COOKIE_SAMESITE,  # "lax" is a good default, "strict" for higher security
        max_age=settings.COOKIE_MAX_AGE_MINUTES * 60,  # Match with token expiration
        path="/",  # Make cookie available across all routes
    )

def clear_auth_cookie(response: Response) -> None:
    """
    Clear authentication cookie securely.
    
    Args:
        response: FastAPI Response object
    """
    # Delete cookie by setting an expired date and empty value
    # Must match the same parameters as when setting (except value and max_age)
    response.delete_cookie(
        key="fctr_session",
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        path="/",
    )

def get_auth_cookie(request: Request) -> Optional[str]:
    """
    Extract authentication cookie from request safely.
    
    Args:
        request: FastAPI Request object
        
    Returns:
        Token string if present, None otherwise
    """
    # Safely extract cookie without raising exceptions
    try:
        return request.cookies.get("fctr_session")
    except Exception:
        # If any error occurs, treat as if cookie doesn't exist
        # This follows the principle of graceful degradation
        return None

def has_valid_cookie_format(request: Request) -> bool:
    """
    Quick check if the authentication cookie exists and has a plausible format.
    This is a preliminary check before actual JWT validation.
    
    Args:
        request: FastAPI Request object
        
    Returns:
        True if cookie exists and has JWT format, False otherwise
    """
    try:
        token = get_auth_cookie(request)
        
        # Basic JWT format check (header.payload.signature)
        if token and isinstance(token, str):
            parts = token.split('.')
            return len(parts) == 3 and all(parts)
            
        return False
    except Exception:
        return False