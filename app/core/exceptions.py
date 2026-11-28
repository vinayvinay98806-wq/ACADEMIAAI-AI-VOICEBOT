"""Domain exceptions for the Academiaai Voicebot backend."""

from typing import Any, Optional


class AppException(Exception):
    """Base application exception for all typed domain errors."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = 500,
        details: Optional[Any] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details


class NotFoundError(AppException):
    """Raised when an entity or resource is not found."""

    def __init__(self, message: str = "Resource not found", details: Optional[Any] = None):
        super().__init__(
            message=message,
            code="NOT_FOUND",
            status_code=404,
            details=details,
        )


class SessionNotFoundError(NotFoundError):
    """Raised when a voice session does not exist."""

    def __init__(self, session_id: str):
        super().__init__(
            message=f"Session not found with ID: {session_id}",
            details={"session_id": session_id},
        )


class BadRequestError(AppException):
    """Raised when client input or state is invalid."""

    def __init__(self, message: str = "Bad request", details: Optional[Any] = None):
        super().__init__(
            message=message,
            code="BAD_REQUEST",
            status_code=400,
            details=details,
        )


class InvalidStateTransitionError(AppException):
    """Raised when an illegal session state transition is attempted."""

    def __init__(
        self,
        current_state: str,
        target_state: str,
        reason: Optional[str] = None,
    ):
        msg = f"Cannot transition session from '{current_state}' to '{target_state}'."
        if reason:
            msg += f" Reason: {reason}"
        super().__init__(
            message=msg,
            code="INVALID_STATE_TRANSITION",
            status_code=409,
            details={
                "current_state": current_state,
                "target_state": target_state,
                "reason": reason,
            },
        )


class ServiceUnavailableError(AppException):
    """Raised when a downstream dependency or service is unavailable."""

    def __init__(self, message: str = "Service unavailable", details: Optional[Any] = None):
        super().__init__(
            message=message,
            code="SERVICE_UNAVAILABLE",
            status_code=503,
            details=details,
        )


class PayloadTooLargeError(AppException):
    """Raised when a request payload exceeds the configured maximum allowed size."""

    def __init__(
        self,
        max_bytes: int,
        received_bytes: Optional[int] = None,
        message: Optional[str] = None,
    ):
        msg = message or f"Request payload exceeds maximum allowed size of {max_bytes} bytes."
        details = {"max_bytes": max_bytes}
        if received_bytes is not None:
            details["received_bytes"] = received_bytes
        super().__init__(
            message=msg,
            code="PAYLOAD_TOO_LARGE",
            status_code=413,
            details=details,
        )


class ConfigurationError(AppException):
    """Raised when application startup configuration is missing or invalid."""

    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(
            message=message,
            code="CONFIGURATION_ERROR",
            status_code=500,
            details=details,
        )


class UnauthorizedError(AppException):
    """Raised when authentication credentials are required but missing or malformed."""

    def __init__(
        self,
        message: str = "Authentication required. Provide valid 'Authorization: Bearer <token>' or 'X-API-Key'.",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            code="UNAUTHORIZED",
            status_code=401,
            details=details,
        )


class ForbiddenError(AppException):
    """Raised when authentication credentials are provided but invalid or forbidden."""

    def __init__(
        self,
        message: str = "Invalid authentication credentials.",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            code="FORBIDDEN",
            status_code=403,
            details=details,
        )


class RateLimitExceededError(AppException):
    """Raised when a client exceeds the allowed request rate limit."""

    def __init__(
        self,
        message: str = "Rate limit exceeded. Please wait before retrying.",
        retry_after: int = 60,
        details: Optional[Any] = None,
    ):
        detail_dict = {"retry_after_seconds": retry_after}
        if isinstance(details, dict):
            detail_dict.update(details)
        self.retry_after = retry_after
        super().__init__(
            message=message,
            code="RATE_LIMIT_EXCEEDED",
            status_code=429,
            details=detail_dict,
        )


class GatewayError(AppException):
    """Raised when a gateway downstream module fails or produces invalid output."""

    def __init__(
        self,
        module_name: str,
        message: str,
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=f"Gateway failure in module '{module_name}': {message}",
            code="GATEWAY_ERROR",
            status_code=502,
            details={"module": module_name, "error": message, "extra": details},
        )


class GatewayTimeoutError(AppException):
    """Raised when a gateway downstream module call times out."""

    def __init__(
        self,
        module_name: str,
        timeout_seconds: float,
    ):
        super().__init__(
            message=f"Gateway call to module '{module_name}' timed out after {timeout_seconds:.1f}s.",
            code="GATEWAY_TIMEOUT",
            status_code=504,
            details={"module": module_name, "timeout_seconds": timeout_seconds},
        )
