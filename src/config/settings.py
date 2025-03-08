from pydantic_settings import BaseSettings
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse
from pathlib import Path
import os

# Get absolute paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent

class Settings(BaseSettings):
    OKTA_CLIENT_ORGURL: str
    OKTA_API_TOKEN: str
    
    # Database settings with sensible defaults
    DB_DIR: str = str(os.getenv("DB_DIR", str(BASE_DIR / "sqlite_db")))
    DB_FILENAME: str = os.getenv("DB_FILENAME", "okta_sync.db")
    
    # No longer needed in .env - computed from DB_DIR and DB_FILENAME
    DATABASE_URL: Optional[str] = None  
    SQLITE_PATH: Optional[str] = None   
    
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    NUM_OF_THREADS: int = int(os.getenv("NUM_OF_THREADS", "4"))
    
    # JWT Settings
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "CHANGE-THIS-KEY-IN-PRODUCTION-ENVIRONMENTS")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    JWT_ISSUER: str = os.getenv("JWT_ISSUER", "fctr-okta-ai-agent")
    JWT_AUDIENCE: str = os.getenv("JWT_AUDIENCE", "ui-user") 
    
    # Cookie Settings
    COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "True").lower() == "true"
    COOKIE_SAMESITE: str = os.getenv("COOKIE_SAMESITE", "lax")
    COOKIE_MAX_AGE_MINUTES: int = int(os.getenv("COOKIE_MAX_AGE_MINUTES", "30"))
    
    # AI Provider
    AI_PROVIDER: str = os.getenv("AI_PROVIDER", "openai_compatible")
    USE_PRE_REASONING: bool = os.getenv("USE_PRE_REASONING", "true").lower() == "true"
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Create database file path
        db_path = Path(self.DB_DIR) / self.DB_FILENAME
        
        # Create database directory if it doesn't exist
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        # Set both database URLs to the same location for consistency
        self.SQLITE_PATH = str(db_path)
        self.DATABASE_URL = f"sqlite+aiosqlite:///{db_path}"
        
        # Log the actual database location for debugging
        log_level = os.getenv("LOG_LEVEL", "").upper()
        if log_level == "DEBUG":
            print(f"Database location: {db_path}")

    @property
    def tenant_id(self) -> str:
        """Extract tenant ID from OKTA_CLIENT_ORGURL"""
        parsed_url = urlparse(self.OKTA_CLIENT_ORGURL)
        return parsed_url.netloc.split('.')[0]

    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'
        extra = "allow"  # Allow extra fields

# Single instance for import
settings = Settings()