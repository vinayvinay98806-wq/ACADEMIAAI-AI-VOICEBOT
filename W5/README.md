# Academiaai AI Voicebot Backend (Team SDE 7)

## Workstream W5: Backend, Sessions and Observability — Week 1 Implementation

Welcome to the backend service for the **Academiaai AI Voicebot**, developed by **Team SDE 7**. This repository hosts the implementation of **Workstream W5 (Backend, Sessions, and Observability)** for **Week 1** in accordance with the official 30-Day Execution Plan.

---

## 1. Executive Summary & Week 1 Scope

Week 1 establishes the rock-solid foundation for the voicebot backend:
- **Application Skeleton**: Modular FastAPI application runnable in standalone **Mock Mode** without requiring paid external AI API keys or third-party audio service credentials.
- **Health & Readiness Endpoints**: Lightweight `/health` and `/ready` probes suitable for liveness/readiness checks and automated testing.
- **Typed Error Envelope**: Standardized, predictable JSON error contracts (`success: false`, `error: {code, message, request_id, details}`) preventing leaks of stack traces or internals.
- **Request & Correlation-ID Middleware**: Contextual tracking using `X-Request-ID` and `X-Correlation-ID` headers with input sanitization and structured logging injection.
- **Session State Machine & In-Memory Repository**: Clean state definitions (`initializing`, `active`, `idle`, `paused`, `completed`, `failed`) and thread-safe in-memory storage.
- **Mock Session Route**: Deterministic mock session generation and initial mock event production (`POST /api/v1/sessions/mock`).
- **One-Command Launcher**: Single command execution (`python run_mock.py`).
- **Automated Test Suite**: 22 unit and integration tests passing with 100% success rate.

---

## 2. Architecture & Folder Structure

```
.
├── app/
│   ├── __init__.py                # Package initialization and version definition
│   ├── main.py                    # FastAPI application factory, lifespan, error handlers
│   ├── config.py                  # Pydantic Settings configuration (mock mode, ports, etc.)
│   ├── core/
│   │   ├── __init__.py
│   │   ├── exceptions.py          # Typed domain exceptions (AppException, SessionNotFoundError, etc.)
│   │   ├── logging.py             # Contextual logging with request/correlation ID filters
│   │   └── middleware.py          # Request & Correlation ID middleware (X-Request-ID, X-Correlation-ID)
│   ├── models/
│   │   ├── __init__.py
│   │   ├── errors.py              # Error envelope schemas (ErrorDetail, ErrorEnvelope)
│   │   ├── health.py              # HealthResponse and ReadinessResponse schemas
│   │   └── session.py             # SessionState enum, Session, SessionEvent, response envelopes
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── base.py                # BaseSessionRepository abstract interface
│   │   └── in_memory_session.py   # Thread-safe in-memory session and event store
│   └── routers/
│       ├── __init__.py
│       ├── health.py              # Liveness (/health) and readiness (/ready) routes
│       └── sessions.py            # Mock session start, get, list, events, and state transitions
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # TestClient and repository reset fixtures
│   ├── test_errors.py             # Tests for 404, 422, and 500 error envelopes
│   ├── test_health.py             # Tests for /health and /ready endpoints
│   ├── test_middleware.py         # Tests for request ID generation and header propagation
│   ├── test_mock_session.py       # Tests for mock session creation, events, and state rules
│   └── test_repository.py         # Unit tests for InMemorySessionRepository
├── pyproject.toml                 # Modern Python package configuration
├── requirements.txt               # Pinned dependencies
├── run_mock.py                    # One-command mock mode launcher
├── .gitignore                     # Git ignore rules
└── README.md                      # Comprehensive documentation and demonstration guide
```

---

## 3. Session State Machine

The session lifecycle for Week 1 enforces safe transitions between well-defined states:

```
          ┌──────────────┐
          │ INITIALIZING │
          └──────┬───────┘
                 │
                 ▼
          ┌──────────────┐◄───────────────┐
          │    ACTIVE    │               │
          └──┬───┬───┬───┘               │
             │   │   │                   │
     ┌───────┘   │   └───────┐           │
     ▼           ▼           ▼           │
┌────────┐  ┌────────┐  ┌───────────┐    │
│  IDLE  │  │ PAUSED │  │ COMPLETED │(Terminal)
└───┬────┘  └───┬────┘  └───────────┘
    │           │             ▲
    └───────────┴─────────────┘
                 │
                 ▼ (from any non-terminal state on error)
          ┌───────────┐
          │  FAILED   │(Terminal)
          └───────────┘
```

- **Valid Transitions**:
  - `INITIALIZING` &rarr; `ACTIVE`, `FAILED`
  - `ACTIVE` &rarr; `IDLE`, `PAUSED`, `COMPLETED`, `FAILED`
  - `IDLE` &rarr; `ACTIVE`, `PAUSED`, `COMPLETED`, `FAILED`
  - `PAUSED` &rarr; `ACTIVE`, `COMPLETED`, `FAILED`
- **Terminal States**: `COMPLETED` and `FAILED` cannot transition to any other state. Attempting to transition out of a terminal state raises a `409 Conflict` typed error.

---

## 4. API Specifications & Contracts

### 4.1 Health and Readiness

#### `GET /health` (or `GET /api/v1/health`)
Returns the service health status and current mode.
```json
{
  "status": "healthy",
  "timestamp": "2026-10-27T10:19:19.776709Z",
  "service": "Academiaai AI Voicebot Backend",
  "version": "0.1.0",
  "mode": "mock"
}
```

#### `GET /ready` (or `GET /api/v1/ready`)
Verifies readiness of local components.
```json
{
  "status": "ready",
  "timestamp": "2026-10-27T10:19:19.782611Z",
  "service": "Academiaai AI Voicebot Backend",
  "dependencies": {
    "session_repository": "ready",
    "mock_provider": "ready"
  }
}
```

---

### 4.2 Mock Sessions & Events

#### `POST /api/v1/sessions/mock`
Starts a deterministic mock session and generates an initial mock audio event.
- **Request Body (Optional)**:
  ```json
  {
    "user_id": "student-1049",
    "metadata": {
      "course": "CS-501",
      "preferred_language": "en"
    }
  }
  ```
- **Response (`201 Created`)**:
  ```json
  {
    "success": true,
    "data": {
      "session": {
        "session_id": "mock-sess-87d1ef9d79",
        "user_id": "student-1049",
        "state": "active",
        "metadata": {
          "mode": "mock",
          "team": "SDE 7",
          "workstream": "W5",
          "course": "CS-501",
          "preferred_language": "en"
        },
        "created_at": "2026-10-27T10:19:19.794940Z",
        "updated_at": "2026-10-27T10:19:19.794940Z"
      },
      "event": {
        "event_id": "mock-evt-87d1ef9d79",
        "session_id": "mock-sess-87d1ef9d79",
        "event_type": "session.started",
        "payload": {
          "message": "Mock voice session initialized successfully",
          "bot_name": "Academiaai-Voicebot",
          "audio_channel": "mock-stream",
          "sample_rate_hz": 16000,
          "codec": "pcm_s16le",
          "initial_prompt": "Hello! Welcome to Academiaai. How can I assist you with your academic queries today?",
          "mock_mode": true
        },
        "timestamp": "2026-10-27T10:19:19.794940Z"
      }
    }
  }
  ```

#### `GET /api/v1/sessions/{session_id}`
Retrieves session details by session ID (`200 OK`).

#### `GET /api/v1/sessions/{session_id}/events`
Retrieves all recorded events for the given session ID (`200 OK`).

#### `GET /api/v1/sessions`
Lists all active/stored sessions (`200 OK`).

#### `POST /api/v1/sessions/{session_id}/transition`
Transitions a session to a target state (`200 OK` on success, `409 Conflict` on illegal transition).
- **Request Body**:
  ```json
  {
    "target_state": "completed"
  }
  ```

---

### 4.3 Standardized Typed Error Envelope

All HTTP errors follow the typed envelope:
```json
{
  "success": false,
  "error": {
    "code": "NOT_FOUND",
    "message": "Session not found with ID: mock-sess-nonexistent",
    "request_id": "req-bce6ddc54723",
    "details": {
      "session_id": "mock-sess-nonexistent"
    }
  }
}
```

Validation errors (`422 Unprocessable Content`):
```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request payload validation failed.",
    "request_id": "req-98fa201b38cf",
    "details": [
      {
        "field": "body -> target_state",
        "issue": "Input should be 'initializing', 'active', 'idle', 'paused', 'completed' or 'failed'",
        "type": "enum"
      }
    ]
  }
}
```

---

## 5. Getting Started & Running the Application

### 5.1 Prerequisites
- Python 3.12+ (or `uv`)

### 5.2 Setup Environment
```bash
# Using uv (recommended)
uv venv --python 3.12
uv pip install -r requirements.txt

# Or using standard python
python -m venv .venv
# Windows:
.\.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate
pip install -r requirements.txt
```

### 5.3 One-Command Mock-Mode Launcher (Task 8)
Run the application with zero external credentials:
```bash
python run_mock.py
```
Output:
```
========================================================================
  ACADEMIAAI AI VOICEBOT BACKEND - TEAM SDE 7
  Workstream: W5 - Backend, Sessions and Observability
  Scope:      Week 1 Implementation (Application Skeleton & Sessions)
  Status:     MOCK MODE ACTIVE (No external API keys required)
========================================================================
  Base URL:      http://127.0.0.1:8000
  Health Check:  http://127.0.0.1:8000/health
  Readiness:     http://127.0.0.1:8000/ready
  Mock Session:  POST http://127.0.0.1:8000/api/v1/sessions/mock
  Swagger Docs:  http://127.0.0.1:8000/docs
========================================================================
```

---

## 6. Running Automated Tests (Task 9)

Execute the full test suite covering all Week 1 features:
```bash
pytest -v
```

Test Results:
```
============================= test session starts =============================
platform win32 -- Python 3.12.14, pytest-9.1.1
collected 22 items

tests/test_errors.py::test_404_typed_error_envelope PASSED               [  4%]
tests/test_errors.py::test_session_not_found_envelope PASSED             [  9%]
tests/test_errors.py::test_422_validation_error_envelope PASSED          [ 13%]
tests/test_health.py::test_health_check_returns_ok PASSED                [ 18%]
tests/test_health.py::test_readiness_check_returns_ready PASSED          [ 22%]
tests/test_health.py::test_versioned_health_and_readiness PASSED         [ 27%]
tests/test_middleware.py::test_generates_request_and_correlation_ids_when_missing PASSED [ 31%]
tests/test_middleware.py::test_preserves_valid_incoming_request_id PASSED [ 36%]
tests/test_middleware.py::test_preserves_valid_incoming_correlation_id PASSED [ 40%]
tests/test_middleware.py::test_sanitizes_malformed_incoming_ids PASSED   [ 45%]
tests/test_middleware.py::test_handles_excessively_long_ids PASSED       [ 50%]
tests/test_mock_session.py::test_start_mock_session_default PASSED       [ 54%]
tests/test_mock_session.py::test_start_mock_session_with_custom_user PASSED [ 59%]
tests/test_mock_session.py::test_get_session_by_id PASSED                [ 63%]
tests/test_mock_session.py::test_get_session_events PASSED               [ 68%]
tests/test_mock_session.py::test_list_sessions PASSED                    [ 72%]
tests/test_mock_session.py::test_session_state_transitions PASSED        [ 77%]
tests/test_repository.py::test_repository_create_and_get PASSED          [ 81%]
tests/test_repository.py::test_repository_get_nonexistent PASSED         [ 86%]
tests/test_repository.py::test_repository_update_session PASSED          [ 90%]
tests/test_repository.py::test_repository_events_storage PASSED          [ 95%]
tests/test_repository.py::test_repository_clear PASSED                   [100%]

============================== 22 passed in 0.44s ==============================
```

---

## 7. Week 1 Live Demonstration Guide (Task 10)

Follow these steps to demonstrate the Week 1 implementation to project leads or teammates:

### Step 1: Launch the backend
```bash
python run_mock.py
```

### Step 2: Test Health & Request ID Propagation
```bash
curl -i http://127.0.0.1:8000/health -H "X-Request-ID: demo-req-001"
```
*Expected*: Status `200 OK`, header `X-Request-ID: demo-req-001`, JSON status `healthy`.

### Step 3: Test Readiness Check
```bash
curl -i http://127.0.0.1:8000/ready
```
*Expected*: Status `200 OK`, JSON status `ready`, `session_repository: ready`.

### Step 4: Start a Mock Voice Session & Receive Mock Event
```bash
curl -i -X POST http://127.0.0.1:8000/api/v1/sessions/mock \
     -H "Content-Type: application/json" \
     -d '{"user_id": "demo-student-1", "metadata": {"course": "Algorithms"}}'
```
*Expected*: Status `201 Created`, JSON containing `session` (`state: active`) and `event` (`session.started` with initial prompt).

### Step 5: Verify Session and Event Retrieval
```bash
# Substitute the session_id returned from Step 4
curl -i http://127.0.0.1:8000/api/v1/sessions/{session_id}
curl -i http://127.0.0.1:8000/api/v1/sessions/{session_id}/events
```

### Step 6: Verify State Enforcement & Error Envelope
```bash
# Valid transition to completed:
curl -i -X POST http://127.0.0.1:8000/api/v1/sessions/{session_id}/transition \
     -H "Content-Type: application/json" \
     -d '{"target_state": "completed"}'

# Illegal transition from completed -> active (returns 409 Conflict):
curl -i -X POST http://127.0.0.1:8000/api/v1/sessions/{session_id}/transition \
     -H "Content-Type: application/json" \
     -d '{"target_state": "active"}'
```
*Expected*: `409 Conflict` response with `INVALID_STATE_TRANSITION` code and safe explanation.

---

## 8. Suggested Git Workflow for Pull Request

As per the team's Git guidelines (Rule 10: Do not push or open a PR automatically), here are the suggested steps:

```bash
# 1. Ensure you are on a dedicated feature branch
git checkout -b feature/w5-week1-backend-sessions-skeleton

# 2. Stage the newly created Week 1 files
git add app/ tests/ pyproject.toml requirements.txt run_mock.py .gitignore README.md

# 3. Commit with semantic convention
git commit -m "feat(w5): implement Week 1 backend skeleton, session models, in-memory repository, and mock route"

# 4. Push to remote and open Pull Request for Team SDE 7 review
git push -u origin feature/w5-week1-backend-sessions-skeleton
```
