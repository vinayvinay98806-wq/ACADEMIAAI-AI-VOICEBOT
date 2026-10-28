"""Tests for health and readiness endpoints."""

from fastapi.testclient import TestClient


def test_health_check_returns_ok(client: TestClient):
    """Verify /health returns 200 with healthy status and mock mode."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data
    assert data["service"] == "Academiaai AI Voicebot Backend"
    assert data["mode"] == "mock"
    assert data["version"] == "0.1.0"


def test_readiness_check_returns_ready(client: TestClient):
    """Verify /ready reports readiness of dependencies."""
    response = client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert "dependencies" in data
    assert data["dependencies"]["session_repository"] == "ready"
    assert data["dependencies"]["mock_provider"] == "ready"


def test_versioned_health_and_readiness(client: TestClient):
    """Verify health and ready endpoints under /api/v1 prefix."""
    res_health = client.get("/api/v1/health")
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "healthy"

    res_ready = client.get("/api/v1/ready")
    assert res_ready.status_code == 200
    assert res_ready.json()["status"] == "ready"
