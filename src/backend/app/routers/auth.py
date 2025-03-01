from fastapi import APIRouter, Depends, HTTPException, status, Response, Cookie
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field, validator
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta

from src.core.auth.dependencies import get_db_session, get_current_user
from src.core.auth.jwt import create_access_token, decode_access_token
from src.okta_db_sync.db.operations import DatabaseOperations
from src.okta_db_sync.db.models import AuthUser, UserRole
from src.utils.logging import logger
from src.config.settings import settings
from src.core.auth.cookies import set_auth_cookie, clear_auth_cookie


router = APIRouter(
    prefix="/api/auth",
    tags=["authentication"],
)

db_operations = DatabaseOperations()

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
    
    @validator('password')
    def password_strength(cls, v):
        """Validate password strength"""
        if len(v) < 12:
            raise ValueError('Password must be at least 12 characters')
        # Check for uppercase, lowercase, number, and special character
        has_upper = any(c.isupper() for c in v)
        has_lower = any(c.islower() for c in v)
        has_digit = any(c.isdigit() for c in v)
        has_special = any(not c.isalnum() for c in v)
        
        if not (has_upper and has_lower and has_digit and has_special):
            raise ValueError('Password must contain uppercase, lowercase, number, and special character')
        return v
    
class UserResponse(BaseModel):
    username: str
    role: str
    is_active: bool

@router.get("/setup-status", response_model=SetupStatus)
async def check_setup_status(session: AsyncSession = Depends(get_db_session)):
    """Check if initial setup is needed"""
    is_setup = await db_operations.check_setup_completed(session)
    return {"needs_setup": not is_setup}

@router.post("/setup", response_model=TokenResponse)
async def initial_setup(
    setup_data: SetupRequest,
    response: Response,
    session: AsyncSession = Depends(get_db_session)
):
    """Set up initial admin user"""
    # Check if setup has already been completed
    is_setup = await db_operations.check_setup_completed(session)
    if is_setup:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Setup has already been completed"
        )
    
    # Check if the username already exists
    existing_user = await db_operations.get_auth_user(session, setup_data.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists"
        )
    
    # Create initial admin user
    try:
        user = await db_operations.create_auth_user(
            session,
            setup_data.username,
            setup_data.password,
            UserRole.ADMIN
        )
        
        # Generate access token
        token_data = {"sub": user.username}
        access_token = create_access_token(token_data)
        
        # Set cookie using the utility
        set_auth_cookie(response, access_token)
        
        return {
            "success": True,
            "message": "Admin user created successfully"
        }
        
    except Exception as e:
        logger.error(f"Error during setup: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error creating admin user"
        )

@router.post("/login", response_model=TokenResponse)
async def login(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_db_session)
):
    """Login and get access token"""
    user = await db_operations.verify_user_credentials(
        session,
        form_data.username,
        form_data.password
    )
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Generate access token
    token_data = {"sub": user.username}
    access_token = create_access_token(token_data)
    
    # Set cookie using the utility
    set_auth_cookie(response, access_token)
    
    return {
        "success": True,
        "message": "Login successful"
    }

@router.get("/logout", response_model=TokenResponse)
async def logout(response: Response):
    """Log out by clearing the token cookie"""
    clear_auth_cookie(response)
    return {
        "success": True,
        "message": "Logout successful"
    }

@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: AuthUser = Depends(get_current_user)):
    """Get current authenticated user info"""
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