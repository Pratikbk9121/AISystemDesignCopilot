"""
Confidence Scoring for RAG responses
Evaluates the quality of retrieved context and response reliability
"""
from typing import List, Tuple, Dict, Any
import numpy as np
from app.core.rag.document_processor import Document


class ConfidenceScorer:
    """
    Calculates confidence scores for RAG responses based on:
    1. Retrieval quality (similarity scores)
    2. Context coverage
    3. Query complexity
    4. Document coherence
    """
    
    def __init__(self):
        """Initialize confidence scorer"""
        pass
    
    def calculate_retrieval_confidence(
        self,
        retrieved_docs: List[Tuple[Document, float]],
        min_score_threshold: float = 0.5
    ) -> float:
        """
        Calculate confidence based on retrieval quality
        
        Args:
            retrieved_docs: List of (Document, similarity_score) tuples
            min_score_threshold: Minimum acceptable similarity score
        
        Returns:
            Confidence score (0.0 - 1.0)
        """
        if not retrieved_docs:
            return 0.0
        
        scores = [score for _, score in retrieved_docs]
        
        # Calculate average score
        avg_score = np.mean(scores)
        
        # Calculate score distribution (consistency)
        score_std = np.std(scores) if len(scores) > 1 else 0.0
        
        # High average + low std deviation = high confidence
        # Low std means consistent retrieval quality
        consistency_bonus = max(0, 1.0 - score_std)
        
        # Penalize if top score is below threshold
        top_score = max(scores)
        threshold_penalty = 0.0
        if top_score < min_score_threshold:
            threshold_penalty = 0.3
        
        # Calculate final confidence
        confidence = (avg_score * 0.6 + consistency_bonus * 0.4) - threshold_penalty
        
        return max(0.0, min(1.0, confidence))
    
    def calculate_coverage_confidence(
        self,
        query: str,
        retrieved_docs: List[Tuple[Document, float]]
    ) -> float:
        """
        Calculate confidence based on context coverage of the query
        
        Args:
            query: User query
            retrieved_docs: Retrieved documents
        
        Returns:
            Coverage confidence score (0.0 - 1.0)
        """
        if not retrieved_docs:
            return 0.0
        
        # Extract important keywords from query
        query_words = set(query.lower().split())
        
        # Remove common stop words
        stop_words = {"the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or", "but", "is", "are", "was", "were"}
        query_keywords = query_words - stop_words
        
        if not query_keywords:
            return 0.5  # Neutral if no meaningful keywords
        
        # Check how many keywords are covered in retrieved docs
        all_doc_content = " ".join([doc.content.lower() for doc, _ in retrieved_docs])
        covered_keywords = sum(1 for kw in query_keywords if kw in all_doc_content)
        
        coverage_ratio = covered_keywords / len(query_keywords)
        
        # Boost if we have multiple documents covering the topic
        num_docs_bonus = min(0.2, len(retrieved_docs) * 0.04)  # Max 0.2 bonus
        
        confidence = min(1.0, coverage_ratio + num_docs_bonus)
        
        return confidence
    
    def calculate_overall_confidence(
        self,
        query: str,
        retrieved_docs: List[Tuple[Document, float]],
        response_content: str = ""
    ) -> Dict[str, Any]:
        """
        Calculate overall confidence score with detailed breakdown
        
        Args:
            query: User query
            retrieved_docs: Retrieved documents with scores
            response_content: Generated response (optional)
        
        Returns:
            Dictionary with confidence scores and metadata
        """
        # Calculate component scores
        retrieval_confidence = self.calculate_retrieval_confidence(retrieved_docs)
        coverage_confidence = self.calculate_coverage_confidence(query, retrieved_docs)
        
        # Calculate overall confidence (weighted average)
        overall_confidence = (
            retrieval_confidence * 0.6 +
            coverage_confidence * 0.4
        )
        
        # Determine confidence level
        if overall_confidence >= 0.8:
            confidence_level = "HIGH"
            recommendation = "Response is well-supported by retrieved context"
        elif overall_confidence >= 0.6:
            confidence_level = "MEDIUM"
            recommendation = "Response is reasonably supported, but context could be better"
        elif overall_confidence >= 0.4:
            confidence_level = "LOW"
            recommendation = "Limited context available, response may be incomplete"
        else:
            confidence_level = "VERY_LOW"
            recommendation = "Insufficient context - consider adding more knowledge sources"
        
        return {
            "overall_confidence": round(overall_confidence, 3),
            "confidence_level": confidence_level,
            "retrieval_confidence": round(retrieval_confidence, 3),
            "coverage_confidence": round(coverage_confidence, 3),
            "num_docs_retrieved": len(retrieved_docs),
            "avg_similarity_score": round(np.mean([s for _, s in retrieved_docs]), 3) if retrieved_docs else 0.0,
            "recommendation": recommendation
        }
