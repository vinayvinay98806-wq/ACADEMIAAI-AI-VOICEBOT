import React from 'react';
import type { SensitiveAction } from '../../types/copilot';

interface PendingActionsListProps {
  actions: SensitiveAction[];
  onReviewAction: (action: SensitiveAction) => void;
}

export const PendingActionsList: React.FC<PendingActionsListProps> = ({
  actions,
  onReviewAction,
}) => {
  const pendingActions = actions.filter((a) => a.status === 'pending');
  const pastActions = actions.filter((a) => a.status !== 'pending');

  return (
    <section className="panel actions-panel" aria-labelledby="actions-heading">
      <div className="panel-header">
        <div className="panel-title-wrap">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10" />
            <path d="m9 12 2 2 4-4" />
          </svg>
          <h2 id="actions-heading" className="panel-title">Sensitive Action Guard (HITL)</h2>
        </div>

        {pendingActions.length > 0 && (
          <span className="pending-counter" aria-label={`${pendingActions.length} actions pending approval`}>
            {pendingActions.length} Pending
          </span>
        )}
      </div>

      <div className="panel-body actions-body">
        <p className="actions-helper">
          Autonomous execution paused for critical academic actions. Human authorization required.
        </p>

        {pendingActions.length === 0 ? (
          <div className="empty-pending-box">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
              <polyline points="22 4 12 14.01 9 11.01" />
            </svg>
            <span>No pending sensitive actions. All systems authorized.</span>
          </div>
        ) : (
          <div className="pending-action-cards">
            {pendingActions.map((action) => (
              <div key={action.id} className={`action-card risk-${action.riskLevel}`}>
                <div className="action-card-header">
                  <span className={`risk-tag tag-${action.riskLevel}`}>
                    {action.riskLevel.toUpperCase()} RISK
                  </span>
                  <span className="action-time">{action.timestamp}</span>
                </div>

                <h3 className="action-title">{action.title}</h3>
                <p className="action-desc">{action.description}</p>

                <div className="action-target">
                  <span className="target-label">Target:</span>
                  <code className="target-code">{action.targetSystem}</code>
                </div>

                <button
                  type="button"
                  className="btn-review-action"
                  onClick={() => onReviewAction(action)}
                  aria-haspopup="dialog"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                    <circle cx="12" cy="12" r="10" />
                    <line x1="12" y1="16" x2="12" y2="12" />
                    <line x1="12" y1="8" x2="12.01" y2="8" />
                  </svg>
                  Review & Decide (Approve / Reject)
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Audit Trail of Handled Actions */}
        {pastActions.length > 0 && (
          <div className="audit-section">
            <span className="audit-heading">Recent Authorization Audit Trail:</span>
            <ul className="audit-list">
              {pastActions.map((act) => (
                <li key={act.id} className={`audit-item item-${act.status}`}>
                  <div className="audit-top">
                    <span className="audit-title">{act.title}</span>
                    <span className={`audit-badge badge-${act.status}`}>
                      {act.status.toUpperCase()}
                    </span>
                  </div>
                  {act.decisionNote && (
                    <p className="audit-note">Note: {act.decisionNote}</p>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
};

