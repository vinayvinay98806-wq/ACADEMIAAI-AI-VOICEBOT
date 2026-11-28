/**
 * Reconnection & Event Replay Test Suite
 * Workstream: W6 Frontend & UX (Week 3)
 * Tests connection recovery, exponential backoff, cursor replay, in-order dispatch,
 * duplicate event rejection, and subscription cleanup.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { LiveBackendClient } from '../api/liveBackendClient';
import type { BackendEvent, ConnectionStatus } from '../types/copilot';

describe('Event Stream Reconnection & Cursor-Based Replay', () => {
  let client: LiveBackendClient;

  beforeEach(() => {
    vi.useFakeTimers();
    client = new LiveBackendClient({
      mockMode: true,
      initialBackoffMs: 200,
      maxBackoffMs: 1600,
      pollIntervalMs: 100,
    });
    client.resetCursors();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('tracks lastEventId cursor and seen event count', async () => {
    const { sessionId } = await client.createSession('student-priya');

    const receivedEvents: BackendEvent[] = [];
    const unsubscribe = client.subscribeToEvents(sessionId, {
      onEvent: (event) => {
        receivedEvents.push(event);
      },
    });

    // Advance timer to trigger initial poll cycle
    await vi.advanceTimersByTimeAsync(150);

    // Initial session.started event should be received
    expect(receivedEvents.length).toBeGreaterThanOrEqual(1);
    expect(receivedEvents[0].event_type).toBe('session.started');
    expect(client.getLastEventId()).toBe(receivedEvents[0].event_id);
    expect(client.getSeenEventCount()).toBeGreaterThanOrEqual(1);

    unsubscribe();
  });

  it('strictly rejects duplicate events during replay', async () => {
    const { sessionId } = await client.createSession('student-priya');

    const receivedEventIds: string[] = [];
    const unsubscribe = client.subscribeToEvents(sessionId, {
      onEvent: (event) => {
        receivedEventIds.push(event.event_id);
      },
    });

    await vi.advanceTimersByTimeAsync(150);

    // Push two identical events with the same event_id
    const duplicateId = 'evt-duplicate-test-001';
    const testEvent: BackendEvent = {
      event_id: duplicateId,
      session_id: sessionId,
      event_type: 'workflow.step_updated',
      payload: { step_id: 's1', status: 'completed' },
      timestamp: new Date().toISOString(),
    };

    client.recordEvent(testEvent);
    client.recordEvent(testEvent); // Duplicate insertion

    await vi.advanceTimersByTimeAsync(200);

    // Verify duplicateId appears EXACTLY ONCE
    const occurrences = receivedEventIds.filter((id) => id === duplicateId);
    expect(occurrences.length).toBe(1);

    unsubscribe();
  });

  it('processes replayed events in strict timestamp order', async () => {
    const { sessionId } = await client.createSession('student-priya');

    // Create 3 events with out-of-order timestamps
    const now = Date.now();
    const event1: BackendEvent = {
      event_id: 'evt-order-1',
      session_id: sessionId,
      event_type: 'workflow.step_updated',
      payload: { step_id: 's1', status: 'completed' },
      timestamp: new Date(now + 1000).toISOString(),
    };
    const event2: BackendEvent = {
      event_id: 'evt-order-2',
      session_id: sessionId,
      event_type: 'workflow.step_updated',
      payload: { step_id: 's2', status: 'running' },
      timestamp: new Date(now + 2000).toISOString(),
    };
    const event3: BackendEvent = {
      event_id: 'evt-order-3',
      session_id: sessionId,
      event_type: 'workflow.step_updated',
      payload: { step_id: 's3', status: 'pending' },
      timestamp: new Date(now + 3000).toISOString(),
    };

    // Feed them to client queue in reverse order
    client.recordEvent(event3);
    client.recordEvent(event1);
    client.recordEvent(event2);

    const receivedIds: string[] = [];
    const unsubscribe = client.subscribeToEvents(sessionId, {
      onEvent: (event) => {
        if (event.event_id.startsWith('evt-order-')) {
          receivedIds.push(event.event_id);
        }
      },
    });

    await vi.advanceTimersByTimeAsync(150);

    // Must be dispatched in chronological order: event1, event2, event3
    expect(receivedIds).toEqual(['evt-order-1', 'evt-order-2', 'evt-order-3']);

    unsubscribe();
  });

  it('detects stream failure, transitions to reconnecting, and recovers with replay', async () => {
    const { sessionId } = await client.createSession('student-priya');

    let streamFailure = false;
    // Spy on fetchEvents to simulate transient disconnect
    vi.spyOn(client, 'fetchEvents').mockImplementation(async (_sId, sinceId) => {
      if (streamFailure) {
        throw new Error('Connection refused: audio stream dropped');
      }
      return client.getMockEventsSince(sinceId);
    });

    const statuses: ConnectionStatus[] = [];
    const receivedEvents: string[] = [];

    const unsubscribe = client.subscribeToEvents(sessionId, {
      onEvent: (event) => {
        receivedEvents.push(event.event_id);
      },
      onStatusChange: (status) => {
        statuses.push(status);
      },
    });

    // Initial poll
    await vi.advanceTimersByTimeAsync(120);

    // Simulate connection drop
    streamFailure = true;
    await vi.advanceTimersByTimeAsync(120);

    // Status should have switched to 'reconnecting'
    expect(statuses).toContain('reconnecting');
    expect(client.getConnectionStatus()).toBe('reconnecting');

    // While disconnected, new backend events arrive
    const missedEvent: BackendEvent = {
      event_id: 'evt-missed-while-offline',
      session_id: sessionId,
      event_type: 'workflow.step_updated',
      payload: { step_id: 's4', status: 'awaiting_approval' },
      timestamp: new Date().toISOString(),
    };
    client.recordEvent(missedEvent);

    // Restore connection
    streamFailure = false;

    // Advance timers through exponential backoff recovery
    await vi.advanceTimersByTimeAsync(500);

    // Status should be restored to 'connected' and missed event replayed
    expect(statuses).toContain('connected');
    expect(receivedEvents).toContain('evt-missed-while-offline');
    expect(client.getLastEventId()).toBe('evt-missed-while-offline');

    unsubscribe();
  });

  it('cleans up subscription timers on unsubscribe', async () => {
    const { sessionId } = await client.createSession('student-priya');
    const spy = vi.fn();

    const unsubscribe = client.subscribeToEvents(sessionId, {
      onEvent: spy,
    });

    // Immediately teardown
    unsubscribe();

    // Advance time significantly
    await vi.advanceTimersByTimeAsync(2000);

    // No events should be received after teardown
    expect(spy).not.toHaveBeenCalled();
  });
});
