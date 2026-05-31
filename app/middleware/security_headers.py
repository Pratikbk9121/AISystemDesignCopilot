"""
Security headers middleware.

Emits a baseline set of browser-protection headers on every response. CSP is
locked down for normal API paths (this is a JSON API; browsers should never
execute anything from it) but relaxed for the Swagger / ReDoc / OpenAPI routes
so the docs UI keeps working — those pages legitimately need jsdelivr-hosted
scripts/styles and inline bootstrapping.

HSTS is intentionally emitted only in `ENVIRONMENT=prod`. In dev the app runs
over plain `http://localhost`, and a stray HSTS header would pin browsers into
HTTPS-only for the localhost origin and break local dev for the user.
"""
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.config import settings


# Locked-down CSP for the JSON API surface. `default-src 'none'` means a
# misconfigured or compromised route cannot trick a browser into loading
# anything; `frame-ancestors 'none'` prevents clickjacking even where
# X-Frame-Options is ignored (modern browsers prefer CSP).
_DEFAULT_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"

# Swagger / ReDoc need to fetch their JS+CSS bundle from jsdelivr and execute
# inline init code. Keep this list explicit — it's small and rarely changes.
_DOCS_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://cdn.jsdelivr.net https://fastapi.tiangolo.com; "
    "font-src 'self' https://cdn.jsdelivr.net; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'"
)

_DOCS_PATHS = frozenset({"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"})


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach browser-protection headers to every outgoing response."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )

        path = request.url.path
        csp = _DOCS_CSP if path in _DOCS_PATHS else _DEFAULT_CSP
        response.headers.setdefault("Content-Security-Policy", csp)

        # Only pin HTTPS in prod — emitting HSTS over http://localhost would
        # poison the browser's HSTS cache for localhost and break dev.
        if settings.environment == "prod":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )

        return response
