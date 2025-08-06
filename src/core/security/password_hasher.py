from argon2 import PasswordHasher, Type
from argon2.exceptions import VerifyMismatchError, InvalidHash
from datetime import datetime, timedelta, timezone
from src.utils.logging import logger

# Configure Argon2 hasher with enhanced security parameters
ph = PasswordHasher(
    type=Type.ID,      # Explicitly use Argon2id (most secure variant)
    time_cost=4,       # Number of iterations (OWASP recommends ≥ 4)
    memory_cost=131072, # Memory usage in kB (128MB for better security)
    parallelism=4,     # Parallel threads
    hash_len=32,       # Hash output length (256 bits)
    salt_len=16,       # Salt length (128 bits)
)

def hash_password(password: str) -> str:
    """
    Hash a password using Argon2id
    
    Enforces password length limits to prevent DoS attacks
    """
    try:
        # Enforce maximum password length to prevent DoS attacks
        if len(password) > 72:  # bcrypt-compatible length limit
            raise ValueError("Password too long (max 72 characters)")
            
        return ph.hash(password)
    except Exception as e:
        logger.error(f"Error hashing password: {str(e)}")
        raise

def verify_password(stored_hash: str, provided_password: str) -> bool:
    """Verify a password against a stored hash using constant-time comparison"""
    try:
        # Enforce same length limit for verification
        if len(provided_password) > 72:
            return False
            
        ph.verify(stored_hash, provided_password)
        return True
    except VerifyMismatchError:
        return False
    except InvalidHash:
        logger.error("Invalid hash format detected during verification")
        return False
    except Exception as e:
        logger.error(f"Error verifying password: {str(e)}")
        return False

def check_password_needs_rehash(password_hash: str) -> bool:
    """Check if the password hash needs to be upgraded due to parameter changes"""
    try:
        return ph.check_needs_rehash(password_hash)
    except InvalidHash:
        logger.error("Invalid hash format detected during rehash check")
        return True
    except Exception as e:
        logger.error(f"Error checking password rehash: {str(e)}")
        # If there's any error, it's safest to rehash
        return True

def calculate_lockout_time(attempts: int) -> datetime:
    """
    Calculate the lockout time based on number of attempts
    Uses exponential backoff with jitter for better security
    """
    # Exponential backoff: 2^attempts minutes
    import random
    base_minutes = min(2 ** attempts, 60)  # Cap at 60 minutes
    
    # Add random jitter (±20%) to prevent timing attacks
    jitter = random.uniform(0.8, 1.2)
    minutes = base_minutes * jitter
    
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)
