"""
Step-Level Audit Trail, Progress Events, and Execution History for W4 Agentic Workflow (Week 3).

Provides:
- ProgressEventType enum covering full workflow, step, checkpoint, and approval lifecycle.
- Immutable StepAuditRecord and WorkflowProgressEvent contracts.
- Append-only AuditTrailManager preserving chronological ordering across checkpoint/resume.
- ExecutionHistory retrieval by workflow_id with subscriber callback support.
"""

from __future__ import annotations

import copy
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from .schemas import _get_utc_now_iso


class ProgressEventType(str, Enum):
    """Canonical progress events emitted during workflow execution."""

    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_CHECKPOINT_CREATED = "workflow_checkpoint_created"
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    STEP_RETRYING = "step_retrying"
    WORKFLOW_PAUSED = "workflow_paused"
    WORKFLOW_RESUMED = "workflow_resumed"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_REJECTED = "approval_rejected"
    APPROVAL_EXPIRED = "approval_expired"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_CANCELLED = "workflow_cancelled"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class StepAuditRecord:
    """
    Immutable step-level audit record capturing timing, state transitions,
    results, retries, errors, and approval references.
    """

    record_id: str
    sequence: int
    workflow_id: str
    execution_id: str
    step_id: Optional[str]
    step_name: Optional[str]
    event_type: str
    previous_state: Optional[str]
    new_state: Optional[str]
    start_timestamp: str
    completion_timestamp: Optional[str] = None
    duration_ms: Optional[float] = None
    result_status: Optional[str] = None
    error: Optional[str] = None
    retry_count: int = 0
    approval_reference: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize audit record to dictionary."""
        return {
            "record_id": self.record_id,
            "sequence": self.sequence,
            "workflow_id": self.workflow_id,
            "execution_id": self.execution_id,
            "step_id": self.step_id,
            "step_name": self.step_name,
            "event_type": self.event_type,
            "previous_state": self.previous_state,
            "new_state": self.new_state,
            "start_timestamp": self.start_timestamp,
            "completion_timestamp": self.completion_timestamp,
            "duration_ms": self.duration_ms,
            "result_status": self.result_status,
            "error": self.error,
            "retry_count": self.retry_count,
            "approval_reference": self.approval_reference,
            "metadata": copy.deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StepAuditRecord":
        """Reconstruct StepAuditRecord from dictionary."""
        return cls(
            record_id=str(data["record_id"]),
            sequence=int(data["sequence"]),
            workflow_id=str(data["workflow_id"]),
            execution_id=str(data["execution_id"]),
            step_id=data.get("step_id"),
            step_name=data.get("step_name"),
            event_type=str(data["event_type"]),
            previous_state=data.get("previous_state"),
            new_state=data.get("new_state"),
            start_timestamp=str(data["start_timestamp"]),
            completion_timestamp=data.get("completion_timestamp"),
            duration_ms=data.get("duration_ms"),
            result_status=data.get("result_status"),
            error=data.get("error"),
            retry_count=int(data.get("retry_count", 0)),
            approval_reference=data.get("approval_reference"),
            metadata=copy.deepcopy(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class WorkflowProgressEvent:
    """Immutable workflow progress notification event."""

    event_id: str
    sequence: int
    event_type: ProgressEventType
    workflow_id: str
    execution_id: str
    timestamp: str
    step_id: Optional[str] = None
    step_name: Optional[str] = None
    previous_state: Optional[str] = None
    new_state: Optional[str] = None
    message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize progress event to dictionary."""
        return {
            "event_id": self.event_id,
            "sequence": self.sequence,
            "event_type": self.event_type.value,
            "workflow_id": self.workflow_id,
            "execution_id": self.execution_id,
            "timestamp": self.timestamp,
            "step_id": self.step_id,
            "step_name": self.step_name,
            "previous_state": self.previous_state,
            "new_state": self.new_state,
            "message": self.message,
            "metadata": copy.deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowProgressEvent":
        """Reconstruct WorkflowProgressEvent from dictionary."""
        return cls(
            event_id=str(data["event_id"]),
            sequence=int(data["sequence"]),
            event_type=ProgressEventType(str(data["event_type"])),
            workflow_id=str(data["workflow_id"]),
            execution_id=str(data["execution_id"]),
            timestamp=str(data["timestamp"]),
            step_id=data.get("step_id"),
            step_name=data.get("step_name"),
            previous_state=data.get("previous_state"),
            new_state=data.get("new_state"),
            message=data.get("message"),
            metadata=copy.deepcopy(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class ExecutionHistory:
    """Complete chronological history for a workflow execution."""

    workflow_id: str
    audit_records: List[StepAuditRecord] = field(default_factory=list)
    progress_events: List[WorkflowProgressEvent] = field(default_factory=list)
    state_transitions: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize execution history to dictionary."""
        return {
            "workflow_id": self.workflow_id,
            "audit_records": [r.to_dict() for r in self.audit_records],
            "progress_events": [e.to_dict() for e in self.progress_events],
            "state_transitions": copy.deepcopy(self.state_transitions),
        }


ProgressSubscriber = Callable[[WorkflowProgressEvent], None]


class AuditTrailManager:
    """
    Append-only manager for step-level audit records, workflow progress events,
    and chronological execution history retrieval.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._audit_by_workflow: Dict[str, List[StepAuditRecord]] = {}
        self._events_by_workflow: Dict[str, List[WorkflowProgressEvent]] = {}
        self._audit_ids: Dict[str, set[str]] = {}
        self._event_ids: Dict[str, set[str]] = {}
        self._sequences: Dict[str, int] = {}
        self._subscribers: List[ProgressSubscriber] = []
        self._subscriber_errors: List[Dict[str, Any]] = []

    @property
    def subscriber_errors(self) -> List[Dict[str, Any]]:
        """Return a copy of recorded subscriber callback error entries."""
        with self._lock:
            return copy.deepcopy(self._subscriber_errors)

    def _next_seq(self, workflow_id: str) -> int:
        seq = self._sequences.get(workflow_id, 0) + 1
        self._sequences[workflow_id] = seq
        return seq

    def subscribe(self, callback: ProgressSubscriber) -> None:
        """Register a listener invoked whenever a WorkflowProgressEvent is emitted."""
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)

    def unsubscribe(self, callback: ProgressSubscriber) -> None:
        """Unregister a progress listener."""
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def record_audit(
        self,
        workflow_id: str,
        execution_id: str,
        event_type: str,
        step_id: Optional[str] = None,
        step_name: Optional[str] = None,
        previous_state: Optional[str] = None,
        new_state: Optional[str] = None,
        start_timestamp: Optional[str] = None,
        completion_timestamp: Optional[str] = None,
        duration_ms: Optional[float] = None,
        result_status: Optional[str] = None,
        error: Optional[str] = None,
        retry_count: int = 0,
        approval_reference: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StepAuditRecord:
        """Append an immutable StepAuditRecord without overwriting prior entries."""
        now_iso = _get_utc_now_iso()
        with self._lock:
            seq = self._next_seq(workflow_id)
            rec = StepAuditRecord(
                record_id=f"aud-{workflow_id}-{seq}-{uuid4().hex[:6]}",
                sequence=seq,
                workflow_id=workflow_id,
                execution_id=execution_id,
                step_id=step_id,
                step_name=step_name,
                event_type=event_type,
                previous_state=previous_state,
                new_state=new_state,
                start_timestamp=start_timestamp or now_iso,
                completion_timestamp=completion_timestamp,
                duration_ms=duration_ms,
                result_status=result_status,
                error=error,
                retry_count=retry_count,
                approval_reference=approval_reference,
                metadata=copy.deepcopy(metadata or {}),
            )
            self._audit_by_workflow.setdefault(workflow_id, []).append(rec)
            self._audit_ids.setdefault(workflow_id, set()).add(rec.record_id)
            return rec

    def emit_progress(
        self,
        event_type: ProgressEventType | str,
        workflow_id: str,
        execution_id: str,
        step_id: Optional[str] = None,
        step_name: Optional[str] = None,
        previous_state: Optional[str] = None,
        new_state: Optional[str] = None,
        message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> WorkflowProgressEvent:
        """Emit an immutable progress event and notify subscribers."""
        ev_type = (
            event_type
            if isinstance(event_type, ProgressEventType)
            else ProgressEventType(str(event_type))
        )
        with self._lock:
            seq = self._next_seq(workflow_id)
            event = WorkflowProgressEvent(
                event_id=f"evt-{workflow_id}-{seq}-{uuid4().hex[:6]}",
                sequence=seq,
                event_type=ev_type,
                workflow_id=workflow_id,
                execution_id=execution_id,
                timestamp=_get_utc_now_iso(),
                step_id=step_id,
                step_name=step_name,
                previous_state=previous_state,
                new_state=new_state,
                message=message,
                metadata=copy.deepcopy(metadata or {}),
            )
            self._events_by_workflow.setdefault(workflow_id, []).append(event)
            self._event_ids.setdefault(workflow_id, set()).add(event.event_id)
            subscribers = list(self._subscribers)

        for subscriber in subscribers:
            try:
                subscriber(event)
            except Exception as exc:
                error_entry = {
                    "timestamp": _get_utc_now_iso(),
                    "event_id": event.event_id,
                    "event_type": event.event_type.value,
                    "workflow_id": workflow_id,
                    "execution_id": execution_id,
                    "subscriber": repr(subscriber),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
                with self._lock:
                    self._subscriber_errors.append(error_entry)
                self.record_audit(
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    event_type="progress_subscriber_error",
                    step_id=event.step_id,
                    step_name=event.step_name,
                    error=f"{type(exc).__name__}: {exc}",
                    metadata={
                        "failed_event_id": event.event_id,
                        "failed_event_type": event.event_type.value,
                    },
                )
        return event

    def get_audit_records(self, workflow_id: str) -> List[StepAuditRecord]:
        """Return chronological copy of all audit records for workflow_id."""
        with self._lock:
            records = list(self._audit_by_workflow.get(workflow_id, []))
            return sorted(records, key=lambda r: r.sequence)

    def get_progress_events(self, workflow_id: str) -> List[WorkflowProgressEvent]:
        """Return chronological copy of all progress events for workflow_id."""
        with self._lock:
            events = list(self._events_by_workflow.get(workflow_id, []))
            return sorted(events, key=lambda e: e.sequence)

    def get_execution_history(
        self,
        workflow_id: str,
        state_transitions: Optional[List[Dict[str, Any]]] = None,
    ) -> ExecutionHistory:
        """Return full ExecutionHistory for workflow_id."""
        with self._lock:
            return ExecutionHistory(
                workflow_id=workflow_id,
                audit_records=self.get_audit_records(workflow_id),
                progress_events=self.get_progress_events(workflow_id),
                state_transitions=copy.deepcopy(state_transitions or []),
            )

    def export_workflow_history(self, workflow_id: str) -> Dict[str, Any]:
        """Export audit records, progress events, and sequence counter for checkpointing."""
        with self._lock:
            return {
                "sequence": self._sequences.get(workflow_id, 0),
                "audit_records": [r.to_dict() for r in self.get_audit_records(workflow_id)],
                "progress_events": [e.to_dict() for e in self.get_progress_events(workflow_id)],
            }

    def restore_workflow_history(self, workflow_id: str, data: Dict[str, Any]) -> None:
        """
        Restore audit records and progress events from a checkpoint snapshot
        without overwriting existing records.
        """
        if not data:
            return
        with self._lock:
            seen_audits = self._audit_ids.setdefault(workflow_id, set())
            audit_list = self._audit_by_workflow.setdefault(workflow_id, [])
            for rec_dict in data.get("audit_records", []):
                rec = StepAuditRecord.from_dict(rec_dict)
                if rec.record_id not in seen_audits:
                    seen_audits.add(rec.record_id)
                    audit_list.append(rec)

            seen_events = self._event_ids.setdefault(workflow_id, set())
            event_list = self._events_by_workflow.setdefault(workflow_id, [])
            for ev_dict in data.get("progress_events", []):
                ev = WorkflowProgressEvent.from_dict(ev_dict)
                if ev.event_id not in seen_events:
                    seen_events.add(ev.event_id)
                    event_list.append(ev)

            max_seq = max(
                [int(data.get("sequence", 0))]
                + [r.sequence for r in audit_list]
                + [e.sequence for e in event_list]
            )
            self._sequences[workflow_id] = max(self._sequences.get(workflow_id, 0), max_seq)
