"""
Workflow Executor for W4 Agentic Workflow (Week 1–3).

Coordinates workflow execution, enforcing:
- Strict state machine lifecycle transitions (draft -> running/awaiting_approval -> succeeded/failed/cancelled)
- Gated approval enforcement for consequential actions (defaults to awaiting_approval)
- Authoritative backend approval state synchronization (never trusting stale local approval)
- Absolute guarantee that pending, rejected, or expired consequential actions NEVER invoke the underlying tool
- Workflow checkpointing, resume after pause/failure/interruption, and failed-step recovery
- Thread-safe idempotency-key deduplication preventing duplicate consequential execution
- Step-level immutable audit trail, progress event emission, and chronological execution history
- Execution timeouts (workflow-level and step-level) and bounded retries strictly for idempotent operations
- Dynamic step output propagation and failure propagation
"""

from __future__ import annotations

import concurrent.futures
import copy
import re
import time
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

from .approval_manager import ApprovalManager, _ScopedRequestsProxy
from .audit import (
    AuditTrailManager,
    ExecutionHistory,
    ProgressEventType,
    ProgressSubscriber,
    StepAuditRecord,
    WorkflowProgressEvent,
)
from .checkpoint import (
    CheckpointNotFoundError,
    CheckpointStore,
    InMemoryCheckpointStore,
    RecoveryError,
    WorkflowCheckpoint,
    evaluate_step_recoverability,
    new_checkpoint_id,
    validate_checkpoint,
)
from .idempotency import IdempotencyStore
from .integrations import BackendApprovalClient, BackendUnavailableError
from .mock_tools import ToolRegistry, create_default_registry
from .schemas import ApprovalRequest, WorkflowPlan, WorkflowResult, WorkflowStep, _get_utc_now_iso
from .state_machine import StateTransitionRecord, WorkflowState, WorkflowStateMachine
from .validator import PlanValidator


class WorkflowExecutor:
    """
    Executes a WorkflowPlan using registered tools, enforces state machine lifecycle transitions,
    coordinates human-in-the-loop approvals, checkpoint/resume, failed-step recovery,
    idempotency protection, bounded retries, execution timeouts, cancellation, output propagation,
    and comprehensive step-level audit + progress event reporting.
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
        execution_id: Optional[str] = None,
        checkpoint_store: Optional[CheckpointStore] = None,
        idempotency_store: Optional[IdempotencyStore] = None,
        audit_manager: Optional[AuditTrailManager] = None,
        backend_approval_client: Optional[BackendApprovalClient] = None,
        auto_checkpoint: bool = True,
        max_recovery_attempts: int = 3,
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

        # Week 3 execution & reliability subsystems
        self.execution_id: str = execution_id or f"exec-{uuid4().hex[:12]}"
        self.checkpoint_store: CheckpointStore = (
            checkpoint_store if checkpoint_store is not None else InMemoryCheckpointStore()
        )
        self.idempotency_store: IdempotencyStore = (
            idempotency_store if idempotency_store is not None else IdempotencyStore()
        )
        self.audit_manager: AuditTrailManager = (
            audit_manager if audit_manager is not None else AuditTrailManager()
        )
        self.backend_approval_client: Optional[BackendApprovalClient] = backend_approval_client
        self.auto_checkpoint: bool = auto_checkpoint
        self.max_recovery_attempts: int = max_recovery_attempts

        # Initialize State Machine matching plan.state (defaults to DRAFT)
        initial_state = (
            WorkflowState(plan.state)
            if plan.state in [s.value for s in WorkflowState]
            else WorkflowState.DRAFT
        )
        self.state_machine = WorkflowStateMachine(initial_state)

        # Week 2 compatible flat audit log tracking executor events
        self.audit_log: List[Dict[str, Any]] = []

    @property
    def approval_requests(self) -> Dict[str, ApprovalRequest]:
        """Provides direct access to approval requests (step_id -> ApprovalRequest)."""
        return self.approval_manager.requests

    @approval_requests.setter
    def approval_requests(self, value: Dict[str, ApprovalRequest]) -> None:
        self.approval_manager._requests = value

    def get_workflow_approval_requests(self) -> Dict[str, ApprovalRequest]:
        """Return approval requests scoped strictly to this executor's workflow_id."""
        if isinstance(self.approval_manager._requests, _ScopedRequestsProxy):
            return self.approval_manager.get_requests_for_workflow(self.plan.workflow_id)
        return {
            step_id: req
            for step_id, req in self.approval_requests.items()
            if req.workflow_id == self.plan.workflow_id
        }

    @property
    def current_state(self) -> WorkflowState:
        """Returns the current state of the workflow execution."""
        return self.state_machine.current_state

    def subscribe_progress(self, callback: ProgressSubscriber) -> None:
        """Subscribe a listener to real-time WorkflowProgressEvent notifications."""
        self.audit_manager.subscribe(callback)

    def get_execution_history(self) -> ExecutionHistory:
        """Retrieve complete chronological audit trail, progress events, and state transitions."""
        transitions = [r.to_dict() for r in self.state_machine.history]
        return self.audit_manager.get_execution_history(
            self.plan.workflow_id,
            state_transitions=transitions,
        )

    def get_step_audit_records(self) -> List[StepAuditRecord]:
        """Retrieve chronological step-level audit records for this workflow."""
        return self.audit_manager.get_audit_records(self.plan.workflow_id)

    def get_progress_events(self) -> List[WorkflowProgressEvent]:
        """Retrieve chronological progress events emitted for this workflow."""
        return self.audit_manager.get_progress_events(self.plan.workflow_id)

    def _record_audit(self, event_type: str, **kwargs: Any) -> None:
        """Append an event to the Week 2 compatible flat executor audit log."""
        record = {
            "timestamp": _get_utc_now_iso(),
            "event": event_type,
            "workflow_id": self.plan.workflow_id,
            "execution_id": self.execution_id,
            "current_state": self.state_machine.current_state.value,
        }
        record.update(kwargs)
        self.audit_log.append(record)

    def _emit_progress(
        self,
        event_type: ProgressEventType,
        step_id: Optional[str] = None,
        step_name: Optional[str] = None,
        previous_state: Optional[str] = None,
        new_state: Optional[str] = None,
        message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> WorkflowProgressEvent:
        """Emit a structured WorkflowProgressEvent via AuditTrailManager."""
        return self.audit_manager.emit_progress(
            event_type=event_type,
            workflow_id=self.plan.workflow_id,
            execution_id=self.execution_id,
            step_id=step_id,
            step_name=step_name,
            previous_state=previous_state,
            new_state=new_state,
            message=message,
            metadata=metadata,
        )

    def _record_step_audit(
        self,
        event_type: str,
        step: Optional[WorkflowStep] = None,
        previous_state: Optional[str] = None,
        new_state: Optional[str] = None,
        start_timestamp: Optional[str] = None,
        completion_timestamp: Optional[str] = None,
        duration_ms: Optional[float] = None,
        result_status: Optional[str] = None,
        error: Optional[str] = None,
        approval_reference: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StepAuditRecord:
        """Record an immutable StepAuditRecord in AuditTrailManager."""
        return self.audit_manager.record_audit(
            workflow_id=self.plan.workflow_id,
            execution_id=self.execution_id,
            event_type=event_type,
            step_id=step.step_id if step else None,
            step_name=step.tool_name if step else None,
            previous_state=previous_state,
            new_state=new_state,
            start_timestamp=start_timestamp,
            completion_timestamp=completion_timestamp,
            duration_ms=duration_ms,
            result_status=result_status,
            error=error,
            retry_count=step.retry_count if step else 0,
            approval_reference=approval_reference,
            metadata=metadata,
        )

    def _transition_state(
        self,
        target_state: WorkflowState,
        reason: Optional[str] = None,
    ) -> WorkflowState:
        """Transition FSM state and synchronize plan.state."""
        new_state = self.state_machine.transition_to(target_state, reason=reason)
        self.plan.state = new_state.value
        return new_state

    # -----------------------------------------------------------------------
    # Checkpointing & Resume
    # -----------------------------------------------------------------------

    def save_checkpoint(self, reason: Optional[str] = None) -> WorkflowCheckpoint:
        """
        Capture and persist a complete WorkflowCheckpoint snapshot for the current
        workflow execution state.
        """
        completed_steps = [s.step_id for s in self.plan.steps if s.status == "completed"]
        pending_steps = [
            s.step_id
            for s in self.plan.steps
            if s.status in ("pending", "awaiting_approval", "running", "skipped")
        ]

        failed_steps = [s for s in self.plan.steps if s.status == "failed"]
        failed_step_info: Optional[Dict[str, Any]] = None
        if failed_steps:
            fs = failed_steps[-1]
            recoverable, non_rec_reason = evaluate_step_recoverability(
                fs.to_dict(),
                default_max_recovery_attempts=self.max_recovery_attempts,
            )
            failed_step_info = {
                "step_id": fs.step_id,
                "tool_name": fs.tool_name,
                "error": fs.result.error if fs.result else None,
                "retry_count": fs.retry_count,
                "recovery_attempts": int(fs.metadata.get("recovery_attempts", 0)),
                "recoverable": recoverable,
                "permanent_failure": not recoverable,
                "reason": non_rec_reason,
            }

        step_results = {
            s.step_id: s.result.to_dict()
            for s in self.plan.steps
            if s.result is not None
        }
        retry_info = {
            s.step_id: {
                "retry_count": s.retry_count,
                "max_retries": s.max_retries,
                "recovery_attempts": int(s.metadata.get("recovery_attempts", 0)),
                "max_recovery_attempts": int(
                    s.metadata.get("max_recovery_attempts", self.max_recovery_attempts)
                ),
            }
            for s in self.plan.steps
        }

        checkpoint = WorkflowCheckpoint(
            checkpoint_id=new_checkpoint_id(self.plan.workflow_id),
            workflow_id=self.plan.workflow_id,
            execution_id=self.execution_id,
            current_state=self.state_machine.current_state.value,
            completed_steps=completed_steps,
            pending_steps=pending_steps,
            failed_step_info=failed_step_info,
            step_results=step_results,
            retry_info=retry_info,
            timestamp=_get_utc_now_iso(),
            idempotency_info=self.idempotency_store.export_state(),
            plan_snapshot=self.plan.to_dict(),
            state_history=[r.to_dict() for r in self.state_machine.history],
            approval_snapshot=self.approval_manager.export_state(),
            audit_snapshot=self.audit_manager.export_workflow_history(self.plan.workflow_id),
            reason=reason,
            workflow_timeout_seconds=self.workflow_timeout_seconds,
            default_step_timeout_seconds=self.default_step_timeout_seconds,
            authorized_permissions=(
                sorted(self.authorized_permissions) if self.authorized_permissions is not None else None
            ),
            auto_checkpoint=self.auto_checkpoint,
            max_recovery_attempts=self.max_recovery_attempts,
            executor_audit_log=copy.deepcopy(self.audit_log),
        )

        saved = self.checkpoint_store.save(checkpoint)
        self._record_audit(
            "workflow_checkpoint_created",
            checkpoint_id=saved.checkpoint_id,
            reason=reason,
        )
        self._emit_progress(
            ProgressEventType.WORKFLOW_CHECKPOINT_CREATED,
            previous_state=self.current_state.value,
            new_state=self.current_state.value,
            message=reason or f"Checkpoint '{saved.checkpoint_id}' saved.",
            metadata={"checkpoint_id": saved.checkpoint_id},
        )
        return saved

    def _auto_save_checkpoint(self, reason: str) -> None:
        if self.auto_checkpoint:
            self.save_checkpoint(reason=reason)

    def get_latest_checkpoint(self) -> Optional[WorkflowCheckpoint]:
        """Return latest saved checkpoint for this workflow, if any."""
        return self.checkpoint_store.get_latest(self.plan.workflow_id)

    def list_checkpoints(self) -> List[WorkflowCheckpoint]:
        """Return all saved checkpoints for this workflow in chronological order."""
        return self.checkpoint_store.list_checkpoints(self.plan.workflow_id)

    @classmethod
    def from_checkpoint(
        cls,
        checkpoint_or_id: WorkflowCheckpoint | str,
        checkpoint_store: Optional[CheckpointStore] = None,
        registry: Optional[ToolRegistry] = None,
        validator: Optional[PlanValidator] = None,
        idempotency_store: Optional[IdempotencyStore] = None,
        audit_manager: Optional[AuditTrailManager] = None,
        backend_approval_client: Optional[BackendApprovalClient] = None,
        authorized_permissions: Optional[Set[str] | List[str]] = None,
        workflow_timeout_seconds: Optional[float] = None,
        default_step_timeout_seconds: Optional[float] = None,
        auto_checkpoint: Optional[bool] = None,
        max_recovery_attempts: Optional[int] = None,
    ) -> "WorkflowExecutor":
        """
        Reconstruct a WorkflowExecutor from a saved checkpoint or checkpoint_id.
        Validates checkpoint structure and integrity before restoration.
        """
        store = checkpoint_store if checkpoint_store is not None else InMemoryCheckpointStore()
        if isinstance(checkpoint_or_id, str):
            checkpoint = store.get(checkpoint_or_id)
            if checkpoint is None:
                raise CheckpointNotFoundError(f"Checkpoint '{checkpoint_or_id}' not found.")
        else:
            checkpoint = checkpoint_or_id

        validate_checkpoint(checkpoint)

        plan = WorkflowPlan.from_dict(checkpoint.plan_snapshot)
        executor = cls(
            plan=plan,
            registry=registry,
            validator=validator,
            authorized_permissions=(
                authorized_permissions
                if authorized_permissions is not None
                else (set(checkpoint.authorized_permissions) if checkpoint.authorized_permissions is not None else None)
            ),
            workflow_timeout_seconds=(
                workflow_timeout_seconds
                if workflow_timeout_seconds is not None
                else checkpoint.workflow_timeout_seconds
            ),
            default_step_timeout_seconds=(
                default_step_timeout_seconds
                if default_step_timeout_seconds is not None
                else checkpoint.default_step_timeout_seconds
            ),
            execution_id=checkpoint.execution_id,
            checkpoint_store=store,
            idempotency_store=idempotency_store,
            audit_manager=audit_manager,
            backend_approval_client=backend_approval_client,
            auto_checkpoint=auto_checkpoint if auto_checkpoint is not None else checkpoint.auto_checkpoint,
            max_recovery_attempts=(
                max_recovery_attempts
                if max_recovery_attempts is not None
                else checkpoint.max_recovery_attempts
            ),
        )
        executor._apply_checkpoint(checkpoint)
        # Preserve explicit caller overrides when supplied to from_checkpoint
        if authorized_permissions is not None:
            executor.authorized_permissions = authorized_permissions
        if workflow_timeout_seconds is not None:
            executor.workflow_timeout_seconds = workflow_timeout_seconds
        if default_step_timeout_seconds is not None:
            executor.default_step_timeout_seconds = default_step_timeout_seconds
        if auto_checkpoint is not None:
            executor.auto_checkpoint = auto_checkpoint
        if max_recovery_attempts is not None:
            executor.max_recovery_attempts = max_recovery_attempts
        return executor

    def _apply_checkpoint(self, checkpoint: WorkflowCheckpoint) -> None:
        """Restore plan, config, FSM history, approvals, idempotency, and audit history from a valid checkpoint."""
        validate_checkpoint(checkpoint, expected_workflow_id=self.plan.workflow_id)

        restored_plan = WorkflowPlan.from_dict(checkpoint.plan_snapshot)
        self.plan.goal = restored_plan.goal
        self.plan.state = restored_plan.state
        self.plan.metadata = dict(restored_plan.metadata)
        self.plan.timeout_seconds = restored_plan.timeout_seconds
        self.plan.steps[:] = restored_plan.steps
        self.execution_id = checkpoint.execution_id
        self.workflow_timeout_seconds = checkpoint.workflow_timeout_seconds
        self.default_step_timeout_seconds = checkpoint.default_step_timeout_seconds
        self.authorized_permissions = (
            set(checkpoint.authorized_permissions)
            if checkpoint.authorized_permissions is not None
            else None
        )
        self.auto_checkpoint = checkpoint.auto_checkpoint
        self.max_recovery_attempts = checkpoint.max_recovery_attempts
        if checkpoint.executor_audit_log:
            self.audit_log = copy.deepcopy(checkpoint.executor_audit_log)

        history_records = [
            StateTransitionRecord(
                from_state=WorkflowState(r["from_state"]),
                to_state=WorkflowState(r["to_state"]),
                timestamp=str(r["timestamp"]),
                reason=r.get("reason"),
            )
            for r in checkpoint.state_history
        ]
        self.state_machine = WorkflowStateMachine(
            initial_state=WorkflowState(checkpoint.current_state),
            history=history_records,
        )
        self.approval_manager.load_state(checkpoint.approval_snapshot)
        self.idempotency_store.load_state(checkpoint.idempotency_info)
        self.audit_manager.restore_workflow_history(self.plan.workflow_id, checkpoint.audit_snapshot)

    def resume_from_checkpoint(
        self,
        checkpoint_or_id: Optional[WorkflowCheckpoint | str] = None,
        recover_failed: bool = True,
        reason: Optional[str] = None,
    ) -> WorkflowResult:
        """
        Resume execution from an explicit checkpoint, checkpoint ID, or the latest
        saved checkpoint for this workflow.
        Completed steps are preserved and never executed again.
        """
        if checkpoint_or_id is None:
            checkpoint = self.checkpoint_store.get_latest(self.plan.workflow_id)
            if checkpoint is None:
                raise CheckpointNotFoundError(
                    f"No checkpoint found for workflow '{self.plan.workflow_id}'."
                )
        elif isinstance(checkpoint_or_id, str):
            checkpoint = self.checkpoint_store.get(checkpoint_or_id)
            if checkpoint is None:
                raise CheckpointNotFoundError(f"Checkpoint '{checkpoint_or_id}' not found.")
        else:
            checkpoint = checkpoint_or_id

        self._apply_checkpoint(checkpoint)

        prev_state = self.current_state.value
        if self.current_state == WorkflowState.PAUSED:
            has_pending_approval = any(
                req.is_pending() for req in self.get_workflow_approval_requests().values()
            )
            target = WorkflowState.AWAITING_APPROVAL if has_pending_approval else WorkflowState.RUNNING
            self._transition_state(target, reason=reason or f"Resumed from checkpoint '{checkpoint.checkpoint_id}'")
            self._record_audit("workflow_resumed", checkpoint_id=checkpoint.checkpoint_id, target_state=self.plan.state)
            self._emit_progress(
                ProgressEventType.WORKFLOW_RESUMED,
                previous_state=prev_state,
                new_state=self.plan.state,
                message=reason or f"Workflow resumed from checkpoint '{checkpoint.checkpoint_id}'.",
                metadata={"checkpoint_id": checkpoint.checkpoint_id},
            )
            return self.run()

        if self.current_state == WorkflowState.FAILED:
            if not recover_failed:
                raise RecoveryError(
                    f"Checkpoint '{checkpoint.checkpoint_id}' is in FAILED state and recover_failed=False."
                )
            return self.recover_failed_step(
                reason=reason or f"Recovered from checkpoint '{checkpoint.checkpoint_id}'",
            )

        if self.current_state in (WorkflowState.AWAITING_APPROVAL, WorkflowState.RUNNING, WorkflowState.DRAFT):
            self._record_audit("workflow_resumed", checkpoint_id=checkpoint.checkpoint_id, target_state=self.plan.state)
            self._emit_progress(
                ProgressEventType.WORKFLOW_RESUMED,
                previous_state=prev_state,
                new_state=self.plan.state,
                message=reason or f"Workflow resumed from checkpoint '{checkpoint.checkpoint_id}'.",
                metadata={"checkpoint_id": checkpoint.checkpoint_id},
            )
            return self.run()

        raise RecoveryError(f"Cannot resume workflow from terminal state '{self.current_state.value}'.")

    def recover_failed_step(
        self,
        step_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> WorkflowResult:
        """
        Recover a failed workflow step while preserving previously completed steps.
        Respects retry/recovery limits and permanently-failed guards.
        """
        if self.current_state != WorkflowState.FAILED:
            raise RecoveryError(
                f"Cannot recover failed step when workflow state is '{self.current_state.value}'. Must be 'failed'."
            )

        failed_steps = [s for s in self.plan.steps if s.status == "failed"]
        if not failed_steps:
            raise RecoveryError(f"Workflow '{self.plan.workflow_id}' is FAILED but has no failed steps.")

        target_step: Optional[WorkflowStep] = None
        if step_id is not None:
            target_step = self.plan.get_step(step_id)
            if target_step is None or target_step.status != "failed":
                raise RecoveryError(f"Step '{step_id}' is not in failed state.")
        else:
            target_step = failed_steps[0]

        recoverable, non_rec_reason = evaluate_step_recoverability(
            target_step.to_dict(),
            default_max_recovery_attempts=self.max_recovery_attempts,
        )
        if not recoverable:
            target_step.metadata["permanently_failed"] = True
            self._record_audit(
                "step_recovery_rejected",
                step_id=target_step.step_id,
                reason=non_rec_reason,
            )
            self._record_step_audit(
                event_type="step_recovery_rejected",
                step=target_step,
                previous_state=WorkflowState.FAILED.value,
                new_state=WorkflowState.FAILED.value,
                result_status="failed",
                error=non_rec_reason,
                metadata={"permanent_failure": True},
            )
            return WorkflowResult.fail(
                error=non_rec_reason or f"Step '{target_step.step_id}' is permanently failed.",
                metadata={"permanent_failure": True, "step_id": target_step.step_id},
            )

        attempt = int(target_step.metadata.get("recovery_attempts", 0)) + 1
        target_step.metadata["recovery_attempts"] = attempt
        recovery_log = list(target_step.metadata.get("recovery_history", []))
        recovery_log.append(
            {
                "attempt": attempt,
                "timestamp": _get_utc_now_iso(),
                "previous_error": target_step.result.error if target_step.result else None,
                "reason": reason or "Step recovery triggered",
            }
        )
        target_step.metadata["recovery_history"] = recovery_log

        # Reset the failed step (and any downstream steps marked skipped) to pending;
        # completed steps remain strictly untouched.
        target_step.status = "pending"
        target_step.result = None
        for step in self.plan.steps:
            if step.status == "skipped":
                step.status = "pending"
                step.result = None

        prev_state = self.current_state.value
        new_state = self.state_machine.recover_to(
            WorkflowState.RUNNING,
            reason=reason or f"Recovering failed step '{target_step.step_id}' (attempt {attempt})",
        )
        self.plan.state = new_state.value

        self._record_audit(
            "step_recovering",
            step_id=target_step.step_id,
            recovery_attempt=attempt,
            reason=reason,
        )
        self._record_step_audit(
            event_type="step_retrying",
            step=target_step,
            previous_state=prev_state,
            new_state=new_state.value,
            result_status="retrying",
            metadata={"recovery_attempt": attempt, "recovery": True},
        )
        self._emit_progress(
            ProgressEventType.WORKFLOW_RESUMED,
            previous_state=prev_state,
            new_state=new_state.value,
            message=f"Workflow resumed for recovery of step '{target_step.step_id}'.",
            metadata={"recovery_attempt": attempt, "step_id": target_step.step_id},
        )
        self._emit_progress(
            ProgressEventType.STEP_RETRYING,
            step_id=target_step.step_id,
            step_name=target_step.tool_name,
            previous_state="failed",
            new_state="pending",
            message=f"Retrying failed step '{target_step.step_id}' (recovery attempt {attempt}).",
            metadata={"recovery_attempt": attempt, "recovery": True},
        )
        self._auto_save_checkpoint(f"Recovery attempt {attempt} for step '{target_step.step_id}'")
        return self.run()

    # -----------------------------------------------------------------------
    # Approval & Authoritative Backend Sync
    # -----------------------------------------------------------------------

    def get_approval_request(self, step_id: str) -> Optional[ApprovalRequest]:
        """Retrieve approval request for a given step ID scoped to this workflow."""
        return self.approval_manager.get_request(step_id, workflow_id=self.plan.workflow_id)

    def sync_backend_approval(self, step_id: str) -> Optional[ApprovalRequest]:
        """
        Query the authoritative backend approval service (when configured) and
        synchronize local ApprovalRequest state. Never allows stale local approval
        to override backend PENDING/REJECTED/EXPIRED states.
        """
        req = self.approval_manager.get_request(step_id, workflow_id=self.plan.workflow_id)
        if self.backend_approval_client is None:
            return req

        backend_state = self.backend_approval_client.get_approval_state(
            workflow_id=self.plan.workflow_id,
            step_id=step_id,
            request_id=req.request_id if req else None,
        )
        if backend_state is None:
            return req

        if backend_state.workflow_id != self.plan.workflow_id or backend_state.step_id != step_id:
            raise ValueError(
                f"Backend approval binding mismatch for step '{step_id}' in workflow '{self.plan.workflow_id}'."
            )

        if req is None:
            req = self.approval_manager.create_request(
                workflow_id=backend_state.workflow_id,
                step_id=backend_state.step_id,
                tool_name=backend_state.tool_name or "unknown_tool",
                expires_at=backend_state.expires_at,
            )

        # Authoritative backend state always takes precedence over stale local cache
        if backend_state.status != req.status:
            req.status = backend_state.status
            req.decided_at = backend_state.decided_at or req.decided_at
            req.decision_reason = backend_state.decision_reason or req.decision_reason
            req.expires_at = backend_state.expires_at or req.expires_at
        elif backend_state.expires_at:
            req.expires_at = backend_state.expires_at
            req.check_expiry()

        return req

    def submit_approval(
        self,
        step_id: str,
        approved: bool,
        reason: Optional[str] = None,
        approver: str = "operator",
    ) -> ApprovalRequest:
        """
        Submit approval decision for a step.
        If approved=True, marks request as APPROVED.
        If approved=False, marks request as REJECTED.
        Validates binding, expiry, and pending state before dispatching to backend.
        Raises KeyError if no request exists for the step.
        """
        req = self.approval_manager.get_request(step_id, workflow_id=self.plan.workflow_id)
        if req is None:
            raise KeyError(f"No pending approval request found for step '{step_id}'.")

        if req.workflow_id != self.plan.workflow_id:
            raise ValueError(
                f"Approval binding mismatch: request '{req.request_id}' belongs to workflow "
                f"'{req.workflow_id}', not '{self.plan.workflow_id}'."
            )
        if req.is_expired():
            raise ValueError(f"Cannot decide request for step '{step_id}': Request is already EXPIRED.")
        if not req.is_pending():
            raise ValueError(f"Cannot decide request for step '{step_id}': Request is already {req.status}.")

        if self.backend_approval_client is not None:
            self.backend_approval_client.submit_decision(
                workflow_id=self.plan.workflow_id,
                step_id=step_id,
                request_id=req.request_id,
                approved=approved,
                reason=reason,
                approver=approver,
            )

        step = self.plan.get_step(step_id)
        if approved:
            decision = self.approval_manager.approve(
                step_id,
                reason=reason or "Explicit approval granted by operator.",
                approver=approver,
                workflow_id=self.plan.workflow_id,
            )
            self._record_audit("approval_submitted", step_id=step_id, decision="APPROVED", reason=reason)
            self._record_step_audit(
                event_type="approval_granted",
                step=step,
                previous_state=self.current_state.value,
                new_state=self.current_state.value,
                result_status="approved",
                approval_reference=decision.request_id,
                metadata={"approver": approver, "reason": decision.decision_reason},
            )
            self._emit_progress(
                ProgressEventType.APPROVAL_GRANTED,
                step_id=step_id,
                step_name=step.tool_name if step else decision.tool_name,
                previous_state=self.current_state.value,
                new_state=self.current_state.value,
                message=decision.decision_reason,
                metadata={"request_id": decision.request_id, "approver": approver},
            )
            return decision
        else:
            decision = self.approval_manager.reject(
                step_id,
                reason=reason or "Explicit rejection by operator.",
                approver=approver,
                workflow_id=self.plan.workflow_id,
            )
            self._record_audit("approval_submitted", step_id=step_id, decision="REJECTED", reason=reason)
            self._record_step_audit(
                event_type="approval_rejected",
                step=step,
                previous_state=self.current_state.value,
                new_state=self.current_state.value,
                result_status="rejected",
                error=decision.decision_reason,
                approval_reference=decision.request_id,
                metadata={"approver": approver},
            )
            self._emit_progress(
                ProgressEventType.APPROVAL_REJECTED,
                step_id=step_id,
                step_name=step.tool_name if step else decision.tool_name,
                previous_state=self.current_state.value,
                new_state=self.current_state.value,
                message=decision.decision_reason,
                metadata={"request_id": decision.request_id, "approver": approver},
            )
            return decision

    def pause(self, reason: Optional[str] = None) -> WorkflowState:
        """Pause the workflow execution and persist a checkpoint."""
        prev_state = self.current_state.value
        new_state = self._transition_state(WorkflowState.PAUSED, reason=reason)
        self._record_audit("workflow_paused", reason=reason)
        self._record_step_audit(
            event_type="workflow_paused",
            previous_state=prev_state,
            new_state=new_state.value,
            result_status="paused",
            metadata={"reason": reason},
        )
        self._emit_progress(
            ProgressEventType.WORKFLOW_PAUSED,
            previous_state=prev_state,
            new_state=new_state.value,
            message=reason or "Workflow execution paused.",
        )
        self._auto_save_checkpoint(reason or "Workflow paused")
        return new_state

    def resume(self) -> WorkflowResult:
        """Resume execution from paused state."""
        if self.state_machine.current_state != WorkflowState.PAUSED:
            raise ValueError(
                f"Cannot resume from state '{self.state_machine.current_state.value}'. Must be paused."
            )

        prev_state = self.current_state.value
        has_pending_approval = any(
            req.is_pending() for req in self.get_workflow_approval_requests().values()
        )
        if has_pending_approval:
            self._transition_state(WorkflowState.AWAITING_APPROVAL, reason="Resumed to awaiting approval")
        else:
            self._transition_state(WorkflowState.RUNNING, reason="Resumed workflow execution")

        self._record_audit("workflow_resumed", target_state=self.plan.state)
        self._record_step_audit(
            event_type="workflow_resumed",
            previous_state=prev_state,
            new_state=self.plan.state,
            result_status="resumed",
        )
        self._emit_progress(
            ProgressEventType.WORKFLOW_RESUMED,
            previous_state=prev_state,
            new_state=self.plan.state,
            message=f"Workflow resumed to state '{self.plan.state}'.",
        )
        return self.run()

    def cancel(self, reason: Optional[str] = None) -> WorkflowState:
        """Cancel workflow execution."""
        prev_state = self.current_state.value
        new_state = self._transition_state(
            WorkflowState.CANCELLED,
            reason=reason or "Operator cancelled workflow",
        )

        # Mark remaining pending/running steps as cancelled
        for step in self.plan.steps:
            if step.status in ("pending", "awaiting_approval", "running"):
                step.status = "cancelled"
                step.result = WorkflowResult.fail(
                    error=f"Step cancelled: {reason or 'Workflow cancelled'}",
                    metadata={"cancelled": True},
                )
                self._record_step_audit(
                    event_type="step_cancelled",
                    step=step,
                    previous_state=prev_state,
                    new_state=new_state.value,
                    result_status="cancelled",
                    error=step.result.error,
                )

        self._record_audit("workflow_cancelled", reason=reason)
        self._emit_progress(
            ProgressEventType.WORKFLOW_CANCELLED,
            previous_state=prev_state,
            new_state=new_state.value,
            message=reason or "Workflow cancelled.",
        )
        self._auto_save_checkpoint(reason or "Workflow cancelled")
        return new_state

    def run(self) -> WorkflowResult:
        """
        Execute the workflow plan according to dependency ordering, approval gating,
        authoritative backend approval state, idempotency protection, timeouts,
        bounded retries, checkpointing, audit recording, and progress events.
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
            prev_state = self.current_state.value
            if self.state_machine.current_state != WorkflowState.FAILED:
                if self.state_machine.can_transition_to(WorkflowState.RUNNING):
                    self._transition_state(WorkflowState.RUNNING, reason="Starting plan validation")
                self._transition_state(
                    WorkflowState.FAILED,
                    reason=f"Validation failed: {str(val_err)}",
                )
            self._record_audit("validation_failed", error=str(val_err))
            self._record_step_audit(
                event_type="validation_failed",
                previous_state=prev_state,
                new_state=WorkflowState.FAILED.value,
                result_status="failed",
                error=str(val_err),
            )
            self._emit_progress(
                ProgressEventType.WORKFLOW_FAILED,
                previous_state=prev_state,
                new_state=WorkflowState.FAILED.value,
                message=f"Plan validation failed: {str(val_err)}",
            )
            return WorkflowResult.fail(f"Plan validation failed: {str(val_err)}")

        # Transition from DRAFT to RUNNING if starting fresh
        if self.state_machine.current_state == WorkflowState.DRAFT:
            prev_state = self.current_state.value
            self._transition_state(WorkflowState.RUNNING, reason="Starting workflow execution")
            self._record_audit("workflow_started", workflow_id=self.plan.workflow_id)
            self._record_step_audit(
                event_type="workflow_started",
                previous_state=prev_state,
                new_state=WorkflowState.RUNNING.value,
                result_status="running",
            )
            self._emit_progress(
                ProgressEventType.WORKFLOW_STARTED,
                previous_state=prev_state,
                new_state=WorkflowState.RUNNING.value,
                message=f"Workflow '{self.plan.workflow_id}' started.",
            )
            self._auto_save_checkpoint("Workflow started")

        start_time = time.monotonic()

        # Execution loop over steps
        for step in self.plan.steps:
            # Completed steps MUST NEVER execute again
            if step.status == "completed":
                continue

            # Workflow-level timeout check
            if self.workflow_timeout_seconds is not None:
                elapsed = time.monotonic() - start_time
                if elapsed > self.workflow_timeout_seconds:
                    prev_wf_state = self.current_state.value
                    step.status = "failed"
                    step.result = WorkflowResult.fail(
                        f"Workflow execution timed out after {elapsed:.2f}s (limit: {self.workflow_timeout_seconds}s).",
                        metadata={"timeout": True, "workflow_timeout": True},
                    )
                    self._skip_dependent_steps(step.step_id)
                    if self.state_machine.can_transition_to(WorkflowState.FAILED):
                        self._transition_state(
                            WorkflowState.FAILED,
                            reason=f"Workflow execution timeout exceeded ({self.workflow_timeout_seconds}s)",
                        )
                    self._record_audit("workflow_timed_out", elapsed=elapsed, limit=self.workflow_timeout_seconds)
                    self._record_step_audit(
                        event_type="step_failed",
                        step=step,
                        previous_state=prev_wf_state,
                        new_state=WorkflowState.FAILED.value,
                        result_status="failed",
                        error=step.result.error,
                        metadata={"workflow_timeout": True},
                    )
                    self._emit_progress(
                        ProgressEventType.STEP_FAILED,
                        step_id=step.step_id,
                        step_name=step.tool_name,
                        previous_state="running",
                        new_state="failed",
                        message=step.result.error,
                    )
                    self._emit_progress(
                        ProgressEventType.WORKFLOW_FAILED,
                        previous_state=prev_wf_state,
                        new_state=WorkflowState.FAILED.value,
                        message=step.result.error,
                    )
                    self._auto_save_checkpoint("Workflow timed out")
                    return step.result

            # Check prerequisite dependencies
            for dep_id in step.dependencies:
                dep_step = self.plan.get_step(dep_id)
                if dep_step is None or dep_step.status != "completed":
                    prev_wf_state = self.current_state.value
                    step.status = "failed"
                    step.result = WorkflowResult.fail(
                        f"Prerequisite step '{dep_id}' is not completed (status: {dep_step.status if dep_step else 'missing'})."
                    )
                    if self.state_machine.can_transition_to(WorkflowState.FAILED):
                        self._transition_state(
                            WorkflowState.FAILED,
                            reason=f"Dependency '{dep_id}' incomplete",
                        )
                    self._record_audit("step_failed_dependency", step_id=step.step_id, missing_dep=dep_id)
                    self._record_step_audit(
                        event_type="step_failed",
                        step=step,
                        previous_state=prev_wf_state,
                        new_state=WorkflowState.FAILED.value,
                        result_status="failed",
                        error=step.result.error,
                        metadata={"missing_dep": dep_id},
                    )
                    self._emit_progress(
                        ProgressEventType.STEP_FAILED,
                        step_id=step.step_id,
                        step_name=step.tool_name,
                        previous_state="pending",
                        new_state="failed",
                        message=step.result.error,
                    )
                    self._emit_progress(
                        ProgressEventType.WORKFLOW_FAILED,
                        previous_state=prev_wf_state,
                        new_state=WorkflowState.FAILED.value,
                        message=step.result.error,
                    )
                    self._auto_save_checkpoint(f"Step '{step.step_id}' failed dependency check")
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
            approval_ref: Optional[str] = None

            # Enforce Approval Policy + Authoritative Backend State for consequential actions
            if is_consequential:
                self.approval_manager.check_expiries()
                req = self.approval_manager.get_request(step.step_id, workflow_id=self.plan.workflow_id)

                # Sync with authoritative backend approval state when backend client is configured
                if self.backend_approval_client is not None:
                    try:
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
                            self.backend_approval_client.publish_request(req)
                            self._record_audit("approval_requested", step_id=step.step_id, request_id=req.request_id)
                            self._record_step_audit(
                                event_type="approval_requested",
                                step=step,
                                previous_state=self.current_state.value,
                                new_state=WorkflowState.AWAITING_APPROVAL.value,
                                result_status="awaiting_approval",
                                approval_reference=req.request_id,
                            )
                            self._emit_progress(
                                ProgressEventType.APPROVAL_REQUESTED,
                                step_id=step.step_id,
                                step_name=step.tool_name,
                                previous_state=self.current_state.value,
                                new_state=WorkflowState.AWAITING_APPROVAL.value,
                                message=req.action_description,
                                metadata={"request_id": req.request_id},
                            )
                        req = self.sync_backend_approval(step.step_id)
                    except BackendUnavailableError as exc:
                        # CRITICAL SAFETY GUARANTEE: Never execute based on stale/unknown approval when backend is down
                        prev_wf_state = self.current_state.value
                        step.status = "failed"
                        step.result = WorkflowResult.fail(
                            error=f"Backend approval state unavailable: {str(exc)}",
                            metadata={"backend_unavailable": True, "step_id": step.step_id},
                        )
                        if self.state_machine.can_transition_to(WorkflowState.FAILED):
                            self._transition_state(
                                WorkflowState.FAILED,
                                reason=f"Backend approval unavailable for step '{step.step_id}'",
                            )
                        self._record_audit("backend_approval_unavailable", step_id=step.step_id, error=str(exc))
                        self._record_step_audit(
                            event_type="backend_approval_unavailable",
                            step=step,
                            previous_state=prev_wf_state,
                            new_state=WorkflowState.FAILED.value,
                            result_status="failed",
                            error=step.result.error,
                            approval_reference=req.request_id if req else None,
                        )
                        self._emit_progress(
                            ProgressEventType.WORKFLOW_FAILED,
                            step_id=step.step_id,
                            step_name=step.tool_name,
                            previous_state=prev_wf_state,
                            new_state=WorkflowState.FAILED.value,
                            message=step.result.error,
                        )
                        self._auto_save_checkpoint(f"Backend approval unavailable at step '{step.step_id}'")
                        return step.result

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
                        self._record_step_audit(
                            event_type="approval_requested",
                            step=step,
                            previous_state=self.current_state.value,
                            new_state=WorkflowState.AWAITING_APPROVAL.value,
                            result_status="awaiting_approval",
                            approval_reference=req.request_id,
                        )
                        self._emit_progress(
                            ProgressEventType.APPROVAL_REQUESTED,
                            step_id=step.step_id,
                            step_name=step.tool_name,
                            previous_state=self.current_state.value,
                            new_state=WorkflowState.AWAITING_APPROVAL.value,
                            message=req.action_description,
                            metadata={"request_id": req.request_id},
                        )

                    req.check_expiry()
                    if req.is_expired():
                        return self._handle_approval_expired(step, req)

                    prev_wf_state = self.current_state.value
                    if self.state_machine.current_state != WorkflowState.AWAITING_APPROVAL:
                        self._transition_state(
                            WorkflowState.AWAITING_APPROVAL,
                            reason=f"Step '{step.step_id}' is consequential and requires approval.",
                        )

                    step.status = "awaiting_approval"
                    self._record_audit("awaiting_approval", step_id=step.step_id, request_id=req.request_id)
                    self._record_step_audit(
                        event_type="awaiting_approval",
                        step=step,
                        previous_state=prev_wf_state,
                        new_state=WorkflowState.AWAITING_APPROVAL.value,
                        result_status="awaiting_approval",
                        approval_reference=req.request_id,
                    )
                    self._auto_save_checkpoint(f"Awaiting approval for step '{step.step_id}'")
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
                    return self._handle_approval_expired(step, req)

                elif req.is_rejected():
                    return self._handle_approval_rejected(step, req)

                elif req.is_approved():
                    # Enforce target binding + post-approval expiry guard before consequential execution
                    can_exec, bind_err = self.approval_manager.can_execute_step(
                        step.step_id,
                        workflow_id=self.plan.workflow_id,
                        tool_name=step.tool_name,
                    )
                    if not can_exec:
                        if bind_err and "expired" in bind_err.lower():
                            return self._handle_approval_expired(step, req, override_reason=bind_err)
                        prev_wf_state = self.current_state.value
                        step.status = "failed"
                        step.result = WorkflowResult.fail(
                            error=bind_err or "Approval validation failed.",
                            metadata={"step_id": step.step_id, "approval_binding_error": True},
                        )
                        if self.state_machine.can_transition_to(WorkflowState.FAILED):
                            self._transition_state(WorkflowState.FAILED, reason=bind_err)
                        self._record_audit("approval_binding_failed", step_id=step.step_id, error=bind_err)
                        self._record_step_audit(
                            event_type="approval_binding_failed",
                            step=step,
                            previous_state=prev_wf_state,
                            new_state=WorkflowState.FAILED.value,
                            result_status="failed",
                            error=bind_err,
                            approval_reference=req.request_id,
                        )
                        self._emit_progress(
                            ProgressEventType.WORKFLOW_FAILED,
                            step_id=step.step_id,
                            step_name=step.tool_name,
                            previous_state=prev_wf_state,
                            new_state=WorkflowState.FAILED.value,
                            message=bind_err,
                        )
                        self._auto_save_checkpoint(f"Approval binding failed at step '{step.step_id}'")
                        return step.result

                    approval_ref = req.request_id
                    if self.state_machine.current_state == WorkflowState.AWAITING_APPROVAL:
                        self._transition_state(
                            WorkflowState.RUNNING,
                            reason=f"Step '{step.step_id}' approved: {req.decision_reason}",
                        )
                        self._record_audit("approval_resuming", step_id=step.step_id, request_id=req.request_id)

            # Execute Step Tool with Idempotency Protection, Timeout, and Bounded Retries
            prev_step_status = step.status
            step.status = "running"
            step_start_iso = _get_utc_now_iso()
            step_t0 = time.monotonic()

            self._record_audit("step_executing", step_id=step.step_id, tool_name=step.tool_name)
            self._emit_progress(
                ProgressEventType.STEP_STARTED,
                step_id=step.step_id,
                step_name=step.tool_name,
                previous_state=prev_step_status,
                new_state="running",
                message=f"Executing step '{step.step_id}' ({step.tool_name}).",
                metadata={"approval_reference": approval_ref},
            )

            idem_key = self.idempotency_store.generate_key(
                workflow_id=self.plan.workflow_id,
                step_id=step.step_id,
                tool_name=step.tool_name,
                payload=resolved_payload,
                explicit_key=step.metadata.get("idempotency_key"),
            )
            step.metadata["idempotency_key"] = idem_key

            result, replayed = self.idempotency_store.execute(
                idempotency_key=idem_key,
                action=lambda: self._execute_step_with_timeout(step, resolved_payload),
                workflow_id=self.plan.workflow_id,
                step_id=step.step_id,
                tool_name=step.tool_name,
                payload=resolved_payload,
            )
            step.result = result

            if replayed:
                self._record_audit(
                    "idempotency_replay",
                    step_id=step.step_id,
                    tool_name=step.tool_name,
                    idempotency_key=idem_key,
                )

            # Bounded Retry Logic (strictly for idempotent operations)
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
                        self._record_step_audit(
                            event_type="step_retrying",
                            step=step,
                            previous_state="running",
                            new_state="running",
                            start_timestamp=step_start_iso,
                            result_status="retrying",
                            error=result.error,
                            approval_reference=approval_ref,
                            metadata={"attempt": step.retry_count, "max_retries": max_retries},
                        )
                        self._emit_progress(
                            ProgressEventType.STEP_RETRYING,
                            step_id=step.step_id,
                            step_name=step.tool_name,
                            previous_state="running",
                            new_state="running",
                            message=f"Retrying step '{step.step_id}' (attempt {step.retry_count}/{max_retries}).",
                            metadata={"attempt": step.retry_count, "max_retries": max_retries},
                        )
                        result, _ = self.idempotency_store.execute(
                            idempotency_key=idem_key,
                            action=lambda: self._execute_step_with_timeout(step, resolved_payload),
                            workflow_id=self.plan.workflow_id,
                            step_id=step.step_id,
                            tool_name=step.tool_name,
                            payload=resolved_payload,
                        )
                        step.result = result
                else:
                    self._record_audit(
                        "retry_prohibited_non_idempotent",
                        step_id=step.step_id,
                        tool_name=step.tool_name,
                        reason="Non-idempotent operation cannot be automatically retried",
                    )

            step_end_iso = _get_utc_now_iso()
            duration_ms = round((time.monotonic() - step_t0) * 1000.0, 3)

            if not result.success:
                prev_wf_state = self.current_state.value
                step.status = "failed"
                if self.state_machine.can_transition_to(WorkflowState.FAILED):
                    self._transition_state(
                        WorkflowState.FAILED,
                        reason=f"Step '{step.step_id}' execution failed: {result.error}",
                    )
                self._record_audit("step_failed", step_id=step.step_id, error=result.error)
                self._record_step_audit(
                    event_type="step_failed",
                    step=step,
                    previous_state="running",
                    new_state="failed",
                    start_timestamp=step_start_iso,
                    completion_timestamp=step_end_iso,
                    duration_ms=duration_ms,
                    result_status="failed",
                    error=result.error,
                    approval_reference=approval_ref,
                    metadata={"idempotency_key": idem_key},
                )
                self._emit_progress(
                    ProgressEventType.STEP_FAILED,
                    step_id=step.step_id,
                    step_name=step.tool_name,
                    previous_state="running",
                    new_state="failed",
                    message=result.error,
                    metadata={"duration_ms": duration_ms},
                )
                self._emit_progress(
                    ProgressEventType.WORKFLOW_FAILED,
                    step_id=step.step_id,
                    step_name=step.tool_name,
                    previous_state=prev_wf_state,
                    new_state=WorkflowState.FAILED.value,
                    message=result.error,
                )
                self._auto_save_checkpoint(f"Step '{step.step_id}' failed")
                return result

            step.status = "completed"
            self._record_audit("step_completed", step_id=step.step_id, output=result.output)
            self._record_step_audit(
                event_type="step_completed",
                step=step,
                previous_state="running",
                new_state="completed",
                start_timestamp=step_start_iso,
                completion_timestamp=step_end_iso,
                duration_ms=duration_ms,
                result_status="success",
                approval_reference=approval_ref,
                metadata={"idempotency_key": idem_key, "idempotency_replay": replayed},
            )
            self._emit_progress(
                ProgressEventType.STEP_COMPLETED,
                step_id=step.step_id,
                step_name=step.tool_name,
                previous_state="running",
                new_state="completed",
                message=f"Step '{step.step_id}' completed.",
                metadata={"duration_ms": duration_ms, "idempotency_replay": replayed},
            )
            self._auto_save_checkpoint(f"Step '{step.step_id}' completed")

        # All steps successfully executed
        if self.state_machine.can_transition_to(WorkflowState.SUCCEEDED):
            prev_wf_state = self.current_state.value
            self._transition_state(
                WorkflowState.SUCCEEDED,
                reason="All workflow steps completed successfully",
            )
            self._record_audit("workflow_succeeded", workflow_id=self.plan.workflow_id)
            self._record_step_audit(
                event_type="workflow_completed",
                previous_state=prev_wf_state,
                new_state=WorkflowState.SUCCEEDED.value,
                result_status="success",
            )
            self._emit_progress(
                ProgressEventType.WORKFLOW_COMPLETED,
                previous_state=prev_wf_state,
                new_state=WorkflowState.SUCCEEDED.value,
                message=f"Workflow '{self.plan.workflow_id}' completed successfully.",
            )
            self._auto_save_checkpoint("Workflow completed")

        return WorkflowResult.ok(
            output={
                "workflow_id": self.plan.workflow_id,
                "total_steps": len(self.plan.steps),
                "completed_steps": [s.step_id for s in self.plan.steps if s.status == "completed"],
            },
            metadata={"state": WorkflowState.SUCCEEDED.value},
        )

    def _handle_approval_expired(
        self,
        step: WorkflowStep,
        req: ApprovalRequest,
        override_reason: Optional[str] = None,
    ) -> WorkflowResult:
        """Handle expired approval safely without invoking the underlying tool."""
        prev_wf_state = self.current_state.value
        reason = override_reason or f"Approval request expired: {req.decision_reason or 'TTL expired'}"
        step.status = "failed"
        step.result = WorkflowResult.fail(
            error=reason,
            metadata={"step_id": step.step_id, "expired": True, "approval_status": "EXPIRED"},
        )
        if self.state_machine.can_transition_to(WorkflowState.FAILED):
            self._transition_state(
                WorkflowState.FAILED,
                reason=f"Step '{step.step_id}' approval expired: {req.decision_reason}",
            )
        self._record_audit("approval_expired", step_id=step.step_id, request_id=req.request_id)
        self._record_step_audit(
            event_type="approval_expired",
            step=step,
            previous_state=prev_wf_state,
            new_state=WorkflowState.FAILED.value,
            result_status="failed",
            error=reason,
            approval_reference=req.request_id,
        )
        self._emit_progress(
            ProgressEventType.APPROVAL_EXPIRED,
            step_id=step.step_id,
            step_name=step.tool_name,
            previous_state=prev_wf_state,
            new_state=WorkflowState.FAILED.value,
            message=reason,
            metadata={"request_id": req.request_id},
        )
        self._emit_progress(
            ProgressEventType.WORKFLOW_FAILED,
            step_id=step.step_id,
            step_name=step.tool_name,
            previous_state=prev_wf_state,
            new_state=WorkflowState.FAILED.value,
            message=reason,
        )
        self._auto_save_checkpoint(f"Approval expired for step '{step.step_id}'")
        return step.result

    def _handle_approval_rejected(self, step: WorkflowStep, req: ApprovalRequest) -> WorkflowResult:
        """Handle rejected approval safely without invoking the underlying tool."""
        prev_wf_state = self.current_state.value
        prev_step_status = step.status
        step.status = "failed"
        step.result = WorkflowResult.fail(
            error=f"Execution rejected by operator: {req.decision_reason or 'No reason provided'}",
            metadata={"step_id": step.step_id, "rejection": True, "approval_status": "REJECTED"},
        )
        if self.state_machine.current_state == WorkflowState.AWAITING_APPROVAL:
            self._transition_state(
                WorkflowState.FAILED,
                reason=f"Step '{step.step_id}' was rejected: {req.decision_reason}",
            )
        elif self.state_machine.can_transition_to(WorkflowState.FAILED):
            self._transition_state(
                WorkflowState.FAILED,
                reason=f"Step '{step.step_id}' was rejected: {req.decision_reason}",
            )
        self._record_audit("approval_rejected", step_id=step.step_id, request_id=req.request_id)
        self._record_step_audit(
            event_type="step_failed",
            step=step,
            previous_state=prev_wf_state,
            new_state=WorkflowState.FAILED.value,
            result_status="rejected",
            error=step.result.error,
            approval_reference=req.request_id,
        )
        already_emitted_rejected = any(
            ev.event_type == ProgressEventType.APPROVAL_REJECTED
            and ev.step_id == step.step_id
            and ev.metadata.get("request_id") == req.request_id
            for ev in self.get_progress_events()
        )
        if not already_emitted_rejected:
            self._emit_progress(
                ProgressEventType.APPROVAL_REJECTED,
                step_id=step.step_id,
                step_name=step.tool_name,
                previous_state=prev_wf_state,
                new_state=WorkflowState.FAILED.value,
                message=req.decision_reason,
                metadata={"request_id": req.request_id},
            )
        self._emit_progress(
            ProgressEventType.STEP_FAILED,
            step_id=step.step_id,
            step_name=step.tool_name,
            previous_state=prev_step_status,
            new_state="failed",
            message=step.result.error,
            metadata={"request_id": req.request_id},
        )
        self._emit_progress(
            ProgressEventType.WORKFLOW_FAILED,
            step_id=step.step_id,
            step_name=step.tool_name,
            previous_state=prev_wf_state,
            new_state=WorkflowState.FAILED.value,
            message=step.result.error,
            metadata={"request_id": req.request_id},
        )
        self._auto_save_checkpoint(f"Approval rejected for step '{step.step_id}'")
        return step.result

    def _execute_step_with_timeout(self, step: WorkflowStep, payload: Dict[str, Any]) -> WorkflowResult:
        """
        Execute a tool handler enforcing step-level timeout.
        Uses explicit non-blocking shutdown on timeout so hung tool threads do not
        block returning the timeout failure result.
        """
        timeout = step.timeout_seconds if step.timeout_seconds is not None else self.default_step_timeout_seconds

        if timeout is not None:
            if timeout <= 0:
                return WorkflowResult.fail(
                    f"Step '{step.step_id}' execution timed out (limit: {timeout}s).",
                    metadata={"timeout": True, "step_id": step.step_id},
                )
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            timed_out = False
            try:
                future = pool.submit(
                    self.registry.execute,
                    step.tool_name,
                    payload,
                    self.authorized_permissions,
                )
                try:
                    return future.result(timeout=timeout)
                except concurrent.futures.TimeoutError:
                    timed_out = True
                    return WorkflowResult.fail(
                        f"Step '{step.step_id}' execution timed out after {timeout}s.",
                        metadata={"timeout": True, "step_id": step.step_id},
                    )
            finally:
                pool.shutdown(wait=not timed_out, cancel_futures=True)

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
                        self._record_step_audit(
                            event_type="step_skipped",
                            step=step,
                            previous_state="pending",
                            new_state="skipped",
                            result_status="skipped",
                            error=step.result.error,
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
