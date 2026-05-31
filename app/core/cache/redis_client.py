"""
Async Redis client (``redis.asyncio``) with connection pooling and error handling.

The previous sync implementation blocked the event loop on every cache op; this
version uses ``redis.asyncio`` so all I/O is awaitable. The connection pool is
created eagerly in ``__init__`` (it's a pool object — no network is touched
until the first ``await``).
"""
import redis.asyncio as redis_async
from typing import Optional
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


class RedisClient:
    """
    Async Redis client wrapper with connection pooling and error handling.

    ``__init__`` stays sync — it just wires up the client object. The first
    ``await`` (typically ``is_available()``) is what actually opens a
    connection from the pool.
    """

    def __init__(self):
        """Initialize Redis client. No I/O happens here."""
        self.client: Optional[redis_async.Redis] = None
        self.enabled = settings.redis_enabled

        if self.enabled:
            try:
                self.client = redis_async.Redis(
                    host=settings.redis_host,
                    port=settings.redis_port,
                    db=settings.redis_db,
                    password=settings.redis_password,
                    decode_responses=False,  # bytes in/out — we handle compression
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    retry_on_timeout=True,
                    health_check_interval=30,
                    max_connections=10,
                )
                logger.info(
                    "Redis async client configured: %s:%s",
                    settings.redis_host,
                    settings.redis_port,
                )
            except Exception as e:  # noqa: BLE001 — construction must not raise
                logger.error("Redis client construction failed: %s", e)
                self.enabled = False
                self.client = None

    async def is_available(self) -> bool:
        """Ping Redis; returns True iff the server answers."""
        if not self.enabled or self.client is None:
            return False
        try:
            await self.client.ping()
            return True
        except Exception:
            return False

    async def get(self, key: str) -> Optional[bytes]:
        """
        Get value from Redis.

        Args:
            key: Cache key

        Returns:
            Cached value as bytes or None if not found
        """
        if not self.enabled or self.client is None:
            return None

        try:
            return await self.client.get(key)
        except Exception as e:
            logger.warning(f"Redis GET failed for key {key}: {e}")
            return None

    async def set(self, key: str, value: bytes, ttl: Optional[int] = None) -> bool:
        """
        Set value in Redis with optional TTL.

        Args:
            key: Cache key
            value: Value to cache (bytes)
            ttl: Time to live in seconds (uses default if not specified)

        Returns:
            True if successful, False otherwise
        """
        if not self.enabled or self.client is None:
            return False

        try:
            ttl = ttl or settings.redis_ttl
            await self.client.setex(key, ttl, value)
            return True
        except Exception as e:
            logger.warning(f"Redis SET failed for key {key}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete key from Redis."""
        if not self.enabled or self.client is None:
            return False

        try:
            await self.client.delete(key)
            return True
        except Exception as e:
            logger.warning(f"Redis DELETE failed for key {key}: {e}")
            return False

    async def clear_pattern(self, pattern: str) -> int:
        """
        Delete all keys matching pattern.

        Args:
            pattern: Redis key pattern (e.g., "emb:*")

        Returns:
            Number of keys deleted
        """
        if not self.enabled or self.client is None:
            return 0

        try:
            # Use async scan_iter to avoid blocking on large keyspaces.
            matched: list[bytes] = []
            async for raw_key in self.client.scan_iter(match=pattern, count=500):
                matched.append(raw_key)
            if not matched:
                return 0
            return await self.client.delete(*matched)
        except Exception as e:
            logger.warning(f"Redis CLEAR failed for pattern {pattern}: {e}")
            return 0

    async def scan_pattern(self, pattern: str, count: int = 500) -> list[str]:
        """
        Non-destructively list keys matching a pattern using async SCAN.

        Unlike ``clear_pattern`` (which deletes) and ``KEYS`` (which can block
        the server on large keyspaces), this iterates with SCAN and only reads.

        Args:
            pattern: Redis key glob pattern (e.g., "conv:*")
            count: SCAN cursor hint for batch size; not a hard limit.

        Returns:
            List of matching keys as strings. Empty list if Redis is
            unavailable or on error.
        """
        if not self.enabled or self.client is None:
            return []

        matched: list[str] = []
        try:
            async for raw_key in self.client.scan_iter(match=pattern, count=count):
                if isinstance(raw_key, bytes):
                    matched.append(raw_key.decode("utf-8", errors="replace"))
                else:
                    matched.append(str(raw_key))
            return matched
        except Exception as e:
            logger.warning(f"Redis SCAN failed for pattern {pattern}: {e}")
            return []

    async def close(self) -> None:
        """Close the Redis client and release pool connections."""
        if self.client:
            try:
                await self.client.aclose()
                logger.info("Redis connection closed")
            except Exception as e:
                logger.error(f"Error closing Redis connection: {e}")


# Global Redis client instance
_redis_client: Optional[RedisClient] = None


def get_redis_client() -> RedisClient:
    """Get or create global Redis client instance."""
    global _redis_client
    if _redis_client is None:
        _redis_client = RedisClient()
    return _redis_client
