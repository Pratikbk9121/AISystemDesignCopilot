"""
LangChain-powered embedding generation for RAG pipeline
Supports HuggingFace (local) and OpenAI (via Bifrost) embeddings
"""
from typing import List, Optional
import numpy as np
import logging
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_openai import OpenAIEmbeddings
from langchain_core.embeddings import Embeddings

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingGenerator:
    """
    LangChain-powered embedding generator with support for multiple providers.

    Supported providers:
    - HuggingFace: Local, free, open-source models
    - OpenAI: Via Tekion Bifrost gateway
    """

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None
    ):
        """
        Initialize embedding generator with LangChain

        Args:
            provider: Embedding provider ("huggingface" or "openai")
            model: Model name (provider-specific)
        """
        self.provider = provider or settings.embedding_provider
        self.model = model

        # Initialize LangChain embeddings based on provider
        self.embeddings: Embeddings = self._create_embeddings()
        self.dimension = self._get_embedding_dimension()

    def _create_embeddings(self) -> Embeddings:
        """
        Create LangChain embeddings instance based on provider

        Returns:
            LangChain Embeddings instance
        """
        if self.provider.lower() == "huggingface":
            model_name = self.model or settings.huggingface_model
            logger.info(f"Initializing HuggingFace embeddings: {model_name}")

            return HuggingFaceEmbeddings(
                model_name=model_name,
                model_kwargs=settings.huggingface_model_kwargs,
                encode_kwargs=settings.huggingface_encode_kwargs,
            )

        elif self.provider.lower() == "openai":
            model_name = self.model or settings.embedding_model

            if not settings.tekion_llm_key:
                raise ValueError(
                    "Tekion LLM key not configured. Please set TEKION_LLM_KEY in your .env file.\n"
                    "Contact #ai-platform-support slack channel to get your key."
                )

            logger.info(f"Initializing OpenAI embeddings via Bifrost: {model_name}")

            return OpenAIEmbeddings(
                model=model_name,
                openai_api_key=settings.tekion_llm_key,
                openai_api_base=settings.embeddings_base_url,
                default_headers={
                    "x-bf-vk": settings.tekion_llm_key,
                },
            )

        else:
            raise ValueError(
                f"Unknown embedding provider: {self.provider}. "
                f"Supported options: 'huggingface', 'openai'"
            )

    def _get_embedding_dimension(self) -> int:
        """
        Get the dimension of embeddings for the current model

        Returns:
            Embedding dimension size
        """
        if self.provider.lower() == "huggingface":
            # HuggingFace model dimensions
            dimensions = {
                "BAAI/bge-base-en-v1.5": 768,
                "BAAI/bge-small-en-v1.5": 384,
                "sentence-transformers/all-mpnet-base-v2": 768,
                "sentence-transformers/all-MiniLM-L6-v2": 384,
            }
            model_name = self.model or settings.huggingface_model
            return dimensions.get(model_name, 768)

        elif self.provider.lower() == "openai":
            # OpenAI model dimensions
            dimensions = {
                "text-embedding-3-small": 1536,
                "text-embedding-3-large": 3072,
                "text-embedding-ada-002": 1536,
            }
            model_name = self.model or settings.embedding_model
            return dimensions.get(model_name, 1536)

        return 768  # Default dimension

    def generate_embedding(self, text: str) -> np.ndarray:
        """
        Generate embedding for a single text using LangChain

        Args:
            text: Text to embed

        Returns:
            Numpy array of embedding vector
        """
        try:
            # Use LangChain's embed_query method
            embedding = self.embeddings.embed_query(text)
            return np.array(embedding, dtype=np.float32)

        except Exception as e:
            raise RuntimeError(f"Failed to generate embedding: {str(e)}") from e

    def generate_embeddings(self, texts: List[str]) -> List[np.ndarray]:
        """
        Generate embeddings for multiple texts using LangChain (batched)

        Args:
            texts: List of texts to embed

        Returns:
            List of numpy arrays containing embedding vectors
        """
        if not texts:
            return []

        try:
            # Use LangChain's embed_documents method for batch processing
            embeddings = self.embeddings.embed_documents(texts)

            # Convert to numpy arrays
            return [np.array(emb, dtype=np.float32) for emb in embeddings]

        except Exception as e:
            raise RuntimeError(f"Failed to generate embeddings: {str(e)}") from e

    def batch_generate_embeddings(
        self,
        texts: List[str],
        batch_size: int = 100
    ) -> List[np.ndarray]:
        """
        Generate embeddings in batches for large datasets

        Args:
            texts: List of texts to embed
            batch_size: Number of texts per batch

        Returns:
            List of numpy arrays containing embedding vectors
        """
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            embeddings = self.generate_embeddings(batch)
            all_embeddings.extend(embeddings)

            # Progress logging
            if (i + batch_size) % 500 == 0 or (i + len(batch)) >= len(texts):
                logger.info(f"Processed {min(i + batch_size, len(texts))}/{len(texts)} embeddings")

        return all_embeddings

    def get_langchain_embeddings(self) -> Embeddings:
        """
        Get the underlying LangChain Embeddings instance

        Returns:
            LangChain Embeddings instance
        """
        return self.embeddings


class CachedEmbeddingGenerator(EmbeddingGenerator):
    """
    Embedding generator with Redis caching support
    """

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        cache_manager: Optional[object] = None
    ):
        """
        Initialize cached embedding generator

        Args:
            provider: Embedding provider
            model: Model name
            cache_manager: CacheManager instance for Redis caching
        """
        super().__init__(provider, model)
        self.cache_manager = cache_manager
        self.cache_enabled = settings.cache_embeddings and cache_manager is not None

        if self.cache_enabled:
            logger.info("Embedding caching enabled")

    def generate_embedding(self, text: str) -> np.ndarray:
        """Generate embedding with caching"""
        if not self.cache_enabled:
            return super().generate_embedding(text)

        # Try to get from cache
        cached = self.cache_manager.get_pickle(text, self.provider, self.model)
        if cached is not None:
            logger.debug(f"Embedding cache HIT for text: {text[:50]}...")
            return cached

        # Generate and cache
        logger.debug(f"Embedding cache MISS for text: {text[:50]}...")
        embedding = super().generate_embedding(text)
        self.cache_manager.set_pickle(
            embedding,
            text,
            self.provider,
            self.model,
            ttl=settings.cache_embedding_ttl
        )

        return embedding

    def generate_embeddings(self, texts: List[str]) -> List[np.ndarray]:
        """Generate embeddings with caching"""
        if not self.cache_enabled:
            return super().generate_embeddings(texts)

        results = []
        cache_misses = []
        cache_miss_indices = []

        # Check cache for each text
        for idx, text in enumerate(texts):
            cached = self.cache_manager.get_pickle(text, self.provider, self.model)
            if cached is not None:
                results.append(cached)
            else:
                results.append(None)  # Placeholder
                cache_misses.append(text)
                cache_miss_indices.append(idx)

        # Generate embeddings for cache misses
        if cache_misses:
            logger.info(f"Embedding cache: {len(texts) - len(cache_misses)}/{len(texts)} hits, generating {len(cache_misses)} new")
            new_embeddings = super().generate_embeddings(cache_misses)

            # Store in cache and update results
            for idx, text, embedding in zip(cache_miss_indices, cache_misses, new_embeddings):
                self.cache_manager.set_pickle(
                    embedding,
                    text,
                    self.provider,
                    self.model,
                    ttl=settings.cache_embedding_ttl
                )
                results[idx] = embedding
        else:
            logger.info(f"Embedding cache: {len(texts)}/{len(texts)} hits (100% cache hit rate)")

        return results
