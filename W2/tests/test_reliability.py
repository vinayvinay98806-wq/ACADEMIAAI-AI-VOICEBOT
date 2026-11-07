"""Unit and contract tests for STT Reliability, Timeouts, and Error Normalization."""

import socket
import time
import unittest
from typing import Any, List

from w2_stt.exceptions import (
    STTConfigurationError,
    STTPermanentError,
    STTProviderError,
    STTTimeoutError,
    STTTransientError,
    normalize_provider_error,
    to_transcript_error_info,
)
from w2_stt.reliability import RetryConfig, execute_with_retry


class TestReliabilityAndErrorHandling(unittest.TestCase):
    """Validation suite for retry logic, timeout enforcement, and error normalization."""

    # -------------------------------------------------------------------------
    # Configuration Validation Tests
    # -------------------------------------------------------------------------

    def test_valid_retry_config(self) -> None:
        """Verify default and customized valid RetryConfig."""
        cfg = RetryConfig(
            max_retries=5,
            initial_backoff_seconds=0.1,
            max_backoff_seconds=2.0,
            backoff_multiplier=1.5,
            timeout_seconds=3.0,
        )
        self.assertEqual(cfg.max_retries, 5)
        self.assertEqual(cfg.initial_backoff_seconds, 0.1)
        self.assertEqual(cfg.max_backoff_seconds, 2.0)
        self.assertEqual(cfg.backoff_multiplier, 1.5)
        self.assertEqual(cfg.timeout_seconds, 3.0)

    def test_invalid_max_retries_rejected(self) -> None:
        """Negative max_retries must raise STTConfigurationError."""
        with self.assertRaises(STTConfigurationError):
            RetryConfig(max_retries=-1)

    def test_invalid_initial_backoff_rejected(self) -> None:
        """Negative initial backoff must raise STTConfigurationError."""
        with self.assertRaises(STTConfigurationError):
            RetryConfig(initial_backoff_seconds=-0.5)

    def test_invalid_max_backoff_less_than_initial_rejected(self) -> None:
        """max_backoff < initial_backoff must raise STTConfigurationError."""
        with self.assertRaises(STTConfigurationError):
            RetryConfig(initial_backoff_seconds=2.0, max_backoff_seconds=1.0)

    def test_invalid_backoff_multiplier_rejected(self) -> None:
        """backoff_multiplier < 1.0 must raise STTConfigurationError."""
        with self.assertRaises(STTConfigurationError):
            RetryConfig(backoff_multiplier=0.8)

    def test_invalid_timeout_rejected(self) -> None:
        """timeout_seconds <= 0 must raise STTConfigurationError."""
        with self.assertRaises(STTConfigurationError):
            RetryConfig(timeout_seconds=0.0)
        with self.assertRaises(STTConfigurationError):
            RetryConfig(timeout_seconds=-2.0)

    # -------------------------------------------------------------------------
    # Error Normalization Tests
    # -------------------------------------------------------------------------

    def test_normalize_timeout_error(self) -> None:
        """Timeout exceptions should normalize into STTTimeoutError (transient)."""
        err = socket.timeout("Socket read timed out")
        norm = normalize_provider_error(err, provider_name="MockEngine")
        self.assertIsInstance(norm, STTTimeoutError)
        self.assertTrue(norm.is_transient)
        self.assertEqual(norm.provider_name, "MockEngine")
        self.assertIs(norm.cause, err)

    def test_normalize_transient_connection_and_rate_limit(self) -> None:
        """Connection resets and rate limit errors must normalize to STTTransientError."""
        # Connection reset
        err1 = ConnectionResetError("Remote server dropped connection")
        norm1 = normalize_provider_error(err1, provider_name="EngineA")
        self.assertIsInstance(norm1, STTTransientError)
        self.assertTrue(norm1.is_transient)

        # 429 rate limit in message
        err2 = RuntimeError("HTTP 429 Too Many Requests: Rate limit exceeded")
        norm2 = normalize_provider_error(err2, provider_name="EngineB")
        self.assertIsInstance(norm2, STTTransientError)
        self.assertTrue(norm2.is_transient)

    def test_normalize_permanent_auth_and_bad_request(self) -> None:
        """Auth and permission errors must normalize to STTPermanentError (non-transient)."""
        err1 = PermissionError("401 Unauthorized: Invalid API key")
        norm1 = normalize_provider_error(err1, provider_name="EngineC")
        self.assertIsInstance(norm1, STTPermanentError)
        self.assertFalse(norm1.is_transient)

        err2 = ValueError("HTTP 400 Bad Request: Unsupported audio encoding")
        norm2 = normalize_provider_error(err2, provider_name="EngineD")
        self.assertIsInstance(norm2, STTPermanentError)
        self.assertFalse(norm2.is_transient)

    def test_to_transcript_error_info_payload(self) -> None:
        """Verify transformation of exceptions into validated TranscriptErrorInfo schemas."""
        timeout_err = STTTimeoutError("Provider query timed out", provider_name="FastSTT", timeout_seconds=2.5)
        info = to_transcript_error_info(timeout_err)
        self.assertEqual(info.code, "STT_TIMEOUT")
        self.assertIn("timed out", info.message)
        self.assertEqual(info.details.get("provider_name"), "FastSTT")
        self.assertEqual(info.details.get("timeout_seconds"), 2.5)

    # -------------------------------------------------------------------------
    # Retry Execution Tests
    # -------------------------------------------------------------------------

    def test_execute_with_retry_immediate_success(self) -> None:
        """Zero retries needed when operation succeeds on first try."""
        call_count = 0

        def operation() -> str:
            nonlocal call_count
            call_count += 1
            return "SUCCESS"

        result = execute_with_retry(operation, RetryConfig(max_retries=3))
        self.assertEqual(result, "SUCCESS")
        self.assertEqual(call_count, 1)

    def test_execute_with_retry_recovers_after_transient_failure(self) -> None:
        """Transient errors are retried up to limit and succeed upon recovery."""
        call_count = 0
        sleep_durations: List[float] = []

        def mock_sleep(d: float) -> None:
            sleep_durations.append(d)

        def failing_operation() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionResetError("Transient network drop")
            return "RECOVERED"

        cfg = RetryConfig(
            max_retries=3,
            initial_backoff_seconds=0.1,
            backoff_multiplier=2.0,
            max_backoff_seconds=1.0,
        )
        result = execute_with_retry(
            failing_operation,
            config=cfg,
            sleep_func=mock_sleep,
        )

        self.assertEqual(result, "RECOVERED")
        self.assertEqual(call_count, 3)
        self.assertEqual(len(sleep_durations), 2)
        # Verify exponential backoff: 0.1, 0.2
        self.assertAlmostEqual(sleep_durations[0], 0.1, places=3)
        self.assertAlmostEqual(sleep_durations[1], 0.2, places=3)

    def test_execute_with_retry_limit_enforced(self) -> None:
        """When transient errors exceed max_retries, normalized error is raised."""
        call_count = 0
        sleep_durations: List[float] = []

        def perpetually_failing_operation() -> None:
            nonlocal call_count
            call_count += 1
            raise STTTransientError("Server temporarily overloaded (503)")

        cfg = RetryConfig(max_retries=2, initial_backoff_seconds=0.01)
        with self.assertRaises(STTTransientError) as ctx:
            execute_with_retry(
                perpetually_failing_operation,
                config=cfg,
                sleep_func=lambda d: sleep_durations.append(d),
            )

        self.assertEqual(call_count, 3)  # Initial attempt + 2 retries
        self.assertEqual(len(sleep_durations), 2)
        self.assertIn("503", str(ctx.exception))

    def test_execute_with_retry_permanent_error_not_retried(self) -> None:
        """Permanent errors fail immediately on attempt 0 without retrying."""
        call_count = 0
        sleep_durations: List[float] = []

        def fatal_operation() -> None:
            nonlocal call_count
            call_count += 1
            raise PermissionError("401 Unauthorized: Invalid API Token")

        cfg = RetryConfig(max_retries=5, initial_backoff_seconds=0.01)
        with self.assertRaises(STTPermanentError) as ctx:
            execute_with_retry(
                fatal_operation,
                config=cfg,
                sleep_func=lambda d: sleep_durations.append(d),
            )

        self.assertEqual(call_count, 1)  # No retries executed!
        self.assertEqual(len(sleep_durations), 0)
        self.assertFalse(ctx.exception.is_transient)

    def test_execute_with_retry_timeout_enforcement(self) -> None:
        """Operations taking longer than timeout_seconds raise STTTimeoutError."""
        def slow_operation() -> str:
            time.sleep(0.3)
            return "TOO_LATE"

        cfg = RetryConfig(max_retries=1, timeout_seconds=0.05, initial_backoff_seconds=0.01)
        with self.assertRaises(STTTimeoutError) as ctx:
            execute_with_retry(
                slow_operation,
                config=cfg,
                sleep_func=lambda d: None,
            )

        self.assertTrue(ctx.exception.is_transient)
        self.assertIn("timed out", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
