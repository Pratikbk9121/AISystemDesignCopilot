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
        
        # Format: [LEVEL] timestamp - logger - message
        formatted = (
            f"{color}[{record.levelname}]{self.RESET} "
            f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} - "
            f"{record.name} - {record.getMessage()}"
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
