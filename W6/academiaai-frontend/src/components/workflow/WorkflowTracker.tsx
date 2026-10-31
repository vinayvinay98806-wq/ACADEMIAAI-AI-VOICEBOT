import React from 'react';
import type { Workflow, StepStatus } from '../../types/copilot';

interface WorkflowTrackerProps {
  workflows: Workflow[];
  onRetryStep: (workflowId: string, stepId: string) => void;
}

const getStepIcon = (status: StepStatus) => {
  switch (status) {
    case 'completed':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
          <polyline points="20 6 9 17 4 12" />
        </svg>
      );
    case 'running':
      return <span className="step-spinner" aria-hidden="true" />;
    case 'failed':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
          <line x1="18" y1="6" x2="6" y2="18" />
          <line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      );
    case 'pending':
    default:
      return <span className="step-bullet" aria-hidden="true" />;
  }
};

export const WorkflowTracker: React.FC<WorkflowTrackerProps> = ({ workflows, onRetryStep }) => {
  return (
    <section className="panel workflow-panel" aria-labelledby="workflow-heading">
      <div className="panel-header">
        <div className="panel-title-wrap">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <line x1="18" y1="20" x2="18" y2="10" />
            <line x1="12" y1="20" x2="12" y2="4" />
            <line x1="6" y1="20" x2="6" y2="14" />
          </svg>
          <h2 id="workflow-heading" className="panel-title">Workflow Execution Pipeline</h2>
        </div>
      </div>

      <div className="panel-body workflow-body">
        {workflows.map((wf) => {
          const completedCount = wf.steps.filter((s) => s.status === 'completed').length;
          const progressPercent = Math.round((completedCount / wf.steps.length) * 100);

          return (
            <div key={wf.id} className="workflow-card">
              <div className="workflow-card-header">
                <div>
                  <span className="workflow-category">{wf.category}</span>
                  <h3 className="workflow-title">{wf.title}</h3>
                </div>
                <span className={`workflow-status-badge status-${wf.status}`}>
                  {wf.status.toUpperCase()}
                </span>
              </div>

              {/* Progress bar */}
              <div className="progress-bar-track" aria-hidden="true">
                <div
                  className={`progress-bar-fill fill-${wf.status}`}
                  style={{ width: `${progressPercent}%` }}
                />
              </div>
              <div className="progress-meta">
                <span>{completedCount} of {wf.steps.length} steps completed</span>
                <span>{progressPercent}%</span>
              </div>

              {/* Steps timeline list */}
              <ol className="step-timeline" aria-label={`Steps for ${wf.title}`}>
                {wf.steps.map((step, idx) => (
                  <li key={step.id} className={`step-item status-${step.status}`}>
                    <div className="step-marker" aria-hidden="true">
                      {getStepIcon(step.status)}
                    </div>

                    <div className="step-content">
                      <div className="step-header-line">
                        <span className="step-name">
                          {idx + 1}. {step.title}
                        </span>
                        <div className="step-tags">
                          {step.duration && <span className="step-duration">{step.duration}</span>}
                          <span className={`step-status-tag tag-${step.status}`}>
                            {step.status}
                          </span>
                        </div>
                      </div>

                      <p className="step-desc">{step.description}</p>

                      {step.status === 'failed' && step.errorDetails && (
                        <div className="step-error-box" role="alert">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                            <circle cx="12" cy="12" r="10" />
                            <line x1="12" y1="8" x2="12" y2="12" />
                            <line x1="12" y1="16" x2="12.01" y2="16" />
                          </svg>
                          <span>{step.errorDetails}</span>
                          <button
                            type="button"
                            className="btn-retry-step"
                            onClick={() => onRetryStep(wf.id, step.id)}
                            aria-label={`Retry failed step: ${step.title}`}
                          >
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                              <polyline points="1 4 1 10 7 10" />
                              <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" />
                            </svg>
                            Retry Step
                          </button>
                        </div>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          );
        })}
      </div>
    </section>
  );
};

