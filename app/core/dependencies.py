"""
Dependency injection for cache managers and other global components
"""
from typing import Optional
import logging

from app.core.cache import CacheManager

logger = logging.getLogger(__name__)

# Global cache manager instances
_embedding_cache: Optional[CacheManager] = None
_llm_cache: Optional[CacheManager] = None
_conversation_cache: Optional[CacheManager] = None

# Global vector store instance (QdrantVectorStore, initialized once at startup)
_vector_store: Optional["QdrantVectorStore"] = None


def set_cache_managers(
    embedding_cache: Optional[CacheManager] = None,
    llm_cache: Optional[CacheManager] = None,
    conversation_cache: Optional[CacheManager] = None
) -> None:
    """
    Set global cache manager instances
    
    Args:
        embedding_cache: CacheManager for embeddings
        llm_cache: CacheManager for LLM responses
        conversation_cache: CacheManager for conversations
    """
    global _embedding_cache, _llm_cache, _conversation_cache
    
    _embedding_cache = embedding_cache
    _llm_cache = llm_cache
    _conversation_cache = conversation_cache
    
    if llm_cache:
        logger.info("✅ Global cache managers initialized")


def get_embedding_cache() -> Optional[CacheManager]:
    """Get the global embedding cache manager"""
    return _embedding_cache


def get_llm_cache() -> Optional[CacheManager]:
    """Get the global LLM cache manager"""
    return _llm_cache


def get_conversation_cache() -> Optional[CacheManager]:
    """Get the global conversation cache manager"""
    return _conversation_cache


def set_vector_store(vector_store: "QdrantVectorStore") -> None:
    """
    Set the global Qdrant vector store instance

    Args:
        vector_store: QdrantVectorStore instance
    """
    global _vector_store
    _vector_store = vector_store
    logger.info("✅ Global Qdrant vector store initialized")


def get_vector_store() -> Optional["QdrantVectorStore"]:
    """
    Get the global Qdrant vector store instance

    Returns:
        QdrantVectorStore instance, or None if not initialized
    """
    return _vector_store
