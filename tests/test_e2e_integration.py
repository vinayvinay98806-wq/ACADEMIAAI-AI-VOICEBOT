"""Comprehensive 14-point End-to-End Integration Test for W5 Week 3."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.rate_limit import get_rate_limiter
from app.gateways.factory import get_audio_gateway, get_reasoning_gateway
from app.main import create_app
from app.repositories.in_memory_session import get_session_repository


def test_w5_week3_complete_e2e_lifecycle():
    """Execute the full 14-point end-to-end integration scenario."""
    get_rate_limiter().clear()
    # Configure app with auth and rate limiting
    settings = Settings(
        auth_enabled=True,
        auth_token="integration-secret-key",
        rate_limit_enabled=True,
        rate_limit_requests=20,
        rate_limit_window_seconds=60,
    )
    app = create_app(settings=settings)

    with TestClient(app) as client:
        auth_headers = {"Authorization": "Bearer integration-secret-key"}

        # --------------------------------------------------------------------
        # 1. Startup & Health Checks (Public, bypassed auth)
        # --------------------------------------------------------------------
        health_res = client.get("/health")
        assert health_res.status_code == 200
        assert health_res.json()["status"] == "healthy"

        ready_res = client.get("/ready")
        assert ready_res.status_code == 200
        assert ready_res.json()["status"] == "ready"

        # --------------------------------------------------------------------
        # 2. Authorization Enforcement: Missing and Invalid Token Rejection
        # --------------------------------------------------------------------
        # Missing token -> 401
        unauth_res = client.post("/api/v1/sessions")
        assert unauth_res.status_code == 401
        assert unauth_res.json()["error"]["code"] == "UNAUTHORIZED"

        # Invalid token -> 403
        forbidden_res = client.post(
            "/api/v1/sessions",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert forbidden_res.status_code == 403
        assert forbidden_res.json()["error"]["code"] == "FORBIDDEN"

        # --------------------------------------------------------------------
        # 3. Authenticated Session Creation
        # --------------------------------------------------------------------
        custom_corr_id = "corr-integration-test-001"
        create_res = client.post(
            "/api/v1/sessions",
            headers={**auth_headers, "X-Correlation-ID": custom_corr_id},
        )
        assert create_res.status_code == 201
        session_data = create_res.json()["data"]["session"]
        session_id = session_data["session_id"]
        assert session_data["state"] == "active"
        assert create_res.headers.get("X-Correlation-ID") == custom_corr_id

        # --------------------------------------------------------------------
        # 4. First Interaction: Audio -> STT -> Reasoning -> Workflow
        # --------------------------------------------------------------------
        interact_1 = client.post(
            f"/api/v1/sessions/{session_id}/interact",
            headers={**auth_headers, "X-Correlation-ID": custom_corr_id},
            json={"user_query": "What is the CS-101 syllabus and prerequisites?"},
        )
        assert interact_1.status_code == 200
        i1_data = interact_1.json()
        assert i1_data["success"] is True
        assert i1_data["transcript"]["text"] == "What is the CS-101 syllabus and prerequisites?"
        assert i1_data["reasoning"]["intent"] == "explain_concept"
        assert i1_data["workflow"]["status"] == "succeeded"
        assert len(i1_data["events_emitted"]) >= 4

        # --------------------------------------------------------------------
        # 5. Monotonic Sequence Numbers & Event Persistence
        # --------------------------------------------------------------------
        events_res = client.get(
            f"/api/v1/sessions/{session_id}/events",
            headers=auth_headers,
        )
        assert events_res.status_code == 200
        events = events_res.json()["events"]
        # session.started + at least 4 gateway events = 5
        assert len(events) >= 5
        # Verify sequence numbers are 1, 2, 3, ...
        seq_nums = [e["sequence_number"] for e in events]
        assert seq_nums == list(range(1, len(events) + 1))

        # Check correlation ID propagation in event payload
        for evt in events:
            assert evt["session_id"] == session_id
            if evt["event_type"].startswith("gateway."):
                assert evt["payload"]["correlation_id"] == custom_corr_id

        # --------------------------------------------------------------------
        # 6. SSE Connection and Initial Replay
        # --------------------------------------------------------------------
        sse_initial = client.get(
            f"/api/v1/sessions/{session_id}/events/stream?follow=false",
            headers=auth_headers,
        )
        assert sse_initial.status_code == 200
        body_initial = sse_initial.text
        assert f": connected to session {session_id}" in body_initial
        for evt in events:
            assert f"id: {evt['event_id']}" in body_initial

        # --------------------------------------------------------------------
        # 7. Disconnect Simulation & Out-of-Band Interaction
        # --------------------------------------------------------------------
        # Client disconnects. System receives a second interaction:
        interact_2 = client.post(
            f"/api/v1/sessions/{session_id}/interact",
            headers={**auth_headers, "X-Correlation-ID": custom_corr_id},
            json={"user_query": "Give me practice question 1."},
        )
        assert interact_2.status_code == 200

        # --------------------------------------------------------------------
        # 8. Reconnect with Last-Event-ID & Strict Replay
        # --------------------------------------------------------------------
        last_seen_event_id = events[-1]["event_id"]
        reconnect_res = client.get(
            f"/api/v1/sessions/{session_id}/events/stream?follow=false",
            headers={**auth_headers, "Last-Event-ID": last_seen_event_id},
        )
        assert reconnect_res.status_code == 200
        body_reconnect = reconnect_res.text

        # Old events must not be redelivered
        assert f"id: {events[0]['event_id']}" not in body_reconnect
        assert f"id: {last_seen_event_id}" not in body_reconnect

        # New events from second interaction must be present
        new_events_res = client.get(
            f"/api/v1/sessions/{session_id}/events?since_id={last_seen_event_id}",
            headers=auth_headers,
        )
        new_events = new_events_res.json()["events"]
        assert len(new_events) >= 4
        for new_evt in new_events:
            assert f"id: {new_evt['event_id']}" in body_reconnect

        # --------------------------------------------------------------------
        # 9. Session Lifecycle Transitions (Pause -> Resume -> Stop)
        # --------------------------------------------------------------------
        pause_res = client.post(f"/api/v1/sessions/{session_id}/pause", headers=auth_headers)
        assert pause_res.status_code == 200
        assert pause_res.json()["data"]["state"] == "paused"

        resume_res = client.post(f"/api/v1/sessions/{session_id}/resume", headers=auth_headers)
        assert resume_res.status_code == 200
        assert resume_res.json()["data"]["state"] == "active"

        stop_res = client.post(f"/api/v1/sessions/{session_id}/stop", headers=auth_headers)
        assert stop_res.status_code == 200
        assert stop_res.json()["data"]["state"] == "completed"

        # --------------------------------------------------------------------
        # 10. Terminal State Prevents Further Interactions
        # --------------------------------------------------------------------
        stopped_interact = client.post(
            f"/api/v1/sessions/{session_id}/interact",
            headers=auth_headers,
            json={"user_query": "Can I ask more?"},
        )
        assert stopped_interact.status_code == 409  # InvalidStateTransitionError

        # --------------------------------------------------------------------
        # 11. Terminal State Stream Emits Session Ended
        # --------------------------------------------------------------------
        terminal_stream = client.get(
            f"/api/v1/sessions/{session_id}/events/stream?follow=false",
            headers=auth_headers,
        )
        assert ": session ended" in terminal_stream.text

        # --------------------------------------------------------------------
        # 12. Rate Limiting Enforced Under Rapid Load
        # --------------------------------------------------------------------
        # Quota is 20 per minute. Send 25 quick queries:
        hit_429 = False
        for i in range(25):
            r = client.get("/api/v1/sessions", headers=auth_headers)
            if r.status_code == 429:
                hit_429 = True
                assert "Retry-After" in r.headers
                assert r.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
                break
        assert hit_429 is True

        # --------------------------------------------------------------------
        # 13. Degraded Component Aggregated Health Reporting
        # --------------------------------------------------------------------
        reasoning_gw = get_reasoning_gateway()
        try:
            reasoning_gw.set_healthy(False)
            agg_health = client.get("/ready")
            assert agg_health.status_code == 200
            assert agg_health.json()["status"] == "degraded"
            assert agg_health.json()["dependencies"]["reasoning_gateway"] == "degraded"
        finally:
            reasoning_gw.set_healthy(True)

        # --------------------------------------------------------------------
        # 14. Repository Cleanup and State Reset
        # --------------------------------------------------------------------
        repo = get_session_repository()
        # Verify repository holds session data cleanly
        assert session_id in repo._sessions
