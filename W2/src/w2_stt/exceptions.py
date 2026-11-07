"""Structured exception hierarchy and error normalization for Workstream W2: Speech-to-Text.

This module defines domain-specific exceptions for STT orchestration:
- STTError: Base class for all STT errors.
- STTConfigurationError: Configuration validation errors.
- STTInputError: Invalid or corrupted audio chunk inputs.
- STTProviderError: Provider-neutral wrapper for speech engine errors.
  - STTTransientError: Temporary/retryable errors (rate limits, timeouts, connection drops).
  - STTTimeoutError: Specific transient timeout error.
  - STTPermanentError: Non-retryable errors (auth failures, invalid formats, quota exhaustion).
- STTPreprocessingError: Audio preprocessing failures (resampling, normalization).

It also provides utility functions to normalize arbitrary provider exceptions into
standardized STTProviderError instances and TranscriptErrorInfo payloads.
"""

from __future__ import annotations

import socket
from typing import Any, Dict, Optional

from w2_stt.schemas import TranscriptErrorInfo


class STTError(Exception):
    """Base exception for all Speech-to-Text pipeline errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} (details: {self.details})"
        return self.message


class STTConfigurationError(STTError):
    """Raised when an STT component is configured with invalid parameters."""
    pass


class STTInputError(STTError):
    """Raised when input audio data or metadata is corrupted, empty, or invalid."""
    pass


class STTPreprocessingError(STTError):
    """Raised when audio preprocessing (resampling, normalization, format conversion) fails."""
    pass


class STTProviderError(STTError):
    """Base exception for transcription provider and adapter failures.

    Attributes:
        message: Human-readable error description.
        provider_name: Identifier of the provider that produced the error.
        cause: The underlying exception if this wraps an external error.
        details: Additional diagnostic metadata.
        is_transient: Flag indicating whether this error is considered retryable.
    """

    def __init__(
        self,
        message: str,
        provider_name: Optional[str] = None,
        cause: Optional[Exception] = None,
        details: Optional[Dict[str, Any]] = None,
        is_transient: bool = False,
    ) -> None:
        super().__init__(message, details)
        self.provider_name = provider_name or "UnknownProvider"
        self.cause = cause
        self.is_transient = is_transient
        if cause is not None and self.__cause__ is None:
            self.__cause__ = cause

    def __str__(self) -> str:
        base = f"[{self.provider_name}] {self.message}"
        if self.details:
            base += f" (details: {self.details})"
        if self.cause:
            base += f" [caused by {type(self.cause).__name__}: {self.cause}]"
        return base


class STTTransientError(STTProviderError):
    """Raised for transient, potentially recoverable provider failures.

    Examples:
    - Network glitches and connection resets.
    - HTTP 429 Too Many Requests / Rate limiting.
    - HTTP 502 / 503 / 504 Gateway & Service Unavailable.
    - Transient provider timeouts.
    """

    def __init__(
        self,
        message: str,
        provider_name: Optional[str] = None,
        cause: Optional[Exception] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            provider_name=provider_name,
            cause=cause,
            details=details,
            is_transient=True,
        )


class STTTimeoutError(STTTransientError):
    """Raised when an STT provider operation exceeds the configured timeout limit."""

    def __init__(
        self,
        message: str = "Transcription provider operation timed out",
        provider_name: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        cause: Optional[Exception] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        merged_details = dict(details or {})
        if timeout_seconds is not None:
            merged_details["timeout_seconds"] = timeout_seconds
        super().__init__(
            message=message,
            provider_name=provider_name,
            cause=cause,
            details=merged_details,
        )
        self.timeout_seconds = timeout_seconds


class STTPermanentError(STTProviderError):
    """Raised for non-recoverable provider failures that should not be retried.

    Examples:
    - Authentication / Invalid API key (HTTP 401).
    - Forbidden / Permission denied (HTTP 403).
    - Bad Request / Unacceptable format (HTTP 400).
    - Quota exceeded / Account suspended.
    - Irrecoverable provider internal logic error.
    """

    def __init__(
        self,
        message: str,
        provider_name: Optional[str] = None,
        cause: Optional[Exception] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            provider_name=provider_name,
            cause=cause,
            details=details,
            is_transient=False,
        )


def normalize_provider_error(
    error: Exception,
    provider_name: str = "UnknownProvider",
) -> STTProviderError:
    """Normalize any arbitrary provider or runtime exception into a structured STTProviderError.

    Distinguishes transient from permanent failures by inspecting exception types and messages.

    Args:
        error: The caught exception.
        provider_name: Name of the active transcription provider.

    Returns:
        An instance of STTProviderError (or its subclass STTTransientError / STTTimeoutError / STTPermanentError).
    """
    if isinstance(error, STTProviderError):
        return error

    err_msg = str(error)
    err_msg_lower = err_msg.lower()
    err_cls_name = type(error).__name__.lower()

    # 1. Timeout classifications
    if isinstance(error, (TimeoutError, socket.timeout)) or "timeout" in err_cls_name or "timed out" in err_msg_lower:
        return STTTimeoutError(
            message=f"Transcription operation timed out: {err_msg}",
            provider_name=provider_name,
            cause=error,
        )

    # 2. Transient network and rate-limit classifications
    transient_indicators = (
        "rate limit",
        "too many requests",
        "429",
        "502 bad gateway",
        "503 service unavailable",
        "504 gateway timeout",
        "connection reset",
        "connection refused",
        "broken pipe",
        "temporarily unavailable",
        "try again later",
    )
    if isinstance(error, (ConnectionResetError, ConnectionRefusedError, BrokenPipeError, ConnectionError)) or any(
        ind in err_msg_lower for ind in transient_indicators
    ):
        return STTTransientError(
            message=f"Transient provider failure: {err_msg}",
            provider_name=provider_name,
            cause=error,
        )

    # 3. Permanent classifications (auth, permission, format, value)
    permanent_indicators = (
        "unauthorized",
        "401",
        "forbidden",
        "403",
        "invalid api key",
        "bad request",
        "400",
        "quota exceeded",
        "unsupported format",
    )
    if isinstance(error, (PermissionError, ValueError, KeyError, TypeError)) or any(
        ind in err_msg_lower for ind in permanent_indicators
    ):
        return STTPermanentError(
            message=f"Permanent provider failure: {err_msg}",
            provider_name=provider_name,
            cause=error,
        )

    # Default fallback: treat unknown runtime errors as permanent to prevent infinite retries
    return STTPermanentError(
        message=f"Unclassified provider failure: {err_msg}",
        provider_name=provider_name,
        cause=error,
    )


def to_transcript_error_info(
    error: Exception,
    code_override: Optional[str] = None,
) -> TranscriptErrorInfo:
    """Convert an exception into a validated TranscriptErrorInfo payload.

    Args:
        error: The exception to convert.
        code_override: Optional explicit error code.

    Returns:
        TranscriptErrorInfo model instance suitable for TranscriptEvent.
    """
    if isinstance(error, STTTimeoutError):
        code = code_override or "STT_TIMEOUT"
    elif isinstance(error, STTTransientError):
        code = code_override or "STT_TRANSIENT_ERROR"
    elif isinstance(error, STTPermanentError):
        code = code_override or "STT_PERMANENT_ERROR"
    elif isinstance(error, STTInputError):
        code = code_override or "AUDIO_INPUT_INVALID"
    elif isinstance(error, STTPreprocessingError):
        code = code_override or "AUDIO_PREPROCESSING_FAILED"
    else:
        code = code_override or "STT_UNEXPECTED_ERROR"

    message = str(error).strip() or "An unexpected transcription error occurred."
    details: Dict[str, Any] = {
        "exception_type": type(error).__name__,
    }
    if hasattr(error, "details") and isinstance(error.details, dict):
        details.update(error.details)
    if hasattr(error, "provider_name"):
        details["provider_name"] = getattr(error, "provider_name")

    return TranscriptErrorInfo(
        code=code,
        message=message,
        details=details if details else None,
    )
