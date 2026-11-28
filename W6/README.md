# AcademiaAI AI Voice Co-Pilot
## Worker 6 (W6): Frontend & UX — Week 3 Implementation

This directory contains the **Week 3** frontend, backend integration, and workflow UX implementation for **Worker 6 (W6)** of the AcademiaAI AI Voice Co-Pilot project.

---

### Week 3 Objectives & Deliverables

1. **Live Backend Integration (Client & Session Lifecycle):**
   - Implemented `LiveBackendClient` (`src/api/liveBackendClient.ts`) connecting the frontend directly to the W5 FastAPI session state machine (`/sessions/mock`, `/sessions/{id}`, `/sessions/{id}/transition`, `/sessions/{id}/events`).
   - Environment-based configuration via `VITE_API_BASE_URL` (default `http://localhost:8000`) and `VITE_USE_MOCK` (default `true` for standalone sandbox execution).
   - Session lifecycle handling: initialization, transitions (`active`, `paused`, `completed`, `failed`), and state synchronization.

2. **Reconnection with Exponential Backoff & Cursor-Based Event Replay:**
   - Real-time event stream subscription (`subscribeToEvents`).
   - Disconnection detection switching status to `reconnecting`.
   - Automatic reconnect with controlled exponential backoff (`calculateExponentialBackoff(attempt, initialMs=500, maxMs=8000)`) with bounded jitter.
   - Cursor-based tracking of `lastEventId`.
   - On reconnect, requests missed events since cursor (`GET /sessions/{sessionId}/events?since_id={lastEventId}`).
   - Guarantees strict in-order chronological dispatch and **zero duplicate events** via `seenEventIds: Set<string>`.
   - Subscription cleanup on unmount or session teardown.

3. **Live Workflow Progress View:**
   - Displays all workflow steps supplied by the backend.
   - Fully supports all backend statuses:
     - `pending`
     - `running` (with active spinner and step badge)
     - `completed` (with checkmark and duration)
     - `failed` (with failure explanation and retry button)
     - `awaiting_approval` (with human review alert notice)
     - `rejected` (with execution blocked notice)
     - `cancelled` (with cancellation tag)
     - `skipped`
   - Dynamically highlights active step and supports workflows with variable/dynamic numbers of steps.

4. **Safe Human-in-the-Loop Approval & Rejection Dialog:**
   - Modal displays: action title, description, risk level pill, impact warning, parameters table, execution safety guarantee, and decision note input.
   - **CRITICAL SAFETY GUARANTEE:**
     - Rejecting an action strictly calls the dedicated rejection endpoint (`submitRejection`), **NEVER** calling the execution target or approval endpoint!
     - Rejected actions remain rejected and mark the workflow step as `rejected`/`blocked`.
     - Duplicate submissions are prevented by disabling all buttons while a submission is in-flight.
     - Rejection failures and network errors are displayed in a structured alert banner.
     - Full keyboard accessibility: focus trapping within the dialog and `Escape` key dismissal.

5. **Privacy Controls & Capture State Indicators:**
   - **Screen Context strictly OFF by default:** Zero visual frames ingested until explicit user action.
   - Visible ON/OFF toggle with immediate visual feedback and permission status.
   - Transparently distinguishes synthetic demonstration fixtures (`Slide 14 OCR`) from live hardware.
   - Privacy Shield active masking student PII.

6. **Comprehensive Automated Test Suite:**
   - 48 automated tests across 9 test suites using Vitest and React Testing Library.
   - 100% test pass rate covering client integration, reconnect/replay, workflow UX, and approval safety.

7. **Working Mock Backend Demonstration:**
   - Interactive CLI demonstration script (`scripts/demo_week3.js` / `npm run demo:week3`).

---

### Project Structure

```text
W6/
├── academiaai-frontend/
│   ├── public/
│   ├── scripts/
│   │   ├── demo_week2.js                 # Week 2 Terminal demonstration
│   │   └── demo_week3.js                 # Week 3 Live Backend & Workflow demonstration
│   ├── src/
│   │   ├── __tests__/                     # Vitest + RTL test suites (48 passing tests)
│   │   │   ├── ApprovalSafety.test.tsx    # Proves rejection execution safety
│   │   │   ├── ContextSourcePanel.test.tsx# Tests privacy controls (OFF by default)
│   │   │   ├── HeaderAndAlerts.test.tsx   # Tests top header & alerts
│   │   │   ├── LiveBackendIntegration.test.ts # Tests client & session contract sync
│   │   │   ├── ReconnectionAndReplay.test.ts # Tests backoff, cursor replay & deduplication
│   │   │   ├── TranscriptPanel.test.tsx   # Tests live interim/final transcripts
│   │   │   ├── VoiceControlPanel.test.tsx # Tests voice controls & capture badges
│   │   │   ├── WorkflowUX.test.tsx        # Tests workflow view across all 8 statuses
│   │   │   └── useVoiceCopilot.test.ts    # Tests copilot state transitions
│   │   ├── api/
│   │   │   ├── copilotApi.ts              # Typed API facade
│   │   │   └── liveBackendClient.ts       # Live backend client & replay engine
│   │   ├── components/
│   │   │   ├── approval/
│   │   │   │   ├── ActionApprovalModal.tsx # Safe approval/rejection modal
│   │   │   │   └── PendingActionsList.tsx  # HITL sensitive actions & audit trail
│   │   │   ├── context/
│   │   │   │   └── ContextSourcePanel.tsx  # Grounded context & privacy controls
│   │   │   ├── layout/
│   │   │   │   ├── AlertBanner.tsx         # Notification toast stack
│   │   │   │   └── Header.tsx              # Brand header & connection status
│   │   │   ├── privacy/
│   │   │   │   └── PrivacyPanel.tsx        # Privacy scope & shield toggle
│   │   │   ├── transcript/
│   │   │   │   ├── AIResponsePanel.tsx     # Grounded AI synthesis output
│   │   │   │   └── TranscriptPanel.tsx     # In-place interim/final transcript view
│   │   │   ├── voice/
│   │   │   │   ├── AudioWaveform.tsx       # Live capture waveform animation
│   │   │   │   └── VoiceControlPanel.tsx   # Session Start, Pause, Resume, Stop
│   │   │   └── workflow/
│   │   │       └── WorkflowTracker.tsx     # Live workflow pipeline progress view
│   │   ├── hooks/
│   │   │   └── useVoiceCopilot.ts         # Central copilot state management hook
│   │   ├── mock/
│   │   │   └── mockData.ts                # Grounded academic fixtures & contracts
│   │   ├── styles/
│   │   │   └── dashboard.css              # Glassmorphic dark dashboard theme
│   │   ├── test/
│   │   │   └── setup.ts                   # Jest-DOM matchers setup for Vitest
│   │   ├── types/
│   │   │   └── copilot.ts                 # TypeScript schemas & backend event contracts
│   │   ├── App.tsx                        # Main 3-column responsive dashboard
│   │   └── main.tsx                       # React 19 application entrypoint
│   ├── package.json
│   └── vite.config.ts
├── README.md
└── PULL_REQUEST.md
```

---

### Startup & Demonstration Commands

#### 1. Run the Automated Test Suite (All 9 Suites / 48 Tests):
```bash
cd academiaai-frontend
npm test
```

#### 2. Run the Week 3 Mock Backend Demonstration:
```bash
cd academiaai-frontend
npm run demo:week3
```

#### 3. Run the Development Server (Interactive UI):
```bash
cd academiaai-frontend
npm run dev
```

#### 4. Build Production Bundle:
```bash
cd academiaai-frontend
npm run build
```
