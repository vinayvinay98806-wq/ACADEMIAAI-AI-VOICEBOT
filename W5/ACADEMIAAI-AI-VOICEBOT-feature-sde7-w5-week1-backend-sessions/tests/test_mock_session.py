"""Tests for mock session route, events, and state rules."""

from fastapi.testclient import TestClient


def test_start_mock_session_default(client: TestClient):
    """Verify starting a mock session returns 201 Created with mock event."""
    response = client.post("/api/v1/sessions/mock")
    assert response.status_code == 201

    data = response.json()
    assert data["success"] is True
    assert "data" in data

    session = data["data"]["session"]
    assert session["session_id"].startswith("mock-sess-")
    assert session["state"] == "active"
    assert session["user_id"] == "anonymous-user"
    assert session["metadata"]["mode"] == "mock"

    event = data["data"]["event"]
    assert event["event_type"] == "session.started"
    assert event["session_id"] == session["session_id"]
    assert event["payload"]["mock_mode"] is True
    assert "Academiaai-Voicebot" in event["payload"]["bot_name"]
    assert "audio_channel" in event["payload"]


def test_start_mock_session_with_custom_user(client: TestClient):
    """Verify custom user_id and metadata are stored in session."""
    payload = {
        "user_id": "student-1049",
        "metadata": {"course": "CS-501", "preferred_language": "en"},
    }
    response = client.post("/api/v1/sessions/mock", json=payload)
    assert response.status_code == 201

    session = response.json()["data"]["session"]
    assert session["user_id"] == "student-1049"
    assert session["metadata"]["course"] == "CS-501"


def test_get_session_by_id(client: TestClient):
    """Verify retrieving an active session by its ID."""
    # Create
    create_res = client.post("/api/v1/sessions/mock")
    sess_id = create_res.json()["data"]["session"]["session_id"]

    # Retrieve
    get_res = client.get(f"/api/v1/sessions/{sess_id}")
    assert get_res.status_code == 200
    fetched = get_res.json()["data"]
    assert fetched["session_id"] == sess_id
    assert fetched["state"] == "active"


def test_get_session_events(client: TestClient):
    """Verify retrieving events for a created session."""
    create_res = client.post("/api/v1/sessions/mock")
    sess_id = create_res.json()["data"]["session"]["session_id"]

    events_res = client.get(f"/api/v1/sessions/{sess_id}/events")
    assert events_res.status_code == 200
    events_data = events_res.json()
    assert events_data["success"] is True
    assert events_data["session_id"] == sess_id
    assert events_data["total"] >= 1
    assert events_data["events"][0]["event_type"] == "session.started"


def test_list_sessions(client: TestClient):
    """Verify listing all active sessions."""
    client.post("/api/v1/sessions/mock", json={"user_id": "u1"})
    client.post("/api/v1/sessions/mock", json={"user_id": "u2"})

    list_res = client.get("/api/v1/sessions")
    assert list_res.status_code == 200
    data = list_res.json()
    assert data["success"] is True
    assert data["total"] == 2


def test_session_state_transitions(client: TestClient):
    """Verify valid state transitions and rejection of invalid transitions."""
    # 1. Create session (starts ACTIVE)
    create_res = client.post("/api/v1/sessions/mock")
    sess_id = create_res.json()["data"]["session"]["session_id"]

    # 2. Transition ACTIVE -> IDLE (valid)
    t1 = client.post(
        f"/api/v1/sessions/{sess_id}/transition",
        json={"target_state": "idle"},
    )
    assert t1.status_code == 200
    assert t1.json()["data"]["state"] == "idle"

    # 3. Transition IDLE -> PAUSED (valid)
    t2 = client.post(
        f"/api/v1/sessions/{sess_id}/transition",
        json={"target_state": "paused"},
    )
    assert t2.status_code == 200
    assert t2.json()["data"]["state"] == "paused"

    # 4. Transition PAUSED -> COMPLETED (valid)
    t3 = client.post(
        f"/api/v1/sessions/{sess_id}/transition",
        json={"target_state": "completed"},
    )
    assert t3.status_code == 200
    assert t3.json()["data"]["state"] == "completed"

    # 5. Transition COMPLETED -> ACTIVE (invalid terminal state transition -> 409 Conflict)
    t4 = client.post(
        f"/api/v1/sessions/{sess_id}/transition",
        json={"target_state": "active"},
    )
    assert t4.status_code == 409
    err = t4.json()
    assert err["success"] is False
    assert err["error"]["code"] == "INVALID_STATE_TRANSITION"
    assert "not permitted" in err["error"]["message"].lower()
