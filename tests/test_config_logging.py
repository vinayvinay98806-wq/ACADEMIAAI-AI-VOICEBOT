"""Unit tests for configuration validation, correlation-ID, and structured logging (Day 12-13)."""

import json
import logging
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.exceptions import ConfigurationError
from app.core.logging import JSONLogFormatter, RequestContextFilter, correlation_id_ctx, request_id_ctx, session_id_ctx


def test_startup_configuration_mock_mode_defaults():
    """Verify application starts safely in mock mode without external AI keys."""
    settings = Settings(mock_mode=True, ai_service_api_key=None, database_url=None)
    # Should not raise
    settings.validate_startup_configuration()
    assert settings.mock_mode is True


def test_startup_configuration_fails_in_production_without_credentials():
    """Verify production startup fails safely when required credentials are missing."""
    settings = Settings(mock_mode=False, ai_service_api_key=None, database_url=None)
    with pytest.raises(ConfigurationError) as exc_info:
        settings.validate_startup_configuration()
    assert "Production startup failed" in str(exc_info.value)
    assert "ai_service_api_key" in exc_info.value.details["missing_fields"]


def test_startup_configuration_fails_on_invalid_bounds():
    """Verify configuration validation rejects invalid port or TTL values."""
    with pytest.raises(Exception):
        Settings(session_ttl_seconds=-10)

    with pytest.raises(Exception):
        Settings(max_payload_size_bytes=0)


def test_startup_configuration_succeeds_in_production_with_valid_credentials():
    """Verify production startup succeeds when required credentials are provided."""
    settings = Settings(
        mock_mode=False,
        ai_service_api_key="real-prod-api-key-12345",
        database_url="postgresql://user:pass@localhost:5432/voicebot",
    )
    # Should succeed without error
    settings.validate_startup_configuration()


def test_safe_dict_masks_secrets():
    """Verify sensitive keys are masked in safe dictionary output."""
    settings = Settings(
        ai_service_api_key="sk-live-secret-key-12345678",
        database_url="postgresql://admin:secret@db.internal:5432/db",
    )
    safe = settings.safe_dict()
    assert safe["ai_service_api_key"] != "sk-live-secret-key-12345678"
    assert "sk-" in safe["ai_service_api_key"]
    assert "***" in safe["ai_service_api_key"] or "..." in safe["ai_service_api_key"]


def test_sensitive_data_sanitization_in_log_messages():
    """Verify logging filter redacts passwords, tokens, and API keys."""
    raw_msg = "Failed login for user admin with password=super_secret_pass and api_key=abc12345678"
    sanitized = RequestContextFilter.sanitize_sensitive_data(raw_msg)
    assert "super_secret_pass" not in sanitized
    assert "abc12345678" not in sanitized
    assert "***REDACTED***" in sanitized


def test_json_log_formatter_outputs_valid_json():
    """Verify JSON log formatter outputs structured JSON with all tracking IDs."""
    formatter = JSONLogFormatter()
    record = logging.LogRecord(
        name="academiaai.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Test structured log event",
        args=(),
        exc_info=None,
    )
    record.request_id = "req-12345"
    record.correlation_id = "corr-99999"
    record.session_id = "sess-88888"

    formatted = formatter.format(record)
    parsed = json.loads(formatted)

    assert parsed["logger"] == "academiaai.test"
    assert parsed["level"] == "INFO"
    assert parsed["message"] == "Test structured log event"
    assert parsed["request_id"] == "req-12345"
    assert parsed["correlation_id"] == "corr-99999"
    assert parsed["session_id"] == "sess-88888"
    assert "timestamp" in parsed


def test_correlation_id_propagation_across_lifecycle(client: TestClient):
    """Verify custom X-Request-ID and X-Correlation-ID are preserved across lifecycle requests."""
    custom_headers = {
        "X-Request-ID": "test-req-abc-123",
        "X-Correlation-ID": "test-corr-xyz-789",
    }
    # Create
    create_res = client.post("/api/v1/sessions", headers=custom_headers)
    assert create_res.status_code == 201
    assert create_res.headers.get("X-Request-ID") == "test-req-abc-123"
    assert create_res.headers.get("X-Correlation-ID") == "test-corr-xyz-789"

    sess_id = create_res.json()["data"]["session"]["session_id"]

    # Pause with same correlation ID, different request ID
    pause_headers = {
        "X-Request-ID": "test-req-abc-456",
        "X-Correlation-ID": "test-corr-xyz-789",
    }
    pause_res = client.post(f"/api/v1/sessions/{sess_id}/pause", headers=pause_headers)
    assert pause_res.status_code == 200
    assert pause_res.headers.get("X-Request-ID") == "test-req-abc-456"
    assert pause_res.headers.get("X-Correlation-ID") == "test-corr-xyz-789"
