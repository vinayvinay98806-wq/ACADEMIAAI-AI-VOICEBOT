"""
Unit tests for the WorkflowStateMachine:
- Supporting all 7 states: draft, awaiting_approval, running, paused, succeeded, failed, cancelled
- Validating allowed transitions
- Rejecting illegal transitions
- Terminal state locks
- Audit history logging
"""

import sys
from pathlib import Path

# Add project root to sys.path for direct or discovered execution
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import unittest
from agentic_workflow.state_machine import (
    IllegalStateTransitionError,
    TERMINAL_STATES,
    VALID_TRANSITIONS,
    WorkflowState,
    WorkflowStateMachine,
)


class TestWorkflowStateMachine(unittest.TestCase):
    """Test suite verifying strict state machine transition rules and safety guarantees."""

    def test_all_seven_states_exist(self):
        """Verify that exactly the seven required states exist with lowercase string values."""
        expected_states = {
            "draft",
            "awaiting_approval",
            "running",
            "paused",
            "succeeded",
            "failed",
            "cancelled",
        }
        actual_states = {s.value for s in WorkflowState}
        self.assertEqual(expected_states, actual_states)
        self.assertEqual(len(WorkflowState), 7)

    def test_initial_state_defaults_to_draft(self):
        """Verify state machine defaults to draft state."""
        fsm = WorkflowStateMachine()
        self.assertEqual(fsm.current_state, WorkflowState.DRAFT)
        self.assertFalse(fsm.is_terminal)
        self.assertEqual(len(fsm.history), 0)

    def test_valid_transitions_from_draft(self):
        """Test all valid transitions originating from draft."""
        # draft -> running
        fsm = WorkflowStateMachine(WorkflowState.DRAFT)
        fsm.transition_to(WorkflowState.RUNNING)
        self.assertEqual(fsm.current_state, WorkflowState.RUNNING)

        # draft -> awaiting_approval
        fsm = WorkflowStateMachine(WorkflowState.DRAFT)
        fsm.transition_to(WorkflowState.AWAITING_APPROVAL)
        self.assertEqual(fsm.current_state, WorkflowState.AWAITING_APPROVAL)

        # draft -> cancelled
        fsm = WorkflowStateMachine(WorkflowState.DRAFT)
        fsm.transition_to(WorkflowState.CANCELLED)
        self.assertEqual(fsm.current_state, WorkflowState.CANCELLED)

    def test_valid_transitions_from_running(self):
        """Test all valid transitions originating from running."""
        for target in [
            WorkflowState.AWAITING_APPROVAL,
            WorkflowState.PAUSED,
            WorkflowState.SUCCEEDED,
            WorkflowState.FAILED,
            WorkflowState.CANCELLED,
        ]:
            fsm = WorkflowStateMachine(WorkflowState.RUNNING)
            fsm.transition_to(target)
            self.assertEqual(fsm.current_state, target)

    def test_valid_transitions_from_awaiting_approval(self):
        """Test all valid transitions originating from awaiting_approval."""
        for target in [
            WorkflowState.RUNNING,
            WorkflowState.PAUSED,
            WorkflowState.FAILED,
            WorkflowState.CANCELLED,
        ]:
            fsm = WorkflowStateMachine(WorkflowState.AWAITING_APPROVAL)
            fsm.transition_to(target)
            self.assertEqual(fsm.current_state, target)

    def test_valid_transitions_from_paused(self):
        """Test all valid transitions originating from paused."""
        for target in [
            WorkflowState.RUNNING,
            WorkflowState.AWAITING_APPROVAL,
            WorkflowState.CANCELLED,
        ]:
            fsm = WorkflowStateMachine(WorkflowState.PAUSED)
            fsm.transition_to(target)
            self.assertEqual(fsm.current_state, target)

    def test_illegal_transitions_rejected(self):
        """Verify that illegal transitions raise IllegalStateTransitionError."""
        # draft cannot jump directly to succeeded
        fsm = WorkflowStateMachine(WorkflowState.DRAFT)
        self.assertFalse(fsm.can_transition_to(WorkflowState.SUCCEEDED))
        with self.assertRaises(IllegalStateTransitionError) as ctx:
            fsm.transition_to(WorkflowState.SUCCEEDED)
        self.assertIn("Illegal transition from 'draft' to 'succeeded'", str(ctx.exception))

        # draft cannot jump to paused
        with self.assertRaises(IllegalStateTransitionError):
            fsm.transition_to(WorkflowState.PAUSED)

        # awaiting_approval cannot jump directly to succeeded without running
        fsm_approval = WorkflowStateMachine(WorkflowState.AWAITING_APPROVAL)
        self.assertFalse(fsm_approval.can_transition_to(WorkflowState.SUCCEEDED))
        with self.assertRaises(IllegalStateTransitionError):
            fsm_approval.transition_to(WorkflowState.SUCCEEDED)

        # paused cannot jump directly to succeeded
        fsm_paused = WorkflowStateMachine(WorkflowState.PAUSED)
        self.assertFalse(fsm_paused.can_transition_to(WorkflowState.SUCCEEDED))
        with self.assertRaises(IllegalStateTransitionError):
            fsm_paused.transition_to(WorkflowState.SUCCEEDED)

    def test_terminal_states_strictly_locked(self):
        """Verify that once in a terminal state, all transitions are strictly rejected."""
        terminal_states = [WorkflowState.SUCCEEDED, WorkflowState.FAILED, WorkflowState.CANCELLED]

        for term in terminal_states:
            fsm = WorkflowStateMachine(term)
            self.assertTrue(fsm.is_terminal)
            self.assertEqual(fsm.get_valid_transitions(), set())

            # Attempt transitioning to all 7 states
            for target in WorkflowState:
                self.assertFalse(fsm.can_transition_to(target))
                with self.assertRaises(IllegalStateTransitionError) as ctx:
                    fsm.transition_to(target)
                self.assertIn("terminal state", str(ctx.exception).lower())

    def test_transition_history_auditing(self):
        """Test that state transitions are faithfully recorded in history."""
        fsm = WorkflowStateMachine(WorkflowState.DRAFT)
        fsm.transition_to(WorkflowState.RUNNING, reason="Start job")
        fsm.transition_to(WorkflowState.PAUSED, reason="Operator break")
        fsm.transition_to(WorkflowState.RUNNING, reason="Resume job")
        fsm.transition_to(WorkflowState.SUCCEEDED, reason="Job completed")

        self.assertEqual(len(fsm.history), 4)
        records = [r.to_dict() for r in fsm.history]

        self.assertEqual(records[0]["from_state"], "draft")
        self.assertEqual(records[0]["to_state"], "running")
        self.assertEqual(records[0]["reason"], "Start job")

        self.assertEqual(records[1]["from_state"], "running")
        self.assertEqual(records[1]["to_state"], "paused")

        self.assertEqual(records[2]["from_state"], "paused")
        self.assertEqual(records[2]["to_state"], "running")

        self.assertEqual(records[3]["from_state"], "running")
        self.assertEqual(records[3]["to_state"], "succeeded")

    def test_transition_with_string_value(self):
        """Test that transition_to accepts string values matching valid enum states."""
        fsm = WorkflowStateMachine()
        fsm.transition_to("running")
        self.assertEqual(fsm.current_state, WorkflowState.RUNNING)

        # Invalid string raises IllegalStateTransitionError
        with self.assertRaises(IllegalStateTransitionError):
            fsm.transition_to("invalid_unknown_state")


if __name__ == "__main__":
    unittest.main()
