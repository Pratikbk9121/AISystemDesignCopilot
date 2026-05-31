"""
API route tests (Slice 8).

Uses `fastapi.testclient.TestClient` plus the `api_client` fixture which
patches the route module's singletons (`get_vector_store`,
`get_conversation_cache`, `create_state_manager`, `SystemDesignOrchestrator`,
`KnowledgeAnalyzer`) so the tests never touch Bifrost / Qdrant / Redis.

Auth: a known `TEST_API_KEY` value is pinned by the `api_client` fixture.
Protected routes pass `headers={"x-api-key": "test-key-abc"}`.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

API_PREFIX = "/api/v1/system-design"
HEADERS = {"x-api-key": "test-key-abc"}


# --------------------------------------------------------------------------- #
# Public (unauthenticated) endpoints
# --------------------------------------------------------------------------- #

def test_health_endpoint_returns_expected_shape(api_client):
    resp = api_client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert "service" in body
    assert "version" in body


def test_readyz_returns_json_with_status_and_checks(api_client):
    """/readyz returns 200 or 503; either is acceptable in unit-test boot.
    Assert the body shape so an operator could read it."""
    resp = api_client.get("/readyz")
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert isinstance(body, dict)
    assert "status" in body
    assert "checks" in body
    assert isinstance(body["checks"], dict)


def test_metrics_endpoint_serves_prometheus_text(api_client):
    resp = api_client.get("/metrics")
    assert resp.status_code == 200
    # Prometheus content-type starts with text/plain.
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text
    assert "http_requests_total" in body


def test_root_endpoint_returns_welcome_payload(api_client):
    resp = api_client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert "message" in body
    assert "version" in body


# --------------------------------------------------------------------------- #
# Auth gate
# --------------------------------------------------------------------------- #

def test_query_without_api_key_returns_401(api_client):
    resp = api_client.post(
        f"{API_PREFIX}/query",
        json={"query": "Design a URL shortener that scales horizontally."},
    )
    assert resp.status_code == 401


def test_query_with_invalid_api_key_returns_401(api_client):
    resp = api_client.post(
        f"{API_PREFIX}/query",
        headers={"x-api-key": "nope"},
        json={"query": "Design a URL shortener that scales horizontally."},
    )
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# POST /query
# --------------------------------------------------------------------------- #

def test_query_happy_path_returns_200_with_canned_response(
    api_client, canned_design_response
):
    resp = api_client.post(
        f"{API_PREFIX}/query",
        headers=HEADERS,
        json={"query": "Design a scalable URL shortener service."},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == canned_design_response.session_id
    assert body["explanation"] == canned_design_response.explanation
    assert body["architecture"]["database"].startswith("Postgres")


def test_query_missing_query_field_returns_422(api_client):
    resp = api_client.post(
        f"{API_PREFIX}/query",
        headers=HEADERS,
        json={},
    )
    assert resp.status_code == 422


def test_query_too_short_returns_422(api_client):
    # min_length=10 on the query field
    resp = api_client.post(
        f"{API_PREFIX}/query",
        headers=HEADERS,
        json={"query": "hi"},
    )
    assert resp.status_code == 422


def test_query_with_oversize_context_returns_413(api_client):
    big_value = "x" * 11_000
    resp = api_client.post(
        f"{API_PREFIX}/query",
        headers=HEADERS,
        json={
            "query": "Design a URL shortener with a giant context blob.",
            "context": {"blob": big_value},
        },
    )
    assert resp.status_code == 413


def test_query_orchestrator_failure_returns_500(api_client, mock_orchestrator):
    mock_orchestrator.generate_design = AsyncMock(
        side_effect=RuntimeError("boom — LLM offline")
    )
    resp = api_client.post(
        f"{API_PREFIX}/query",
        headers=HEADERS,
        json={"query": "Design a URL shortener with auto-scaling backends."},
    )
    assert resp.status_code == 500


# --------------------------------------------------------------------------- #
# POST /query-stream
# --------------------------------------------------------------------------- #

def test_query_stream_returns_sse_events(api_client):
    with api_client.stream(
        "POST",
        f"{API_PREFIX}/query-stream",
        headers=HEADERS,
        json={"query": "Stream me a URL shortener design please."},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers.get("cache-control") == "no-cache"

        body = b"".join(resp.iter_bytes()).decode("utf-8")

    # SSE frames look like `event: <name>\ndata: <json>\n\n`.
    assert "event: metadata" in body
    assert "event: design_complete" in body
    assert "event: done" in body


def test_query_stream_validates_context_size(api_client):
    big_value = "x" * 11_000
    resp = api_client.post(
        f"{API_PREFIX}/query-stream",
        headers=HEADERS,
        json={
            "query": "Stream a URL shortener with a huge context.",
            "context": {"blob": big_value},
        },
    )
    assert resp.status_code == 413


# --------------------------------------------------------------------------- #
# GET / DELETE conversation
# --------------------------------------------------------------------------- #

def test_get_conversation_returns_history(api_client, mock_state_manager):
    resp = api_client.get(
        f"{API_PREFIX}/conversation/sess-abc",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == "sess-abc"
    assert len(body["messages"]) == 2
    mock_state_manager.get_conversation.assert_awaited_once_with("sess-abc")


def test_get_conversation_missing_session_returns_404(api_client, mock_state_manager):
    mock_state_manager.get_conversation = AsyncMock(side_effect=KeyError("missing"))
    resp = api_client.get(
        f"{API_PREFIX}/conversation/nope",
        headers=HEADERS,
    )
    assert resp.status_code == 404


def test_delete_conversation_returns_204(api_client, mock_state_manager):
    resp = api_client.delete(
        f"{API_PREFIX}/conversation/sess-abc",
        headers=HEADERS,
    )
    assert resp.status_code == 204
    mock_state_manager.delete_conversation.assert_awaited_once_with("sess-abc")


# --------------------------------------------------------------------------- #
# GET /knowledge/topics + /knowledge/stats
# --------------------------------------------------------------------------- #

def test_knowledge_topics_happy_path(api_client):
    resp = api_client.get(
        f"{API_PREFIX}/knowledge/topics",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert "topics" in body["data"]
    assert body["data"]["document_count"] == 1


def test_knowledge_topics_failure_returns_500(api_client):
    api_client.fake_analyzer.get_available_topics.side_effect = RuntimeError(
        "analyzer offline"
    )
    resp = api_client.get(
        f"{API_PREFIX}/knowledge/topics",
        headers=HEADERS,
    )
    assert resp.status_code == 500


def test_knowledge_stats_happy_path(api_client):
    resp = api_client.get(
        f"{API_PREFIX}/knowledge/stats",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["data"]["total_files"] == 1


def test_knowledge_stats_failure_returns_500(api_client):
    api_client.fake_analyzer.get_knowledge_stats.side_effect = RuntimeError(
        "stats blew up"
    )
    resp = api_client.get(
        f"{API_PREFIX}/knowledge/stats",
        headers=HEADERS,
    )
    assert resp.status_code == 500


# --------------------------------------------------------------------------- #
# Deferred hardening
# --------------------------------------------------------------------------- #

@pytest.mark.skip(reason="rate-limit smoke deferred — needs a per-test limiter reset")
def test_query_rate_limited_429(api_client):
    """Flooding /query past the configured limit should yield 429."""
    raise NotImplementedError
