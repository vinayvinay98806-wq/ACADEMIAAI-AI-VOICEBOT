"""
Demonstration Script for W4 Agentic Workflow (Week 1).

Demonstrates:
1. Purely harmless workflow execution (academic_lookup).
2. Consequential action approval gating (halting at awaiting_approval, followed by approval and success).
3. Consequential action rejection protection (rejection terminates workflow and guarantees tool is NEVER invoked).
"""

import json
from agentic_workflow import (
    WorkflowExecutor,
    WorkflowPlan,
    WorkflowStep,
    create_default_registry,
)


def print_section(title: str) -> None:
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)


def demo_harmless_workflow() -> None:
    print_section("DEMO 1: Harmless Read-Only Workflow Execution")
    registry = create_default_registry()

    plan = WorkflowPlan(
        workflow_id="wf-demo-01",
        goal="Lookup student record and corresponding course catalog information",
        steps=[
            WorkflowStep(
                step_id="step_student",
                tool_name="academic_lookup",
                input_payload={"record_type": "student", "record_id": "S101"},
            ),
            WorkflowStep(
                step_id="step_course",
                tool_name="academic_lookup",
                input_payload={"record_type": "course", "record_id": "CS101"},
                dependencies=["step_student"],
            ),
        ],
    )

    print(f"Initial State : {plan.state}")
    executor = WorkflowExecutor(plan=plan, registry=registry)
    result = executor.run()

    print(f"Final State   : {executor.current_state.value}")
    print(f"Success       : {result.success}")
    print("Execution History:")
    for record in executor.state_machine.history:
        print(f"  {record.from_state.value} -> {record.to_state.value} ({record.reason})")

    print("\nStep Outputs:")
    for step in plan.steps:
        print(f"  [{step.step_id}] -> {step.status}: {json.dumps(step.result.output)}")


def demo_consequential_approval_flow() -> None:
    print_section("DEMO 2: Consequential Action Gating (Approval Flow)")
    registry = create_default_registry()

    plan = WorkflowPlan(
        workflow_id="wf-demo-02",
        goal="Change student enrollment status to 'on_leave' upon verified request",
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
                    "reason": "Approved family leave",
                },
                dependencies=["step_lookup"],
            ),
        ],
    )

    executor = WorkflowExecutor(plan=plan, registry=registry)

    # 1. First execution run (will pause at consequential step)
    print("Starting execution...")
    result_phase1 = executor.run()
    print(f"Current State after Phase 1 : {executor.current_state.value}")
    print(f"Student status update tool invocation count : {registry.get_invocation_count('student_status_update')}")

    app_req = executor.get_approval_request("step_update")
    print("\nGenerated Approval Request:")
    print(f"  Request ID : {app_req.request_id}")
    print(f"  Tool Name  : {app_req.tool_name}")
    print(f"  Description: {app_req.action_description}")
    print(f"  Status     : {app_req.status}")

    # 2. Operator reviews and grants explicit approval
    print("\nOperator Action: Granting explicit approval...")
    executor.submit_approval("step_update", approved=True, reason="Medical paperwork verified by registrar.")
    print(f"Approval Request status updated to: {app_req.status}")

    # 3. Resuming execution
    print("\nResuming execution...")
    result_phase2 = executor.run()
    print(f"Current State after Phase 2 : {executor.current_state.value}")
    print(f"Student status update tool invocation count : {registry.get_invocation_count('student_status_update')}")
    print(f"Updated Step Output: {json.dumps(plan.get_step('step_update').result.output)}")


def demo_consequential_rejection_flow() -> None:
    print_section("DEMO 3: Consequential Action Gating (Rejection Flow)")
    registry = create_default_registry()

    plan = WorkflowPlan(
        workflow_id="wf-demo-03",
        goal="Attempt unauthorized academic probation placement",
        steps=[
            WorkflowStep(
                step_id="step_probation",
                tool_name="student_status_update",
                input_payload={
                    "student_id": "S103",
                    "new_status": "probation",
                    "reason": "Unsubstantiated rumor",
                },
            ),
        ],
    )

    executor = WorkflowExecutor(plan=plan, registry=registry)

    # 1. Run until awaiting approval
    executor.run()
    print(f"Current State : {executor.current_state.value}")
    print(f"Tool invocation count before decision : {registry.get_invocation_count('student_status_update')}")

    # 2. Operator reviews and rejects action
    print("\nOperator Action: REJECTING approval request...")
    executor.submit_approval("step_probation", approved=False, reason="Insufficient evidence for probation.")

    # 3. Resume run
    result = executor.run()
    print(f"Current State after Rejection : {executor.current_state.value}")
    print(f"Workflow Succeeded?           : {result.success}")
    print(f"Error Message                 : {result.error}")
    print(f"SAFETY GUARANTEE: Tool invocation count strictly remains : {registry.get_invocation_count('student_status_update')}")


if __name__ == "__main__":
    demo_harmless_workflow()
    demo_consequential_approval_flow()
    demo_consequential_rejection_flow()
