"""Tests for Local Token Authorization and Sliding-Window Rate Limiting (W5 Week 3)."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.auth import constant_time_token_check
from app.core.rate_limit import InMemorySlidingWindowRateLimiter, get_rate_limiter
from app.main import create_app


def test_constant_time_token_check():
    """Verify constant-time token comparison logic."""
    assert constant_time_token_check("secret-key", "secret-key") is True
    assert constant_time_token_check("secret-key", "wrong-key") is False
    assert constant_time_token_check("", "secret-key") is False
    assert constant_time_token_check(None, "secret-key") is False
    assert constant_time_token_check("secret-key", None) is False


def test_auth_disabled_by_default(client: TestClient):
    """Verify that by default (mock mode), endpoints do not require authorization."""
    res = client.post("/api/v1/sessions")
    assert res.status_code == 201


def test_auth_missing_credentials_returns_401():
    """Verify 401 Unauthorized typed error when auth is enabled and token is missing."""
    settings = Settings(auth_enabled=True, auth_token="my-secure-token")
    app = create_app(settings=settings)

    with TestClient(app) as test_client:
        res = test_client.post("/api/v1/sessions")
        assert res.status_code == 401
        data = res.json()
        assert data["success"] is False
        assert data["error"]["code"] == "UNAUTHORIZED"
        assert "WWW-Authenticate" in res.headers


def test_auth_invalid_credentials_returns_403():
    """Verify 403 Forbidden typed error when auth is enabled and token is wrong."""
    settings = Settings(auth_enabled=True, auth_token="my-secure-token")
    app = create_app(settings=settings)

    with TestClient(app) as test_client:
        res = test_client.post(
            "/api/v1/sessions",
            headers={"Authorization": "Bearer completely-wrong-token"},
        )
        assert res.status_code == 403
        data = res.json()
        assert data["success"] is False
        assert data["error"]["code"] == "FORBIDDEN"


def test_auth_valid_bearer_token_succeeds():
    """Verify valid Bearer token grants access to protected endpoints."""
    settings = Settings(auth_enabled=True, auth_token="my-secure-token")
    app = create_app(settings=settings)

    with TestClient(app) as test_client:
        res = test_client.post(
            "/api/v1/sessions",
            headers={"Authorization": "Bearer my-secure-token"},
        )
        assert res.status_code == 201
        assert res.json()["success"] is True


def test_public_endpoints_bypass_auth():
    """Verify public health and docs endpoints bypass authorization checks."""
    settings = Settings(auth_enabled=True, auth_token="my-secure-token")
    app = create_app(settings=settings)

    with TestClient(app) as test_client:
        # Health liveness probe
        health_res = test_client.get("/health")
        assert health_res.status_code == 200

        # Readiness probe
        ready_res = test_client.get("/ready")
        assert ready_res.status_code == 200

        # OpenAPI schema
        docs_res = test_client.get("/openapi.json")
        assert docs_res.status_code == 200


def test_rate_limiting_enforcement_and_headers():
    """Verify sliding-window rate limiter returns 429 when threshold exceeded."""
    get_rate_limiter().clear()

    settings = Settings(
        rate_limit_enabled=True,
        rate_limit_requests=2,
        rate_limit_window_seconds=60,
    )
    app = create_app(settings=settings)

    with TestClient(app) as test_client:
        # Request 1: Allowed
        r1 = test_client.get("/api/v1/sessions")
        assert r1.status_code == 200
        assert r1.headers.get("X-RateLimit-Limit") == "2"
        assert r1.headers.get("X-RateLimit-Remaining") == "1"

        # Request 2: Allowed
        r2 = test_client.get("/api/v1/sessions")
        assert r2.status_code == 200
        assert r2.headers.get("X-RateLimit-Remaining") == "0"

        # Request 3: Blocked (429)
        r3 = test_client.get("/api/v1/sessions")
        assert r3.status_code == 429
        data = r3.json()
        assert data["success"] is False
        assert data["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert "Retry-After" in r3.headers


def test_rate_limiter_unit_sliding_window_reset():
    """Unit test sliding-window rate limiter with deterministic time progression."""
    simulated_time = 100.0

    def mock_clock() -> float:
        return simulated_time

    limiter = InMemorySlidingWindowRateLimiter(
        max_requests=2,
        window_seconds=10,
        clock_fn=mock_clock,
    )

    client_key = "192.168.1.1"

    # Request 1 at t=100.0
    allowed, rem, reset, retry = limiter.check_rate_limit(client_key)
    assert allowed is True
    assert rem == 1

    # Request 2 at t=102.0
    simulated_time = 102.0
    allowed, rem, reset, retry = limiter.check_rate_limit(client_key)
    assert allowed is True
    assert rem == 0

    # Request 3 at t=105.0 -> blocked!
    simulated_time = 105.0
    allowed, rem, reset, retry = limiter.check_rate_limit(client_key)
    assert allowed is False
    assert rem == 0
    assert retry > 0

    # Advance time past window (t=111.0: Request 1 from t=100 has expired)
    simulated_time = 111.0
    allowed, rem, reset, retry = limiter.check_rate_limit(client_key)
    assert allowed is True
    assert rem == 0  # 1 consumed from (102, 111)


def test_rate_limiter_client_isolation():
    """Verify distinct clients have isolated rate limit buckets."""
    limiter = InMemorySlidingWindowRateLimiter(max_requests=1, window_seconds=60)

    # Client A consumes quota
    allowed_a1, _, _, _ = limiter.check_rate_limit("client_A")
    assert allowed_a1 is True
    allowed_a2, _, _, _ = limiter.check_rate_limit("client_A")
    assert allowed_a2 is False

    # Client B should still have full quota
    allowed_b1, _, _, _ = limiter.check_rate_limit("client_B")
    assert allowed_b1 is True
