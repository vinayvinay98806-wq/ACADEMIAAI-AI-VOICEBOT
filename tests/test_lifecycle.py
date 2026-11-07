"""Unit and integration tests for complete session lifecycle (Day 8-9)."""

import time
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from app.models.session import SessionState
from app.repositories.in_memory_session import get_session_repository


def test_session_creation_default(client: TestClient):
    """Verify standard session creation with default anonymous user and TTL."""
    response = client.post("/api/v1/sessions")
    assert response.status_code == 201

    body = response.json()
    assert body["success"] is True
    session = body["data"]["session"]
    assert session["session_id"].startswith("sess-")
    assert session["state"] == "active"
    assert session["user_id"] == "anonymous-user"
    assert "expires_at" in session
    assert session["expires_at"] is not None

    event = body["data"]["event"]
    assert event["event_type"] == "session.started"
    assert event["session_id"] == session["session_id"]
    assert "expires_at" in event["payload"]


def test_session_creation_custom(client: TestClient):
    """Verify session creation with custom user ID, metadata, and TTL."""
    payload = {
        "user_id": "student-alice",
        "metadata": {"subject": "Physics", "grade": "11"},
        "ttl_seconds": 600,
    }
    response = client.post("/api/v1/sessions", json=payload)
    assert response.status_code == 201

    session = response.json()["data"]["session"]
    assert session["user_id"] == "student-alice"
    assert session["metadata"]["subject"] == "Physics"
    assert session["metadata"]["grade"] == "11"


def test_session_pause_and_resume_lifecycle(client: TestClient):
    """Verify successful pause and resume with state transitions and timestamps."""
    # 1. Create session (starts ACTIVE)
    create_res = client.post("/api/v1/sessions")
    sess_id = create_res.json()["data"]["session"]["session_id"]

    # 2. Pause session
    pause_res = client.post(
        f"/api/v1/sessions/{sess_id}/pause",
        json={"reason": "User took a break"},
    )
    assert pause_res.status_code == 200
    pause_data = pause_res.json()
    assert pause_data["success"] is True
    assert pause_data["data"]["state"] == "paused"
    assert pause_data["data"]["metadata"]["pause_reason"] == "User took a break"
    assert "paused_at" in pause_data["data"]["metadata"]
    assert pause_data["event"]["event_type"] == "session.paused"
    assert pause_data["event"]["payload"]["reason"] == "User took a break"

    # 3. Resume session
    resume_res = client.post(
        f"/api/v1/sessions/{sess_id}/resume",
        json={"reason": "User resumed interaction"},
    )
    assert resume_res.status_code == 200
    resume_data = resume_res.json()
    assert resume_data["success"] is True
    assert resume_data["data"]["state"] == "active"
    assert resume_data["data"]["metadata"]["resume_reason"] == "User resumed interaction"
    assert "resumed_at" in resume_data["data"]["metadata"]
    assert resume_data["event"]["event_type"] == "session.resumed"


def test_session_stop_lifecycle(client: TestClient):
    """Verify successful stop/complete lifecycle and terminal ended_at timestamp."""
    create_res = client.post("/api/v1/sessions")
    sess_id = create_res.json()["data"]["session"]["session_id"]

    stop_res = client.post(
        f"/api/v1/sessions/{sess_id}/stop",
        json={"reason": "Tutoring session finished"},
    )
    assert stop_res.status_code == 200
    stop_data = stop_res.json()
    assert stop_data["success"] is True
    assert stop_data["data"]["state"] == "completed"
    assert stop_data["data"]["ended_at"] is not None
    assert stop_data["event"]["event_type"] == "session.stopped"
    assert stop_data["event"]["payload"]["reason"] == "Tutoring session finished"


def test_session_explicit_expiry(client: TestClient):
    """Verify explicit session expiry endpoint and event."""
    create_res = client.post("/api/v1/sessions")
    sess_id = create_res.json()["data"]["session"]["session_id"]

    expire_res = client.post(
        f"/api/v1/sessions/{sess_id}/expire",
        json={"reason": "Explicit timeout test"},
    )
    assert expire_res.status_code == 200
    expire_data = expire_res.json()
    assert expire_data["success"] is True
    assert expire_data["data"]["state"] == "expired"
    assert expire_data["data"]["ended_at"] is not None
    assert expire_data["event"]["event_type"] == "session.expired"


async def test_session_automatic_expiry_by_ttl(client: TestClient):
    """Verify that sessions automatically expire when TTL has elapsed upon retrieval."""
    repo = get_session_repository()

    # Create session with expires_at in the past
    create_res = client.post("/api/v1/sessions")
    sess_id = create_res.json()["data"]["session"]["session_id"]

    # Manually backdate expires_at to 10 seconds ago
    stored = await repo.get_by_id(sess_id)
    assert stored is not None
    stored.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    await repo.update(stored)

    # Retrieval should trigger auto-expiry
    get_res = client.get(f"/api/v1/sessions/{sess_id}")
    assert get_res.status_code == 200
    session_data = get_res.json()["data"]
    assert session_data["state"] == "expired"

    # Verify session.expired event was appended to history
    events_res = client.get(f"/api/v1/sessions/{sess_id}/events")
    event_types = [e["event_type"] for e in events_res.json()["events"]]
    assert "session.expired" in event_types


def test_invalid_state_transitions(client: TestClient):
    """Verify that illegal transitions (e.g. resuming completed/expired sessions) return 409 Conflict."""
    create_res = client.post("/api/v1/sessions")
    sess_id = create_res.json()["data"]["session"]["session_id"]

    # Stop session -> COMPLETED
    client.post(f"/api/v1/sessions/{sess_id}/stop")

    # Attempting to resume a completed session is illegal
    bad_resume = client.post(f"/api/v1/sessions/{sess_id}/resume")
    assert bad_resume.status_code == 409
    err = bad_resume.json()
    assert err["success"] is False
    assert err["error"]["code"] == "INVALID_STATE_TRANSITION"
    assert "completed" in err["error"]["message"].lower()

    # Attempting to pause a completed session is illegal
    bad_pause = client.post(f"/api/v1/sessions/{sess_id}/pause")
    assert bad_pause.status_code == 409
    assert bad_pause.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_lifecycle_idempotency(client: TestClient):
    """Verify repeated lifecycle commands are idempotent and do not create duplicate events."""
    create_res = client.post("/api/v1/sessions")
    sess_id = create_res.json()["data"]["session"]["session_id"]

    # 1. Pause once
    p1 = client.post(f"/api/v1/sessions/{sess_id}/pause")
    assert p1.status_code == 200
    assert p1.json()["event"] is not None

    # Pause again (repeated command)
    p2 = client.post(f"/api/v1/sessions/{sess_id}/pause")
    assert p2.status_code == 200
    assert p2.json()["data"]["state"] == "paused"
    assert p2.json()["event"] is None  # No duplicate event

    # 2. Resume once
    r1 = client.post(f"/api/v1/sessions/{sess_id}/resume")
    assert r1.status_code == 200
    assert r1.json()["event"] is not None

    # Resume again (repeated command)
    r2 = client.post(f"/api/v1/sessions/{sess_id}/resume")
    assert r2.status_code == 200
    assert r2.json()["data"]["state"] == "active"
    assert r2.json()["event"] is None  # No duplicate event

    # 3. Stop once
    s1 = client.post(f"/api/v1/sessions/{sess_id}/stop")
    assert s1.status_code == 200
    assert s1.json()["event"] is not None

    # Stop again (repeated command)
    s2 = client.post(f"/api/v1/sessions/{sess_id}/stop")
    assert s2.status_code == 200
    assert s2.json()["data"]["state"] == "completed"
    assert s2.json()["event"] is None  # No duplicate event


def test_event_ordering_and_timestamps(client: TestClient):
    """Verify events are stored and retrieved in strict chronological order with ascending timestamps."""
    create_res = client.post("/api/v1/sessions")
    sess_id = create_res.json()["data"]["session"]["session_id"]

    client.post(f"/api/v1/sessions/{sess_id}/pause")
    client.post(f"/api/v1/sessions/{sess_id}/resume")
    client.post(f"/api/v1/sessions/{sess_id}/stop")

    events_res = client.get(f"/api/v1/sessions/{sess_id}/events")
    events = events_res.json()["events"]

    expected_types = [
        "session.started",
        "session.paused",
        "session.resumed",
        "session.stopped",
    ]
    assert [e["event_type"] for e in events] == expected_types

    # Timestamps must be monotonic non-decreasing
    timestamps = [datetime.fromisoformat(e["timestamp"]) for e in events]
    for i in range(len(timestamps) - 1):
        assert timestamps[i] <= timestamps[i + 1]

