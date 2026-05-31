"""
Prometheus metrics — HTTP middleware + module-level instruments.

Exposes:

  - `http_requests_total{path,method,status}` — Counter
  - `http_request_duration_seconds{path,method}` — Histogram
  - `llm_tokens_total{model,kind}` — Counter (kind ∈ prompt|completion)
  - `llm_cost_usd_total{model}` — Counter
  - `cache_hits_total{namespace}` / `cache_misses_total{namespace}` — Counter
  - `qdrant_query_duration_seconds` — Histogram (no labels; one logical op)

The HTTP path label is the *templated* route path (e.g.
`/api/v1/system-design/conversation/{session_id}`), NOT the raw URL — using
raw paths explodes label cardinality once you start handing out UUID session
IDs and breaks Prometheus's per-series storage. Unmatched 404 routes fall
back to `"unmatched"`.

All instruments live in the default registry so `generate_latest()` picks them
up without further wiring. The instruments are module-level singletons; under
pytest, repeated imports of this module would normally trigger
`Duplicated timeseries in CollectorRegistry`. We guard with a try/except so
tests can re-import the app without crashing — the second import just reuses
the metrics already registered.
"""
from __future__ import annotations

import time
from typing import Callable

from fastapi import Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,  # re-exported for callers
    REGISTRY,
    Counter,
    Histogram,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


def _counter(name: str, doc: str, labels: list[str]) -> Counter:
    """Return an existing Counter or create one — idempotent under re-import."""
    existing = REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]
    if existing is not None:
        return existing  # type: ignore[return-value]
    return Counter(name, doc, labels)


def _histogram(
    name: str, doc: str, labels: list[str], buckets: tuple[float, ...]
) -> Histogram:
    """Return an existing Histogram or create one — idempotent under re-import."""
    existing = REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]
    if existing is not None:
        return existing  # type: ignore[return-value]
    return Histogram(name, doc, labels, buckets=buckets)


HTTP_REQUESTS = _counter(
    "http_requests_total",
    "Total HTTP requests handled by the API.",
    ["path", "method", "status"],
)
HTTP_DURATION = _histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["path", "method"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
)
LLM_TOKENS = _counter(
    "llm_tokens_total",
    "Total LLM tokens consumed, split by model and kind (prompt|completion).",
    ["model", "kind"],
)
LLM_COST = _counter(
    "llm_cost_usd_total",
    "Estimated cumulative LLM spend in USD, by model.",
    ["model"],
)
CACHE_HITS = _counter(
    "cache_hits_total",
    "Cache hits by namespace (emb, llm, conv, ...).",
    ["namespace"],
)
CACHE_MISSES = _counter(
    "cache_misses_total",
    "Cache misses by namespace.",
    ["namespace"],
)
QDRANT_QUERY = _histogram(
    "qdrant_query_duration_seconds",
    "Qdrant query_points latency in seconds.",
    [],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
)


__all__ = [
    "CONTENT_TYPE_LATEST",
    "CACHE_HITS",
    "CACHE_MISSES",
    "HTTP_DURATION",
    "HTTP_REQUESTS",
    "LLM_COST",
    "LLM_TOKENS",
    "MetricsMiddleware",
    "QDRANT_QUERY",
]


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record per-request HTTP metrics.

    Path label uses Starlette's matched route template so that variable URL
    segments (session IDs, etc.) collapse into a single time series per
    endpoint. The `/metrics` endpoint itself is skipped so scrapes don't show
    up in the very metrics they expose (would cause a self-amplifying signal).
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip instrumenting the scrape endpoint itself.
        if request.url.path == "/metrics":
            return await call_next(request)

        start = time.perf_counter()
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            # Re-raise but record a 500 so failed requests don't go uncounted.
            elapsed = time.perf_counter() - start
            path = _route_template(request)
            HTTP_REQUESTS.labels(path=path, method=request.method, status="500").inc()
            HTTP_DURATION.labels(path=path, method=request.method).observe(elapsed)
            raise

        elapsed = time.perf_counter() - start
        path = _route_template(request)
        HTTP_REQUESTS.labels(
            path=path, method=request.method, status=str(status)
        ).inc()
        HTTP_DURATION.labels(path=path, method=request.method).observe(elapsed)
        return response


def _route_template(request: Request) -> str:
    """Resolve the matched route's templated path; fall back to ``"unmatched"``.

    Starlette stamps `scope["route"]` once routing succeeds. For 404s the key
    is absent — we deliberately do NOT use `request.url.path` there, because
    attacker-style URL scans would otherwise blow up cardinality.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path or "unmatched"
