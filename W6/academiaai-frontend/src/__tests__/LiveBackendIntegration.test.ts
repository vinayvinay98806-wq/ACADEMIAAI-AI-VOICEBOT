/**
 * Live Backend Integration Test Suite
 * Workstream: W6 Frontend & UX (Week 3)
 * Tests live backend API client, session lifecycle, and contract synchronization.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  LiveBackendClient,
  calculateExponentialBackoff,
} from '../api/liveBackendClient';

describe('LiveBackendClient & Backend Contract Integration', () => {
  let client: LiveBackendClient;

  beforeEach(() => {
    client = new LiveBackendClient({ mockMode: true });
    client.resetCursors();
  });

  it('initializes with mock mode as safe default', () => {
    const config = client.getConfig();
    expect(config.mockMode).toBe(true);
    expect(client.getSessionState()).toBe('idle');
    expect(client.getLastEventId()).toBeNull();
  });

  it('creates session and emits initial session.started event', async () => {
    const { sessionId, state } = await client.createSession('student-priya');
    expect(sessionId).toMatch(/^mock-sess-/);
    expect(state).toBe('active');
    expect(client.getSessionState()).toBe('active');
  });

  it('transitions session state following W5 state machine rules', async () => {
    const { sessionId } = await client.createSession('student-priya');

    // Pause session
    const pauseRes = await client.transitionSession(sessionId, 'paused');
    expect(pauseRes.success).toBe(true);
    expect(pauseRes.state).toBe('paused');
    expect(client.getSessionState()).toBe('paused');

    // Resume session
    const resumeRes = await client.transitionSession(sessionId, 'active');
    expect(resumeRes.success).toBe(true);
    expect(resumeRes.state).toBe('active');
    expect(client.getSessionState()).toBe('active');

    // Complete session
    const stopRes = await client.transitionSession(sessionId, 'completed');
    expect(stopRes.success).toBe(true);
    expect(stopRes.state).toBe('completed');
  });

  it('calculates exponential backoff with clamping and jitter', () => {
    const b0 = calculateExponentialBackoff(0, 500, 8000);
    const b1 = calculateExponentialBackoff(1, 500, 8000);
    const b2 = calculateExponentialBackoff(2, 500, 8000);
    const bHigh = calculateExponentialBackoff(10, 500, 8000);

    // Initial backoff should be around 500ms
    expect(b0).toBeGreaterThanOrEqual(500);
    expect(b0).toBeLessThan(700);

    // Bounded growth
    expect(b1).toBeGreaterThanOrEqual(1000);
    expect(b2).toBeGreaterThanOrEqual(2000);

    // Max backoff clamp
    expect(bHigh).toBeLessThanOrEqual(8150);
  });

  it('enforces privacy safety: screen context is OFF by default and updates safely', async () => {
    const initialContext = await client.updateScreenContext(false);
    expect(initialContext.captureEnabled).toBe(false);
    expect(initialContext.permission).toBe('not-requested');

    // Explicit opt-in
    const enabledContext = await client.updateScreenContext(true);
    expect(enabledContext.captureEnabled).toBe(true);
    expect(enabledContext.permission).toBe('granted');
    expect(enabledContext.synthetic).toBe(true); // Always marked synthetic in demo

    // Turn OFF again
    const disabledContext = await client.updateScreenContext(false);
    expect(disabledContext.captureEnabled).toBe(false);
  });

  it('handles live backend fetch fallback when mockMode is false', async () => {
    const liveClient = new LiveBackendClient({
      baseUrl: 'http://localhost:8000',
      mockMode: false,
    });

    // Mock global fetch
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        data: {
          session: { session_id: 'sess-live-99', state: 'active' },
        },
      }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await liveClient.createSession('student-priya');
    expect(result.sessionId).toBe('sess-live-99');
    expect(result.state).toBe('active');
    expect(fetchMock).toHaveBeenCalled();

    vi.unstubAllGlobals();
  });
});
