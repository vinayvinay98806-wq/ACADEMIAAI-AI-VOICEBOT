"""Unit and integration tests for request validation and payload limits (Day 10-11)."""

from fastapi.testclient import TestClient


def test_invalid_request_schema_returns_422(client: TestClient):
    """Verify invalid data types and out-of-range values return 422 with typed error envelope."""
    # Invalid ttl_seconds (string instead of integer)
    bad_payload = {"user_id": "alice", "ttl_seconds": "not-an-integer"}
    response = client.post("/api/v1/sessions", json=bad_payload)
    assert response.status_code == 422

    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert isinstance(body["error"]["details"], list)


def test_invalid_ttl_out_of_range_returns_422(client: TestClient):
    """Verify negative or zero TTL is rejected by Pydantic validation."""
    response = client.post("/api/v1/sessions", json={"ttl_seconds": 0})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_malformed_json_body_returns_422(client: TestClient):
    """Verify malformed JSON syntax is caught and wrapped in typed error envelope."""
    response = client.post(
        "/api/v1/sessions",
        content="this is not valid json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_oversized_payload_rejected_by_content_length(client: TestClient):
    """Verify payload with Content-Length exceeding max limit is rejected with 413."""
    headers = {
        "Content-Type": "application/json",
        "Content-Length": "10000000",  # 10MB > 1MB limit
    }
    response = client.post("/api/v1/sessions", content="{}", headers=headers)
    assert response.status_code == 413

    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert "exceeds maximum allowed size" in body["error"]["message"]
    assert "max_bytes" in body["error"]["details"]


def test_oversized_payload_rejected_by_body_size(client: TestClient):
    """Verify actual request body larger than 1MB is rejected with 413."""
    # Create payload slightly over 1MB (1,048,576 bytes)
    large_payload = {"user_id": "student-test", "metadata": {"blob": "x" * 1_100_000}}
    response = client.post("/api/v1/sessions", json=large_payload)
    assert response.status_code == 413

    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_unknown_session_handling_across_lifecycle_endpoints(client: TestClient):
    """Verify unknown session IDs return 404 with typed error envelope across all lifecycle endpoints."""
    endpoints = [
        ("GET", "/api/v1/sessions/unknown-sess-999"),
        ("POST", "/api/v1/sessions/unknown-sess-999/pause"),
        ("POST", "/api/v1/sessions/unknown-sess-999/resume"),
        ("POST", "/api/v1/sessions/unknown-sess-999/stop"),
        ("POST", "/api/v1/sessions/unknown-sess-999/expire"),
        ("GET", "/api/v1/sessions/unknown-sess-999/events"),
        ("POST", "/api/v1/sessions/unknown-sess-999/transition"),
    ]

    for method, path in endpoints:
        if method == "GET":
            res = client.get(path)
        else:
            res = client.post(path, json={"target_state": "active"} if "transition" in path else {})

        assert res.status_code == 404, f"Failed on {method} {path}"
        data = res.json()
        assert data["success"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        assert "unknown-sess-999" in data["error"]["message"]

