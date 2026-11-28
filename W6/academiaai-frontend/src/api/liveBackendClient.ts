/**
 * Live Backend Client & Event Replay Engine for AcademiaAI Voice Co-Pilot
 * Workstream: W6 Frontend & UX (Week 3: Live Backend Integration & Workflow UX)
 *
 * Integrates directly with:
 * - W5 FastAPI session state machine & event stream (REST & cursor-based event polling/SSE)
 * - W4 Agentic Workflow executor & Human-In-The-Loop approval gates
 * - W2 STT live transcript streaming engine
 * - W3 Context & Reasoning grounding contracts
 *
 * Key Capabilities:
 * 1. Environment-based backend configuration (VITE_API_BASE_URL, VITE_USE_MOCK).
 * 2. Real-time event subscription with exponential backoff reconnection.
 * 3. Cursor-based event replay with guaranteed deduplication (seenEventIds).
 * 4. Strict Rejection Execution Safety: Rejecting an action strictly prevents tool execution.
 * 5. Clean teardown and lifecycle cleanup on component unmount.
 */

import type {
  SessionState,
  ConnectionStatus,
  BackendEvent,
  StreamSubscriptionOptions,
  ApprovalDecisionPayload,
  ScreenContextData,
  AcademicSourceReference,
} from '../types/copilot';
import { INITIAL_SCREEN_CONTEXT, INITIAL_ACADEMIC_SOURCES } from '../mock/mockData';

export interface LiveBackendConfig {
  baseUrl?: string;
  mockMode?: boolean;
  requestTimeoutMs?: number;
  initialBackoffMs?: number;
  maxBackoffMs?: number;
  pollIntervalMs?: number;
}

export class BackendIntegrationError extends Error {
  code: string;
  statusCode?: number;
  details?: unknown;

  constructor(message: string, code = 'INTEGRATION_ERROR', statusCode?: number, details?: unknown) {
    super(message);
    this.name = 'BackendIntegrationError';
    this.code = code;
    this.statusCode = statusCode;
    this.details = details;
  }
}

/**
 * Calculates controlled exponential backoff with jitter.
 */
export function calculateExponentialBackoff(
  attempt: number,
  initialMs = 500,
  maxMs = 8000
): number {
  const base = initialMs * Math.pow(2, Math.max(0, attempt));
  const clamped = Math.min(maxMs, base);
  // Deterministic bounded jitter
  const jitter = ((attempt * 73) % 120);
  return clamped + jitter;
}

export class LiveBackendClient {
  private config: Required<LiveBackendConfig>;
  private activeSessionId: string | null = null;
  private currentSessionState: SessionState = 'idle';
  private screenContext: ScreenContextData = { ...INITIAL_SCREEN_CONTEXT };

  // Replay and connection recovery state
  private lastEventId: string | null = null;
  private seenEventIds: Set<string> = new Set();
  private connectionStatus: ConnectionStatus = 'connected';
  private inFlightDecisions: Set<string> = new Set();

  // Mock event queue for realistic mock backend streaming & replay demonstration
  private mockEventQueue: BackendEvent[] = [];
  private mockEventCursor = 0;

  constructor(config: LiveBackendConfig = {}) {
    const envBaseUrl =
      typeof import.meta !== 'undefined' && import.meta.env
        ? (import.meta.env.VITE_API_BASE_URL as string | undefined)
        : undefined;
    const envMock =
      typeof import.meta !== 'undefined' && import.meta.env
        ? (import.meta.env.VITE_USE_MOCK !== 'false')
        : true;

    this.config = {
      baseUrl: config.baseUrl || envBaseUrl || 'http://localhost:8000',
      mockMode: config.mockMode ?? envMock ?? true,
      requestTimeoutMs: config.requestTimeoutMs ?? 5000,
      initialBackoffMs: config.initialBackoffMs ?? 500,
      maxBackoffMs: config.maxBackoffMs ?? 8000,
      pollIntervalMs: config.pollIntervalMs ?? 1000,
    };
  }

  public getConfig(): Required<LiveBackendConfig> {
    return { ...this.config };
  }

  public setMockMode(mock: boolean): void {
    this.config.mockMode = mock;
  }

  public getSessionId(): string | null {
    return this.activeSessionId;
  }

  public getSessionState(): SessionState {
    return this.currentSessionState;
  }

  public getLastEventId(): string | null {
    return this.lastEventId;
  }

  public getSeenEventCount(): number {
    return this.seenEventIds.size;
  }

  public getConnectionStatus(): ConnectionStatus {
    return this.connectionStatus;
  }

  /**
   * Resets internal tracking cursors (used in new sessions or unit tests).
   */
  public resetCursors(): void {
    this.lastEventId = null;
    this.seenEventIds.clear();
    this.mockEventCursor = 0;
    this.inFlightDecisions.clear();
  }

  /**
   * Initializes or connects to a voice session (aligned with W5 session contract).
   */
  public async createSession(userId = 'student-priya'): Promise<{ sessionId: string; state: SessionState }> {
    this.resetCursors();

    if (this.config.mockMode) {
      this.activeSessionId = `mock-sess-${Date.now().toString(36)}-${Math.random().toString(36).substring(2, 6)}`;
      this.currentSessionState = 'active';

      // Seed initial mock session started event
      const initialEvent: BackendEvent = {
        event_id: `evt-init-${Date.now()}`,
        session_id: this.activeSessionId,
        event_type: 'session.started',
        payload: {
          user_id: userId,
          bot_name: 'AcademiaAI-Voicebot',
          mode: 'mock',
          sample_rate_hz: 16000,
          initial_prompt: 'AcademiaAI voice session initialized. Listening for queries...',
        },
        timestamp: new Date().toISOString(),
      };
      this.recordEvent(initialEvent);

      return { sessionId: this.activeSessionId, state: this.currentSessionState };
    }

    try {
      // First attempt W5 mock session endpoint, then fallback to standard session endpoint
      const response = await fetch(`${this.config.baseUrl}/sessions/mock`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId }),
      });

      if (!response.ok) {
        // Fallback to /sessions/
        const fallbackRes = await fetch(`${this.config.baseUrl}/sessions/`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: userId }),
        });

        if (!fallbackRes.ok) {
          throw new BackendIntegrationError(
            `Failed to initialize session: ${response.statusText}`,
            'SESSION_CREATE_FAILED',
            response.status
          );
        }

        const fallbackJson = await fallbackRes.json();
        this.activeSessionId = fallbackJson.data?.session_id || fallbackJson.session_id || fallbackJson.id;
        this.currentSessionState = 'active';
        return { sessionId: this.activeSessionId!, state: this.currentSessionState };
      }

      const json = await response.json();
      this.activeSessionId = json.data?.session?.session_id || json.data?.session_id || json.session_id;
      this.currentSessionState = 'active';

      if (json.data?.event) {
        const ev = json.data.event;
        this.recordEvent({
          event_id: ev.event_id,
          session_id: ev.session_id,
          event_type: ev.event_type,
          payload: ev.payload || {},
          timestamp: ev.timestamp || new Date().toISOString(),
        });
      }

      return { sessionId: this.activeSessionId!, state: this.currentSessionState };
    } catch (err: unknown) {
      if (err instanceof BackendIntegrationError) throw err;
      throw new BackendIntegrationError(
        'Network error connecting to session backend. Ensure backend is running.',
        'NETWORK_OFFLINE',
        0,
        err
      );
    }
  }

  /**
   * Fetches current session details from backend.
   */
  public async getSession(sessionId: string): Promise<{ session_id: string; state: SessionState }> {
    if (this.config.mockMode) {
      return { session_id: sessionId, state: this.currentSessionState };
    }

    try {
      const response = await fetch(`${this.config.baseUrl}/sessions/${sessionId}`);
      if (!response.ok) {
        throw new BackendIntegrationError(`Session not found: ${sessionId}`, 'SESSION_NOT_FOUND', response.status);
      }
      const json = await response.json();
      const state = json.data?.state || json.state || 'active';
      this.currentSessionState = state;
      return { session_id: sessionId, state };
    } catch (err: unknown) {
      if (err instanceof BackendIntegrationError) throw err;
      throw new BackendIntegrationError('Failed to fetch session state', 'NETWORK_OFFLINE', 0, err);
    }
  }

  /**
   * Transitions session state following W5 state machine rules.
   */
  public async transitionSession(
    sessionId: string,
    targetState: SessionState
  ): Promise<{ success: boolean; state: SessionState }> {
    if (this.config.mockMode) {
      const prev = this.currentSessionState;
      this.currentSessionState = targetState;
      this.recordEvent({
        event_id: `evt-trans-${Date.now().toString(36)}`,
        session_id: sessionId,
        event_type: 'session.state_changed',
        payload: { previous_state: prev, new_state: targetState },
        timestamp: new Date().toISOString(),
      });
      return { success: true, state: this.currentSessionState };
    }

    try {
      const response = await fetch(`${this.config.baseUrl}/sessions/${sessionId}/transition`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_state: targetState }),
      });

      if (!response.ok) {
        throw new BackendIntegrationError(
          `Session state transition rejected: ${response.statusText}`,
          'INVALID_TRANSITION',
          response.status
        );
      }

      const json = await response.json();
      const newState = json.data?.state || targetState;
      this.currentSessionState = newState;
      return { success: true, state: this.currentSessionState };
    } catch (err: unknown) {
      if (err instanceof BackendIntegrationError) throw err;
      throw new BackendIntegrationError('Failed to transition session state', 'NETWORK_OFFLINE', 0, err);
    }
  }

  /**
   * Fetches session events for cursor-based replay.
   */
  public async fetchEvents(sessionId: string, sinceEventId?: string | null): Promise<BackendEvent[]> {
    if (this.config.mockMode) {
      return this.getMockEventsSince(sinceEventId);
    }

    try {
      const url = new URL(`${this.config.baseUrl}/sessions/${sessionId}/events`);
      if (sinceEventId) {
        url.searchParams.set('since_id', sinceEventId);
      }

      const response = await fetch(url.toString());
      if (!response.ok) {
        throw new BackendIntegrationError(`Failed to fetch events: ${response.statusText}`, 'EVENTS_FETCH_FAILED', response.status);
      }

      const json = await response.json();
      const rawEvents: Array<{
        event_id: string;
        session_id: string;
        event_type: string;
        payload: Record<string, unknown>;
        timestamp: string;
      }> = json.events || json.data?.events || [];

      return rawEvents.map((e) => ({
        event_id: e.event_id,
        session_id: e.session_id,
        event_type: e.event_type,
        payload: e.payload,
        timestamp: e.timestamp,
      }));
    } catch (err: unknown) {
      if (err instanceof BackendIntegrationError) throw err;
      throw new BackendIntegrationError('Event stream service unavailable', 'NETWORK_OFFLINE', 0, err);
    }
  }

  /**
   * Core Real-Time Event Subscription with:
   * - Automatic reconnect with exponential backoff
   * - Cursor-based replay of missed events (lastEventId)
   * - In-order processing and deduplication (seenEventIds)
   * - Disconnection detection and cleanup
   */
  public subscribeToEvents(
    sessionId: string,
    options: StreamSubscriptionOptions
  ): () => void {
    let isTerminated = false;
    let pollTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectAttempt = 0;

    const notifyStatus = (status: ConnectionStatus) => {
      this.connectionStatus = status;
      options.onStatusChange?.(status);
    };

    // Helper to safely dispatch events in order without duplication
    const dispatchEvents = (events: BackendEvent[]) => {
      if (isTerminated) return;

      // Sort by timestamp or sequence to guarantee in-order delivery
      const sorted = [...events].sort(
        (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
      );

      for (const ev of sorted) {
        if (isTerminated) return;
        if (!this.seenEventIds.has(ev.event_id)) {
          this.seenEventIds.add(ev.event_id);
          this.lastEventId = ev.event_id;
          options.onEvent(ev);
        }
      }
    };

    const pollCycle = async () => {
      if (isTerminated) return;

      try {
        const events = await this.fetchEvents(sessionId, this.lastEventId);
        if (isTerminated) return;

        if (this.connectionStatus !== 'connected') {
          notifyStatus('connected');
        }
        reconnectAttempt = 0;

        if (events && events.length > 0) {
          dispatchEvents(events);
        }

        // Schedule next regular poll
        if (!isTerminated) {
          pollTimer = setTimeout(pollCycle, this.config.pollIntervalMs);
        }
      } catch (err: unknown) {
        if (isTerminated) return;

        // Disconnection detected!
        notifyStatus('reconnecting');
        const errorObj = err instanceof Error ? err : new Error(String(err));
        options.onError?.(errorObj);

        // Calculate exponential backoff delay with jitter
        const backoffDelay = calculateExponentialBackoff(
          reconnectAttempt,
          this.config.initialBackoffMs,
          this.config.maxBackoffMs
        );
        reconnectAttempt += 1;

        // Wait backoff period, then attempt reconnection & event replay
        pollTimer = setTimeout(async () => {
          if (isTerminated) return;

          try {
            // Replay all events since the last successfully processed event ID cursor
            const replayedEvents = await this.fetchEvents(sessionId, this.lastEventId);
            if (isTerminated) return;

            notifyStatus('connected');
            reconnectAttempt = 0;

            if (replayedEvents && replayedEvents.length > 0) {
              dispatchEvents(replayedEvents);
            }

            // Resume normal polling
            if (!isTerminated) {
              pollTimer = setTimeout(pollCycle, this.config.pollIntervalMs);
            }
          } catch {
            // Re-schedule another reconnect backoff
            if (!isTerminated) {
              pollCycle();
            }
          }
        }, backoffDelay);
      }
    };

    // Start initial polling cycle immediately
    pollCycle();

    // Return cleanup function to tear down subscription
    return () => {
      isTerminated = true;
      if (pollTimer) {
        clearTimeout(pollTimer);
        pollTimer = null;
      }
    };
  }

  // ==========================================
  // SAFE HUMAN-IN-THE-LOOP APPROVAL / REJECTION
  // ==========================================

  /**
   * Submits an explicit approval decision for a sensitive action.
   */
  public async submitApproval(
    requestId: string,
    actionId: string,
    note?: string
  ): Promise<ApprovalDecisionPayload> {
    const key = `approve-${requestId}-${actionId}`;
    if (this.inFlightDecisions.has(key)) {
      throw new BackendIntegrationError(
        'Approval decision already submitted and in flight',
        'DUPLICATE_SUBMISSION'
      );
    }
    this.inFlightDecisions.add(key);

    const nowIso = new Date().toISOString();
    const payload: ApprovalDecisionPayload = {
      request_id: requestId,
      action_id: actionId,
      decision: 'APPROVED',
      decision_reason: note || 'Explicit approval granted by reviewer',
      timestamp: nowIso,
    };

    if (this.config.mockMode) {
      this.inFlightDecisions.delete(key);
      this.recordEvent({
        event_id: `evt-appr-${Date.now().toString(36)}`,
        session_id: this.activeSessionId || 'mock-sess',
        event_type: 'workflow.approval_decided',
        payload: { ...payload },
        timestamp: nowIso,
      });
      return payload;
    }

    try {
      const response = await fetch(`${this.config.baseUrl}/workflows/approvals/${requestId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action_id: actionId,
          decision_reason: payload.decision_reason,
        }),
      });

      if (!response.ok) {
        throw new BackendIntegrationError(
          `Approval endpoint rejected submission: ${response.statusText}`,
          'APPROVAL_FAILED',
          response.status
        );
      }

      this.inFlightDecisions.delete(key);
      return payload;
    } catch (err: unknown) {
      this.inFlightDecisions.delete(key);
      if (err instanceof BackendIntegrationError) throw err;
      throw new BackendIntegrationError('Approval service unreachable', 'NETWORK_OFFLINE', 0, err);
    }
  }

  /**
   * CRITICAL SAFETY REQUIREMENT:
   * Submits an explicit REJECTION decision for a sensitive action.
   *
   * Rejecting an action strictly prevents tool execution!
   * - Calls the dedicated rejection endpoint independently.
   * - NEVER triggers execution or the approval endpoint.
   * - Enforces idempotency and safe state updates.
   */
  public async submitRejection(
    requestId: string,
    actionId: string,
    reason?: string
  ): Promise<ApprovalDecisionPayload> {
    const key = `reject-${requestId}-${actionId}`;
    if (this.inFlightDecisions.has(key)) {
      throw new BackendIntegrationError(
        'Rejection decision already submitted and in flight',
        'DUPLICATE_SUBMISSION'
      );
    }
    this.inFlightDecisions.add(key);

    const nowIso = new Date().toISOString();
    const payload: ApprovalDecisionPayload = {
      request_id: requestId,
      action_id: actionId,
      decision: 'REJECTED',
      decision_reason: reason || 'Action rejected by reviewer. Execution blocked.',
      timestamp: nowIso,
    };

    if (this.config.mockMode) {
      this.inFlightDecisions.delete(key);
      this.recordEvent({
        event_id: `evt-rej-${Date.now().toString(36)}`,
        session_id: this.activeSessionId || 'mock-sess',
        event_type: 'workflow.approval_decided',
        payload: { ...payload },
        timestamp: nowIso,
      });
      return payload;
    }

    try {
      const response = await fetch(`${this.config.baseUrl}/workflows/approvals/${requestId}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action_id: actionId,
          decision_reason: payload.decision_reason,
        }),
      });

      if (!response.ok) {
        throw new BackendIntegrationError(
          `Rejection endpoint returned error: ${response.statusText}`,
          'REJECTION_FAILED',
          response.status
        );
      }

      this.inFlightDecisions.delete(key);
      return payload;
    } catch (err: unknown) {
      this.inFlightDecisions.delete(key);
      if (err instanceof BackendIntegrationError) throw err;
      throw new BackendIntegrationError('Rejection service unreachable', 'NETWORK_OFFLINE', 0, err);
    }
  }

  // ==========================================
  // SCREEN CONTEXT & PRIVACY SETTINGS
  // ==========================================

  /**
   * Updates screen context capture status.
   * CRITICAL PRIVACY RULE: Screen context capture MUST default to FALSE.
   */
  public async updateScreenContext(enabled: boolean): Promise<ScreenContextData> {
    if (this.config.mockMode) {
      this.screenContext = {
        ...this.screenContext,
        captureEnabled: enabled,
        permission: enabled ? 'granted' : 'not-requested',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
        synthetic: true,
      };

      this.recordEvent({
        event_id: `evt-ctx-${Date.now().toString(36)}`,
        session_id: this.activeSessionId || 'mock-sess',
        event_type: 'context.screen_updated',
        payload: { capture_enabled: enabled, synthetic: true },
        timestamp: new Date().toISOString(),
      });

      return { ...this.screenContext };
    }

    try {
      const response = await fetch(`${this.config.baseUrl}/context/screen`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ capture_enabled: enabled }),
      });

      if (!response.ok) {
        throw new BackendIntegrationError('Screen context service error', 'SCREEN_CONTEXT_ERROR', response.status);
      }

      const data = await response.json();
      this.screenContext = data;
      return this.screenContext;
    } catch (err: unknown) {
      if (err instanceof BackendIntegrationError) throw err;
      throw new BackendIntegrationError('Screen context service unreachable', 'NETWORK_OFFLINE', 0, err);
    }
  }

  /**
   * Retrieves academic sources grounded in W3 contracts.
   */
  public async getAcademicSources(): Promise<AcademicSourceReference[]> {
    if (this.config.mockMode) {
      return [...INITIAL_ACADEMIC_SOURCES];
    }

    try {
      const response = await fetch(`${this.config.baseUrl}/context/sources`);
      if (!response.ok) {
        throw new BackendIntegrationError('Failed to fetch academic sources', 'SOURCES_FETCH_FAILED', response.status);
      }
      return await response.json();
    } catch (err: unknown) {
      if (err instanceof BackendIntegrationError) throw err;
      throw new BackendIntegrationError('Academic sources catalog unavailable', 'NETWORK_OFFLINE', 0, err);
    }
  }

  // ==========================================
  // MOCK EVENT REPLAY & TEST HARNESS HELPERS
  // ==========================================

  /**
   * Pushes a backend event into the local event journal.
   */
  public recordEvent(event: BackendEvent): void {
    this.mockEventQueue.push(event);
  }

  /**
   * Returns unread events for replay based on sinceEventId cursor.
   */
  public getMockEventsSince(sinceEventId?: string | null): BackendEvent[] {
    if (!sinceEventId) {
      const events = this.mockEventQueue.slice(this.mockEventCursor);
      this.mockEventCursor = this.mockEventQueue.length;
      return events;
    }

    const index = this.mockEventQueue.findIndex((e) => e.event_id === sinceEventId);
    if (index === -1) {
      // If cursor not found, return all unseen events
      return this.mockEventQueue.filter((e) => !this.seenEventIds.has(e.event_id));
    }

    return this.mockEventQueue.slice(index + 1);
  }

  /**
   * Injects mock workflow step event for realistic demonstration.
   */
  public emitWorkflowStepUpdate(
    workflowId: string,
    stepId: string,
    status: 'pending' | 'running' | 'completed' | 'failed' | 'awaiting_approval' | 'rejected' | 'cancelled',
    duration?: string,
    errorDetails?: string
  ): BackendEvent {
    const event: BackendEvent = {
      event_id: `evt-wf-step-${Date.now().toString(36)}-${Math.random().toString(36).substring(2, 6)}`,
      session_id: this.activeSessionId || 'mock-sess',
      event_type: 'workflow.step_updated',
      payload: {
        workflow_id: workflowId,
        step_id: stepId,
        status,
        duration,
        error_details: errorDetails,
      },
      timestamp: new Date().toISOString(),
    };
    this.recordEvent(event);
    return event;
  }
}

// Global live client singleton
export const liveBackendClient = new LiveBackendClient();

