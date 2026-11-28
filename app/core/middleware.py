"""Request, correlation ID, payload limit, rate limiting, and authorization middleware."""

import hmac
import re
import time
import uuid
from typing import Any, Callable, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import get_settings
from app.core.exceptions import (
    ForbiddenError,
    PayloadTooLargeError,
    RateLimitExceededError,
    UnauthorizedError,
)
from app.core.logging import correlation_id_ctx, logger, request_id_ctx, session_id_ctx
from app.core.rate_limit import get_client_identifier, get_rate_limiter
from app.models.errors import ErrorDetail, ErrorEnvelope

REQUEST_ID_HEADER = "X-Request-ID"
CORRELATION_ID_HEADER = "X-Correlation-ID"

# Safe ID pattern: 1-128 chars, alphanumeric, hyphens, underscores, dots
VALID_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]{1,128}$")

PUBLIC_PATH_PREFIXES = (
    "/health",
    "/ready",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/health",
    "/api/v1/ready",
)


def _is_valid_id(value: str | None) -> bool:
    """Validate incoming request or correlation ID safely."""
    if not value or not isinstance(value, str):
        return False
    return bool(VALID_ID_PATTERN.match(value.strip()))


def is_public_path(path: str) -> bool:
    """Check if the requested path is a designated public endpoint."""
    return any(path == p or path.startswith(f"{p}/") for p in PUBLIC_PATH_PREFIXES)


def extract_token_from_request(request: Request) -> Optional[str]:
    """Extract bearer token or API key from request headers."""
    auth_header = request.headers.get("Authorization")
    if auth_header:
        parts = auth_header.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
        elif len(parts) == 1:
            return parts[0]

    api_key_header = request.headers.get("X-API-Key")
    if api_key_header:
        return api_key_header.strip()

    return None


class RequestCorrelationMiddleware(BaseHTTPMiddleware):
    """Middleware to handle Request/Correlation IDs, payload size limits, rate limiting, and authorization."""

    def __init__(self, app, settings: Optional[Any] = None) -> None:
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        settings = self.settings or (
            getattr(request.app.state, "settings", None)
            if hasattr(request, "app") and hasattr(request.app, "state")
            else None
        ) or get_settings()

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
        sess_token = session_id_ctx.set(None)

        start_time = time.perf_counter()
        logger.info(
            f"Incoming request: {request.method} {request.url.path} "
            f"[client={request.client.host if request.client else 'unknown'}]"
        )

        rate_limit_meta = None

        try:
            # 1. Enforce payload size limit on incoming requests with a body
            max_bytes = settings.max_payload_size_bytes
            content_length_header = request.headers.get("content-length")
            if content_length_header:
                try:
                    content_length = int(content_length_header)
                    if content_length > max_bytes:
                        raise PayloadTooLargeError(max_bytes=max_bytes, received_bytes=content_length)
                except ValueError:
                    pass

            if request.method in ("POST", "PUT", "PATCH"):
                body = await request.body()
                if len(body) > max_bytes:
                    raise PayloadTooLargeError(max_bytes=max_bytes, received_bytes=len(body))

            # 2. Enforce Rate Limiting (bypassed on public health endpoints)
            if settings.rate_limit_enabled and not is_public_path(request.url.path):
                limiter = get_rate_limiter()
                client_id = get_client_identifier(request)
                rate_limit_meta = limiter.check(
                    client_key=client_id,
                    max_requests=settings.rate_limit_requests,
                    window_seconds=float(settings.rate_limit_window_seconds),
                )

            # 3. Enforce Local Authorization (bypassed on public endpoints or if auth_enabled=False)
            if settings.auth_enabled and not is_public_path(request.url.path):
                token = extract_token_from_request(request)
                if not token:
                    raise UnauthorizedError(
                        message="Authentication required. Provide 'Authorization: Bearer <token>' or 'X-API-Key'."
                    )
                expected = settings.auth_token or ""
                if not hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8")):
                    raise ForbiddenError(message="Invalid authentication credentials.")

            response: Response = await call_next(request)
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.info(
                f"Completed request: {request.method} {request.url.path} "
                f"status={response.status_code} duration={duration_ms}ms"
            )

        except PayloadTooLargeError as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.warning(
                f"Payload limit exceeded on {request.method} {request.url.path} "
                f"after {duration_ms}ms: {exc.message}"
            )
            envelope = ErrorEnvelope(
                success=False,
                error=ErrorDetail(
                    code=exc.code,
                    message=exc.message,
                    request_id=request_id,
                    details=exc.details,
                ),
            )
            response = JSONResponse(
                status_code=exc.status_code,
                content=envelope.model_dump(mode="json"),
            )

        except UnauthorizedError as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.warning(f"Unauthorized access on {request.method} {request.url.path}")
            envelope = ErrorEnvelope(
                success=False,
                error=ErrorDetail(
                    code=exc.code,
                    message=exc.message,
                    request_id=request_id,
                    details=exc.details,
                ),
            )
            response = JSONResponse(
                status_code=exc.status_code,
                content=envelope.model_dump(mode="json"),
                headers={"WWW-Authenticate": "Bearer"},
            )

        except ForbiddenError as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.warning(f"Forbidden access on {request.method} {request.url.path}")
            envelope = ErrorEnvelope(
                success=False,
                error=ErrorDetail(
                    code=exc.code,
                    message=exc.message,
                    request_id=request_id,
                    details=exc.details,
                ),
            )
            response = JSONResponse(
                status_code=exc.status_code,
                content=envelope.model_dump(mode="json"),
            )

        except RateLimitExceededError as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.warning(f"Rate limit exceeded on {request.method} {request.url.path}")
            envelope = ErrorEnvelope(
                success=False,
                error=ErrorDetail(
                    code=exc.code,
                    message=exc.message,
                    request_id=request_id,
                    details=exc.details,
                ),
            )
            response = JSONResponse(
                status_code=exc.status_code,
                content=envelope.model_dump(mode="json"),
                headers={
                    "Retry-After": str(exc.retry_after),
                    "X-RateLimit-Limit": str(settings.rate_limit_requests),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(exc.retry_after),
                },
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
            session_id_ctx.reset(sess_token)

        # Propagate headers in response
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[CORRELATION_ID_HEADER] = correlation_id

        if rate_limit_meta:
            response.headers["X-RateLimit-Limit"] = str(rate_limit_meta["limit"])
            response.headers["X-RateLimit-Remaining"] = str(rate_limit_meta["remaining"])
            response.headers["X-RateLimit-Reset"] = str(rate_limit_meta["reset_seconds"])

        return response
