from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field

# Common response models for all agents
class RateLimited(BaseModel):
    """Response when Okta API rate limits are hit."""
    message: str
    partial_results: Optional[Any] = None
    rate_limit_reset: Optional[int] = None
    
    def __str__(self) -> str:
        reset_info = f", reset in {self.rate_limit_reset}s" if self.rate_limit_reset else ""
        return f"Rate limited: {self.message}{reset_info}"

class EntityError(BaseModel):
    """Error response from entity agent."""
    message: str
    error_type: str
    entity: str
    
    def __str__(self) -> str:
        return f"{self.error_type} error for {self.entity}: {self.message}"

class EntityResponse(BaseModel):
    """Base class for all entity responses."""
    metadata: Dict[str, Any] = Field(default_factory=dict)