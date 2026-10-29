export type VoiceState = 'idle' | 'listening' | 'processing' | 'responding';

export type ConnectionStatus = 'connected' | 'reconnecting' | 'offline';

export type ScreenShareStatus = 'active' | 'paused' | 'disabled';

export type PrivacyScope = 'fullscreen' | 'window' | 'notes-only';

export type SpeakerRole = 'user' | 'ai' | 'system';

export interface TranscriptItem {
  id: string;
  speaker: SpeakerRole;
  text: string;
  timestamp: string;
  confidence?: number;
  isStreaming?: boolean;
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
}

