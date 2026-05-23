"""
Redis client for caching with compression support
"""
import redis
from typing import Optional
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


class RedisClient:
    """
    Redis client wrapper with connection pooling and error handling
    """
    
    def __init__(self):
        """Initialize Redis client with connection pool"""
        self.client: Optional[redis.Redis] = None
        self.enabled = settings.redis_enabled
        
        if self.enabled:
            self._connect()
    
    def _connect(self) -> None:
        """Establish Redis connection with retry logic"""
        try:
            self.client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                db=settings.redis_db,
                password=settings.redis_password,
                decode_responses=False,  # We'll handle encoding for compression
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
                health_check_interval=30,
                max_connections=10
            )
            # Test connection
            self.client.ping()
            logger.info(f"✅ Redis connected: {settings.redis_host}:{settings.redis_port}")
        except Exception as e:
            logger.error(f"❌ Redis connection failed: {e}")
            self.enabled = False
            self.client = None
    
    def is_available(self) -> bool:
        """Check if Redis is available and connected"""
        if not self.enabled or self.client is None:
            return False
        
        try:
            self.client.ping()
            return True
        except Exception:
            return False
    
    def get(self, key: str) -> Optional[bytes]:
        """
        Get value from Redis
        
        Args:
            key: Cache key
            
        Returns:
            Cached value as bytes or None if not found
        """
        if not self.is_available():
            return None
        
        try:
            return self.client.get(key)
        except Exception as e:
            logger.warning(f"Redis GET failed for key {key}: {e}")
            return None
    
    def set(self, key: str, value: bytes, ttl: Optional[int] = None) -> bool:
        """
        Set value in Redis with optional TTL
        
        Args:
            key: Cache key
            value: Value to cache (bytes)
            ttl: Time to live in seconds (uses default if not specified)
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_available():
            return False
        
        try:
            ttl = ttl or settings.redis_ttl
            self.client.setex(key, ttl, value)
            return True
        except Exception as e:
            logger.warning(f"Redis SET failed for key {key}: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """Delete key from Redis"""
        if not self.is_available():
            return False
        
        try:
            self.client.delete(key)
            return True
        except Exception as e:
            logger.warning(f"Redis DELETE failed for key {key}: {e}")
            return False
    
    def clear_pattern(self, pattern: str) -> int:
        """
        Delete all keys matching pattern

        Args:
            pattern: Redis key pattern (e.g., "emb:*")

        Returns:
            Number of keys deleted
        """
        if not self.is_available():
            return 0

        try:
            keys = self.client.keys(pattern)
            if keys:
                return self.client.delete(*keys)
            return 0
        except Exception as e:
            logger.warning(f"Redis CLEAR failed for pattern {pattern}: {e}")
            return 0

    def scan_pattern(self, pattern: str, count: int = 500) -> list[str]:
        """
        Non-destructively list keys matching a pattern using SCAN.

        Unlike ``clear_pattern`` (which deletes) and ``KEYS`` (which can block
        the server on large keyspaces), this iterates with SCAN and only reads.

        Args:
            pattern: Redis key glob pattern (e.g., "conv:*")
            count: SCAN cursor hint for batch size; not a hard limit.

        Returns:
            List of matching keys as strings. Empty list if Redis is
            unavailable or on error.
        """
        if not self.is_available():
            return []

        matched: list[str] = []
        try:
            for raw_key in self.client.scan_iter(match=pattern, count=count):
                if isinstance(raw_key, bytes):
                    matched.append(raw_key.decode("utf-8", errors="replace"))
                else:
                    matched.append(str(raw_key))
            return matched
        except Exception as e:
            logger.warning(f"Redis SCAN failed for pattern {pattern}: {e}")
            return []
    
    def close(self) -> None:
        """Close Redis connection"""
        if self.client:
            try:
                self.client.close()
                logger.info("Redis connection closed")
            except Exception as e:
                logger.error(f"Error closing Redis connection: {e}")


# Global Redis client instance
_redis_client: Optional[RedisClient] = None


def get_redis_client() -> RedisClient:
    """Get or create global Redis client instance"""
    global _redis_client
    if _redis_client is None:
        _redis_client = RedisClient()
    return _redis_client
