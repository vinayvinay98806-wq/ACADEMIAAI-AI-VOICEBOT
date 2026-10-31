"""Request and correlation ID middleware for Team SDE 7."""

import re
import time
import uuid
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import correlation_id_ctx, logger, request_id_ctx

REQUEST_ID_HEADER = "X-Request-ID"
CORRELATION_ID_HEADER = "X-Correlation-ID"

# Safe ID pattern: 1-128 chars, alphanumeric, hyphens, underscores, dots
VALID_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]{1,128}$")


def _is_valid_id(value: str | None) -> bool:
    """Validate incoming request or correlation ID safely."""
    if not value or not isinstance(value, str):
        return False
    return bool(VALID_ID_PATTERN.match(value.strip()))


class RequestCorrelationMiddleware(BaseHTTPMiddleware):
    """Middleware to safely handle and propagate Request and Correlation IDs."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Extract and validate incoming X-Request-ID
        raw_req_id = request.headers.get(REQUEST_ID_HEADER)
        if _is_valid_id(raw_req_id):
            request_id = raw_req_id.strip()
        else:
            request_id = f"req-{uuid.uuid4().hex[:12]}"

        # Extract and validate incoming X-Correlation-ID
        raw_corr_id = request.headers.get(CORRELATION_ID_HEADER)
        if _is_valid_id(raw_corr_id):
            correlation_id = raw_corr_id.strip()
        else:
            correlation_id = request_id

        # Attach to request state
        request.state.request_id = request_id
        request.state.correlation_id = correlation_id

        # Set contextvars for structured logging
        req_token = request_id_ctx.set(request_id)
        corr_token = correlation_id_ctx.set(correlation_id)

        start_time = time.perf_counter()
        logger.info(
            f"Incoming request: {request.method} {request.url.path} "
            f"[client={request.client.host if request.client else 'unknown'}]"
        )

        try:
            response: Response = await call_next(request)
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.info(
                f"Completed request: {request.method} {request.url.path} "
                f"status={response.status_code} duration={duration_ms}ms"
            )
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.error(
                f"Unhandled error processing {request.method} {request.url.path} "
                f"after {duration_ms}ms: {exc}"
            )
            raise
        finally:
            # Clean up contextvars
            request_id_ctx.reset(req_token)
            correlation_id_ctx.reset(corr_token)

        # Propagate headers in response
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[CORRELATION_ID_HEADER] = correlation_id

        return response
