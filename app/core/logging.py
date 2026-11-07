"""Structured logging configuration with context propagation and sensitive data masking."""

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Optional

request_id_ctx: ContextVar[Optional[str]] = ContextVar("request_id_ctx", default=None)
correlation_id_ctx: ContextVar[Optional[str]] = ContextVar("correlation_id_ctx", default=None)
session_id_ctx: ContextVar[Optional[str]] = ContextVar("session_id_ctx", default=None)

# Patterns for sensitive tokens, passwords, and API keys
SENSITIVE_PATTERNS = [
    re.compile(r'(?i)(api[_-]?key|password|secret|token|bearer|auth|authorization)["\s:=]+([a-zA-Z0-9_\-\.]{6,})'),
    re.compile(r'(?i)(sk-[a-zA-Z0-9]{20,})'),
]


class RequestContextFilter(logging.Filter):
    """Logging filter to inject request_id, correlation_id, and session_id into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get() or "-"
        record.correlation_id = correlation_id_ctx.get() or "-"
        record.session_id = session_id_ctx.get() or "-"

        # Mask any sensitive data in the log message
        if isinstance(record.msg, str):
            record.msg = self.sanitize_sensitive_data(record.msg)

        return True

    @staticmethod
    def sanitize_sensitive_data(message: str) -> str:
        """Mask sensitive keys, tokens, or credentials in log messages."""
        sanitized = message
        for pattern in SENSITIVE_PATTERNS:
            sanitized = pattern.sub(r"\1=***REDACTED***", sanitized)
        return sanitized


class JSONLogFormatter(logging.Formatter):
    """Structured JSON formatter for production log aggregators."""

    def format(self, record: logging.LogRecord) -> str:
        log_payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "correlation_id": getattr(record, "correlation_id", "-"),
            "session_id": getattr(record, "session_id", "-"),
        }
        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_payload)


def setup_logging(level: str = "INFO", format_type: str = "text") -> logging.Logger:
    """Configure root and application loggers with structured output."""
    logger = logging.getLogger("academiaai")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear existing handlers to prevent duplicate outputs
    logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)

    if format_type.lower() == "json":
        handler.setFormatter(JSONLogFormatter())
    else:
        text_format = (
            "%(asctime)s [%(levelname)s] [req_id=%(request_id)s] "
            "[corr_id=%(correlation_id)s] [sess_id=%(session_id)s] %(name)s: %(message)s"
        )
        handler.setFormatter(logging.Formatter(text_format))

    handler.addFilter(RequestContextFilter())
    logger.addHandler(handler)
    logger.propagate = False

    return logger


logger = setup_logging()
