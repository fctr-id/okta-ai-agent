from pydantic_settings import BaseSettings
from datetime import datetime
from typing import Optional, List
from urllib.parse import urlparse
from pathlib import Path
import os, math
import logging

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
    
    # Custom user attributes
    OKTA_USER_CUSTOM_ATTRIBUTES: str = os.getenv("OKTA_USER_CUSTOM_ATTRIBUTES", "")
    
    # Deprovisioned user sync settings
    SYNC_DEPROVISIONED_USERS: bool = os.getenv("SYNC_DEPROVISIONED_USERS", "true").lower() == "true"
    DEPR_USER_CREATED_AFTER: str = os.getenv("DEPR_USER_CREATED_AFTER", "")
    DEPR_USER_UPDATED_AFTER: str = os.getenv("DEPR_USER_UPDATED_AFTER", "")
    
    # device syncing
    SYNC_OKTA_DEVICES: bool = os.getenv("SYNC_OKTA_DEVICES", "false").lower() == "true"
    
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
    
    #Okta API concurrent limits setting
    # Actual Okta limits: Free/One App=35, Workforce/Customer Identity=75, DynamicScale=75+
    # Default is 18 (recommended for Free/Integrator accounts at 50% rate limit slider - the default)
    # Users should adjust based on their plan and rate limit percentage (see README table)
    OKTA_CONCURRENT_LIMIT: int = int(os.environ.get("OKTA_CONCURRENT_LIMIT", "18"))

    
    # AI Provider
    AI_PROVIDER: str = os.getenv("AI_PROVIDER", "openai_compatible")
    USE_PRE_REASONING: bool = os.getenv("USE_PRE_REASONING", "true").lower() == "true"
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Normalize Okta URL - remove trailing slash for consistency
        if self.OKTA_CLIENT_ORGURL and self.OKTA_CLIENT_ORGURL.endswith('/'):
            self.OKTA_CLIENT_ORGURL = self.OKTA_CLIENT_ORGURL.rstrip('/')
        
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
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"Database location: {db_path}")
            
        # Validate deprovisioned user sync settings
        self._validate_deprovisioned_user_settings()

    def _validate_deprovisioned_user_settings(self):
        """Validate the deprovisioned user sync date settings"""
        
        # Validate date formats
        for date_setting, date_value in [
            ("DEPR_USER_CREATED_AFTER", self.DEPR_USER_CREATED_AFTER),
            ("DEPR_USER_UPDATED_AFTER", self.DEPR_USER_UPDATED_AFTER)
        ]:
            if date_value:
                try:
                    # Try to parse the date to validate format
                    datetime.strptime(date_value, "%Y-%m-%d")
                    logging.info(f"Using {date_setting}: {date_value}")
                except ValueError:
                    logging.error(f"Invalid date format for {date_setting}: {date_value}. Use YYYY-MM-DD format.")
                    raise ValueError(f"Invalid date format for {date_setting}. Use YYYY-MM-DD format (e.g., 2024-01-01)")
        
        # Log sync configuration
        if self.SYNC_DEPROVISIONED_USERS:
            if not self.DEPR_USER_CREATED_AFTER and not self.DEPR_USER_UPDATED_AFTER:
                logging.info("Deprovisioned users: ALL will be included in sync")
            else:
                conditions = []
                if self.DEPR_USER_CREATED_AFTER:
                    conditions.append(f"created after {self.DEPR_USER_CREATED_AFTER}")
                if self.DEPR_USER_UPDATED_AFTER:
                    conditions.append(f"updated after {self.DEPR_USER_UPDATED_AFTER}")
                logging.info(f"Deprovisioned users: Only those {' and '.join(conditions)} will be included in sync")
        else:
            logging.info("Deprovisioned users: EXCLUDED from sync (default Okta behavior)")

    @property
    def tenant_id(self) -> str:
        """Extract tenant ID from OKTA_CLIENT_ORGURL"""
        parsed_url = urlparse(self.OKTA_CLIENT_ORGURL)
        return parsed_url.netloc.split('.')[0]
    
    @property
    def MAX_CONCURRENT_USERS(self) -> int:
        """Calculate the maximum number of concurrent users based on rate limit (rounded down)"""
        # We make ~2 calls per user (groups, factors) so we can run Limit/2 safely
        # Formula: Concurrency = (RPM/60) * (latency_ms/1000)
        return max(1, math.floor(self.OKTA_CONCURRENT_LIMIT / 2))
    
    @property
    def MAX_CONCURRENT_APPS(self) -> int:
        """Calculate the maximum number of concurrent apps based on apps API rate limit"""
        # /api/v1/apps/{id}/users endpoint: 500 req/min limit
        # 0.4 multiplier balances speed vs safety
        # Free tier (35): 14 apps | Workforce (75): 30 apps
        # RATE_LIMIT_DELAY and natural latency keep us under 500 RPM limit
        return max(1, math.floor(self.OKTA_CONCURRENT_LIMIT * 0.4))        
    
    @property
    def MAX_CONCURRENT_GROUPS(self) -> int:
        """Calculate the maximum number of concurrent groups"""
        # Groups API has similar limits to users (500-600/min for premium tiers)
        # Groups don't make additional API calls per group (unlike users)
        # So we can use a higher percentage of the concurrent limit
        return max(1, math.floor(self.OKTA_CONCURRENT_LIMIT * 0.8))    

    # Helper properties to parse the comma-separated strings
    @property
    def okta_user_custom_attributes_list(self) -> List[str]:
        """Parse OKTA_USER_CUSTOM_ATTRIBUTES into a list, filtering out empty strings"""
        if not self.OKTA_USER_CUSTOM_ATTRIBUTES:
            return []
        return [attr.strip() for attr in self.OKTA_USER_CUSTOM_ATTRIBUTES.split(',') if attr.strip()]

    # Helper properties for deprovisioned user date filters
    @property
    def depr_user_created_after_iso(self) -> str:
        """Convert DEPR_USER_CREATED_AFTER to ISO format for Okta API"""
        if self.DEPR_USER_CREATED_AFTER:
            try:
                # Validate the date format first
                datetime.strptime(self.DEPR_USER_CREATED_AFTER, "%Y-%m-%d")
                return f"{self.DEPR_USER_CREATED_AFTER}T00:00:00.000Z"
            except ValueError:
                logging.error(f"Invalid DEPR_USER_CREATED_AFTER format: {self.DEPR_USER_CREATED_AFTER}")
                raise ValueError(f"DEPR_USER_CREATED_AFTER must be in YYYY-MM-DD format, got: {self.DEPR_USER_CREATED_AFTER}")
        return ""
    
    @property
    def depr_user_updated_after_iso(self) -> str:
        """Convert DEPR_USER_UPDATED_AFTER to ISO format for Okta API"""
        if self.DEPR_USER_UPDATED_AFTER:
            try:
                # Validate the date format first
                datetime.strptime(self.DEPR_USER_UPDATED_AFTER, "%Y-%m-%d")
                return f"{self.DEPR_USER_UPDATED_AFTER}T00:00:00.000Z"
            except ValueError:
                logging.error(f"Invalid DEPR_USER_UPDATED_AFTER format: {self.DEPR_USER_UPDATED_AFTER}")
                raise ValueError(f"DEPR_USER_UPDATED_AFTER must be in YYYY-MM-DD format, got: {self.DEPR_USER_UPDATED_AFTER}")
        return ""

    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'
        extra = "allow"  # Allow extra fields

# Single instance for import
settings = Settings()