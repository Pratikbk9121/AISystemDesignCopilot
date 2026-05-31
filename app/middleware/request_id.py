"""
Request correlation IDs.

Generates (or accepts via `x-request-id` header) a stable identifier for the
lifetime of a single HTTP request. The ID is mirrored on:

  - `request.state.request_id` — available to any downstream dependency / route
  - a module-level `ContextVar` — available to logging formatters that have no
    direct access to the Request object (handlers, background helpers).
  - the response `x-request-id` header — clients (and the eval harness) can
    grep their own request out of access logs without needing to correlate
    by timestamp.

The middleware is registered LAST in `app.main` so it wraps every other layer
and the `ContextVar` is set before anything else can emit a log line on this
request's task. Reset via the token in `finally` so the var doesn't leak across
tasks if the same worker handles many requests.
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


# ContextVar holds the current request's ID. `None` when no request is active
# (background tasks, startup/shutdown logs).
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a correlation ID to every request/response.

    Honors an incoming `x-request-id` header so upstream gateways (e.g. an
    nginx ingress) can propagate their existing IDs; otherwise mints a fresh
    `uuid4().hex`.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = rid
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        # Always echo the ID on the response so clients can correlate.
        response.headers["x-request-id"] = rid
        return response
