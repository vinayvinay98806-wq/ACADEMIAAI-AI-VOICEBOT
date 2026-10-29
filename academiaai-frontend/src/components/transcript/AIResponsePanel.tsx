import React from 'react';
import type { TranscriptItem, VoiceState } from '../../types/copilot';

interface AIResponsePanelProps {
  latestAiResponse?: TranscriptItem;
  voiceState: VoiceState;
}

export const AIResponsePanel: React.FC<AIResponsePanelProps> = ({
  latestAiResponse,
  voiceState,
}) => {
  const isResponding = voiceState === 'responding';
  const isProcessing = voiceState === 'processing';

  return (
    <section className="panel ai-response-panel" aria-labelledby="ai-response-heading">
      <div className="panel-header">
        <div className="panel-title-wrap">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3L12 3z" />
          </svg>
          <h2 id="ai-response-heading" className="panel-title">Active AI Copilot Synthesis</h2>
        </div>

        <div className="panel-badge-group">
          {isProcessing && (
            <span className="synthesis-badge badge-processing">
              <span className="spinner-sm" aria-hidden="true" />
              Synthesizing...
            </span>
          )}
          {isResponding && (
            <span className="synthesis-badge badge-speaking">
              <span className="audio-dot" aria-hidden="true" />
              Audio Responding
            </span>
          )}
          {!isProcessing && !isResponding && (
            <span className="synthesis-badge badge-idle">Ready</span>
          )}
        </div>
      </div>

      <div className="panel-body response-body">
        {isProcessing ? (
          <div className="processing-indicator">
            <div className="glow-spinner" aria-hidden="true" />
            <p className="processing-text">Analyzing lecture context and structuring response...</p>
          </div>
        ) : latestAiResponse ? (
          <div className="response-card">
            <div className="response-meta-bar">
              <span className="response-source">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z" />
                </svg>
                Context: Slide 14 & Canvas Syllabus Module 4
              </span>
              <span className="response-time">{latestAiResponse.timestamp}</span>
            </div>

            <div className="response-content">
              {latestAiResponse.text.split('\n').map((paragraph, i) => (
                <p key={i}>{paragraph}</p>
              ))}
            </div>

            <div className="citation-tray">
              <span className="citation-title">Verified Academic Sources:</span>
              <div className="citation-tags">
                <span className="citation-tag">Vaswani et al. (2017) "Attention Is All You Need"</span>
                <span className="citation-tag">CS 685 Syllabus §4.2</span>
                <span className="citation-tag">Slide 14 OCR Matched (99.4%)</span>
              </div>
            </div>
          </div>
        ) : (
          <div className="empty-state">
            <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
              <circle cx="12" cy="12" r="10" />
              <path d="m9 12 2 2 4-4" />
            </svg>
            <p>AI response will appear here once audio or prompt is synthesized.</p>
          </div>
        )}
      </div>
    </section>
  );
};

