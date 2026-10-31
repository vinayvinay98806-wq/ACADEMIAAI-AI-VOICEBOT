"""Tests for Typed Error Envelope."""

from fastapi.testclient import TestClient


def test_404_typed_error_envelope(client: TestClient):
    """Verify missing endpoints return structured typed error envelope."""
    response = client.get("/nonexistent-endpoint-123")
    assert response.status_code == 404

    data = response.json()
    assert data["success"] is False
    assert "error" in data
    assert data["error"]["code"] == "NOT_FOUND"
    assert "message" in data["error"]
    assert "request_id" in data["error"]
    assert data["error"]["request_id"] is not None


def test_session_not_found_envelope(client: TestClient):
    """Verify session not found returns 404 with typed envelope."""
    response = client.get("/api/v1/sessions/mock-sess-does-not-exist")
    assert response.status_code == 404

    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "NOT_FOUND"
    assert "Session not found" in data["error"]["message"]
    assert data["error"]["details"]["session_id"] == "mock-sess-does-not-exist"


def test_422_validation_error_envelope(client: TestClient):
    """Verify invalid payloads return typed validation error envelope."""
    # Pass invalid state string to transition endpoint
    response = client.post(
        "/api/v1/sessions/any-id/transition",
        json={"target_state": "non-existent-state"},
    )
    assert response.status_code == 422

    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "VALIDATION_ERROR"
    assert "validation failed" in data["error"]["message"].lower()
    assert isinstance(data["error"]["details"], list)
    assert len(data["error"]["details"]) > 0
