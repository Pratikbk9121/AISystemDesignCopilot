"""
Unit tests for app.core.rag.hallucination_guard.HallucinationGuard.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.rag.document_processor import Document
from app.core.rag.hallucination_guard import HallucinationGuard


def _doc(content: str, source: str = "doc.md") -> Document:
    return Document(content=content, metadata={"source": source})


def test_min_documents_not_met_returns_not_sufficient():
    guard = HallucinationGuard(min_documents=2)
    result = guard.check_context_sufficiency(query="any", retrieved_docs=[])
    assert result["is_sufficient"] is False
    assert "Insufficient documents" in result["reason"]


def test_top_score_below_similarity_threshold_returns_not_sufficient():
    guard = HallucinationGuard(min_documents=1, min_similarity_threshold=0.6)
    docs = [(_doc("Some content"), 0.4)]
    result = guard.check_context_sufficiency(
        query="design a URL shortener", retrieved_docs=docs
    )
    assert result["is_sufficient"] is False
    assert "Low relevance" in result["reason"]


def test_confidence_below_threshold_returns_not_sufficient():
    """Pass the similarity/document checks but fail on overall confidence."""
    guard = HallucinationGuard(
        min_documents=1,
        min_similarity_threshold=0.0,
        min_confidence_threshold=0.99,
    )
    docs = [(_doc("Marginally relevant content."), 0.45)]
    result = guard.check_context_sufficiency(
        query="some query with keywords",
        retrieved_docs=docs,
    )
    assert result["is_sufficient"] is False
    assert "Low confidence" in result["reason"]


def test_happy_path_passes_all_checks():
    guard = HallucinationGuard(
        min_documents=1,
        min_similarity_threshold=0.3,
        min_confidence_threshold=0.1,
    )
    docs = [
        (_doc("URL shortener uses sharded keys and caching layer."), 0.9),
        (_doc("URL shortener employs hashing and caching tactics."), 0.85),
    ]
    result = guard.check_context_sufficiency(
        query="URL shortener caching",
        retrieved_docs=docs,
    )
    assert result["is_sufficient"] is True
    assert result["confidence_details"] is not None


def test_force_generation_bypasses_checks():
    """force_generation=True returns (True, None) regardless of context."""
    guard = HallucinationGuard()
    proceed, insufficient = guard.should_proceed_with_generation(
        query="anything", retrieved_docs=[], force_generation=True
    )
    assert proceed is True
    assert insufficient is None


def test_insufficient_response_includes_available_topics_when_analyzer_attached():
    """When a vector_store is passed, the analyzer surfaces topics."""
    fake_vs = MagicMock()
    guard = HallucinationGuard(min_documents=1, vector_store=fake_vs)

    # Replace the lazy-built analyzer with a stub that returns deterministic data.
    fake_analyzer = MagicMock()
    fake_analyzer.get_available_topics.return_value = {
        "topics": [{"name": "URL Shortener"}, {"name": "Cache"}],
        "example_queries": ["Design a URL Shortener", "Design a cache"],
    }
    fake_analyzer.suggest_similar_topics.return_value = ["URL Shortener"]
    guard.knowledge_analyzer = fake_analyzer

    validation = {
        "is_sufficient": False,
        "reason": "Not enough docs",
        "suggestion": "Add more sources",
        "confidence_details": None,
    }
    response = guard.create_insufficient_context_response(
        query="design an unknown system",
        validation_result=validation,
    )
    assert response["message"] == "Not enough data"
    assert "URL Shortener" in response["available_topics"]
    assert "URL Shortener" in response["similar_topics"]
    assert response["example_queries"]
