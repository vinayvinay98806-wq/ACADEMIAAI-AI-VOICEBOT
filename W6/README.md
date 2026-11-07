# AcademiaAI AI Voice Co-Pilot
## Worker 6 (W6): Frontend & UX — Week 2 Implementation

This directory contains the **Week 2** frontend and user experience implementation for **Worker 6 (W6)** of the AcademiaAI AI Voice Co-Pilot project.

---

### Week 2 Objectives & Capabilities Delivered

1. **Pause and Resume Controls (Days 8–9):**
   - Active voice session supports seamless **Pause** and **Resume** transitions (`idle` → `listening` → `paused` → `listening` → `idle`).
   - Pausing halts audio streaming capture while preserving session continuity, transcript history, and active timer state.
   - Guarded against accidental termination during pause.

2. **Visible Capture State Indicators (Days 8–9):**
   - **Microphone Capture Indicator:** Displays live capture status (`LIVE`, `PAUSED`, `STANDBY`), hardware format (PCM 16kHz Mono), and real-time audio input level percentage.
   - **Screen-Context Capture Indicator:** Clearly indicates visual context status (`OFF (DEFAULT)` vs `ACTIVE (MOCK)`), with a direct toggle action.

3. **Loading, Offline, and Error States (Days 8–9):**
   - **Loading State:** Dedicated synthesis spinner, skeleton placeholder, and accessible `aria-busy` feedback.
   - **Offline Resilience:** Header and panel-level offline banners with one-click **Reconnect** action that restores WebSocket streaming without losing session state.
   - **Error Handling:** Structured error notifications with retry actions.

4. **Live Transcript Segments with Interim & Final Revisions (Days 10–11):**
   - Implements speech-to-text contract aligned with W2 `TranscriptSegment` schema.
   - Distinguishes **Interim** provisional segments (pulsing indicator, dashed boundary, italicized hypothesis) from **Final** confirmed segments (solid boundary, high contrast, confirmed tag).
   - **In-Place Segment Revisions:** When a revised or final transcript arrives with a matching stable `id`, the corresponding segment updates in-place with a revision counter (`rev 2`), strictly eliminating duplicate segments.
   - **Confidence Score Formatting:** Dynamic color-coded pill (`High: >=90%`, `Medium: 75–89%`, `Low: <75%`).
   - Diarized speaker labels and stream inception timestamps (`+0.0s`).

5. **Context and Source Grounding Panel (Days 12–13):**
   - **Screen Context strictly OFF by default:** Guarantees zero unconfirmed visual capture or privacy leakage.
   - Explicit **ON/OFF** user control with clear permission indicator.
   - **Synthetic Demo Fixtures:** Transparently marks mock visual frames (`frame-fixture-014`, Lecture 7 Slide 14 OCR) to prevent false claims of live desktop recording.
   - **Grounded Academic Sources:** Ingests W3 `SourceReference` contracts (e.g. Vaswani et al. 2017 Attention paper, Course Syllabus Module 4, Lecture Slides) with relevance match percentages.
   - **Academic Privacy Shield:** Client-side sanitization masking confidential student IDs, grades, and credential tokens.

6. **Automated UI Testing & Demonstration (Day 14):**
   - Comprehensive Vitest + React Testing Library test suite (`27 tests across 5 test suites`).
   - Mock-backend demonstration script (`scripts/demo_week2.js`).

---

### Project Structure

```text
W6/
├── academiaai-frontend/
│   ├── public/
│   ├── scripts/
│   │   └── demo_week2.js                 # Terminal mock-backend demonstration
│   ├── src/
│   │   ├── __tests__/                     # Vitest + RTL UI test suite
│   │   │   ├── ContextSourcePanel.test.tsx
│   │   │   ├── HeaderAndAlerts.test.tsx
│   │   │   ├── TranscriptPanel.test.tsx
│   │   │   ├── VoiceControlPanel.test.tsx
│   │   │   └── useVoiceCopilot.test.ts
│   │   ├── api/
│   │   │   └── copilotApi.ts             # Typed API client with W5/W2/W3 mock contracts
│   │   ├── components/
│   │   │   ├── approval/                 # HITL sensitive action approval modals
│   │   │   ├── context/                  # Week 2 Context & Grounded Source Panel
│   │   │   │   └── ContextSourcePanel.tsx
│   │   │   ├── layout/                   # Header bar, Alert banner stack
│   │   │   ├── privacy/                  # Scope selector & privacy shield
│   │   │   ├── transcript/               # Live transcripts & AI synthesis cards
│   │   │   ├── voice/                    # Voice controls & animated audio waveform
│   │   │   └── workflow/                 # Agentic workflow step tracker
│   │   ├── hooks/
│   │   │   └── useVoiceCopilot.ts        # Central copilot state management hook
│   │   ├── mock/
│   │   │   └── mockData.ts               # Grounded academic fixtures & contracts
│   │   ├── styles/
│   │   │   └── dashboard.css             # Dark-mode dashboard theme & animations
│   │   ├── test/
│   │   │   └── setup.ts                  # Jest-DOM matchers setup for Vitest
│   │   ├── types/
│   │   │   └── copilot.ts                # TypeScript schemas for frontend
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
├── README.md
└── PULL_REQUEST.md
```

---

### Getting Started & Verification Commands

All commands are run from the `academiaai-frontend` directory:

```powershell
cd academiaai-frontend
```

#### 1. Running Unit & UI Tests
Execute the complete automated test suite (all 27 tests):
```powershell
npm test
```

#### 2. Running the Mock Backend Demonstration
Run the end-to-end simulated demonstration script showcasing all Week 2 behaviors:
```powershell
npm run demo
```

#### 3. Building for Production
Verify compilation and bundle generation:
```powershell
npm run build
```

#### 4. Running Code Linter
Verify code style and rules of hooks:
```powershell
npm run lint
```

#### 5. Starting the Local Development Server
Launch the interactive web application in mock mode:
```powershell
npm run dev
```
