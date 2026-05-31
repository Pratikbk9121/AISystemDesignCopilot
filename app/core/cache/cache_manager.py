"""
Cache manager with compression and hash-based key generation
"""
import hashlib
import hmac
import json
import zlib
import pickle
from datetime import datetime
from typing import Any, Optional
import logging

from app.core.cache.redis_client import RedisClient
from app.core.config import settings

logger = logging.getLogger(__name__)

# Bump CACHE_VERSION on any schema-breaking change to invalidate stale entries.
CACHE_VERSION = "1"


def _record_hit(namespace: str) -> None:
    """Bump the Prometheus hit counter; swallow any error.

    Imported locally to avoid pulling the middleware package at module-load
    time (cache_manager is imported transitively from app.core.config users).
    """
    try:
        from app.middleware.metrics import CACHE_HITS

        CACHE_HITS.labels(namespace=namespace).inc()
    except Exception:  # noqa: BLE001 — metrics must not break the cache path
        pass


def _record_miss(namespace: str) -> None:
    """Bump the Prometheus miss counter; swallow any error."""
    try:
        from app.middleware.metrics import CACHE_MISSES

        CACHE_MISSES.labels(namespace=namespace).inc()
    except Exception:  # noqa: BLE001
        pass


def _get_salt_bytes() -> bytes:
    """Return the configured cache key salt as bytes.

    Source of truth is `settings.cache_key_salt` — the prod model-validator
    rejects the dev placeholder, so reaching this in prod implies a real value.
    """
    return settings.cache_key_salt.encode("utf-8")


class DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles datetime objects"""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


class CacheManager:
    """
    High-level cache manager with compression and serialization
    """

    def __init__(self, redis_client: RedisClient, namespace: str = ""):
        """
        Initialize cache manager

        Args:
            redis_client: RedisClient instance
            namespace: Default namespace prefix used when callers don't pass one
                (kept for backward compatibility with existing call sites).
        """
        self.redis = redis_client
        # Strip a trailing colon if a legacy caller passed "emb:" style prefix,
        # so we always render exactly one separator in the final key.
        self.namespace = namespace.rstrip(":")

    def _resolve_namespace(self, namespace: Optional[str]) -> str:
        """Pick the explicit namespace, else fall back to the instance default."""
        if namespace:
            return namespace
        if self.namespace:
            return self.namespace
        return "default"

    def _generate_key(self, namespace: Optional[str], *args: Any) -> str:
        """
        Generate cache key as: ``{namespace}:v{CACHE_VERSION}:{hmac_sha256_hex}``

        Args:
            namespace: Logical cache namespace (e.g., "embed", "llm", "doc").
                If None/empty, falls back to the instance default or "default".
            *args: Arguments to hash into the key body

        Returns:
            Namespaced, version-tagged, HMAC-derived cache key
        """
        ns = self._resolve_namespace(namespace)
        # Convert all args to string and concatenate with a delimiter unlikely to
        # appear in stringified inputs.
        content = "|".join(str(arg) for arg in args).encode("utf-8")
        digest = hmac.new(_get_salt_bytes(), content, hashlib.sha256).hexdigest()
        return f"{ns}:v{CACHE_VERSION}:{digest}"

    def _compress(self, data: bytes) -> bytes:
        """Compress data using zlib"""
        return zlib.compress(data, level=6)

    def _decompress(self, data: bytes) -> bytes:
        """Decompress data using zlib"""
        return zlib.decompress(data)

    async def get_json(self, *key_parts: Any, namespace: Optional[str] = None) -> Optional[dict]:
        """
        Get JSON object from cache

        Args:
            *key_parts: Parts to generate cache key
            namespace: Logical cache namespace; defaults to instance namespace

        Returns:
            Cached JSON object or None
        """
        ns = self._resolve_namespace(namespace)
        key = self._generate_key(namespace, *key_parts)
        data = await self.redis.get(key)

        if data is None:
            _record_miss(ns)
            return None

        # Step 1: decompress. zlib failure on bytes that aren't a valid stream
        # is treated as confirmed corruption -> safe to delete.
        try:
            decompressed = self._decompress(data)
        except zlib.error as e:
            logger.warning(
                f"Corrupt cached payload (zlib) at key {key}: {e}; deleting entry."
            )
            await self.redis.delete(key)
            _record_miss(ns)
            return None
        except Exception as e:
            # Unexpected; treat as transient miss, do NOT delete.
            logger.warning(f"Decompression error for key {key}: {e}; treating as miss.")
            _record_miss(ns)
            return None

        # Step 2: utf-8 decode. Invalid UTF-8 -> confirmed corruption.
        try:
            text = decompressed.decode("utf-8")
        except UnicodeDecodeError as e:
            logger.warning(
                f"Corrupt cached payload (non-utf8) at key {key}: {e}; deleting entry."
            )
            await self.redis.delete(key)
            _record_miss(ns)
            return None

        # Step 3: JSON parse. Could be transient (partial read) — log + miss.
        try:
            result = json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(
                f"JSON decode failed for cached entry at key {key}: {e}; "
                "returning miss without deleting."
            )
            _record_miss(ns)
            return None
        _record_hit(ns)
        return result

    async def set_json(
        self,
        value: dict,
        *key_parts: Any,
        ttl: Optional[int] = None,
        namespace: Optional[str] = None,
    ) -> bool:
        """
        Store JSON object in cache with compression

        Args:
            value: JSON-serializable object to cache
            *key_parts: Parts to generate cache key
            ttl: Time to live in seconds
            namespace: Logical cache namespace; defaults to instance namespace

        Returns:
            True if successful
        """
        key = self._generate_key(namespace, *key_parts)

        try:
            # Use custom encoder to handle datetime objects
            serialized = json.dumps(value, cls=DateTimeEncoder).encode()
            compressed = self._compress(serialized)
            return await self.redis.set(key, compressed, ttl)
        except Exception as e:
            logger.warning(f"Failed to cache JSON: {e}")
            return False

    async def get_pickle(self, *key_parts: Any, namespace: Optional[str] = None) -> Optional[Any]:
        """
        Get pickled object from cache

        Args:
            *key_parts: Parts to generate cache key
            namespace: Logical cache namespace; defaults to instance namespace

        Returns:
            Cached object or None
        """
        ns = self._resolve_namespace(namespace)
        key = self._generate_key(namespace, *key_parts)
        data = await self.redis.get(key)

        if data is None:
            _record_miss(ns)
            return None

        # zlib failure -> confirmed corruption.
        try:
            decompressed = self._decompress(data)
        except zlib.error as e:
            logger.warning(
                f"Corrupt cached payload (zlib) at key {key}: {e}; deleting entry."
            )
            await self.redis.delete(key)
            _record_miss(ns)
            return None
        except Exception as e:
            logger.warning(f"Decompression error for key {key}: {e}; treating as miss.")
            _record_miss(ns)
            return None

        # Pickle errors may be transient (partial network read); do NOT delete.
        try:
            result = pickle.loads(decompressed)
        except (pickle.UnpicklingError, EOFError, AttributeError, ImportError, IndexError) as e:
            logger.warning(
                f"Pickle decode failed for cached entry at key {key}: {e}; "
                "returning miss without deleting."
            )
            _record_miss(ns)
            return None
        except Exception as e:
            logger.warning(f"Unexpected pickle error for key {key}: {e}; treating as miss.")
            _record_miss(ns)
            return None
        _record_hit(ns)
        return result

    async def set_pickle(
        self,
        value: Any,
        *key_parts: Any,
        ttl: Optional[int] = None,
        namespace: Optional[str] = None,
    ) -> bool:
        """
        Store object in cache using pickle with compression

        Args:
            value: Object to cache
            *key_parts: Parts to generate cache key
            ttl: Time to live in seconds
            namespace: Logical cache namespace; defaults to instance namespace

        Returns:
            True if successful
        """
        key = self._generate_key(namespace, *key_parts)

        try:
            serialized = pickle.dumps(value)
            compressed = self._compress(serialized)
            return await self.redis.set(key, compressed, ttl)
        except Exception as e:
            logger.warning(f"Failed to cache pickle: {e}")
            return False

    async def delete(self, *key_parts: Any, namespace: Optional[str] = None) -> bool:
        """Delete cached item"""
        key = self._generate_key(namespace, *key_parts)
        return await self.redis.delete(key)

    async def clear_namespace(self, namespace: Optional[str] = None) -> int:
        """Clear all keys in the given (or instance default) namespace+version."""
        ns = self._resolve_namespace(namespace)
        return await self.redis.clear_pattern(f"{ns}:v{CACHE_VERSION}:*")
