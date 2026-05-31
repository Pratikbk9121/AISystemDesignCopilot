"""
Tests for app.core.state_manager.

Covers:
- In-memory ConversationStateManager basic CRUD + listing.
- Strict-get raises SessionNotFoundError.
- list_sessions does not lose data.
- RedisConversationStateManager (with mocked CacheManager/RedisClient):
  - list_sessions never calls clear_pattern or delete.
  - Malformed cache payloads are treated as cache miss without deletion.
  - Falls back to in-memory when Redis is unavailable.

All state manager methods are now async (Slice 7 — async correctness).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.state_manager import (
    ConversationStateManager,
    RedisConversationStateManager,
    SessionNotFoundError,
)
from app.models.schemas import ConversationHistory


# --------------------------------------------------------------------------- #
# In-memory state manager
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_inmemory_get_conversation_creates_session():
    mgr = ConversationStateManager()
    convo = await mgr.get_conversation("session-a")
    assert isinstance(convo, ConversationHistory)
    assert convo.session_id == "session-a"
    assert convo.messages == []


@pytest.mark.asyncio
async def test_inmemory_add_message_persists_across_get():
    mgr = ConversationStateManager()
    convo = await mgr.get_conversation("session-b")
    convo.add_message("user", "hello")
    convo.add_message("assistant", "hi there")
    await mgr.save_conversation("session-b", convo)

    again = await mgr.get_conversation("session-b")
    assert len(again.messages) == 2
    assert again.messages[0].role == "user"
    assert again.messages[0].content == "hello"
    assert again.messages[1].role == "assistant"


@pytest.mark.asyncio
async def test_inmemory_list_sessions_returns_ids_without_losing_data():
    mgr = ConversationStateManager()
    await mgr.get_conversation("s1")
    await mgr.get_conversation("s2")
    convo = await mgr.get_conversation("s3")
    convo.add_message("user", "still here")

    sessions = await mgr.list_sessions()
    assert set(sessions) == {"s1", "s2", "s3"}

    # Calling list_sessions must not delete or mutate stored data.
    sessions_again = await mgr.list_sessions()
    assert set(sessions_again) == {"s1", "s2", "s3"}
    convo_s3 = await mgr.get_conversation("s3")
    assert convo_s3.messages[0].content == "still here"


@pytest.mark.asyncio
async def test_inmemory_get_session_strict_raises_for_missing():
    mgr = ConversationStateManager()
    with pytest.raises(SessionNotFoundError):
        await mgr.get_session_strict("does-not-exist")

    # And it must not silently create the session as a side effect.
    sessions = await mgr.list_sessions()
    assert "does-not-exist" not in sessions


@pytest.mark.asyncio
async def test_inmemory_delete_conversation_removes_session():
    mgr = ConversationStateManager()
    await mgr.get_conversation("kill-me")
    sessions = await mgr.list_sessions()
    assert "kill-me" in sessions
    await mgr.delete_conversation("kill-me")
    sessions = await mgr.list_sessions()
    assert "kill-me" not in sessions
    # Deleting a missing session is a no-op, not an error.
    await mgr.delete_conversation("never-existed")


# --------------------------------------------------------------------------- #
# Redis-backed state manager (mocked)
# --------------------------------------------------------------------------- #

def _make_mock_cache_manager(namespace: str = "conv:", redis_up: bool = True) -> MagicMock:
    """Build a MagicMock that quacks like a CacheManager with an async redis."""
    cache_manager = MagicMock()
    cache_manager.namespace = namespace
    cache_manager.redis = MagicMock()
    cache_manager.redis.is_available = AsyncMock(return_value=redis_up)
    cache_manager.redis.scan_pattern = AsyncMock(return_value=[])
    cache_manager.redis.delete = AsyncMock(return_value=True)
    cache_manager.redis.clear_pattern = AsyncMock(return_value=0)
    cache_manager.get_json = AsyncMock(return_value=None)
    cache_manager.set_json = AsyncMock(return_value=True)
    cache_manager.delete = AsyncMock(return_value=True)
    cache_manager.clear_namespace = AsyncMock(return_value=0)
    return cache_manager


@pytest.mark.asyncio
async def test_redis_list_sessions_uses_scan_and_never_deletes():
    cache_manager = _make_mock_cache_manager(namespace="conv:")
    cache_manager.redis.scan_pattern = AsyncMock(return_value=[
        "conv:abc123",
        "conv:def456",
        "conv:ghi789",
    ])

    mgr = RedisConversationStateManager(cache_manager)
    sessions = await mgr.list_sessions()

    # Returns the per-key suffix (namespace stripped).
    assert sessions == ["abc123", "def456", "ghi789"]

    # Critically: must use SCAN, never destructive ops.
    cache_manager.redis.scan_pattern.assert_called_once_with("conv:*")
    cache_manager.redis.clear_pattern.assert_not_called()
    cache_manager.redis.delete.assert_not_called()
    cache_manager.delete.assert_not_called()


@pytest.mark.asyncio
async def test_redis_list_sessions_empty_when_no_keys():
    cache_manager = _make_mock_cache_manager()
    cache_manager.redis.scan_pattern = AsyncMock(return_value=[])

    mgr = RedisConversationStateManager(cache_manager)
    assert await mgr.list_sessions() == []
    cache_manager.redis.clear_pattern.assert_not_called()
    cache_manager.redis.delete.assert_not_called()


@pytest.mark.asyncio
async def test_redis_get_conversation_returns_new_on_cache_miss():
    cache_manager = _make_mock_cache_manager()
    cache_manager.get_json = AsyncMock(return_value=None)

    mgr = RedisConversationStateManager(cache_manager)
    convo = await mgr.get_conversation("missing-session")
    assert isinstance(convo, ConversationHistory)
    assert convo.session_id == "missing-session"
    cache_manager.redis.delete.assert_not_called()
    cache_manager.delete.assert_not_called()


@pytest.mark.asyncio
async def test_redis_get_conversation_handles_malformed_cache_without_deleting():
    cache_manager = _make_mock_cache_manager()
    # Missing required `session_id` is fine (it has a factory), but a wrong
    # type for `messages` will trigger ValidationError.
    cache_manager.get_json = AsyncMock(return_value={
        "session_id": "broken",
        "messages": "not-a-list",
    })

    mgr = RedisConversationStateManager(cache_manager)
    convo = await mgr.get_conversation("broken")

    # Treated as cache miss: returns a fresh empty conversation.
    assert isinstance(convo, ConversationHistory)
    assert convo.session_id == "broken"
    assert convo.messages == []

    # And we did NOT delete the malformed entry — that's a write on a read.
    cache_manager.delete.assert_not_called()
    cache_manager.redis.delete.assert_not_called()
    cache_manager.redis.clear_pattern.assert_not_called()


@pytest.mark.asyncio
async def test_redis_get_session_strict_raises_when_missing():
    cache_manager = _make_mock_cache_manager()
    cache_manager.get_json = AsyncMock(return_value=None)

    mgr = RedisConversationStateManager(cache_manager)
    with pytest.raises(SessionNotFoundError):
        await mgr.get_session_strict("nope")
    cache_manager.delete.assert_not_called()


@pytest.mark.asyncio
async def test_redis_save_conversation_serializes_and_calls_set_json():
    cache_manager = _make_mock_cache_manager()
    mgr = RedisConversationStateManager(cache_manager)

    convo = ConversationHistory(session_id="s-save")
    convo.add_message("user", "hi")
    await mgr.save_conversation("s-save", convo)

    assert cache_manager.set_json.call_count == 1
    args, kwargs = cache_manager.set_json.call_args
    payload = args[0]
    assert isinstance(payload, dict)
    assert payload["session_id"] == "s-save"
    assert "s-save" in args  # used as a key part
    assert "ttl" in kwargs


@pytest.mark.asyncio
async def test_redis_falls_back_to_inmemory_when_redis_unavailable():
    """When Redis is_available() returns False on first use, the manager
    degrades to in-memory storage via _ensure_redis()."""
    cache_manager = _make_mock_cache_manager(redis_up=False)

    mgr = RedisConversationStateManager(cache_manager)

    # First operation triggers _ensure_redis() which nulls out cache_manager.
    convo = await mgr.get_conversation("fallback")
    assert mgr.cache_manager is None

    convo.add_message("user", "still works")
    await mgr.save_conversation("fallback", convo)

    # list_sessions on the fallback path must not hit Redis at all.
    sessions = await mgr.list_sessions()
    assert "fallback" in sessions
    cache_manager.redis.scan_pattern.assert_not_called()
    cache_manager.redis.clear_pattern.assert_not_called()
