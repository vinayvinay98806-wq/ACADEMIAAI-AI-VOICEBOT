"""
Unit tests for Approval Enforcement in W4 Agentic Workflow.

Specifically verifies and PROVES:
1. Consequential actions default to 'awaiting_approval'.
2. A pending consequential action NEVER invokes its tool (tool invocation counter == 0).
3. A rejected consequential action NEVER invokes its tool (tool invocation counter == 0).
4. An explicitly approved consequential action executes and invokes its tool (tool invocation counter == 1).
5. Non-consequential actions execute without pausing for approval.
"""

import sys
from pathlib import Path

# Add project root to sys.path for direct or discovered execution
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import unittest
from agentic_workflow.executor import WorkflowExecutor
from agentic_workflow.mock_tools import create_default_registry
from agentic_workflow.schemas import WorkflowPlan, WorkflowStep
from agentic_workflow.state_machine import WorkflowState


class TestApprovalEnforcement(unittest.TestCase):
    """Test suite proving absolute approval enforcement and invocation prevention."""

    def setUp(self):
        self.registry = create_default_registry()
        self.registry.reset_counts()

    def test_consequential_action_defaults_to_awaiting_approval(self):
        """Verify consequential action automatically transitions workflow to awaiting_approval."""
        # student_status_update is consequential by default (ToolSpec.is_consequential = True)
        plan = WorkflowPlan(
            workflow_id="wf-consequential-default",
            goal="Update student status with approval required",
            steps=[
                WorkflowStep(
                    step_id="step-update-1",
                    tool_name="student_status_update",
                    input_payload={
                        "student_id": "S101",
                        "new_status": "on_leave",
                        "reason": "Family emergency",
                    },
                )
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=self.registry)
        result = executor.run()

        # State should be awaiting_approval
        self.assertEqual(executor.current_state, WorkflowState.AWAITING_APPROVAL)
        self.assertEqual(plan.state, "awaiting_approval")

        # Step status should be awaiting_approval
        step = plan.get_step("step-update-1")
        self.assertIsNotNone(step)
        self.assertEqual(step.status, "awaiting_approval")

        # ApprovalRequest should exist and be pending
        req = executor.get_approval_request("step-update-1")
        self.assertIsNotNone(req)
        self.assertTrue(req.is_pending())
        self.assertEqual(req.tool_name, "student_status_update")

    def test_pending_consequential_action_never_invokes_tool(self):
        """
        SAFETY PROOF 1:
        Verify that a pending consequential action NEVER invokes the underlying tool.
        """
        plan = WorkflowPlan(
            workflow_id="wf-pending-proof",
            goal="Verify tool is never called while pending approval",
            steps=[
                WorkflowStep(
                    step_id="step-update-pending",
                    tool_name="student_status_update",
                    input_payload={
                        "student_id": "S101",
                        "new_status": "graduated",
                        "reason": "Completed all credits",
                    },
                )
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=self.registry)

        # Before run: invocation count is 0
        self.assertEqual(self.registry.get_invocation_count("student_status_update"), 0)

        # Run 1: encounters consequential step, halts at awaiting_approval
        executor.run()
        self.assertEqual(executor.current_state, WorkflowState.AWAITING_APPROVAL)
        # PROOF: Tool invocation count MUST strictly be 0
        self.assertEqual(
            self.registry.get_invocation_count("student_status_update"),
            0,
            "Tool was invoked despite approval being pending!",
        )

        # Run 2: attempting to run again without deciding approval
        executor.run()
        self.assertEqual(executor.current_state, WorkflowState.AWAITING_APPROVAL)
        # PROOF: Tool invocation count STILL strictly 0
        self.assertEqual(
            self.registry.get_invocation_count("student_status_update"),
            0,
            "Tool was invoked on subsequent run while approval was still pending!",
        )

    def test_rejected_consequential_action_never_invokes_tool(self):
        """
        SAFETY PROOF 2:
        Verify that rejecting a consequential action halts execution and NEVER invokes the tool.
        """
        plan = WorkflowPlan(
            workflow_id="wf-reject-proof",
            goal="Verify rejected action never executes tool",
            steps=[
                WorkflowStep(
                    step_id="step-update-reject",
                    tool_name="student_status_update",
                    input_payload={
                        "student_id": "S102",
                        "new_status": "probation",
                        "reason": "Disciplinary review",
                    },
                )
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=self.registry)

        # Initial run reaches awaiting_approval
        executor.run()
        self.assertEqual(executor.current_state, WorkflowState.AWAITING_APPROVAL)
        self.assertEqual(self.registry.get_invocation_count("student_status_update"), 0)

        # Operator explicitly REJECTS the approval request
        executor.submit_approval("step-update-reject", approved=False, reason="Disciplinary action denied by appeals board")

        # Re-run after rejection
        result = executor.run()

        # Workflow must transition to FAILED
        self.assertEqual(executor.current_state, WorkflowState.FAILED)
        self.assertEqual(plan.state, "failed")
        self.assertFalse(result.success)
        self.assertIn("rejected", result.error.lower())
        self.assertIn("appeals board", result.error)

        # CRITICAL SAFETY PROOF: Tool invocation count must remain 0!
        self.assertEqual(
            self.registry.get_invocation_count("student_status_update"),
            0,
            "Tool was invoked despite being explicitly rejected by operator!",
        )

        # Step itself must be marked failed
        step = plan.get_step("step-update-reject")
        self.assertEqual(step.status, "failed")
        self.assertFalse(step.result.success)

    def test_approved_consequential_action_executes_successfully(self):
        """
        Verify that explicit approval transitions state to running, invokes the tool,
        and completes to succeeded.
        """
        plan = WorkflowPlan(
            workflow_id="wf-approve-flow",
            goal="Verify approved action invokes tool and succeeds",
            steps=[
                WorkflowStep(
                    step_id="step-update-approve",
                    tool_name="student_status_update",
                    input_payload={
                        "student_id": "S103",
                        "new_status": "active",
                        "reason": "Returned from leave of absence",
                    },
                )
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=self.registry)

        # Initial run: halts at awaiting_approval
        executor.run()
        self.assertEqual(executor.current_state, WorkflowState.AWAITING_APPROVAL)
        self.assertEqual(self.registry.get_invocation_count("student_status_update"), 0)

        # Operator grants approval
        executor.submit_approval("step-update-approve", approved=True, reason="Medical clearance submitted")

        # Resume execution
        result = executor.run()

        # Workflow successfully completes
        self.assertEqual(executor.current_state, WorkflowState.SUCCEEDED)
        self.assertEqual(plan.state, "succeeded")
        self.assertTrue(result.success)

        # Tool was invoked exactly ONCE
        self.assertEqual(self.registry.get_invocation_count("student_status_update"), 1)

        # Step record shows completed
        step = plan.get_step("step-update-approve")
        self.assertEqual(step.status, "completed")
        self.assertTrue(step.result.success)
        self.assertEqual(step.result.output["new_status"], "active")

    def test_non_consequential_tool_does_not_require_approval(self):
        """Verify non-consequential tools (academic_lookup) execute directly without approval."""
        plan = WorkflowPlan(
            workflow_id="wf-non-consequential",
            goal="Lookup student record",
            steps=[
                WorkflowStep(
                    step_id="step-lookup",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student", "record_id": "S101"},
                )
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=self.registry)
        result = executor.run()

        # Runs straight to succeeded without stopping at awaiting_approval
        self.assertEqual(executor.current_state, WorkflowState.SUCCEEDED)
        self.assertTrue(result.success)
        self.assertEqual(self.registry.get_invocation_count("academic_lookup"), 1)
        self.assertEqual(len(executor.approval_requests), 0)

    def test_explicit_step_consequential_override(self):
        """Verify that step.is_consequential=True forces approval even on harmless tools."""
        plan = WorkflowPlan(
            workflow_id="wf-override",
            goal="Harmless tool with explicit step consequentiality flag",
            steps=[
                WorkflowStep(
                    step_id="step-lookup-flagged",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student", "record_id": "S101"},
                    is_consequential=True,  # Explicitly flagged
                )
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=self.registry)
        executor.run()

        # Must halt at awaiting_approval
        self.assertEqual(executor.current_state, WorkflowState.AWAITING_APPROVAL)
        self.assertEqual(self.registry.get_invocation_count("academic_lookup"), 0)


if __name__ == "__main__":
    unittest.main()
