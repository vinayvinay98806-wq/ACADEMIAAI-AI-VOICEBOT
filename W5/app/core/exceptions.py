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
