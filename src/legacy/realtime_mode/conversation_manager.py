import time
import logging
import hashlib
from typing import Dict, List, Optional, Any, Tuple
from threading import RLock
from pydantic_ai.messages import ModelMessagesTypeAdapter

logger = logging.getLogger(__name__)

class ConversationManager:
    """Manage conversation histories for users with IP-based identification.
    
    This class maintains a map of conversation histories keyed by a hash of the user's IP
    and other identifying information, allowing for stateful interactions with the agents.
    """
    
    def __init__(self, max_conversations: int = 1000, max_history_per_user: int = 10):
        """Initialize the conversation manager.
        
        Args:
            max_conversations: Maximum number of distinct users to track
            max_history_per_user: Maximum number of messages to retain per user
        """
        self.conversations: Dict[str, List[Any]] = {}
        self.conversation_times: Dict[str, float] = {}  # For LRU tracking
        self.max_conversations = max_conversations
        self.max_history_per_user = max_history_per_user
        self.lock = RLock()  # Thread safety
    
    def generate_user_key(self, ip_address: str, user_agent: Optional[str] = None) -> str:
        """Generate a unique key for the user based on their IP and user agent.
        
        Args:
            ip_address: The user's IP address
            user_agent: The user's browser user agent string, if available
            
        Returns:
            A hashed identifier for the user
        """
        # Create a composite key
        key_material = f"{ip_address}:{user_agent or 'unknown'}"
        # Create a hash to avoid storing raw IP addresses
        return hashlib.sha256(key_material.encode()).hexdigest()
    
    def get_conversation(self, user_key: str) -> List[Any]:
        """Get conversation history for a user.
        
        Args:
            user_key: The user's unique key
            
        Returns:
            The list of conversation messages
        """
        with self.lock:
            # Update access time
            if user_key in self.conversations:
                self.conversation_times[user_key] = time.time()
                
            return self.conversations.get(user_key, [])
    
    def update_conversation(self, user_key: str, messages: List[Any]) -> None:
        """Update conversation history for a user.
        
        Args:
            user_key: The user's unique key
            messages: The new conversation messages
        """
        with self.lock:
            # Check if we need to evict the least recently used conversation
            if user_key not in self.conversations and len(self.conversations) >= self.max_conversations:
                self._evict_lru_conversation()
            
            # Limit history length per user
            if len(messages) > self.max_history_per_user:
                messages = messages[-self.max_history_per_user:]
            
            self.conversations[user_key] = messages
            self.conversation_times[user_key] = time.time()
    
    def _evict_lru_conversation(self) -> None:
        """Remove the least recently used conversation to free memory."""
        if not self.conversation_times:
            return
            
        # Find least recently used
        lru_key = min(self.conversation_times, key=self.conversation_times.get)
        
        # Remove it
        self.conversations.pop(lru_key, None)
        self.conversation_times.pop(lru_key, None)
        logger.info(f"Evicted conversation for user key: {lru_key[:8]}...")
    
    def serialize_conversation(self, user_key: str) -> Optional[str]:
        """Serialize conversation to JSON string.
        
        Args:
            user_key: The user's unique key
            
        Returns:
            JSON string of the conversation or None if no conversation exists
        """
        messages = self.get_conversation(user_key)
        if not messages:
            return None
        
        # Use ModelMessagesTypeAdapter to serialize
        return ModelMessagesTypeAdapter.dump_json(messages)
    
    def deserialize_conversation(self, json_str: str) -> List[Any]:
        """Deserialize conversation from JSON string.
        
        Args:
            json_str: JSON string of the conversation
            
        Returns:
            List of conversation messages
        """
        if not json_str:
            return []
            
        return ModelMessagesTypeAdapter.parse_json(json_str)

# Create a global instance that can be imported across modules
conversation_manager = ConversationManager()