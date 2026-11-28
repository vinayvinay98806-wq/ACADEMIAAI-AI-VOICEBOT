import { useState, useEffect, useCallback, useRef } from 'react';
import type {
  VoiceState,
  ConnectionStatus,
  ScreenShareStatus,
  PrivacyScope,
  TranscriptItem,
  Workflow,
  StepStatus,
  SensitiveAction,
  SystemNotification,
  ScreenContextData,
  AcademicSourceReference,
  MicrophoneCaptureStatus,
  ErrorState,
  BackendEvent,
} from '../types/copilot';
import {
  INITIAL_TRANSCRIPTS,
  INITIAL_WORKFLOWS,
  INITIAL_SENSITIVE_ACTIONS,
  INITIAL_NOTIFICATIONS,
  INITIAL_SCREEN_CONTEXT,
  INITIAL_ACADEMIC_SOURCES,
} from '../mock/mockData';
import { copilotApi } from '../api/copilotApi';

export function useVoiceCopilot() {
  // Voice & Session States (Week 2 Day 8-9: includes 'paused')
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [voiceState, setVoiceState] = useState<VoiceState>('idle');
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('connected');
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [errorState, setErrorState] = useState<ErrorState | null>(null);

  // Screen Context & Privacy States (Week 2 Day 12-13: Screen context OFF by default)
  const [screenShareStatus, setScreenShareStatus] = useState<ScreenShareStatus>('disabled');
  const [screenContext, setScreenContext] = useState<ScreenContextData>({ ...INITIAL_SCREEN_CONTEXT });
  const [academicSources, setAcademicSources] = useState<AcademicSourceReference[]>(INITIAL_ACADEMIC_SOURCES);
  const [privacyScope, setPrivacyScope] = useState<PrivacyScope>('window');
  const [privacyShieldActive, setPrivacyShieldActive] = useState<boolean>(true);

  // Transcript items (Week 2 Day 10-11: supports interim & final revisions)
  const [transcripts, setTranscripts] = useState<TranscriptItem[]>(INITIAL_TRANSCRIPTS);
  const activeStreamCancelRef = useRef<(() => void) | null>(null);
  const eventUnsubscribeRef = useRef<(() => void) | null>(null);

  // Workflows & Sensitive Actions (HITL)
  const [workflows, setWorkflows] = useState<Workflow[]>(INITIAL_WORKFLOWS);
  const [sensitiveActions, setSensitiveActions] = useState<SensitiveAction[]>(INITIAL_SENSITIVE_ACTIONS);
  const [selectedAction, setSelectedAction] = useState<SensitiveAction | null>(null);

  // System Notifications
  const [notifications, setNotifications] = useState<SystemNotification[]>(INITIAL_NOTIFICATIONS);

  // Audio metrics & Session timer
  const [rawAudioLevel, setRawAudioLevel] = useState<number>(0);
  const [elapsedSeconds, setElapsedSeconds] = useState<number>(1420); // ~23 mins into session

  // Clear pending stream timers on unmount
  useEffect(() => {
    return () => {
      if (activeStreamCancelRef.current) {
        activeStreamCancelRef.current();
      }
    };
  }, []);

  // Audio level simulation: active during 'listening' or 'responding', strictly 0 when 'paused' or 'idle'
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

  // Session timer: ticks while session is active or paused
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

  // Structured notification dispatcher
  const addNotification = useCallback(
    (
      type: SystemNotification['type'],
      title: string,
      message: string,
      retryAction?: () => void,
      retryLabel?: string
    ) => {
      const newNotif: SystemNotification = {
        id: `notif-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`,
        type,
        title,
        message,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
        retryAction,
        retryLabel,
      };
      setNotifications((prev) => [newNotif, ...prev.slice(0, 5)]);
    },
    []
  );

  const dismissNotification = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  }, []);

  // Update or append transcript segment (ensures in-place revisions for matching IDs)
  const addOrUpdateTranscriptSegment = useCallback((segment: TranscriptItem) => {
    setTranscripts((prev) => {
      const existingIndex = prev.findIndex((item) => item.id === segment.id);
      if (existingIndex >= 0) {
        // In-place revision without duplicating the entry
        const next = [...prev];
        const existing = next[existingIndex];
        next[existingIndex] = {
          ...existing,
          ...segment,
          revisionCount: (existing.revisionCount || 0) + 1,
          isRevision: true,
        };
        return next;
      }
      return [...prev, { ...segment, revisionCount: 0, isRevision: false }];
    });
  }, []);

  // Clear transient revision flash animation
  useEffect(() => {
    const timer = setTimeout(() => {
      setTranscripts((prev) => {
        if (!prev.some((t) => t.isRevision)) return prev;
        return prev.map((t) => (t.isRevision ? { ...t, isRevision: false } : t));
      });
    }, 650);
    return () => clearTimeout(timer);
  }, [transcripts]);

  // Backend Event Handler for Live Replay & Progress Tracking
  const handleBackendEvent = useCallback(
    (event: BackendEvent) => {
      switch (event.event_type) {
        case 'session.started': {
          setConnectionStatus('connected');
          break;
        }
        case 'session.state_changed': {
          const payload = event.payload as { new_state?: string };
          if (payload?.new_state === 'paused') {
            setVoiceState('paused');
            setRawAudioLevel(0);
          } else if (payload?.new_state === 'active') {
            setVoiceState('listening');
          } else if (payload?.new_state === 'completed' || payload?.new_state === 'failed') {
            setVoiceState('idle');
            setRawAudioLevel(0);
          }
          break;
        }
        case 'stt.transcript_segment': {
          const payload = event.payload as unknown as TranscriptItem;
          if (payload && payload.id && payload.text) {
            addOrUpdateTranscriptSegment(payload);
          }
          break;
        }
        case 'workflow.step_updated': {
          const payload = event.payload as {
            workflow_id?: string;
            step_id?: string;
            status?: StepStatus;
            duration?: string;
            error_details?: string;
          };
          if (payload?.workflow_id && payload?.step_id && payload?.status) {
            setWorkflows((prev) =>
              prev.map((wf) => {
                if (wf.id !== payload.workflow_id) return wf;
                const nextSteps = wf.steps.map((st) =>
                  st.id === payload.step_id
                    ? {
                        ...st,
                        status: payload.status!,
                        duration: payload.duration ?? st.duration,
                        errorDetails: payload.error_details ?? st.errorDetails,
                      }
                    : st
                );
                const anyFailed = nextSteps.some((s) => s.status === 'failed' || s.status === 'rejected');
                const anyAwaiting = nextSteps.some((s) => s.status === 'awaiting_approval');
                const allCompleted = nextSteps.every((s) => s.status === 'completed');
                const newStatus = anyFailed
                  ? 'failed'
                  : anyAwaiting
                  ? 'awaiting_approval'
                  : allCompleted
                  ? 'completed'
                  : 'in-progress';
                return {
                  ...wf,
                  status: newStatus,
                  steps: nextSteps,
                };
              })
            );
          }
          break;
        }
        case 'workflow.approval_requested': {
          const payload = event.payload as {
            request_id: string;
            workflow_id: string;
            step_id: string;
            action_title?: string;
            action_description?: string;
            impact?: string;
            risk_level?: 'low' | 'medium' | 'high';
            tool_name?: string;
          };
          if (payload?.request_id) {
            const actionItem: SensitiveAction = {
              id: payload.request_id,
              requestId: payload.request_id,
              workflowId: payload.workflow_id,
              stepId: payload.step_id,
              title: payload.action_title || `Execute ${payload.tool_name || 'Sensitive Action'}`,
              description: payload.action_description || 'Action requires operator approval.',
              impact: payload.impact || 'Human-in-the-loop review safeguard enforced.',
              riskLevel: payload.risk_level || 'high',
              targetSystem: payload.tool_name || 'Execution Gateway',
              parameters: {},
              status: 'pending',
              timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
            };
            setSensitiveActions((prev) => {
              const exists = prev.some((a) => a.id === actionItem.id);
              return exists ? prev.map((a) => (a.id === actionItem.id ? actionItem : a)) : [actionItem, ...prev];
            });
            setSelectedAction(actionItem);
            if (payload.workflow_id && payload.step_id) {
              setWorkflows((prev) =>
                prev.map((wf) => {
                  if (wf.id !== payload.workflow_id) return wf;
                  return {
                    ...wf,
                    status: 'awaiting_approval',
                    steps: wf.steps.map((st) =>
                      st.id === payload.step_id ? { ...st, status: 'awaiting_approval' as const } : st
                    ),
                  };
                })
              );
            }
            addNotification(
              'warning',
              'Human Review Required',
              `Action "${actionItem.title}" requires explicit authorization before execution.`
            );
          }
          break;
        }
        case 'workflow.approval_decided': {
          const payload = event.payload as {
            request_id?: string;
            action_id?: string;
            decision?: 'APPROVED' | 'REJECTED';
            decision_reason?: string;
          };
          const id = payload?.action_id || payload?.request_id;
          if (id) {
            const isRejected = payload.decision === 'REJECTED';
            setSensitiveActions((prev) =>
              prev.map((act) =>
                act.id === id || act.requestId === id
                  ? {
                      ...act,
                      status: isRejected ? 'rejected' : 'approved',
                      decisionNote: payload.decision_reason,
                    }
                  : act
              )
            );
          }
          break;
        }
        case 'context.screen_updated': {
          const payload = event.payload as { capture_enabled?: boolean };
          if (typeof payload?.capture_enabled === 'boolean') {
            setScreenContext((prev) => ({
              ...prev,
              captureEnabled: payload.capture_enabled!,
              permission: payload.capture_enabled ? 'granted' : 'not-requested',
            }));
            setScreenShareStatus(payload.capture_enabled ? 'active' : 'disabled');
          }
          break;
        }
        default:
          break;
      }
    },
    [addOrUpdateTranscriptSegment, addNotification]
  );

  // Subscribe to real-time events for active session
  const subscribeSession = useCallback(
    (sessId: string) => {
      if (eventUnsubscribeRef.current) {
        eventUnsubscribeRef.current();
        eventUnsubscribeRef.current = null;
      }
      const unsubscribe = copilotApi.subscribeToEvents(sessId, {
        onEvent: (event: BackendEvent) => {
          handleBackendEvent(event);
        },
        onStatusChange: (status: ConnectionStatus) => {
          setConnectionStatus(status);
          if (status === 'reconnecting') {
            addNotification(
              'warning',
              'Connection Interrupted',
              'Reconnecting with exponential backoff and cursor replay...'
            );
          } else if (status === 'connected') {
            setErrorState(null);
          }
        },
        onError: (err: Error) => {
          setErrorState({
            hasError: true,
            message: err.message,
            code: 'EVENT_STREAM_ERROR',
            timestamp: new Date().toLocaleTimeString(),
            retryAction: () => reconnect(),
          });
        },
      });
      eventUnsubscribeRef.current = unsubscribe;
    },
    [handleBackendEvent, addNotification]
  );

  // Initial session startup
  useEffect(() => {
    let mounted = true;
    copilotApi
      .createSession()
      .then(({ sessionId: newId }) => {
        if (!mounted) return;
        setSessionId(newId);
        subscribeSession(newId);
      })
      .catch((err) => {
        if (!mounted) return;
        const msg = err instanceof Error ? err.message : 'Session initialization failed';
        setConnectionStatus('offline');
        setErrorState({
          hasError: true,
          message: msg,
          code: 'SESSION_INIT_FAILED',
          timestamp: new Date().toLocaleTimeString(),
          retryAction: () => reconnect(),
        });
      });

    return () => {
      mounted = false;
      if (eventUnsubscribeRef.current) {
        eventUnsubscribeRef.current();
        eventUnsubscribeRef.current = null;
      }
    };
  }, [subscribeSession]);

  // Voice Controls: Start, Pause, Resume, Stop
  const startListening = useCallback(() => {
    if (connectionStatus === 'offline') {
      addNotification(
        'error',
        'Cannot Listen',
        'Assistant is currently offline. Please reconnect first.',
        () => {
          setConnectionStatus('connected');
          setVoiceState('listening');
        },
        'Reconnect & Listen'
      );
      return;
    }
    setErrorState(null);
    setVoiceState('listening');
    addNotification('info', 'Microphone Active', 'Listening for speech input... (Press Pause or Stop to control session)');
  }, [connectionStatus, addNotification]);

  const pauseListening = useCallback(() => {
    if (voiceState !== 'listening') return;
    setVoiceState('paused');
    setRawAudioLevel(0);
    addNotification(
      'warning',
      'Session Paused',
      'Microphone stream suspended. Session remains active. Click Resume to continue listening.'
    );
  }, [voiceState, addNotification]);

  const resumeListening = useCallback(() => {
    if (voiceState !== 'paused') return;
    if (connectionStatus === 'offline') {
      addNotification('error', 'Cannot Resume', 'Cannot resume voice session while connection is offline.');
      return;
    }
    setVoiceState('listening');
    addNotification('info', 'Session Resumed', 'Microphone stream re-activated. Ready for speech.');
  }, [voiceState, connectionStatus, addNotification]);

  const stopListening = useCallback(() => {
    if (voiceState === 'idle') return;
    if (activeStreamCancelRef.current) {
      activeStreamCancelRef.current();
      activeStreamCancelRef.current = null;
    }
    setVoiceState('idle');
    setRawAudioLevel(0);
    addNotification('info', 'Session Stopped', 'Voice session halted. Input stream closed.');
  }, [voiceState, addNotification]);

  // Simulate specific voice prompt with live interim revisions
  const simulateVoicePrompt = useCallback(
    (query: string, triggersAction: boolean = false) => {
      if (connectionStatus === 'offline') {
        addNotification('error', 'Simulation Blocked', 'Cannot process prompt while offline. Please reconnect.');
        return;
      }
      if (voiceState === 'processing' || voiceState === 'responding') return;

      // Cancel any ongoing streaming simulation
      if (activeStreamCancelRef.current) {
        activeStreamCancelRef.current();
        activeStreamCancelRef.current = null;
      }

      setErrorState(null);
      setVoiceState('listening');

      // Stream interim segments with in-place revisions
      const cancelStream = copilotApi.streamTranscriptUtterance(query, {
        onInterim: (interimSeg) => {
          addOrUpdateTranscriptSegment(interimSeg);
        },
        onFinal: (finalSeg) => {
          addOrUpdateTranscriptSegment(finalSeg);
          setVoiceState('processing');
          setIsLoading(true);

          // Simulated synthesis latency
          setTimeout(() => {
            setIsLoading(false);
            setVoiceState('responding');

            let aiText = '';
            if (triggersAction) {
              aiText =
                'I have prepared the submission package for Canvas LMS. Because submitting an official assignment impacts your course grading record, human approval is required before execution. Please review the sensitive action prompt.';
            } else if (query.includes('computational complexity')) {
              aiText =
                'Standard self-attention computes scaled dot-products between all pairs of N sequence positions, resulting in O(N² · d) time complexity and O(N²) memory complexity. For long documents, FlashAttention and causal chunking are commonly used to mitigate this quadratic bottleneck.';
            } else if (query.includes('practice questions')) {
              aiText =
                'Here are 3 practice questions on Self-Attention:\n1. Why is the dot product scaled by √d_k in attention computation?\n2. What is the key advantage of multi-head attention over single-head attention?\n3. How does causal masking prevent lookahead in decoder layers?';
            } else if (query.includes('Citation')) {
              aiText =
                'I identified 2 citations. Notice: Devlin et al. (2018) DOI lookup experienced a repository timeout. You can inspect the step in the Workflow tracker and retry.';
            } else {
              aiText =
                'Summary: The current slide presents Multi-Head Attention mechanics with computational complexity O(n² · d). Memory overhead is dominated by sequence length n.';
            }

            const aiItem: TranscriptItem = {
              id: `tx-ai-${Date.now()}`,
              speaker: 'ai',
              speakerId: 'AcademiaAI Co-Pilot',
              text: aiText,
              timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
              startTime: finalSeg.endTime || 1.0,
              endTime: (finalSeg.endTime || 1.0) + 3.5,
              confidence: 0.99,
              isFinal: true,
              language: 'en-US',
            };

            setTranscripts((prev) => [...prev, aiItem]);

            if (triggersAction) {
              const canvasAction = sensitiveActions.find((a) => a.id === 'act-101');
              if (canvasAction) {
                const enrichedAction: SensitiveAction = {
                  ...canvasAction,
                  requestId: 'req-canvas-101',
                  workflowId: 'wf-1',
                  stepId: 's4',
                };
                setSelectedAction(enrichedAction);
                setSensitiveActions((prev) =>
                  prev.map((a) => (a.id === 'act-101' ? enrichedAction : a))
                );
                setWorkflows((prev) =>
                  prev.map((wf) => {
                    if (wf.id !== 'wf-1') return wf;
                    return {
                      ...wf,
                      status: 'awaiting_approval',
                      steps: wf.steps.map((st) =>
                        st.id === 's4'
                          ? {
                              ...st,
                              status: 'awaiting_approval' as const,
                              description: 'Awaiting human authorization for Canvas submission',
                            }
                          : st
                      ),
                    };
                  })
                );
              }
            }

            setVoiceState('idle');
          }, 1800);
        },
      });

      activeStreamCancelRef.current = cancelStream;
    },
    [voiceState, connectionStatus, sensitiveActions, addOrUpdateTranscriptSegment, addNotification]
  );

  // Screen Context ON/OFF (Day 12-13: strictly OFF by default)
  const toggleScreenContextRef = useRef<((explicitState?: boolean) => Promise<void>) | null>(null);

  const toggleScreenContext = useCallback(
    async (explicitState?: boolean) => {
      const nextState = explicitState !== undefined ? explicitState : !screenContext.captureEnabled;
      setIsLoading(true);

      try {
        const updated = await copilotApi.updateScreenContext(nextState);
        setScreenContext(updated);
        setScreenShareStatus(nextState ? 'active' : 'disabled');

        addNotification(
          nextState ? 'success' : 'info',
          'Screen Context ' + (nextState ? 'Enabled (Synthetic Demo)' : 'Disabled'),
          nextState
            ? 'Screen context is now active using synthetic lecture fixture (Slide 14 OCR). Privacy shield protects PII.'
            : 'Screen context turned OFF. Assistant is operating in audio-only mode. No visual data is accessed.'
        );
      } catch (err: unknown) {
        const errorMsg = err instanceof Error ? err.message : 'Unknown context update error';
        setErrorState({
          hasError: true,
          message: errorMsg,
          code: 'SCREEN_CONTEXT_FAILURE',
          timestamp: new Date().toLocaleTimeString(),
          retryAction: () => {
            toggleScreenContextRef.current?.(nextState);
          },
        });
        addNotification(
          'error',
          'Screen Context Error',
          'Failed to update screen capture status. Click retry.',
          () => {
            toggleScreenContextRef.current?.(nextState);
          },
          'Retry'
        );
      } finally {
        setIsLoading(false);
      }
    },
    [screenContext.captureEnabled, addNotification]
  );

  useEffect(() => {
    toggleScreenContextRef.current = toggleScreenContext;
  }, [toggleScreenContext]);

  // Toggle Screen Share for backward compatibility with PrivacyPanel
  const toggleScreenShare = useCallback(() => {
    toggleScreenContext();
  }, [toggleScreenContext]);

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

  // Workflows (HITL retry)
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

      // Mock completion after 1.8s
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
      }, 1800);
    },
    [addNotification]
  );

  // Sensitive Actions (HITL Approval / Rejection with Dedicated Safety)
  const approveAction = useCallback(
    async (actionId: string, note?: string) => {
      const act = sensitiveActions.find((a) => a.id === actionId);
      const reqId = act?.requestId || `req-${actionId}`;
      setIsLoading(true);
      try {
        await copilotApi.submitApproval(reqId, actionId, note);
        setSensitiveActions((prev) =>
          prev.map((a) =>
            a.id === actionId
              ? { ...a, status: 'approved', decisionNote: note || 'Approved by user via dashboard' }
              : a
          )
        );
        if (act?.workflowId && act?.stepId) {
          setWorkflows((prev) =>
            prev.map((wf) => {
              if (wf.id !== act.workflowId) return wf;
              return {
                ...wf,
                status: 'in-progress',
                steps: wf.steps.map((st) =>
                  st.id === act.stepId ? { ...st, status: 'running' as const } : st
                ),
              };
            })
          );
        }
        setSelectedAction(null);
        addNotification(
          'success',
          'Action Approved',
          `Authorized execution for "${act?.title || actionId}". Gateway dispatched.`
        );
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : 'Approval submission error';
        addNotification('error', 'Approval Error', msg);
      } finally {
        setIsLoading(false);
      }
    },
    [sensitiveActions, addNotification]
  );

  const rejectAction = useCallback(
    async (actionId: string, reason: string) => {
      const act = sensitiveActions.find((a) => a.id === actionId);
      const reqId = act?.requestId || `req-${actionId}`;
      setIsLoading(true);
      try {
        // CRITICAL SAFETY REQUIREMENT:
        // Dedicated rejection path, NEVER triggers tool execution or approval!
        await copilotApi.submitRejection(reqId, actionId, reason);
        setSensitiveActions((prev) =>
          prev.map((a) =>
            a.id === actionId
              ? { ...a, status: 'rejected', decisionNote: reason || 'Rejected by user' }
              : a
          )
        );
        // Step is strictly marked as rejected/cancelled and workflow fails safely
        if (act?.workflowId && act?.stepId) {
          setWorkflows((prev) =>
            prev.map((wf) => {
              if (wf.id !== act.workflowId) return wf;
              return {
                ...wf,
                status: 'failed',
                steps: wf.steps.map((st) =>
                  st.id === act.stepId
                    ? {
                        ...st,
                        status: 'rejected' as const,
                        errorDetails: `Execution blocked: Action rejected by human operator (${reason || 'Denied'})`,
                      }
                    : st
                ),
              };
            })
          );
        }
        setSelectedAction(null);
        addNotification(
          'warning',
          'Action Blocked / Rejected',
          `Sensitive action blocked. Tool execution safely prevented. Reason: ${reason || 'Denied by reviewer.'}`
        );
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : 'Rejection submission error';
        addNotification('error', 'Rejection Error', msg);
      } finally {
        setIsLoading(false);
      }
    },
    [sensitiveActions, addNotification]
  );

  // Connection toggle (for testing offline/error states)
  const toggleConnection = useCallback(() => {
    setConnectionStatus((prev) => {
      const next = prev === 'connected' ? 'reconnecting' : prev === 'reconnecting' ? 'offline' : 'connected';
      if (next === 'offline') {
        if (voiceState === 'listening') {
          setVoiceState('paused');
        }
        setErrorState({
          hasError: true,
          message: 'Connection to AcademiaAI audio stream lost. Backend is offline.',
          code: 'OFFLINE_DISCONNECTED',
          timestamp: new Date().toLocaleTimeString(),
          retryAction: () => {
            setConnectionStatus('connected');
            setErrorState(null);
          },
        });
        addNotification(
          'error',
          'Gateway Offline',
          'Connection to AcademiaAI audio stream lost. Click reconnect to restore service.',
          () => {
            setConnectionStatus('connected');
            setErrorState(null);
          },
          'Reconnect Now'
        );
      } else if (next === 'reconnecting') {
        setErrorState(null);
        addNotification('warning', 'Reconnecting', 'Re-synchronizing session state with voice pipeline (jitter: 180ms)...');
      } else {
        setErrorState(null);
        addNotification('success', 'Connected', 'Audio websocket re-established. Latency: 22ms.');
      }
      return next;
    });
  }, [voiceState, addNotification]);

  const reconnect = useCallback(() => {
    setIsLoading(true);
    setConnectionStatus('reconnecting');

    setTimeout(() => {
      setConnectionStatus('connected');
      setErrorState(null);
      setIsLoading(false);
      addNotification('success', 'Reconnected Successfully', 'Live event stream restored. Missed events replayed.');
      const currentId = sessionId || copilotApi.getSessionId() || 'mock-sess-reconnected';
      subscribeSession(currentId);
    }, 800);
  }, [sessionId, subscribeSession, addNotification]);

  const clearTranscripts = useCallback(() => {
    setTranscripts([]);
    addNotification('info', 'Transcript Cleared', 'Live transcript log reset for this session.');
  }, [addNotification]);

  // Derived microphone status
  const microphoneStatus: MicrophoneCaptureStatus = {
    isCapturing: voiceState === 'listening',
    isPaused: voiceState === 'paused',
    volumeLevel: audioLevel,
    deviceName: 'Studio Array Mic (Realtek HD, 48kHz)',
    sampleRate: 16000,
    channels: 1,
    permission: 'granted',
  };

  return {
    sessionId,
    voiceState,
    audioLevel,
    startListening,
    pauseListening,
    resumeListening,
    stopListening,
    simulateVoicePrompt,
    connectionStatus,
    toggleConnection,
    reconnect,
    isLoading,
    errorState,
    setErrorState,
    microphoneStatus,
    screenShareStatus,
    screenContext,
    toggleScreenContext,
    toggleScreenShare,
    academicSources,
    setAcademicSources,
    privacyScope,
    setPrivacyScope,
    privacyShieldActive,
    togglePrivacyShield,
    transcripts,
    addOrUpdateTranscriptSegment,
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
