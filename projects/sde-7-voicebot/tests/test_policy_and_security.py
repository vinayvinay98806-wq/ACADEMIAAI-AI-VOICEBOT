"""
Policy and Security Test Suite for W4 Agentic Workflow (Day 14).

Comprehensively verifies and proves the 16 core policy requirements:
1. Valid workflow execution.
2. Missing dependency rejection.
3. Circular dependency rejection.
4. Unknown tool rejection.
5. Invalid tool arguments.
6. Permission-scope violations.
7. Approval granted.
8. Approval rejected.
9. Approval expired.
10. Rejected action never executing (Invocation Counter == 0).
11. Execution timeout.
12. Bounded retry behavior.
13. Non-idempotent operation not being retried.
14. Workflow cancellation.
15. Failure propagation.
16. Execution history and audit records.
"""

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

# Add project root to sys.path for direct or discovered execution
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import unittest
from agentic_workflow.approval_manager import ApprovalManager
from agentic_workflow.executor import WorkflowExecutor
from agentic_workflow.mock_tools import (
    ACADEMIC_LOOKUP_SPEC,
    STUDENT_STATUS_UPDATE_SPEC,
    ToolRegistry,
    academic_lookup_handler,
    create_default_registry,
    student_status_update_handler,
)
from agentic_workflow.schemas import (
    ApprovalRequest,
    ToolSpec,
    WorkflowPlan,
    WorkflowResult,
    WorkflowStep,
)
from agentic_workflow.state_machine import WorkflowState
from agentic_workflow.validator import PlanValidationError, PlanValidator


class TestPolicyAndSecurity(unittest.TestCase):
    """Test suite executing the 16 mandated policy and security proofs."""

    def setUp(self):
        self.registry = create_default_registry()
        self.registry.reset_counts()
        self.validator = PlanValidator(self.registry)

    # -------------------------------------------------------------------------
    # 1. Valid workflow execution
    # -------------------------------------------------------------------------
    def test_01_valid_workflow_execution(self):
        """1. Verify a well-formed, multi-step workflow executes to completion."""
        plan = WorkflowPlan(
            workflow_id="wf-policy-01",
            goal="Lookup student and corresponding course record",
            steps=[
                WorkflowStep(
                    step_id="step_lookup_student",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student", "record_id": "S101"},
                ),
                WorkflowStep(
                    step_id="step_lookup_course",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "course", "record_id": "CS101"},
                    dependencies=["step_lookup_student"],
                ),
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=self.registry, validator=self.validator)
        result = executor.run()

        self.assertTrue(result.success)
        self.assertEqual(executor.current_state, WorkflowState.SUCCEEDED)
        self.assertEqual(plan.state, "succeeded")
        self.assertEqual(plan.get_step("step_lookup_student").status, "completed")
        self.assertEqual(plan.get_step("step_lookup_course").status, "completed")
        self.assertEqual(self.registry.get_invocation_count("academic_lookup"), 2)

    # -------------------------------------------------------------------------
    # 2. Missing dependency rejection
    # -------------------------------------------------------------------------
    def test_02_missing_dependency_rejection(self):
        """2. Verify that a workflow referencing a nonexistent dependency is rejected."""
        plan = WorkflowPlan(
            workflow_id="wf-policy-02",
            goal="Reference nonexistent dependency",
            steps=[
                WorkflowStep(
                    step_id="step_real",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student", "record_id": "S101"},
                    dependencies=["ghost_step_nonexistent"],
                ),
            ],
        )

        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate(plan)
        self.assertIn("unknown dependency 'ghost_step_nonexistent'", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 3. Circular dependency rejection
    # -------------------------------------------------------------------------
    def test_03_circular_dependency_rejection(self):
        """3. Verify circular dependencies (2-step and 3-step DAG cycles) are rejected."""
        # Two-step circular dependency: A -> B -> A
        plan_cycle_2 = WorkflowPlan(
            workflow_id="wf-policy-03a",
            goal="Two-step cycle",
            steps=[
                WorkflowStep(
                    step_id="step_a",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student", "record_id": "S101"},
                    dependencies=["step_b"],
                ),
                WorkflowStep(
                    step_id="step_b",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "course", "record_id": "CS101"},
                    dependencies=["step_a"],
                ),
            ],
        )
        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate(plan_cycle_2)
        self.assertIn("Circular dependency detected", str(ctx.exception))

        # Three-step circular dependency: X -> Y -> Z -> X
        plan_cycle_3 = WorkflowPlan(
            workflow_id="wf-policy-03b",
            goal="Three-step cycle",
            steps=[
                WorkflowStep(
                    step_id="step_x",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student", "record_id": "S101"},
                    dependencies=["step_z"],
                ),
                WorkflowStep(
                    step_id="step_y",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student", "record_id": "S102"},
                    dependencies=["step_x"],
                ),
                WorkflowStep(
                    step_id="step_z",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "course", "record_id": "CS101"},
                    dependencies=["step_y"],
                ),
            ],
        )
        with self.assertRaises(PlanValidationError) as ctx3:
            self.validator.validate(plan_cycle_3)
        self.assertIn("Circular dependency detected", str(ctx3.exception))

    # -------------------------------------------------------------------------
    # 4. Unknown tool rejection
    # -------------------------------------------------------------------------
    def test_04_unknown_tool_rejection(self):
        """4. Verify that attempting to use an unregistered tool is rejected."""
        plan = WorkflowPlan(
            workflow_id="wf-policy-04",
            goal="Execute unregistered shell tool",
            steps=[
                WorkflowStep(
                    step_id="step_unauthorized_tool",
                    tool_name="system_shell_exec",
                    input_payload={"cmd": "ls"},
                )
            ],
        )

        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate(plan)
        self.assertIn("specifies unregistered tool 'system_shell_exec'", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 5. Invalid tool arguments
    # -------------------------------------------------------------------------
    def test_05_invalid_tool_arguments(self):
        """5. Verify that invalid tool parameters violate schema validation."""
        # 5a. Missing required parameter
        plan_missing = WorkflowPlan(
            workflow_id="wf-policy-05a",
            goal="Missing required parameter",
            steps=[
                WorkflowStep(
                    step_id="step_miss",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student"},  # missing record_id
                )
            ],
        )
        with self.assertRaises(PlanValidationError) as ctx1:
            self.validator.validate(plan_missing)
        self.assertIn("missing required parameter 'record_id'", str(ctx1.exception))

        # 5b. Incorrect parameter type
        plan_bad_type = WorkflowPlan(
            workflow_id="wf-policy-05b",
            goal="Invalid parameter type",
            steps=[
                WorkflowStep(
                    step_id="step_bad_type",
                    tool_name="academic_lookup",
                    input_payload={"record_type": ["student"], "record_id": "S101"},
                )
            ],
        )
        with self.assertRaises(PlanValidationError) as ctx2:
            self.validator.validate(plan_bad_type)
        self.assertIn("must be a str", str(ctx2.exception))

        # 5c. Disallowed enum value
        plan_bad_val = WorkflowPlan(
            workflow_id="wf-policy-05c",
            goal="Disallowed enum value",
            steps=[
                WorkflowStep(
                    step_id="step_bad_val",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "professors", "record_id": "P01"},
                )
            ],
        )
        with self.assertRaises(PlanValidationError) as ctx3:
            self.validator.validate(plan_bad_val)
        self.assertIn("not in allowed values", str(ctx3.exception))

    # -------------------------------------------------------------------------
    # 6. Permission-scope violations
    # -------------------------------------------------------------------------
    def test_06_permission_scope_violations(self):
        """6. Verify that an execution context with insufficient scopes is rejected."""
        plan = WorkflowPlan(
            workflow_id="wf-policy-06",
            goal="Attempt status update without write permission",
            steps=[
                WorkflowStep(
                    step_id="step_unauthorized_update",
                    tool_name="student_status_update",
                    input_payload={
                        "student_id": "S101",
                        "new_status": "graduated",
                        "reason": "Credits complete",
                    },
                )
            ],
        )

        # Authorized scope has only academic:read, but student_status_update requires academic:write
        read_only_scopes = {"academic:read"}

        # Static validation rejection
        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate(plan, authorized_permissions=read_only_scopes)
        self.assertIn("Permission-scope violation", str(ctx.exception))
        self.assertIn("academic:write", str(ctx.exception))

        # Direct executor run rejection
        executor = WorkflowExecutor(
            plan=plan,
            registry=self.registry,
            validator=self.validator,
            authorized_permissions=read_only_scopes,
        )
        result = executor.run()
        self.assertFalse(result.success)
        self.assertEqual(executor.current_state, WorkflowState.FAILED)
        self.assertEqual(self.registry.get_invocation_count("student_status_update"), 0)

    # -------------------------------------------------------------------------
    # 7. Approval granted
    # -------------------------------------------------------------------------
    def test_07_approval_granted(self):
        """7. Verify consequential action requests approval and executes upon grant."""
        plan = WorkflowPlan(
            workflow_id="wf-policy-07",
            goal="Consequential update with approval",
            steps=[
                WorkflowStep(
                    step_id="step_grant",
                    tool_name="student_status_update",
                    input_payload={
                        "student_id": "S101",
                        "new_status": "on_leave",
                        "reason": "Approved medical leave",
                    },
                )
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=self.registry)

        # Run 1: Halts at awaiting_approval
        result1 = executor.run()
        self.assertEqual(executor.current_state, WorkflowState.AWAITING_APPROVAL)
        self.assertEqual(self.registry.get_invocation_count("student_status_update"), 0)

        # Grant approval
        executor.submit_approval("step_grant", approved=True, reason="Medical board approval confirmed")

        # Run 2: Resumes and succeeds
        result2 = executor.run()
        self.assertTrue(result2.success)
        self.assertEqual(executor.current_state, WorkflowState.SUCCEEDED)
        self.assertEqual(self.registry.get_invocation_count("student_status_update"), 1)

    # -------------------------------------------------------------------------
    # 8. Approval rejected
    # -------------------------------------------------------------------------
    def test_08_approval_rejected(self):
        """8. Verify consequential action halts when rejected and marks workflow failed."""
        plan = WorkflowPlan(
            workflow_id="wf-policy-08",
            goal="Consequential update with rejection",
            steps=[
                WorkflowStep(
                    step_id="step_reject",
                    tool_name="student_status_update",
                    input_payload={
                        "student_id": "S102",
                        "new_status": "probation",
                        "reason": "Administrative query",
                    },
                )
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=self.registry)

        # Run 1: Reaches awaiting_approval
        executor.run()
        self.assertEqual(executor.current_state, WorkflowState.AWAITING_APPROVAL)

        # Operator rejects
        executor.submit_approval("step_reject", approved=False, reason="Insufficient evidence for probation")

        # Run 2: Terminates in failed state
        result2 = executor.run()
        self.assertFalse(result2.success)
        self.assertEqual(executor.current_state, WorkflowState.FAILED)
        self.assertIn("rejected", result2.error.lower())

    # -------------------------------------------------------------------------
    # 9. Approval expired
    # -------------------------------------------------------------------------
    def test_09_approval_expired(self):
        """9. Verify approval request with expired timestamp is rejected and fails workflow."""
        past_time = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        plan = WorkflowPlan(
            workflow_id="wf-policy-09",
            goal="Consequential update with expired approval TTL",
            steps=[
                WorkflowStep(
                    step_id="step_expiring",
                    tool_name="student_status_update",
                    input_payload={
                        "student_id": "S101",
                        "new_status": "active",
                        "reason": "Re-enrollment",
                    },
                    metadata={"approval_expires_at": past_time},
                )
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=self.registry)
        result = executor.run()

        self.assertFalse(result.success)
        self.assertEqual(executor.current_state, WorkflowState.FAILED)
        self.assertIn("expired", result.error.lower())
        self.assertEqual(self.registry.get_invocation_count("student_status_update"), 0)

    # -------------------------------------------------------------------------
    # 10. Rejected action never executing (Invocation Counter == 0)
    # -------------------------------------------------------------------------
    def test_10_rejected_action_never_executing(self):
        """
        10. CRITICAL SAFETY PROOF:
        Verify that a rejected action strictly maintains a tool invocation counter of ZERO.
        """
        plan = WorkflowPlan(
            workflow_id="wf-policy-10",
            goal="Prove rejected action invocation counter is strictly zero",
            steps=[
                WorkflowStep(
                    step_id="step_dangerous",
                    tool_name="student_status_update",
                    input_payload={
                        "student_id": "S103",
                        "new_status": "probation",
                        "reason": "Hostile takeover",
                    },
                )
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=self.registry)
        executor.run()
        self.assertEqual(executor.current_state, WorkflowState.AWAITING_APPROVAL)
        self.assertEqual(self.registry.get_invocation_count("student_status_update"), 0)

        executor.submit_approval("step_dangerous", approved=False, reason="Disallowed by security policy")
        result = executor.run()

        self.assertFalse(result.success)
        self.assertEqual(executor.current_state, WorkflowState.FAILED)
        # INVOCATION COUNT MUST BE STRICTLY ZERO
        self.assertEqual(
            self.registry.get_invocation_count("student_status_update"),
            0,
            "CRITICAL SECURITY VIOLATION: Tool was invoked despite operator rejection!",
        )

    # -------------------------------------------------------------------------
    # 11. Execution timeout
    # -------------------------------------------------------------------------
    def test_11_execution_timeout(self):
        """11. Verify workflow and step execution timeouts halt execution safely."""
        # 11a. Step-level timeout: test tool execution timeout
        def slow_tool_handler(payload: Dict[str, Any]) -> WorkflowResult:
            time.sleep(0.15)
            return WorkflowResult.ok({"status": "slept"})

        slow_spec = ToolSpec(
            name="slow_tool",
            description="Tool simulating slow remote call",
            parameters_schema={},
            is_idempotent=True,
        )
        test_registry = create_default_registry()
        test_registry.register(slow_spec, slow_tool_handler)

        plan = WorkflowPlan(
            workflow_id="wf-policy-11",
            goal="Test step execution timeout",
            steps=[
                WorkflowStep(
                    step_id="step_slow",
                    tool_name="slow_tool",
                    input_payload={},
                    timeout_seconds=0.03,  # 30ms timeout (handler takes 150ms)
                )
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=test_registry)
        result = executor.run()

        self.assertFalse(result.success)
        self.assertEqual(executor.current_state, WorkflowState.FAILED)
        self.assertIn("timed out", result.error.lower())
        self.assertTrue(result.metadata.get("timeout"))

    # -------------------------------------------------------------------------
    # 12. Bounded retry behavior
    # -------------------------------------------------------------------------
    def test_12_bounded_retry_behavior(self):
        """12. Verify that an idempotent tool retries up to bounded max_retries."""
        flaky_call_count = 0

        def flaky_idempotent_handler(payload: Dict[str, Any]) -> WorkflowResult:
            nonlocal flaky_call_count
            flaky_call_count += 1
            if flaky_call_count < 3:
                return WorkflowResult.fail(f"Simulated transient error attempt {flaky_call_count}")
            return WorkflowResult.ok({"attempt": flaky_call_count, "data": "recovered"})

        flaky_spec = ToolSpec(
            name="flaky_idempotent_tool",
            description="Idempotent tool that recovers on 3rd attempt",
            parameters_schema={},
            is_idempotent=True,
        )
        retry_registry = create_default_registry()
        retry_registry.register(flaky_spec, flaky_idempotent_handler)

        plan = WorkflowPlan(
            workflow_id="wf-policy-12",
            goal="Retry idempotent tool until bounded success",
            steps=[
                WorkflowStep(
                    step_id="step_retryable",
                    tool_name="flaky_idempotent_tool",
                    input_payload={},
                    max_retries=3,  # allows up to 3 retries
                )
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=retry_registry)
        result = executor.run()

        self.assertTrue(result.success)
        self.assertEqual(executor.current_state, WorkflowState.SUCCEEDED)
        self.assertEqual(flaky_call_count, 3)
        self.assertEqual(plan.get_step("step_retryable").retry_count, 2)

    # -------------------------------------------------------------------------
    # 13. Non-idempotent operation not being retried
    # -------------------------------------------------------------------------
    def test_13_non_idempotent_operation_not_being_retried(self):
        """
        13. CRITICAL SAFETY PROOF:
        Verify that a non-idempotent tool is NEVER automatically retried upon failure.
        """
        non_idempotent_invocations = 0

        def failing_mutation_handler(payload: Dict[str, Any]) -> WorkflowResult:
            nonlocal non_idempotent_invocations
            non_idempotent_invocations += 1
            return WorkflowResult.fail("Database lock failure during mutation")

        mutation_spec = ToolSpec(
            name="failing_mutation_tool",
            description="Non-idempotent mutation tool",
            parameters_schema={},
            is_idempotent=False,  # Explicitly NON-IDEMPOTENT
        )
        mut_registry = create_default_registry()
        mut_registry.register(mutation_spec, failing_mutation_handler)

        plan = WorkflowPlan(
            workflow_id="wf-policy-13",
            goal="Ensure non-idempotent operation is never retried",
            steps=[
                WorkflowStep(
                    step_id="step_no_retry",
                    tool_name="failing_mutation_tool",
                    input_payload={},
                    max_retries=5,  # Caller requested retries, but tool is non-idempotent!
                )
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=mut_registry)
        result = executor.run()

        self.assertFalse(result.success)
        self.assertEqual(executor.current_state, WorkflowState.FAILED)
        # STRICT VERIFICATION: Invocations MUST be exactly 1, retries MUST be 0
        self.assertEqual(non_idempotent_invocations, 1)
        self.assertEqual(plan.get_step("step_no_retry").retry_count, 0)

    # -------------------------------------------------------------------------
    # 14. Workflow cancellation
    # -------------------------------------------------------------------------
    def test_14_workflow_cancellation(self):
        """14. Verify cancelling a workflow immediately halts execution and locks state."""
        plan = WorkflowPlan(
            workflow_id="wf-policy-14",
            goal="Cancel workflow before completion",
            steps=[
                WorkflowStep(
                    step_id="step_initial",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student", "record_id": "S101"},
                ),
                WorkflowStep(
                    step_id="step_never_runs",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "course", "record_id": "CS101"},
                    dependencies=["step_initial"],
                ),
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=self.registry)
        # Cancel before run
        cancel_state = executor.cancel(reason="Emergency user abort")

        self.assertEqual(cancel_state, WorkflowState.CANCELLED)
        self.assertEqual(executor.current_state, WorkflowState.CANCELLED)

        # Attempt to run cancelled workflow
        result = executor.run()
        self.assertFalse(result.success)
        self.assertEqual(self.registry.get_invocation_count("academic_lookup"), 0)
        self.assertEqual(plan.get_step("step_never_runs").status, "cancelled")

    # -------------------------------------------------------------------------
    # 15. Failure propagation
    # -------------------------------------------------------------------------
    def test_15_failure_propagation(self):
        """15. Verify that failure of a prerequisite step prevents execution of dependent steps."""
        plan = WorkflowPlan(
            workflow_id="wf-policy-15",
            goal="Verify dependent step is never invoked when prerequisite fails",
            steps=[
                WorkflowStep(
                    step_id="step_fail_prereq",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student", "record_id": "NONEXISTENT_999"},
                ),
                WorkflowStep(
                    step_id="step_dependent",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "course", "record_id": "CS101"},
                    dependencies=["step_fail_prereq"],
                ),
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=self.registry)
        result = executor.run()

        self.assertFalse(result.success)
        self.assertEqual(executor.current_state, WorkflowState.FAILED)
        self.assertEqual(plan.get_step("step_fail_prereq").status, "failed")
        # Dependent step must remain unexecuted (pending)
        self.assertEqual(plan.get_step("step_dependent").status, "pending")
        # Academic lookup only called once for the first step
        self.assertEqual(self.registry.get_invocation_count("academic_lookup"), 1)

    # -------------------------------------------------------------------------
    # 16. Execution history and audit records
    # -------------------------------------------------------------------------
    def test_16_execution_history_and_audit_records(self):
        """16. Verify that state transitions, approvals, and steps are faithfully logged."""
        plan = WorkflowPlan(
            workflow_id="wf-policy-16",
            goal="Comprehensive audit log verification",
            steps=[
                WorkflowStep(
                    step_id="step_audit_lookup",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student", "record_id": "S101"},
                ),
                WorkflowStep(
                    step_id="step_audit_update",
                    tool_name="student_status_update",
                    input_payload={
                        "student_id": "S101",
                        "new_status": "active",
                        "reason": "Annual confirmation",
                    },
                    dependencies=["step_audit_lookup"],
                ),
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=self.registry)

        # Run 1: Halts at awaiting approval
        executor.run()
        executor.submit_approval("step_audit_update", approved=True, reason="Audited by registrar")
        # Run 2: Succeeded
        executor.run()

        # Check State Machine History
        history = executor.state_machine.history
        self.assertGreaterEqual(len(history), 3)
        states = [(r.from_state.value, r.to_state.value) for r in history]
        self.assertIn(("draft", "running"), states)
        self.assertIn(("running", "awaiting_approval"), states)
        self.assertIn(("awaiting_approval", "running"), states)
        self.assertIn(("running", "succeeded"), states)

        # Check Approval Audit Log
        approval_entries = executor.approval_manager.audit_log
        self.assertEqual(len(approval_entries), 2)  # REQUESTED and APPROVED
        self.assertEqual(approval_entries[0].decision, "REQUESTED")
        self.assertEqual(approval_entries[1].decision, "APPROVED")
        self.assertEqual(approval_entries[1].reason, "Audited by registrar")

        # Check Executor Audit Log
        executor_events = [e["event"] for e in executor.audit_log]
        self.assertIn("workflow_started", executor_events)
        self.assertIn("approval_requested", executor_events)
        self.assertIn("approval_submitted", executor_events)
        self.assertIn("workflow_succeeded", executor_events)

    # -------------------------------------------------------------------------
    # BONUS: Output Propagation
    # -------------------------------------------------------------------------
    def test_output_propagation_between_steps(self):
        """Verify dynamic step output propagation (resolving $step_id.key)."""
        plan = WorkflowPlan(
            workflow_id="wf-policy-output-prop",
            goal="Propagate student course ID into next step",
            steps=[
                WorkflowStep(
                    step_id="step_get_student",
                    tool_name="academic_lookup",
                    input_payload={"record_type": "student", "record_id": "S101"},
                ),
                WorkflowStep(
                    step_id="step_get_course",
                    tool_name="academic_lookup",
                    # Uses dynamic reference: S101 enrolled_courses is ["CS101", "AI202"]
                    input_payload={"record_type": "course", "record_id": "$step_get_student.enrolled_courses[0]"},
                    dependencies=["step_get_student"],
                ),
            ],
        )

        executor = WorkflowExecutor(plan=plan, registry=self.registry)
        result = executor.run()

        self.assertTrue(result.success)
        self.assertEqual(executor.current_state, WorkflowState.SUCCEEDED)

        # Check resolved payload
        step2 = plan.get_step("step_get_course")
        self.assertEqual(step2.input_payload["record_id"], "CS101")
        self.assertEqual(step2.result.output["course_id"], "CS101")


if __name__ == "__main__":
    unittest.main()

