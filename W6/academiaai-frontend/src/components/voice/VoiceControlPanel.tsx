import React from 'react';
import type { VoiceState, ConnectionStatus, MicrophoneCaptureStatus } from '../../types/copilot';
import { SAMPLE_VOICE_PROMPTS } from '../../mock/mockData';
import { AudioWaveform } from './AudioWaveform';

export interface VoiceControlPanelProps {
  voiceState: VoiceState;
  audioLevel: number;
  connectionStatus: ConnectionStatus;
  isLoading?: boolean;
  microphoneStatus: MicrophoneCaptureStatus;
  screenContextEnabled: boolean;
  onStartListening: () => void;
  onPauseListening: () => void;
  onResumeListening: () => void;
  onStopListening: () => void;
  onSimulatePrompt: (query: string, triggersAction?: boolean) => void;
  onToggleScreenContext?: () => void;
  onReconnect?: () => void;
}

export const VoiceControlPanel: React.FC<VoiceControlPanelProps> = ({
  voiceState,
  audioLevel,
  connectionStatus,
  isLoading = false,
  microphoneStatus,
  screenContextEnabled,
  onStartListening,
  onPauseListening,
  onResumeListening,
  onStopListening,
  onSimulatePrompt,
  onToggleScreenContext,
  onReconnect,
}) => {
  const isListening = voiceState === 'listening';
  const isPaused = voiceState === 'paused';
  const isBusy = voiceState === 'processing' || voiceState === 'responding' || isLoading;
  const isOffline = connectionStatus === 'offline';

  return (
    <section className="panel voice-control-panel" aria-labelledby="voice-control-heading">
      <div className="panel-header">
        <div className="panel-title-wrap">
          <svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            aria-hidden="true"
          >
            <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
            <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            <line x1="12" y1="19" x2="12" y2="22" />
          </svg>
          <h2 id="voice-control-heading" className="panel-title">Voice Control & Session</h2>
        </div>

        <div
          className={`voice-state-badge state-${voiceState}`}
          role="status"
          aria-live="polite"
          aria-label={`Voice session status is ${voiceState}`}
        >
          <span className="state-pulse-ring" aria-hidden="true" />
          <span className="state-badge-text">{voiceState.toUpperCase()}</span>
        </div>
      </div>

      <div className="panel-body">
        {/* Offline Alert Bar when connection is lost */}
        {isOffline && (
          <div className="voice-offline-alert" role="alert" aria-live="assertive">
            <div className="offline-alert-icon" aria-hidden="true">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
            </div>
            <div className="offline-alert-text">
              <strong>Offline Mode:</strong> Audio gateway disconnected. Session controls suspended.
            </div>
            {onReconnect && (
              <button
                type="button"
                className="btn-retry-compact"
                onClick={onReconnect}
                aria-label="Reconnect to audio pipeline"
              >
                Reconnect
              </button>
            )}
          </div>
        )}

        {/* Capture State Indicators Section */}
        <div className="capture-indicators-tray" aria-label="Audio and visual capture indicators">
          {/* 1. Microphone Capture Indicator */}
          <div
            className={`capture-badge capture-mic ${
              isListening ? 'capture-active' : isPaused ? 'capture-paused' : 'capture-inactive'
            }`}
            title={`Microphone input status: ${microphoneStatus.isCapturing ? 'Active' : isPaused ? 'Paused' : 'Standby'}`}
          >
            <span className="capture-badge-dot" aria-hidden="true" />
            <span className="capture-badge-label">
              <span className="capture-badge-sub">MIC CAPTURE:</span>{' '}
              {isListening && 'LIVE'}
              {isPaused && 'PAUSED'}
              {!isListening && !isPaused && 'STANDBY'}
            </span>
            {isListening && <span className="capture-level-pill">{audioLevel}%</span>}
          </div>

          {/* 2. Screen-Context Capture Indicator */}
          <div
            className={`capture-badge capture-screen ${
              screenContextEnabled ? 'capture-active' : 'capture-inactive'
            }`}
            title={`Screen context: ${screenContextEnabled ? 'Active (Synthetic Demo)' : 'OFF (Audio Only)'}`}
          >
            <span className="capture-badge-dot" aria-hidden="true" />
            <span className="capture-badge-label">
              <span className="capture-badge-sub">SCREEN CONTEXT:</span>{' '}
              {screenContextEnabled ? 'ACTIVE (MOCK)' : 'OFF (DEFAULT)'}
            </span>
            {onToggleScreenContext && (
              <button
                type="button"
                className="btn-badge-toggle"
                onClick={onToggleScreenContext}
                aria-label={`Toggle screen context. Currently ${screenContextEnabled ? 'ON' : 'OFF'}`}
              >
                {screenContextEnabled ? 'Turn OFF' : 'Turn ON'}
              </button>
            )}
          </div>
        </div>

        {/* Animated Waveform & Audio Meter */}
        <AudioWaveform voiceState={voiceState} audioLevel={audioLevel} />

        {/* Primary Controls: Start, Pause, Resume, Stop */}
        <div className="voice-action-buttons">
          {/* START BUTTON (visible when idle or stopped) */}
          {!isPaused && (
            <button
              type="button"
              className={`btn-voice-primary ${isListening ? 'active-pulse' : ''}`}
              onClick={onStartListening}
              disabled={isListening || isBusy || isOffline}
              aria-label="Start listening for voice input"
              aria-pressed={isListening}
            >
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                aria-hidden="true"
              >
                <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
                <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                <line x1="12" y1="19" x2="12" y2="22" />
              </svg>
              <span>{isListening ? 'Listening...' : 'Start'}</span>
            </button>
          )}

          {/* PAUSE BUTTON (visible and active when listening) */}
          {isListening && (
            <button
              type="button"
              className="btn-voice-warning"
              onClick={onPauseListening}
              disabled={!isListening || isBusy}
              aria-label="Pause voice session without terminating"
              title="Pause audio capture and hold current session"
            >
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="currentColor"
                stroke="none"
                aria-hidden="true"
              >
                <rect x="6" y="4" width="4" height="16" rx="1" />
                <rect x="14" y="4" width="4" height="16" rx="1" />
              </svg>
              <span>Pause</span>
            </button>
          )}

          {/* RESUME BUTTON (visible when paused) */}
          {isPaused && (
            <button
              type="button"
              className="btn-voice-success"
              onClick={onResumeListening}
              disabled={!isPaused || isOffline}
              aria-label="Resume paused voice session"
              title="Resume microphone stream and continue session"
            >
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="currentColor"
                stroke="none"
                aria-hidden="true"
              >
                <polygon points="5 3 19 12 5 21 5 3" />
              </svg>
              <span>Resume</span>
            </button>
          )}

          {/* STOP BUTTON (terminates current active/paused session) */}
          <button
            type="button"
            className="btn-voice-danger"
            onClick={onStopListening}
            disabled={voiceState === 'idle' || isBusy}
            aria-label="Stop current voice session"
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="currentColor"
              stroke="none"
              aria-hidden="true"
            >
              <rect x="6" y="6" width="12" height="12" rx="2" />
            </svg>
            <span>Stop</span>
          </button>
        </div>

        {/* Input source selector */}
        <div className="device-selector">
          <label htmlFor="mic-select" className="device-label">
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              aria-hidden="true"
            >
              <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
              <line x1="8" y1="21" x2="16" y2="21" />
              <line x1="12" y1="17" x2="12" y2="21" />
            </svg>
            Input Microphone & Audio Format
          </label>
          <select id="mic-select" className="device-dropdown" defaultValue="default">
            <option value="default">Default: Studio Array Mic (PCM 16kHz Mono / 48kHz System)</option>
            <option value="headset">USB Headset Microphone (Noise-Cancelling, 16kHz)</option>
            <option value="virtual">Virtual Audio Cable (Simulated Synthetic Stream)</option>
          </select>
        </div>

        {/* Interactive Sample Speech Prompts */}
        <div className="sample-prompts-section">
          <span className="sample-prompts-label">Quick Voice Simulation Prompts:</span>
          <div className="prompt-chips">
            {SAMPLE_VOICE_PROMPTS.map((sample, idx) => (
              <button
                key={idx}
                type="button"
                className={`prompt-chip ${sample.triggersAction ? 'chip-sensitive' : ''}`}
                onClick={() => onSimulatePrompt(sample.query, sample.triggersAction)}
                disabled={voiceState === 'processing' || voiceState === 'responding' || isOffline}
                title={`Click to simulate: "${sample.query}"`}
              >
                {sample.triggersAction && (
                  <svg
                    width="12"
                    height="12"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    aria-hidden="true"
                  >
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10" />
                  </svg>
                )}
                <span>{sample.label}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
};
