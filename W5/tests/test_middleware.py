"""Tests for Request and Correlation ID middleware."""

from fastapi.testclient import TestClient


def test_generates_request_and_correlation_ids_when_missing(client: TestClient):
    """Ensure middleware generates IDs and returns them in headers."""
    response = client.get("/health")
    assert response.status_code == 200

    assert "X-Request-ID" in response.headers
    assert "X-Correlation-ID" in response.headers

    req_id = response.headers["X-Request-ID"]
    corr_id = response.headers["X-Correlation-ID"]

    assert req_id.startswith("req-")
    assert corr_id == req_id


def test_preserves_valid_incoming_request_id(client: TestClient):
    """Ensure valid client-supplied X-Request-ID is preserved."""
    custom_id = "client-req-abc-12345"
    response = client.get("/health", headers={"X-Request-ID": custom_id})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == custom_id
    assert response.headers["X-Correlation-ID"] == custom_id


def test_preserves_valid_incoming_correlation_id(client: TestClient):
    """Ensure valid client-supplied X-Correlation-ID is preserved separately."""
    custom_req = "client-req-111"
    custom_corr = "client-corr-999"
    response = client.get(
        "/health",
        headers={
            "X-Request-ID": custom_req,
            "X-Correlation-ID": custom_corr,
        },
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == custom_req
    assert response.headers["X-Correlation-ID"] == custom_corr


def test_sanitizes_malformed_incoming_ids(client: TestClient):
    """Ensure malicious or malformed IDs with spaces/special characters are replaced safely."""
    malformed_id = "malicious<script>alert(1)</script> \r\n injection"
    response = client.get("/health", headers={"X-Request-ID": malformed_id})

    assert response.status_code == 200
    safe_id = response.headers["X-Request-ID"]
    assert safe_id.startswith("req-")
    assert "<script>" not in safe_id


def test_handles_excessively_long_ids(client: TestClient):
    """Ensure headers exceeding max length are replaced with generated safe IDs."""
    long_id = "A" * 300
    response = client.get("/health", headers={"X-Request-ID": long_id})

    assert response.status_code == 200
    safe_id = response.headers["X-Request-ID"]
    assert safe_id.startswith("req-")
    assert len(safe_id) < 100
