"""
Document Re-ranking for improved retrieval quality.

Wave 2B overhaul — replaces the legacy keyword/length heuristic with a
sentence-transformers ``CrossEncoder`` (default ``BAAI/bge-reranker-v2-m3``).
Cross-encoders score the (query, passage) pair jointly and consistently
outperform bi-encoder cosine similarity on relevance ranking.

The heuristic ``calculate_relevance_score`` is preserved so callers that
relied on it (and the existing unit tests) keep working. It is now used
only as the legacy/fallback path when ``settings.enable_cross_encoder_rerank``
is False or the cross-encoder model can't be loaded.

Diversity / MMR is applied AFTER cross-encoder scoring — cross-encoder
gives relevance, the diversity pass reduces redundancy on top.
"""
import logging
import math
from typing import Dict, List, Optional, Tuple

import numpy as np

from app.core.config import settings
from app.core.rag.document_processor import Document
from app.core.rag.embeddings import EmbeddingGenerator

logger = logging.getLogger(__name__)

try:  # Imported lazily-friendly: import error is non-fatal, fallback is used.
    from sentence_transformers import CrossEncoder  # type: ignore
except Exception as exc:  # pragma: no cover - environment-specific
    CrossEncoder = None  # type: ignore
    logger.warning(
        "sentence-transformers.CrossEncoder unavailable (%s); reranker will fall "
        "back to the legacy heuristic path.",
        exc,
    )


class DocumentReranker:
    """
    Cross-encoder backed re-ranker with diversity-aware MMR pass.

    Strategy:
    1. Score each (query, document) pair with ``CrossEncoder.predict``.
    2. Sort by score descending.
    3. Optionally apply a diversity penalty so the top-k aren't redundant.

    The CrossEncoder is cached on the class so multiple ``DocumentReranker``
    instances in the same process share the (~580MB) model weights.
    """

    # Class-level cache: model_name -> CrossEncoder instance.
    # Multiple DocumentReranker() instances share one loaded model.
    _cross_encoder_cache: Dict[str, "CrossEncoder"] = {}

    def __init__(self, embedding_generator: Optional[EmbeddingGenerator] = None):
        """
        Initialize reranker.

        Args:
            embedding_generator: Embedding generator used by the diversity
                pass to detect redundant documents.
        """
        self.embedding_generator = embedding_generator or EmbeddingGenerator()

    # ------------------------------------------------------------------
    # CrossEncoder management
    # ------------------------------------------------------------------
    @classmethod
    def _get_encoder(cls, model_name: str) -> Optional["CrossEncoder"]:
        """
        Lazy, cached CrossEncoder loader.

        Returns ``None`` when the underlying library is missing or the model
        can't be loaded (offline, disk full, network blocked). Callers should
        fall back to the heuristic path on ``None``.
        """
        if CrossEncoder is None:
            return None
        cached = cls._cross_encoder_cache.get(model_name)
        if cached is not None:
            return cached
        try:
            logger.info("Loading CrossEncoder model: %s", model_name)
            encoder = CrossEncoder(model_name, max_length=512)
            cls._cross_encoder_cache[model_name] = encoder
            logger.info("CrossEncoder loaded: %s", model_name)
            return encoder
        except Exception as exc:  # pragma: no cover - load-time/IO failure
            logger.warning(
                "Failed to load CrossEncoder '%s' (%s); falling back to "
                "heuristic rerank.",
                model_name,
                exc,
            )
            return None

    # ------------------------------------------------------------------
    # Diversity penalty (MMR-style)
    # ------------------------------------------------------------------
    def calculate_diversity_penalty(
        self,
        doc_embedding: np.ndarray,
        selected_embeddings: List[np.ndarray],
        penalty_weight: float = 0.3
    ) -> float:
        """Penalize documents too similar to already-selected ones."""
        if not selected_embeddings:
            return 0.0

        similarities = []
        for selected_emb in selected_embeddings:
            similarity = np.dot(doc_embedding, selected_emb) / (
                np.linalg.norm(doc_embedding) * np.linalg.norm(selected_emb)
            )
            similarities.append(similarity)

        max_similarity = max(similarities)
        return penalty_weight * max_similarity

    # ------------------------------------------------------------------
    # Legacy heuristic (kept for the fallback path and existing unit tests)
    # ------------------------------------------------------------------
    def calculate_relevance_score(
        self,
        query: str,
        doc: Document,
        initial_score: float
    ) -> float:
        """
        Legacy heuristic relevance score. Used only when the cross-encoder
        path is disabled or unavailable. Kept stable for unit tests.
        """
        score = initial_score
        metadata = doc.metadata

        if metadata.get("source", "").endswith(".md"):
            score *= 1.1

        query_lower = query.lower()
        content_lower = doc.content.lower()

        important_keywords = [
            "scalability", "database", "api", "microservices",
            "caching", "load balancing", "consistency", "availability",
        ]
        keyword_matches = sum(
            1
            for kw in important_keywords
            if kw in query_lower and kw in content_lower
        )
        score += keyword_matches * 0.05

        doc_length = len(doc.content)
        if doc_length < 100:
            score *= 0.8
        elif doc_length > 5000:
            score *= 0.9

        return score

    # ------------------------------------------------------------------
    # Public API for confidence_scorer
    # ------------------------------------------------------------------
    def score_pairs(
        self,
        query: str,
        contents: List[str],
        model_name: Optional[str] = None,
    ) -> List[float]:
        """
        Raw cross-encoder scores for (query, content) pairs.

        Used by ``ConfidenceScorer`` so the semantic-coverage signal can
        consume the cross-encoder's relevance estimate directly. Returns an
        empty list if the cross-encoder isn't available — callers should
        handle that by reverting to the bi-encoder similarity signal.
        """
        if not contents:
            return []
        encoder = self._get_encoder(model_name or settings.reranker_model)
        if encoder is None:
            return []
        pairs = [(query, content) for content in contents]
        try:
            raw_scores = encoder.predict(pairs, show_progress_bar=False)
        except Exception as exc:  # pragma: no cover - inference-time failure
            logger.warning(
                "CrossEncoder.predict failed (%s); returning empty scores.",
                exc,
            )
            return []
        return [float(s) for s in raw_scores]

    # ------------------------------------------------------------------
    # Main rerank entry point
    # ------------------------------------------------------------------
    async def rerank(
        self,
        query: str,
        documents: List[Tuple[Document, float]],
        top_k: Optional[int] = None,
        use_diversity: bool = True,
    ) -> List[Tuple[Document, float]]:
        """
        Re-rank documents.

        When ``settings.enable_cross_encoder_rerank`` is True (default) and the
        model loads, scores are produced by the cross-encoder. Otherwise the
        legacy heuristic is used. In both modes an optional diversity pass
        de-duplicates the result set.

        Args:
            query: Original user query.
            documents: List of ``(Document, initial_score)`` from retrieval.
            top_k: Number of top documents to return (``None`` = all).
            use_diversity: Apply MMR-style diversity penalty after scoring.

        Returns:
            Re-ranked list of ``(Document, new_score)`` pairs sorted by score
            descending. When the cross-encoder runs, ``new_score`` is the
            cross-encoder relevance score (raw, may be negative).
        """
        if not documents:
            return []

        logger.info("Re-ranking %d documents...", len(documents))

        encoder: Optional["CrossEncoder"] = None
        if settings.enable_cross_encoder_rerank:
            encoder = self._get_encoder(settings.reranker_model)

        if encoder is not None:
            # Cross-encoder path
            pairs = [(query, doc.content) for doc, _ in documents]
            try:
                scores = encoder.predict(pairs, show_progress_bar=False)
            except Exception as exc:  # pragma: no cover - runtime failure
                logger.warning(
                    "CrossEncoder.predict failed (%s); falling back to "
                    "heuristic rerank.",
                    exc,
                )
                scores = None
            if scores is not None:
                scored_docs = [
                    (doc, float(score))
                    for (doc, _initial), score in zip(documents, scores)
                ]
            else:
                scored_docs = [
                    (doc, self.calculate_relevance_score(query, doc, initial))
                    for doc, initial in documents
                ]
        else:
            # Fallback heuristic path (disabled flag, missing lib, or load failure)
            scored_docs = [
                (doc, self.calculate_relevance_score(query, doc, initial))
                for doc, initial in documents
            ]

        # Sort by relevance
        scored_docs.sort(key=lambda x: x[1], reverse=True)

        # Diversity / MMR pass — applied AFTER cross-encoder scoring
        if use_diversity and len(scored_docs) > 1:
            doc_texts = [doc.content for doc, _ in scored_docs]
            try:
                doc_embeddings = await self.embedding_generator.generate_embeddings(
                    doc_texts
                )
            except Exception as exc:  # pragma: no cover - embedding failure
                logger.warning(
                    "Diversity embedding generation failed (%s); skipping "
                    "diversity pass.",
                    exc,
                )
                doc_embeddings = None

            if doc_embeddings is not None:
                final_docs: List[Tuple[Document, float]] = []
                selected_embeddings: List[np.ndarray] = []
                for (doc, score), doc_embedding in zip(scored_docs, doc_embeddings):
                    diversity_penalty = self.calculate_diversity_penalty(
                        doc_embedding,
                        selected_embeddings,
                        penalty_weight=0.3,
                    )
                    final_docs.append((doc, score - diversity_penalty))
                    selected_embeddings.append(doc_embedding)
                final_docs.sort(key=lambda x: x[1], reverse=True)
            else:
                final_docs = scored_docs
        else:
            final_docs = scored_docs

        result = final_docs[:top_k] if top_k else final_docs

        if result:
            logger.info("Re-ranking complete - Top score: %.4f", result[0][1])

        return result
