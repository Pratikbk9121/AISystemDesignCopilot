"""
Rate limiting via slowapi.

Per-route limits are applied as decorators (`@limiter.limit(...)`). The key
function prefers an authenticated caller ID (stamped on `request.state` by
`require_api_key`) and falls back to the remote address — that way an
unauthenticated `/health` ping is still IP-throttled, while authenticated
calls are throttled per API key regardless of source IP (NAT-friendly).

Storage URI is configurable via `settings.rate_limit_storage_uri`:
- `memory://` (default) is per-process — fine for single-worker dev.
- `redis://...` is shared across workers — required in prod.
"""
from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.config import settings


def caller_key_func(request: Request) -> str:
    """slowapi key function: prefer authenticated caller, fall back to IP."""
    caller_id = getattr(request.state, "caller_id", None)
    if caller_id and caller_id != "anon":
        return f"key:{caller_id}"
    return f"ip:{get_remote_address(request)}"


# Exported limiter. Decorators on routes reference this same instance, and
# `app.state.limiter = limiter` in app/main.py wires it into the request scope.
limiter = Limiter(
    key_func=caller_key_func,
    storage_uri=settings.rate_limit_storage_uri,
    default_limits=[settings.rate_limit_default],
)


# Re-export slowapi's default handler so app/main.py can register it without
# having to know slowapi's internal module layout.
from slowapi import _rate_limit_exceeded_handler as rate_limit_exceeded_handler  # noqa: E402


__all__ = [
    "caller_key_func",
    "limiter",
    "rate_limit_exceeded_handler",
    "RateLimitExceeded",
]
