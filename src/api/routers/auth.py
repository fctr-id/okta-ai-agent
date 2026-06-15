from fastapi import APIRouter, Depends, HTTPException, status, Response, Cookie, Request
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field, field_validator  
from typing import Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
import hmac
import secrets
import re
import sys
import time

from src.core.security.dependencies import get_db_session, get_current_user
from src.core.security.jwt import create_access_token, decode_access_token
from src.core.okta.sync.operations import DatabaseOperations
from src.core.okta.sync.models import AuthUser, UserRole
from src.utils.logging import logger
from src.config.settings import settings
from src.core.security.cookies import set_auth_cookie, clear_auth_cookie, get_auth_cookie


router = APIRouter(
    prefix="/api/auth",
    tags=["authentication"],
)

db_operations = DatabaseOperations()
_ephemeral_setup_token: Optional[str] = None
_ephemeral_setup_token_announced = False


def _get_or_create_ephemeral_setup_token() -> str:
    global _ephemeral_setup_token
    global _ephemeral_setup_token_announced

    if not _ephemeral_setup_token:
        _ephemeral_setup_token = secrets.token_urlsafe(24)

    if not _ephemeral_setup_token_announced:
        banner = "=" * 72
        print(
            f"\n{banner}"
            "\n[okta-ai-agent] INITIAL SETUP REQUIRED"
            f"\n[okta-ai-agent] Setup token: {_ephemeral_setup_token}"
            "\n[okta-ai-agent] Use this token once to create the first admin account."
            "\n[okta-ai-agent] The token is kept in memory only and resets on process restart."
            f"\n{banner}\n",
            file=sys.stdout,
            flush=True,
        )
        _ephemeral_setup_token_announced = True

    return _ephemeral_setup_token


def ensure_ephemeral_setup_token() -> str:
    """Ensure an in-memory setup token exists and is announced to the local operator."""
    return _get_or_create_ephemeral_setup_token()


def _clear_ephemeral_setup_token() -> None:
    global _ephemeral_setup_token
    global _ephemeral_setup_token_announced
    _ephemeral_setup_token = None
    _ephemeral_setup_token_announced = False

# Input sanitization for usernames
def sanitize_input(input_str: str, max_length: int = 50) -> Tuple[str, bool]:
    """
    Sanitize user input to prevent injection attacks
    
    Args:
        input_str: Raw user input
        max_length: Maximum allowed length
        
    Returns:
        Tuple of (sanitized_input, was_modified)
    """
    if not input_str:
        return "", False
        
    original = input_str
    
    # Remove control characters except newlines and tabs
    input_str = ''.join(char for char in input_str if ord(char) >= 32 or char in '\n\t')
    
    # Limit length
    if len(input_str) > max_length:
        input_str = input_str[:max_length]
    
    # Check if the input was modified during sanitization
    was_modified = (original != input_str)
    
    return input_str.strip(), was_modified

# Pydantic models for request/response validation
class Token(BaseModel):
    access_token: str
    token_type: str
    
class TokenResponse(BaseModel):
    success: bool
    message: str
    
class SetupStatus(BaseModel):
    needs_setup: bool
    
class SetupRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=20)
    password: str = Field(..., min_length=12, max_length=50)
    setup_token: str = Field(..., min_length=1, max_length=200)
    
    @field_validator('username')  # Updated to V2 validator
    @classmethod
    def username_format(cls, v):
        """Validate username format"""
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError('Username must contain only letters, numbers, underscores, and hyphens')
        return v
    
    @field_validator('password')  # Updated to V2 validator
    @classmethod
    def password_strength(cls, v):
        """Validate password strength"""
        errors = []
        
        if len(v) < 12:
            errors.append('Password must be at least 12 characters')
            
        # Check for uppercase, lowercase, number, and special character
        if not any(c.isupper() for c in v):
            errors.append('Password must contain at least one uppercase letter')
            
        if not any(c.islower() for c in v):
            errors.append('Password must contain at least one lowercase letter')
            
        if not any(c.isdigit() for c in v):
            errors.append('Password must contain at least one number')
            
        if not any(not c.isalnum() for c in v):
            errors.append('Password must contain at least one special character')
        
        if errors:
            raise ValueError('. '.join(errors))
            
        return v
    
class UserResponse(BaseModel):
    username: str
    role: str
    is_active: bool

@router.get("/setup-status", response_model=SetupStatus)
async def check_setup_status(session: AsyncSession = Depends(get_db_session)):
    """Check if initial setup is needed"""
    is_setup = await db_operations.check_setup_completed(session)
    if is_setup:
        _clear_ephemeral_setup_token()
    else:
        _get_or_create_ephemeral_setup_token()
    return {"needs_setup": not is_setup}

@router.post("/setup", response_model=TokenResponse)
async def initial_setup(
    request: Request,
    setup_data: SetupRequest,
    response: Response,
    session: AsyncSession = Depends(get_db_session)
):
    """Set up initial admin user"""
    # Get client IP for logging
    client_ip = request.client.host if request.client else "unknown"
    
    # Check if setup has already been completed
    is_setup = await db_operations.check_setup_completed(session)
    if is_setup:
        _clear_ephemeral_setup_token()
        logger.warning(f"Setup attempted when already complete from IP: {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Setup has already been completed"
        )

    expected_setup_token = _get_or_create_ephemeral_setup_token().strip()
    provided_setup_token = (setup_data.setup_token or "").strip()

    if not hmac.compare_digest(provided_setup_token, expected_setup_token):
        logger.warning(f"Setup attempted with invalid bootstrap token from IP: {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid setup token"
        )
    
    # Apply extra sanitization to username and password
    sanitized_username, username_modified = sanitize_input(setup_data.username, 20)
    sanitized_password, password_modified = sanitize_input(setup_data.password, 50)
    
    if username_modified or password_modified:
        logger.warning(f"Suspicious input detected in setup request from IP: {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid input format"
        )
    
    # Check if the username already exists
    existing_user = await db_operations.get_auth_user(session, sanitized_username)
    if existing_user:
        logger.warning(f"Setup attempted with existing username from IP: {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists"
        )
    
    # Create initial admin user
    try:
        user = await db_operations.create_auth_user(
            session,
            sanitized_username,
            sanitized_password,
            UserRole.ADMIN
        )
        
        # Generate access token with improved claims
        token_data = {
            "sub": user.username,
            "role": user.role
        }
        access_token = create_access_token(token_data)
        
        # Set cookie using the updated utility (fctr_session)
        set_auth_cookie(response, access_token)
        _clear_ephemeral_setup_token()
        
        logger.info(f"Initial setup completed: Admin user created from IP: {client_ip}")
        return {
            "success": True,
            "message": "Admin user created successfully"
        }
        
    except Exception as e:
        logger.error(f"Error during setup: {str(e)} from IP: {client_ip}")
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error creating admin user"
        )

@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_db_session)
):
    """Login and get access token"""
    # Get client IP for logging
    client_ip = request.client.host if request.client else "unknown"
    
    # Add a small delay for security (helps against user enumeration)
    time.sleep(0.1)
    
    # Sanitize inputs before database operations
    username, username_modified = sanitize_input(form_data.username, 20)
    password, password_modified = sanitize_input(form_data.password, 50)
    
    if username_modified or password_modified:
        logger.warning(f"Suspicious input detected in login request from IP: {client_ip}")
        # Don't reveal that we modified the input, just proceed with sanitized version
    
    # Verify credentials with sanitized input
    user = await db_operations.verify_user_credentials(
        session,
        username,
        password
    )
    
    if not user:
        logger.warning(f"Failed login attempt from IP: {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer realm=\"Okta AI Agent API\""},
        )
    
    # Check if user is active
    if not user.is_active:
        logger.warning(f"Login attempt for disabled account from IP: {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )
    
    # Generate access token with role information
    token_data = {
        "sub": user.username,
        "role": user.role
    }
    access_token = create_access_token(token_data)
    
    # Set cookie using the updated utility (fctr_session)
    set_auth_cookie(response, access_token)
    
    # Update last login time
    user.last_login = datetime.utcnow()
    await session.commit()
    
    logger.info(f"Successful login for user: '{user.username}' from IP: {client_ip}")
    return {
        "success": True,
        "message": "Login successful"
    }

@router.post("/logout", response_model=TokenResponse)
async def logout(response: Response, request: Request):
    """Log out by clearing the token cookie"""
    # Get client IP for logging
    client_ip = request.client.host if request.client else "unknown"
    
    # Get the current cookie to check if user was logged in
    cookie = get_auth_cookie(request)
    
    # Clear the cookie regardless
    clear_auth_cookie(response)
    
    # Log the logout, including whether it was a valid session
    if cookie:
        try:
            payload = decode_access_token(cookie)
            if payload and "sub" in payload:
                # Sanitize username from token before logging
                username, _ = sanitize_input(payload["sub"], 20)
                logger.info(f"User '{username}' logged out from IP: {client_ip}")
        except Exception:
            # If token decoding fails, just log a generic message
            logger.info(f"User logged out with invalid token from IP: {client_ip}")
    
    return {
        "success": True,
        "message": "Logout successful"
    }

@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: AuthUser = Depends(get_current_user),
    request: Request = None
):
    """Get current authenticated user info"""
    # Log access to sensitive user info (for audit)
    client_ip = request.client.host if request and request.client else "unknown"
    logger.debug(f"User info accessed: '{current_user.username}' from IP: {client_ip}")
    
    # Return only the necessary user info
    return {
        "username": current_user.username,
        "role": current_user.role,
        "is_active": current_user.is_active
    }

@router.get("/check", response_model=TokenResponse)
async def check_authentication(current_user: AuthUser = Depends(get_current_user)):
    """Check if authentication is valid"""
    return {
        "success": True,
        "message": "Authentication valid"
    }