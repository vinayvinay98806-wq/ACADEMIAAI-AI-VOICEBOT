import React from 'react';
import type { ScreenShareStatus, PrivacyScope } from '../../types/copilot';

interface PrivacyPanelProps {
  screenShareStatus: ScreenShareStatus;
  privacyScope: PrivacyScope;
  privacyShieldActive: boolean;
  onToggleScreenShare: () => void;
  onChangeScope: (scope: PrivacyScope) => void;
  onTogglePrivacyShield: () => void;
}

export const PrivacyPanel: React.FC<PrivacyPanelProps> = ({
  screenShareStatus,
  privacyScope,
  privacyShieldActive,
  onToggleScreenShare,
  onChangeScope,
  onTogglePrivacyShield,
}) => {
  return (
    <section className="panel privacy-panel" aria-labelledby="privacy-heading">
      <div className="panel-header">
        <div className="panel-title-wrap">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
          </svg>
          <h2 id="privacy-heading" className="panel-title">Privacy & Screen Context</h2>
        </div>

        <div className={`privacy-status-indicator status-${screenShareStatus}`} role="status">
          <span className="privacy-dot" aria-hidden="true" />
          <span className="privacy-status-text">
            {screenShareStatus === 'active' && 'Sharing Active'}
            {screenShareStatus === 'paused' && 'Vision Paused'}
            {screenShareStatus === 'disabled' && 'Screen Private'}
          </span>
        </div>
      </div>

      <div className="panel-body">
        {/* Toggle Screen Share */}
        <div className="privacy-row">
          <div className="privacy-info">
            <span className="privacy-item-title">Visual Context Sharing</span>
            <span className="privacy-item-desc">
              {screenShareStatus === 'active'
                ? 'Co-pilot can read visible lecture slides and code snippets.'
                : screenShareStatus === 'paused'
                ? 'Screen stream temporarily halted. Co-pilot uses audio only.'
                : 'Screen stream completely disconnected.'}
            </span>
          </div>

          <button
            type="button"
            className={`btn-screen-toggle btn-screen-${screenShareStatus}`}
            onClick={onToggleScreenShare}
            aria-label={`Toggle screen sharing. Currently ${screenShareStatus}`}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
              <line x1="8" y1="21" x2="16" y2="21" />
              <line x1="12" y1="17" x2="12" y2="21" />
            </svg>
            <span>
              {screenShareStatus === 'active' && 'Pause Stream'}
              {screenShareStatus === 'paused' && 'Resume Stream'}
              {screenShareStatus === 'disabled' && 'Enable Stream'}
            </span>
          </button>
        </div>

        {/* Boundary Scope Selector */}
        <div className="privacy-scope-group">
          <label className="scope-group-label" id="scope-label">
            Context Boundary Scope
          </label>
          <div className="scope-pills" role="radiogroup" aria-labelledby="scope-label">
            <button
              type="button"
              role="radio"
              aria-checked={privacyScope === 'notes-only'}
              className={`scope-pill ${privacyScope === 'notes-only' ? 'selected' : ''}`}
              onClick={() => onChangeScope('notes-only')}
            >
              Notes Only
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={privacyScope === 'window'}
              className={`scope-pill ${privacyScope === 'window' ? 'selected' : ''}`}
              onClick={() => onChangeScope('window')}
            >
              Active Window
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={privacyScope === 'fullscreen'}
              className={`scope-pill ${privacyScope === 'fullscreen' ? 'selected' : ''}`}
              onClick={() => onChangeScope('fullscreen')}
            >
              Entire Screen
            </button>
          </div>
        </div>

        {/* Sensitive PII Masking Shield */}
        <div className="privacy-shield-card">
          <div className="shield-left">
            <div className={`shield-icon-badge ${privacyShieldActive ? 'shield-on' : 'shield-off'}`} aria-hidden="true">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10" />
              </svg>
            </div>
            <div>
              <span className="shield-title">Academic Privacy Shield</span>
              <p className="shield-desc">
                {privacyShieldActive
                  ? 'Active: Redacting student IDs, emails, and exam keys before OCR extraction.'
                  : 'Bypassed: No PII sanitization filter applied.'}
              </p>
            </div>
          </div>

          <button
            type="button"
            className={`toggle-switch ${privacyShieldActive ? 'switch-on' : 'switch-off'}`}
            onClick={onTogglePrivacyShield}
            role="switch"
            aria-checked={privacyShieldActive}
            aria-label="Toggle Academic Privacy Shield"
          >
            <span className="switch-thumb" />
          </button>
        </div>
      </div>
    </section>
  );
};

