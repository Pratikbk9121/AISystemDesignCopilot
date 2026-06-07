"""
Qdrant vector store implementation using qdrant-client directly
Supports in-memory, persistent local, and server modes.

Wave 2A: native Qdrant hybrid retrieval. When ``enable_hybrid`` is on
(default ``settings.enable_hybrid_retrieval``), the store maintains both a
named dense vector ("dense") and a sparse BM25 vector ("bm25", with the IDF
modifier required by ``Qdrant/bm25``). Search runs a single
``query_points`` call with two prefetch branches fused via
``FusionQuery(RRF)`` — all library-side, no hand-rolled BM25/RRF.

If ``fastembed`` is not installed, the store logs a warning and degrades
to the original dense-only path so the service still boots.
"""
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from qdrant_client import QdrantClient, models
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.core.config import settings
from app.core.rag.document_processor import Document
from app.core.rag.embeddings import EmbeddingGenerator

logger = logging.getLogger(__name__)


# Sparse encoder used for BM25 — Qdrant's first-party model paired with the
# server-side IDF modifier. We load it lazily so unit tests that mock the
# store don't pay the FastEmbed cold-start cost.
_SPARSE_ENCODER_NAME = "Qdrant/bm25"
# Named vector keys for hybrid mode. Kept as module constants so the upsert
# and query paths cannot drift.
_DENSE_VECTOR_NAME = "dense"
_SPARSE_VECTOR_NAME = "bm25"


def _get_sparse_encoder():
    """Lazy-import + construct the FastEmbed BM25 sparse encoder.

    Importing FastEmbed at module import time would force every test that
    only mocks the store to pay the dependency cost, so we defer until the
    first hybrid-enabled instance is constructed.
    """
    from fastembed import SparseTextEmbedding  # local import on purpose

    return SparseTextEmbedding(_SPARSE_ENCODER_NAME)


class QdrantVectorStore:
    """
    Qdrant vector store for efficient similarity search using qdrant-client directly.
    Supports in-memory, persistent local, and server modes.
    """

    def __init__(
        self,
        embedding_generator: EmbeddingGenerator | None = None,
        collection_name: str | None = None,
        use_memory: bool | None = None,
        qdrant_url: str | None = None,
        enable_hybrid: bool | None = None,
    ):
        """
        Initialize Qdrant vector store

        Args:
            embedding_generator: EmbeddingGenerator instance
            collection_name: Name of the Qdrant collection
            use_memory: If True, use in-memory storage. If False, use persistent storage
            qdrant_url: URL of Qdrant server (if using server mode)
            enable_hybrid: If True, run BM25 sparse + dense retrieval fused with
                RRF (Qdrant-native). Defaults to ``settings.enable_hybrid_retrieval``.
                Falls back to dense-only if fastembed is unavailable.
        """
        self.embedding_generator = embedding_generator or EmbeddingGenerator()
        self.collection_name = collection_name or settings.qdrant_collection_name
        self.embedding_dimension = self.embedding_generator.dimension

        # Resolve hybrid flag (param > settings). The encoder is wired up
        # below; if fastembed is missing we flip this back to False so every
        # downstream branch (collection schema, upsert, search) takes the
        # dense-only path.
        self.enable_hybrid = (
            enable_hybrid if enable_hybrid is not None else settings.enable_hybrid_retrieval
        )
        self._sparse_encoder = None
        if self.enable_hybrid:
            try:
                self._sparse_encoder = _get_sparse_encoder()
                logger.info(
                    "Hybrid retrieval enabled (sparse encoder: %s)", _SPARSE_ENCODER_NAME
                )
            except Exception as e:  # noqa: BLE001 — optional dep, never crash boot.
                logger.warning(
                    "fastembed unavailable (%s); falling back to dense-only retrieval",
                    e,
                )
                self.enable_hybrid = False
                self._sparse_encoder = None

        # Initialize Qdrant client
        use_memory = use_memory if use_memory is not None else settings.qdrant_use_memory

        if use_memory:
            # In-memory mode (for development/testing)
            self.client = QdrantClient(":memory:")
            self.storage_path = None
            self.url = None
            logger.info("Qdrant initialized in-memory mode")
        elif qdrant_url:
            # Server mode (connect to running Qdrant instance)
            self.client = QdrantClient(url=qdrant_url)
            self.storage_path = None
            self.url = qdrant_url
            logger.info("Qdrant connected to server: %s", qdrant_url)
        else:
            # Persistent local storage
            self.storage_path = Path(settings.qdrant_path)
            self.storage_path.mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=str(self.storage_path))
            self.url = None
            logger.info("Qdrant initialized with persistent storage: %s", self.storage_path)

        # Track documents with their IDs
        self.document_id_map: Dict[str, Document] = {}

        # Create/connect to collection
        self._initialize_collection()

    def _initialize_collection(self) -> None:
        """
        Initialize or connect to Qdrant collection.

        In hybrid mode the collection schema is *different* (named dense
        vector + sparse BM25 vector with IDF modifier). This is a breaking
        schema change vs. the dense-only path. When reconnecting to an
        existing collection we inspect its vector schema and either
        auto-clear (in-memory: ephemeral) or raise a clear RuntimeError
        (persistent: operator must run ``initialize_qdrant.py --clear``)
        rather than letting upsert/search blow up at query time on a
        missing named vector.
        """
        try:
            # Check if collection exists
            collections = self.client.get_collections().collections
            collection_exists = any(c.name == self.collection_name for c in collections)

            if not collection_exists:
                if self.enable_hybrid:
                    # Named dense vector + sparse BM25 with IDF modifier.
                    # The IDF modifier is mandatory for the Qdrant/bm25
                    # encoder — without it the server can't apply the IDF
                    # weighting baked into FastEmbed's tokenization.
                    self.client.create_collection(
                        collection_name=self.collection_name,
                        vectors_config={
                            _DENSE_VECTOR_NAME: VectorParams(
                                size=self.embedding_dimension,
                                distance=Distance.COSINE,
                            ),
                        },
                        sparse_vectors_config={
                            _SPARSE_VECTOR_NAME: models.SparseVectorParams(
                                modifier=models.Modifier.IDF,
                            ),
                        },
                    )
                    logger.info(
                        "Created hybrid Qdrant collection: %s (dense=%d + bm25-IDF)",
                        self.collection_name,
                        self.embedding_dimension,
                    )
                else:
                    # Legacy dense-only collection (unnamed vector).
                    self.client.create_collection(
                        collection_name=self.collection_name,
                        vectors_config=VectorParams(
                            size=self.embedding_dimension,
                            distance=Distance.COSINE,
                        ),
                    )
                    logger.info("Created Qdrant collection: %s", self.collection_name)
            else:
                logger.info("Connected to existing Qdrant collection: %s", self.collection_name)
                self._guard_schema_drift()

        except Exception as e:
            logger.error("Error initializing collection: %s", e, exc_info=True)
            raise

    def _guard_schema_drift(self) -> None:
        """
        Compare the existing collection's vector schema against what the
        current ``enable_hybrid`` mode expects and act on mismatch:

        - Hybrid mode expects named vector ``dense`` + sparse vector ``bm25``.
        - Non-hybrid mode expects a single unnamed dense vector (or a
          ``dense`` named vector) and NO sparse vectors.

        On mismatch:
        - In-memory store (``qdrant_use_memory=True``): auto-clear the
          collection. The store is ephemeral so a reseed on next bootstrap
          is the right move.
        - Persistent store: raise ``RuntimeError`` with operator guidance.
          We refuse to silently nuke a disk-backed corpus.

        Any failure to inspect the collection (rare race window where the
        collection vanished between ``get_collections`` and here) is
        downgraded to a warning so the normal init path can continue.
        """
        try:
            info = self.client.get_collection(self.collection_name)
        except Exception as e:  # noqa: BLE001 — best-effort inspection.
            logger.warning(
                "Skipping schema-drift check on collection '%s': %s",
                self.collection_name,
                e,
            )
            return

        vectors_cfg = info.config.params.vectors
        sparse_cfg = info.config.params.sparse_vectors

        # ``vectors_cfg`` is a dict for multi/named-vector collections and
        # a bare ``VectorParams`` for the legacy unnamed-vector case.
        existing_has_named_dense = (
            isinstance(vectors_cfg, dict) and _DENSE_VECTOR_NAME in vectors_cfg
        )
        existing_has_sparse_bm25 = (
            isinstance(sparse_cfg, dict) and _SPARSE_VECTOR_NAME in sparse_cfg
        )
        existing_is_hybrid = existing_has_named_dense and existing_has_sparse_bm25

        if self.enable_hybrid and existing_is_hybrid:
            return
        if not self.enable_hybrid and not existing_has_sparse_bm25:
            # Either an unnamed VectorParams or a named-dense-only layout —
            # both are acceptable for non-hybrid mode (upsert/search both
            # tolerate the named ``dense`` key just fine via dense-only API
            # paths… but to keep it strict we only accept *unnamed* dense
            # vectors when hybrid is off, since hybrid-off code paths
            # always emit a bare ``embedding.tolist()`` for upsert).
            if not isinstance(vectors_cfg, dict):
                return
            # Named-vector layout but no sparse — still a mismatch because
            # the upsert path will pass an unnamed vector to a named
            # collection. Fall through to drift handling.

        # Mismatch — describe both sides for the error/warning message.
        mode_want = "hybrid (dense + bm25)" if self.enable_hybrid else "dense-only (unnamed)"
        mode_have_parts = []
        if isinstance(vectors_cfg, dict):
            mode_have_parts.append("named=" + ",".join(sorted(vectors_cfg.keys())))
        else:
            mode_have_parts.append("unnamed-dense")
        if isinstance(sparse_cfg, dict) and sparse_cfg:
            mode_have_parts.append("sparse=" + ",".join(sorted(sparse_cfg.keys())))
        mode_have = " + ".join(mode_have_parts)

        msg = (
            f"Qdrant collection '{self.collection_name}' schema mismatch: "
            f"expected {mode_want}, found {mode_have}."
        )

        if settings.qdrant_use_memory:
            logger.warning("%s Auto-clearing in-memory collection.", msg)
            self.client.delete_collection(collection_name=self.collection_name)
            self.document_id_map.clear()
            # Re-create with the now-correct schema. Recurse into the same
            # init path so creation logic stays single-sourced.
            self._initialize_collection()
            return

        raise RuntimeError(
            f"{msg} Persistent storage cannot be auto-cleared. "
            "Run `python scripts/initialize_qdrant.py --clear` once to reseed "
            "the corpus under the new schema, then restart the service."
        )

    async def add_documents(
        self,
        documents: List[Document],
        ids: Optional[List[str]] = None,
    ) -> None:
        """
        Add documents to the Qdrant collection.

        Async because ``embedding_generator.generate_embeddings`` is async
        (touches the Redis-backed embedding cache).

        Args:
            documents: List of Document objects to add
            ids: Optional list of point IDs (one per document). When provided,
                upserts use these IDs — pass deterministic IDs (e.g. uuid5 over
                source+chunk_index) to make the seed idempotent. When None, a
                fresh uuid4 is generated per document (legacy behavior).
        """
        if not documents:
            return

        if ids is not None and len(ids) != len(documents):
            raise ValueError(
                f"ids length ({len(ids)}) must match documents length ({len(documents)})"
            )

        # Batch-embed all document contents in a single call to avoid N+1
        # round-trips to the embedding provider. Dense embeddings use the
        # passage form (no BGE query prefix) for both modes.
        texts = [doc.content for doc in documents]
        embeddings = await self.embedding_generator.generate_embeddings(texts)

        # Compute sparse embeddings up-front in a single FastEmbed batch when
        # hybrid is on. ``embed`` returns a generator — materialise it once
        # to keep the zip below straightforward.
        sparse_embeddings: List[Any] = []
        if self.enable_hybrid and self._sparse_encoder is not None:
            sparse_embeddings = list(self._sparse_encoder.embed(texts))

        # Prepare points for batch upload
        points = []
        for i, (doc, embedding) in enumerate(zip(documents, embeddings)):
            # Use caller-provided ID when present; otherwise generate uuid4.
            point_id = ids[i] if ids is not None else str(uuid.uuid4())

            # Prepare payload with document content and metadata
            payload = {
                "content": doc.content,
                "metadata": doc.metadata or {},
            }

            if self.enable_hybrid and self._sparse_encoder is not None:
                # Named-vector dict payload: must match the collection schema
                # keys exactly (``dense`` + ``bm25``).
                sparse_emb = sparse_embeddings[i]
                sparse_vec = models.SparseVector(
                    indices=sparse_emb.indices.tolist(),
                    values=sparse_emb.values.tolist(),
                )
                vector_payload = {
                    _DENSE_VECTOR_NAME: embedding.tolist(),
                    _SPARSE_VECTOR_NAME: sparse_vec,
                }
            else:
                # Legacy single unnamed vector.
                vector_payload = embedding.tolist()

            point = PointStruct(
                id=point_id,
                vector=vector_payload,
                payload=payload,
            )
            points.append(point)

            # Track document by ID
            self.document_id_map[point_id] = doc

        # Batch upsert to Qdrant
        self.client.upsert(
            collection_name=self.collection_name,
            points=points,
        )

        logger.info("Added %d documents to Qdrant collection '%s'", len(documents), self.collection_name)

    async def search(
        self,
        query: str,
        top_k: int | None = None,
        filter_metadata: Dict[str, Any] | None = None,
    ) -> List[Tuple[Document, float]]:
        """
        Search for similar documents using Qdrant.

        Async because ``embedding_generator.generate_embedding`` is async
        (touches the Redis-backed embedding cache).

        Args:
            query: Search query text
            top_k: Number of results to return
            filter_metadata: Optional metadata filters

        Returns:
            List of tuples (Document, similarity_score). In hybrid mode the
            score is the RRF-fused score returned by Qdrant; in dense-only
            mode it's the cosine similarity (unchanged from Wave 1).
        """
        top_k = top_k or settings.top_k_retrieval

        # Generate embedding for query. is_query=True activates the BGE
        # instruction prefix on BGE+HuggingFace stacks (no-op on others), so
        # the query lives in the same semantic region as indexed passages.
        query_embedding = await self.embedding_generator.generate_embedding(
            query, is_query=True
        )

        # Build filter if metadata is provided
        query_filter = None
        if filter_metadata:
            conditions = []
            for key, value in filter_metadata.items():
                conditions.append(
                    FieldCondition(
                        key=f"metadata.{key}",
                        match=MatchValue(value=value),
                    )
                )
            if conditions:
                query_filter = Filter(must=conditions)

        def _run_query():
            if self.enable_hybrid and self._sparse_encoder is not None:
                # Build BM25 sparse query via FastEmbed's query_embed (which
                # applies the query-side tokenization variant — *not* the
                # same as the passage embed call).
                sparse_emb = list(self._sparse_encoder.query_embed([query]))[0]
                sparse_q = models.SparseVector(
                    indices=sparse_emb.indices.tolist(),
                    values=sparse_emb.values.tolist(),
                )
                # Over-fetch each branch (top_k * 2) so RRF has enough
                # signal to fuse meaningfully before truncation.
                prefetch = [
                    models.Prefetch(
                        query=query_embedding.tolist(),
                        using=_DENSE_VECTOR_NAME,
                        limit=top_k * 2,
                        filter=query_filter,
                    ),
                    models.Prefetch(
                        query=sparse_q,
                        using=_SPARSE_VECTOR_NAME,
                        limit=top_k * 2,
                        filter=query_filter,
                    ),
                ]
                return self.client.query_points(
                    collection_name=self.collection_name,
                    prefetch=prefetch,
                    query=models.FusionQuery(fusion=models.Fusion.RRF),
                    limit=top_k,
                    with_payload=True,
                    query_filter=query_filter,
                )
            # Dense-only backstop — unchanged behaviour from Wave 1.
            return self.client.query_points(
                collection_name=self.collection_name,
                query=query_embedding.tolist(),
                limit=top_k,
                query_filter=query_filter,
            )

        # Time the actual query via a fresh Prometheus Timer each call.
        # prometheus_client's Timer is single-use — calling ``.time()`` and
        # re-entering it on the next search would silently drop the
        # observation (or raise), so we acquire the context manager inline.
        try:
            from app.middleware.metrics import QDRANT_QUERY

            with QDRANT_QUERY.time():
                query_response = _run_query()
        except ImportError:
            query_response = _run_query()

        # Convert results to Document format
        results = []
        for scored_point in query_response.points:
            # Retrieve document from map or reconstruct from payload
            doc = self.document_id_map.get(scored_point.id)

            if doc is None:
                # Reconstruct document from payload
                payload = scored_point.payload
                doc = Document(
                    content=payload.get("content", ""),
                    metadata=payload.get("metadata", {}),
                )

            # Qdrant with cosine returns similarity score (higher is better).
            # In hybrid mode this is the RRF-fused score.
            results.append((doc, scored_point.score))

        return results

    def delete_collection(self) -> None:
        """
        Delete the entire collection (use with caution!)
        """
        self.client.delete_collection(collection_name=self.collection_name)
        self.document_id_map.clear()
        logger.info("Deleted Qdrant collection: %s", self.collection_name)

    def get_collection_info(self) -> Dict[str, Any]:
        """
        Get information about the collection

        Returns:
            Dictionary with collection stats
        """
        info = self.client.get_collection(collection_name=self.collection_name)
        return {
            "collection_name": self.collection_name,
            "indexed_vectors_count": info.indexed_vectors_count,
            "points_count": info.points_count,
            "segments_count": info.segments_count,
            "status": str(info.status),
            "hybrid": self.enable_hybrid,
        }

    def clear_collection(self) -> None:
        """
        Remove all documents from the collection but keep the collection
        """
        # Delete and recreate collection
        self.client.delete_collection(collection_name=self.collection_name)
        self.document_id_map.clear()
        self._initialize_collection()
        logger.info("Cleared all documents from collection: %s", self.collection_name)

    def close(self) -> None:
        """
        Release the underlying Qdrant client.

        Qdrant local-mode (persistent path) acquires a file lock; if we exit
        without closing, a subsequent restart can hit a "storage already
        accessed" error. Wrapped in try/except so shutdown never raises.
        """
        try:
            self.client.close()
            logger.info("Qdrant client closed for collection: %s", self.collection_name)
        except Exception as e:  # noqa: BLE001 — shutdown path, swallow.
            logger.warning("Error closing Qdrant client: %s", e, exc_info=True)
