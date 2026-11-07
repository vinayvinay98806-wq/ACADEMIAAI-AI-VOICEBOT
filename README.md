# Academiaai AI Voicebot Backend (Team SDE 7)

## Workstream W5: Backend, Sessions and Observability — Week 2 Implementation

Welcome to the backend service for the **Academiaai AI Voicebot**, developed by **Team SDE 7**. This repository hosts the implementation of **Workstream W5 (Backend, Sessions, and Observability)** covering both **Week 1** foundation and **Week 2 (Days 8–14)** complete session lifecycle, Server-Sent Events (SSE) streaming, configurable payload limits, startup configuration validation, and structured observability.

---

## 1. Executive Summary & Week 2 Scope

Week 2 expands upon the solid Week 1 skeleton with full production-grade lifecycle capabilities:

- **Complete Session Lifecycle (Days 8–9)**:
  - Standard session creation with custom TTL support (`POST /api/v1/sessions`).
  - Session pause (`POST /api/v1/sessions/{session_id}/pause`).
  - Session resume (`POST /api/v1/sessions/{session_id}/resume`).
  - Session stop/completion (`POST /api/v1/sessions/{session_id}/stop`).
  - Explicit and automatic session expiry (`POST /api/v1/sessions/{session_id}/expire`).
  - **Idempotency**: Repeated commands (e.g. pausing an already paused session or stopping a completed session) return `200 OK` as no-ops without creating duplicate events or corrupting state.
  - **Terminal State Protection**: Transitions out of `completed`, `expired`, or `failed` are strictly rejected with `409 Conflict` typed errors.
  - **Lifecycle Timestamps**: Automated tracking of `created_at`, `updated_at`, `expires_at`, and `ended_at`.
- **Event Streaming & Replay (Days 10–11)**:
  - Real-time Server-Sent Events (SSE) endpoint (`GET /api/v1/sessions/{session_id}/events/stream`).
  - Strict chronological event ordering (`id: ...`, `event: ...`, `data: ...`).
  - Reconnect and replay capabilities via `Last-Event-ID` header and `?since_id=...` query parameter.
  - Safe disconnection handling and pubsub subscriber decoupling.
  - Unknown session validation returning typed `404 Not Found` error envelopes.
- **Request Validation & Payload Limits (Days 10–11)**:
  - Configurable payload limits (`max_payload_size_bytes`, default 1MB).
  - Rapid rejection of oversized payloads (`413 Payload Too Large`) with typed error envelopes.
  - Strict Pydantic input validation rejecting malformed payloads (`422 Unprocessable Content`).
- **Startup Configuration Validation & Structured Logging (Days 12–13)**:
  - Centralized settings validation on startup in FastAPI `lifespan`.
  - Safe mock-mode defaults allowing zero-credential execution.
  - Strict production-mode checks failing safely when required API keys or database URLs are missing.
  - Sensitive credential masking (`safe_dict()` and regex log filter redacting tokens, keys, passwords).
  - Structured logging with `request_id`, `correlation_id`, and `session_id` context propagation.
- **Comprehensive Verification (Day 14)**:
  - 49 automated unit and integration tests passing with 100% success rate.
  - Interactive demonstration scripts (`demo_week1.py` and `demo_week2.py`).

---

## 2. Architecture & Project Structure

The project strictly follows layered architecture principles, decoupling Routers, Domain Services, Repositories, and Core Infrastructure:

```
.
├── app/
│   ├── __init__.py                # Package initialization and version definition
│   ├── main.py                    # FastAPI application factory, lifespan startup validation, error handlers
│   ├── config.py                  # Centralized Pydantic Settings & startup configuration validation
│   ├── core/
│   │   ├── __init__.py
│   │   ├── exceptions.py          # Domain exceptions (AppException, PayloadTooLargeError, etc.)
│   │   ├── logging.py             # Structured logging, JSON formatter, contextvars, sensitive data masking
│   │   └── middleware.py          # Request ID, Correlation ID tracking, and Payload Size Limit enforcement
│   ├── models/
│   │   ├── __init__.py
│   │   ├── errors.py              # Standardized ErrorDetail and ErrorEnvelope schemas
│   │   ├── health.py              # HealthResponse and ReadinessResponse schemas
│   │   └── session.py             # SessionState enum, Session, SessionEvent, lifecycle request/response schemas
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── base.py                # BaseSessionRepository interface with pubsub methods
│   │   └── in_memory_session.py   # Thread-safe in-memory store with subscriber broadcast queues
│   ├── services/
│   │   ├── __init__.py
│   │   └── session_service.py     # Domain service: lifecycle orchestration, idempotency, auto-expiry
│   └── routers/
│       ├── __init__.py
│       ├── health.py              # Liveness (/health) and readiness (/ready) routes
│       └── sessions.py            # Session CRUD, lifecycle routes (pause/resume/stop/expire), and SSE stream
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # TestClient and repository reset fixtures
│   ├── test_config_logging.py     # Tests for startup validation, correlation ID, secret masking, JSON logging
│   ├── test_errors.py             # Tests for 404, 422, and 500 error envelopes
│   ├── test_health.py             # Tests for /health and /ready endpoints
│   ├── test_lifecycle.py          # Tests for create, pause, resume, stop, expire, idempotency, auto-expiry
│   ├── test_middleware.py         # Tests for ID generation, header preservation, sanitization
│   ├── test_mock_session.py       # Tests for Week 1 mock routes and basic transitions
│   ├── test_repository.py         # Unit tests for InMemorySessionRepository
│   ├── test_streaming.py          # Tests for SSE streaming format, chronological order, replay via Last-Event-ID
│   └── test_validation_limits.py  # Tests for 413 payload limits, 422 validation, unknown session 404s
├── pyproject.toml                 # Package configuration (hatchling wheel build target configured)
├── requirements.txt               # Pinned dependencies
├── run_mock.py                    # One-command mock mode launcher
├── demo_week1.py                  # Week 1 interactive demonstration script
├── demo_week2.py                  # Week 2 comprehensive interactive demonstration script
└── README.md                      # Complete system documentation
```

---

## 3. Session State Machine & Lifecycle Transitions

The state machine governs all valid state transitions and guarantees terminal state safety:

```
                      ┌──────────────┐
                      │ INITIALIZING │
                      └──────┬───────┘
                             │
                             ▼
     ┌────────────────>┌──────────────┐<────────────────┐
     │                 │    ACTIVE    │                 │
     │                 └──┬───┬───┬───┘                 │
     │                    │   │   │                     │
     │            ┌───────┘   │   └───────┐             │
     │            ▼           ▼           ▼             │
     │       ┌────────┐  ┌────────┐  ┌───────────┐      │
     └───────┤  IDLE  │  │ PAUSED │  │ COMPLETED │(Term)│
             └───┬────┘  └───┬────┘  └───────────┘      │
                 │           │             ▲            │
                 └───────────┼─────────────┘            │
                             │                          │
                             ▼ (Resume)                 │
                             └──────────────────────────┘
                             │
                             ▼ (TTL / explicit timeout)
                      ┌───────────┐
                      │  EXPIRED  │(Terminal)
                      └───────────┘
                             ▲
                             │ (from any non-terminal on failure)
                      ┌───────────┐
                      │  FAILED   │(Terminal)
                      └───────────┘
```

### Transition Rules

| Current State | Permitted Target States | Notes |
| :--- | :--- | :--- |
| `INITIALIZING` | `ACTIVE`, `FAILED` | Session initialization phase |
| `ACTIVE` | `IDLE`, `PAUSED`, `COMPLETED`, `EXPIRED`, `FAILED` | Standard operational state |
| `IDLE` | `ACTIVE`, `PAUSED`, `COMPLETED`, `EXPIRED`, `FAILED` | Inactive operational state |
| `PAUSED` | `ACTIVE`, `COMPLETED`, `EXPIRED`, `FAILED` | Resuming transitions back to `ACTIVE` |
| `COMPLETED` | *(None)* | **Terminal State**. Transitions out raise `409 Conflict`. |
| `EXPIRED` | *(None)* | **Terminal State**. Transitions out raise `409 Conflict`. |
| `FAILED` | *(None)* | **Terminal State**. Transitions out raise `409 Conflict`. |

### Idempotency Contract

- Sending a lifecycle command matching the session's current state (e.g., calling `pause` on a `PAUSED` session, `resume` on an `ACTIVE` session, or `stop` on a `COMPLETED` session) is an **idempotent no-op**.
- The API responds with `200 OK`, returns the current session object, and does **not** record duplicate events or alter timestamps.

---

## 4. API Specifications & Endpoints

### 4.1 Health and Readiness

#### `GET /health` (or `GET /api/v1/health`)
Returns service health status, runtime mode, and version.
```json
{
  "status": "healthy",
  "timestamp": "2026-11-07T06:30:00.000000Z",
  "service": "Academiaai AI Voicebot Backend",
  "version": "0.1.0",
  "mode": "mock"
}
```

#### `GET /ready` (or `GET /api/v1/ready`)
Verifies readiness of local repositories and mock components.
```json
{
  "status": "ready",
  "timestamp": "2026-11-07T06:30:00.000000Z",
  "service": "Academiaai AI Voicebot Backend",
  "dependencies": {
    "session_repository": "ready",
    "mock_provider": "ready"
  }
}
```

---

### 4.2 Session Creation

#### `POST /api/v1/sessions`
Creates a standard voice session with configurable user ID, metadata, and custom TTL.

- **Request Body**:
  ```json
  {
    "user_id": "student-alice",
    "metadata": {
      "subject": "Calculus",
      "topic": "Derivatives"
    },
    "ttl_seconds": 1800
  }
  ```
- **Response (`201 Created`)**:
  ```json
  {
    "success": true,
    "data": {
      "session": {
        "session_id": "sess-a1b2c3d4e5",
        "user_id": "student-alice",
        "state": "active",
        "metadata": {
          "mode": "mock",
          "team": "SDE 7",
          "workstream": "W5: Backend, Sessions and Observability",
          "subject": "Calculus",
          "topic": "Derivatives"
        },
        "created_at": "2026-11-07T06:30:00.000000Z",
        "updated_at": "2026-11-07T06:30:00.000000Z",
        "expires_at": "2026-11-07T07:00:00.000000Z",
        "ended_at": null
      },
      "event": {
        "event_id": "evt-a1b2c3d4e5",
        "session_id": "sess-a1b2c3d4e5",
        "event_type": "session.started",
        "payload": {
          "message": "Voice session initialized successfully",
          "user_id": "student-alice",
          "ttl_seconds": 1800,
          "expires_at": "2026-11-07T07:00:00+00:00",
          "mock_mode": true
        },
        "timestamp": "2026-11-07T06:30:00.000000Z"
      }
    }
  }
  ```

#### `POST /api/v1/sessions/mock`
Deterministic mock session generation (retained from Week 1).

---

### 4.3 Lifecycle Operations

#### `POST /api/v1/sessions/{session_id}/pause`
Pauses an active or idle session. Idempotent if already paused.
- **Request Body (Optional)**:
  ```json
  { "reason": "Student paused for a break" }
  ```
- **Response (`200 OK`)**:
  ```json
  {
    "success": true,
    "data": {
      "session_id": "sess-a1b2c3d4e5",
      "state": "paused",
      "metadata": {
        "pause_reason": "Student paused for a break",
        "paused_at": "2026-11-07T06:35:00.000000Z"
      }
    },
    "event": {
      "event_id": "evt-pause-7890",
      "session_id": "sess-a1b2c3d4e5",
      "event_type": "session.paused",
      "payload": {
        "reason": "Student paused for a break",
        "paused_at": "2026-11-07T06:35:00.000000Z"
      }
    }
  }
  ```

#### `POST /api/v1/sessions/{session_id}/resume`
Resumes a paused session to `active`. Refreshes session TTL. Idempotent if already active.

#### `POST /api/v1/sessions/{session_id}/stop`
Stops a session and transitions it to terminal `completed` state. Sets `ended_at`. Idempotent if already completed.

#### `POST /api/v1/sessions/{session_id}/expire`
Explicitly expires a session and transitions it to terminal `expired` state. Sets `ended_at`.

---

### 4.4 Server-Sent Events (SSE) Streaming

#### `GET /api/v1/sessions/{session_id}/events/stream`
Streams session events in chronological order via Server-Sent Events (SSE).

- **Query Parameters**:
  - `since_id` *(optional)*: Replay only events occurring after this event ID.
  - `follow` *(optional, default: false)*: If `true`, keeps the connection open and pushes live events in real-time.
- **Headers**:
  - `Last-Event-ID` *(optional)*: Replays events occurring after this ID (standard SSE reconnect header).
- **Stream Format**:
  ```http
  HTTP/1.1 200 OK
  Content-Type: text/event-stream
  Cache-Control: no-cache
  Connection: keep-alive

  : connected to session sess-a1b2c3d4e5

  id: evt-a1b2c3d4e5
  event: session.started
  data: {"event_id":"evt-a1b2c3d4e5","session_id":"sess-a1b2c3d4e5","event_type":"session.started","payload":{...},"timestamp":"2026-11-07T06:30:00Z"}

  id: evt-pause-7890
  event: session.paused
  data: {"event_id":"evt-pause-7890","session_id":"sess-a1b2c3d4e5","event_type":"session.paused","payload":{...},"timestamp":"2026-11-07T06:35:00Z"}
  ```

---

### 4.5 Standard Typed Error Envelope

All error responses strictly adhere to the typed error envelope contract:

```json
{
  "success": false,
  "error": {
    "code": "INVALID_STATE_TRANSITION",
    "message": "Cannot transition session from 'completed' to 'active'. Reason: Transition from 'completed' to 'active' is not permitted.",
    "request_id": "req-9b8a7c6d5e",
    "details": {
      "current_state": "completed",
      "target_state": "active",
      "reason": "Transition from 'completed' to 'active' is not permitted."
    }
  }
}
```

#### Payload Too Large (`413 Payload Too Large`):
```json
{
  "success": false,
  "error": {
    "code": "PAYLOAD_TOO_LARGE",
    "message": "Request payload exceeds maximum allowed size of 1048576 bytes.",
    "request_id": "req-1234567890",
    "details": {
      "max_bytes": 1048576,
      "received_bytes": 1200000
    }
  }
}
```

#### Validation Error (`422 Unprocessable Content`):
```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request payload validation failed.",
    "request_id": "req-0987654321",
    "details": [
      {
        "field": "body -> ttl_seconds",
        "issue": "Input should be greater than 0",
        "type": "greater_than"
      }
    ]
  }
}
```

---

## 5. Startup Configuration & Structured Logging

### 5.1 Configuration Options

All settings are centralized in `app/config.py` and configurable via environment variables:

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `MOCK_MODE` | `bool` | `True` | Standalone mock mode (zero external credentials needed) |
| `HOST` | `str` | `127.0.0.1` | Binding host address |
| `PORT` | `int` | `8000` | Port (validated between 1 and 65535) |
| `LOG_LEVEL` | `str` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `LOG_FORMAT` | `str` | `text` | Log format: `text` or `json` (for log aggregators) |
| `SESSION_TTL_SECONDS`| `int` | `1800` | Default session idle timeout in seconds (30 mins) |
| `MAX_PAYLOAD_SIZE_BYTES` | `int` | `1048576` | Maximum allowed request size in bytes (1MB) |
| `AI_SERVICE_API_KEY` | `str` | `None` | External AI key (required in production mode) |
| `DATABASE_URL` | `str` | `None` | Production database connection string |

### 5.2 Safe Startup & Production Guardrails

- When `MOCK_MODE=True`, the application initializes immediately with safe mock defaults and requires zero credentials.
- When `MOCK_MODE=False` (production), startup validation automatically verifies the existence and validity of `AI_SERVICE_API_KEY` and `DATABASE_URL`. If missing or invalid, the service terminates safely with a `ConfigurationError`.
- Secrets are masked using `settings.safe_dict()`, ensuring API keys and passwords never leak into logs.

### 5.3 Structured Logging & Context Propagation

Every log line captures request and session correlation details:
```
2026-11-07 12:02:24 [INFO] [req_id=req-cd02d9caf60b] [corr_id=req-cd02d9caf60b] [sess_id=sess-937f8b75f9] academiaai: Resumed session sess-937f8b75f9
```
A regex-based `SensitiveDataFilter` automatically scans all log messages and redacts keys, tokens, and authorization headers with `***REDACTED***`.

---

## 6. Getting Started & Verification

### 6.1 Setup Environment

```bash
# Using uv (recommended)
uv venv --python 3.12
uv pip install -r requirements.txt
uv pip install -e .

# Or using standard python
python -m venv .venv
# Windows:
.\.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

### 6.2 Running the Application

Launch the server in standalone mock mode:
```bash
python run_mock.py
```

### 6.3 Executing the Test Suite

Run the full automated test suite covering all 17 test categories:
```bash
pytest -v
```

**Results: 49 passed in ~0.75 seconds.**

### 6.4 Running Interactive Demos

```bash
# Run Week 1 demonstration
python demo_week1.py

# Run Week 2 complete lifecycle & streaming demonstration
python demo_week2.py
```
