import { useState, useEffect, useCallback } from 'react';
import type {
  VoiceState,
  ConnectionStatus,
  ScreenShareStatus,
  PrivacyScope,
  TranscriptItem,
  Workflow,
  SensitiveAction,
  SystemNotification,
} from '../types/copilot';
import {
  INITIAL_TRANSCRIPTS,
  INITIAL_WORKFLOWS,
  INITIAL_SENSITIVE_ACTIONS,
  INITIAL_NOTIFICATIONS,
} from '../mock/mockData';

export function useVoiceCopilot() {
  const [voiceState, setVoiceState] = useState<VoiceState>('idle');
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('connected');
  const [screenShareStatus, setScreenShareStatus] = useState<ScreenShareStatus>('active');
  const [privacyScope, setPrivacyScope] = useState<PrivacyScope>('window');
  const [privacyShieldActive, setPrivacyShieldActive] = useState<boolean>(true);

  const [transcripts, setTranscripts] = useState<TranscriptItem[]>(INITIAL_TRANSCRIPTS);
  const [workflows, setWorkflows] = useState<Workflow[]>(INITIAL_WORKFLOWS);
  const [sensitiveActions, setSensitiveActions] = useState<SensitiveAction[]>(INITIAL_SENSITIVE_ACTIONS);
  const [selectedAction, setSelectedAction] = useState<SensitiveAction | null>(null);

  const [notifications, setNotifications] = useState<SystemNotification[]>(INITIAL_NOTIFICATIONS);
  const [rawAudioLevel, setRawAudioLevel] = useState<number>(0);
  const [elapsedSeconds, setElapsedSeconds] = useState<number>(1420); // starts at ~23 mins into session

  // Audio level simulation during listening/responding
  useEffect(() => {
    if (voiceState !== 'listening' && voiceState !== 'responding') {
      return;
    }

    const interval = window.setInterval(() => {
      const base = voiceState === 'listening' ? 40 : 55;
      const randomFactor = Math.floor(Math.random() * 45);
      setRawAudioLevel(Math.min(100, base + randomFactor));
    }, 150);

    return () => {
      clearInterval(interval);
    };
  }, [voiceState]);

  const audioLevel = (voiceState === 'listening' || voiceState === 'responding') ? rawAudioLevel : 0;

  // Session timer
  useEffect(() => {
    const timer = setInterval(() => {
      setElapsedSeconds((prev) => prev + 1);
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const formatSessionTime = (totalSeconds: number) => {
    const hrs = Math.floor(totalSeconds / 3600);
    const mins = Math.floor((totalSeconds % 3600) / 60);
    const secs = totalSeconds % 60;
    return `${hrs.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  const addNotification = useCallback(
    (type: SystemNotification['type'], title: string, message: string) => {
      const newNotif: SystemNotification = {
        id: `notif-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`,
        type,
        title,
        message,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
      };
      setNotifications((prev) => [newNotif, ...prev.slice(0, 4)]);
    },
    []
  );

  const dismissNotification = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  }, []);

  // Voice Controls
  const startListening = useCallback(() => {
    if (connectionStatus === 'offline') {
      addNotification('error', 'Cannot Listen', 'Assistant is currently offline. Please reconnect first.');
      return;
    }
    setVoiceState('listening');
    addNotification('info', 'Microphone Active', 'Listening for speech input... (Press Stop or speak command)');
  }, [connectionStatus, addNotification]);

  const stopListening = useCallback(() => {
    if (voiceState !== 'listening') return;
    setVoiceState('processing');

    // Simulate processing -> responding
    setTimeout(() => {
      const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      const userItem: TranscriptItem = {
        id: `tx-u-${Date.now()}`,
        speaker: 'user',
        text: 'Explain the difference between cross-entropy loss and focal loss for imbalanced training sets.',
        timestamp: now,
        confidence: 0.97,
      };

      setTranscripts((prev) => [...prev, userItem]);
      setVoiceState('responding');

      setTimeout(() => {
        const aiItem: TranscriptItem = {
          id: `tx-ai-${Date.now()}`,
          speaker: 'ai',
          text: 'Cross-entropy treats all samples equally, causing easy negative samples to dominate gradients in class-imbalanced settings. Focal Loss introduces a modulating factor (1 - p_t)^γ with focusing parameter γ, heavily down-weighting well-classified examples so training focuses on hard, underrepresented samples.',
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
          confidence: 0.99,
        };
        setTranscripts((prev) => [...prev, aiItem]);
        setVoiceState('idle');
      }, 3200);
    }, 1500);
  }, [voiceState]);

  // Simulate specific voice prompt click
  const simulateVoicePrompt = useCallback(
    (query: string, triggersAction: boolean = false) => {
      if (voiceState !== 'idle') return;
      setVoiceState('listening');

      setTimeout(() => {
        setVoiceState('processing');
        const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        const userItem: TranscriptItem = {
          id: `tx-u-${Date.now()}`,
          speaker: 'user',
          text: query,
          timestamp: now,
          confidence: 0.98,
        };
        setTranscripts((prev) => [...prev, userItem]);

        setTimeout(() => {
          setVoiceState('responding');
          let aiText = '';

          if (triggersAction) {
            aiText = 'I have prepared the submission package for Canvas LMS. Because submitting an official assignment impacts your course grading record, human approval is required before execution. Please review the sensitive action prompt.';
          } else if (query.includes('practice questions')) {
            aiText = 'Here are 3 practice questions on Self-Attention:\n1. Why is the dot product scaled by √d_k in attention computation?\n2. What is the key advantage of multi-head attention over single-head attention?\n3. How does causal masking prevent lookahead in decoder layers?';
          } else if (query.includes('Citation')) {
            aiText = 'I identified 2 citations. Notice: Devlin et al. (2018) DOI lookup experienced a repository timeout. You can inspect the step in the Workflow tracker and retry.';
          } else {
            aiText = 'Summary: The current slide presents Multi-Head Attention mechanics with computational complexity O(n² · d). Memory overhead is dominated by sequence length n.';
          }

          const aiItem: TranscriptItem = {
            id: `tx-ai-${Date.now()}`,
            speaker: 'ai',
            text: aiText,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
            confidence: 0.99,
          };
          setTranscripts((prev) => [...prev, aiItem]);

          if (triggersAction) {
            const canvasAction = sensitiveActions.find((a) => a.id === 'act-101');
            if (canvasAction) {
              setSelectedAction(canvasAction);
            }
          }

          setVoiceState('idle');
        }, 2200);
      }, 1200);
    },
    [voiceState, sensitiveActions]
  );

  // Privacy toggles
  const toggleScreenShare = useCallback(() => {
    setScreenShareStatus((prev) => {
      const next = prev === 'active' ? 'paused' : prev === 'paused' ? 'disabled' : 'active';
      addNotification(
        next === 'active' ? 'info' : 'warning',
        'Screen Context Updated',
        `Screen-sharing is now ${next.toUpperCase()}. AI vision context ${next === 'active' ? 'enabled' : 'restricted'}.`
      );
      return next;
    });
  }, [addNotification]);

  const togglePrivacyShield = useCallback(() => {
    setPrivacyShieldActive((prev) => {
      const next = !prev;
      addNotification(
        next ? 'success' : 'warning',
        'Privacy Shield',
        next
          ? 'Privacy Shield Active: Student IDs, email addresses, and grades are masked.'
          : 'Privacy Shield Inactive: Raw viewport text visible to assistant.'
      );
      return next;
    });
  }, [addNotification]);

  // Workflows
  const retryWorkflowStep = useCallback(
    (workflowId: string, stepId: string) => {
      setWorkflows((prev) =>
        prev.map((wf) => {
          if (wf.id !== workflowId) return wf;
          return {
            ...wf,
            status: 'in-progress',
            steps: wf.steps.map((st) => (st.id === stepId ? { ...st, status: 'running', errorDetails: undefined } : st)),
          };
        })
      );

      addNotification('info', 'Retrying Step', 'Re-executing CrossRef / Semantic Scholar DOI verification...');

      // Mock completion after 2s
      setTimeout(() => {
        setWorkflows((prev) =>
          prev.map((wf) => {
            if (wf.id !== workflowId) return wf;
            const updatedSteps = wf.steps.map((st) =>
              st.id === stepId ? { ...st, status: 'completed' as const, duration: '1.4s' } : st
            );
            const allDone = updatedSteps.every((s) => s.status === 'completed');
            return {
              ...wf,
              status: allDone ? 'completed' : 'in-progress',
              steps: updatedSteps,
            };
          })
        );
        addNotification('success', 'Step Completed', 'DOI resolution succeeded. Cross-references verified.');
      }, 2000);
    },
    [addNotification]
  );

  // Sensitive Actions (HITL)
  const approveAction = useCallback(
    (actionId: string, note?: string) => {
      setSensitiveActions((prev) =>
        prev.map((act) =>
          act.id === actionId
            ? { ...act, status: 'approved', decisionNote: note || 'Approved by user via dashboard' }
            : act
        )
      );
      setSelectedAction(null);
      addNotification(
        'success',
        'Action Approved',
        `Authorized execution for "${sensitiveActions.find((a) => a.id === actionId)?.title || actionId}". Gateway dispatched.`
      );
    },
    [sensitiveActions, addNotification]
  );

  const rejectAction = useCallback(
    (actionId: string, reason: string) => {
      setSensitiveActions((prev) =>
        prev.map((act) =>
          act.id === actionId
            ? { ...act, status: 'rejected', decisionNote: reason || 'Rejected by user' }
            : act
        )
      );
      setSelectedAction(null);
      addNotification(
        'warning',
        'Action Blocked / Rejected',
        `Sensitive action blocked. Reason: ${reason || 'Denied by reviewer.'}`
      );
    },
    [addNotification]
  );

  // Connection status toggle (for testing offline/error states)
  const toggleConnection = useCallback(() => {
    setConnectionStatus((prev) => {
      const next = prev === 'connected' ? 'reconnecting' : prev === 'reconnecting' ? 'offline' : 'connected';
      if (next === 'offline') {
        addNotification('error', 'Gateway Offline', 'Connection to AcademiaAI audio stream lost. Attempting auto-reconnect...');
      } else if (next === 'reconnecting') {
        addNotification('warning', 'Reconnecting', 'Re-synchronizing session state with voice pipeline (jitter: 180ms)...');
      } else {
        addNotification('success', 'Connected', 'Audio websocket re-established. Latency: 22ms.');
      }
      return next;
    });
  }, [addNotification]);

  const clearTranscripts = useCallback(() => {
    setTranscripts([]);
    addNotification('info', 'Transcript Cleared', 'Live transcript log reset for this session.');
  }, [addNotification]);

  return {
    voiceState,
    audioLevel,
    startListening,
    stopListening,
    simulateVoicePrompt,
    connectionStatus,
    toggleConnection,
    screenShareStatus,
    toggleScreenShare,
    privacyScope,
    setPrivacyScope,
    privacyShieldActive,
    togglePrivacyShield,
    transcripts,
    clearTranscripts,
    workflows,
    retryWorkflowStep,
    sensitiveActions,
    selectedAction,
    setSelectedAction,
    approveAction,
    rejectAction,
    notifications,
    dismissNotification,
    addNotification,
    sessionDuration: formatSessionTime(elapsedSeconds),
  };
}
