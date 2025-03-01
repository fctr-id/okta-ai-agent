from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from datetime import datetime, timedelta, timezone
from src.utils.logging import logger

# Configure Argon2 hasher with recommended security parameters
ph = PasswordHasher(
    time_cost=3,       # Number of iterations
    memory_cost=65536, # Memory usage in kB (64MB)
    parallelism=4,     # Parallel threads
    hash_len=32,       # Hash output length
    salt_len=16,       # Salt length
)

def hash_password(password: str) -> str:
    """Hash a password using Argon2id"""
    try:
        return ph.hash(password)
    except Exception as e:
        logger.error(f"Error hashing password: {e}")
        raise

def verify_password(stored_hash: str, provided_password: str) -> bool:
    """Verify a password against a stored hash"""
    try:
        ph.verify(stored_hash, provided_password)
        return True
    except VerifyMismatchError:
        return False
    except Exception as e:
        logger.error(f"Error verifying password: {e}")
        return False

def check_password_needs_rehash(password_hash: str) -> bool:
    """Check if the password hash needs to be upgraded"""
    try:
        return ph.check_needs_rehash(password_hash)
    except Exception:
        # If there's any error, it's safest to rehash
        return True

def calculate_lockout_time(attempts: int) -> datetime:
    """Calculate the lockout time based on number of attempts"""
    # Exponential backoff: 2^attempts minutes
    minutes = min(2 ** attempts, 60)  # Cap at 60 minutes
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)