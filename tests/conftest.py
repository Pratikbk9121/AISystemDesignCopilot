"""
Shared pytest fixtures for the test suite.
"""
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_redis():
    """
    Provide a MagicMock that mimics the RedisClient surface used by CacheManager.

    The mock starts with an in-memory dict so tests can exercise round-trips
    (set then get) without requiring a live Redis instance.
    """
    store: dict[str, bytes] = {}

    client = MagicMock()

    def _get(key: str):
        return store.get(key)

    def _set(key: str, value: bytes, ttl=None):
        store[key] = value
        return True

    def _delete(key: str):
        return store.pop(key, None) is not None

    def _clear_pattern(pattern: str):
        prefix = pattern.rstrip("*")
        keys = [k for k in store if k.startswith(prefix)]
        for k in keys:
            del store[k]
        return len(keys)

    client.get.side_effect = _get
    client.set.side_effect = _set
    client.delete.side_effect = _delete
    client.clear_pattern.side_effect = _clear_pattern
    client.is_available.return_value = True
    client._store = store  # exposed for assertions in tests
    return client


@pytest.fixture
def sample_documents():
    """A small set of sample documents for vector-store / RAG-style tests."""
    return [
        {
            "content": "Design a scalable ride-sharing system like Uber.",
            "metadata": {"topic": "system-design", "difficulty": "hard"},
        },
        {
            "content": "Implement a URL shortener service.",
            "metadata": {"topic": "system-design", "difficulty": "medium"},
        },
        {
            "content": "Design a distributed in-memory cache.",
            "metadata": {"topic": "system-design", "difficulty": "hard"},
        },
    ]
