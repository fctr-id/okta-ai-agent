from fastapi import Depends, HTTPException, status, Request, Cookie
from fastapi.security import APIKeyCookie
from typing import Optional, Dict, Any, Union
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from src.core.auth.jwt import decode_access_token
from src.okta_db_sync.db.operations import DatabaseOperations
from src.okta_db_sync.db.models import AuthUser
from src.utils.logging import logger

# Create cookie security scheme
oauth2_scheme = APIKeyCookie(name="access_token")

# Database connection
db_operations = DatabaseOperations()

async def get_db_session() -> AsyncSession:
    """Get a database session"""
    async with db_operations.get_session() as session:
        yield session

async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    access_token: Optional[str] = Cookie(None)
) -> AuthUser:
    """
    Dependency to get the current authenticated user
    
    Args:
        request: FastAPI request object
        session: Database session
        access_token: JWT token from cookie
        
    Returns:
        AuthUser object if authentication is valid
        
    Raises:
        HTTPException: If authentication is invalid
    """
    # Check if token exists
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Validate token and extract user ID
    token_data = decode_access_token(access_token)
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    username = token_data.get("sub")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    
    # Get user from database
    user = await db_operations.get_auth_user(session, username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    
    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )
    
    # Update last activity (optional)
    user.last_login = datetime.now()
    await session.commit()
    
    return user

async def get_current_active_admin(
    current_user: AuthUser = Depends(get_current_user),
) -> AuthUser:
    """
    Dependency for routes that require admin privileges
    
    Args:
        current_user: User from get_current_user dependency
        
    Returns:
        AuthUser if user is admin
        
    Raises:
        HTTPException: If user is not an admin
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    return current_user