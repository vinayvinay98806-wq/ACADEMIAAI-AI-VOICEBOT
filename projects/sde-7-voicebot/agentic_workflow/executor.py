"""
Workflow Executor for W4 Agentic Workflow.

Coordinates workflow execution, enforcing:
- Strict state machine lifecycle transitions (draft -> running/awaiting_approval -> succeeded/failed/cancelled)
- Gated approval enforcement for consequential actions (defaults to awaiting_approval)
- Absolute guarantee that pending, rejected, or expired consequential actions NEVER invoke the underlying tool
- Approval Manager integration with expiry tracking, target step binding, and audit logging
- Execution timeouts (workflow-level and step-level)
- Bounded retries strictly for explicitly idempotent operations (zero retries for non-idempotent operations)
- Safe workflow pause, resume, and cancellation
- Proper step output propagation to subsequent dependent steps
- Failure propagation preventing execution of dependent steps
- Harmless, deterministic mock tool execution via allow-listed ToolRegistry
"""

from __future__ import annotations

import concurrent.futures
import re
import time
from typing import Any, Dict, List, Optional, Set

from .approval_manager import ApprovalManager
from .mock_tools import ToolRegistry, create_default_registry
from .schemas import ApprovalRequest, WorkflowPlan, WorkflowResult, WorkflowStep, _get_utc_now_iso
from .state_machine import WorkflowState, WorkflowStateMachine
from .validator import PlanValidator


class WorkflowExecutor:
    """
    Executes a WorkflowPlan using registered tools, enforces state machine lifecycle transitions,
    coordinates human-in-the-loop approvals, bounded retries, execution timeouts,
    cancellation, output propagation, and comprehensive audit logging.
    """

    def __init__(
        self,
        plan: WorkflowPlan,
        registry: Optional[ToolRegistry] = None,
        validator: Optional[PlanValidator] = None,
        approval_manager: Optional[ApprovalManager] = None,
        authorized_permissions: Optional[Set[str] | List[str]] = None,
        workflow_timeout_seconds: Optional[float] = None,
        default_step_timeout_seconds: Optional[float] = None,
    ) -> None:
        self.plan = plan
        self.registry = registry if registry is not None else create_default_registry()
        self.validator = validator if validator is not None else PlanValidator(self.registry)
        self.approval_manager = approval_manager if approval_manager is not None else ApprovalManager()
        self.authorized_permissions = authorized_permissions
        self.workflow_timeout_seconds = (
            workflow_timeout_seconds if workflow_timeout_seconds is not None else plan.timeout_seconds
        )
        self.default_step_timeout_seconds = default_step_timeout_seconds

        # Initialize State Machine matching plan.state (defaults to DRAFT)
        initial_state = (
            WorkflowState(plan.state)
            if plan.state in [s.value for s in WorkflowState]
            else WorkflowState.DRAFT
        )
        self.state_machine = WorkflowStateMachine(initial_state)

        # Audit log tracking all executor events
        self.audit_log: List[Dict[str, Any]] = []

    @property
    def approval_requests(self) -> Dict[str, ApprovalRequest]:
        """Provides direct access to approval requests (step_id -> ApprovalRequest)."""
        return self.approval_manager.requests

    @approval_requests.setter
    def approval_requests(self, value: Dict[str, ApprovalRequest]) -> None:
        self.approval_manager._requests = value

    @property
    def current_state(self) -> WorkflowState:
        """Returns the current state of the workflow execution."""
        return self.state_machine.current_state

    def _record_audit(self, event_type: str, **kwargs: Any) -> None:
        """Append an event to the executor audit log."""
        record = {
            "timestamp": _get_utc_now_iso(),
            "event": event_type,
            "workflow_id": self.plan.workflow_id,
            "current_state": self.state_machine.current_state.value,
        }
        record.update(kwargs)
        self.audit_log.append(record)

    def get_approval_request(self, step_id: str) -> Optional[ApprovalRequest]:
        """Retrieve approval request for a given step ID."""
        return self.approval_manager.get_request(step_id)

    def submit_approval(self, step_id: str, approved: bool, reason: Optional[str] = None) -> ApprovalRequest:
        """
        Submit approval decision for a step.
        If approved=True, marks request as APPROVED.
        If approved=False, marks request as REJECTED.
        Raises KeyError if no pending request exists for the step.
        """
        req = self.approval_manager.get_request(step_id)
        if req is None:
            raise KeyError(f"No pending approval request found for step '{step_id}'.")

        if approved:
            decision = self.approval_manager.approve(
                step_id,
                reason=reason or "Explicit approval granted by operator.",
            )
            self._record_audit("approval_submitted", step_id=step_id, decision="APPROVED", reason=reason)
            return decision
        else:
            decision = self.approval_manager.reject(
                step_id,
                reason=reason or "Explicit rejection by operator.",
            )
            self._record_audit("approval_submitted", step_id=step_id, decision="REJECTED", reason=reason)
            return decision

    def pause(self, reason: Optional[str] = None) -> WorkflowState:
        """Pause the workflow execution."""
        new_state = self.state_machine.transition_to(WorkflowState.PAUSED, reason=reason)
        self.plan.state = new_state.value
        self._record_audit("workflow_paused", reason=reason)
        return new_state

    def resume(self) -> WorkflowResult:
        """Resume execution from paused state."""
        if self.state_machine.current_state != WorkflowState.PAUSED:
            raise ValueError(
                f"Cannot resume from state '{self.state_machine.current_state.value}'. Must be paused."
            )

        # Check if we were paused while waiting for approval
        has_pending_approval = any(req.is_pending() for req in self.approval_requests.values())
        if has_pending_approval:
            self.state_machine.transition_to(WorkflowState.AWAITING_APPROVAL, reason="Resumed to awaiting approval")
        else:
            self.state_machine.transition_to(WorkflowState.RUNNING, reason="Resumed workflow execution")

        self.plan.state = self.state_machine.current_state.value
        self._record_audit("workflow_resumed", target_state=self.plan.state)
        return self.run()

    def cancel(self, reason: Optional[str] = None) -> WorkflowState:
        """Cancel workflow execution."""
        new_state = self.state_machine.transition_to(
            WorkflowState.CANCELLED,
            reason=reason or "Operator cancelled workflow",
        )
        self.plan.state = new_state.value

        # Mark remaining pending/running steps as cancelled
        for step in self.plan.steps:
            if step.status in ("pending", "awaiting_approval", "running"):
                step.status = "cancelled"
                step.result = WorkflowResult.fail(
                    error=f"Step cancelled: {reason or 'Workflow cancelled'}",
                    metadata={"cancelled": True},
                )

        self._record_audit("workflow_cancelled", reason=reason)
        return new_state

    def run(self) -> WorkflowResult:
        """
        Execute the workflow plan according to dependency ordering, approval gating,
        timeouts, retries, and output propagation.
        """
        # If workflow already in terminal state, return corresponding result
        if self.state_machine.current_state == WorkflowState.CANCELLED:
            return WorkflowResult.fail(
                "Workflow execution cancelled.",
                metadata={"state": WorkflowState.CANCELLED.value},
            )
        if self.state_machine.current_state == WorkflowState.FAILED:
            return WorkflowResult.fail(
                "Workflow in terminal failed state.",
                metadata={"state": WorkflowState.FAILED.value},
            )
        if self.state_machine.current_state == WorkflowState.SUCCEEDED:
            return WorkflowResult.ok(
                output={"workflow_id": self.plan.workflow_id, "status": "already_succeeded"},
                metadata={"state": WorkflowState.SUCCEEDED.value},
            )

        # Validate plan structure, DAG consistency, and permission scopes
        try:
            self.validator.validate(self.plan, authorized_permissions=self.authorized_permissions)
        except Exception as val_err:
            if self.state_machine.current_state != WorkflowState.FAILED:
                if self.state_machine.can_transition_to(WorkflowState.RUNNING):
                    self.state_machine.transition_to(WorkflowState.RUNNING, reason="Starting plan validation")
                self.state_machine.transition_to(
                    WorkflowState.FAILED,
                    reason=f"Validation failed: {str(val_err)}",
                )
                self.plan.state = WorkflowState.FAILED.value
            self._record_audit("validation_failed", error=str(val_err))
            return WorkflowResult.fail(f"Plan validation failed: {str(val_err)}")

        # Transition from DRAFT to RUNNING if starting fresh
        if self.state_machine.current_state == WorkflowState.DRAFT:
            self.state_machine.transition_to(WorkflowState.RUNNING, reason="Starting workflow execution")
            self.plan.state = WorkflowState.RUNNING.value
            self._record_audit("workflow_started", workflow_id=self.plan.workflow_id)

        start_time = time.monotonic()

        # Execution loop over steps
        for step in self.plan.steps:
            # If step already completed, skip
            if step.status == "completed":
                continue

            # Workflow-level timeout check
            if self.workflow_timeout_seconds is not None:
                elapsed = time.monotonic() - start_time
                if elapsed > self.workflow_timeout_seconds:
                    step.status = "failed"
                    step.result = WorkflowResult.fail(
                        f"Workflow execution timed out after {elapsed:.2f}s (limit: {self.workflow_timeout_seconds}s).",
                        metadata={"timeout": True, "workflow_timeout": True},
                    )
                    self._skip_dependent_steps(step.step_id)
                    if self.state_machine.can_transition_to(WorkflowState.FAILED):
                        self.state_machine.transition_to(
                            WorkflowState.FAILED,
                            reason=f"Workflow execution timeout exceeded ({self.workflow_timeout_seconds}s)",
                        )
                    self.plan.state = WorkflowState.FAILED.value
                    self._record_audit("workflow_timed_out", elapsed=elapsed, limit=self.workflow_timeout_seconds)
                    return step.result

            # Check prerequisite dependencies
            for dep_id in step.dependencies:
                dep_step = self.plan.get_step(dep_id)
                if dep_step is None or dep_step.status != "completed":
                    step.status = "failed"
                    step.result = WorkflowResult.fail(
                        f"Prerequisite step '{dep_id}' is not completed (status: {dep_step.status if dep_step else 'missing'})."
                    )
                    if self.state_machine.can_transition_to(WorkflowState.FAILED):
                        self.state_machine.transition_to(
                            WorkflowState.FAILED,
                            reason=f"Dependency '{dep_id}' incomplete",
                        )
                    self.plan.state = WorkflowState.FAILED.value
                    self._record_audit("step_failed_dependency", step_id=step.step_id, missing_dep=dep_id)
                    return step.result

            # Propagate outputs from completed prior steps into step.input_payload
            completed_outputs = {
                s.step_id: (s.result.output or {})
                for s in self.plan.steps
                if s.status == "completed" and s.result is not None
            }
            resolved_payload = self._resolve_payload(step.input_payload, completed_outputs)
            step.input_payload = resolved_payload

            # Determine whether this action is consequential
            is_consequential = self._is_step_consequential(step)

            # Enforce Approval Policy for consequential actions
            if is_consequential:
                # Sweep expiries first
                self.approval_manager.check_expiries()
                req = self.approval_manager.get_request(step.step_id)

                if req is None or req.is_pending():
                    if req is None:
                        req = self.approval_manager.create_request(
                            workflow_id=self.plan.workflow_id,
                            step_id=step.step_id,
                            tool_name=step.tool_name,
                            action_description=(
                                f"Consequential action '{step.tool_name}' requires explicit operator approval."
                            ),
                            ttl_seconds=step.metadata.get("approval_ttl_seconds"),
                            expires_at=step.metadata.get("approval_expires_at"),
                        )
                        self._record_audit("approval_requested", step_id=step.step_id, request_id=req.request_id)

                    # Re-check expiry after creation
                    req.check_expiry()
                    if req.is_expired():
                        step.status = "failed"
                        step.result = WorkflowResult.fail(
                            error=f"Approval request expired: {req.decision_reason or 'TTL expired'}",
                            metadata={"step_id": step.step_id, "expired": True, "approval_status": "EXPIRED"},
                        )
                        if self.state_machine.can_transition_to(WorkflowState.FAILED):
                            self.state_machine.transition_to(
                                WorkflowState.FAILED,
                                reason=f"Step '{step.step_id}' approval expired: {req.decision_reason}",
                            )
                        self.plan.state = WorkflowState.FAILED.value
                        self._record_audit("approval_expired", step_id=step.step_id, request_id=req.request_id)
                        return step.result

                    # Transition state machine to awaiting_approval
                    if self.state_machine.current_state != WorkflowState.AWAITING_APPROVAL:
                        self.state_machine.transition_to(
                            WorkflowState.AWAITING_APPROVAL,
                            reason=f"Step '{step.step_id}' is consequential and requires approval.",
                        )
                        self.plan.state = WorkflowState.AWAITING_APPROVAL.value

                    step.status = "awaiting_approval"
                    self._record_audit("awaiting_approval", step_id=step.step_id, request_id=req.request_id)
                    # CRITICAL SAFETY GUARANTEE: Never invoke tool while pending approval!
                    return WorkflowResult.ok(
                        output={"approval_request": req.to_dict()},
                        metadata={
                            "state": WorkflowState.AWAITING_APPROVAL.value,
                            "pending_step": step.step_id,
                            "consequential": True,
                        },
                    )

                elif req.is_expired():
                    # CRITICAL SAFETY GUARANTEE: Expired action NEVER invokes tool!
                    step.status = "failed"
                    step.result = WorkflowResult.fail(
                        error=f"Approval request expired: {req.decision_reason or 'TTL expired'}",
                        metadata={"step_id": step.step_id, "expired": True, "approval_status": "EXPIRED"},
                    )
                    if self.state_machine.can_transition_to(WorkflowState.FAILED):
                        self.state_machine.transition_to(
                            WorkflowState.FAILED,
                            reason=f"Step '{step.step_id}' approval expired: {req.decision_reason}",
                        )
                    self.plan.state = WorkflowState.FAILED.value
                    self._record_audit("approval_expired", step_id=step.step_id, request_id=req.request_id)
                    return step.result

                elif req.is_rejected():
                    # CRITICAL SAFETY GUARANTEE: Rejection strictly prevents execution of the tool!
                    step.status = "failed"
                    step.result = WorkflowResult.fail(
                        error=f"Execution rejected by operator: {req.decision_reason or 'No reason provided'}",
                        metadata={"step_id": step.step_id, "rejection": True, "approval_status": "REJECTED"},
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
                    self._record_audit("approval_rejected", step_id=step.step_id, request_id=req.request_id)
                    return step.result

                elif req.is_approved():
                    # Transition from awaiting_approval to running if needed
                    if self.state_machine.current_state == WorkflowState.AWAITING_APPROVAL:
                        self.state_machine.transition_to(
                            WorkflowState.RUNNING,
                            reason=f"Step '{step.step_id}' approved: {req.decision_reason}",
                        )
                        self.plan.state = WorkflowState.RUNNING.value
                        self._record_audit("approval_resuming", step_id=step.step_id, request_id=req.request_id)

            # Execute Step Tool with Timeout and Bounded Retries
            step.status = "running"
            self._record_audit("step_executing", step_id=step.step_id, tool_name=step.tool_name)

            result = self._execute_step_with_timeout(step, resolved_payload)
            step.result = result

            # Bounded Retry Logic
            if not result.success:
                is_idempotent = self._is_step_idempotent(step)
                if is_idempotent:
                    max_retries = min(step.max_retries, 5)  # Enforce upper bound of 5
                    while not result.success and step.retry_count < max_retries:
                        step.retry_count += 1
                        self._record_audit(
                            "step_retry",
                            step_id=step.step_id,
                            tool_name=step.tool_name,
                            attempt=step.retry_count,
                            max_retries=max_retries,
                            error=result.error,
                        )
                        result = self._execute_step_with_timeout(step, resolved_payload)
                        step.result = result
                else:
                    self._record_audit(
                        "retry_prohibited_non_idempotent",
                        step_id=step.step_id,
                        tool_name=step.tool_name,
                        reason="Non-idempotent operation cannot be automatically retried",
                    )

            if not result.success:
                step.status = "failed"
                if self.state_machine.can_transition_to(WorkflowState.FAILED):
                    self.state_machine.transition_to(
                        WorkflowState.FAILED,
                        reason=f"Step '{step.step_id}' execution failed: {result.error}",
                    )
                self.plan.state = WorkflowState.FAILED.value
                self._record_audit("step_failed", step_id=step.step_id, error=result.error)
                return result

            step.status = "completed"
            self._record_audit("step_completed", step_id=step.step_id, output=result.output)

        # All steps successfully executed
        if self.state_machine.can_transition_to(WorkflowState.SUCCEEDED):
            self.state_machine.transition_to(
                WorkflowState.SUCCEEDED,
                reason="All workflow steps completed successfully",
            )
            self.plan.state = WorkflowState.SUCCEEDED.value
            self._record_audit("workflow_succeeded", workflow_id=self.plan.workflow_id)

        return WorkflowResult.ok(
            output={
                "workflow_id": self.plan.workflow_id,
                "total_steps": len(self.plan.steps),
                "completed_steps": [s.step_id for s in self.plan.steps if s.status == "completed"],
            },
            metadata={"state": WorkflowState.SUCCEEDED.value},
        )

    def _execute_step_with_timeout(self, step: WorkflowStep, payload: Dict[str, Any]) -> WorkflowResult:
        """Execute a tool handler enforcing step-level timeout."""
        timeout = step.timeout_seconds if step.timeout_seconds is not None else self.default_step_timeout_seconds

        if timeout is not None:
            if timeout <= 0:
                return WorkflowResult.fail(
                    f"Step '{step.step_id}' execution timed out (limit: {timeout}s).",
                    metadata={"timeout": True, "step_id": step.step_id},
                )
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    self.registry.execute,
                    step.tool_name,
                    payload,
                    self.authorized_permissions,
                )
                try:
                    return future.result(timeout=timeout)
                except concurrent.futures.TimeoutError:
                    return WorkflowResult.fail(
                        f"Step '{step.step_id}' execution timed out after {timeout}s.",
                        metadata={"timeout": True, "step_id": step.step_id},
                    )

        return self.registry.execute(step.tool_name, payload, caller_permissions=self.authorized_permissions)

    def _skip_dependent_steps(self, failed_step_id: str) -> None:
        """Find all steps directly or indirectly dependent on failed_step_id and mark as skipped."""
        visited: Set[str] = set()
        to_visit: List[str] = [failed_step_id]

        while to_visit:
            curr = to_visit.pop(0)
            for step in self.plan.steps:
                if curr in step.dependencies and step.step_id not in visited:
                    visited.add(step.step_id)
                    to_visit.append(step.step_id)
                    if step.status not in ("completed", "failed"):
                        step.status = "skipped"
                        step.result = WorkflowResult.fail(
                            f"Step '{step.step_id}' skipped because dependency '{curr}' failed.",
                            metadata={"skipped": True, "failed_dependency": curr},
                        )
                        self._record_audit(
                            "step_skipped",
                            step_id=step.step_id,
                            reason=f"Prerequisite dependency '{curr}' failed",
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

    def _is_step_idempotent(self, step: WorkflowStep) -> bool:
        """
        Determines if a step operation is idempotent:
        1. If explicitly set on step.is_idempotent, honors that flag.
        2. Otherwise defaults to the tool's ToolSpec.is_idempotent.
        """
        if step.is_idempotent is not None:
            return bool(step.is_idempotent)

        if self.registry.has_tool(step.tool_name):
            tool_spec = self.registry.get_spec(step.tool_name)
            return bool(tool_spec.is_idempotent)

        return False

    def _resolve_payload(
        self,
        payload: Dict[str, Any],
        completed_outputs: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Recursively resolves dynamic references to previous step outputs in input payloads.
        Supports references in the form:
        - "$step_id.key"
        - "$step_id.output.key"
        - "$step_id.key[0]"
        - "{{step_id.key}}"
        """
        resolved: Dict[str, Any] = {}
        for k, v in payload.items():
            if isinstance(v, str):
                resolved[k] = self._resolve_reference(v, completed_outputs)
            elif isinstance(v, dict):
                resolved[k] = self._resolve_payload(v, completed_outputs)
            elif isinstance(v, list):
                resolved[k] = [
                    self._resolve_reference(item, completed_outputs) if isinstance(item, str) else item
                    for item in v
                ]
            else:
                resolved[k] = v
        return resolved

    def _resolve_reference(self, expr: str, completed_outputs: Dict[str, Dict[str, Any]]) -> Any:
        """Resolve a single reference string against completed outputs."""
        trimmed = expr.strip()
        if trimmed.startswith("{{") and trimmed.endswith("}}"):
            cleaned = trimmed[2:-2].strip()
        elif trimmed.startswith("$"):
            cleaned = trimmed[1:].strip()
        else:
            return expr

        parts = cleaned.split(".", 1)
        step_id = parts[0]
        if step_id not in completed_outputs:
            return expr

        current = completed_outputs[step_id]
        if len(parts) == 1:
            return current

        path = parts[1]
        if path.startswith("output."):
            path = path[7:]

        tokens = re.findall(r"[^.\[\]]+|\[\d+\]", path)
        for token in tokens:
            if token.startswith("[") and token.endswith("]"):
                idx = int(token[1:-1])
                if isinstance(current, (list, tuple)) and 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return expr
            else:
                if isinstance(current, dict) and token in current:
                    current = current[token]
                else:
                    return expr

        return current
