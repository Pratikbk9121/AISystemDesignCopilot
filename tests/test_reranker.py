"""
Unit tests for app.core.rag.reranker.DocumentReranker.

The reranker's heavy dependency is `EmbeddingGenerator`, so we inject a stub
with a deterministic async `generate_embeddings` to avoid downloading the
HuggingFace model in unit tests.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from app.core.rag.document_processor import Document
from app.core.rag.reranker import DocumentReranker


def _doc(content: str, source: str = "doc.md") -> Document:
    return Document(content=content, metadata={"source": source})


def _stub_embedding_generator(vectors: list[np.ndarray]) -> MagicMock:
    """Build a MagicMock EmbeddingGenerator that returns the given vectors."""
    eg = MagicMock(name="StubEmbeddingGenerator")
    eg.generate_embeddings = AsyncMock(return_value=vectors)
    eg.generate_embedding = AsyncMock(side_effect=lambda _t: vectors[0])
    return eg


@pytest.mark.asyncio
async def test_rerank_empty_input_returns_empty():
    eg = _stub_embedding_generator([])
    reranker = DocumentReranker(embedding_generator=eg)
    result = await reranker.rerank(query="anything", documents=[])
    assert result == []


def test_markdown_source_gets_score_boost():
    """Same initial score, .md docs receive a 1.1x relevance boost."""
    eg = _stub_embedding_generator([np.array([1.0, 0.0])])
    reranker = DocumentReranker(embedding_generator=eg)

    md_doc = _doc("Content about scalability." * 5, source="x.md")
    txt_doc = _doc("Content about scalability." * 5, source="x.txt")
    md_score = reranker.calculate_relevance_score("scalability", md_doc, 0.5)
    txt_score = reranker.calculate_relevance_score("scalability", txt_doc, 0.5)
    assert md_score > txt_score


def test_keyword_overlap_increases_relevance_score():
    """Keyword matches add 0.05 per match — present > absent."""
    eg = _stub_embedding_generator([np.array([1.0, 0.0])])
    reranker = DocumentReranker(embedding_generator=eg)

    matching = _doc(
        "Discussion of caching, database, and api design." * 3,
        source="x.md",
    )
    non_matching = _doc("Some unrelated text about animals." * 3, source="x.md")
    query = "caching database api"
    s1 = reranker.calculate_relevance_score(query, matching, 0.5)
    s2 = reranker.calculate_relevance_score(query, non_matching, 0.5)
    assert s1 > s2


def test_short_doc_gets_length_penalty():
    """Docs under 100 chars get multiplied by 0.8."""
    eg = _stub_embedding_generator([np.array([1.0, 0.0])])
    reranker = DocumentReranker(embedding_generator=eg)

    short_doc = _doc("tiny", source="x.md")
    long_doc = _doc("x" * 500, source="x.md")
    s_short = reranker.calculate_relevance_score("foo", short_doc, 0.5)
    s_long = reranker.calculate_relevance_score("foo", long_doc, 0.5)
    assert s_short < s_long


@pytest.mark.asyncio
async def test_diversity_penalty_drops_near_duplicate():
    """Two near-identical embeddings → the second gets penalized."""
    # Use orthogonal-ish vectors so we can predict diversity behavior.
    vec_a = np.array([1.0, 0.0, 0.0])
    vec_b_near = np.array([0.99, 0.05, 0.0])  # near-duplicate of A
    vec_c_diff = np.array([0.0, 1.0, 0.0])  # different from both

    eg = _stub_embedding_generator([vec_a, vec_b_near, vec_c_diff])
    reranker = DocumentReranker(embedding_generator=eg)

    docs = [
        (_doc("First doc " * 30, source="a.md"), 0.9),
        (_doc("Near duplicate " * 30, source="b.md"), 0.89),
        (_doc("Different content " * 30, source="c.md"), 0.88),
    ]
    ranked = await reranker.rerank(
        query="design", documents=docs, use_diversity=True
    )
    # Near-duplicate should NOT be ranked second — diversity penalty should
    # push the orthogonal doc above it.
    assert ranked[0][0].metadata["source"] == "a.md"
    sources_after_first = [d.metadata["source"] for d, _ in ranked[1:]]
    assert sources_after_first[0] == "c.md"
