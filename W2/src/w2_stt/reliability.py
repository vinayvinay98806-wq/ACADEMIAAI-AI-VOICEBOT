"""Reliability, retry logic, and timeout enforcement for Workstream W2: Speech-to-Text.

This module provides configurable retry policies and execution wrappers to guarantee
resilience against transient provider failures, connection timeouts, and rate limits
without risking infinite loops or state corruption.
"""

from __future__ import annotations

import concurrent.futures
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, TypeVar

from w2_stt.exceptions import (
    STTConfigurationError,
    STTProviderError,
    STTTimeoutError,
    STTTransientError,
    normalize_provider_error,
)

T = TypeVar("T")


@dataclass(frozen=True)
class RetryConfig:
    """Configuration options for timeout enforcement and bounded retries.

    Attributes:
        max_retries: Maximum number of retry attempts after the initial call (>= 0).
        initial_backoff_seconds: Delay before first retry in seconds (>= 0.0).
        max_backoff_seconds: Upper ceiling on backoff delay (>= initial_backoff_seconds).
        backoff_multiplier: Exponential multiplier applied to backoff delay (>= 1.0).
        timeout_seconds: Hard timeout per operation attempt in seconds (None for no timeout).
        retry_on_transient_only: If True, only STTTransientError / timeouts are retried.
    """

    max_retries: int = 3
    initial_backoff_seconds: float = 0.05
    max_backoff_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    timeout_seconds: Optional[float] = 5.0
    retry_on_transient_only: bool = True

    def __post_init__(self) -> None:
        """Validate configuration parameters strictly."""
        if not isinstance(self.max_retries, int) or isinstance(self.max_retries, bool) or self.max_retries < 0:
            raise STTConfigurationError(
                f"max_retries must be a non-negative integer, got {self.max_retries!r}"
            )
        if not isinstance(self.initial_backoff_seconds, (int, float)) or self.initial_backoff_seconds < 0.0:
            raise STTConfigurationError(
                f"initial_backoff_seconds must be non-negative, got {self.initial_backoff_seconds!r}"
            )
        if not isinstance(self.max_backoff_seconds, (int, float)) or self.max_backoff_seconds < self.initial_backoff_seconds:
            raise STTConfigurationError(
                f"max_backoff_seconds ({self.max_backoff_seconds!r}) must be >= initial_backoff_seconds ({self.initial_backoff_seconds!r})"
            )
        if not isinstance(self.backoff_multiplier, (int, float)) or self.backoff_multiplier < 1.0:
            raise STTConfigurationError(
                f"backoff_multiplier must be >= 1.0, got {self.backoff_multiplier!r}"
            )
        if self.timeout_seconds is not None:
            if not isinstance(self.timeout_seconds, (int, float)) or self.timeout_seconds <= 0.0:
                raise STTConfigurationError(
                    f"timeout_seconds must be positive if specified, got {self.timeout_seconds!r}"
                )


def execute_with_retry(
    operation: Callable[[], T],
    config: Optional[RetryConfig] = None,
    provider_name: str = "UnknownProvider",
    sleep_func: Callable[[float], None] = time.sleep,
) -> T:
    """Execute a callable with timeout protection and bounded exponential retries.

    Args:
        operation: The zero-argument callable to invoke.
        config: Retry and timeout configuration (defaults to standard RetryConfig()).
        provider_name: Name of the underlying provider for diagnostics.
        sleep_func: Sleep function invoked between retries (can be mocked for instant testing).

    Returns:
        The result returned by `operation`.

    Raises:
        STTProviderError: When retries are exhausted or a non-retryable error occurs.
    """
    cfg = config or RetryConfig()
    attempt = 0
    last_error: Optional[STTProviderError] = None

    while True:
        try:
            # 1. Execute operation with optional timeout
            if cfg.timeout_seconds is not None:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(operation)
                    try:
                        return future.result(timeout=cfg.timeout_seconds)
                    except concurrent.futures.TimeoutError as timeout_exc:
                        raise STTTimeoutError(
                            message=f"Operation timed out after {cfg.timeout_seconds:.2f}s",
                            provider_name=provider_name,
                            timeout_seconds=cfg.timeout_seconds,
                            cause=timeout_exc,
                        ) from timeout_exc
            else:
                return operation()

        except Exception as exc:
            # 2. Normalize caught exception
            normalized = normalize_provider_error(exc, provider_name=provider_name)
            last_error = normalized

            # 3. Check retry eligibility
            can_retry = (not cfg.retry_on_transient_only) or normalized.is_transient
            if not can_retry or attempt >= cfg.max_retries:
                # Re-raise normalized error, preserving cause and details
                raise normalized

            # 4. Calculate backoff delay and sleep
            backoff = min(
                cfg.max_backoff_seconds,
                cfg.initial_backoff_seconds * (cfg.backoff_multiplier ** attempt),
            )
            attempt += 1
            sleep_func(backoff)
