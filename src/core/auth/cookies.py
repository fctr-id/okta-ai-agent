from fastapi import Response
from src.config.settings import settings

def set_auth_cookie(response: Response, token: str) -> None:
    """
    Set the authentication cookie with consistent settings
    
    Args:
        response: FastAPI response object
        token: JWT token string
    """
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=settings.COOKIE_MAX_AGE_SECONDS,
    )

def clear_auth_cookie(response: Response) -> None:
    """
    Clear the authentication cookie
    
    Args:
        response: FastAPI response object
    """
    response.delete_cookie(key="access_token")