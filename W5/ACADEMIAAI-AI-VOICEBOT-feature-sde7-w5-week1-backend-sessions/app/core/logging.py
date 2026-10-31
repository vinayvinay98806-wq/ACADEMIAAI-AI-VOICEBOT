"""Structured logging configuration with context propagation."""

import logging
import sys
from contextvars import ContextVar
from typing import Optional

request_id_ctx: ContextVar[Optional[str]] = ContextVar("request_id_ctx", default=None)
correlation_id_ctx: ContextVar[Optional[str]] = ContextVar("correlation_id_ctx", default=None)


class RequestContextFilter(logging.Filter):
    """Logging filter to inject request_id and correlation_id into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get() or "-"
        record.correlation_id = correlation_id_ctx.get() or "-"
        return True


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure root and application loggers."""
    log_format = (
        "%(asctime)s [%(levelname)s] [req_id=%(request_id)s] "
        "[corr_id=%(correlation_id)s] %(name)s: %(message)s"
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(log_format))
    handler.addFilter(RequestContextFilter())

    logger = logging.getLogger("academiaai")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Avoid duplicate handlers if called multiple times
    if not logger.handlers:
        logger.addHandler(handler)
        logger.propagate = False

    return logger


logger = setup_logging()
