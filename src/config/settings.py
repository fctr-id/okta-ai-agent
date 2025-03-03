from pydantic_settings import BaseSettings
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse
from pathlib import Path
import os

# Get absolute paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_DIR = BASE_DIR / "sqlite_db"
DB_FILE = DB_DIR / "okta_sync.db"

class Settings(BaseSettings):
    OKTA_CLIENT_ORGURL: str
    OKTA_CLIENT_TOKEN: str
    DATABASE_URL: str = None  # Will be set in __init__
    SYNC_INTERVAL_HOURS: int = 1
    LOG_LEVEL: str = "INFO"
    NUM_OF_THREADS: int = int(os.getenv("NUM_OF_THREADS", "4"))
    
    # JWT Settings
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "CHANGE-THIS-KEY-IN-PRODUCTION-ENVIRONMENTS")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30"))  # make sure it matches the cookie_max_age_minutes
    JWT_ISSUER: str = os.getenv("JWT_ISSUER", "fctr-okta-ai-agent")
    JWT_AUDIENCE: str = os.getenv("JWT_AUDIENCE", "ui-user") 
    
    # Cookie Settings
    COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "True").lower() == "true"
    COOKIE_SAMESITE: str = os.getenv("COOKIE_SAMESITE", "lax")
    COOKIE_MAX_AGE_MINUTES: int = int(os.getenv("COOKIE_MAX_AGE_MINUTES", "30"))  # 30 minutes
    
    # SQLite path (used by auth migration)
    SQLITE_PATH: str = str(DB_FILE)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Create database directory if it doesn't exist
        os.makedirs(DB_DIR, exist_ok=True)
        # Set database URL after ensuring directory exists
        self.DATABASE_URL = f"sqlite+aiosqlite:///{DB_FILE}"

    @property
    def tenant_id(self) -> str:
        """Extract tenant ID from OKTA_CLIENT_ORGURL"""
        parsed_url = urlparse(self.OKTA_CLIENT_ORGURL)
        return parsed_url.netloc.split('.')[0]

    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'
        extra = "allow"  # Allow extra fields

settings = Settings()