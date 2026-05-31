"""
Unit tests for app.core.knowledge_analyzer.KnowledgeAnalyzer.

We use `tmp_path` to give the analyzer a controlled filesystem so the tests
don't depend on the real ./data/system_design_docs tree.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.knowledge_analyzer import KnowledgeAnalyzer


def test_missing_data_dir_returns_empty_topics(tmp_path):
    missing = tmp_path / "does_not_exist"
    analyzer = KnowledgeAnalyzer(data_directory=str(missing))
    result = analyzer.get_available_topics()
    assert result["document_count"] == 0
    assert result["topics"] == []


def test_categorization_buckets_populated_correctly(tmp_path):
    """Drop a few .md files matching the known keyword buckets and verify
    they land in the right `coverage_areas` slots."""
    (tmp_path / "ride_sharing_uber.md").write_text("# Uber design\n")
    (tmp_path / "video_streaming_netflix.md").write_text("# Netflix design\n")
    (tmp_path / "social_feed.md").write_text("# Feed design\n")
    (tmp_path / "messaging_whatsapp.md").write_text("# Whatsapp\n")
    (tmp_path / "file_storage_dropbox.md").write_text("# Dropbox\n")
    (tmp_path / "random_other_topic.md").write_text("# Other\n")

    analyzer = KnowledgeAnalyzer(data_directory=str(tmp_path))
    result = analyzer.get_available_topics()

    assert result["document_count"] == 6
    areas = result["coverage_areas"]
    assert "ride-sharing" in areas
    assert "streaming" in areas
    assert "social-media" in areas
    assert "messaging" in areas
    assert "file-storage" in areas
    assert "other" in areas


@pytest.mark.asyncio
async def test_suggest_similar_topics_uses_vector_store(tmp_path):
    """Async search returns docs whose source metadata is converted to titles."""
    from app.core.rag.document_processor import Document

    vs = MagicMock()
    docs = [
        (Document(content="x", metadata={"source": "/path/url_shortener.md"}), 0.9),
        (Document(content="y", metadata={"source": "/path/cache_design.md"}), 0.8),
    ]
    vs.search = AsyncMock(return_value=docs)

    analyzer = KnowledgeAnalyzer(vector_store=vs, data_directory=str(tmp_path))
    suggestions = await analyzer.suggest_similar_topics("design cache", top_k=2)

    assert suggestions  # non-empty
    assert any("Url Shortener" in s or "Cache" in s for s in suggestions)
    vs.search.assert_awaited_once()


def test_get_knowledge_stats_reports_file_counts(tmp_path):
    (tmp_path / "a.md").write_text("alpha")
    (tmp_path / "b.md").write_text("beta beta")
    (tmp_path / "c.txt").write_text("gamma gamma gamma")

    analyzer = KnowledgeAnalyzer(data_directory=str(tmp_path))
    stats = analyzer.get_knowledge_stats()

    assert stats["total_files"] == 3
    assert stats["file_types"][".md"] == 2
    assert stats["file_types"][".txt"] == 1
    assert isinstance(stats["largest_files"], list)
