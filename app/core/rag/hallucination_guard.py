"""
Hallucination Guard for RAG responses
Validates if retrieved context is sufficient before generating responses
"""
from typing import List, Literal, Tuple, Dict, Any, Optional
from app.core.rag.document_processor import Document
from app.core.rag.confidence_scorer import ConfidenceScorer
from app.core.knowledge_analyzer import KnowledgeAnalyzer


GuardStatus = Literal["proceed", "degraded", "refuse"]


class HallucinationGuard:
    """
    Guards against hallucinations by validating context quality
    before allowing LLM generation to proceed.
    
    If context is insufficient, returns "Not enough data" instead of
    allowing the LLM to potentially hallucinate.
    """
    
    def __init__(
        self,
        min_confidence_threshold: float = 0.3,
        min_documents: int = 1,
        min_similarity_threshold: float = 0.4,
        degrade_lower_bound: float = 0.3,
        vector_store=None
    ):
        """
        Initialize hallucination guard

        Args:
            min_confidence_threshold: Minimum confidence score to proceed (above this → "proceed")
            min_documents: Minimum number of documents required
            min_similarity_threshold: Minimum similarity score for top document
            degrade_lower_bound: Floor for degraded mode. Between this and
                min_confidence_threshold we still generate but mark the
                response as extrapolated (Perplexity-style "best effort"
                UX). Below this we hard-refuse.
            vector_store: Optional vector store for suggesting similar topics
        """
        self.min_confidence_threshold = min_confidence_threshold
        self.min_documents = min_documents
        self.min_similarity_threshold = min_similarity_threshold
        self.degrade_lower_bound = degrade_lower_bound
        self.confidence_scorer = ConfidenceScorer()
        self.knowledge_analyzer = KnowledgeAnalyzer(vector_store=vector_store) if vector_store else None
    
    def check_context_sufficiency(
        self,
        query: str,
        retrieved_docs: List[Tuple[Document, float]]
    ) -> Dict[str, Any]:
        """
        Check if retrieved context is sufficient for generation
        
        Args:
            query: User query
            retrieved_docs: Retrieved documents with similarity scores
        
        Returns:
            Dictionary with validation results:
            - is_sufficient: bool
            - reason: str (explanation)
            - confidence_details: dict
        """
        # Check 1: Minimum number of documents
        if len(retrieved_docs) < self.min_documents:
            return {
                "is_sufficient": False,
                "reason": f"Insufficient documents retrieved. Found {len(retrieved_docs)}, need at least {self.min_documents}",
                "suggestion": "Try adding more knowledge sources or rephrasing your query",
                "confidence_details": None
            }
        
        # Check 2: Top document similarity threshold
        if retrieved_docs:
            top_score = max(score for _, score in retrieved_docs)
            if top_score < self.min_similarity_threshold:
                return {
                    "is_sufficient": False,
                    "reason": f"Low relevance of retrieved documents. Best match score: {top_score:.3f}, threshold: {self.min_similarity_threshold}",
                    "suggestion": "The available knowledge base may not contain relevant information for this query",
                    "confidence_details": None
                }
        
        # Check 3: Overall confidence score
        confidence_details = self.confidence_scorer.calculate_overall_confidence(
            query=query,
            retrieved_docs=retrieved_docs
        )
        
        if confidence_details["overall_confidence"] < self.min_confidence_threshold:
            return {
                "is_sufficient": False,
                "reason": f"Low confidence in context quality. Confidence: {confidence_details['overall_confidence']:.3f}, threshold: {self.min_confidence_threshold}",
                "suggestion": confidence_details["recommendation"],
                "confidence_details": confidence_details
            }
        
        # All checks passed
        return {
            "is_sufficient": True,
            "reason": "Context quality is sufficient for generation",
            "suggestion": None,
            "confidence_details": confidence_details
        }
    
    async def create_insufficient_context_response(
        self,
        query: str,
        validation_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a response for when context is insufficient

        Args:
            query: User query
            validation_result: Result from check_context_sufficiency

        Returns:
            Formatted response dict
        """
        # Get available topics and suggestions
        available_topics = []
        similar_topics = []
        example_queries = []

        if self.knowledge_analyzer:
            try:
                topics_info = self.knowledge_analyzer.get_available_topics()
                available_topics = [t["name"] for t in topics_info.get("topics", [])[:5]]
                example_queries = topics_info.get("example_queries", [])[:3]
                similar_topics = await self.knowledge_analyzer.suggest_similar_topics(query, top_k=3)
            except Exception as e:
                # Fallback if analyzer fails
                pass

        # Build explanation with rich context
        explanation_parts = [
            "# ❌ Insufficient Knowledge\n",
            f"I don't have sufficient context in my knowledge base to provide a reliable system design for: **\"{query}\"**\n",
            "\n## 🔍 Why This Happened\n",
            f"**{validation_result['reason']}**\n",
        ]

        # Add similar topics if found
        if similar_topics:
            explanation_parts.append("\n## 🎯 You Might Be Looking For\n")
            explanation_parts.append("Based on your query, these related topics ARE available:\n")
            for topic in similar_topics:
                explanation_parts.append(f"- **{topic}**\n")

        # Add available topics
        if available_topics:
            explanation_parts.append("\n## 📚 Currently Available Topics\n")
            explanation_parts.append("The knowledge base currently covers:\n")
            for topic in available_topics:
                explanation_parts.append(f"- {topic}\n")

        # Add example queries
        if example_queries:
            explanation_parts.append("\n## ✅ Example Queries That Work\n")
            for example in example_queries:
                explanation_parts.append(f"- \"{example}\"\n")

        # Add actionable steps
        explanation_parts.extend([
            "\n## 💡 What You Can Do\n",
            "1. **Try a related query** from the available topics above\n",
            "2. **Check all topics** via: `GET /api/v1/system-design/knowledge/topics`\n",
            "3. **Rephrase with different keywords** (e.g., use specific tech names)\n",
            "4. **Expand the knowledge base** by adding docs to `data/system_design_docs/` and running `python scripts/initialize_qdrant.py --clear`\n",
            "\n## 📖 Suggestion\n",
            f"{validation_result.get('suggestion', 'Try a different query or add relevant documentation.')}\n",
            "\n---\n",
            "*This safeguard prevents hallucinated or unreliable system design advice. ",
            "I prefer to say \"I don't know\" rather than provide potentially incorrect architecture guidance.*"
        ])

        explanation = "".join(explanation_parts)

        return {
            "message": "Not enough data",
            "explanation": explanation,
            "query": query,
            "validation_details": validation_result,
            "available_topics": available_topics,
            "similar_topics": similar_topics,
            "example_queries": example_queries,
        }
    
    async def should_proceed_with_generation(
        self,
        query: str,
        retrieved_docs: List[Tuple[Document, float]],
        force_generation: bool = False
    ) -> Tuple[GuardStatus, Optional[Dict[str, Any]], List[str]]:
        """
        Determine guard status: proceed, degraded, or refuse.

        Status semantics:
            - "proceed":  Confidence >= min_confidence_threshold. Generate normally.
            - "degraded": Hard structural checks pass (min_documents,
                          min_similarity_threshold) but overall confidence
                          is in [degrade_lower_bound, min_confidence_threshold).
                          Still generate, but caller should label the
                          response as extrapolated from related patterns.
            - "refuse":   Hard checks fail OR confidence < degrade_lower_bound.
                          Do not generate; return insufficient-context response.

        Args:
            query: User query
            retrieved_docs: Retrieved documents
            force_generation: If True, bypass checks (for testing/debugging)

        Returns:
            Tuple of (status, context_dict, related_topics)
            - status="proceed":  context_dict is None, related_topics is []
            - status="degraded": context_dict is None, related_topics is the
                                 list of suggested similar topic names
            - status="refuse":   context_dict carries the insufficient-context
                                 response payload, related_topics is []
        """
        if force_generation:
            return "proceed", None, []

        validation_result = self.check_context_sufficiency(query, retrieved_docs)

        if validation_result["is_sufficient"]:
            return "proceed", None, []

        # Insufficient. Decide: degrade (soft) vs refuse (hard).
        # Only the overall_confidence check is eligible for degradation —
        # the structural min_documents / min_similarity_threshold checks
        # signal we have no usable patterns at all and must hard-refuse.
        confidence_details = validation_result.get("confidence_details")
        if confidence_details is not None:
            conf = float(confidence_details.get("overall_confidence", 0.0))
            if conf >= self.degrade_lower_bound:
                # Degraded mode: pull related topics for the disclaimer.
                related_topics: List[str] = []
                if self.knowledge_analyzer:
                    try:
                        related_topics = await self.knowledge_analyzer.suggest_similar_topics(
                            query, top_k=3
                        )
                    except Exception:
                        # Best-effort — degraded mode still proceeds without topics.
                        related_topics = []
                return "degraded", None, related_topics

        # Hard refuse — either structural failure or confidence below floor.
        insufficient_response = await self.create_insufficient_context_response(
            query,
            validation_result
        )
        return "refuse", insufficient_response, []
