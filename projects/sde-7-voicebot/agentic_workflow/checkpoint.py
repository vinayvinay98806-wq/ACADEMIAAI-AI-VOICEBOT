"""
Workflow Checkpointing, Persistence, and Recovery Contracts for W4 Agentic Workflow (Week 3).

Provides:
- WorkflowCheckpoint dataclass capturing complete execution state + SHA-256 integrity checksum.
- Strict checkpoint validation rejecting missing, empty, malformed, or tampered checksums/payloads.
- CheckpointStore interface with InMemoryCheckpointStore and atomic FileCheckpointStore.
- Failed-step recovery policy evaluation respecting retry limits and permanent failures.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from .schemas import _get_utc_now_iso
from .state_machine import WorkflowState


class CheckpointError(ValueError):
    """Base exception for checkpoint and resume errors."""


class CheckpointNotFoundError(CheckpointError):
    """Raised when a requested checkpoint cannot be found."""


class InvalidCheckpointError(CheckpointError):
    """Raised when a checkpoint is malformed, corrupted, or invalid for resumption."""


class RecoveryError(CheckpointError):
    """Raised when a failed workflow step cannot be recovered."""


# Error metadata flags or event markers that indicate permanent, non-recoverable failures
NON_RECOVERABLE_MARKERS = {
    "approval_rejected",
    "approval_expired",
    "permission_violation",
    "payload_invalid",
    "cancelled",
    "permanent_failure",
}


def _compute_checkpoint_checksum(payload: Dict[str, Any]) -> str:
    """Compute deterministic SHA-256 checksum over checkpoint payload excluding checksum itself."""
    sanitized = {k: v for k, v in payload.items() if k != "checksum"}
    canonical = json.dumps(sanitized, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@dataclass
class WorkflowCheckpoint:
    """
    Serializable snapshot of workflow execution sufficient for deterministic
    resume after pause, interruption, or recoverable step failure.
    """

    checkpoint_id: str
    workflow_id: str
    execution_id: str
    current_state: str
    completed_steps: List[str] = field(default_factory=list)
    pending_steps: List[str] = field(default_factory=list)
    failed_step_info: Optional[Dict[str, Any]] = None
    step_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    retry_info: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    timestamp: str = field(default_factory=_get_utc_now_iso)
    idempotency_info: Dict[str, Any] = field(default_factory=dict)
    plan_snapshot: Dict[str, Any] = field(default_factory=dict)
    state_history: List[Dict[str, Any]] = field(default_factory=list)
    approval_snapshot: Dict[str, Any] = field(default_factory=dict)
    audit_snapshot: Dict[str, Any] = field(default_factory=dict)
    reason: Optional[str] = None
    workflow_timeout_seconds: Optional[float] = None
    default_step_timeout_seconds: Optional[float] = None
    authorized_permissions: Optional[List[str]] = None
    auto_checkpoint: bool = True
    max_recovery_attempts: int = 3
    executor_audit_log: List[Dict[str, Any]] = field(default_factory=list)
    checksum: Optional[str] = None

    def __post_init__(self) -> None:
        # Compute checksum ONLY when creating a fresh checkpoint (checksum omitted as None).
        # Explicit empty string "" is preserved so verification fails rather than resealing.
        if self.checksum is None:
            self.checksum = self.compute_checksum()

    def _payload_for_checksum(self) -> Dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "workflow_id": self.workflow_id,
            "execution_id": self.execution_id,
            "current_state": self.current_state,
            "completed_steps": list(self.completed_steps),
            "pending_steps": list(self.pending_steps),
            "failed_step_info": self.failed_step_info,
            "step_results": self.step_results,
            "retry_info": self.retry_info,
            "timestamp": self.timestamp,
            "idempotency_info": self.idempotency_info,
            "plan_snapshot": self.plan_snapshot,
            "state_history": self.state_history,
            "approval_snapshot": self.approval_snapshot,
            "audit_snapshot": self.audit_snapshot,
            "reason": self.reason,
            "workflow_timeout_seconds": self.workflow_timeout_seconds,
            "default_step_timeout_seconds": self.default_step_timeout_seconds,
            "authorized_permissions": (
                list(self.authorized_permissions) if self.authorized_permissions is not None else None
            ),
            "auto_checkpoint": self.auto_checkpoint,
            "max_recovery_attempts": self.max_recovery_attempts,
            "executor_audit_log": self.executor_audit_log,
        }

    def compute_checksum(self) -> str:
        """Compute expected SHA-256 integrity checksum for this checkpoint."""
        return _compute_checkpoint_checksum(self._payload_for_checksum())

    def verify_checksum(self) -> bool:
        """Verify checkpoint integrity against its stored checksum."""
        if not isinstance(self.checksum, str) or not self.checksum.strip():
            return False
        return self.checksum == self.compute_checksum()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize checkpoint to JSON-safe dictionary."""
        data = self._payload_for_checksum()
        data["checksum"] = self.checksum if self.checksum is not None else self.compute_checksum()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowCheckpoint":
        """
        Reconstruct WorkflowCheckpoint from serialized dictionary.
        Strictly rejects missing, empty, non-string, or mismatched checksums
        and NEVER recalculates a new checksum for imported data.
        """
        if not isinstance(data, dict):
            raise InvalidCheckpointError("Checkpoint payload must be a dictionary.")
        required = ("checkpoint_id", "workflow_id", "execution_id", "current_state", "plan_snapshot")
        for key in required:
            if key not in data or not data[key]:
                raise InvalidCheckpointError(f"Malformed checkpoint: missing required field '{key}'.")

        raw_checksum = data.get("checksum")
        if not isinstance(raw_checksum, str) or not raw_checksum.strip():
            raise InvalidCheckpointError(
                f"Malformed checkpoint '{data.get('checkpoint_id')}': missing or empty checksum."
            )

        if not isinstance(data["plan_snapshot"], dict):
            raise InvalidCheckpointError("Malformed checkpoint: 'plan_snapshot' must be a dict.")

        def _require_list(field_name: str) -> List[Any]:
            val = data.get(field_name, [])
            if val is None:
                return []
            if not isinstance(val, list):
                raise InvalidCheckpointError(f"Malformed checkpoint: '{field_name}' must be a list.")
            return list(val)

        def _require_dict(field_name: str) -> Dict[str, Any]:
            val = data.get(field_name, {})
            if val is None:
                return {}
            if not isinstance(val, dict):
                raise InvalidCheckpointError(f"Malformed checkpoint: '{field_name}' must be a dict.")
            return dict(val)

        raw_perms = data.get("authorized_permissions")
        if raw_perms is not None:
            if not isinstance(raw_perms, list) or not all(isinstance(p, str) for p in raw_perms):
                raise InvalidCheckpointError(
                    "Malformed checkpoint: 'authorized_permissions' must be a list of strings or null."
                )
            raw_perms = list(raw_perms)

        raw_auto_chk = data.get("auto_checkpoint", True)
        if not isinstance(raw_auto_chk, bool):
            raise InvalidCheckpointError("Malformed checkpoint: 'auto_checkpoint' must be a bool.")

        raw_max_rec = data.get("max_recovery_attempts", 3)
        if isinstance(raw_max_rec, bool) or not isinstance(raw_max_rec, int) or raw_max_rec < 0:
            raise InvalidCheckpointError(
                "Malformed checkpoint: 'max_recovery_attempts' must be a non-negative int."
            )

        chk = cls(
            checkpoint_id=str(data["checkpoint_id"]),
            workflow_id=str(data["workflow_id"]),
            execution_id=str(data["execution_id"]),
            current_state=str(data["current_state"]),
            completed_steps=_require_list("completed_steps"),
            pending_steps=_require_list("pending_steps"),
            failed_step_info=data.get("failed_step_info"),
            step_results=_require_dict("step_results"),
            retry_info=_require_dict("retry_info"),
            timestamp=str(data.get("timestamp", "")),
            idempotency_info=_require_dict("idempotency_info"),
            plan_snapshot=dict(data["plan_snapshot"]),
            state_history=_require_list("state_history"),
            approval_snapshot=_require_dict("approval_snapshot"),
            audit_snapshot=_require_dict("audit_snapshot"),
            reason=data.get("reason"),
            workflow_timeout_seconds=data.get("workflow_timeout_seconds"),
            default_step_timeout_seconds=data.get("default_step_timeout_seconds"),
            authorized_permissions=raw_perms,
            auto_checkpoint=raw_auto_chk,
            max_recovery_attempts=raw_max_rec,
            executor_audit_log=_require_list("executor_audit_log"),
            checksum=raw_checksum,
        )

        if not chk.verify_checksum():
            raise InvalidCheckpointError(
                f"Checkpoint '{chk.checkpoint_id}' failed integrity checksum verification."
            )
        return chk


def new_checkpoint_id(workflow_id: str) -> str:
    """Generate a unique checkpoint identifier."""
    return f"chk-{workflow_id}-{uuid4().hex[:10]}"


def validate_checkpoint(
    checkpoint: WorkflowCheckpoint,
    expected_workflow_id: Optional[str] = None,
    allow_terminal: bool = False,
) -> None:
    """
    Validate checkpoint structure, state, integrity checksum, and plan consistency.
    Raises InvalidCheckpointError if invalid.
    """
    if not isinstance(checkpoint, WorkflowCheckpoint):
        raise InvalidCheckpointError(f"Expected WorkflowCheckpoint, got {type(checkpoint).__name__}.")

    for field_name in ("checkpoint_id", "workflow_id", "execution_id", "current_state", "timestamp"):
        val = getattr(checkpoint, field_name, None)
        if not val or not str(val).strip():
            raise InvalidCheckpointError(f"Invalid checkpoint: '{field_name}' must be non-empty.")

    if expected_workflow_id is not None and checkpoint.workflow_id != expected_workflow_id:
        raise InvalidCheckpointError(
            f"Checkpoint workflow_id '{checkpoint.workflow_id}' does not match '{expected_workflow_id}'."
        )

    valid_states = {s.value for s in WorkflowState}
    if checkpoint.current_state not in valid_states:
        raise InvalidCheckpointError(f"Invalid checkpoint workflow state '{checkpoint.current_state}'.")

    if not allow_terminal and checkpoint.current_state in {
        WorkflowState.SUCCEEDED.value,
        WorkflowState.CANCELLED.value,
    }:
        raise InvalidCheckpointError(
            f"Cannot resume checkpoint '{checkpoint.checkpoint_id}' from terminal state '{checkpoint.current_state}'."
        )

    if not checkpoint.verify_checksum():
        raise InvalidCheckpointError(
            f"Checkpoint '{checkpoint.checkpoint_id}' failed integrity checksum verification."
        )

    plan_snap = checkpoint.plan_snapshot
    if not isinstance(plan_snap, dict) or not isinstance(plan_snap.get("steps"), list) or not plan_snap.get("steps"):
        raise InvalidCheckpointError("Invalid checkpoint: 'plan_snapshot' is missing workflow steps.")

    if plan_snap.get("workflow_id") != checkpoint.workflow_id:
        raise InvalidCheckpointError("Invalid checkpoint: plan_snapshot workflow_id mismatch.")

    if len(set(checkpoint.completed_steps)) != len(checkpoint.completed_steps):
        raise InvalidCheckpointError("Invalid checkpoint: duplicate entries in 'completed_steps'.")
    if len(set(checkpoint.pending_steps)) != len(checkpoint.pending_steps):
        raise InvalidCheckpointError("Invalid checkpoint: duplicate entries in 'pending_steps'.")

    overlap = set(checkpoint.completed_steps) & set(checkpoint.pending_steps)
    if overlap:
        raise InvalidCheckpointError(
            f"Invalid checkpoint: steps cannot be both completed and pending: {sorted(overlap)}."
        )

    valid_step_statuses = {
        "pending",
        "awaiting_approval",
        "running",
        "completed",
        "failed",
        "skipped",
        "cancelled",
    }

    # Cross-check checkpoint step lists and failed_step_info against plan_snapshot step statuses
    seen_plan_sids: set[str] = set()
    plan_completed: List[str] = []
    plan_pending: List[str] = []
    plan_failed: List[str] = []
    for step_item in plan_snap["steps"]:
        if not isinstance(step_item, dict) or not step_item.get("step_id"):
            raise InvalidCheckpointError("Invalid checkpoint: malformed step entry in 'plan_snapshot'.")
        sid = str(step_item["step_id"])
        if sid in seen_plan_sids:
            raise InvalidCheckpointError(
                f"Invalid checkpoint: duplicate step_id '{sid}' in 'plan_snapshot'."
            )
        seen_plan_sids.add(sid)
        status = step_item.get("status")
        if status not in valid_step_statuses:
            raise InvalidCheckpointError(
                f"Invalid checkpoint: step '{sid}' in 'plan_snapshot' has invalid status '{status}'."
            )
        if status == "completed":
            plan_completed.append(sid)
        elif status in ("pending", "awaiting_approval", "running", "skipped"):
            plan_pending.append(sid)
        elif status == "failed":
            plan_failed.append(sid)

    if set(checkpoint.completed_steps) != set(plan_completed):
        raise InvalidCheckpointError(
            "Invalid checkpoint: 'completed_steps' does not match 'plan_snapshot' step statuses."
        )
    if set(checkpoint.pending_steps) != set(plan_pending):
        raise InvalidCheckpointError(
            "Invalid checkpoint: 'pending_steps' does not match 'plan_snapshot' step statuses."
        )

    if checkpoint.failed_step_info is not None:
        if not isinstance(checkpoint.failed_step_info, dict) or not checkpoint.failed_step_info.get("step_id"):
            raise InvalidCheckpointError("Invalid checkpoint: malformed 'failed_step_info'.")
        failed_sid = str(checkpoint.failed_step_info["step_id"])
        if failed_sid not in plan_failed:
            raise InvalidCheckpointError(
                f"Invalid checkpoint: 'failed_step_info' references step '{failed_sid}' "
                f"which is not in 'failed' status in 'plan_snapshot'."
            )

    unknown_results = set(checkpoint.step_results.keys()) - seen_plan_sids
    if unknown_results:
        raise InvalidCheckpointError(
            f"Invalid checkpoint: 'step_results' references unknown steps {sorted(unknown_results)}."
        )


def evaluate_step_recoverability(
    step_dict: Dict[str, Any],
    failed_step_info: Optional[Dict[str, Any]] = None,
    default_max_recovery_attempts: int = 3,
) -> Tuple[bool, Optional[str]]:
    """
    Determine whether a failed step is eligible for recovery.
    Returns (True, None) if recoverable, or (False, reason) if permanently failed.
    """
    meta = dict(step_dict.get("metadata") or {})
    if meta.get("permanently_failed") or meta.get("permanent_failure"):
        return False, "Step is marked as permanently failed."

    if meta.get("recoverable") is False:
        return False, "Step is marked non-recoverable."

    result = step_dict.get("result") or {}
    res_meta = dict(result.get("metadata") or {})

    if res_meta.get("permanent_failure") or res_meta.get("recoverable") is False:
        return False, "Step failure result indicates a permanent failure."

    if res_meta.get("rejection") or res_meta.get("approval_status") == "REJECTED":
        return False, "Step failed due to operator rejection and cannot be recovered."

    if res_meta.get("expired") or res_meta.get("approval_status") == "EXPIRED":
        return False, "Step failed due to expired approval and cannot be recovered."

    if res_meta.get("permission_violation"):
        return False, "Step failed due to permission violation and cannot be recovered."

    if res_meta.get("cancelled"):
        return False, "Step was cancelled and cannot be recovered."

    if failed_step_info and failed_step_info.get("permanent_failure"):
        return False, str(failed_step_info.get("reason") or "Failed step is permanently failed.")

    attempts = int(meta.get("recovery_attempts", 0))
    max_attempts = int(meta.get("max_recovery_attempts", default_max_recovery_attempts))
    if attempts >= max_attempts:
        return (
            False,
            f"Recovery limit exhausted for step '{step_dict.get('step_id')}' ({attempts}/{max_attempts} attempts).",
        )

    return True, None


class CheckpointStore:
    """Abstract base interface for workflow checkpoint persistence."""

    def save(self, checkpoint: WorkflowCheckpoint) -> WorkflowCheckpoint:
        raise NotImplementedError

    def get(self, checkpoint_id: str) -> Optional[WorkflowCheckpoint]:
        raise NotImplementedError

    def get_latest(self, workflow_id: str) -> Optional[WorkflowCheckpoint]:
        raise NotImplementedError

    def list_checkpoints(self, workflow_id: str) -> List[WorkflowCheckpoint]:
        raise NotImplementedError


class InMemoryCheckpointStore(CheckpointStore):
    """Thread-safe in-memory checkpoint store (default for mock/local mode)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_id: Dict[str, WorkflowCheckpoint] = {}
        self._by_workflow: Dict[str, List[str]] = {}

    def save(self, checkpoint: WorkflowCheckpoint) -> WorkflowCheckpoint:
        validate_checkpoint(checkpoint, allow_terminal=True)
        stored = WorkflowCheckpoint.from_dict(checkpoint.to_dict())
        with self._lock:
            self._by_id[stored.checkpoint_id] = stored
            wf_list = self._by_workflow.setdefault(stored.workflow_id, [])
            if stored.checkpoint_id not in wf_list:
                wf_list.append(stored.checkpoint_id)
        return WorkflowCheckpoint.from_dict(stored.to_dict())

    def get(self, checkpoint_id: str) -> Optional[WorkflowCheckpoint]:
        with self._lock:
            chk = self._by_id.get(checkpoint_id)
            return WorkflowCheckpoint.from_dict(chk.to_dict()) if chk is not None else None

    def get_latest(self, workflow_id: str) -> Optional[WorkflowCheckpoint]:
        with self._lock:
            ids = self._by_workflow.get(workflow_id, [])
            if not ids:
                return None
            chk = self._by_id.get(ids[-1])
            return WorkflowCheckpoint.from_dict(chk.to_dict()) if chk is not None else None

    def list_checkpoints(self, workflow_id: str) -> List[WorkflowCheckpoint]:
        with self._lock:
            ids = self._by_workflow.get(workflow_id, [])
            return [
                WorkflowCheckpoint.from_dict(self._by_id[cid].to_dict())
                for cid in ids
                if cid in self._by_id
            ]


class FileCheckpointStore(CheckpointStore):
    """JSON file-backed checkpoint store using atomic file replacement."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _index_path(self, workflow_id: str) -> Path:
        safe_wf = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in workflow_id)
        return self.directory / f"{safe_wf}.index.json"

    def _checkpoint_path(self, checkpoint_id: str) -> Path:
        safe_id = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in checkpoint_id)
        return self.directory / f"{safe_id}.checkpoint.json"

    @staticmethod
    def _atomic_write_text(target: Path, content: str) -> None:
        """Write content to a sibling temp file, flush/fsync, and atomically replace target."""
        tmp_path = target.with_name(f".{target.name}.{uuid4().hex[:8]}.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, target)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def _read_index(self, workflow_id: str) -> List[str]:
        idx_path = self._index_path(workflow_id)
        if not idx_path.exists():
            return []
        try:
            data = json.loads(idx_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            raise InvalidCheckpointError(
                f"Corrupted checkpoint index file for workflow '{workflow_id}': {exc}"
            ) from exc
        if not isinstance(data, list) or not all(isinstance(item, str) and item.strip() for item in data):
            raise InvalidCheckpointError(
                f"Malformed checkpoint index for workflow '{workflow_id}': expected list of non-empty checkpoint IDs."
            )
        return data

    def save(self, checkpoint: WorkflowCheckpoint) -> WorkflowCheckpoint:
        validate_checkpoint(checkpoint, allow_terminal=True)
        payload = checkpoint.to_dict()
        with self._lock:
            chk_path = self._checkpoint_path(checkpoint.checkpoint_id)
            self._atomic_write_text(chk_path, json.dumps(payload, indent=2))

            ids = self._read_index(checkpoint.workflow_id)
            if checkpoint.checkpoint_id not in ids:
                ids.append(checkpoint.checkpoint_id)
            idx_path = self._index_path(checkpoint.workflow_id)
            self._atomic_write_text(idx_path, json.dumps(ids, indent=2))
        return WorkflowCheckpoint.from_dict(payload)

    def get(self, checkpoint_id: str) -> Optional[WorkflowCheckpoint]:
        with self._lock:
            chk_path = self._checkpoint_path(checkpoint_id)
            if not chk_path.exists():
                return None
            try:
                data = json.loads(chk_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
                raise InvalidCheckpointError(
                    f"Corrupted checkpoint file for '{checkpoint_id}': {exc}"
                ) from exc
            return WorkflowCheckpoint.from_dict(data)

    def get_latest(self, workflow_id: str) -> Optional[WorkflowCheckpoint]:
        with self._lock:
            ids = self._read_index(workflow_id)
            if not ids:
                return None
            return self.get(ids[-1])

    def list_checkpoints(self, workflow_id: str) -> List[WorkflowCheckpoint]:
        with self._lock:
            ids = self._read_index(workflow_id)
            out: List[WorkflowCheckpoint] = []
            for cid in ids:
                chk = self.get(cid)
                if chk is not None:
                    out.append(chk)
            return out
