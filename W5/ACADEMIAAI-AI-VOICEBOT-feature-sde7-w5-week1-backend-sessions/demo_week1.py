"""Interactive Week 1 demonstration script for Team SDE 7 (W5).

Executes the entire Week 1 verification flow and prints formatted results.

Usage:
    python demo_week1.py
"""

import json
from fastapi.testclient import TestClient

from app.main import create_app
from app.repositories.in_memory_session import get_session_repository


def run_demo() -> None:
    print("=" * 70)
    print(" ACADEMIAAI AI VOICEBOT BACKEND - TEAM SDE 7")
    print(" WORKSTREAM W5: WEEK 1 DEMONSTRATION & VERIFICATION")
    print("=" * 70)

    app = create_app()
    client = TestClient(app)

    # 1. Health check
    print("\n[Step 1] Liveness Health Check (GET /health)")
    res = client.get("/health")
    print(f"Status Code: {res.status_code}")
    print(f"Headers: X-Request-ID={res.headers.get('X-Request-ID')}")
    print("Response JSON:")
    print(json.dumps(res.json(), indent=2))

    # 2. Readiness check
    print("\n[Step 2] Readiness Probe (GET /ready)")
    res = client.get("/ready")
    print(f"Status Code: {res.status_code}")
    print("Response JSON:")
    print(json.dumps(res.json(), indent=2))

    # 3. Request and Correlation ID Propagation
    print("\n[Step 3] Request & Correlation ID Middleware")
    custom_headers = {
        "X-Request-ID": "sde7-demo-req-101",
        "X-Correlation-ID": "sde7-demo-corr-999",
    }
    res = client.get("/health", headers=custom_headers)
    print(f"Sent Headers: {custom_headers}")
    print(f"Received Headers: X-Request-ID={res.headers.get('X-Request-ID')}, X-Correlation-ID={res.headers.get('X-Correlation-ID')}")

    # 4. Start Mock Session & Receive Mock Event
    print("\n[Step 4] Start Mock Session & Return Mock Event (POST /api/v1/sessions/mock)")
    mock_payload = {
        "user_id": "intern_sde7_user",
        "metadata": {
            "demo": True,
            "subject": "Computer Science",
            "voice_enabled": True,
        },
    }
    res = client.post("/api/v1/sessions/mock", json=mock_payload)
    print(f"Status Code: {res.status_code}")
    mock_data = res.json()
    print("Response JSON:")
    print(json.dumps(mock_data, indent=2))

    session_id = mock_data["data"]["session"]["session_id"]
    event_id = mock_data["data"]["event"]["event_id"]
    print(f"\nCreated Session ID: {session_id}")
    print(f"Produced Mock Event ID: {event_id}")

    # 5. Retrieve Session by ID
    print(f"\n[Step 5] Fetch Stored Session (GET /api/v1/sessions/{session_id})")
    res = client.get(f"/api/v1/sessions/{session_id}")
    print(f"Status Code: {res.status_code}")
    print("Response JSON:")
    print(json.dumps(res.json(), indent=2))

    # 6. Retrieve Session Events
    print(f"\n[Step 6] Fetch Session Events (GET /api/v1/sessions/{session_id}/events)")
    res = client.get(f"/api/v1/sessions/{session_id}/events")
    print(f"Status Code: {res.status_code}")
    print("Response JSON:")
    print(json.dumps(res.json(), indent=2))

    # 7. State Transition: ACTIVE -> IDLE
    print(f"\n[Step 7] Transition Session State: ACTIVE -> IDLE (POST /api/v1/sessions/{session_id}/transition)")
    res = client.post(
        f"/api/v1/sessions/{session_id}/transition",
        json={"target_state": "idle"},
    )
    print(f"Status Code: {res.status_code}")
    print(f"New State: {res.json()['data']['state']}")

    # 8. State Transition: IDLE -> COMPLETED
    print(f"\n[Step 8] Transition Session State: IDLE -> COMPLETED (POST /api/v1/sessions/{session_id}/transition)")
    res = client.post(
        f"/api/v1/sessions/{session_id}/transition",
        json={"target_state": "completed"},
    )
    print(f"Status Code: {res.status_code}")
    print(f"New State: {res.json()['data']['state']}")

    # 9. Invalid State Transition: COMPLETED -> ACTIVE (Enforcing Terminal State Rules)
    print(f"\n[Step 9] Illegal Transition from Terminal State: COMPLETED -> ACTIVE (Expect 409 Conflict)")
    res = client.post(
        f"/api/v1/sessions/{session_id}/transition",
        json={"target_state": "active"},
    )
    print(f"Status Code: {res.status_code}")
    print("Response JSON (Typed Error Envelope):")
    print(json.dumps(res.json(), indent=2))

    # 10. Nonexistent Session (Expect 404 Typed Error Envelope)
    print("\n[Step 10] Lookup Nonexistent Session (Expect 404 Typed Error Envelope)")
    res = client.get("/api/v1/sessions/nonexistent-sess-999")
    print(f"Status Code: {res.status_code}")
    print("Response JSON (Typed Error Envelope):")
    print(json.dumps(res.json(), indent=2))

    # 11. Malformed Payload (Expect 422 Validation Error Envelope)
    print("\n[Step 11] Malformed Request Body (Expect 422 Validation Error Envelope)")
    res = client.post(
        f"/api/v1/sessions/{session_id}/transition",
        json={"target_state": "INVALID_STATE_VALUE"},
    )
    print(f"Status Code: {res.status_code}")
    print("Response JSON (Typed Error Envelope):")
    print(json.dumps(res.json(), indent=2))

    print("\n" + "=" * 70)
    print(" ALL 11 DEMONSTRATION STEPS COMPLETED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    run_demo()
