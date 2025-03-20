from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

@dataclass
class OktaState:
    """Shared state for Okta operations."""
    # User-related state
    users_list: List[Dict[str, Any]] = field(default_factory=list)
    user_details: Optional[Dict[str, Any]] = None
    
    # Group-related state
    groups_list: List[Dict[str, Any]] = field(default_factory=list)
    
    # Application-related state
    applications_list: List[Dict[str, Any]] = field(default_factory=list)
    
    # Other state
    errors: List[str] = field(default_factory=list)
    result: Any = None  # Final result of the operation