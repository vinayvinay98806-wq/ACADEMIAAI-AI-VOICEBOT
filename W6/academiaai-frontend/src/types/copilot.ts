/**
 * AcademiaAI AI Voice Co-Pilot Type Definitions
 * Workstream: W6 Frontend & UX
 * Supports Week 1 baseline and Week 2 extensions (Pause/Resume, Capture Indicators,
 * Live Transcript Segments, Context & Source grounding, Offline/Error states).
 */

export type VoiceState = 'idle' | 'listening' | 'paused' | 'processing' | 'responding' | 'error';

export type SessionState = 'initializing' | 'active' | 'idle' | 'paused' | 'completed' | 'failed';

export type ConnectionStatus = 'connected' | 'reconnecting' | 'offline';

export type ScreenShareStatus = 'active' | 'paused' | 'disabled';

export type PrivacyScope = 'fullscreen' | 'window' | 'notes-only';

export type SpeakerRole = 'user' | 'ai' | 'system';

/**
 * Transcript segment data contract aligned with W2 STT TranscriptSegment schema.
 * Supports interim and final revisions with stable segment_id correlation.
 */
export interface TranscriptItem {
  id: string; // Stable segment_id for interim-to-final correlation
  speaker: SpeakerRole;
  text: string;
  timestamp: string; // Formatted display time
  startTime?: number; // Stream inception offset (seconds)
  endTime?: number; // Stream end offset (seconds)
  confidence?: number; // Normalized [0.0, 1.0]
  isFinal: boolean; // False = interim/provisional, True = finalized
  isStreaming?: boolean;
  language?: string; // BCP-47 language tag (e.g., 'en-US')
  speakerId?: string; // Optional speaker label or diarization ID
  revisionCount?: number; // Count of in-place revisions
  isRevision?: boolean; // Flash highlight on update
}

export type StepStatus = 'pending' | 'running' | 'completed' | 'failed';

export interface WorkflowStep {
  id: string;
  title: string;
  description: string;
  status: StepStatus;
  duration?: string;
  errorDetails?: string;
}

export interface Workflow {
  id: string;
  title: string;
  category: string;
  status: 'idle' | 'in-progress' | 'completed' | 'failed';
  currentStepIndex: number;
  steps: WorkflowStep[];
}

export type RiskLevel = 'low' | 'medium' | 'high';

export interface SensitiveAction {
  id: string;
  title: string;
  description: string;
  impact: string;
  riskLevel: RiskLevel;
  targetSystem: string;
  parameters: Record<string, string>;
  status: 'pending' | 'approved' | 'rejected';
  timestamp: string;
  decisionNote?: string;
}

export interface SystemNotification {
  id: string;
  type: 'info' | 'warning' | 'error' | 'success';
  title: string;
  message: string;
  timestamp: string;
  retryAction?: () => void;
  retryLabel?: string;
}

/**
 * Screen context payload aligned with W3 Context & Reasoning schema.
 * SAFETY RULE: captureEnabled MUST default to False.
 */
export interface ScreenContextData {
  captureEnabled: boolean; // Default FALSE
  frameId?: string;
  timestamp?: string;
  ocrExtractedText?: string;
  activeWindowTitle?: string;
  synthetic: boolean; // True when using synthetic demo fixtures
  permission: 'not-requested' | 'granted' | 'denied';
  metadata?: Record<string, unknown>;
}

/**
 * Grounded Academic Source reference aligned with W3 SourceReference schema.
 */
export interface AcademicSourceReference {
  sourceId: string;
  title: string;
  snippet: string;
  uriOrPath?: string;
  relevanceScore: number;
  sourceType: 'textbook' | 'slide' | 'code' | 'syllabus' | 'transcript';
}

/**
 * Microphone hardware and capture stream status.
 */
export interface MicrophoneCaptureStatus {
  isCapturing: boolean;
  isPaused: boolean;
  volumeLevel: number;
  deviceName: string;
  sampleRate: number;
  channels: number;
  permission: 'granted' | 'prompt' | 'denied';
}

/**
 * Structured error state with retry callback capability.
 */
export interface ErrorState {
  hasError: boolean;
  message: string;
  code?: string;
  timestamp: string;
  retryAction?: () => void;
}
