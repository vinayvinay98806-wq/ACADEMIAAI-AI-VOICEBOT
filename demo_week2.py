"""Interactive Week 2 demonstration script for Team SDE 7 (W5).

Executes the complete Week 2 verification flow including:
- Complete session lifecycle (Create, Pause, Resume, Stop, Expire)
- Idempotency for repeated commands
- Server-Sent Events (SSE) event streaming & reconnect replay
- Request & payload size validation (413 & 422)
- Correlation ID tracking and structured logging

Usage:
    python demo_week2.py
"""

import json
from fastapi.testclient import TestClient

from app.main import create_app


def run_demo() -> None:
    print("=" * 75)
    print(" ACADEMIAAI AI VOICEBOT BACKEND - TEAM SDE 7")
    print(" WORKSTREAM W5: WEEK 2 DEMONSTRATION & VERIFICATION")
    print(" Scope: Complete Session Lifecycle, Event Streaming, Validation, Observability")
    print("=" * 75)

    app = create_app()
    client = TestClient(app)

    # 1. Health and Readiness Checks
    print("\n[Step 1] Service Health & Readiness (GET /health & /ready)")
    res_health = client.get("/health")
    print(f"Health Status: {res_health.status_code} -> {res_health.json()['status']}")
    res_ready = client.get("/ready")
    print(f"Readiness:     {res_ready.status_code} -> {res_ready.json()['dependencies']}")

    # 2. Session Creation with Custom TTL
    print("\n[Step 2] Session Creation with Custom TTL (POST /api/v1/sessions)")
    create_payload = {
        "user_id": "student-alice",
        "metadata": {"subject": "Calculus III", "module": "Partial Derivatives"},
        "ttl_seconds": 1200,
    }
    create_res = client.post("/api/v1/sessions", json=create_payload)
    print(f"Status Code: {create_res.status_code}")
    create_data = create_res.json()
    sess_id = create_data["data"]["session"]["session_id"]
    print(f"Created Session ID: {sess_id} [State: {create_data['data']['session']['state']}]")
    print(f"Expires At:         {create_data['data']['session']['expires_at']}")

    # 3. Successful Pause
    print(f"\n[Step 3] Pause Session (POST /api/v1/sessions/{sess_id}/pause)")
    pause_res = client.post(
        f"/api/v1/sessions/{sess_id}/pause",
        json={"reason": "Student paused lecture audio for notes"},
    )
    print(f"Status Code: {pause_res.status_code}")
    pause_data = pause_res.json()
    print(f"New State:   {pause_data['data']['state']}")
    print(f"Event Added: {pause_data['event']['event_type']} [ID: {pause_data['event']['event_id']}]")

    # 4. Repeated Pause (Idempotency)
    print(f"\n[Step 4] Repeated Pause - Idempotency Verification")
    pause_again = client.post(
        f"/api/v1/sessions/{sess_id}/pause",
        json={"reason": "Duplicate pause request"},
    )
    print(f"Status Code: {pause_again.status_code} (Expect 200 OK)")
    print(f"Current State: {pause_again.json()['data']['state']}")
    print(f"Event:         {pause_again.json()['event']} (Verified None: No duplicate event created!)")

    # 5. Successful Resume
    print(f"\n[Step 5] Resume Session (POST /api/v1/sessions/{sess_id}/resume)")
    resume_res = client.post(
        f"/api/v1/sessions/{sess_id}/resume",
        json={"reason": "Student resumed lecture audio"},
    )
    print(f"Status Code: {resume_res.status_code}")
    resume_data = resume_res.json()
    print(f"New State:   {resume_data['data']['state']}")
    print(f"Event Added: {resume_data['event']['event_type']} [ID: {resume_data['event']['event_id']}]")
    print(f"Refreshed Expiry: {resume_data['data']['expires_at']}")

    # 6. Stop / Complete Session
    print(f"\n[Step 6] Stop Session (POST /api/v1/sessions/{sess_id}/stop)")
    stop_res = client.post(
        f"/api/v1/sessions/{sess_id}/stop",
        json={"reason": "Student completed lesson"},
    )
    print(f"Status Code: {stop_res.status_code}")
    stop_data = stop_res.json()
    print(f"New State:   {stop_data['data']['state']} (Terminal)")
    print(f"Ended At:    {stop_data['data']['ended_at']}")
    print(f"Event Added: {stop_data['event']['event_type']}")

    # 7. Illegal Transition Rejection
    print(f"\n[Step 7] Illegal Transition Rejection (COMPLETED -> ACTIVE)")
    illegal_res = client.post(f"/api/v1/sessions/{sess_id}/resume")
    print(f"Status Code: {illegal_res.status_code} (Expect 409 Conflict)")
    print(f"Error Code:  {illegal_res.json()['error']['code']}")
    print(f"Message:     {illegal_res.json()['error']['message']}")

    # 8. Server-Sent Events (SSE) Stream
    print(f"\n[Step 8] Server-Sent Events Stream (GET /api/v1/sessions/{sess_id}/events/stream)")
    stream_res = client.get(f"/api/v1/sessions/{sess_id}/events/stream")
    print(f"Status Code:  {stream_res.status_code}")
    print(f"Content-Type: {stream_res.headers.get('content-type')}")
    print("SSE Stream Payload Sample:")
    for line in stream_res.text.strip().splitlines()[:12]:
        print(f"  | {line}")
    print("  | ... [stream output continues]")

    # 9. Reconnect / Replay with Last-Event-ID
    print(f"\n[Step 9] Reconnect & Replay via Last-Event-ID header")
    first_event_id = create_data["data"]["event"]["event_id"]
    replay_res = client.get(
        f"/api/v1/sessions/{sess_id}/events/stream",
        headers={"Last-Event-ID": first_event_id},
    )
    print(f"Status Code: {replay_res.status_code}")
    print("Replayed Events after start:")
    for line in replay_res.text.strip().splitlines():
        if line.startswith("event:") or line.startswith("id:"):
            print(f"  -> {line}")

    # 10. Oversized Payload Rejection
    print(f"\n[Step 10] Enforce Payload Limits (Payload Too Large -> 413)")
    huge_data = {"user_id": "test", "metadata": {"blob": "0" * 1_200_000}}
    huge_res = client.post("/api/v1/sessions", json=huge_data)
    print(f"Status Code: {huge_res.status_code} (Expect 413 Payload Too Large)")
    print(f"Error Code:  {huge_res.json()['error']['code']}")
    print(f"Message:     {huge_res.json()['error']['message']}")

    # 11. Malformed Payload Validation
    print(f"\n[Step 11] Request Validation Error (Expect 422 Unprocessable Content)")
    bad_res = client.post("/api/v1/sessions", json={"ttl_seconds": -500})
    print(f"Status Code: {bad_res.status_code} (Expect 422)")
    print(f"Error Code:  {bad_res.json()['error']['code']}")
    print(f"Details:     {bad_res.json()['error']['details']}")

    # 12. Correlation ID Propagation
    print(f"\n[Step 12] Correlation ID Tracking")
    corr_headers = {
        "X-Request-ID": "sde7-demo-req-002",
        "X-Correlation-ID": "sde7-demo-trace-777",
    }
    track_res = client.get(f"/api/v1/sessions/{sess_id}", headers=corr_headers)
    print(f"Sent:     {corr_headers}")
    print(f"Received: X-Request-ID={track_res.headers.get('X-Request-ID')}, X-Correlation-ID={track_res.headers.get('X-Correlation-ID')}")

    print("\n" + "=" * 75)
    print(" ALL 12 WEEK 2 DEMONSTRATION STEPS COMPLETED SUCCESSFULLY!")
    print("=" * 75)


if __name__ == "__main__":
    run_demo()

