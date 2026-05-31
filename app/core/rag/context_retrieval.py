"""
Context Retrieval Module - Deep RAG Pipeline

This module provides a single interface for retrieving Reference Patterns with quality assurance.
It hides the complexity of multi-query retrieval, reranking, confidence scoring, and hallucination guard.
"""
from dataclasses import dataclass
from typing import List, Optional
import logging

from app.core.config import settings
from app.core.rag.multi_query import MultiQueryRetriever
from app.core.rag.reranker import DocumentReranker
from app.core.rag.confidence_scorer import ConfidenceScorer
from app.core.rag.hallucination_guard import HallucinationGuard
from app.models.schemas import ConfidenceMetrics

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """
    Result of Context Retrieval with quality assurance.
    
    This is the public interface - callers only see what they need:
    - Reference patterns to inject into LLM prompts
    - Quality indicators (confidence metrics)
    - Safety signal (whether to refuse generation)
    """
    patterns: List[str]  # Reference patterns content
    confidence: ConfidenceMetrics  # Quality indicators
    guard_triggered: bool  # Whether Hallucination Guard blocked generation
    insufficient_response: Optional[str] = None  # Message when guard triggers


class ContextRetrieval:
    """
    Deep module for Context Retrieval with quality assurance.
    
    Interface (what callers see):
        result = await context_retrieval.retrieve(query, quality_threshold)
        if result.guard_triggered:
            # Refuse generation - insufficient context
        else:
            # Use result.patterns in LLM prompt
    
    Implementation (what callers don't see):
        - Multi-query expansion (LLM vs heuristic decision)
        - Document reranking with diversity
        - Confidence scoring
        - Hallucination Guard threshold enforcement
        
    All RAG complexity is hidden behind this seam.
    """

    def __init__(
        self,
        vector_store,
        llm_client,
        use_multi_query: bool = None,
        use_llm_expansion: bool = None,
        enable_reranking: bool = None,
        enable_hallucination_guard: bool = None,
    ):
        """
        Initialize Context Retrieval module.
        
        Args:
            vector_store: Vector store for similarity search
            llm_client: LLM client for multi-query expansion (if using LLM mode)
            use_multi_query: Whether to use multi-query retrieval (defaults to settings)
            use_llm_expansion: Whether to use LLM for query expansion (defaults to settings)
            enable_reranking: Whether to rerank results (defaults to settings)
            enable_hallucination_guard: Whether to use hallucination guard (defaults to settings)
        """
        self.vector_store = vector_store
        
        # Configuration with sensible defaults from settings
        self.use_multi_query = use_multi_query if use_multi_query is not None else settings.enable_multi_query_retrieval
        self.use_llm_expansion = use_llm_expansion if use_llm_expansion is not None else settings.multi_query_use_llm
        self.enable_reranking = enable_reranking if enable_reranking is not None else settings.enable_reranking
        self.enable_guard = enable_hallucination_guard if enable_hallucination_guard is not None else settings.enable_hallucination_guard
        
        # Initialize RAG components (adapters behind the seam)
        self.multi_query_retriever = MultiQueryRetriever(
            llm_client=llm_client,
            use_llm=self.use_llm_expansion
        )
        self.reranker = DocumentReranker()
        self.confidence_scorer = ConfidenceScorer()
        # Pass the configured threshold to hallucination guard
        self.hallucination_guard = HallucinationGuard(
            vector_store=vector_store,
            min_confidence_threshold=settings.confidence_threshold
        )

    async def retrieve(
        self,
        query: str,
        quality_threshold: float = None
    ) -> RetrievalResult:
        """
        Retrieve Reference Patterns with quality assurance.
        
        This is the deep interface - callers get high leverage:
        - One call to get quality-assured reference patterns
        - Don't need to know about multi-query, reranking, scoring, or guard
        
        Args:
            query: User's system design query
            quality_threshold: Minimum confidence threshold (defaults to settings)
            
        Returns:
            RetrievalResult with patterns and quality indicators
        """
        threshold = quality_threshold if quality_threshold is not None else settings.confidence_threshold
        
        logger.info("Context Retrieval for query: %s", query[:100])
        
        # Step 1: Retrieval (with optional multi-query expansion)
        if self.use_multi_query:
            logger.debug("Using Multi-Query Retrieval")
            results = await self.multi_query_retriever.retrieve_with_multi_query(
                query=query,
                vector_store=self.vector_store,
                num_sub_queries=settings.multi_query_num_sub_queries,
                top_k_per_query=settings.multi_query_top_k_per_query
            )
        else:
            logger.debug("Using Direct Retrieval")
            results = await self.vector_store.search(query, top_k=settings.top_k_retrieval)
        
        # Step 2: Reranking (if enabled)
        if self.enable_reranking:
            reranked_results = await self.reranker.rerank(
                query=query,
                documents=results,
                top_k=5,
                use_diversity=True
            )
        else:
            reranked_results = results[:5]
        
        # Step 3: Confidence Scoring
        confidence_metrics_dict = self.confidence_scorer.calculate_overall_confidence(
            query=query,
            retrieved_docs=reranked_results
        )
        confidence_metrics = ConfidenceMetrics(**confidence_metrics_dict)
        
        logger.info(
            "Confidence: %.3f (%s)",
            confidence_metrics.overall_confidence,
            confidence_metrics.confidence_level
        )
        
        # Step 4: Hallucination Guard
        if self.enable_guard:
            should_proceed, insufficient_msg = await self.hallucination_guard.should_proceed_with_generation(
                query=query,
                retrieved_docs=reranked_results
            )
            
            if not should_proceed:
                logger.warning("⚠️  Hallucination Guard triggered - insufficient context")
                return RetrievalResult(
                    patterns=[],
                    confidence=confidence_metrics,
                    guard_triggered=True,
                    insufficient_response=insufficient_msg
                )
        
        # Success - extract pattern content
        patterns = [doc.content for doc, score in reranked_results]
        
        return RetrievalResult(
            patterns=patterns,
            confidence=confidence_metrics,
            guard_triggered=False
        )
