import React from 'react';
import type { VoiceState } from '../../types/copilot';
import { SAMPLE_VOICE_PROMPTS } from '../../mock/mockData';
import { AudioWaveform } from './AudioWaveform';

interface VoiceControlPanelProps {
  voiceState: VoiceState;
  audioLevel: number;
  onStartListening: () => void;
  onStopListening: () => void;
  onSimulatePrompt: (query: string, triggersAction?: boolean) => void;
}

export const VoiceControlPanel: React.FC<VoiceControlPanelProps> = ({
  voiceState,
  audioLevel,
  onStartListening,
  onStopListening,
  onSimulatePrompt,
}) => {
  const isListening = voiceState === 'listening';
  const isBusy = voiceState === 'processing' || voiceState === 'responding';

  return (
    <section className="panel voice-control-panel" aria-labelledby="voice-control-heading">
      <div className="panel-header">
        <div className="panel-title-wrap">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
            <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            <line x1="12" y1="19" x2="12" y2="22" />
          </svg>
          <h2 id="voice-control-heading" className="panel-title">Voice Control</h2>
        </div>

        <div className={`voice-state-badge state-${voiceState}`} role="status" aria-live="polite">
          <span className="state-pulse-ring" aria-hidden="true" />
          <span className="state-badge-text">{voiceState.toUpperCase()}</span>
        </div>
      </div>

      <div className="panel-body">
        {/* Animated Waveform & Audio Meter */}
        <AudioWaveform voiceState={voiceState} audioLevel={audioLevel} />

        {/* Primary Controls */}
        <div className="voice-action-buttons">
          <button
            type="button"
            className={`btn-voice-primary ${isListening ? 'active-pulse' : ''}`}
            onClick={onStartListening}
            disabled={isListening || isBusy}
            aria-label="Start listening for voice input"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
              <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
              <line x1="12" y1="19" x2="12" y2="22" />
            </svg>
            <span>{isListening ? 'Listening...' : 'Start Listening'}</span>
          </button>

          <button
            type="button"
            className="btn-voice-danger"
            onClick={onStopListening}
            disabled={!isListening && !isBusy}
            aria-label="Stop listening or cancel current response"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden="true">
              <rect x="6" y="6" width="12" height="12" rx="2" />
            </svg>
            <span>Stop</span>
          </button>
        </div>

        {/* Input source selector */}
        <div className="device-selector">
          <label htmlFor="mic-select" className="device-label">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
              <line x1="8" y1="21" x2="16" y2="21" />
              <line x1="12" y1="17" x2="12" y2="21" />
            </svg>
            Input Microphone
          </label>
          <select id="mic-select" className="device-dropdown" defaultValue="default">
            <option value="default">Default: Studio Array Mic (Realtek HD, 48kHz)</option>
            <option value="headset">USB Headset Microphone (Noise-Cancelling)</option>
            <option value="virtual">Virtual Audio Cable (Screen Audio Feed)</option>
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
                disabled={voiceState !== 'idle'}
                title={`Click to simulate: "${sample.query}"`}
              >
                {sample.triggersAction && (
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
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

