"""
Shared pytest fixtures for the test suite.

Slice 8 (test coverage) adds the API-level fixtures that wire a FastAPI
TestClient against mocked orchestrator/vector_store/state_manager singletons
so route tests can run without hitting Bifrost, Qdrant, or Redis.
"""
from __future__ import annotations

import os
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

# --------------------------------------------------------------------------- #
# Environment defaults
# --------------------------------------------------------------------------- #
# `app.core.config.Settings` requires TEKION_LLM_KEY at module import time and
# applies several prod invariants. Set sane dev defaults BEFORE any
# `app.*` import so importing the FastAPI app inside tests doesn't blow up.
os.environ.setdefault("TEKION_LLM_KEY", "test-llm-key")
os.environ.setdefault("CACHE_KEY_SALT", "test-salt-must-be-16chars-long")
os.environ.setdefault("API_AUTH_ENABLED", "true")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("TEST_API_KEY", "test-key-abc")
os.environ.setdefault("RATE_LIMIT_DEFAULT", "10000/minute")
os.environ.setdefault("RATE_LIMIT_QUERY", "10000/minute")
os.environ.setdefault("RATE_LIMIT_HEALTH", "10000/minute")
os.environ.setdefault("METRICS_ENABLED", "true")
os.environ.setdefault("REDIS_ENABLED", "false")
os.environ.setdefault("AUTO_SEED_KNOWLEDGE", "false")
os.environ.setdefault("QDRANT_REQUIRED_ON_STARTUP", "false")
os.environ.setdefault("BIFROST_HEALTHCHECK_ON_STARTUP", "false")


# --------------------------------------------------------------------------- #
# Redis mock (preserved from Slice 7)
# --------------------------------------------------------------------------- #

@pytest.fixture
def mock_redis():
    """
    Provide an AsyncMock that mimics the async RedisClient surface used by
    CacheManager.

    The mock keeps an in-memory dict so tests can exercise round-trips
    (set then get) without requiring a live Redis instance. All methods are
    async (return-via-side_effect on AsyncMock auto-wraps to a coroutine).
    """
    store: dict[str, bytes] = {}

    client = MagicMock()

    async def _get(key: str):
        return store.get(key)

    async def _set(key: str, value: bytes, ttl=None):
        store[key] = value
        return True

    async def _delete(key: str):
        return store.pop(key, None) is not None

    async def _clear_pattern(pattern: str):
        prefix = pattern.rstrip("*")
        keys = [k for k in store if k.startswith(prefix)]
        for k in keys:
            del store[k]
        return len(keys)

    async def _scan_pattern(pattern: str, count: int = 500):
        prefix = pattern.rstrip("*")
        return [k for k in store if k.startswith(prefix)]

    async def _is_available():
        return True

    client.get = AsyncMock(side_effect=_get)
    client.set = AsyncMock(side_effect=_set)
    client.delete = AsyncMock(side_effect=_delete)
    client.clear_pattern = AsyncMock(side_effect=_clear_pattern)
    client.scan_pattern = AsyncMock(side_effect=_scan_pattern)
    client.is_available = AsyncMock(side_effect=_is_available)
    client._store = store  # exposed for assertions in tests
    return client


@pytest.fixture
def sample_documents():
    """A small set of sample documents for vector-store / RAG-style tests."""
    return [
        {
            "content": "Design a scalable ride-sharing system like Uber.",
            "metadata": {"topic": "system-design", "difficulty": "hard"},
        },
        {
            "content": "Implement a URL shortener service.",
            "metadata": {"topic": "system-design", "difficulty": "medium"},
        },
        {
            "content": "Design a distributed in-memory cache.",
            "metadata": {"topic": "system-design", "difficulty": "hard"},
        },
    ]


# --------------------------------------------------------------------------- #
# API-level fixtures (Slice 8)
# --------------------------------------------------------------------------- #

@pytest.fixture
def sample_documents_with_scores():
    """
    A list of (Document, similarity_score) tuples used by RAG-quality tests
    (reranker, confidence scorer, hallucination guard).
    """
    from app.core.rag.document_processor import Document

    docs = [
        (
            Document(
                content=(
                    "Designing a scalable URL shortener requires sharded "
                    "key generation, caching, and a write-optimized database."
                ),
                metadata={"source": "url_shortener.md"},
            ),
            0.92,
        ),
        (
            Document(
                content=(
                    "Caching strategies include cache-aside, write-through, "
                    "and TTL-based invalidation."
                ),
                metadata={"source": "caching.md"},
            ),
            0.78,
        ),
        (
            Document(
                content="Database sharding splits writes across shards.",
                metadata={"source": "sharding.txt"},
            ),
            0.62,
        ),
    ]
    return docs


@pytest.fixture
def mock_vector_store():
    """
    MagicMock standing in for QdrantVectorStore. `.search` is async; the
    metadata helpers are sync (match the real class shape).
    """
    vs = MagicMock(name="MockVectorStore")
    vs.search = AsyncMock(return_value=[])
    vs.add_documents = AsyncMock(return_value=None)
    vs.get_collection_info = MagicMock(
        return_value={
            "collection_name": "system_design_docs",
            "points_count": 42,
            "vector_size": 768,
            "status": "ok",
        }
    )
    vs.close = MagicMock(return_value=None)
    return vs


@pytest.fixture
def mock_llm_client():
    """AsyncMock standing in for the LLM client used by the orchestrator."""
    client = MagicMock(name="MockLLMClient")
    client.generate = AsyncMock(return_value="LLM response text")
    client.generate_structured = AsyncMock(
        return_value={"services": ["A", "B"], "database": "Postgres"}
    )
    return client


@pytest.fixture
def canned_design_response():
    """A canned SystemDesignResponse to return from the orchestrator mock."""
    from app.models.schemas import (
        SystemArchitecture,
        SystemDesignResponse,
        TokenUsage,
    )

    return SystemDesignResponse(
        query="Design a URL shortener",
        session_id="sess-abc",
        architecture=SystemArchitecture(
            services=["API Gateway", "URL Service", "Cache"],
            database="Postgres for metadata + Redis for hot lookups",
            scaling_strategy="Horizontal sharding by short-code prefix",
        ),
        explanation="High level URL shortener design.",
        evaluation=None,
        token_usage=TokenUsage(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            estimated_cost_usd=0.001,
        ),
        retrieved_context=["doc1", "doc2"],
    )


@pytest.fixture
def mock_orchestrator(canned_design_response):
    """
    AsyncMock standing in for SystemDesignOrchestrator. `generate_design`
    returns the canned response; `stream_design` returns an async generator
    yielding a sensible sequence of SSE events.
    """
    orch = MagicMock(name="MockOrchestrator")
    orch.generate_design = AsyncMock(return_value=canned_design_response)

    async def _stream(_query):
        yield {"type": "metadata", "data": {"session_id": "sess-abc"}}
        yield {"type": "progress", "data": {"step": "retrieving"}}
        yield {
            "type": "design_complete",
            "data": {
                "architecture": {
                    "services": ["A"],
                    "database": "Postgres",
                    "scaling_strategy": "shard",
                },
                "explanation": "done",
                "revision_count": 0,
            },
        }
        yield {"type": "done", "data": {"session_id": "sess-abc"}}

    orch.stream_design = _stream
    return orch


@pytest.fixture
def mock_knowledge_analyzer():
    """
    MagicMock standing in for KnowledgeAnalyzer. `get_available_topics`
    returns a dict (matching the real signature) and `get_knowledge_stats`
    returns a dict.

    Kept as its own fixture so individual tests can mutate the return values
    (e.g. raise an exception) without touching the shared `api_client` wiring.
    """
    analyzer = MagicMock(name="MockKnowledgeAnalyzer")
    analyzer.get_available_topics.return_value = {
        "topics": [{"name": "URL Shortener", "file": "url_shortener.md"}],
        "document_count": 1,
        "coverage_areas": {"other": ["URL Shortener"]},
        "example_queries": ["Design a URL Shortener"],
        "vector_store_stats": {},
        "knowledge_base_path": "./data/system_design_docs",
    }
    analyzer.get_knowledge_stats.return_value = {
        "total_files": 1,
        "total_size_mb": 0.1,
        "file_types": {".md": 1},
        "largest_files": [],
    }
    return analyzer


@pytest.fixture
def api_test_key():
    """The x-api-key value pinned by `api_client` and accepted by the auth dep."""
    return "test-key-abc"


@pytest.fixture
def mock_state_manager():
    """AsyncMock standing in for a ConversationStateManager."""
    from app.models.schemas import ConversationHistory, ConversationMessage

    mgr = MagicMock(name="MockStateManager")
    convo = ConversationHistory(
        session_id="sess-abc",
        messages=[
            ConversationMessage(role="user", content="Hello"),
            ConversationMessage(role="assistant", content="Hi"),
        ],
    )
    mgr.get_conversation = AsyncMock(return_value=convo)
    mgr.save_conversation = AsyncMock(return_value=None)
    mgr.delete_conversation = AsyncMock(return_value=None)
    mgr.list_sessions = AsyncMock(return_value=["sess-abc"])
    return mgr


@pytest.fixture
def api_client(
    monkeypatch,
    mock_vector_store,
    mock_orchestrator,
    mock_state_manager,
    mock_knowledge_analyzer,
    api_test_key,
):
    """
    Yield a `fastapi.testclient.TestClient` wired against the mocked
    orchestrator / vector_store / state_manager singletons.

    `app/api/routes.py` calls module-level factories (`get_vector_store`,
    `get_conversation_cache`, `create_state_manager`) and constructs
    `SystemDesignOrchestrator()` / `KnowledgeAnalyzer()` inline rather than
    via FastAPI `Depends`, so we patch the module-level names directly
    rather than using `app.dependency_overrides`.

    The fixture also pins `settings.test_api_key` to a known value so tests
    can authenticate via `headers={"x-api-key": "test-key-abc"}`.
    """
    from fastapi.testclient import TestClient

    from app.core.config import settings as app_settings

    # Pin the test API key for the duration of the fixture.
    original_test_key = app_settings.test_api_key
    app_settings.test_api_key = api_test_key

    # Patch the route module's singletons.
    import app.api.routes as routes_module

    monkeypatch.setattr(
        routes_module,
        "get_vector_store",
        lambda: mock_vector_store,
    )
    monkeypatch.setattr(
        routes_module,
        "get_conversation_cache",
        lambda: None,  # state manager factory accepts None and returns in-memory
    )
    monkeypatch.setattr(
        routes_module,
        "create_state_manager",
        lambda _cache: mock_state_manager,
    )
    monkeypatch.setattr(
        routes_module,
        "SystemDesignOrchestrator",
        lambda: mock_orchestrator,
    )

    # Patch the global vector_store dependency too so /readyz finds it.
    import app.core.dependencies as deps_module

    monkeypatch.setattr(
        deps_module,
        "get_vector_store",
        lambda: mock_vector_store,
    )

    # Patch KnowledgeAnalyzer with the shared stub so individual tests can mutate
    # its return values via the `mock_knowledge_analyzer` fixture without
    # reaching into `api_client`.
    monkeypatch.setattr(
        routes_module,
        "KnowledgeAnalyzer",
        lambda **_kw: mock_knowledge_analyzer,
    )

    # Import the app *after* env defaults are applied at module import.
    from app.main import app

    with TestClient(app) as client:
        client.fake_analyzer = mock_knowledge_analyzer  # exposed for tests that mutate it
        yield client

    # Restore the original test_api_key value.
    app_settings.test_api_key = original_test_key
