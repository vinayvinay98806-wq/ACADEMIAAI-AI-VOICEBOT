/**
 * Typed API Client for AcademiaAI Voice Co-Pilot
 * Connects Frontend (W6) with backend session state machine (W5),
 * STT speech transcript engine (W2), and Context & Reasoning (W3).
 *
 * Mock mode is the robust default, allowing standalone verification.
 */

import type {
  SessionState,
  TranscriptItem,
  ScreenContextData,
  AcademicSourceReference,
} from '../types/copilot';
import {
  INITIAL_SCREEN_CONTEXT,
  INITIAL_ACADEMIC_SOURCES,
} from '../mock/mockData';

export interface ApiClientConfig {
  baseUrl?: string;
  mockMode?: boolean;
  requestTimeoutMs?: number;
}

export class CopilotApiError extends Error {
  code: string;
  details?: unknown;

  constructor(message: string, code: string = 'API_ERROR', details?: unknown) {
    super(message);
    this.name = 'CopilotApiError';
    this.code = code;
    this.details = details;
  }
}

export class CopilotApiClient {
  private config: Required<ApiClientConfig>;
  private activeSessionId: string | null = null;
  private currentSessionState: SessionState = 'idle';
  private screenContext: ScreenContextData = { ...INITIAL_SCREEN_CONTEXT };

  constructor(config: ApiClientConfig = {}) {
    this.config = {
      baseUrl: config.baseUrl || 'http://localhost:8000',
      mockMode: config.mockMode ?? true, // Mock mode default
      requestTimeoutMs: config.requestTimeoutMs ?? 5000,
    };
  }

  public getSessionId(): string | null {
    return this.activeSessionId;
  }

  public getSessionState(): SessionState {
    return this.currentSessionState;
  }

  /**
   * Initializes or fetches active voicebot session (aligned with W5 session contract).
   */
  public async createSession(userId: string = 'student-priya'): Promise<{ sessionId: string; state: SessionState }> {
    if (this.config.mockMode) {
      this.activeSessionId = `sess-${Date.now().toString(36)}-${Math.random().toString(36).substring(2, 6)}`;
      this.currentSessionState = 'active';
      return { sessionId: this.activeSessionId, state: this.currentSessionState };
    }

    try {
      const response = await fetch(`${this.config.baseUrl}/sessions/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId }),
      });

      if (!response.ok) {
        throw new CopilotApiError(`Failed to create session: ${response.statusText}`, 'SESSION_CREATE_FAILED');
      }

      const json = await response.json();
      this.activeSessionId = json.data?.session?.session_id || json.session_id;
      this.currentSessionState = 'active';
      return { sessionId: this.activeSessionId!, state: this.currentSessionState };
    } catch (err: unknown) {
      if (err instanceof CopilotApiError) throw err;
      throw new CopilotApiError('Network error connecting to session backend', 'NETWORK_OFFLINE', err);
    }
  }

  /**
   * Transitions session state following W5 transition validation rules.
   */
  public async transitionSession(sessionId: string, targetState: SessionState): Promise<{ success: boolean; state: SessionState }> {
    if (this.config.mockMode) {
      this.currentSessionState = targetState;
      return { success: true, state: this.currentSessionState };
    }

    try {
      const response = await fetch(`${this.config.baseUrl}/sessions/${sessionId}/transition`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_state: targetState }),
      });

      if (!response.ok) {
        throw new CopilotApiError(`State transition rejected: ${response.statusText}`, 'INVALID_TRANSITION');
      }

      const json = await response.json();
      this.currentSessionState = json.data?.state || targetState;
      return { success: true, state: this.currentSessionState };
    } catch (err: unknown) {
      if (err instanceof CopilotApiError) throw err;
      throw new CopilotApiError('Failed to synchronize session state transition', 'TRANSITION_ERROR', err);
    }
  }

  /**
   * Pause current active voice session without terminating it.
   */
  public async pauseSession(sessionId: string): Promise<void> {
    await this.transitionSession(sessionId, 'paused');
  }

  /**
   * Resume paused voice session back to active listening.
   */
  public async resumeSession(sessionId: string): Promise<void> {
    await this.transitionSession(sessionId, 'active');
  }

  /**
   * Terminate/Stop voice session.
   */
  public async stopSession(sessionId: string): Promise<void> {
    await this.transitionSession(sessionId, 'completed');
  }

  /**
   * Toggles screen context capture (aligned with W3 ScreenContext schema).
   * Screen context is strictly OFF by default.
   */
  public async updateScreenContext(enabled: boolean): Promise<ScreenContextData> {
    if (this.config.mockMode) {
      this.screenContext = {
        ...this.screenContext,
        captureEnabled: enabled,
        permission: enabled ? 'granted' : 'not-requested',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
        synthetic: true, // Always marks synthetic in mock mode
      };
      return { ...this.screenContext };
    }

    try {
      const response = await fetch(`${this.config.baseUrl}/context/screen`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ capture_enabled: enabled }),
      });

      if (!response.ok) {
        throw new CopilotApiError('Failed to update screen context status', 'SCREEN_CONTEXT_ERROR');
      }

      const data = await response.json();
      this.screenContext = data;
      return this.screenContext;
    } catch (err: unknown) {
      if (err instanceof CopilotApiError) throw err;
      throw new CopilotApiError('Screen context service unreachable', 'NETWORK_OFFLINE', err);
    }
  }

  /**
   * Fetch grounded academic sources (aligned with W3 SourceReference schema).
   */
  public async getAcademicSources(): Promise<AcademicSourceReference[]> {
    if (this.config.mockMode) {
      return [...INITIAL_ACADEMIC_SOURCES];
    }

    try {
      const response = await fetch(`${this.config.baseUrl}/context/sources`);
      if (!response.ok) {
        throw new CopilotApiError('Failed to fetch academic sources', 'SOURCES_FETCH_FAILED');
      }
      return await response.json();
    } catch (err: unknown) {
      if (err instanceof CopilotApiError) throw err;
      throw new CopilotApiError('Academic sources catalog unavailable', 'NETWORK_OFFLINE', err);
    }
  }

  /**
   * Simulates realistic live STT stream with interim revisions followed by finalization.
   * Crucial: Uses a single stable segment_id to demonstrate in-place segment updates!
   */
  public streamTranscriptUtterance(
    utteranceText: string,
    callbacks: {
      onInterim: (segment: TranscriptItem) => void;
      onFinal: (segment: TranscriptItem) => void;
    }
  ): () => void {
    const stableSegmentId = `seg-stt-${Date.now().toString(36)}`;
    const words = utteranceText.split(' ');
    let currentWordIndex = 0;
    let cancelled = false;

    // Distribute into 3-4 interim snapshots then final
    const stepCount = Math.min(4, Math.max(2, Math.floor(words.length / 2)));
    const wordsPerStep = Math.max(1, Math.ceil(words.length / stepCount));

    let revisionCounter = 0;

    const interval = setInterval(() => {
      if (cancelled) {
        clearInterval(interval);
        return;
      }

      currentWordIndex = Math.min(words.length, currentWordIndex + wordsPerStep);
      const isLastStep = currentWordIndex >= words.length;
      revisionCounter += 1;

      const partialText = words.slice(0, currentWordIndex).join(' ');
      const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

      const segment: TranscriptItem = {
        id: stableSegmentId,
        speaker: 'user',
        speakerId: 'Student (You)',
        text: partialText,
        timestamp: now,
        startTime: 0.0,
        endTime: +(revisionCounter * 0.4).toFixed(1),
        confidence: isLastStep ? 0.98 : +(0.75 + (revisionCounter * 0.06)).toFixed(2),
        isFinal: isLastStep,
        language: 'en-US',
        revisionCount: revisionCounter,
        isRevision: true,
      };

      if (isLastStep) {
        clearInterval(interval);
        callbacks.onFinal(segment);
      } else {
        callbacks.onInterim(segment);
      }
    }, 450);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }
}

// Export singleton default client configured for mock mode
export const copilotApi = new CopilotApiClient();
