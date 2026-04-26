"""
Conversation state management for tracking chat history and session states
"""
from typing import Dict
from threading import Lock

from app.models.schemas import ConversationHistory


class ConversationStateManager:
    """
    Manages conversation states and history across sessions.
    
    In production, this should be backed by Redis or a persistent database.
    Currently using in-memory storage for development.
    """
    
    def __init__(self):
        """Initialize the state manager with in-memory storage"""
        self._conversations: Dict[str, ConversationHistory] = {}
        self._lock = Lock()
    
    def get_conversation(self, session_id: str) -> ConversationHistory:
        """
        Retrieve conversation history for a session.
        Creates a new conversation if it doesn't exist.
        
        Args:
            session_id: The session identifier
        
        Returns:
            ConversationHistory for the session
        """
        with self._lock:
            if session_id not in self._conversations:
                self._conversations[session_id] = ConversationHistory(session_id=session_id)
            return self._conversations[session_id]
    
    def save_conversation(self, session_id: str, conversation: ConversationHistory) -> None:
        """
        Save or update conversation history.
        
        Args:
            session_id: The session identifier
            conversation: The conversation history to save
        """
        with self._lock:
            self._conversations[session_id] = conversation
    
    def delete_conversation(self, session_id: str) -> None:
        """
        Delete conversation history for a session.
        
        Args:
            session_id: The session identifier
        """
        with self._lock:
            if session_id in self._conversations:
                del self._conversations[session_id]
    
    def list_sessions(self) -> list[str]:
        """
        List all active session IDs.
        
        Returns:
            List of session IDs
        """
        with self._lock:
            return list(self._conversations.keys())
    
    def clear_all(self) -> None:
        """
        Clear all conversation histories.
        Use with caution - typically for testing only.
        """
        with self._lock:
            self._conversations.clear()


# TODO: Implement Redis-backed state manager for production
class RedisConversationStateManager(ConversationStateManager):
    """
    Redis-backed conversation state manager for production use.
    Provides persistence and distributed session management.
    """
    
    def __init__(self, redis_client=None):
        """
        Initialize Redis state manager
        
        Args:
            redis_client: Redis client instance
        """
        super().__init__()
        self.redis_client = redis_client
        # TODO: Implement Redis-specific methods
