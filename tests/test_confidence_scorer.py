"""
Unit tests for app.core.rag.confidence_scorer.ConfidenceScorer.

The scorer is pure-python (no I/O) so these tests are deterministic.
"""
from __future__ import annotations

import pytest

from app.core.rag.confidence_scorer import ConfidenceScorer
from app.core.rag.document_processor import Document


def _doc(content: str, source: str = "doc.md") -> Document:
    return Document(content=content, metadata={"source": source})


def test_empty_doc_list_returns_zero_retrieval_confidence():
    scorer = ConfidenceScorer()
    assert scorer.calculate_retrieval_confidence([]) == 0.0


def test_high_uniform_scores_yield_high_overall_band():
    """Three high-similarity, low-variance docs should land in the HIGH band."""
    scorer = ConfidenceScorer()
    docs = [
        (_doc("Sharded database design improves scalability."), 0.95),
        (_doc("Sharded database with replication for scalability."), 0.94),
        (_doc("Database scalability via sharded partitions."), 0.93),
    ]
    result = scorer.calculate_overall_confidence(
        query="sharded database scalability",
        retrieved_docs=docs,
    )
    assert result["confidence_level"] == "HIGH"
    assert result["overall_confidence"] >= 0.8


def test_low_top_score_triggers_threshold_penalty():
    """When the best similarity is below the threshold, confidence drops."""
    scorer = ConfidenceScorer()
    low_docs = [(_doc("Random unrelated content"), 0.2)]
    high_docs = [(_doc("Random unrelated content"), 0.8)]
    low_conf = scorer.calculate_retrieval_confidence(
        low_docs, min_score_threshold=0.5
    )
    high_conf = scorer.calculate_retrieval_confidence(
        high_docs, min_score_threshold=0.5
    )
    assert low_conf < high_conf
    # Penalty subtracts 0.3 — low_conf should be noticeably lower.
    assert high_conf - low_conf > 0.2


def test_coverage_tracks_retrieval_similarity():
    """Semantic coverage: mean(scores)*0.8 + doc-count bonus, clamped [0,1].

    Replaces the legacy keyword-overlap heuristic. The new signal is
    embedding-driven, so stop-words in the query no longer change the
    outcome — only the retrieved doc scores matter.
    """
    scorer = ConfidenceScorer()

    high = scorer.calculate_coverage_confidence(
        query="anything", retrieved_docs=[(_doc("x"), 0.9)]
    )
    low = scorer.calculate_coverage_confidence(
        query="anything", retrieved_docs=[(_doc("x"), 0.2)]
    )
    assert high > low
    # 0.9 * 0.8 + 0.04 = 0.76
    assert abs(high - 0.76) < 1e-6
    # 0.2 * 0.8 + 0.04 = 0.20
    assert abs(low - 0.20) < 1e-6

    # Empty docs → 0.0 (no signal at all, treated as no coverage).
    assert scorer.calculate_coverage_confidence(query="q", retrieved_docs=[]) == 0.0


def test_calculate_overall_confidence_returns_full_breakdown():
    """The overall dict carries every documented key plus a recommendation."""
    scorer = ConfidenceScorer()
    docs = [
        (_doc("Sharded database content"), 0.7),
        (_doc("Replication and consistency tradeoffs"), 0.65),
    ]
    result = scorer.calculate_overall_confidence(
        query="sharded database replication",
        retrieved_docs=docs,
    )
    expected_keys = {
        "overall_confidence",
        "confidence_level",
        "retrieval_confidence",
        "coverage_confidence",
        "num_docs_retrieved",
        "avg_similarity_score",
        "recommendation",
    }
    assert expected_keys.issubset(result.keys())
    assert result["num_docs_retrieved"] == 2
    assert result["confidence_level"] in {"HIGH", "MEDIUM", "LOW", "VERY_LOW"}
