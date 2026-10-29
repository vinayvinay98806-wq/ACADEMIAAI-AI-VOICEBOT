import React, { useRef, useEffect, useState } from 'react';
import type { TranscriptItem } from '../../types/copilot';

interface TranscriptPanelProps {
  transcripts: TranscriptItem[];
  onClear: () => void;
}

export const TranscriptPanel: React.FC<TranscriptPanelProps> = ({ transcripts, onClear }) => {
  const bottomRef = useRef<HTMLDivElement>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [transcripts]);

  const handleCopyTranscript = () => {
    const text = transcripts
      .map((t) => `[${t.timestamp}] ${t.speaker.toUpperCase()}: ${t.text}`)
      .join('\n\n');
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <section className="panel transcript-panel" aria-labelledby="transcript-heading">
      <div className="panel-header">
        <div className="panel-title-wrap">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
          <h2 id="transcript-heading" className="panel-title">Live Transcript & Dialogue</h2>
          <span className="transcript-count">{transcripts.length} entries</span>
        </div>

        <div className="panel-actions">
          <button
            type="button"
            className="btn-ghost-sm"
            onClick={handleCopyTranscript}
            title="Copy full transcript to clipboard"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
            </svg>
            {copied ? 'Copied!' : 'Copy'}
          </button>
          <button
            type="button"
            className="btn-ghost-sm"
            onClick={onClear}
            title="Clear current transcript history"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            </svg>
            Clear
          </button>
        </div>
      </div>

      <div className="panel-body transcript-body" role="log" aria-live="polite">
        {transcripts.length === 0 ? (
          <div className="empty-state">
            <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
              <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
              <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            </svg>
            <p>No active speech transcript yet. Click <strong>Start Listening</strong> or select a prompt.</p>
          </div>
        ) : (
          <div className="transcript-messages">
            {transcripts.map((item) => (
              <div key={item.id} className={`transcript-bubble bubble-${item.speaker}`}>
                <div className="bubble-header">
                  <div className="bubble-author">
                    {item.speaker === 'user' && (
                      <span className="author-badge badge-user">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                          <circle cx="12" cy="7" r="4" />
                        </svg>
                        Student / You
                      </span>
                    )}
                    {item.speaker === 'ai' && (
                      <span className="author-badge badge-ai">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                          <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
                        </svg>
                        AcademiaAI Co-Pilot
                      </span>
                    )}
                    {item.speaker === 'system' && (
                      <span className="author-badge badge-system">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                          <circle cx="12" cy="12" r="10" />
                          <line x1="12" y1="16" x2="12" y2="12" />
                          <line x1="12" y1="8" x2="12.01" y2="8" />
                        </svg>
                        System Event
                      </span>
                    )}
                  </div>

                  <div className="bubble-meta">
                    {item.confidence && (
                      <span className="confidence-pill" title="Speech recognition confidence score">
                        {(item.confidence * 100).toFixed(0)}% match
                      </span>
                    )}
                    <span className="bubble-timestamp">{item.timestamp}</span>
                  </div>
                </div>

                <div className="bubble-text">
                  {item.text.split('\n').map((line, lIdx) => (
                    <p key={lIdx}>{line}</p>
                  ))}
                </div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>
    </section>
  );
};

