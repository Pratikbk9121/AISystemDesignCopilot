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

# BGE models (BAAI/bge-*) recommend prefixing QUERIES (not passages) with a
# short instruction so the bi-encoder maps queries into the same semantic
# region as passages. See the BAAI/bge-base-en-v1.5 model card. We apply it
# only when (provider == "huggingface" AND model startswith "BAAI/bge") to
# avoid polluting other embedding stacks.
_BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def _bge_query_prefix_applies(provider: str, model_name: str) -> bool:
    """Return True iff the active embedding stack benefits from the BGE
    query-side instruction prefix."""
    return provider.lower() == "huggingface" and model_name.startswith("BAAI/bge")


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

    def _maybe_prefix_query(self, text: str, is_query: bool) -> str:
        """Apply the BGE query-side instruction prefix when applicable.

        Only triggers for ``provider == "huggingface"`` AND a ``BAAI/bge*``
        model. All other configurations get the raw text back. This must
        run BEFORE any cache lookup so cached vectors stay consistent with
        the actual encoded input.
        """
        if not is_query:
            return text
        model_name = self.model or settings.huggingface_model
        if _bge_query_prefix_applies(self.provider, model_name):
            return f"{_BGE_QUERY_PREFIX}{text}"
        return text

    async def generate_embedding(
        self, text: str, is_query: bool = False
    ) -> np.ndarray:
        """
        Generate embedding for a single text using LangChain.

        Async-by-interface so callers can ``await`` regardless of whether the
        caching subclass is in play. The underlying LangChain call itself is
        sync — wrap via asyncio.to_thread when called from an async context
        if you need to free the event loop.

        Args:
            text: Text to embed.
            is_query: When True and the active stack is BGE+HuggingFace, the
                BGE query-side instruction prefix is prepended. Pass True from
                vector-search call sites; leave False (default) for passage
                embeddings to keep the index identical to its build-time
                ingestion vectors.
        """
        try:
            effective_text = self._maybe_prefix_query(text, is_query)
            # Use LangChain's embed_query method
            embedding = self.embeddings.embed_query(effective_text)
            return np.array(embedding, dtype=np.float32)

        except Exception as e:
            raise RuntimeError(f"Failed to generate embedding: {str(e)}") from e

    async def generate_embeddings(
        self, texts: List[str], is_query: bool = False
    ) -> List[np.ndarray]:
        """
        Generate embeddings for multiple texts using LangChain (batched).

        Async-by-interface so callers can ``await`` regardless of whether the
        caching subclass is in play.

        Args:
            texts: Texts to embed.
            is_query: When True and the active stack is BGE+HuggingFace, the
                BGE query-side instruction prefix is prepended to every text
                before encoding. Mirrors :meth:`generate_embedding`.
        """
        if not texts:
            return []

        try:
            effective_texts = (
                [self._maybe_prefix_query(t, is_query=True) for t in texts]
                if is_query
                else texts
            )
            # Use LangChain's embed_documents method for batch processing
            embeddings = self.embeddings.embed_documents(effective_texts)

            # Convert to numpy arrays
            return [np.array(emb, dtype=np.float32) for emb in embeddings]

        except Exception as e:
            raise RuntimeError(f"Failed to generate embeddings: {str(e)}") from e

    async def batch_generate_embeddings(
        self,
        texts: List[str],
        batch_size: int = 100,
        is_query: bool = False,
    ) -> List[np.ndarray]:
        """
        Generate embeddings in batches for large datasets.

        Args:
            texts: List of texts to embed
            batch_size: Number of texts per batch
            is_query: Forwarded to :meth:`generate_embeddings` for BGE prefix.

        Returns:
            List of numpy arrays containing embedding vectors
        """
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            embeddings = await self.generate_embeddings(batch, is_query=is_query)
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

    async def generate_embedding(
        self, text: str, is_query: bool = False
    ) -> np.ndarray:
        """Generate embedding with caching (async to await Redis I/O).

        ``is_query`` is forwarded to the base class so BGE query-side
        prefixing kicks in for search calls. The cache key uses the
        *effective* (prefixed) text so query-cache and passage-cache stay in
        separate keyspaces and never alias each other.
        """
        if not self.cache_enabled:
            return await super().generate_embedding(text, is_query=is_query)

        cache_key_text = self._maybe_prefix_query(text, is_query)

        # Try to get from cache
        cached = await self.cache_manager.get_pickle(
            cache_key_text, self.provider, self.model
        )
        if cached is not None:
            logger.debug(f"Embedding cache HIT for text: {text[:50]}...")
            return cached

        # Generate and cache. The underlying LangChain call is sync/blocking;
        # callers run in an async context, so this CPU-or-network blocking is
        # acceptable here (matches the legacy behavior) — the embedding
        # provider call dominates and is already orchestrated via threadpool
        # in multi_query retrieval.
        logger.debug(f"Embedding cache MISS for text: {text[:50]}...")
        embedding = await super().generate_embedding(text, is_query=is_query)
        await self.cache_manager.set_pickle(
            embedding,
            cache_key_text,
            self.provider,
            self.model,
            ttl=settings.cache_embedding_ttl
        )

        return embedding

    async def generate_embeddings(
        self, texts: List[str], is_query: bool = False
    ) -> List[np.ndarray]:
        """Generate embeddings with caching (async to await Redis I/O).

        ``is_query``: when True, the BGE query-side instruction prefix is
        applied to each input text (where applicable) BEFORE embedding and
        BEFORE cache lookup, mirroring the single-call path so query and
        passage caches share no keys.
        """
        if not self.cache_enabled:
            return await super().generate_embeddings(texts, is_query=is_query)

        results = []
        cache_misses = []           # effective (prefixed) texts to embed
        cache_miss_indices = []     # positions in results for each miss

        # Check cache for each text — keyed on the *effective* text so the
        # query-prefixed variant never aliases the raw-passage variant.
        for idx, text in enumerate(texts):
            cache_key_text = self._maybe_prefix_query(text, is_query)
            cached = await self.cache_manager.get_pickle(
                cache_key_text, self.provider, self.model
            )
            if cached is not None:
                results.append(cached)
            else:
                results.append(None)  # Placeholder
                cache_misses.append(cache_key_text)
                cache_miss_indices.append(idx)

        # Generate embeddings for cache misses
        if cache_misses:
            logger.info(f"Embedding cache: {len(texts) - len(cache_misses)}/{len(texts)} hits, generating {len(cache_misses)} new")
            # cache_misses are already prefixed; pass straight to the base
            # batch call (which does not re-prefix).
            new_embeddings = await super().generate_embeddings(cache_misses)

            # Store in cache and update results
            for idx, cache_key_text, embedding in zip(
                cache_miss_indices, cache_misses, new_embeddings
            ):
                await self.cache_manager.set_pickle(
                    embedding,
                    cache_key_text,
                    self.provider,
                    self.model,
                    ttl=settings.cache_embedding_ttl
                )
                results[idx] = embedding
        else:
            logger.info(f"Embedding cache: {len(texts)}/{len(texts)} hits (100% cache hit rate)")

        return results
