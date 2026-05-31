"""
Request/Response logging middleware for FastAPI
"""
import time
import logging
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.config import settings

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log all HTTP requests and responses
    """
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.enabled = settings.log_requests
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Log request and response details"""
        if not self.enabled:
            return await call_next(request)
        
        # Start timer
        start_time = time.time()
        
        # Log request
        logger.info(
            f"Request started: {request.method} {request.url.path}",
            extra={
                "extra_data": {
                    "method": request.method,
                    "path": request.url.path,
                    "client_host": request.client.host if request.client else None,
                }
            }
        )
        
        # Process request
        try:
            response = await call_next(request)
            
            # Calculate duration
            duration = time.time() - start_time
            
            # Log response
            logger.info(
                f"Request completed: {request.method} {request.url.path} - {response.status_code}",
                extra={
                    "extra_data": {
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": response.status_code,
                        "duration_ms": round(duration * 1000, 2),
                    }
                }
            )
            
            return response
            
        except Exception as e:
            # Calculate duration
            duration = time.time() - start_time
            
            # Log error
            logger.error(
                f"Request failed: {request.method} {request.url.path}",
                exc_info=True,
                extra={
                    "extra_data": {
                        "method": request.method,
                        "path": request.url.path,
                        "duration_ms": round(duration * 1000, 2),
                        "error": str(e),
                    }
                }
            )
            
            raise


class ErrorLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log all unhandled errors
    """
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.enabled = settings.log_errors
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Catch and log unhandled errors"""
        if not self.enabled:
            return await call_next(request)
        
        try:
            return await call_next(request)
        except Exception as e:
            logger.error(
                f"Unhandled error in {request.method} {request.url.path}",
                exc_info=True,
                extra={
                    "extra_data": {
                        "method": request.method,
                        "path": request.url.path,
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    }
                }
            )
            raise
