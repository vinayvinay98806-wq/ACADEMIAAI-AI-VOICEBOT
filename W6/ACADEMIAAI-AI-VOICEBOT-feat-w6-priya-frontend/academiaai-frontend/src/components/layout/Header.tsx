import React from 'react';
import type { ConnectionStatus } from '../../types/copilot';

interface HeaderProps {
  sessionDuration: string;
  connectionStatus: ConnectionStatus;
  toggleConnection: () => void;
  onTriggerTestAlert: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  sessionDuration,
  connectionStatus,
  toggleConnection,
  onTriggerTestAlert,
}) => {
  return (
    <header className="copilot-header" role="banner">
      <div className="header-brand">
        <div className="brand-logo-badge" aria-hidden="true">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
            <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            <line x1="12" y1="19" x2="12" y2="22" />
          </svg>
        </div>
        <div>
          <div className="brand-title-row">
            <h1 className="brand-title">AcademiaAI</h1>
            <span className="brand-badge">Voice Co-Pilot</span>
            <span className="brand-tag">Work 6: Frontend & UX</span>
          </div>
          <p className="brand-sub">Active Context: CS 685 — Deep Learning & NLP (Prof. Reynolds)</p>
        </div>
      </div>

      <div className="header-meta">
        <div className="meta-item">
          <span className="meta-label">Session Time</span>
          <span className="meta-value timer-mono" aria-label={`Session duration ${sessionDuration}`}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <circle cx="12" cy="12" r="10" />
              <polyline points="12 6 12 12 16 14" />
            </svg>
            {sessionDuration}
          </span>
        </div>

        <div className="meta-divider" aria-hidden="true" />

        <div className="meta-item">
          <span className="meta-label">Network Status</span>
          <button
            type="button"
            className={`status-pill pill-${connectionStatus}`}
            onClick={toggleConnection}
            title="Click to toggle connection state for testing"
            aria-label={`Connection status: ${connectionStatus}. Click to test state change.`}
          >
            <span className="status-dot" aria-hidden="true" />
            <span className="status-text">
              {connectionStatus === 'connected' && 'Online (22ms)'}
              {connectionStatus === 'reconnecting' && 'Reconnecting...'}
              {connectionStatus === 'offline' && 'Offline'}
            </span>
          </button>
        </div>

        <div className="meta-divider" aria-hidden="true" />

        <div className="header-actions">
          <button
            type="button"
            className="btn-ghost-sm"
            onClick={onTriggerTestAlert}
            title="Trigger an accessible mock error alert"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
              <line x1="12" y1="9" x2="12" y2="13" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
            Simulate Alert
          </button>
        </div>
      </div>
    </header>
  );
};

