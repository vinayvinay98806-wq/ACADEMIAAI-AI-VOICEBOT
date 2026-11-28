import React, { useState, useEffect, useRef } from 'react';
import type { SensitiveAction } from '../../types/copilot';

interface ActionApprovalModalProps {
  action: SensitiveAction | null;
  onClose: () => void;
  onApprove: (actionId: string, note?: string) => Promise<void> | void;
  onReject: (actionId: string, reason: string) => Promise<void> | void;
}

export const ActionApprovalModal: React.FC<ActionApprovalModalProps> = ({
  action,
  onClose,
  onApprove,
  onReject,
}) => {
  const [reason, setReason] = useState('');
  const [submittingState, setSubmittingState] = useState<'approving' | 'rejecting' | null>(null);
  const [submissionError, setSubmissionError] = useState<string | null>(null);

  const approveBtnRef = useRef<HTMLButtonElement>(null);
  const rejectBtnRef = useRef<HTMLButtonElement>(null);
  const cancelBtnRef = useRef<HTMLButtonElement>(null);
  const modalContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    approveBtnRef.current?.focus();
  }, []);

  // Handle escape key and focus trapping
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (!submittingState) {
          onClose();
        }
        return;
      }

      // Focus trap within modal
      if (e.key === 'Tab' && modalContainerRef.current) {
        const focusableElements = modalContainerRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex="0"]'
        );
        const firstElement = focusableElements[0];
        const lastElement = focusableElements[focusableElements.length - 1];

        if (e.shiftKey) {
          if (document.activeElement === firstElement) {
            e.preventDefault();
            lastElement?.focus();
          }
        } else {
          if (document.activeElement === lastElement) {
            e.preventDefault();
            firstElement?.focus();
          }
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose, submittingState]);

  if (!action) return null;

  const handleApprove = async () => {
    if (submittingState) return; // Prevent duplicate submission
    setSubmittingState('approving');
    setSubmissionError(null);
    try {
      await onApprove(action.id, reason);
    } catch (err: unknown) {
      setSubmissionError(err instanceof Error ? err.message : 'Approval request failed');
      setSubmittingState(null);
    }
  };

  /**
   * CRITICAL SAFETY REQUIREMENT:
   * Rejecting an action must NEVER trigger its execution!
   * Independent rejection pathway calling only onReject.
   */
  const handleReject = async () => {
    if (submittingState) return; // Prevent duplicate submission
    setSubmittingState('rejecting');
    setSubmissionError(null);
    try {
      await onReject(action.id, reason);
    } catch (err: unknown) {
      setSubmissionError(err instanceof Error ? err.message : 'Rejection request failed');
      setSubmittingState(null);
    }
  };

  return (
    <div className="modal-backdrop" role="presentation" onClick={submittingState ? undefined : onClose}>
      <div
        ref={modalContainerRef}
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
            disabled={!!submittingState}
            aria-label="Close approval dialog without action"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <div className="modal-body">
          {submissionError && (
            <div className="modal-error-banner" role="alert">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
              <span>{submissionError}</span>
            </div>
          )}

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

          <div className="modal-section safety-guarantee-note">
            <span className="safety-label">Execution Safety Guarantee</span>
            <p className="safety-text">
              Rejecting this action strictly halts execution and marks the workflow step as rejected.
              Rejection decisions are recorded authoritatively and never invoke the execution target.
            </p>
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
              disabled={!!submittingState}
              onChange={(e) => setReason(e.target.value)}
            />
          </div>
        </div>

        <div className="modal-footer">
          <button
            ref={cancelBtnRef}
            type="button"
            className="btn-modal-cancel"
            onClick={onClose}
            disabled={!!submittingState}
          >
            Cancel
          </button>

          <button
            ref={rejectBtnRef}
            type="button"
            className="btn-modal-reject"
            onClick={handleReject}
            disabled={!!submittingState}
            aria-busy={submittingState === 'rejecting'}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
            {submittingState === 'rejecting' ? 'Rejecting & Blocking...' : 'Reject Action'}
          </button>

          <button
            ref={approveBtnRef}
            type="button"
            className="btn-modal-approve"
            onClick={handleApprove}
            disabled={!!submittingState}
            aria-busy={submittingState === 'approving'}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <polyline points="20 6 9 17 4 12" />
            </svg>
            {submittingState === 'approving' ? 'Authorizing...' : 'Authorize & Execute'}
          </button>
        </div>
      </div>
    </div>
  );
};
