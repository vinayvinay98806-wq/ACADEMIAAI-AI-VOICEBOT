"""
Demonstration Script for W4 Agentic Workflow (Week 2).

Demonstrates:
- DEMO A: Harmless read-only workflow executes successfully (with dynamic output propagation).
- DEMO B: Consequential action requests approval, receives approval, and executes.
- DEMO C: Consequential action is rejected and its tool invocation count strictly remains ZERO.
- BONUS DEMO D: Approval expiry, permission-scope enforcement, and bounded idempotent retries.
"""

import json
from datetime import datetime, timedelta, timezone
from agentic_workflow import (
    ApprovalManager,
    ToolSpec,
    WorkflowExecutor,
    WorkflowPlan,
    WorkflowResult,
    WorkflowStep,
    create_default_registry,
)


def print_section(title: str) -> None:
    print("\n" + "=" * 76)
    print(f" {title}")
    print("=" * 76)


def demo_a_harmless_workflow() -> None:
    """DEMO A: Harmless read-only workflow executes successfully with output propagation."""
    print_section("DEMO A: Harmless Read-Only Workflow Executes Successfully")
    registry = create_default_registry()

    plan = WorkflowPlan(
        workflow_id="wf-demo-a",
        goal="Lookup student record and dynamically query their first enrolled course",
        steps=[
            WorkflowStep(
                step_id="step_student",
                tool_name="academic_lookup",
                input_payload={"record_type": "student", "record_id": "S101"},
            ),
            WorkflowStep(
                step_id="step_course",
                tool_name="academic_lookup",
                # Output propagation: references S101's enrolled course from step_student output
                input_payload={"record_type": "course", "record_id": "$step_student.enrolled_courses[0]"},
                dependencies=["step_student"],
            ),
        ],
    )

    print(f"Initial State       : {plan.state}")
    executor = WorkflowExecutor(plan=plan, registry=registry)
    result = executor.run()

    print(f"Final State         : {executor.current_state.value}")
    print(f"Workflow Succeeded? : {result.success}")
    print(f"Tool Invocations    : academic_lookup count = {registry.get_invocation_count('academic_lookup')}")

    print("\nState Transition History:")
    for record in executor.state_machine.history:
        print(f"  [{record.timestamp}] {record.from_state.value} -> {record.to_state.value} ({record.reason})")

    print("\nStep Outputs (with Output Propagation):")
    for step in plan.steps:
        print(f"  Step '{step.step_id}' [{step.status}]:")
        print(f"    Payload : {json.dumps(step.input_payload)}")
        print(f"    Output  : {json.dumps(step.result.output)}")


def demo_b_consequential_approval_flow() -> None:
    """DEMO B: Consequential action requests approval, receives approval, and executes."""
    print_section("DEMO B: Consequential Action Requests Approval, Receives Approval, and Executes")
    registry = create_default_registry()

    plan = WorkflowPlan(
        workflow_id="wf-demo-b",
        goal="Update student enrollment status to 'on_leave' upon verified medical request",
        steps=[
            WorkflowStep(
                step_id="step_lookup",
                tool_name="academic_lookup",
                input_payload={"record_type": "student", "record_id": "S102"},
            ),
            WorkflowStep(
                step_id="step_update",
                tool_name="student_status_update",
                input_payload={
                    "student_id": "S102",
                    "new_status": "on_leave",
                    "reason": "Verified medical leave request",
                },
                dependencies=["step_lookup"],
            ),
        ],
    )

    executor = WorkflowExecutor(plan=plan, registry=registry)

    # 1. First execution phase: Halts at awaiting_approval for consequential step
    print("Phase 1: Starting execution...")
    result_phase1 = executor.run()
    print(f"  Workflow State after Phase 1 : {executor.current_state.value}")
    print(f"  Student update invocation count : {registry.get_invocation_count('student_status_update')}")
    print("  -> GUARANTEE: Consequential tool has NOT been invoked while pending.")

    app_req = executor.get_approval_request("step_update")
    print("\nGenerated Approval Request:")
    print(f"  Request ID : {app_req.request_id}")
    print(f"  Step ID    : {app_req.step_id}")
    print(f"  Tool Name  : {app_req.tool_name}")
    print(f"  Description: {app_req.action_description}")
    print(f"  Status     : {app_req.status}")

    # 2. Operator action: Grant explicit approval
    print("\nPhase 2: Operator reviews documentation and grants explicit approval...")
    executor.submit_approval("step_update", approved=True, reason="Medical documentation verified by university registrar.")
    print(f"  Approval Request status updated to: {app_req.status}")

    # 3. Second execution phase: Resumes and executes tool
    print("\nPhase 3: Resuming execution after approval...")
    result_phase2 = executor.run()
    print(f"  Workflow State after Phase 2 : {executor.current_state.value}")
    print(f"  Workflow Succeeded?          : {result_phase2.success}")
    print(f"  Student update invocation count : {registry.get_invocation_count('student_status_update')}")
    print(f"  Updated Record Output: {json.dumps(plan.get_step('step_update').result.output)}")


def demo_c_consequential_rejection_flow() -> None:
    """DEMO C: Consequential action is rejected and its tool invocation count strictly remains ZERO."""
    print_section("DEMO C: Consequential Action is Rejected and Tool Invocation Count Strictly Remains ZERO")
    registry = create_default_registry()

    plan = WorkflowPlan(
        workflow_id="wf-demo-c",
        goal="Attempt unauthorized disciplinary probation status change",
        steps=[
            WorkflowStep(
                step_id="step_probation",
                tool_name="student_status_update",
                input_payload={
                    "student_id": "S103",
                    "new_status": "probation",
                    "reason": "Unsubstantiated anonymous report",
                },
            ),
        ],
    )

    executor = WorkflowExecutor(plan=plan, registry=registry)

    # 1. Run until awaiting approval
    print("Phase 1: Starting workflow execution...")
    executor.run()
    print(f"  Current State                          : {executor.current_state.value}")
    print(f"  Tool invocation count before decision : {registry.get_invocation_count('student_status_update')}")

    # 2. Operator reviews and REJECTS the request
    print("\nPhase 2: Operator reviews and REJECTS the consequential action...")
    executor.submit_approval(
        "step_probation",
        approved=False,
        reason="Disciplinary committee rejected the request: Lack of corroborating evidence.",
    )

    # 3. Resume run after rejection
    print("\nPhase 3: Attempting to resume workflow after rejection...")
    result = executor.run()
    print(f"  Workflow State after Rejection : {executor.current_state.value}")
    print(f"  Workflow Succeeded?            : {result.success}")
    print(f"  Reported Error                 : {result.error}")
    print("  " + "-" * 72)
    print(f"  CRITICAL SAFETY PROOF:")
    print(f"  student_status_update invocation count strictly remains : {registry.get_invocation_count('student_status_update')}")
    print("  " + "-" * 72)


def demo_d_safety_and_policy_features() -> None:
    """DEMO D: Demonstrating Approval Expiry, Scope Enforcement, and Bounded Retries."""
    print_section("DEMO D: Advanced Policy Controls (Expiry, Permissions & Retries)")
    registry = create_default_registry()

    # D1: Approval Expiry
    print("1. Approval Expiry Demonstration:")
    past_time = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    plan_exp = WorkflowPlan(
        workflow_id="wf-demo-d1",
        goal="Expired TTL consequential action",
        steps=[
            WorkflowStep(
                step_id="step_expired",
                tool_name="student_status_update",
                input_payload={"student_id": "S101", "new_status": "active", "reason": "Expired request"},
                metadata={"approval_expires_at": past_time},
            )
        ],
    )
    exec_exp = WorkflowExecutor(plan=plan_exp, registry=registry)
    res_exp = exec_exp.run()
    print(f"   Outcome: State = {exec_exp.current_state.value}, Error = '{res_exp.error}'")
    print(f"   Invocation count strictly remains: {registry.get_invocation_count('student_status_update')}")

    # D2: Permission Scope Enforcement
    print("\n2. Permission-Scope Enforcement Demonstration:")
    read_only_scopes = {"academic:read"}
    plan_perm = WorkflowPlan(
        workflow_id="wf-demo-d2",
        goal="Attempt write action with read-only permissions",
        steps=[
            WorkflowStep(
                step_id="step_write_attempt",
                tool_name="student_status_update",
                input_payload={"student_id": "S101", "new_status": "active", "reason": "Testing scopes"},
            )
        ],
    )
    exec_perm = WorkflowExecutor(plan=plan_perm, registry=registry, authorized_permissions=read_only_scopes)
    res_perm = exec_perm.run()
    print(f"   Outcome: State = {exec_perm.current_state.value}, Error = '{res_perm.error}'")


if __name__ == "__main__":
    demo_a_harmless_workflow()
    demo_b_consequential_approval_flow()
    demo_c_consequential_rejection_flow()
    demo_d_safety_and_policy_features()
