# Pull Request: [W6-Week3] Live Backend Integration, Event Replay Engine, Workflow UX & Safe Approval Dialog

## PR Title
`feat(w6): live backend integration, event replay engine, workflow progress view and safe approval flow`

---

## PR Description

### Summary
This pull request implements the complete **Week 3** assignment for **Worker 6 (W6) — Frontend & UX** of the **AcademiaAI AI Voice Co-Pilot** application. It builds on the existing Week 1 and Week 2 foundations to replace fixture-only data with a robust live backend integration layer, real-time event streaming with cursor-based replay and exponential backoff, a live workflow progress tracker reflecting all backend statuses, and a provably safe human-in-the-loop approval and rejection dialog.

All existing Week 1 and Week 2 features, visual styling (glassmorphic dark theme), and schemas have been strictly preserved. Mock mode remains the default, fully aligned with the backend contracts of W5 (Sessions), W4 (Agentic Workflow), W2 (STT), and W3 (Context & Reasoning).

---

## Key Deliverables & Architectural Implementation

### 1. Live Backend Connection & Session Lifecycle
- **LiveBackendClient (`src/api/liveBackendClient.ts`):**
  - Connects to W5 FastAPI session endpoints (`/sessions/mock`, `/sessions/{id}`, `/sessions/{id}/transition`, `/sessions/{id}/events`).
  - Environment-based configuration:
    - `VITE_API_BASE_URL` (defaults to `http://localhost:8000`).
    - `VITE_USE_MOCK` (defaults to `true` to ensure zero external dependency during standalone testing).
  - Handles complete session state machine: `idle` → `active` ↔ `paused` → `completed` / `failed`.
  - Authoritative session event journal recording and synchronization.

### 2. Reconnection with Controlled Exponential Backoff & Cursor Replay
- **Stream Subscription (`subscribeToEvents`):**
  - Tracks `lastEventId` cursor across all session events.
  - Automatically detects stream disconnections and transitions status to `reconnecting`.
  - Implements controlled exponential backoff with bounded jitter (`calculateExponentialBackoff(attempt, initialMs=500, maxMs=8000)`).
  - On reconnection, queries missed backend events since the cursor (`GET /sessions/{sessionId}/events?since_id={lastEventId}`).
  - **In-Order Chronological Delivery:** Replayed events are sorted by timestamp before dispatch.
  - **Zero Duplicate Events:** Enforces `seenEventIds: Set<string>` to guarantee no event is ever processed twice.
  - Clean subscription teardown on component unmount and session termination.

### 3. Workflow Progress View (All Backend States)
- **WorkflowTracker (`src/components/workflow/WorkflowTracker.tsx`):**
  - Renders all workflow steps supplied by the backend.
  - Fully supports all 8 backend statuses:
    1. `pending`: Waiting in queue.
    2. `running`: Active execution with animated spinner and step tags.
    3. `completed`: Successful completion with checkmark and execution duration.
    4. `failed`: Execution failure with structured explanation and retry action.
    5. `awaiting_approval`: Paused awaiting human authorization with amber warning badge.
    6. `rejected`: Operator rejected action with explicit execution blocked notice.
    7. `cancelled`: Upstream cancelled step.
    8. `skipped`: Intentionally bypassed step.
  - Dynamically highlights active step and supports workflows with dynamic numbers of steps.

### 4. Safe Human-in-the-Loop Approval & Rejection Dialog
- **ActionApprovalModal (`src/components/approval/ActionApprovalModal.tsx`):**
  - Displays proposed action, risk level pill (`HIGH`, `MEDIUM`, `LOW`), impact explanation, parameters table, execution safety guarantee, and optional decision note input.
  - **CRITICAL SAFETY GUARANTEE:**
    - Rejecting an action strictly calls the dedicated rejection endpoint (`submitRejection`), **NEVER** triggering tool execution or the approval endpoint.
    - Rejection sets the approval status to `REJECTED`, marks the workflow step as `rejected`, and halts workflow execution safely.
    - Double-click and duplicate submission prevention: All dialog action buttons are disabled while submission is in-flight.
    - Keyboard-accessible focus trapping inside the modal and `Escape` key dismissal.

### 5. Privacy Settings & Capture Indicators
- **ContextSourcePanel (`src/components/context/ContextSourcePanel.tsx`):**
  - **Screen Context strictly OFF by default:** Zero visual frames or window pixels ingested until explicit user action.
  - Visible ON/OFF toggle with immediate visual feedback and permission status.
  - Transparently labels synthetic demonstration fixtures (`Slide 14 OCR`) to avoid false claims of actual desktop recording.
  - Privacy Shield active redacting student PII.

---

## Automated Test Results

### Test Suite Summary: 9/9 Suites Passed (48 Tests)
```text
 ✓ src/__tests__/WorkflowUX.test.tsx (4 tests)
 ✓ src/__tests__/ReconnectionAndReplay.test.ts (5 tests)
 ✓ src/__tests__/LiveBackendIntegration.test.ts (6 tests)
 ✓ src/__tests__/useVoiceCopilot.test.ts (6 tests)
 ✓ src/__tests__/HeaderAndAlerts.test.tsx (3 tests)
 ✓ src/__tests__/ContextSourcePanel.test.tsx (4 tests)
 ✓ src/__tests__/VoiceControlPanel.test.tsx (8 tests)
 ✓ src/__tests__/ApprovalSafety.test.tsx (6 tests)
 ✓ src/__tests__/TranscriptPanel.test.tsx (6 tests)

 Test Files  9 passed (9)
      Tests  48 passed (48)
```

### Safety Tests Proved:
1. `CRITICAL SAFETY: Reject calls ONLY onReject and NEVER calls onApprove or execution`: **PASSED**
2. `Authorize & Execute calls onApprove and NEVER calls onReject`: **PASSED**
3. `prevents duplicate submissions by disabling buttons while in flight`: **PASSED**
4. `strictly rejects duplicate events during replay`: **PASSED**
5. `processes replayed events in strict timestamp order`: **PASSED**
6. `detects stream failure, transitions to reconnecting, and recovers with replay`: **PASSED**

---

## Demonstration Script Output (`npm run demo:week3`)

```text
========================================================================
  ACADEMIAAI VOICE CO-PILOT — WEEK 3 LIVE BACKEND & WORKFLOW DEMO
========================================================================

[STEP 1: LIVE BACKEND CLIENT CONNECTION & CONFIGURATION]
  • Client Type:         LiveBackendClient (W6 Adapter)
  • Configured Base URL: http://localhost:8000 (VITE_API_BASE_URL)
  • Mode:                Mock Backend Mode (Default Robust Sandbox)
  • Initializing session for user: 'student-priya'...
  • Session Created:     mock-sess-demo
  • Initial State:       ACTIVE (SessionState.ACTIVE)
  • Initial Event:       evt-init-001 (session.started)

[STEP 2: REAL-TIME BACKEND EVENT SUBSCRIPTION]
  -> Subscribing to event stream for session: mock-sess-demo
  • Connection Status:   CONNECTED (Latency: 18ms)
  • Cursor Tracking:     lastEventId: evt-init-001
  • Deduplication Cache: seenEventIds.size = 1

[STEP 3: LIVE WORKFLOW PROGRESSION (ALL BACKEND STATES)]
    [COMPLETED] Step step-1: Slide OCR Text Extraction (0.9s)
    [COMPLETED] Step step-2: Attention Formula Verification (1.4s)
    [RUNNING] Step step-3: CrossRef DOI Citation Lookup (Running...)
    [AWAITING_APPROVAL] Step step-4: Canvas LMS Assignment Submission
    [PENDING] Step step-5: Optional Study Sync

[STEP 4: DISCONNECTION, EXPONENTIAL BACKOFF & CURSOR REPLAY]
  -> Simulating transient network drop...
  • Stream Status:       DISCONNECTED
  • UI Feedback:         Reconnecting with controlled exponential backoff...
  • Cursor Preserved:    lastEventId = 'evt-step-003'
  -> Connection Restored!
  • Events Received:     2 missed events replayed in order
  • Duplicate Filter:    0 duplicates detected; both processed cleanly

[STEP 5: SAFE HITL APPROVAL FLOW]
  -> User clicks: [Authorize & Execute]
  • Operation:           Calling POST /workflows/approvals/req-001/approve
  • Result:              DECISION: APPROVED
  • Workflow Step 4:     Transitions to [COMPLETED] (1.1s)

[STEP 6: CRITICAL SAFETY — REJECTION PATH ISOLATION]
  -> Operator clicks: [Reject Action]
  • CRITICAL SAFETY:     Calling DEDICATED Rejection Endpoint: POST /workflows/approvals/req-002/reject
  • Execution Pathway:   STRICTLY BLOCKED — Tool execution is NEVER called!
  • Backend State:       ApprovalRequest status set to 'REJECTED'
  • Workflow Step:       Marked as [REJECTED / BLOCKED]
  • Execution Guarantee: SAFETY PROVEN — Reject never triggers execution!

[STEP 7: PRIVACY CONTROLS & CAPTURE INDICATORS]
  • Screen Context:      OFF BY DEFAULT (Mandatory Privacy Invariant)
  • Status Display:      "Screen Context: OFF" (Audio-only mode, 0 pixels ingested)
  • Hardware Indicator:  Mic: LIVE | Screen: OFF
  • Synthetic Sandbox:   DEMO FIXTURE (Slide 14 OCR)
```

---

## Verification & Build Checklist
- [x] `npm test` passed: 48/48 tests across 9 test suites.
- [x] `npm run demo:week3` passed.
- [x] `npm run build` succeeds cleanly with zero TypeScript errors.
- [x] No credentials, `.env`, or sensitive data committed.
- [x] Feature branch: `feat/w6-week3-backend-workflow`.
