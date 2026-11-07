import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useVoiceCopilot } from '../hooks/useVoiceCopilot';
import type { TranscriptItem } from '../types/copilot';

describe('useVoiceCopilot hook (Week 2 Core Logic)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it('initializes with default safe state (screen context OFF, idle voice)', () => {
    const { result } = renderHook(() => useVoiceCopilot());

    expect(result.current.voiceState).toBe('idle');
    expect(result.current.connectionStatus).toBe('connected');
    expect(result.current.screenContext.captureEnabled).toBe(false);
    expect(result.current.screenShareStatus).toBe('disabled');
    expect(result.current.microphoneStatus.isCapturing).toBe(false);
    expect(result.current.microphoneStatus.isPaused).toBe(false);
  });

  it('performs full session state transitions: Start -> Pause -> Resume -> Stop', () => {
    const { result } = renderHook(() => useVoiceCopilot());

    // 1. Start listening
    act(() => {
      result.current.startListening();
    });
    expect(result.current.voiceState).toBe('listening');
    expect(result.current.microphoneStatus.isCapturing).toBe(true);
    expect(result.current.microphoneStatus.isPaused).toBe(false);

    // 2. Pause session (crucial: must not terminate session)
    act(() => {
      result.current.pauseListening();
    });
    expect(result.current.voiceState).toBe('paused');
    expect(result.current.microphoneStatus.isCapturing).toBe(false);
    expect(result.current.microphoneStatus.isPaused).toBe(true);
    expect(result.current.audioLevel).toBe(0);

    // 3. Resume session back to listening
    act(() => {
      result.current.resumeListening();
    });
    expect(result.current.voiceState).toBe('listening');
    expect(result.current.microphoneStatus.isCapturing).toBe(true);
    expect(result.current.microphoneStatus.isPaused).toBe(false);

    // 4. Stop session
    act(() => {
      result.current.stopListening();
    });
    expect(result.current.voiceState).toBe('idle');
    expect(result.current.microphoneStatus.isCapturing).toBe(false);
    expect(result.current.microphoneStatus.isPaused).toBe(false);
  });

  it('updates transcript segments in-place when matching IDs arrive', () => {
    const { result } = renderHook(() => useVoiceCopilot());

    const interimSeg: TranscriptItem = {
      id: 'seg-test-stream',
      speaker: 'user',
      text: 'Explaining attention',
      timestamp: '15:30:00',
      isFinal: false,
    };

    act(() => {
      result.current.addOrUpdateTranscriptSegment(interimSeg);
    });

    const initialLength = result.current.transcripts.length;
    const added = result.current.transcripts.find((t) => t.id === 'seg-test-stream');
    expect(added).toBeDefined();
    expect(added?.text).toBe('Explaining attention');
    expect(added?.isFinal).toBe(false);

    // Send final revision with same id
    const finalSeg: TranscriptItem = {
      id: 'seg-test-stream',
      speaker: 'user',
      text: 'Explaining multi-head attention mechanics',
      timestamp: '15:30:02',
      isFinal: true,
      confidence: 0.99,
    };

    act(() => {
      result.current.addOrUpdateTranscriptSegment(finalSeg);
    });

    // Length should remain unchanged (not duplicated!)
    expect(result.current.transcripts.length).toBe(initialLength);

    const updated = result.current.transcripts.find((t) => t.id === 'seg-test-stream');
    expect(updated?.text).toBe('Explaining multi-head attention mechanics');
    expect(updated?.isFinal).toBe(true);
    expect(updated?.confidence).toBe(0.99);
    expect(updated?.revisionCount).toBe(1);
  });

  it('toggles screen context explicitly ON and OFF', async () => {
    const { result } = renderHook(() => useVoiceCopilot());

    expect(result.current.screenContext.captureEnabled).toBe(false);

    await act(async () => {
      await result.current.toggleScreenContext(true);
    });
    expect(result.current.screenContext.captureEnabled).toBe(true);
    expect(result.current.screenShareStatus).toBe('active');
    expect(result.current.screenContext.permission).toBe('granted');
    expect(result.current.screenContext.synthetic).toBe(true);

    await act(async () => {
      await result.current.toggleScreenContext(false);
    });
    expect(result.current.screenContext.captureEnabled).toBe(false);
    expect(result.current.screenShareStatus).toBe('disabled');
  });

  it('handles offline disconnection and reconnects successfully', () => {
    const { result } = renderHook(() => useVoiceCopilot());

    // Cycle connection: connected -> reconnecting -> offline
    act(() => {
      result.current.toggleConnection(); // to reconnecting
    });
    expect(result.current.connectionStatus).toBe('reconnecting');

    act(() => {
      result.current.toggleConnection(); // to offline
    });
    expect(result.current.connectionStatus).toBe('offline');

    // Attempting to listen while offline should create error notification and prevent listening
    act(() => {
      result.current.startListening();
    });
    expect(result.current.voiceState).toBe('idle');
    expect(result.current.notifications.some((n) => n.type === 'error')).toBe(true);

    // Reconnect
    act(() => {
      result.current.reconnect();
    });
    act(() => {
      vi.advanceTimersByTime(850);
    });
    expect(result.current.connectionStatus).toBe('connected');
  });

  it('retries failed workflow step and marks it completed', () => {
    const { result } = renderHook(() => useVoiceCopilot());

    const failedWf = result.current.workflows.find((w) => w.id === 'wf-2');
    expect(failedWf?.status).toBe('failed');

    act(() => {
      result.current.retryWorkflowStep('wf-2', 'c2');
    });

    const retryingWf = result.current.workflows.find((w) => w.id === 'wf-2');
    const retryingStep = retryingWf?.steps.find((s) => s.id === 'c2');
    expect(retryingStep?.status).toBe('running');

    // Fast-forward mock timer
    act(() => {
      vi.advanceTimersByTime(2000);
    });

    const completedWf = result.current.workflows.find((w) => w.id === 'wf-2');
    const completedStep = completedWf?.steps.find((s) => s.id === 'c2');
    expect(completedStep?.status).toBe('completed');
  });
});
