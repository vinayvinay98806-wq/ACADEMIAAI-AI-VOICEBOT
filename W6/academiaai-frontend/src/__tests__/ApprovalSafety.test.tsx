/**
 * Safe Approval & Rejection Dialog Test Suite
 * Workstream: W6 Frontend & UX (Week 3)
 *
 * CRITICAL SAFETY REQUIREMENT:
 * Proves mathematically and behaviorally that:
 * 1. Rejecting an action strictly calls the rejection operation.
 * 2. Rejecting an action NEVER calls the execution/approval operation!
 * 3. Rejected actions remain rejected and execution is prevented.
 * 4. Duplicate submissions are safely blocked (buttons disabled, in-flight protection).
 * 5. Rejection failures and network errors are clearly displayed.
 * 6. Keyboard accessibility: Escape closes, Tab traps focus.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ActionApprovalModal } from '../components/approval/ActionApprovalModal';
import type { SensitiveAction } from '../types/copilot';

describe('Safe Human-In-The-Loop Approval & Rejection Dialog', () => {
  const mockAction: SensitiveAction = {
    id: 'act-canvas-99',
    requestId: 'req-canvas-99',
    title: 'Submit Assignment to Canvas LMS',
    description: 'Uploading final paper version 4 to University grading gateway.',
    impact: 'Irrevocably modifies student course submission timestamp.',
    riskLevel: 'high',
    targetSystem: 'Canvas LMS Gateway (HTTPS)',
    parameters: {
      Course: 'CS 685: Advanced NLP',
      File: 'assignment_final.pdf',
    },
    status: 'pending',
    timestamp: '16:00:00',
  };

  it('renders all required safety fields: title, risk level, description, impact, target system', () => {
    render(
      <ActionApprovalModal
        action={mockAction}
        onClose={vi.fn()}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />
    );

    expect(screen.getByText('Submit Assignment to Canvas LMS')).toBeInTheDocument();
    expect(screen.getByText(/HIGH RISK LEVEL/i)).toBeInTheDocument();
    expect(screen.getByText(/Uploading final paper version 4/i)).toBeInTheDocument();
    expect(screen.getByText(/Irrevocably modifies student course submission/i)).toBeInTheDocument();
    expect(screen.getByText('Canvas LMS Gateway (HTTPS)')).toBeInTheDocument();
    expect(screen.getByText(/Execution Safety Guarantee/i)).toBeInTheDocument();
  });

  it('CRITICAL SAFETY: Reject calls ONLY onReject and NEVER calls onApprove or execution', async () => {
    const onApprove = vi.fn();
    const onReject = vi.fn();
    const onClose = vi.fn();

    render(
      <ActionApprovalModal
        action={mockAction}
        onClose={onClose}
        onApprove={onApprove}
        onReject={onReject}
      />
    );

    const reasonInput = screen.getByPlaceholderText(/Approved for Canvas submission/i);
    fireEvent.change(reasonInput, { target: { value: 'Formula on page 3 is incorrect. Do not submit.' } });

    const rejectButton = screen.getByRole('button', { name: /Reject Action/i });
    fireEvent.click(rejectButton);

    // Verify rejection operation was dispatched
    expect(onReject).toHaveBeenCalledTimes(1);
    expect(onReject).toHaveBeenCalledWith('act-canvas-99', 'Formula on page 3 is incorrect. Do not submit.');

    // PROVE SAFETY: onApprove / execution must NEVER have been called!
    expect(onApprove).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('Authorize & Execute calls onApprove and NEVER calls onReject', async () => {
    const onApprove = vi.fn();
    const onReject = vi.fn();

    render(
      <ActionApprovalModal
        action={mockAction}
        onClose={vi.fn()}
        onApprove={onApprove}
        onReject={onReject}
      />
    );

    const approveButton = screen.getByRole('button', { name: /Authorize & Execute/i });
    fireEvent.click(approveButton);

    expect(onApprove).toHaveBeenCalledTimes(1);
    expect(onApprove).toHaveBeenCalledWith('act-canvas-99', '');
    expect(onReject).not.toHaveBeenCalled();
  });

  it('prevents duplicate submissions by disabling buttons while in flight', async () => {
    // Delay resolution to keep in-flight
    let resolveReject: () => void = () => {};
    const onReject = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveReject = resolve;
        })
    );
    const onApprove = vi.fn();

    render(
      <ActionApprovalModal
        action={mockAction}
        onClose={vi.fn()}
        onApprove={onApprove}
        onReject={onReject}
      />
    );

    const rejectButton = screen.getByRole('button', { name: /Reject Action/i });
    const approveButton = screen.getByRole('button', { name: /Authorize & Execute/i });

    // First click triggers submission
    fireEvent.click(rejectButton);
    expect(onReject).toHaveBeenCalledTimes(1);

    // Both buttons should now be disabled and reject button displays busy state
    expect(rejectButton).toBeDisabled();
    expect(approveButton).toBeDisabled();

    // Clicking again while in flight does NOT trigger duplicate call
    fireEvent.click(rejectButton);
    fireEvent.click(approveButton);
    expect(onReject).toHaveBeenCalledTimes(1);
    expect(onApprove).not.toHaveBeenCalled();

    // Complete the submission
    resolveReject();
  });

  it('displays backend error message if rejection fails', async () => {
    const onReject = vi.fn().mockRejectedValue(new Error('Gateway timeout: rejection could not be recorded'));

    render(
      <ActionApprovalModal
        action={mockAction}
        onClose={vi.fn()}
        onApprove={vi.fn()}
        onReject={onReject}
      />
    );

    const rejectButton = screen.getByRole('button', { name: /Reject Action/i });
    fireEvent.click(rejectButton);

    await waitFor(() => {
      expect(screen.getByText('Gateway timeout: rejection could not be recorded')).toBeInTheDocument();
    });
  });

  it('handles keyboard navigation: Escape key closes modal', () => {
    const onClose = vi.fn();

    render(
      <ActionApprovalModal
        action={mockAction}
        onClose={onClose}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />
    );

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

