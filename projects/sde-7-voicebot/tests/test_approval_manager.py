"""
Unit tests for ApprovalManager:
- Creation and validation of approval requests
- State lifecycle (PENDING, APPROVED, REJECTED, EXPIRED)
- TTL and timestamp-based expiry handling
- Target step binding (an approval applies strictly to its intended step)
- Approval decision audit logging
- Resumption authorization validation
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to sys.path for direct or discovered execution
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import unittest
from agentic_workflow.approval_manager import ApprovalError, ApprovalManager


class TestApprovalManager(unittest.TestCase):
    """Test suite verifying human-in-the-loop approval management and safety rules."""

    def setUp(self):
        self.mgr = ApprovalManager()

    def test_create_valid_request(self):
        """Test creating a valid approval request."""
        req = self.mgr.create_request(
            workflow_id="wf-101",
            step_id="step_update",
            tool_name="student_status_update",
            action_description="Approve status update for student S101",
        )
        self.assertEqual(req.workflow_id, "wf-101")
        self.assertEqual(req.step_id, "step_update")
        self.assertEqual(req.tool_name, "student_status_update")
        self.assertEqual(req.status, "PENDING")
        self.assertTrue(req.is_pending())
        self.assertFalse(req.is_approved())
        self.assertFalse(req.is_rejected())
        self.assertFalse(req.is_expired())

        # Check retrieval
        self.assertIs(self.mgr.get_request("step_update"), req)
        self.assertIs(self.mgr.get_request_by_id(req.request_id), req)

    def test_invalid_request_creation_rejected(self):
        """Verify invalid approval requests are rejected with clear errors."""
        with self.assertRaises(ApprovalError):
            self.mgr.create_request(workflow_id="", step_id="s1", tool_name="tool")
        with self.assertRaises(ApprovalError):
            self.mgr.create_request(workflow_id="wf-1", step_id="", tool_name="tool")
        with self.assertRaises(ApprovalError):
            self.mgr.create_request(workflow_id="wf-1", step_id="s1", tool_name="")

    def test_approve_request(self):
        """Test explicitly approving a pending request."""
        req = self.mgr.create_request(
            workflow_id="wf-102",
            step_id="step_change",
            tool_name="student_status_update",
        )
        approved_req = self.mgr.approve(
            step_id="step_change",
            reason="Dean signed waiver",
            approver="dean_smith",
        )
        self.assertEqual(approved_req.status, "APPROVED")
        self.assertTrue(approved_req.is_approved())
        self.assertFalse(approved_req.is_pending())
        self.assertEqual(approved_req.decision_reason, "Dean signed waiver")
        self.assertIsNotNone(approved_req.decided_at)

        # Execution check
        can_exec, err = self.mgr.can_execute_step("step_change")
        self.assertTrue(can_exec)
        self.assertIsNone(err)

    def test_reject_request(self):
        """Test explicitly rejecting a pending request."""
        req = self.mgr.create_request(
            workflow_id="wf-103",
            step_id="step_expel",
            tool_name="student_status_update",
        )
        rejected_req = self.mgr.reject(
            step_id="step_expel",
            reason="Unsubstantiated allegation",
            approver="hearing_board",
        )
        self.assertEqual(rejected_req.status, "REJECTED")
        self.assertTrue(rejected_req.is_rejected())
        self.assertFalse(rejected_req.is_pending())
        self.assertIn("Unsubstantiated allegation", rejected_req.decision_reason)

        # Execution check: CANNOT execute
        can_exec, err = self.mgr.can_execute_step("step_expel")
        self.assertFalse(can_exec)
        self.assertIn("rejected", err)

    def test_approval_target_step_binding(self):
        """
        Verify that an approval decision is strictly bound to the intended step
        and cannot inadvertently authorize another step.
        """
        self.mgr.create_request(workflow_id="wf-bind", step_id="step_target", tool_name="student_status_update")
        self.mgr.create_request(workflow_id="wf-bind", step_id="step_other", tool_name="student_status_update")

        self.mgr.approve(step_id="step_target", reason="Target approved")

        # Target step is authorized
        can_exec_target, _ = self.mgr.can_execute_step("step_target")
        self.assertTrue(can_exec_target)

        # Other step remains pending and unauthorized
        can_exec_other, err_other = self.mgr.can_execute_step("step_other")
        self.assertFalse(can_exec_other)
        self.assertIn("pending", err_other)

    def test_cannot_decide_nonexistent_or_already_decided_request(self):
        """Verify errors when attempting to decide unknown or already decided requests."""
        # Nonexistent step
        with self.assertRaises(ApprovalError):
            self.mgr.approve("step_ghost")
        with self.assertRaises(ApprovalError):
            self.mgr.reject("step_ghost")

        # Double decision
        self.mgr.create_request(workflow_id="wf-double", step_id="s1", tool_name="tool")
        self.mgr.approve("s1")
        with self.assertRaises(ApprovalError):
            self.mgr.approve("s1")
        with self.assertRaises(ApprovalError):
            self.mgr.reject("s1")

    def test_approval_expiry_via_ttl(self):
        """Test approval request expiry based on time-to-live (TTL)."""
        # Create request that expired 10 seconds ago
        past_time = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        req = self.mgr.create_request(
            workflow_id="wf-exp",
            step_id="step_expired",
            tool_name="student_status_update",
            expires_at=past_time,
        )

        # get_request triggers automatic expiry check
        fetched = self.mgr.get_request("step_expired")
        self.assertEqual(fetched.status, "EXPIRED")
        self.assertTrue(fetched.is_expired())

        # Attempting to approve an expired request must fail
        with self.assertRaises(ApprovalError):
            self.mgr.approve("step_expired")

        # Attempting to execute an expired request must fail
        can_exec, err = self.mgr.can_execute_step("step_expired")
        self.assertFalse(can_exec)
        self.assertIn("expired", err.lower())

    def test_check_expiries_sweep(self):
        """Test scanning and expiring stale approval requests."""
        past_time = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        future_time = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()

        self.mgr.create_request(workflow_id="wf-sweep", step_id="stale_step", tool_name="tool", expires_at=past_time)
        self.mgr.create_request(workflow_id="wf-sweep", step_id="fresh_step", tool_name="tool", expires_at=future_time)

        expired_steps = self.mgr.check_expiries()
        self.assertIn("stale_step", expired_steps)
        self.assertNotIn("fresh_step", expired_steps)

        stale_req = self.mgr.get_request("stale_step")
        self.assertTrue(stale_req.is_expired())

        fresh_req = self.mgr.get_request("fresh_step")
        self.assertTrue(fresh_req.is_pending())

    def test_audit_log_captures_all_events(self):
        """Verify that every lifecycle transition generates an immutable audit record."""
        self.mgr.create_request(workflow_id="wf-audit", step_id="step_1", tool_name="tool_a")
        self.mgr.approve("step_1", reason="Operator approved", approver="admin_user")

        self.mgr.create_request(workflow_id="wf-audit", step_id="step_2", tool_name="tool_b")
        self.mgr.reject("step_2", reason="Operator rejected", approver="compliance_officer")

        self.mgr.create_request(workflow_id="wf-audit", step_id="step_3", tool_name="tool_c")
        self.mgr.expire("step_3", reason="Manual timeout")

        entries = self.mgr.audit_log
        self.assertEqual(len(entries), 6)  # 3 requested + 1 approved + 1 rejected + 1 expired

        decisions = [e.decision for e in entries]
        self.assertEqual(decisions, ["REQUESTED", "APPROVED", "REQUESTED", "REJECTED", "REQUESTED", "EXPIRED"])


if __name__ == "__main__":
    unittest.main()

