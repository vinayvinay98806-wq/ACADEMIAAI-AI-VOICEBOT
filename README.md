# Academiaai AI Voicebot Backend (Team SDE 7)

## Workstream W5: Backend, Sessions and Observability — Week 3 Implementation

Welcome to the backend service for the **Academiaai AI Voicebot**, developed by **Team SDE 7**. This repository hosts the implementation of **Workstream W5 (Backend, Sessions, and Observability)** covering **Week 1** foundation, **Week 2** complete session lifecycle & streaming, and **Week 3 (Days 15–21)** cross-workstream module gateways, atomic event replay & reconnect, local token authorization, sliding-window rate limiting, aggregated health monitoring, and end-to-end integration.

---

## 1. Executive Summary & Week 3 Scope

Week 3 integrates the W5 backend with the upstream and downstream workstreams (W1 Audio, W2 STT, W3 Context & Reasoning, W4 Workflow), while hardening the core with production-grade authorization, rate limiting, and zero-loss event streaming:

- **Cross-Workstream Module Gateways (Days 15–16)**:
  - **W1 Audio Gateway**: Interacts with audio pipelines and capture adapters; supports 16kHz PCM chunks and Voice Activity Detection (VAD).
  - **W2 STT Gateway**: Transcribes speech into academic queries; supports confidence scoring, multiple languages, and transcript event normalization.
  - **W3 Context & Reasoning Gateway**: Classifies query intent (`explain_concept`, `schedule_practice`, `general_academic_qa`), checks prerequisites, and grounds responses in academic sources.
  - **W4 Workflow Gateway**: Executes multi-step agentic plans and simulated tool invocations (`academic_lookup`, `student_status_update`).
  - **Gateway Coordinator**: Orchestrates `Audio -> STT -> Reasoning -> Workflow -> Session Events` pipeline under configurable timeouts with unified error normalization (`502 GatewayError`, `504 GatewayTimeoutError`).
  - **Dynamic Fallbacks**: Uses typed `Protocol` abstractions and dynamic module import detection (`app/gateways/module_adapters.py`) with zero-dependency fallback to deterministic mock adapters (`app/gateways/mock_adapters.py`).
- **Atomic Event Replay & Reconnect (Days 17–18)**:
  - **Strict Monotonic Sequence Numbers**: Every event assigned `sequence_number = len(events) + 1` within an atomic lock boundary.
  - **Atomic Queue Registration & Slice**: `subscribe_and_replay()` captures historical event slices and registers live subscriber queues under a single `asyncio.Lock`, eliminating the race window where events could be permanently dropped.
  - **Cursor-Based Replay**: Supports `Last-Event-ID` header and `?since_id=...` query parameter to replay events strictly after client disconnect.
  - **Zero Duplicates & Zero Drops**: In-stream deduplication via `seen_event_ids` ensures seamless continuity.
  - **Bounded Queue Overflow Tracking**: Detects slow client buffer overflows and emits `event: stream.overflow` notifications with re-sync instructions.
- **Local Authorization & Sliding-Window Rate Limiting (Days 19–20)**:
  - **Constant-Time Token Check**: `hmac.compare_digest` protects against timing side-channel attacks.
  - **Typed Error Envelopes**: Rejection with `401 Unauthorized` (missing credentials) and `403 Forbidden` (invalid credentials).
  - **Public Endpoint Whitelist**: `/health`, `/ready`, `/docs`, `/openapi.json` remain publicly accessible.
  - **Sliding-Window Rate Limiting**: In-memory rate limiter with automatic pruning, returning `429 Too Many Requests`, `Retry-After`, and `X-RateLimit-*` headers.
  - **Pluggable Monotonic Clock**: Enables deterministic, zero-sleep testing of rate limit windows.
  - **Client Isolation**: Independent quota tracking by IP address or authentication token.
- **Aggregated Component Health & Diagnostics (Day 21)**:
  - **Liveness Probe (`GET /health`)**: Ultra-lightweight check returning service status.
  - **Aggregated Readiness Probe (`GET /ready`)**: Aggregates `session_repository`, `mock_provider`, `audio_gateway`, `transcription_gateway`, `reasoning_gateway`, `workflow_gateway`, and `event_stream`. Returns `ready`, `degraded`, or `not_ready`.
  - **Diagnostic Report (`GET /api/v1/health/aggregated`)**: Component-level latency, provider types, and error details.
- **Comprehensive Verification & Testing**:
  - **78 automated unit and integration tests** passing with 100% success rate.
  - End-to-end 14-point integration suite (`tests/test_e2e_integration.py`).
  - Interactive demonstration scripts: `demo_week1.py`, `demo_week2.py`, and `demo_week3.py`.

---

## 2. Architecture & Project Structure

The project strictly follows layered architecture principles, decoupling Routers, Gateways, Domain Services, Repositories, and Core Infrastructure:

```
.
├── app/
│   ├── __init__.py                # Package initialization and version definition
│   ├── main.py                    # FastAPI application factory, lifespan startup validation, error handlers
│   ├── config.py                  # Centralized Pydantic Settings & startup configuration validation
│   ├── core/
│   │   ├── __init__.py
│   │   ├── auth.py                # Local token authentication & constant-time comparison guardrails
│   │   ├── exceptions.py          # Domain exceptions (AppException, UnauthorizedError, GatewayError, etc.)
│   │   ├── logging.py             # Structured logging, JSON formatter, contextvars, sensitive data masking
│   │   ├── middleware.py          # Request ID, Correlation ID, Payload Limit, Auth, & Rate Limit middleware
│   │   └── rate_limit.py          # Sliding-window rate limiter with deterministic mock clock support
│   ├── gateways/
│   │   ├── __init__.py            # Gateway package exports
│   │   ├── protocols.py           # Typed gateway protocols (Audio, STT, Reasoning, Workflow) & data containers
│   │   ├── mock_adapters.py       # Deterministic standalone mock adapters for all 4 workstreams
│   │   ├── module_adapters.py     # Dynamic integration adapters importing teammate modules when present
│   │   ├── factory.py             # Dependency injection providers for gateway adapters
│   │   └── coordinator.py         # End-to-end voice interaction coordinator (Audio -> STT -> Reasoning -> Workflow)
│   ├── models/
│   │   ├── __init__.py
│   │   ├── errors.py              # Standardized ErrorDetail and ErrorEnvelope schemas
│   │   ├── health.py              # HealthResponse and ReadinessResponse schemas
│   │   └── session.py             # SessionState enum, Session, SessionEvent, interaction schemas
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── base.py                # BaseSessionRepository interface with atomic replay & pubsub methods
│   │   └── in_memory_session.py   # Thread-safe in-memory store with monotonic sequence & subscribe_and_replay
│   ├── services/
│   │   ├── __init__.py
│   │   └── session_service.py     # Domain service: lifecycle orchestration, idempotency, auto-expiry
│   └── routers/
│       ├── __init__.py
│       ├── health.py              # Liveness (/health), readiness (/ready), and aggregated (/health/aggregated)
│       └── sessions.py            # Session CRUD, lifecycle, SSE streaming, and /interact cross-module endpoint
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # TestClient and repository reset fixtures
│   ├── test_auth_ratelimit.py     # Tests for 401/403 auth guardrails and sliding-window rate limiting
│   ├── test_config_logging.py     # Tests for startup validation, correlation ID, secret masking, JSON logging
│   ├── test_e2e_integration.py    # Comprehensive 14-point end-to-end integration test
│   ├── test_errors.py             # Tests for 404, 422, and 500 error envelopes
│   ├── test_gateways.py           # Unit tests for W1, W2, W3, W4 gateways, coordinator, and /interact
│   ├── test_health.py             # Tests for basic /health and /ready endpoints
│   ├── test_health_aggregation.py # Tests for aggregated readiness, component breakdown, and degraded handling
│   ├── test_lifecycle.py          # Tests for create, pause, resume, stop, expire, idempotency, auto-expiry
│   ├── test_middleware.py         # Tests for ID generation, header preservation, sanitization
│   ├── test_mock_session.py       # Tests for Week 1 mock routes and basic transitions
│   ├── test_replay_reconnect.py   # Tests for monotonic sequence, atomic replay, cursor reconnect, queue overflow
│   ├── test_repository.py         # Unit tests for InMemorySessionRepository
│   ├── test_streaming.py          # Tests for SSE streaming format, chronological order, replay via Last-Event-ID
│   └── test_validation_limits.py  # Tests for 413 payload limits, 422 validation, unknown session 404s
├── pyproject.toml                 # Package configuration (hatchling wheel build target configured)
├── requirements.txt               # Pinned dependencies
├── run_mock.py                    # One-command mock mode launcher
├── demo_week1.py                  # Week 1 interactive demonstration script
├── demo_week2.py                  # Week 2 lifecycle & streaming demonstration script
├── demo_week3.py                  # Week 3 full gateway, replay, auth & rate limiting demonstration script
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
| `AUTH_ENABLED` | `bool` | `False` | Enforce local bearer token authorization on API routes |
| `AUTH_TOKEN` | `str` | `None` | Secret token string for local authorization |
| `RATE_LIMIT_ENABLED` | `bool` | `False` | Enable in-memory sliding-window rate limiting |
| `RATE_LIMIT_REQUESTS` | `int` | `60` | Maximum allowed requests per window |
| `RATE_LIMIT_WINDOW_SECONDS` | `int` | `60` | Sliding window duration in seconds |
| `GATEWAY_TIMEOUT_SECONDS` | `float` | `10.0` | Default timeout for module gateway operations |
| `AUDIO_ADAPTER_TYPE` | `str` | `mock` | W1 Audio adapter: `mock` or `module` |
| `TRANSCRIPTION_ADAPTER_TYPE` | `str` | `mock` | W2 STT adapter: `mock` or `module` |
| `REASONING_ADAPTER_TYPE` | `str` | `mock` | W3 Reasoning adapter: `mock` or `module` |
| `WORKFLOW_ADAPTER_TYPE` | `str` | `mock` | W4 Workflow adapter: `mock` or `module` |

### 5.2 Safe Startup & Production Guardrails

- When `MOCK_MODE=True`, the application initializes immediately with safe mock defaults and requires zero credentials.
- When `MOCK_MODE=False` (production), startup validation automatically verifies the existence and validity of `AI_SERVICE_API_KEY` and `DATABASE_URL`. If missing or invalid, the service terminates safely with a `ConfigurationError`.
- Secrets and tokens are masked using `settings.safe_dict()`, ensuring API keys, passwords, and authorization tokens never leak into logs.

### 5.3 Structured Logging & Context Propagation

Every log line captures request and session correlation details:
```
2026-11-28 11:22:16 [INFO] [req_id=req-9808afcaf971] [corr_id=trace-demo-week3-777] [sess_id=sess-fcfcaff50c] academiaai: Created session: sess-fcfcaff50c
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

Run the full automated test suite covering all Week 1, Week 2, and Week 3 test suites:
```bash
pytest -v
```

**Results: 78 passed, 0 failed in ~2.2 seconds.**

### 6.4 Running Interactive Demos

```bash
# Run Week 1 demonstration
python demo_week1.py

# Run Week 2 complete lifecycle & streaming demonstration
python demo_week2.py

# Run Week 3 module gateways, atomic replay, auth & rate limiting demonstration
python demo_week3.py
```
