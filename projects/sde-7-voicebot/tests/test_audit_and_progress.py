"""
Unit and Integration Tests for Week 3 Days 17-18:
- Step-level immutable audit trail records
- Workflow progress events & subscriber notifications
- Chronological ordering and execution history retrieval by workflow_id
- Tracking failed and retried steps
- Preserving audit records & progress events across checkpoint and resume
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import unittest
from agentic_workflow import (
    AuditTrailManager,
    InMemoryCheckpointStore,
    ProgressEventType,
    ToolSpec,
    WorkflowExecutor,
    WorkflowPlan,
    WorkflowProgressEvent,
    WorkflowResult,
    WorkflowState,
    WorkflowStep,
    create_default_registry,
)


class TestAuditAndProgressEvents(unittest.TestCase):
    """Tests verifying Days 17-18 step-level audit trail and progress event guarantees."""

    def setUp(self) -> None:
        self.registry = create_default_registry()
        self.registry.reset_counts()

    def test_every_step_produces_structured_audit_record(self) -> None:
        """Verify every executed step produces structured audit records with timing & status."""
        plan = WorkflowPlan(
            workflow_id="wf-audit-steps",
            goal="Verify step-level audit fields",
            steps=[
                WorkflowStep(
                    step_id="step_1",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student", "record_id": "S101"},
                ),
                WorkflowStep(
                    step_id="step_2",
                    tool_name="student_status_update",
                    input_payload={"student_id": "S101", "new_status": "active", "reason": "Audit check"},
                    dependencies=["step_1"],
                ),
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=self.registry)
        executor.run()
        req = executor.get_approval_request("step_2")
        assert req is not None
        executor.submit_approval("step_2", approved=True, reason="Approved for audit test")
        res = executor.run()
        self.assertTrue(res.success)

        records = executor.get_step_audit_records()
        step1_recs = [r for r in records if r.step_id == "step_1" and r.event_type == "step_completed"]
        step2_recs = [r for r in records if r.step_id == "step_2" and r.event_type == "step_completed"]

        self.assertEqual(len(step1_recs), 1)
        self.assertEqual(len(step2_recs), 1)

        r1 = step1_recs[0]
        self.assertEqual(r1.workflow_id, "wf-audit-steps")
        self.assertEqual(r1.execution_id, executor.execution_id)
        self.assertEqual(r1.step_name, "academic_lookup")
        self.assertEqual(r1.previous_state, "running")
        self.assertEqual(r1.new_state, "completed")
        self.assertIsNotNone(r1.start_timestamp)
        self.assertIsNotNone(r1.completion_timestamp)
        self.assertIsNotNone(r1.duration_ms)
        self.assertEqual(r1.result_status, "success")

        r2 = step2_recs[0]
        self.assertEqual(r2.approval_reference, req.request_id)
        self.assertEqual(r2.result_status, "success")

    def test_progress_events_emitted_in_chronological_order(self) -> None:
        """Verify progress events are emitted to subscribers in strict chronological order."""
        observed: List[WorkflowProgressEvent] = []
        plan = WorkflowPlan(
            workflow_id="wf-progress-order",
            goal="Verify ordered progress events",
            steps=[
                WorkflowStep(
                    step_id="s1",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student", "record_id": "S101"},
                ),
                WorkflowStep(
                    step_id="s2",
                    tool_name="student_status_update",
                    input_payload={"student_id": "S101", "new_status": "on_leave", "reason": "Leave"},
                    dependencies=["s1"],
                ),
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=self.registry)
        executor.subscribe_progress(observed.append)

        executor.run()
        executor.submit_approval("s2", approved=True, reason="Approved")
        executor.run()

        event_types = [e.event_type for e in observed]
        self.assertIn(ProgressEventType.WORKFLOW_STARTED, event_types)
        self.assertIn(ProgressEventType.WORKFLOW_CHECKPOINT_CREATED, event_types)
        self.assertIn(ProgressEventType.STEP_STARTED, event_types)
        self.assertIn(ProgressEventType.STEP_COMPLETED, event_types)
        self.assertIn(ProgressEventType.APPROVAL_REQUESTED, event_types)
        self.assertIn(ProgressEventType.APPROVAL_GRANTED, event_types)
        self.assertIn(ProgressEventType.WORKFLOW_COMPLETED, event_types)

        sequences = [e.sequence for e in observed]
        self.assertEqual(sequences, sorted(sequences))
        self.assertEqual(len(set(sequences)), len(sequences))

    def test_failed_and_retried_steps_tracked_and_not_overwritten(self) -> None:
        """Verify failed, retrying, and recovery events are tracked immutably without overwriting."""
        calls = 0

        def flaky_twice(payload: Dict[str, Any]) -> WorkflowResult:
            nonlocal calls
            calls += 1
            if calls < 3:
                return WorkflowResult.fail(f"Transient error #{calls}")
            return WorkflowResult.ok({"ok": True})

        registry = create_default_registry()
        registry.register(
            ToolSpec(name="flaky_twice", description="Fails twice", is_idempotent=True),
            flaky_twice,
        )

        plan = WorkflowPlan(
            workflow_id="wf-retry-audit",
            goal="Track retries and failure/recovery",
            steps=[WorkflowStep(step_id="s_retry", tool_name="flaky_twice", max_retries=1)],
        )

        executor = WorkflowExecutor(plan=plan, registry=registry)
        # First run: fails once + 1 automatic retry -> fails
        res1 = executor.run()
        self.assertFalse(res1.success)

        # Recover failed step -> succeeds on 3rd call
        res2 = executor.recover_failed_step("s_retry", reason="Manual retry")
        self.assertTrue(res2.success)

        history = executor.get_execution_history()
        self.assertEqual(history.workflow_id, "wf-retry-audit")

        audit_types = [r.event_type for r in history.audit_records]
        self.assertIn("step_retrying", audit_types)
        self.assertIn("step_failed", audit_types)
        self.assertIn("step_completed", audit_types)

        progress_types = [e.event_type for e in history.progress_events]
        self.assertIn(ProgressEventType.STEP_RETRYING, progress_types)
        self.assertIn(ProgressEventType.STEP_FAILED, progress_types)
        self.assertIn(ProgressEventType.WORKFLOW_RESUMED, progress_types)
        self.assertIn(ProgressEventType.WORKFLOW_COMPLETED, progress_types)

        # State transitions include recovery transition failed -> running
        transitions = [(t["from_state"], t["to_state"]) for t in history.state_transitions]
        self.assertIn(("running", "failed"), transitions)
        self.assertIn(("failed", "running"), transitions)
        self.assertIn(("running", "succeeded"), transitions)

        # Returned list is a copy; mutating it does not overwrite stored audit records
        returned = executor.get_step_audit_records()
        orig_len = len(returned)
        returned.clear()
        self.assertEqual(len(executor.get_step_audit_records()), orig_len)

    def test_audit_information_survives_checkpoint_and_resume(self) -> None:
        """Verify audit records and progress events survive checkpointing into a new executor."""
        store = InMemoryCheckpointStore()
        plan = WorkflowPlan(
            workflow_id="wf-audit-survives",
            goal="Verify audit survival across checkpoint/resume",
            steps=[
                WorkflowStep(
                    step_id="step_1",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student", "record_id": "S101"},
                ),
                WorkflowStep(
                    step_id="step_2",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "course", "record_id": "CS101"},
                    dependencies=["step_1"],
                ),
            ],
        )

        exec1 = WorkflowExecutor(plan=plan, registry=self.registry, checkpoint_store=store)
        exec1.state_machine.transition_to(WorkflowState.RUNNING)
        exec1._record_step_audit(
            event_type="step_completed",
            step=plan.get_step("step_1"),
            previous_state="running",
            new_state="completed",
            result_status="success",
        )
        plan.get_step("step_1").status = "completed"
        plan.get_step("step_1").result = WorkflowResult.ok({"student_id": "S101"})
        exec1.pause("Paused for migration")
        chk = exec1.get_latest_checkpoint()
        assert chk is not None

        # New executor with fresh AuditTrailManager loaded from checkpoint
        fresh_audit = AuditTrailManager()
        exec2 = WorkflowExecutor.from_checkpoint(
            chk.checkpoint_id,
            checkpoint_store=store,
            registry=self.registry,
            audit_manager=fresh_audit,
        )
        res = exec2.resume_from_checkpoint(chk.checkpoint_id)
        self.assertTrue(res.success)

        history = exec2.get_execution_history()
        event_types = [e.event_type for e in history.progress_events]
        self.assertIn(ProgressEventType.WORKFLOW_PAUSED, event_types)
        self.assertIn(ProgressEventType.WORKFLOW_RESUMED, event_types)
        self.assertIn(ProgressEventType.WORKFLOW_COMPLETED, event_types)

        audit_steps = [r.step_id for r in history.audit_records if r.event_type == "step_completed"]
        self.assertIn("step_1", audit_steps)
        self.assertIn("step_2", audit_steps)

    def test_failing_subscriber_isolated_without_interrupting_execution(self) -> None:
        """
        Verify a progress subscriber raising an exception does not interrupt workflow
        execution, does not starve other subscribers, and records the subscriber error.
        """
        healthy_events: List[WorkflowProgressEvent] = []

        def broken_subscriber(event: WorkflowProgressEvent) -> None:
            raise RuntimeError("Simulated UI websocket disconnect")

        plan = WorkflowPlan(
            workflow_id="wf-sub-isolation",
            goal="Verify subscriber exception isolation",
            steps=[
                WorkflowStep(
                    step_id="s1",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student", "record_id": "S101"},
                )
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=self.registry)
        executor.subscribe_progress(broken_subscriber)
        executor.subscribe_progress(healthy_events.append)

        res = executor.run()
        self.assertTrue(res.success)
        self.assertEqual(executor.current_state, WorkflowState.SUCCEEDED)
        self.assertIsNotNone(executor.get_latest_checkpoint())

        # Healthy subscriber still received all events
        healthy_types = [e.event_type for e in healthy_events]
        self.assertIn(ProgressEventType.WORKFLOW_STARTED, healthy_types)
        self.assertIn(ProgressEventType.STEP_COMPLETED, healthy_types)
        self.assertIn(ProgressEventType.WORKFLOW_COMPLETED, healthy_types)

        # Errors safely recorded in subscriber_errors and audit trail
        self.assertGreater(len(executor.audit_manager.subscriber_errors), 0)
        audit_types = [r.event_type for r in executor.get_step_audit_records()]
        self.assertIn("progress_subscriber_error", audit_types)

    def test_cancellation_rejection_and_expiry_progress_events(self) -> None:
        """Verify WORKFLOW_CANCELLED, STEP_FAILED on rejection, and APPROVAL_EXPIRED events."""
        from datetime import datetime, timedelta, timezone

        # 1. Cancellation event
        plan_cancel = WorkflowPlan(
            workflow_id="wf-cancel-evt",
            goal="Verify cancelled progress event",
            steps=[
                WorkflowStep(
                    step_id="s1",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student", "record_id": "S101"},
                )
            ],
        )
        exec_cancel = WorkflowExecutor(plan=plan_cancel, registry=self.registry)
        exec_cancel.cancel("User aborted")
        cancel_events = [e.event_type for e in exec_cancel.get_progress_events()]
        self.assertIn(ProgressEventType.WORKFLOW_CANCELLED, cancel_events)

        # 2. Rejection emits APPROVAL_REJECTED, STEP_FAILED, and WORKFLOW_FAILED
        plan_rej = WorkflowPlan(
            workflow_id="wf-rej-evt",
            goal="Verify rejection progress events",
            steps=[
                WorkflowStep(
                    step_id="s1",
                    tool_name="student_status_update",
                    input_payload={"student_id": "S101", "new_status": "on_leave", "reason": "Test"},
                )
            ],
        )
        exec_rej = WorkflowExecutor(plan=plan_rej, registry=self.registry)
        exec_rej.run()
        exec_rej.submit_approval("s1", approved=False, reason="No")
        exec_rej.run()
        rej_events = [e.event_type for e in exec_rej.get_progress_events()]
        self.assertIn(ProgressEventType.APPROVAL_REJECTED, rej_events)
        self.assertIn(ProgressEventType.STEP_FAILED, rej_events)
        self.assertIn(ProgressEventType.WORKFLOW_FAILED, rej_events)

        # 3. Expiry emits APPROVAL_EXPIRED and WORKFLOW_FAILED
        past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        plan_exp = WorkflowPlan(
            workflow_id="wf-exp-evt",
            goal="Verify expired progress event",
            steps=[
                WorkflowStep(
                    step_id="s1",
                    tool_name="student_status_update",
                    input_payload={"student_id": "S101", "new_status": "on_leave", "reason": "Test"},
                    metadata={"approval_expires_at": past},
                )
            ],
        )
        exec_exp = WorkflowExecutor(plan=plan_exp, registry=self.registry)
        exec_exp.run()
        exp_events = [e.event_type for e in exec_exp.get_progress_events()]
        self.assertIn(ProgressEventType.APPROVAL_EXPIRED, exp_events)
        self.assertIn(ProgressEventType.WORKFLOW_FAILED, exp_events)

    def test_backend_and_direct_approval_rejection_emit_consistent_progress_events(self) -> None:
        """
        Verify approval rejection via backend sync (without submit_approval) emits the
        same APPROVAL_REJECTED -> STEP_FAILED -> WORKFLOW_FAILED events without duplication.
        """
        from agentic_workflow import BackendApprovalState, MockBackendApprovalClient

        backend = MockBackendApprovalClient()
        plan = WorkflowPlan(
            workflow_id="wf-backend-rej-evt",
            goal="Verify backend rejection progress events",
            steps=[
                WorkflowStep(
                    step_id="s1",
                    tool_name="student_status_update",
                    input_payload={"student_id": "S101", "new_status": "on_leave", "reason": "Test"},
                )
            ],
        )
        executor = WorkflowExecutor(
            plan=plan,
            registry=self.registry,
            backend_approval_client=backend,
        )
        executor.run()
        req = executor.get_approval_request("s1")
        assert req is not None

        backend.seed_state(
            BackendApprovalState(
                request_id=req.request_id,
                workflow_id="wf-backend-rej-evt",
                step_id="s1",
                status="REJECTED",
                tool_name="student_status_update",
                decision_reason="Rejected by remote backend",
            )
        )
        res = executor.run()
        self.assertFalse(res.success)
        events = [e.event_type for e in executor.get_progress_events()]
        self.assertEqual(events.count(ProgressEventType.APPROVAL_REJECTED), 1)
        self.assertEqual(events.count(ProgressEventType.STEP_FAILED), 1)
        self.assertEqual(events.count(ProgressEventType.WORKFLOW_FAILED), 1)
        self.assertLess(
            events.index(ProgressEventType.APPROVAL_REJECTED),
            events.index(ProgressEventType.STEP_FAILED),
        )
        self.assertLess(
            events.index(ProgressEventType.STEP_FAILED),
            events.index(ProgressEventType.WORKFLOW_FAILED),
        )


if __name__ == "__main__":
    unittest.main()
