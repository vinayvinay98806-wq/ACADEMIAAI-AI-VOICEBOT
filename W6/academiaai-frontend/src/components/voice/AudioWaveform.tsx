import React from 'react';
import type { VoiceState } from '../../types/copilot';

interface AudioWaveformProps {
  voiceState: VoiceState;
  audioLevel: number;
}

export const AudioWaveform: React.FC<AudioWaveformProps> = ({ voiceState, audioLevel }) => {
  const barCount = 20;

  return (
    <div className={`waveform-container state-${voiceState}`} aria-hidden="true">
      <div className="waveform-bars">
        {Array.from({ length: barCount }).map((_, index) => {
          let heightPercent = 12;

          if (voiceState === 'listening') {
            // Symmetrical distribution around center
            const distFromCenter = Math.abs(index - barCount / 2) / (barCount / 2);
            const factor = Math.max(0.15, 1 - distFromCenter * 0.7);
            const variance = Math.sin(index * 1.5) * 12;
            heightPercent = Math.max(12, Math.min(95, (audioLevel * factor) + variance));
          } else if (voiceState === 'responding') {
            const distFromCenter = Math.abs(index - barCount / 2) / (barCount / 2);
            const factor = Math.max(0.2, 1 - distFromCenter * 0.6);
            heightPercent = Math.max(15, Math.min(85, (audioLevel * factor * 0.9)));
          } else if (voiceState === 'processing') {
            heightPercent = 25 + Math.sin(index * 0.8) * 18;
          }

          return (
            <span
              key={index}
              className="waveform-bar"
              style={{
                height: `${heightPercent}%`,
                animationDelay: `${index * 0.04}s`,
              }}
            />
          );
        })}
      </div>

      <div className="waveform-indicator-row">
        <span className="waveform-label">
          {voiceState === 'idle' && 'Microphone Standby'}
          {voiceState === 'listening' && `Listening... Mic Input: ${audioLevel}%`}
          {voiceState === 'processing' && 'Synthesizing Query & Academic Context...'}
          {voiceState === 'responding' && `Copilot Responding... (${audioLevel}%)`}
        </span>
      </div>
    </div>
  );
};
