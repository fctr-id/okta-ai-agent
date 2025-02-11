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
    NUM_OF_THREADS: int = os.getenv("NUM_OF_THREADS")
   

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
        extra = "allow"  # Allow extra fields

settings = Settings()