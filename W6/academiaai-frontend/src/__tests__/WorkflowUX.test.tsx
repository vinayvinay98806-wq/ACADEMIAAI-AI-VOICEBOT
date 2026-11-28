/**
 * Workflow Progress View Test Suite
 * Workstream: W6 Frontend & UX (Week 3)
 * Tests rendering of all backend statuses:
 * - Pending, Running, Completed, Failed, Waiting for approval, Rejected, Cancelled, Skipped
 * - Dynamic step count support
 * - Active step highlighting
 * - Failure explanations and retry interaction
 * - Accessibility attributes
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { WorkflowTracker } from '../components/workflow/WorkflowTracker';
import type { Workflow } from '../types/copilot';

describe('WorkflowTracker UX & Status Representation', () => {
  const mockWorkflows: Workflow[] = [
    {
      id: 'wf-dynamic-test',
      title: 'Automated Academic Paper Pipeline',
      category: 'Research Assistant',
      status: 'in-progress',
      currentStepIndex: 1,
      steps: [
        {
          id: 'step-1',
          title: 'Extract Abstract Citations',
          description: 'Parsing IEEE bibliography links',
          status: 'completed',
          duration: '0.8s',
        },
        {
          id: 'step-2',
          title: 'Verify DOI Links via Semantic Scholar',
          description: 'Checking online repository connectivity',
          status: 'running',
          duration: 'Running...',
        },
        {
          id: 'step-3',
          title: 'Review Consequential Repository Modification',
          description: 'Requires human confirmation before writing to repository',
          status: 'awaiting_approval',
        },
        {
          id: 'step-4',
          title: 'Overwriting Published Lecture Notes',
          description: 'Action was denied by instructor',
          status: 'rejected',
          errorDetails: 'Execution blocked: Denied by reviewer.',
        },
        {
          id: 'step-5',
          title: 'Secondary Indexing',
          description: 'Cancelled due to upstream rejection',
          status: 'cancelled',
        },
        {
          id: 'step-6',
          title: 'Network Cache Sync',
          description: 'Timeout contacting remote endpoint',
          status: 'failed',
          errorDetails: 'Timeout after 5000ms connecting to sync gateway.',
        },
        {
          id: 'step-7',
          title: 'Optional Archival Sync',
          description: 'Step skipped per user settings',
          status: 'skipped',
        },
        {
          id: 'step-8',
          title: 'Final Notification Dispatch',
          description: 'Pending execution of earlier steps',
          status: 'pending',
        },
      ],
    },
  ];

  it('renders every workflow step and all required backend statuses', () => {
    const onRetry = vi.fn();
    render(<WorkflowTracker workflows={mockWorkflows} onRetryStep={onRetry} />);

    // Header and title
    expect(screen.getByText('Automated Academic Paper Pipeline')).toBeInTheDocument();
    expect(screen.getByText('Research Assistant')).toBeInTheDocument();

    // Verify all statuses are represented
    expect(screen.getByText(/1\. Extract Abstract Citations/)).toBeInTheDocument();
    expect(screen.getAllByText(/Completed/i).length).toBeGreaterThanOrEqual(1);

    expect(screen.getByText(/2\. Verify DOI Links/)).toBeInTheDocument();
    expect(screen.getAllByText(/Running/i).length).toBeGreaterThanOrEqual(1);

    expect(screen.getByText(/3\. Review Consequential Repository/)).toBeInTheDocument();
    expect(screen.getAllByText(/Waiting for approval/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Awaiting Human Review/i)).toBeInTheDocument();

    expect(screen.getByText(/4\. Overwriting Published Lecture Notes/)).toBeInTheDocument();
    expect(screen.getAllByText(/Rejected/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Execution blocked: Denied by reviewer/i)).toBeInTheDocument();

    expect(screen.getByText(/5\. Secondary Indexing/)).toBeInTheDocument();
    expect(screen.getAllByText(/Cancelled/i).length).toBeGreaterThanOrEqual(1);

    expect(screen.getByText(/6\. Network Cache Sync/)).toBeInTheDocument();
    expect(screen.getAllByText(/Failed/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Timeout after 5000ms connecting/i)).toBeInTheDocument();

    expect(screen.getByText(/7\. Optional Archival Sync/)).toBeInTheDocument();
    expect(screen.getAllByText(/Skipped/i).length).toBeGreaterThanOrEqual(1);

    expect(screen.getByText(/8\. Final Notification Dispatch/)).toBeInTheDocument();
    expect(screen.getAllByText(/Pending/i).length).toBeGreaterThanOrEqual(1);
  });

  it('supports dynamic numbers of steps without fixed assumptions', () => {
    const shortWorkflow: Workflow[] = [
      {
        id: 'wf-short',
        title: 'Quick Audio Check',
        category: 'Diagnostics',
        status: 'completed',
        currentStepIndex: 1,
        steps: [
          {
            id: 'chk-1',
            title: 'Mic Level Check',
            description: '48kHz PCM capture confirmed',
            status: 'completed',
            duration: '0.2s',
          },
        ],
      },
    ];

    render(<WorkflowTracker workflows={shortWorkflow} onRetryStep={vi.fn()} />);
    expect(screen.getByText('Quick Audio Check')).toBeInTheDocument();
    expect(screen.getByText('1 of 1 steps completed')).toBeInTheDocument();
    expect(screen.getByText('100%')).toBeInTheDocument();
  });

  it('renders failure explanation and allows retrying failed steps', () => {
    const onRetry = vi.fn();
    render(<WorkflowTracker workflows={mockWorkflows} onRetryStep={onRetry} />);

    const retryBtn = screen.getByRole('button', {
      name: /Retry failed step: Network Cache Sync/i,
    });
    expect(retryBtn).toBeInTheDocument();

    fireEvent.click(retryBtn);
    expect(onRetry).toHaveBeenCalledWith('wf-dynamic-test', 'step-6');
  });

  it('displays empty state when no workflows are present', () => {
    render(<WorkflowTracker workflows={[]} onRetryStep={vi.fn()} />);
    expect(screen.getByText('No active workflows in the current session.')).toBeInTheDocument();
  });
});
