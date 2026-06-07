"""
Unit tests for app.core.rag.hallucination_guard.HallucinationGuard.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

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


@pytest.mark.asyncio
async def test_force_generation_bypasses_checks():
    """force_generation=True returns status='proceed' regardless of context."""
    guard = HallucinationGuard()
    status, insufficient, related = await guard.should_proceed_with_generation(
        query="anything", retrieved_docs=[], force_generation=True
    )
    assert status == "proceed"
    assert insufficient is None
    assert related == []


@pytest.mark.asyncio
async def test_low_confidence_degrades_instead_of_refusing():
    """Confidence in [degrade_lower_bound, threshold) returns 'degraded'."""
    fake_vs = MagicMock()
    guard = HallucinationGuard(
        min_documents=1,
        min_similarity_threshold=0.3,
        min_confidence_threshold=0.7,
        degrade_lower_bound=0.3,
        vector_store=fake_vs,
    )
    fake_analyzer = MagicMock()
    fake_analyzer.suggest_similar_topics = AsyncMock(return_value=["Twitter"])
    guard.knowledge_analyzer = fake_analyzer

    docs = [(_doc("Twitter uses fan-out-on-write for feed delivery."), 0.55)]
    status, payload, related = await guard.should_proceed_with_generation(
        query="design instagram", retrieved_docs=docs
    )
    assert status == "degraded"
    assert payload is None
    assert related == ["Twitter"]


@pytest.mark.asyncio
async def test_hard_refuse_when_confidence_below_degrade_floor():
    """Confidence < degrade_lower_bound hard-refuses with payload."""
    fake_vs = MagicMock()
    guard = HallucinationGuard(
        min_documents=1,
        min_similarity_threshold=0.0,
        min_confidence_threshold=0.7,
        degrade_lower_bound=0.5,
        vector_store=fake_vs,
    )
    fake_analyzer = MagicMock()
    fake_analyzer.get_available_topics.return_value = {"topics": [], "example_queries": []}
    fake_analyzer.suggest_similar_topics = AsyncMock(return_value=[])
    guard.knowledge_analyzer = fake_analyzer

    docs = [(_doc("Irrelevant blob."), 0.05)]
    status, payload, related = await guard.should_proceed_with_generation(
        query="design quantum teleportation", retrieved_docs=docs
    )
    assert status == "refuse"
    assert payload is not None
    assert payload["message"] == "Not enough data"
    assert related == []


@pytest.mark.asyncio
async def test_insufficient_response_includes_available_topics_when_analyzer_attached():
    """When a vector_store is passed, the analyzer surfaces topics."""
    fake_vs = MagicMock()
    guard = HallucinationGuard(min_documents=1, vector_store=fake_vs)

    # Replace the lazy-built analyzer with a stub that returns deterministic data.
    # suggest_similar_topics is async on the real analyzer, so the stub must too.
    fake_analyzer = MagicMock()
    fake_analyzer.get_available_topics.return_value = {
        "topics": [{"name": "URL Shortener"}, {"name": "Cache"}],
        "example_queries": ["Design a URL Shortener", "Design a cache"],
    }
    fake_analyzer.suggest_similar_topics = AsyncMock(return_value=["URL Shortener"])
    guard.knowledge_analyzer = fake_analyzer

    validation = {
        "is_sufficient": False,
        "reason": "Not enough docs",
        "suggestion": "Add more sources",
        "confidence_details": None,
    }
    response = await guard.create_insufficient_context_response(
        query="design an unknown system",
        validation_result=validation,
    )
    assert response["message"] == "Not enough data"
    assert "URL Shortener" in response["available_topics"]
    assert "URL Shortener" in response["similar_topics"]
    assert response["example_queries"]
