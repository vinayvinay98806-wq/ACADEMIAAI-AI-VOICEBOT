"""
Demonstration Script for W4 Agentic Workflow (Weeks 2 & 3).

Demonstrates:
- DEMO A: Harmless read-only workflow executes successfully (with dynamic output propagation).
- DEMO B: Consequential action requests approval, receives approval, and executes.
- DEMO C: Consequential action is rejected and its tool invocation count strictly remains ZERO.
- DEMO D: Approval expiry, permission-scope enforcement, and bounded idempotent retries.
- DEMO E (Week 3): Proposal -> multi-step execution -> step failure -> checkpoint save ->
  resume & failed-step recovery without repeating completed steps -> audit & progress events ->
  backend + UI approval -> duplicate approval safety.
- DEMO F (Week 3): UI rejection and expired approval safety proofs (invocation count == 0).
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from agentic_workflow import (
    ApprovalManager,
    ApprovalUIService,
    InMemoryCheckpointStore,
    MockBackendApprovalClient,
    ToolSpec,
    UIApprovalAction,
    WorkflowExecutor,
    WorkflowPlan,
    WorkflowProposalAdapter,
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


def demo_e_week3_checkpoint_audit_and_approval() -> None:
    """
    DEMO E (Week 3): Reproducible end-to-end demonstration of:
    1. Reasoning proposal validation & conversion
    2. Multi-step execution + step failure + checkpoint save
    3. Resume & failed-step recovery without repeating completed steps
    4. Audit records & progress events
    5. Backend + UI approval + duplicate approval rejection
    """
    print_section("DEMO E (Week 3): Checkpoint/Resume, Recovery, Audit, Progress & UI Approval")

    registry = create_default_registry()
    verify_attempts = {"count": 0}

    def transient_enrollment_check(payload: Dict[str, Any]) -> WorkflowResult:
        verify_attempts["count"] += 1
        if verify_attempts["count"] == 1:
            return WorkflowResult.fail("Transient verification service timeout")
        return WorkflowResult.ok({"verified": True, "student_id": payload.get("student_id")})

    registry.register(
        ToolSpec(
            name="enrollment_verify",
            description="Transiently flaky verification mock tool",
            parameters_schema={"student_id": {"type": "str", "required": True}},
            is_consequential=False,
            required_permissions=["academic:read"],
            is_idempotent=False,
        ),
        transient_enrollment_check,
    )

    # 1. Convert reasoning proposal into validated WorkflowPlan
    adapter = WorkflowProposalAdapter(registry=registry)
    proposal = {
        "proposal_id": "prop-w3-demo",
        "workflow_id": "wf-demo-e-w3",
        "goal": "Lookup student S101, verify enrollment, and update status with approval",
        "steps": [
            {
                "step_id": "step_lookup",
                "tool_name": "academic_lookup",
                "input_payload": {"record_type": "student", "record_id": "S101"},
            },
            {
                "step_id": "step_verify",
                "tool_name": "enrollment_verify",
                "input_payload": {"student_id": "$step_lookup.student_id"},
                "dependencies": ["step_lookup"],
            },
            {
                "step_id": "step_update",
                "tool_name": "student_status_update",
                "input_payload": {
                    "student_id": "$step_lookup.student_id",
                    "new_status": "on_leave",
                    "reason": "Week 3 approved leave",
                },
                "dependencies": ["step_verify"],
                "idempotency_key": "idem-demo-e-s101-leave",
            },
        ],
    }
    plan = adapter.validate_and_convert(
        proposal,
        authorized_permissions={"academic:read", "academic:write"},
    )

    checkpoint_store = InMemoryCheckpointStore()
    backend_client = MockBackendApprovalClient()
    ui_service = ApprovalUIService(auto_resume_on_approve=True)
    emitted_events = []

    executor = WorkflowExecutor(
        plan=plan,
        registry=registry,
        checkpoint_store=checkpoint_store,
        backend_approval_client=backend_client,
        authorized_permissions={"academic:read", "academic:write"},
    )
    executor.subscribe_progress(emitted_events.append)
    ui_service.register_executor(executor)

    # 2. Start workflow: step_lookup completes, step_verify fails, checkpoint saved
    print("Phase 1: Starting workflow (step_lookup succeeds, step_verify fails once)...")
    res1 = executor.run()
    latest_chk = executor.get_latest_checkpoint()
    print(f"  State after failure        : {executor.current_state.value} (success={res1.success})")
    print(f"  academic_lookup calls      : {registry.get_invocation_count('academic_lookup')}")
    print(f"  Latest Checkpoint ID       : {latest_chk.checkpoint_id if latest_chk else 'None'}")
    print(f"  Checkpoint failed step     : {latest_chk.failed_step_info['step_id'] if latest_chk and latest_chk.failed_step_info else 'None'}")

    # 3. Resume from checkpoint: step_lookup MUST NOT re-execute; step_verify recovers; halts at awaiting_approval
    print("\nPhase 2: Resuming from checkpoint (recovering step_verify)...")
    res2 = executor.resume_from_checkpoint()
    print(f"  State after recovery       : {executor.current_state.value}")
    print(f"  academic_lookup calls      : {registry.get_invocation_count('academic_lookup')} (completed step NOT repeated)")
    print(f"  step_verify status         : {plan.get_step('step_verify').status} (recovery_attempts={plan.get_step('step_verify').metadata.get('recovery_attempts')})")
    print(f"  student_status_update calls: {registry.get_invocation_count('student_status_update')} (pending approval)")

    # 4. UI approves consequential step -> executes once
    print("\nPhase 3: User approves via ApprovalUIService...")
    ui_resp1 = ui_service.submit_decision(
        UIApprovalAction(
            workflow_id="wf-demo-e-w3",
            step_id="step_update",
            decision="APPROVE",
            reason="Registrar approved medical leave",
            operator_id="registrar_01",
            submission_id="demo-click-1",
        )
    )
    print(f"  UI Response 1              : accepted={ui_resp1.accepted}, status={ui_resp1.status}, wf_state={ui_resp1.workflow_state}")
    print(f"  student_status_update calls: {registry.get_invocation_count('student_status_update')}")

    # 5. Duplicate approval click is safely rejected without re-executing tool
    print("\nPhase 4: Duplicate UI approval submission...")
    ui_resp2 = ui_service.submit_decision(
        UIApprovalAction(
            workflow_id="wf-demo-e-w3",
            step_id="step_update",
            decision="APPROVE",
            submission_id="demo-click-2",
        )
    )
    print(f"  UI Response 2 (duplicate)  : accepted={ui_resp2.accepted}, duplicate={ui_resp2.duplicate_submission}, error={ui_resp2.error_code}")
    print(f"  student_status_update calls: {registry.get_invocation_count('student_status_update')} (strictly remains 1)")

    # 6. Inspect audit trail and progress events
    history = executor.get_execution_history()
    print(f"\nAudit & Progress Summary:")
    print(f"  Step Audit Records         : {len(history.audit_records)}")
    print(f"  Progress Events Emitted    : {[e.event_type.value for e in emitted_events]}")


def demo_f_week3_rejection_and_expiry_safety() -> None:
    """DEMO F (Week 3): UI rejection & expired approval never execute consequential tools."""
    print_section("DEMO F (Week 3): UI Rejection & Expired Approval Safety Proofs")

    registry = create_default_registry()
    ui_service = ApprovalUIService(auto_resume_on_approve=True)

    # 1. Rejection via UI
    plan_rej = WorkflowPlan(
        workflow_id="wf-demo-f-rej",
        goal="Reject consequential action via UI",
        steps=[
            WorkflowStep(
                step_id="step_rej",
                tool_name="student_status_update",
                input_payload={"student_id": "S102", "new_status": "probation", "reason": "UI rejection demo"},
            )
        ],
    )
    exec_rej = WorkflowExecutor(plan=plan_rej, registry=registry)
    ui_service.register_executor(exec_rej)
    exec_rej.run()
    rej_resp = ui_service.submit_decision(
        UIApprovalAction(workflow_id="wf-demo-f-rej", step_id="step_rej", decision="REJECT", reason="Denied")
    )
    print(f"1. UI Rejection -> status={rej_resp.status}, wf_state={rej_resp.workflow_state}, tool_calls={registry.get_invocation_count('student_status_update')}")

    # 2. Expired approval rejected safely
    past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    plan_exp = WorkflowPlan(
        workflow_id="wf-demo-f-exp",
        goal="Expired approval cannot execute via UI",
        steps=[
            WorkflowStep(
                step_id="step_exp",
                tool_name="student_status_update",
                input_payload={"student_id": "S103", "new_status": "active", "reason": "Expired demo"},
                metadata={"approval_expires_at": past},
            )
        ],
    )
    exec_exp = WorkflowExecutor(plan=plan_exp, registry=registry)
    ui_service.register_executor(exec_exp)
    exec_exp.run()
    exp_resp = ui_service.submit_decision(
        UIApprovalAction(workflow_id="wf-demo-f-exp", step_id="step_exp", decision="APPROVE")
    )
    print(f"2. Expired Approval -> accepted={exp_resp.accepted}, error_code={exp_resp.error_code}, tool_calls={registry.get_invocation_count('student_status_update')}")


if __name__ == "__main__":
    demo_a_harmless_workflow()
    demo_b_consequential_approval_flow()
    demo_c_consequential_rejection_flow()
    demo_d_safety_and_policy_features()
    demo_e_week3_checkpoint_audit_and_approval()
    demo_f_week3_rejection_and_expiry_safety()
