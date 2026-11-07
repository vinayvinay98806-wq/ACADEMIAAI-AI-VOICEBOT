import React, { useState } from 'react';
import type { ScreenContextData, AcademicSourceReference } from '../../types/copilot';

export interface ContextSourcePanelProps {
  screenContext: ScreenContextData;
  academicSources: AcademicSourceReference[];
  privacyShieldActive: boolean;
  onToggleScreenContext: (explicitState?: boolean) => void;
  onTogglePrivacyShield: () => void;
  isLoading?: boolean;
}

export const ContextSourcePanel: React.FC<ContextSourcePanelProps> = ({
  screenContext,
  academicSources,
  privacyShieldActive,
  onToggleScreenContext,
  onTogglePrivacyShield,
  isLoading = false,
}) => {
  const [showPrivacyDetails, setShowPrivacyDetails] = useState<boolean>(false);
  const isEnabled = screenContext.captureEnabled;

  return (
    <section className="panel context-source-panel" aria-labelledby="context-source-heading">
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
            <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
            <line x1="8" y1="21" x2="16" y2="21" />
            <line x1="12" y1="17" x2="12" y2="21" />
          </svg>
          <h2 id="context-source-heading" className="panel-title">Context & Source Grounding</h2>
        </div>

        <div
          className={`privacy-status-indicator ${isEnabled ? 'status-active' : 'status-disabled'}`}
          role="status"
          aria-live="polite"
        >
          <span className="privacy-dot" aria-hidden="true" />
          <span className="privacy-status-text">
            {isEnabled ? 'Screen Context: ON (Mock)' : 'Screen Context: OFF'}
          </span>
        </div>
      </div>

      <div className="panel-body">
        {/* Explicit Screen Context ON/OFF Control Card */}
        <div className={`screen-context-control-card ${isEnabled ? 'card-enabled' : 'card-disabled'}`}>
          <div className="context-card-header">
            <div className="context-card-title-group">
              <span className="context-shield-icon" aria-hidden="true">
                {isEnabled ? (
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
                    <line x1="8" y1="21" x2="16" y2="21" />
                    <line x1="12" y1="17" x2="12" y2="21" />
                  </svg>
                ) : (
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                  </svg>
                )}
              </span>
              <div>
                <span className="context-card-title">Visual Screen Context Capture</span>
                <span className="context-card-subtitle">
                  {isEnabled
                    ? 'Synthetic Lecture Fixture Active (Slide 14 OCR)'
                    : 'Disabled by Default (Zero Visual Ingestion)'}
                </span>
              </div>
            </div>

            {/* Explicit ON/OFF Toggle Button */}
            <button
              type="button"
              className={`btn-screen-context-toggle ${isEnabled ? 'btn-active' : 'btn-inactive'}`}
              onClick={() => onToggleScreenContext()}
              disabled={isLoading}
              aria-pressed={isEnabled}
              aria-label={`Toggle screen context. Currently ${isEnabled ? 'Enabled' : 'Disabled'}`}
            >
              <span className="toggle-indicator-dot" aria-hidden="true" />
              <span>{isEnabled ? 'Turn OFF' : 'Turn ON'}</span>
            </button>
          </div>

          {/* Current Permission & Capture Status */}
          <div className="context-meta-row">
            <span className="meta-badge">
              <strong>Permission:</strong>{' '}
              {isEnabled ? 'Granted (Mock Sandbox)' : 'Not Requested (Default Safe)'}
            </span>
            <span className="meta-badge">
              <strong>Mode:</strong>{' '}
              {screenContext.synthetic ? 'Synthetic Demo Fixture' : 'Live Hardware Stream'}
            </span>
          </div>

          {/* Clear Indication when Screen Context is Disabled */}
          {!isEnabled && (
            <div className="context-disabled-notice" role="status">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
              <p>
                <strong>Screen context is OFF:</strong> Co-pilot operates strictly in audio-only mode.
                No window contents, browser tabs, or screen pixels are accessed or transmitted.
              </p>
            </div>
          )}

          {/* Synthetic Context Details (When Enabled) */}
          {isEnabled && (
            <div className="synthetic-context-preview" aria-label="Mock screen context fixture details">
              <div className="synthetic-banner">
                <span className="synthetic-tag">DEMO FIXTURE</span>
                <span className="synthetic-text">
                  Synthetic Frame <code>{screenContext.frameId}</code> • Window: {screenContext.activeWindowTitle}
                </span>
              </div>

              <div className="ocr-snippet-box">
                <span className="ocr-label">Synthetic OCR Extracted Content:</span>
                <pre className="ocr-pre">{screenContext.ocrExtractedText}</pre>
              </div>
            </div>
          )}
        </div>

        {/* Privacy-Focused Explanation Accordion / Card */}
        <div className="privacy-explanation-card">
          <div className="privacy-card-summary">
            <div className="privacy-badge-icon" aria-hidden="true">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10" />
              </svg>
            </div>
            <div>
              <span className="privacy-title">Student Privacy & Academic Safety</span>
              <p className="privacy-desc">
                Screen context is strictly opt-in. Demonstrations use synthetic fixtures only.
              </p>
            </div>
            <button
              type="button"
              className="btn-details-toggle"
              onClick={() => setShowPrivacyDetails((prev) => !prev)}
              aria-expanded={showPrivacyDetails}
              aria-label="Toggle student privacy details"
            >
              {showPrivacyDetails ? 'Hide Policy' : 'View Policy'}
            </button>
          </div>

          {showPrivacyDetails && (
            <div className="privacy-card-expanded">
              <ul className="privacy-points-list">
                <li>
                  <strong>Safe Defaults:</strong> Screen capture is disabled by default upon every session initialization.
                </li>
                <li>
                  <strong>No Real Screen Capture:</strong> This application never invokes desktop recording APIs without explicit confirmation; all demonstrations utilize verified mock fixtures.
                </li>
                <li>
                  <strong>Academic Privacy Shield:</strong> When active, client-side regex masks student ID numbers, course grade books, and confidential credential tokens.
                </li>
              </ul>

              <div className="privacy-shield-row">
                <span className="shield-label">
                  PII Sanitization Shield: <strong>{privacyShieldActive ? 'ACTIVE (Redacted)' : 'BYPASS'}</strong>
                </span>
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
          )}
        </div>

        {/* Available Grounded Academic Sources */}
        <div className="sources-section">
          <div className="sources-header">
            <span className="sources-title">Available Academic Sources ({academicSources.length})</span>
            <span className="sources-note">Grounded W3 reasoning contracts</span>
          </div>

          <div className="sources-list" role="list">
            {academicSources.map((source) => (
              <div key={source.sourceId} className="source-item-card" role="listitem">
                <div className="source-item-top">
                  <span className={`source-type-tag type-${source.sourceType}`}>
                    {source.sourceType.toUpperCase()}
                  </span>
                  <span className="source-relevance-pill" title="Relevance score to current module">
                    {(source.relevanceScore * 100).toFixed(0)}% match
                  </span>
                </div>
                <h3 className="source-item-title">{source.title}</h3>
                <p className="source-item-snippet">{source.snippet}</p>
                {source.uriOrPath && (
                  <span className="source-item-path" title={source.uriOrPath}>
                    Ref: <code>{source.uriOrPath}</code>
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
};
