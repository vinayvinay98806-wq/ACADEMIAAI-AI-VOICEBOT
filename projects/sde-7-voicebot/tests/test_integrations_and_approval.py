"""
Unit and Integration Tests for Week 3 Days 19-21:
- WorkflowProposals integration & validation (valid, invalid, conversion)
- Backend approval-state integration (mock mode default, stale local prevention, unavailable)
- UI approval and rejection integration (approve, reject, duplicate, expired, binding mismatch)
- Approval security proofs (no tool execution after rejection, expiry, duplicate, wrong binding)
"""

from __future__ import annotations

import sys
import threading
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import unittest
from agentic_workflow import (
    ApprovalManager,
    ApprovalUIService,
    BackendApprovalState,
    BackendUnavailableError,
    HttpBackendApprovalClient,
    IdempotencyStore,
    MockBackendApprovalClient,
    ProposalValidationError,
    UIApprovalAction,
    WorkflowExecutor,
    WorkflowPlan,
    WorkflowProposalAdapter,
    WorkflowState,
    WorkflowStep,
    create_default_registry,
)


@dataclass
class _DuckTypedProposal:
    proposal_id: str
    goal: str
    steps: List[Dict[str, Any]]
    workflow_id: str | None = None
    confidence: float = 0.95


class TestIntegrationsAndApprovalSecurity(unittest.TestCase):
    """Tests for Days 19-21 proposal, backend approval, and UI integration security."""

    def setUp(self) -> None:
        self.registry = create_default_registry()
        self.registry.reset_counts()
        self.adapter = WorkflowProposalAdapter(registry=self.registry)

    # ------------------------------------------------------------------
    # WorkflowProposals Integration
    # ------------------------------------------------------------------

    def test_valid_reasoning_proposal_and_conversion(self) -> None:
        """Verify valid reasoning proposals convert cleanly while preserving proposal/workflow IDs."""
        proposals_batch = {
            "batch_id": "batch-r3-01",
            "proposals": [
                {
                    "proposal_id": "prop-101",
                    "workflow_id": "wf-from-prop-101",
                    "intent": "Lookup S101 and update status to on_leave",
                    "steps": [
                        {
                            "id": "s_lookup",
                            "tool": "academic_lookup",
                            "parameters": {"record_type": "student", "record_id": "S101"},
                        },
                        {
                            "id": "s_update",
                            "action": "student_status_update",
                            "arguments": {
                                "student_id": "$s_lookup.student_id",
                                "new_status": "on_leave",
                                "reason": "Approved medical leave",
                            },
                            "depends_on": ["s_lookup"],
                            "idempotency_key": "idem-prop-101-s-update",
                        },
                    ],
                }
            ],
        }

        plans = self.adapter.convert_workflow_proposals(
            proposals_batch,
            authorized_permissions={"academic:read", "academic:write"},
        )
        self.assertEqual(len(plans), 1)
        plan = plans[0]
        self.assertIsInstance(plan, WorkflowPlan)
        self.assertEqual(plan.workflow_id, "wf-from-prop-101")
        self.assertEqual(plan.metadata["proposal_id"], "prop-101")
        self.assertEqual(plan.metadata["proposals_batch_id"], "batch-r3-01")
        self.assertEqual(plan.get_step("s_update").dependencies, ["s_lookup"])
        self.assertEqual(plan.get_step("s_update").metadata["proposal_id"], "prop-101")
        self.assertEqual(plan.get_step("s_update").metadata["idempotency_key"], "idem-prop-101-s-update")

        # Duck-typed proposal model also supported
        duck = _DuckTypedProposal(
            proposal_id="prop-duck-1",
            goal="Lookup CS101",
            steps=[{"step_id": "s1", "tool_name": "academic_lookup", "input_payload": {"record_type": "course", "record_id": "CS101"}}],
        )
        duck_plan = self.adapter.validate_and_convert(duck)
        self.assertEqual(duck_plan.workflow_id, "wf-prop-duck-1")
        self.assertEqual(duck_plan.metadata["proposal_id"], "prop-duck-1")

    def test_invalid_reasoning_proposal_rejected(self) -> None:
        """Verify invalid or unsupported reasoning proposals are rejected safely."""
        # Missing proposal_id
        with self.assertRaises(ProposalValidationError):
            self.adapter.validate_and_convert({"goal": "Test", "steps": [{"tool_name": "academic_lookup"}]})

        # Unsupported proposal flag
        with self.assertRaises(ProposalValidationError):
            self.adapter.validate_and_convert({"proposal_id": "p1", "goal": "Test", "supported": False, "steps": [{"tool_name": "academic_lookup"}]})

        # Unregistered tool
        with self.assertRaises(ProposalValidationError):
            self.adapter.validate_and_convert({
                "proposal_id": "p2",
                "goal": "Run unknown tool",
                "steps": [{"step_id": "s1", "tool_name": "drop_database", "input_payload": {}}],
            })

        # Insufficient permissions
        with self.assertRaises(ProposalValidationError):
            self.adapter.validate_and_convert(
                {
                    "proposal_id": "p3",
                    "goal": "Unauthorized write",
                    "steps": [
                        {
                            "step_id": "s1",
                            "tool_name": "student_status_update",
                            "input_payload": {"student_id": "S101", "new_status": "active", "reason": "Test"},
                        }
                    ],
                },
                authorized_permissions={"academic:read"},
            )

    # ------------------------------------------------------------------
    # Backend Approval-State Integration
    # ------------------------------------------------------------------

    def test_backend_approval_state_retrieval_and_stale_local_protection(self) -> None:
        """
        Verify authoritative backend state overrides stale local APPROVED state
        when backend reports PENDING or REJECTED.
        """
        backend = MockBackendApprovalClient()
        plan = WorkflowPlan(
            workflow_id="wf-backend-sync",
            goal="Respect authoritative backend state",
            steps=[
                WorkflowStep(
                    step_id="step_write",
                    tool_name="student_status_update",
                    input_payload={"student_id": "S101", "new_status": "on_leave", "reason": "Backend check"},
                )
            ],
        )
        executor = WorkflowExecutor(plan=plan, registry=self.registry, backend_approval_client=backend)

        # Phase 1: creates request locally and publishes PENDING to backend
        executor.run()
        self.assertEqual(executor.current_state, WorkflowState.AWAITING_APPROVAL)
        req = executor.get_approval_request("step_write")
        assert req is not None

        # Simulate stale local cache claiming APPROVED while backend is still PENDING
        req.status = "APPROVED"
        res_pending = executor.run()
        self.assertEqual(executor.current_state, WorkflowState.AWAITING_APPROVAL)
        self.assertEqual(res_pending.metadata.get("state"), "awaiting_approval")
        self.assertEqual(self.registry.get_invocation_count("student_status_update"), 0)

        # Authoritative backend rejects -> local stale approval must NOT execute tool
        req.status = "APPROVED"
        backend.seed_state(
            BackendApprovalState(
                request_id=req.request_id,
                workflow_id="wf-backend-sync",
                step_id="step_write",
                status="REJECTED",
                tool_name="student_status_update",
                decision_reason="Rejected in authoritative backend",
            )
        )
        res_rejected = executor.run()
        self.assertFalse(res_rejected.success)
        self.assertEqual(executor.current_state, WorkflowState.FAILED)
        self.assertEqual(self.registry.get_invocation_count("student_status_update"), 0)

    def test_backend_unavailable_blocks_consequential_execution(self) -> None:
        """Verify consequential tool NEVER executes when backend approval service is unavailable."""
        backend = MockBackendApprovalClient(available=True)
        plan = WorkflowPlan(
            workflow_id="wf-backend-down",
            goal="Handle backend outage safely",
            steps=[
                WorkflowStep(
                    step_id="step_write",
                    tool_name="student_status_update",
                    input_payload={"student_id": "S102", "new_status": "active", "reason": "Outage test"},
                )
            ],
        )
        executor = WorkflowExecutor(plan=plan, registry=self.registry, backend_approval_client=backend)
        executor.run()
        req = executor.get_approval_request("step_write")
        assert req is not None

        # Even if local request looks approved, backend unavailability must block execution
        req.status = "APPROVED"
        backend.set_available(False)
        res = executor.run()

        self.assertFalse(res.success)
        self.assertTrue(res.metadata.get("backend_unavailable"))
        self.assertEqual(executor.current_state, WorkflowState.FAILED)
        self.assertEqual(self.registry.get_invocation_count("student_status_update"), 0)

    # ------------------------------------------------------------------
    # UI Approval / Rejection & Security
    # ------------------------------------------------------------------

    def test_ui_successful_approval_and_duplicate_submission_blocked(self) -> None:
        """
        Verify UI approval executes tool once, and duplicate UI submissions
        (with same or different submission_id) NEVER execute the tool twice.
        """
        backend = MockBackendApprovalClient()
        idem_store = IdempotencyStore()
        ui = ApprovalUIService(auto_resume_on_approve=True)

        plan = WorkflowPlan(
            workflow_id="wf-ui-approve",
            goal="Approve via UI contract",
            steps=[
                WorkflowStep(
                    step_id="step_update",
                    tool_name="student_status_update",
                    input_payload={"student_id": "S101", "new_status": "on_leave", "reason": "UI approved"},
                )
            ],
        )
        executor = WorkflowExecutor(
            plan=plan,
            registry=self.registry,
            backend_approval_client=backend,
            idempotency_store=idem_store,
        )
        ui.register_executor(executor)
        executor.run()

        pending = ui.list_pending_approvals("wf-ui-approve")
        self.assertEqual(len(pending), 1)
        self.assertTrue(pending[0].can_decide)

        # First UI approval click
        resp1 = ui.submit_decision(
            UIApprovalAction(
                workflow_id="wf-ui-approve",
                step_id="step_update",
                request_id=pending[0].request_id,
                decision="APPROVE",
                reason="Confirmed by advisor",
                operator_id="advisor_1",
                submission_id="ui-click-1",
            )
        )
        self.assertTrue(resp1.accepted)
        self.assertFalse(resp1.duplicate_submission)
        self.assertEqual(resp1.status, "APPROVED")
        self.assertEqual(resp1.workflow_state, "succeeded")
        self.assertEqual(self.registry.get_invocation_count("student_status_update"), 1)

        # Duplicate click with same submission_id
        resp2 = ui.submit_decision(
            UIApprovalAction(
                workflow_id="wf-ui-approve",
                step_id="step_update",
                decision="APPROVE",
                submission_id="ui-click-1",
            )
        )
        self.assertTrue(resp2.duplicate_submission)
        self.assertEqual(self.registry.get_invocation_count("student_status_update"), 1)

        # Duplicate click with new submission_id against already-approved request
        resp3 = ui.submit_decision(
            UIApprovalAction(
                workflow_id="wf-ui-approve",
                step_id="step_update",
                decision="APPROVE",
                submission_id="ui-click-2",
            )
        )
        self.assertFalse(resp3.accepted)
        self.assertTrue(resp3.duplicate_submission)
        self.assertEqual(resp3.error_code, "ALREADY_DECIDED")
        self.assertEqual(self.registry.get_invocation_count("student_status_update"), 1)

    def test_ui_rejection_never_executes_tool(self) -> None:
        """Verify UI rejection transitions workflow to failed with tool invocation count == 0."""
        ui = ApprovalUIService(auto_resume_on_approve=True)
        plan = WorkflowPlan(
            workflow_id="wf-ui-reject",
            goal="Reject via UI contract",
            steps=[
                WorkflowStep(
                    step_id="step_update",
                    tool_name="student_status_update",
                    input_payload={"student_id": "S102", "new_status": "probation", "reason": "Review"},
                )
            ],
        )
        executor = WorkflowExecutor(plan=plan, registry=self.registry)
        ui.register_executor(executor)
        executor.run()

        resp = ui.submit_decision(
            UIApprovalAction(
                workflow_id="wf-ui-reject",
                step_id="step_update",
                decision="REJECT",
                reason="Insufficient evidence",
                operator_id="dean_1",
            )
        )
        self.assertTrue(resp.accepted)
        self.assertEqual(resp.status, "REJECTED")
        self.assertEqual(resp.workflow_state, "failed")
        self.assertEqual(self.registry.get_invocation_count("student_status_update"), 0)

    def test_expired_approval_rejected_by_ui_and_executor(self) -> None:
        """Verify expired approvals cannot be approved or executed (tool count == 0)."""
        ui = ApprovalUIService(auto_resume_on_approve=True)
        past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        plan = WorkflowPlan(
            workflow_id="wf-ui-expired",
            goal="Expired approval security",
            steps=[
                WorkflowStep(
                    step_id="step_update",
                    tool_name="student_status_update",
                    input_payload={"student_id": "S103", "new_status": "active", "reason": "Expired"},
                    metadata={"approval_expires_at": past},
                )
            ],
        )
        executor = WorkflowExecutor(plan=plan, registry=self.registry)
        ui.register_executor(executor)
        res = executor.run()
        self.assertFalse(res.success)
        self.assertEqual(executor.current_state, WorkflowState.FAILED)
        self.assertEqual(self.registry.get_invocation_count("student_status_update"), 0)

        # UI submission against expired request must fail with APPROVAL_EXPIRED
        resp = ui.submit_decision(
            UIApprovalAction(workflow_id="wf-ui-expired", step_id="step_update", decision="APPROVE")
        )
        self.assertFalse(resp.accepted)
        self.assertEqual(resp.error_code, "APPROVAL_EXPIRED")
        self.assertEqual(self.registry.get_invocation_count("student_status_update"), 0)

    def test_approval_for_wrong_workflow_or_step_rejected(self) -> None:
        """Verify approval bound to workflow A / step X cannot authorize workflow B / step Y."""
        ui = ApprovalUIService(auto_resume_on_approve=True)
        plan_a = WorkflowPlan(
            workflow_id="wf-A",
            goal="Workflow A",
            steps=[
                WorkflowStep(
                    step_id="step_a",
                    tool_name="student_status_update",
                    input_payload={"student_id": "S101", "new_status": "active", "reason": "A"},
                )
            ],
        )
        plan_b = WorkflowPlan(
            workflow_id="wf-B",
            goal="Workflow B",
            steps=[
                WorkflowStep(
                    step_id="step_b",
                    tool_name="student_status_update",
                    input_payload={"student_id": "S102", "new_status": "on_leave", "reason": "B"},
                )
            ],
        )
        exec_a = WorkflowExecutor(plan=plan_a, registry=self.registry)
        exec_b = WorkflowExecutor(plan=plan_b, registry=self.registry)
        ui.register_executor(exec_a)
        ui.register_executor(exec_b)
        exec_a.run()
        exec_b.run()

        req_a = exec_a.get_approval_request("step_a")
        assert req_a is not None

        # Passing req_a.request_id to workflow B / step_b must fail binding check
        bad_resp = ui.submit_decision(
            UIApprovalAction(
                workflow_id="wf-B",
                step_id="step_b",
                request_id=req_a.request_id,
                decision="APPROVE",
            )
        )
        self.assertFalse(bad_resp.accepted)
        self.assertEqual(bad_resp.error_code, "BINDING_MISMATCH")
        self.assertEqual(self.registry.get_invocation_count("student_status_update"), 0)

        # Direct ApprovalManager binding mismatch check
        exec_b.approval_requests["step_b"] = req_a  # Simulate mismatched request placed on step_b
        can_exec, err = exec_b.approval_manager.can_execute_step("step_b", workflow_id="wf-B")
        self.assertFalse(can_exec)
        self.assertIn("mismatch", err.lower())

        # Running exec_b with mismatched approval request must fail without calling tool
        req_a.approve("Approved for A")
        res_b = exec_b.run()
        self.assertFalse(res_b.success)
        self.assertEqual(self.registry.get_invocation_count("student_status_update"), 0)

    def test_proposal_cannot_downgrade_consequential_tool_and_rejects_malformed_fields(self) -> None:
        """
        Security tests for WorkflowProposalAdapter:
        - student_status_update with is_consequential=False must still require approval
        - student_status_update with requires_approval=False must still require approval
        - harmless tool with valid metadata executes without approval
        - malformed metadata / max_retries / timeout_seconds raise ProposalValidationError
        """
        for flag_key in ("is_consequential", "requires_approval"):
            self.registry.reset_counts()
            proposal = {
                "proposal_id": f"prop-downgrade-{flag_key}",
                "goal": "Attempt consequential downgrade",
                "steps": [
                    {
                        "step_id": "s_upd",
                        "tool_name": "student_status_update",
                        "input_payload": {
                            "student_id": "S101",
                            "new_status": "on_leave",
                            "reason": "Downgrade probe",
                        },
                        flag_key: False,
                    }
                ],
            }
            plan = self.adapter.validate_and_convert(
                proposal,
                authorized_permissions={"academic:write"},
            )
            step = plan.get_step("s_upd")
            self.assertTrue(step.is_consequential)
            self.assertTrue(step.metadata.get("downgrade_attempt_blocked"))

            executor = WorkflowExecutor(
                plan=plan,
                registry=self.registry,
                authorized_permissions={"academic:write"},
            )
            res = executor.run()
            self.assertEqual(executor.current_state, WorkflowState.AWAITING_APPROVAL)
            self.assertEqual(res.metadata.get("state"), "awaiting_approval")
            self.assertEqual(self.registry.get_invocation_count("student_status_update"), 0)

        # Harmless tool with valid metadata executes cleanly without approval
        harmless_plan = self.adapter.validate_and_convert(
            {
                "proposal_id": "prop-harmless-meta",
                "goal": "Harmless lookup",
                "steps": [
                    {
                        "step_id": "s_read",
                        "tool_name": "academic_lookup",
                        "input_payload": {"record_type": "student", "record_id": "S101"},
                        "metadata": {"trace": "r3"},
                    }
                ],
            },
            authorized_permissions={"academic:read"},
        )
        harmless_exec = WorkflowExecutor(plan=harmless_plan, registry=self.registry)
        harmless_res = harmless_exec.run()
        self.assertTrue(harmless_res.success)
        self.assertEqual(self.registry.get_invocation_count("academic_lookup"), 1)

        # Malformed proposal fields raise ProposalValidationError
        malformed_cases = [
            {"proposal_id": "prop-bad-retries", "goal": "Bad retries", "steps": [{"tool_name": "academic_lookup", "input_payload": {"record_type": "student", "record_id": "S101"}, "max_retries": "abc"}]},
            {"proposal_id": "prop-bad-meta", "goal": "Bad metadata", "steps": [{"tool_name": "academic_lookup", "input_payload": {"record_type": "student", "record_id": "S101"}, "metadata": "not_a_dict"}]},
            {"proposal_id": "prop-nan-timeout", "goal": "NaN timeout", "steps": [{"tool_name": "academic_lookup", "input_payload": {"record_type": "student", "record_id": "S101"}, "timeout_seconds": float("nan")}]},
            {"proposal_id": "prop-inf-timeout", "goal": "Inf timeout", "steps": [{"tool_name": "academic_lookup", "input_payload": {"record_type": "student", "record_id": "S101"}, "timeout_seconds": float("inf")}]},
            {"proposal_id": "prop-neg-wf-timeout", "goal": "Neg timeout", "timeout_seconds": -1, "steps": [{"tool_name": "academic_lookup", "input_payload": {"record_type": "student", "record_id": "S101"}}]},
            {"proposal_id": "prop-bad-deps-str", "goal": "Bad deps", "steps": [{"tool_name": "academic_lookup", "input_payload": {"record_type": "student", "record_id": "S101"}, "dependencies": "s0"}]},
            {"proposal_id": "prop-bad-deps-item", "goal": "Bad dep item", "steps": [{"tool_name": "academic_lookup", "input_payload": {"record_type": "student", "record_id": "S101"}, "dependencies": [123]}]},
            {"proposal_id": "prop-bad-payload", "goal": "Bad payload", "steps": [{"tool_name": "academic_lookup", "input_payload": "not_a_dict"}]},
            {"proposal_id": "prop-bad-conseq", "goal": "Bad conseq", "steps": [{"tool_name": "academic_lookup", "input_payload": {"record_type": "student", "record_id": "S101"}, "is_consequential": "false"}]},
            {"proposal_id": {"bad": 1}, "goal": "Bad id", "steps": [{"tool_name": "academic_lookup", "input_payload": {"record_type": "student", "record_id": "S101"}}]},
        ]
        for bad_prop in malformed_cases:
            with self.assertRaises(ProposalValidationError):
                self.adapter.validate_and_convert(bad_prop)

    def test_approval_manager_cross_workflow_isolation_same_step_id(self) -> None:
        """
        Verify two workflows sharing an ApprovalManager with identical step_id remain
        strictly isolated for approve, reject, and can_execute_step.
        """
        mgr = ApprovalManager()
        mgr.create_request("wf-one", "step_1", "student_status_update")
        mgr.create_request("wf-two", "step_1", "student_status_update")

        # Approve wf-one only -> wf-two must remain pending
        mgr.approve("step_1", reason="OK for wf-one", workflow_id="wf-one")
        ok1, _ = mgr.can_execute_step("step_1", workflow_id="wf-one")
        ok2, err2 = mgr.can_execute_step("step_1", workflow_id="wf-two")
        self.assertTrue(ok1)
        self.assertFalse(ok2)
        self.assertIn("pending", err2.lower())

        # Reject wf-two -> wf-one must remain approved
        mgr.reject("step_1", reason="Denied for wf-two", workflow_id="wf-two")
        ok1_after, _ = mgr.can_execute_step("step_1", workflow_id="wf-one")
        ok2_after, err2_after = mgr.can_execute_step("step_1", workflow_id="wf-two")
        self.assertTrue(ok1_after)
        self.assertFalse(ok2_after)
        self.assertIn("rejected", err2_after.lower())

        # Shared ApprovalManager across two WorkflowExecutors with same step_id
        shared_mgr = ApprovalManager()
        ui = ApprovalUIService(auto_resume_on_approve=False)
        p1 = WorkflowPlan(
            workflow_id="wf-shared-1",
            goal="Shared 1",
            steps=[
                WorkflowStep(
                    step_id="step_1",
                    tool_name="student_status_update",
                    input_payload={"student_id": "S101", "new_status": "on_leave", "reason": "One"},
                )
            ],
        )
        p2 = WorkflowPlan(
            workflow_id="wf-shared-2",
            goal="Shared 2",
            steps=[
                WorkflowStep(
                    step_id="step_1",
                    tool_name="student_status_update",
                    input_payload={"student_id": "S102", "new_status": "on_leave", "reason": "Two"},
                )
            ],
        )
        e1 = WorkflowExecutor(plan=p1, registry=self.registry, approval_manager=shared_mgr)
        e2 = WorkflowExecutor(plan=p2, registry=self.registry, approval_manager=shared_mgr)
        ui.register_executor(e1)
        ui.register_executor(e2)
        e1.run()
        e2.run()

        pending_1 = ui.list_pending_approvals("wf-shared-1")
        pending_all = ui.list_pending_approvals()
        self.assertEqual(len(pending_1), 1)
        self.assertEqual(pending_1[0].workflow_id, "wf-shared-1")
        self.assertEqual({v.workflow_id for v in pending_all}, {"wf-shared-1", "wf-shared-2"})

        # Pause/resume wf-shared-1 after approving only wf-shared-1 must NOT block on wf-shared-2
        e1.pause("Pause before resume")
        e1.submit_approval("step_1", approved=True, reason="Approve wf-shared-1")
        res_1 = e1.resume()
        self.assertTrue(res_1.success)
        self.assertEqual(e2.current_state, WorkflowState.AWAITING_APPROVAL)

    def test_ui_cross_workflow_submission_id_reuse_and_concurrent_decisions(self) -> None:
        """
        Verify:
        1. Reusing submission_id on a different workflow/step does not return wrong cached response.
        2. Concurrent UI approval clicks execute the consequential tool strictly once.
        """
        ui = ApprovalUIService(auto_resume_on_approve=True)
        plan1 = WorkflowPlan(
            workflow_id="wf-ui-1",
            goal="WF 1",
            steps=[
                WorkflowStep(
                    step_id="step_1",
                    tool_name="student_status_update",
                    input_payload={"student_id": "S101", "new_status": "on_leave", "reason": "One"},
                )
            ],
        )
        plan2 = WorkflowPlan(
            workflow_id="wf-ui-2",
            goal="WF 2",
            steps=[
                WorkflowStep(
                    step_id="step_1",
                    tool_name="student_status_update",
                    input_payload={"student_id": "S102", "new_status": "on_leave", "reason": "Two"},
                )
            ],
        )
        exec1 = WorkflowExecutor(plan=plan1, registry=self.registry)
        exec2 = WorkflowExecutor(plan=plan2, registry=self.registry)
        ui.register_executor(exec1)
        ui.register_executor(exec2)
        exec1.run()
        exec2.run()

        # Approve wf-ui-1 with submission_id="shared-sub"
        r1 = ui.submit_decision(
            UIApprovalAction(workflow_id="wf-ui-1", step_id="step_1", decision="APPROVE", submission_id="shared-sub")
        )
        self.assertTrue(r1.accepted)
        self.assertFalse(r1.duplicate_submission)

        # Reuse submission_id="shared-sub" to REJECT wf-ui-2 -> must NOT return wf-ui-1's APPROVED response
        r2 = ui.submit_decision(
            UIApprovalAction(workflow_id="wf-ui-2", step_id="step_1", decision="REJECT", submission_id="shared-sub")
        )
        self.assertTrue(r2.accepted)
        self.assertFalse(r2.duplicate_submission)
        self.assertEqual(r2.status, "REJECTED")
        self.assertEqual(r2.workflow_state, "failed")
        self.assertEqual(self.registry.get_invocation_count("student_status_update"), 1)

        # Concurrent UI approval clicks on a third workflow
        self.registry.reset_counts()
        plan3 = WorkflowPlan(
            workflow_id="wf-ui-conc",
            goal="Concurrent UI clicks",
            steps=[
                WorkflowStep(
                    step_id="step_c",
                    tool_name="student_status_update",
                    input_payload={"student_id": "S103", "new_status": "active", "reason": "Conc"},
                )
            ],
        )
        exec3 = WorkflowExecutor(plan=plan3, registry=self.registry)
        ui.register_executor(exec3)
        exec3.run()

        barrier = threading.Barrier(4)
        responses = []

        def click_approve(idx: int) -> None:
            barrier.wait(timeout=2.0)
            responses.append(
                ui.submit_decision(
                    UIApprovalAction(
                        workflow_id="wf-ui-conc",
                        step_id="step_c",
                        decision="APPROVE",
                        submission_id=f"conc-click-{idx}",
                    )
                )
            )

        threads = [threading.Thread(target=click_approve, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        self.assertEqual(len(responses), 4)
        self.assertEqual(sum(1 for r in responses if r.accepted), 1)
        self.assertEqual(sum(1 for r in responses if r.error_code == "ALREADY_DECIDED"), 3)
        self.assertEqual(self.registry.get_invocation_count("student_status_update"), 1)

    def test_backend_expired_sync_post_approval_expiry_and_http_errors(self) -> None:
        """
        Verify:
        - Backend returning EXPIRED during sync blocks execution
        - Request approved before expires_at passes is blocked when expires_at elapses before run()
        - HttpBackendApprovalClient raises BackendUnavailableError on network/timeout errors
        """
        # 1. Backend reports EXPIRED
        backend = MockBackendApprovalClient()
        plan1 = WorkflowPlan(
            workflow_id="wf-backend-exp",
            goal="Backend expiry check",
            steps=[
                WorkflowStep(
                    step_id="step_w",
                    tool_name="student_status_update",
                    input_payload={"student_id": "S101", "new_status": "on_leave", "reason": "Exp"},
                )
            ],
        )
        exec1 = WorkflowExecutor(plan=plan1, registry=self.registry, backend_approval_client=backend)
        exec1.run()
        req1 = exec1.get_approval_request("step_w")
        assert req1 is not None

        backend.seed_state(
            BackendApprovalState(
                request_id=req1.request_id,
                workflow_id="wf-backend-exp",
                step_id="step_w",
                status="EXPIRED",
                tool_name="student_status_update",
                decision_reason="Backend TTL expired",
            )
        )
        res1 = exec1.run()
        self.assertFalse(res1.success)
        self.assertEqual(exec1.current_state, WorkflowState.FAILED)
        self.assertEqual(self.registry.get_invocation_count("student_status_update"), 0)

        # 2. Request approved, then expires_at passes before execution
        future_exp = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
        plan2 = WorkflowPlan(
            workflow_id="wf-post-approve-exp",
            goal="Post-approval expiry check",
            steps=[
                WorkflowStep(
                    step_id="step_w2",
                    tool_name="student_status_update",
                    input_payload={"student_id": "S101", "new_status": "on_leave", "reason": "Post exp"},
                    metadata={"approval_expires_at": future_exp},
                )
            ],
        )
        exec2 = WorkflowExecutor(plan=plan2, registry=self.registry)
        exec2.run()
        req2 = exec2.submit_approval("step_w2", approved=True, reason="Approved before deadline")
        # Simulate clock passing expiry right before execution
        req2.expires_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        res2 = exec2.run()
        self.assertFalse(res2.success)
        self.assertEqual(exec2.current_state, WorkflowState.FAILED)
        self.assertEqual(self.registry.get_invocation_count("student_status_update"), 0)

        # 3. HttpBackendApprovalClient error & timeout handling
        http_client = HttpBackendApprovalClient(base_url="http://localhost:9999", timeout_seconds=0.1)
        with patch("urllib.request.urlopen", side_effect=TimeoutError("Request timed out")):
            with self.assertRaises(BackendUnavailableError):
                http_client.get_approval_state("wf-1", "step-1")
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
            with self.assertRaises(BackendUnavailableError):
                http_client.get_approval_state("wf-1", "step-1")


if __name__ == "__main__":
    unittest.main()
