from jose import JWTError, jwt
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Any, Union
from src.utils.logging import logger
from src.config.settings import settings

# Get settings with fallbacks
SECRET_KEY = getattr(settings, "JWT_SECRET_KEY", "CHANGE-THIS-KEY-IN-PRODUCTION-ENVIRONMENTS")
ALGORITHM = getattr(settings, "JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = getattr(settings, "JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 30)

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a new JWT access token
    
    Args:
        data: Dictionary of claims to include in the token
        expires_delta: Optional expiration time, defaults to settings
        
    Returns:
        Encoded JWT token string
    """
    to_encode = data.copy()
    
    # Set expiration time
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    # Add standard claims
    to_encode.update({
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access"
    })
    
    # Encode the token
    try:
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    except Exception as e:
        logger.error(f"Error creating JWT token: {e}")
        raise

def decode_access_token(token: str) -> Union[Dict[str, Any], None]:
    """
    Decode and validate a JWT access token
    
    Args:
        token: The JWT token string
        
    Returns:
        Dictionary of claims if valid, None if invalid
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        # Check token type for extra security
        if payload.get("type") != "access":
            logger.warning("Invalid token type")
            return None
            
        return payload
    except JWTError as e:
        logger.warning(f"JWT validation error: {e}")
        return None
    except Exception as e:
        logger.error(f"Error decoding token: {e}")
        return None