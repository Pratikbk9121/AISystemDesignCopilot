"""
Unit tests for app.core.cache.cache_manager.CacheManager.

The Redis client is mocked via the `mock_redis` fixture in conftest.py — no
live Redis is required. All cache methods are async (post-Slice 7).
"""
import pytest

from app.core.cache.cache_manager import CacheManager


class _PicklableSample:
    """Module-level so pickle can resolve it by qualified name."""

    def __init__(self, n):
        self.n = n

    def __eq__(self, other):
        return isinstance(other, _PicklableSample) and self.n == other.n


@pytest.mark.asyncio
async def test_set_and_get_json_roundtrip(mock_redis):
    """A value stored via set_json is retrievable with the same key parts."""
    cache = CacheManager(mock_redis, namespace="test:")
    payload = {"answer": 42, "items": ["a", "b"]}

    assert await cache.set_json(payload, "key1", "key2") is True
    fetched = await cache.get_json("key1", "key2")

    assert fetched == payload


@pytest.mark.asyncio
async def test_get_json_cache_miss_returns_none(mock_redis):
    """Looking up a never-set key returns None (no exception)."""
    cache = CacheManager(mock_redis, namespace="test:")
    assert await cache.get_json("never", "stored") is None


@pytest.mark.asyncio
async def test_namespace_isolation_prevents_collision(mock_redis):
    """Two CacheManagers with different namespaces don't collide on the same key parts."""
    cache_a = CacheManager(mock_redis, namespace="ns_a:")
    cache_b = CacheManager(mock_redis, namespace="ns_b:")

    await cache_a.set_json({"value": "A"}, "shared", "key")
    await cache_b.set_json({"value": "B"}, "shared", "key")

    assert await cache_a.get_json("shared", "key") == {"value": "A"}
    assert await cache_b.get_json("shared", "key") == {"value": "B"}


@pytest.mark.asyncio
async def test_delete_removes_entry(mock_redis):
    """delete() removes a previously stored value."""
    cache = CacheManager(mock_redis, namespace="test:")
    await cache.set_json({"x": 1}, "k")
    assert await cache.get_json("k") == {"x": 1}

    assert await cache.delete("k") is True
    assert await cache.get_json("k") is None


@pytest.mark.asyncio
async def test_set_pickle_roundtrip(mock_redis):
    """Pickle-based set/get preserves arbitrary Python objects."""
    cache = CacheManager(mock_redis, namespace="pkl:")
    obj = _PicklableSample(7)
    assert await cache.set_pickle(obj, "obj-id") is True
    assert await cache.get_pickle("obj-id") == obj


@pytest.mark.asyncio
async def test_clear_namespace_only_clears_own_keys(mock_redis):
    """clear_namespace() removes only this namespace's keys."""
    cache_a = CacheManager(mock_redis, namespace="ns_a:")
    cache_b = CacheManager(mock_redis, namespace="ns_b:")

    await cache_a.set_json({"v": 1}, "x")
    await cache_b.set_json({"v": 2}, "y")

    cleared = await cache_a.clear_namespace()
    assert cleared >= 1
    assert await cache_a.get_json("x") is None
    assert await cache_b.get_json("y") == {"v": 2}


def test_generated_key_includes_namespace_prefix(mock_redis):
    """Internal key generation prefixes the configured namespace.

    _generate_key takes (namespace, *args); passing None falls back to the
    instance namespace (with trailing ':' stripped on init). This is a sync
    helper — no await needed.
    """
    cache = CacheManager(mock_redis, namespace="emb:")
    key = cache._generate_key(None, "hello", "world")
    assert key.startswith("emb:v")
    explicit = cache._generate_key("override", "hello", "world")
    assert explicit.startswith("override:v")
    assert explicit != key
