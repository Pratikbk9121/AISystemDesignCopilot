"""
Middleware for request/response processing
"""
from app.middleware.auth_middleware import require_api_key
from app.middleware.logging_middleware import (
    ErrorLoggingMiddleware,
    RequestLoggingMiddleware,
)
from app.middleware.metrics import MetricsMiddleware
from app.middleware.rate_limit import (
    RateLimitExceeded,
    caller_key_func,
    limiter,
    rate_limit_exceeded_handler,
)
from app.middleware.request_id import RequestIdMiddleware, request_id_var
from app.middleware.security_headers import SecurityHeadersMiddleware

__all__ = [
    "ErrorLoggingMiddleware",
    "MetricsMiddleware",
    "RateLimitExceeded",
    "RequestIdMiddleware",
    "RequestLoggingMiddleware",
    "SecurityHeadersMiddleware",
    "caller_key_func",
    "limiter",
    "rate_limit_exceeded_handler",
    "request_id_var",
    "require_api_key",
]
