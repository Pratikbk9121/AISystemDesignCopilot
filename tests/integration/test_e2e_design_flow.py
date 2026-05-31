"""
End-to-end integration smoke tests.

These tests hit a *running* AISystemDesignCopilot stack — real Redis, real
Qdrant, real Bifrost LLM. They're skipped automatically when the required
env vars aren't set so `pytest -m "not integration"` (the default CI gate)
never touches them.

To run locally:
    REDIS_HOST=localhost \
    QDRANT_URL=http://localhost:6333 \
    TEKION_LLM_KEY=sk-... \
    API_BASE_URL=http://localhost:8000 \
    TEST_API_KEY=test-key \
    .venv/bin/python -m pytest tests/integration -m integration -v
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration

# Skip the whole module if the required env vars aren't set. We check at
# module import so collection still works (the test count is visible) but
# execution never tries to connect to a missing service.
_REQUIRED = ("REDIS_HOST", "QDRANT_URL", "TEKION_LLM_KEY", "API_BASE_URL")
_missing = [k for k in _REQUIRED if not os.environ.get(k)]
if _missing:
    pytest.skip(
        f"integration env vars missing: {_missing}. "
        "Set REDIS_HOST, QDRANT_URL, TEKION_LLM_KEY, API_BASE_URL.",
        allow_module_level=True,
    )


# Imports below assume the env is sane.
import httpx  # noqa: E402

API_BASE_URL = os.environ["API_BASE_URL"].rstrip("/")
API_KEY = os.environ.get("TEST_API_KEY", "")
_AUTH_HEADERS = {"x-api-key": API_KEY} if API_KEY else {}


def test_health_live():
    """The deployed instance answers liveness."""
    resp = httpx.get(f"{API_BASE_URL}/health", timeout=5.0)
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


def test_knowledge_topics_live():
    """The knowledge endpoint returns a topic list against real Qdrant."""
    resp = httpx.get(
        f"{API_BASE_URL}/api/v1/system-design/knowledge/topics",
        headers=_AUTH_HEADERS,
        timeout=10.0,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert "topics" in body["data"]


def test_new_design_then_refinement_persists_history():
    """End-to-end: create a design, refine it, verify history has >=2 messages."""
    with httpx.Client(base_url=API_BASE_URL, timeout=120.0) as client:
        first = client.post(
            "/api/v1/system-design/query",
            json={"query": "Design a simple URL shortener service.", "include_evaluation": False},
            headers=_AUTH_HEADERS,
        )
        assert first.status_code == 200
        session_id = first.json()["session_id"]
        assert session_id

        second = client.post(
            "/api/v1/system-design/query",
            json={
                "query": "Add caching to that URL shortener design.",
                "session_id": session_id,
                "include_evaluation": False,
            },
            headers=_AUTH_HEADERS,
        )
        assert second.status_code == 200
        assert second.json()["session_id"] == session_id

        history = client.get(
            f"/api/v1/system-design/conversation/{session_id}",
            headers=_AUTH_HEADERS,
        )
        assert history.status_code == 200
        body = history.json()
        # After two design calls we expect at least two user + two assistant messages.
        assert len(body["messages"]) >= 2
