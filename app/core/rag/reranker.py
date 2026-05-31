"""
Document Re-ranking for improved retrieval quality
Uses semantic similarity and relevance scoring to reorder retrieved documents
"""
import logging
from typing import List, Optional, Tuple

import numpy as np

from app.core.rag.document_processor import Document
from app.core.rag.embeddings import EmbeddingGenerator

logger = logging.getLogger(__name__)


class DocumentReranker:
    """
    Re-ranks retrieved documents to improve relevance.
    Combines multiple scoring strategies:
    1. Cosine similarity (from initial retrieval)
    2. Query-document relevance scoring
    3. Document diversity (avoiding redundant content)
    """

    def __init__(self, embedding_generator: Optional[EmbeddingGenerator] = None):
        """
        Initialize reranker
        
        Args:
            embedding_generator: Embedding generator for semantic scoring
        """
        self.embedding_generator = embedding_generator or EmbeddingGenerator()
    
    def calculate_diversity_penalty(
        self,
        doc_embedding: np.ndarray,
        selected_embeddings: List[np.ndarray],
        penalty_weight: float = 0.3
    ) -> float:
        """
        Calculate penalty for documents too similar to already selected ones
        
        Args:
            doc_embedding: Embedding of candidate document
            selected_embeddings: Embeddings of already selected documents
            penalty_weight: Weight for diversity penalty (0-1)
        
        Returns:
            Diversity penalty score (higher = more redundant)
        """
        if not selected_embeddings:
            return 0.0
        
        # Calculate max similarity with already selected docs
        similarities = []
        for selected_emb in selected_embeddings:
            # Cosine similarity
            similarity = np.dot(doc_embedding, selected_emb) / (
                np.linalg.norm(doc_embedding) * np.linalg.norm(selected_emb)
            )
            similarities.append(similarity)
        
        max_similarity = max(similarities)
        return penalty_weight * max_similarity
    
    def calculate_relevance_score(
        self,
        query: str,
        doc: Document,
        initial_score: float
    ) -> float:
        """
        Calculate enhanced relevance score combining multiple signals
        
        Args:
            query: Original user query
            doc: Document to score
            initial_score: Initial similarity score from vector search
        
        Returns:
            Enhanced relevance score
        """
        # Start with initial score
        score = initial_score
        
        # Boost score based on metadata
        metadata = doc.metadata
        
        # Boost for important document types
        if metadata.get("source", "").endswith(".md"):
            score *= 1.1  # Markdown docs typically more comprehensive
        
        # Boost for certain topics (can be customized)
        query_lower = query.lower()
        content_lower = doc.content.lower()
        
        # Check for exact keyword matches
        important_keywords = ["scalability", "database", "api", "microservices", 
                              "caching", "load balancing", "consistency", "availability"]
        
        keyword_matches = sum(1 for kw in important_keywords if kw in query_lower and kw in content_lower)
        score += keyword_matches * 0.05  # Small boost per matching keyword
        
        # Penalize very short or very long documents
        doc_length = len(doc.content)
        if doc_length < 100:
            score *= 0.8  # Too short, likely not comprehensive
        elif doc_length > 5000:
            score *= 0.9  # Very long, might be too detailed
        
        return score
    
    async def rerank(
        self,
        query: str,
        documents: List[Tuple[Document, float]],
        top_k: Optional[int] = None,
        use_diversity: bool = True
    ) -> List[Tuple[Document, float]]:
        """
        Re-rank documents using enhanced relevance scoring.

        Async because ``embedding_generator.generate_embeddings`` is async.

        Args:
            query: Original user query
            documents: List of (Document, initial_score) tuples
            top_k: Number of top documents to return (None = all)
            use_diversity: Whether to apply diversity penalty

        Returns:
            Re-ranked list of (Document, new_score) tuples
        """
        if not documents:
            return []

        logger.info("Re-ranking %d documents...", len(documents))

        # Calculate enhanced relevance scores
        scored_docs = []
        for doc, initial_score in documents:
            relevance_score = self.calculate_relevance_score(query, doc, initial_score)
            scored_docs.append((doc, relevance_score))

        # Apply diversity if requested
        if use_diversity:
            final_docs = []
            selected_embeddings = []

            # Sort by relevance first
            scored_docs.sort(key=lambda x: x[1], reverse=True)

            # Batch-embed all candidate documents up-front in a single call to
            # avoid N+1 embedding round-trips inside the diversity loop.
            doc_texts = [doc.content for doc, _ in scored_docs]
            doc_embeddings = await self.embedding_generator.generate_embeddings(doc_texts)

            for (doc, score), doc_embedding in zip(scored_docs, doc_embeddings):
                # Calculate diversity penalty using pre-computed embedding
                diversity_penalty = self.calculate_diversity_penalty(
                    doc_embedding,
                    selected_embeddings,
                    penalty_weight=0.3
                )

                # Apply penalty
                final_score = score - diversity_penalty
                final_docs.append((doc, final_score))
                selected_embeddings.append(doc_embedding)

            # Re-sort after applying diversity
            final_docs.sort(key=lambda x: x[1], reverse=True)
        else:
            final_docs = scored_docs
            final_docs.sort(key=lambda x: x[1], reverse=True)
        
        # Return top-k
        result = final_docs[:top_k] if top_k else final_docs

        logger.info("Re-ranking complete - Top score: %.4f", result[0][1])

        return result
