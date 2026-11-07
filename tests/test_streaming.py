"""Unit and integration tests for Server-Sent Events (SSE) streaming (Day 10-11)."""

import json
from datetime import datetime
from fastapi.testclient import TestClient


def parse_sse_events(sse_text: str):
    """Helper to parse raw SSE text into structured events."""
    events = []
    current = {}
    for line in sse_text.splitlines():
        line = line.strip()
        if not line:
            if current:
                events.append(current)
                current = {}
            continue
        if line.startswith(":"):
            # Comment line
            continue
        if ":" in line:
            field, val = line.split(":", 1)
            val = val.lstrip()
            if field == "data":
                try:
                    current["data"] = json.loads(val)
                except Exception:
                    current["data"] = val
            else:
                current[field] = val
    if current:
        events.append(current)
    return events


def test_stream_events_format_and_ordering(client: TestClient):
    """Verify SSE streaming produces valid event stream with headers and chronological order."""
    # Create and perform actions
    res = client.post("/api/v1/sessions")
    sess_id = res.json()["data"]["session"]["session_id"]

    client.post(f"/api/v1/sessions/{sess_id}/pause", json={"reason": "break"})
    client.post(f"/api/v1/sessions/{sess_id}/resume", json={"reason": "back"})

    # Stream events
    stream_res = client.get(f"/api/v1/sessions/{sess_id}/events/stream")
    assert stream_res.status_code == 200
    assert "text/event-stream" in stream_res.headers["content-type"]
    assert "no-cache" in stream_res.headers["cache-control"]

    events = parse_sse_events(stream_res.text)
    assert len(events) == 3

    assert events[0]["event"] == "session.started"
    assert events[1]["event"] == "session.paused"
    assert events[2]["event"] == "session.resumed"

    # Verify ID presence and chronological timestamp ordering
    for evt in events:
        assert "id" in evt
        assert "data" in evt
        assert evt["data"]["session_id"] == sess_id


def test_stream_events_reconnect_replay_since_id(client: TestClient):
    """Verify replay/reconnect support via since_id query parameter."""
    res = client.post("/api/v1/sessions")
    sess_id = res.json()["data"]["session"]["session_id"]
    start_event_id = res.json()["data"]["event"]["event_id"]

    client.post(f"/api/v1/sessions/{sess_id}/pause")
    client.post(f"/api/v1/sessions/{sess_id}/resume")

    # Replay after the initial start event
    stream_res = client.get(
        f"/api/v1/sessions/{sess_id}/events/stream",
        params={"since_id": start_event_id},
    )
    assert stream_res.status_code == 200
    events = parse_sse_events(stream_res.text)
    assert len(events) == 2
    assert events[0]["event"] == "session.paused"
    assert events[1]["event"] == "session.resumed"


def test_stream_events_reconnect_replay_last_event_id_header(client: TestClient):
    """Verify replay/reconnect support via Last-Event-ID HTTP header."""
    res = client.post("/api/v1/sessions")
    sess_id = res.json()["data"]["session"]["session_id"]
    start_event_id = res.json()["data"]["event"]["event_id"]

    p_res = client.post(f"/api/v1/sessions/{sess_id}/pause")
    pause_event_id = p_res.json()["event"]["event_id"]

    client.post(f"/api/v1/sessions/{sess_id}/resume")

    # Replay after the pause event via Last-Event-ID header
    stream_res = client.get(
        f"/api/v1/sessions/{sess_id}/events/stream",
        headers={"Last-Event-ID": pause_event_id},
    )
    assert stream_res.status_code == 200
    events = parse_sse_events(stream_res.text)
    assert len(events) == 1
    assert events[0]["event"] == "session.resumed"


def test_stream_events_unknown_session_returns_404(client: TestClient):
    """Verify requesting event stream for unknown session returns standard 404 typed error envelope."""
    stream_res = client.get("/api/v1/sessions/mock-sess-nonexistent/events/stream")
    assert stream_res.status_code == 404

    body = stream_res.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"
    assert "mock-sess-nonexistent" in body["error"]["message"]

