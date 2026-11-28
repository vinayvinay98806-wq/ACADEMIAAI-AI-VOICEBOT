"""Tests for Aggregated Health Probes and Gateway Diagnostics (W5 Week 3)."""

import pytest
from fastapi.testclient import TestClient

from app.gateways.factory import (
    get_audio_gateway,
    get_transcription_gateway,
    get_reasoning_gateway,
    get_workflow_gateway,
)
from app.main import create_app


def test_health_liveness_probe(client: TestClient):
    """Verify /health returns 200 and healthy status immediately."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data
    assert "version" in data


def test_ready_aggregated_all_healthy(client: TestClient):
    """Verify /ready aggregates repository, mock provider, and all 4 module gateways."""
    # Ensure all mock adapters are healthy
    get_audio_gateway().set_healthy(True)
    get_transcription_gateway().set_healthy(True)
    get_reasoning_gateway().set_healthy(True)
    get_workflow_gateway().set_healthy(True)

    res = client.get("/ready")
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "ready"
    deps = data["dependencies"]

    # Week 1 & 2 baseline contracts
    assert deps["session_repository"] == "ready"
    assert deps["mock_provider"] == "ready"

    # Week 3 gateway contracts
    assert deps["audio_gateway"] == "ready"
    assert deps["transcription_gateway"] == "ready"
    assert deps["reasoning_gateway"] == "ready"
    assert deps["workflow_gateway"] == "ready"
    assert deps["event_stream"] == "ready"


def test_ready_degraded_when_gateway_unhealthy(client: TestClient):
    """Verify /ready reports degraded status when one gateway is degraded, without crashing."""
    reasoning_gw = get_reasoning_gateway()
    try:
        # Mark reasoning gateway as unhealthy
        reasoning_gw.set_healthy(False)

        res = client.get("/ready")
        assert res.status_code == 200
        data = res.json()

        assert data["status"] == "degraded"
        assert data["dependencies"]["reasoning_gateway"] == "degraded"
        # Other dependencies still report healthy
        assert data["dependencies"]["session_repository"] == "ready"
        assert data["dependencies"]["audio_gateway"] == "ready"
    finally:
        # Restore health
        reasoning_gw.set_healthy(True)


def test_health_aggregated_diagnostic_details(client: TestClient):
    """Verify /api/v1/health/aggregated returns comprehensive diagnostics for all modules."""
    res = client.get("/api/v1/health/aggregated")
    assert res.status_code == 200
    data = res.json()

    assert data["status"] in ("ready", "degraded")
    assert "summary" in data
    assert "components" in data

    components = data["components"]
    assert "W1_Audio" in components
    assert "W2_STT" in components
    assert "W3_ContextReasoning" in components
    assert "W4_Workflow" in components
    assert "SessionRepository" in components

    # Verify component metadata structure
    audio_info = components["W1_Audio"]
    assert audio_info["status"] in ("ready", "healthy")
    assert "adapter_type" in audio_info
    assert "latency_ms" in audio_info
