"""
Conversation state management for tracking chat history and session states.

Async interface
---------------
Both the in-memory and Redis-backed managers expose async methods so call
sites don't need to branch on which backend is active. The in-memory variant
is trivially async (no I/O — just dict operations under a threading.Lock).
"""
from typing import Dict, Optional
from threading import Lock
import logging

from pydantic import ValidationError

from app.models.schemas import ConversationHistory
from app.core.config import settings

logger = logging.getLogger(__name__)


class SessionNotFoundError(KeyError):
    """Raised when a strict session lookup is performed and the session is absent."""


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

    async def get_conversation(self, session_id: str) -> ConversationHistory:
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

    async def get_session_strict(self, session_id: str) -> ConversationHistory:
        """
        Retrieve conversation history for an existing session without creating one.

        Args:
            session_id: The session identifier

        Returns:
            ConversationHistory for the session

        Raises:
            SessionNotFoundError: If the session does not exist.
        """
        with self._lock:
            if session_id not in self._conversations:
                raise SessionNotFoundError(session_id)
            return self._conversations[session_id]

    async def save_conversation(self, session_id: str, conversation: ConversationHistory) -> None:
        """
        Save or update conversation history.

        Args:
            session_id: The session identifier
            conversation: The conversation history to save
        """
        with self._lock:
            self._conversations[session_id] = conversation

    async def delete_conversation(self, session_id: str) -> None:
        """
        Delete conversation history for a session.

        Args:
            session_id: The session identifier
        """
        with self._lock:
            if session_id in self._conversations:
                del self._conversations[session_id]

    async def list_sessions(self) -> list[str]:
        """
        List all active session IDs.

        Returns:
            List of session IDs
        """
        with self._lock:
            return list(self._conversations.keys())

    async def clear_all(self) -> None:
        """
        Clear all conversation histories.
        Use with caution - typically for testing only.
        """
        with self._lock:
            self._conversations.clear()


class RedisConversationStateManager(ConversationStateManager):
    """
    Redis-backed conversation state manager for production use.
    Provides persistence and distributed session management.

    Construction is sync — we just stash the cache_manager. The is_available
    probe runs lazily on first read/write so __init__ stays non-blocking.
    """

    def __init__(self, cache_manager: Optional[object] = None):
        """
        Initialize Redis state manager

        Args:
            cache_manager: CacheManager instance with namespace "conv:"
        """
        super().__init__()
        self.cache_manager = cache_manager

        if cache_manager is not None:
            logger.info("Redis conversation state manager configured")

    async def _ensure_redis(self) -> bool:
        """Probe Redis once; on failure, null out cache_manager and warn.

        Returns True if Redis is usable, False if we've degraded to in-memory.
        Mutates self.cache_manager on first failure so subsequent calls take
        the cheap branch.
        """
        if self.cache_manager is None:
            return False
        try:
            if await self.cache_manager.redis.is_available():
                return True
        except Exception as e:  # noqa: BLE001 — degraded mode shouldn't crash
            logger.warning("Redis is_available() raised: %s; degrading to in-memory.", e)
        logger.warning("Redis not available, falling back to in-memory storage")
        self.cache_manager = None
        return False

    async def get_conversation(self, session_id: str) -> ConversationHistory:
        """
        Retrieve conversation history from Redis.
        Creates a new conversation if it doesn't exist.
        """
        if not await self._ensure_redis():
            return await super().get_conversation(session_id)

        cached = await self.cache_manager.get_json(session_id)
        if not cached:
            return ConversationHistory(session_id=session_id)

        # Defensive deserialization: a malformed cache entry must not poison
        # the read path. Treat parse failures as a cache miss; do NOT delete
        # the entry — that's a write side-effect on a read.
        try:
            return ConversationHistory(**cached)
        except (ValidationError, TypeError) as e:
            logger.warning(
                "Malformed cached conversation for session %s: %s; treating as cache miss",
                session_id,
                e,
            )
            return ConversationHistory(session_id=session_id)

    async def get_session_strict(self, session_id: str) -> ConversationHistory:
        """
        Retrieve a session from Redis without creating one.

        Raises:
            SessionNotFoundError: If the session does not exist in Redis.
        """
        if not await self._ensure_redis():
            return await super().get_session_strict(session_id)

        cached = await self.cache_manager.get_json(session_id)
        if not cached:
            raise SessionNotFoundError(session_id)

        try:
            return ConversationHistory(**cached)
        except (ValidationError, TypeError) as e:
            logger.warning(
                "Malformed cached conversation for session %s: %s; treating as missing",
                session_id,
                e,
            )
            raise SessionNotFoundError(session_id) from e

    async def save_conversation(
        self, session_id: str, conversation: ConversationHistory
    ) -> None:
        """Save conversation history to Redis with TTL."""
        if not await self._ensure_redis():
            return await super().save_conversation(session_id, conversation)

        conversation_data = (
            conversation.model_dump()
            if hasattr(conversation, "model_dump")
            else conversation.dict()
        )
        await self.cache_manager.set_json(
            conversation_data, session_id, ttl=settings.cache_conversation_ttl
        )

    async def delete_conversation(self, session_id: str) -> None:
        """Delete conversation history from Redis."""
        if not await self._ensure_redis():
            return await super().delete_conversation(session_id)
        await self.cache_manager.delete(session_id)

    async def list_sessions(self) -> list[str]:
        """
        List all active session keys from Redis using non-destructive SCAN.

        NOTE: Cache keys are SHA256-hashed by ``CacheManager._generate_key``,
        so the original session_id strings are not recoverable from the keys
        themselves. We return the per-key suffix (the part after the
        namespace prefix) which uniquely identifies each stored session.
        """
        if not await self._ensure_redis():
            return await super().list_sessions()

        namespace = self.cache_manager.namespace or ""
        pattern = f"{namespace}*"
        matched_keys = await self.cache_manager.redis.scan_pattern(pattern)

        session_ids: list[str] = []
        for key in matched_keys:
            if namespace and key.startswith(namespace):
                session_ids.append(key[len(namespace):])
            else:
                session_ids.append(key)

        logger.info("Found %d conversation sessions", len(session_ids))
        return session_ids

    async def clear_all(self) -> None:
        """Clear all conversation histories from Redis."""
        if not await self._ensure_redis():
            return await super().clear_all()

        num_cleared = await self.cache_manager.clear_namespace()
        logger.info("Cleared %d conversations from cache", num_cleared)


def create_state_manager(
    cache_manager: Optional[object] = None,
) -> ConversationStateManager | RedisConversationStateManager:
    """
    Factory function to create the appropriate state manager based on settings.

    Args:
        cache_manager: CacheManager instance for Redis-backed state

    Returns:
        ConversationStateManager or RedisConversationStateManager
    """
    if settings.redis_enabled and settings.cache_conversations and cache_manager:
        logger.info("Using Redis-backed state manager")
        return RedisConversationStateManager(cache_manager)
    else:
        logger.info("Using in-memory state manager")
        return ConversationStateManager()
