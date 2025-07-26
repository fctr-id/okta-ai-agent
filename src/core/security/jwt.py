from jose import JWTError, jwt
from datetime import datetime, timedelta, timezone
import secrets
import time
import base64
import json
from typing import Optional, Dict, Any, Union
from config.settings import settings
from utils.logging import logger
#import logging

#logger.setLevel(logging.DEBUG)

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token with standardized security claims
    """
    # Debug: Log settings values
    logger.debug(f"JWT_AUDIENCE setting value: '{getattr(settings, 'JWT_AUDIENCE', 'not set')}'")
    logger.debug(f"JWT_ISSUER setting value: '{getattr(settings, 'JWT_ISSUER', 'not set')}'")
    
    # Create a copy of the data to avoid modifying the original
    payload = data.copy()
    
    # Set expiration time with timezone awareness
    now = datetime.now(timezone.utc)
    expires = now + (
        expires_delta if expires_delta 
        else timedelta(minutes=getattr(settings, "JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 30))
    )
    
    # Add standard security claims
    audience = getattr(settings, "JWT_AUDIENCE", "ui-user")
    issuer = getattr(settings, "JWT_ISSUER", "fctr-okta-ai-agent")
    
    payload.update({
        "iat": now,                         
        "exp": expires,                     
        "nbf": now,                         
        "jti": secrets.token_hex(16),       
        "iss": issuer,        
        "aud": audience,                   
        "type": "access"                    
    })
    
    # Debug: log the full payload being encoded
    logger.debug(f"Creating token with payload: {payload}")
    logger.debug(f"Token audience being set: '{audience}'")
    logger.debug(f"Token issuer being set: '{issuer}'")
    
    # Get JWT secret from settings with fallback
    secret_key = getattr(settings, "JWT_SECRET_KEY", 
                         getattr(settings, "SECRET_KEY", "default_secret_insecure"))
    
    # Get algorithm from settings with fallback
    algorithm = getattr(settings, "JWT_ALGORITHM", "HS256")
    
    # Encode the token
    token = jwt.encode(
        payload, 
        secret_key,
        algorithm=algorithm
    )
    
    logger.debug(f"Token created successfully for {payload.get('sub')}")
    return token

def decode_access_token(token: str, leeway: int = 30) -> Optional[Dict[str, Any]]:
    """
    Decode and validate a JWT token with comprehensive security checks
    """
    if not token:
        return None
    
    # Debug log statement with limited token info for security
    logger.debug(f"Validating token: {token[:15]}...")
    
    # Extract payload for debugging without verification
    try:
        parts = token.split('.')
        if len(parts) == 3:
            padded = parts[1] + '=' * (4 - len(parts[1]) % 4)
            raw_payload = base64.urlsafe_b64decode(padded)
            debug_payload = json.loads(raw_payload)
            logger.debug(f"Raw token payload: {debug_payload}")
            logger.debug(f"Token audience in payload: '{debug_payload.get('aud', 'not present')}'")
            logger.debug(f"Token issuer in payload: '{debug_payload.get('iss', 'not present')}'")
    except Exception:
        pass
    
    # Get expected values
    expected_audience = getattr(settings, "JWT_AUDIENCE", "ui-user")
    expected_issuer = getattr(settings, "JWT_ISSUER", "fctr-okta-ai-agent")
    logger.debug(f"Expected audience: '{expected_audience}'")
    logger.debug(f"Expected issuer: '{expected_issuer}'")
    
    try:
        # Get JWT secret and algorithm 
        secret_key = getattr(settings, "JWT_SECRET_KEY", 
                            getattr(settings, "SECRET_KEY", "default_secret_insecure"))
        algorithm = getattr(settings, "JWT_ALGORITHM", "HS256")
        
        #  Pass audience and issuer explicitly
        payload = jwt.decode(
            token, 
            secret_key,
            algorithms=[algorithm],
            audience=expected_audience,  # Explicitly pass the audience
            issuer=expected_issuer,      # Explicitly pass the issuer
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_nbf": True,
                "require": ["exp", "iat", "sub", "type"],
                "leeway": leeway
            }
        )
        
        logger.debug(f"JWT decode succeeded with payload: {payload}")
        
        # Basic validation - ensure we have a valid subject and type
        if payload.get("type") != "access":
            logger.warning("Token type validation failed")
            return None
            
        username = payload.get("sub")
        if not isinstance(username, str) or not username:
            logger.warning("Token subject validation failed")
            return None
        
        logger.debug(f"Token validated successfully for user: {username}")
        return payload
    except JWTError as e:
        logger.warning(f"JWT validation error: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unexpected JWT validation error: {str(e)}")
        return None