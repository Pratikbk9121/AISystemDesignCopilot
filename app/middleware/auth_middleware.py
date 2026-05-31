"""
API-key authentication for FastAPI routes.

Wired in as a per-router dependency (`Depends(require_api_key)`) rather than
a `BaseHTTPMiddleware`, because `BaseHTTPMiddleware` wraps streaming responses
in a way that breaks `/query-stream` SSE. The dependency runs once at request
start, before the stream opens, which is the correct semantics for both
auth (one-shot check) and rate limiting (one decrement per request).
"""
from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import Header, HTTPException, Request, status

from app.core.config import settings

logger = logging.getLogger(__name__)


def _fingerprint(key: str) -> str:
    """Return a short, non-reversible identifier for a verified key.

    The first 8 hex chars of SHA-256 give ~32 bits of entropy — enough to tell
    callers apart in logs / rate-limit storage without leaking the real key.
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


def _is_valid_key(candidate: str) -> bool:
    """Constant-time compare against configured keys + optional test key."""
    valid: list[str] = list(settings.api_keys)
    if settings.test_api_key:
        valid.append(settings.test_api_key)
    for known in valid:
        if hmac.compare_digest(candidate, known):
            return True
    return False


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> None:
    """FastAPI dependency that enforces `x-api-key` header.

    On success: stamps `request.state.caller_id` with a short fingerprint of
    the verified key so rate limiting and access logs can attribute the call.
    On failure: raises 401.
    On `settings.api_auth_enabled is False`: bypasses entirely (dev mode);
    `caller_id` falls back to `"anon"` so downstream code doesn't need to
    null-check it.
    """
    if not settings.api_auth_enabled:
        request.state.caller_id = "anon"
        return

    if not x_api_key or not _is_valid_key(x_api_key):
        # Don't log the candidate key — just the path, so an attacker can't
        # grep for their attempts in the logs.
        logger.warning(
            "Rejected unauthenticated request",
            extra={"extra_data": {"path": request.url.path}},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    request.state.caller_id = _fingerprint(x_api_key)
