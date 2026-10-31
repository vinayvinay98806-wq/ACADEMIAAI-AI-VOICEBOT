import React, { useState, useEffect, useRef } from 'react';
import type { SensitiveAction } from '../../types/copilot';

interface ActionApprovalModalProps {
  action: SensitiveAction | null;
  onClose: () => void;
  onApprove: (actionId: string, note?: string) => void;
  onReject: (actionId: string, reason: string) => void;
}

export const ActionApprovalModal: React.FC<ActionApprovalModalProps> = ({
  action,
  onClose,
  onApprove,
  onReject,
}) => {
  const [reason, setReason] = useState('');
  const approveBtnRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    approveBtnRef.current?.focus();
  }, []);

  // Handle escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  if (!action) return null;

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="modal-container"
        role="dialog"
        aria-modal="true"
        aria-labelledby="approval-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className={`modal-header-banner banner-${action.riskLevel}`}>
          <div className="modal-icon-badge" aria-hidden="true">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10" />
              <path d="m9 12 2 2 4-4" />
            </svg>
          </div>
          <div>
            <div className="modal-tag-row">
              <span className={`modal-risk-pill pill-${action.riskLevel}`}>
                {action.riskLevel.toUpperCase()} RISK LEVEL
              </span>
              <span className="modal-sub-tag">Human-in-the-Loop Safeguard</span>
            </div>
            <h2 id="approval-modal-title" className="modal-title">
              {action.title}
            </h2>
          </div>
          <button
            type="button"
            className="modal-close-btn"
            onClick={onClose}
            aria-label="Close approval dialog without action"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <div className="modal-body">
          <div className="modal-section">
            <span className="section-label">Action Impact & Description</span>
            <p className="impact-text">{action.description}</p>
            <div className="impact-warning-box">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
                <line x1="12" y1="9" x2="12" y2="13" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
              <span>{action.impact}</span>
            </div>
          </div>

          <div className="modal-section">
            <span className="section-label">Execution Target & Payloads</span>
            <div className="parameters-table-wrapper">
              <table className="parameters-table">
                <tbody>
                  <tr>
                    <td className="param-key">Target Gateway</td>
                    <td className="param-value">
                      <code>{action.targetSystem}</code>
                    </td>
                  </tr>
                  {Object.entries(action.parameters).map(([key, val]) => (
                    <tr key={key}>
                      <td className="param-key">{key}</td>
                      <td className="param-value">{val}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="modal-section">
            <label htmlFor="decision-note" className="section-label">
              Decision Note / Rejection Reason (Optional)
            </label>
            <input
              id="decision-note"
              type="text"
              className="modal-input"
              placeholder="e.g. Approved for Canvas submission, or: Need to review formula on page 3 first."
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </div>
        </div>

        <div className="modal-footer">
          <button
            type="button"
            className="btn-modal-cancel"
            onClick={onClose}
          >
            Cancel
          </button>

          <button
            type="button"
            className="btn-modal-reject"
            onClick={() => onReject(action.id, reason)}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
            Reject Action
          </button>

          <button
            ref={approveBtnRef}
            type="button"
            className="btn-modal-approve"
            onClick={() => onApprove(action.id, reason)}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <polyline points="20 6 9 17 4 12" />
            </svg>
            Authorize & Execute
          </button>
        </div>
      </div>
    </div>
  );
};
