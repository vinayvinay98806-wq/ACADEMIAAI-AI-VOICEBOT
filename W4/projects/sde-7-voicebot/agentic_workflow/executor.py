"""
Workflow Executor for W4 Agentic Workflow.

Coordinates workflow execution, enforcing:
- Strict state machine lifecycle transitions (draft -> running/awaiting_approval -> succeeded/failed/cancelled)
- Gated approval enforcement for consequential actions (defaults to awaiting_approval)
- Absolute guarantee that pending or rejected consequential actions NEVER invoke the underlying tool
- Harmless, deterministic mock tool execution via allow-listed ToolRegistry
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from .schemas import ApprovalRequest, WorkflowPlan, WorkflowResult, WorkflowStep
from .state_machine import WorkflowState, WorkflowStateMachine
from .mock_tools import ToolRegistry, create_default_registry
from .validator import PlanValidator


class WorkflowExecutor:
    """
    Executes a WorkflowPlan using registered tools and manages state transitions
    and human-in-the-loop approval gating.
    """

    def __init__(
        self,
        plan: WorkflowPlan,
        registry: Optional[ToolRegistry] = None,
        validator: Optional[PlanValidator] = None,
    ) -> None:
        self.plan = plan
        self.registry = registry if registry is not None else create_default_registry()
        self.validator = validator if validator is not None else PlanValidator(self.registry)

        # Initialize State Machine matching plan.state (defaults to DRAFT)
        initial_state = WorkflowState(plan.state) if plan.state in [s.value for s in WorkflowState] else WorkflowState.DRAFT
        self.state_machine = WorkflowStateMachine(initial_state)
        self.approval_requests: Dict[str, ApprovalRequest] = {}

    @property
    def current_state(self) -> WorkflowState:
        """Returns the current state of the workflow execution."""
        return self.state_machine.current_state

    def get_approval_request(self, step_id: str) -> Optional[ApprovalRequest]:
        """Retrieve approval request for a given step ID."""
        return self.approval_requests.get(step_id)

    def submit_approval(self, step_id: str, approved: bool, reason: Optional[str] = None) -> ApprovalRequest:
        """
        Submit approval decision for a step.
        If approved=True, marks request as APPROVED.
        If approved=False, marks request as REJECTED.
        """
        request = self.approval_requests.get(step_id)
        if request is None:
            raise KeyError(f"No pending approval request found for step '{step_id}'.")

        if approved:
            request.approve(reason=reason or "Explicit approval granted by operator.")
        else:
            request.reject(reason=reason or "Explicit rejection by operator.")

        return request

    def pause(self, reason: Optional[str] = None) -> WorkflowState:
        """Pause the workflow execution."""
        new_state = self.state_machine.transition_to(WorkflowState.PAUSED, reason=reason)
        self.plan.state = new_state.value
        return new_state

    def resume(self) -> WorkflowResult:
        """Resume execution from paused state."""
        if self.state_machine.current_state != WorkflowState.PAUSED:
            raise ValueError(f"Cannot resume from state '{self.state_machine.current_state.value}'. Must be paused.")

        # Check if we were paused while waiting for approval
        has_pending_approval = any(req.is_pending() for req in self.approval_requests.values())
        if has_pending_approval:
            self.state_machine.transition_to(WorkflowState.AWAITING_APPROVAL, reason="Resumed to awaiting approval")
        else:
            self.state_machine.transition_to(WorkflowState.RUNNING, reason="Resumed workflow execution")

        self.plan.state = self.state_machine.current_state.value
        return self.run()

    def cancel(self, reason: Optional[str] = None) -> WorkflowState:
        """Cancel workflow execution."""
        new_state = self.state_machine.transition_to(WorkflowState.CANCELLED, reason=reason)
        self.plan.state = new_state.value
        return new_state

    def run(self) -> WorkflowResult:
        """
        Execute the workflow plan according to dependency ordering and approval gating.
        Returns WorkflowResult summarizing completion, pause at awaiting_approval, or failure.
        """
        # Validate plan structure and DAG consistency
        try:
            self.validator.validate(self.plan)
        except Exception as val_err:
            if self.state_machine.current_state != WorkflowState.FAILED:
                # Transition to FAILED if not already
                if self.state_machine.can_transition_to(WorkflowState.RUNNING):
                    self.state_machine.transition_to(WorkflowState.RUNNING, reason="Starting plan validation")
                self.state_machine.transition_to(WorkflowState.FAILED, reason=f"Validation failed: {str(val_err)}")
                self.plan.state = WorkflowState.FAILED.value
            return WorkflowResult.fail(f"Plan validation failed: {str(val_err)}")

        # Transition from DRAFT to RUNNING if starting fresh
        if self.state_machine.current_state == WorkflowState.DRAFT:
            self.state_machine.transition_to(WorkflowState.RUNNING, reason="Starting workflow execution")
            self.plan.state = WorkflowState.RUNNING.value

        # Execution loop over steps
        for step in self.plan.steps:
            # If step already completed, skip
            if step.status == "completed":
                continue

            # Check prerequisite dependencies
            for dep_id in step.dependencies:
                dep_step = self.plan.get_step(dep_id)
                if dep_step is None or dep_step.status != "completed":
                    step.status = "failed"
                    step.result = WorkflowResult.fail(f"Prerequisite step '{dep_id}' is not completed.")
                    self.state_machine.transition_to(WorkflowState.FAILED, reason=f"Dependency '{dep_id}' incomplete")
                    self.plan.state = WorkflowState.FAILED.value
                    return step.result

            # Determine whether this action is consequential
            is_consequential = self._is_step_consequential(step)

            # Enforce Approval Policy for consequential actions
            if is_consequential:
                req = self.approval_requests.get(step.step_id)

                if req is None or req.is_pending():
                    # Create approval request if not already present
                    if req is None:
                        req = ApprovalRequest(
                            request_id=f"apr-{self.plan.workflow_id}-{step.step_id}",
                            workflow_id=self.plan.workflow_id,
                            step_id=step.step_id,
                            tool_name=step.tool_name,
                            action_description=(
                                f"Consequential action '{step.tool_name}' requires explicit operator approval."
                            ),
                            status="PENDING",
                        )
                        self.approval_requests[step.step_id] = req

                    # Transition state machine to awaiting_approval
                    if self.state_machine.current_state != WorkflowState.AWAITING_APPROVAL:
                        self.state_machine.transition_to(
                            WorkflowState.AWAITING_APPROVAL,
                            reason=f"Step '{step.step_id}' is consequential and requires approval.",
                        )
                        self.plan.state = WorkflowState.AWAITING_APPROVAL.value

                    step.status = "awaiting_approval"
                    # CRITICAL SAFETY GUARANTEE: Never invoke the tool while pending approval!
                    return WorkflowResult.ok(
                        output={"approval_request": req.to_dict()},
                        metadata={
                            "state": WorkflowState.AWAITING_APPROVAL.value,
                            "pending_step": step.step_id,
                            "consequential": True,
                        },
                    )

                elif req.is_rejected():
                    # CRITICAL SAFETY GUARANTEE: Rejection strictly prevents execution of the tool!
                    step.status = "failed"
                    step.result = WorkflowResult.fail(
                        error=f"Execution rejected by operator: {req.decision_reason or 'No reason provided'}",
                        metadata={"step_id": step.step_id, "rejection": True},
                    )
                    if self.state_machine.current_state == WorkflowState.AWAITING_APPROVAL:
                        self.state_machine.transition_to(
                            WorkflowState.FAILED,
                            reason=f"Step '{step.step_id}' was rejected: {req.decision_reason}",
                        )
                    elif self.state_machine.can_transition_to(WorkflowState.FAILED):
                        self.state_machine.transition_to(
                            WorkflowState.FAILED,
                            reason=f"Step '{step.step_id}' was rejected: {req.decision_reason}",
                        )
                    self.plan.state = WorkflowState.FAILED.value
                    return step.result

                elif req.is_approved():
                    # Transition from awaiting_approval to running if needed
                    if self.state_machine.current_state == WorkflowState.AWAITING_APPROVAL:
                        self.state_machine.transition_to(
                            WorkflowState.RUNNING,
                            reason=f"Step '{step.step_id}' approved: {req.decision_reason}",
                        )
                        self.plan.state = WorkflowState.RUNNING.value

            # Execute Step Tool
            step.status = "running"
            result = self.registry.execute(step.tool_name, step.input_payload)
            step.result = result

            if not result.success:
                step.status = "failed"
                if self.state_machine.can_transition_to(WorkflowState.FAILED):
                    self.state_machine.transition_to(
                        WorkflowState.FAILED,
                        reason=f"Step '{step.step_id}' execution failed: {result.error}",
                    )
                self.plan.state = WorkflowState.FAILED.value
                return result

            step.status = "completed"

        # All steps successfully executed
        if self.state_machine.can_transition_to(WorkflowState.SUCCEEDED):
            self.state_machine.transition_to(WorkflowState.SUCCEEDED, reason="All workflow steps completed successfully")
            self.plan.state = WorkflowState.SUCCEEDED.value

        return WorkflowResult.ok(
            output={
                "workflow_id": self.plan.workflow_id,
                "total_steps": len(self.plan.steps),
                "completed_steps": [s.step_id for s in self.plan.steps if s.status == "completed"],
            },
            metadata={"state": WorkflowState.SUCCEEDED.value},
        )

    def _is_step_consequential(self, step: WorkflowStep) -> bool:
        """
        Determines if an action is consequential:
        1. If explicitly set on step.is_consequential, honors that flag.
        2. Otherwise defaults to the tool's ToolSpec.is_consequential.
        """
        if step.is_consequential is not None:
            return bool(step.is_consequential)

        if self.registry.has_tool(step.tool_name):
            tool_spec = self.registry.get_spec(step.tool_name)
            return bool(tool_spec.is_consequential)

        return False
