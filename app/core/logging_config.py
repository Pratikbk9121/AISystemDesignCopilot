"""
Centralized logging configuration
"""
import logging
import sys
import json
from datetime import datetime
from typing import Any
from pathlib import Path

from app.core.config import settings


def _current_request_id() -> str | None:
    """Look up the request-scoped correlation ID via lazy import.

    The lazy import avoids a circular import at module load — `app.middleware`
    pulls in submodules that themselves use `get_logger`, which imports this
    module. By deferring until `format()` is called we sidestep the cycle.
    """
    try:
        from app.middleware.request_id import request_id_var

        return request_id_var.get()
    except Exception:
        return None


class JSONFormatter(logging.Formatter):
    """
    Custom JSON formatter for structured logging
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON"""
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Correlation ID — present whenever the log call happens inside a
        # request task (RequestIdMiddleware sets the ContextVar).
        rid = _current_request_id()
        if rid is not None:
            log_data["request_id"] = rid

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields
        if hasattr(record, "extra_data"):
            log_data.update(record.extra_data)

        return json.dumps(log_data)


class TextFormatter(logging.Formatter):
    """
    Custom text formatter with colors for console output
    """

    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
    }
    RESET = '\033[0m'

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with colors"""
        color = self.COLORS.get(record.levelname, self.RESET)

        # Short-form request id prefix (first 8 chars) so terminal output stays
        # scannable. Omitted entirely outside of request context.
        rid = _current_request_id()
        rid_prefix = f"[rid={rid[:8]}] " if rid else ""

        # Format: [LEVEL] timestamp [rid=...] - logger - message
        formatted = (
            f"{color}[{record.levelname}]{self.RESET} "
            f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} "
            f"{rid_prefix}- {record.name} - {record.getMessage()}"
        )

        # Add exception if present
        if record.exc_info:
            formatted += f"\n{self.formatException(record.exc_info)}"

        return formatted


def setup_logging() -> None:
    """
    Configure application-wide logging based on settings
    """
    # Get log level from settings
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    
    # Create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove existing handlers
    root_logger.handlers.clear()
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    
    # Choose formatter based on settings
    if settings.log_format == "json":
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(TextFormatter())
    
    root_logger.addHandler(console_handler)
    
    # File handler (if configured)
    if settings.log_file:
        log_path = Path(settings.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_path)
        file_handler.setLevel(log_level)
        file_handler.setFormatter(JSONFormatter())  # Always use JSON for file logs
        root_logger.addHandler(file_handler)
    
    # Set specific loggers to avoid noise
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
    
    # Log startup message
    logger = logging.getLogger(__name__)
    logger.info(
        f"Logging initialized: level={settings.log_level}, format={settings.log_format}",
        extra={"extra_data": {"app_name": settings.app_name, "version": settings.app_version}}
    )


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the given name
    
    Args:
        name: Logger name (typically __name__)
        
    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)
