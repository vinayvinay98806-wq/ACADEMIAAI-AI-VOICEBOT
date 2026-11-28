"""
Idempotency Protection for W4 Agentic Workflow (Week 3).

Provides:
- Deterministic idempotency key generation and explicit key support.
- Thread-safe storage of execution outcomes keyed by idempotency key.
- Strict payload-hash enforcement across both sequential and concurrent callers.
- Bounded concurrent waiter synchronization and safe cleanup after failure/exception.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple

from .schemas import WorkflowResult, _get_utc_now_iso


class IdempotencyError(ValueError):
    """Base exception for idempotency violations or invalid keys."""


class DuplicateExecutionError(IdempotencyError):
    """Raised when strict duplicate rejection is requested for an already-executed key."""


def _canonical_json(data: Any) -> str:
    """Serialize arbitrary JSON-compatible data deterministically."""
    return json.dumps(data if data is not None else {}, sort_keys=True, separators=(",", ":"), default=str)


def compute_payload_hash(payload: Optional[Dict[str, Any]]) -> str:
    """Compute SHA-256 hex digest for an action payload."""
    encoded = _canonical_json(payload or {}).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass
class IdempotencyRecord:
    """Stored execution result bound to an idempotency key."""

    idempotency_key: str
    workflow_id: str
    step_id: str
    tool_name: str
    payload_hash: str
    result: WorkflowResult
    created_at: str = field(default_factory=_get_utc_now_iso)
    hit_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize record to dictionary."""
        return {
            "idempotency_key": self.idempotency_key,
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "payload_hash": self.payload_hash,
            "result": self.result.to_dict(),
            "created_at": self.created_at,
            "hit_count": self.hit_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IdempotencyRecord":
        """Reconstruct IdempotencyRecord from dictionary."""
        return cls(
            idempotency_key=str(data["idempotency_key"]),
            workflow_id=str(data.get("workflow_id", "")),
            step_id=str(data.get("step_id", "")),
            tool_name=str(data.get("tool_name", "")),
            payload_hash=str(data.get("payload_hash", "")),
            result=WorkflowResult.from_dict(data["result"]),
            created_at=str(data.get("created_at", _get_utc_now_iso())),
            hit_count=int(data.get("hit_count", 0)),
        )


class _InFlightExecution:
    """Coordination barrier for concurrent requests sharing an idempotency key."""

    def __init__(self, payload_hash: str) -> None:
        self.payload_hash = payload_hash
        self.event = threading.Event()
        self.result: Optional[WorkflowResult] = None
        self.error: Optional[BaseException] = None


class IdempotencyStore:
    """
    Thread-safe idempotency store preventing duplicate tool execution
    across repeated calls, checkpoint resumes, and concurrent requests.
    """

    def __init__(self, default_wait_timeout_seconds: Optional[float] = 30.0) -> None:
        self._lock = threading.RLock()
        self._records: Dict[str, IdempotencyRecord] = {}
        self._in_flight: Dict[str, _InFlightExecution] = {}
        self.default_wait_timeout_seconds = default_wait_timeout_seconds

    @staticmethod
    def generate_key(
        workflow_id: str,
        step_id: str,
        tool_name: str,
        payload: Optional[Dict[str, Any]] = None,
        explicit_key: Optional[str] = None,
    ) -> str:
        """
        Return explicit_key if provided, otherwise derive a deterministic key
        scoped to (workflow_id, step_id, tool_name, payload).
        """
        if explicit_key is not None:
            cleaned = str(explicit_key).strip()
            if not cleaned:
                raise IdempotencyError("Explicit idempotency_key cannot be empty.")
            return cleaned

        raw = f"{workflow_id}|{step_id}|{tool_name}|{_canonical_json(payload or {})}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
        return f"idem-{workflow_id}-{step_id}-{digest}"

    def has_key(self, idempotency_key: str) -> bool:
        """Check whether a completed execution result is stored for the key."""
        with self._lock:
            return idempotency_key in self._records

    def get_record(self, idempotency_key: str) -> Optional[IdempotencyRecord]:
        """Return stored IdempotencyRecord if present."""
        with self._lock:
            return self._records.get(idempotency_key)

    def get_result(self, idempotency_key: str) -> Optional[WorkflowResult]:
        """Return a copy of the stored WorkflowResult if present."""
        with self._lock:
            rec = self._records.get(idempotency_key)
            if rec is None:
                return None
            return WorkflowResult.from_dict(rec.result.to_dict())

    def store_result(
        self,
        idempotency_key: str,
        result: WorkflowResult,
        workflow_id: str = "",
        step_id: str = "",
        tool_name: str = "",
        payload: Optional[Dict[str, Any]] = None,
    ) -> IdempotencyRecord:
        """Explicitly store a completed execution result for an idempotency key."""
        if not idempotency_key or not str(idempotency_key).strip():
            raise IdempotencyError("idempotency_key must be a non-empty string.")
        with self._lock:
            record = IdempotencyRecord(
                idempotency_key=idempotency_key,
                workflow_id=workflow_id,
                step_id=step_id,
                tool_name=tool_name,
                payload_hash=compute_payload_hash(payload),
                result=WorkflowResult.from_dict(result.to_dict()),
            )
            self._records[idempotency_key] = record
            return record

    def execute(
        self,
        idempotency_key: str,
        action: Callable[[], WorkflowResult],
        workflow_id: str = "",
        step_id: str = "",
        tool_name: str = "",
        payload: Optional[Dict[str, Any]] = None,
        cache_failures: bool = False,
        raise_on_duplicate: bool = False,
        wait_timeout_seconds: Optional[float] = None,
    ) -> Tuple[WorkflowResult, bool]:
        """
        Execute `action` at most once for a given `idempotency_key` and matching payload.

        Returns:
            (WorkflowResult, is_replayed): `is_replayed` is True when the result
            came from a previously completed or concurrent in-flight execution.
        """
        if not idempotency_key or not str(idempotency_key).strip():
            raise IdempotencyError("idempotency_key must be a non-empty string.")

        payload_hash = compute_payload_hash(payload)
        effective_wait = (
            wait_timeout_seconds
            if wait_timeout_seconds is not None
            else self.default_wait_timeout_seconds
        )
        flight: Optional[_InFlightExecution] = None
        is_leader = False

        with self._lock:
            existing = self._records.get(idempotency_key)
            if existing is not None:
                if existing.payload_hash != payload_hash:
                    raise IdempotencyError(
                        f"Idempotency key '{idempotency_key}' was already used with a different payload."
                    )
                if raise_on_duplicate:
                    raise DuplicateExecutionError(
                        f"Duplicate execution rejected for idempotency key '{idempotency_key}'."
                    )
                existing.hit_count += 1
                replayed = WorkflowResult.from_dict(existing.result.to_dict())
                replayed.metadata["idempotency_key"] = idempotency_key
                replayed.metadata["idempotency_replay"] = True
                return replayed, True

            flight = self._in_flight.get(idempotency_key)
            if flight is not None:
                if flight.payload_hash != payload_hash:
                    raise IdempotencyError(
                        f"Idempotency key '{idempotency_key}' is currently in flight with a different payload."
                    )
            else:
                flight = _InFlightExecution(payload_hash=payload_hash)
                self._in_flight[idempotency_key] = flight
                is_leader = True

        if not is_leader:
            completed = flight.event.wait(timeout=effective_wait)
            if not completed:
                raise IdempotencyError(
                    f"Timed out waiting for concurrent execution of idempotency key '{idempotency_key}'."
                )
            if raise_on_duplicate:
                raise DuplicateExecutionError(
                    f"Concurrent duplicate execution rejected for idempotency key '{idempotency_key}'."
                )
            with self._lock:
                existing = self._records.get(idempotency_key)
                if existing is not None:
                    if existing.payload_hash != payload_hash:
                        raise IdempotencyError(
                            f"Idempotency key '{idempotency_key}' completed with a different payload."
                        )
                    existing.hit_count += 1
                    replayed = WorkflowResult.from_dict(existing.result.to_dict())
                    replayed.metadata["idempotency_key"] = idempotency_key
                    replayed.metadata["idempotency_replay"] = True
                    return replayed, True
            if flight.error is not None:
                raise flight.error
            if flight.result is not None:
                replayed = WorkflowResult.from_dict(flight.result.to_dict())
                replayed.metadata["idempotency_key"] = idempotency_key
                replayed.metadata["idempotency_replay"] = True
                return replayed, True
            return WorkflowResult.fail("Concurrent idempotent execution produced no result."), True

        # Leader executes the underlying action outside the global lock
        try:
            result = action()
            flight.result = result
            if result.success or cache_failures:
                with self._lock:
                    stored = WorkflowResult.from_dict(result.to_dict())
                    stored.metadata.setdefault("idempotency_key", idempotency_key)
                    self._records[idempotency_key] = IdempotencyRecord(
                        idempotency_key=idempotency_key,
                        workflow_id=workflow_id,
                        step_id=step_id,
                        tool_name=tool_name,
                        payload_hash=payload_hash,
                        result=stored,
                    )
            return result, False
        except BaseException as exc:
            flight.error = exc
            raise
        finally:
            with self._lock:
                if self._in_flight.get(idempotency_key) is flight:
                    self._in_flight.pop(idempotency_key, None)
            flight.event.set()

    def export_state(self) -> Dict[str, Any]:
        """Export stored idempotency records for checkpoint persistence."""
        with self._lock:
            return {
                "keys": list(self._records.keys()),
                "records": {k: rec.to_dict() for k, rec in self._records.items()},
            }

    def load_state(self, data: Dict[str, Any]) -> None:
        """Restore stored idempotency records from a checkpoint snapshot."""
        if not data:
            return
        records_data = data.get("records", {})
        if not isinstance(records_data, dict):
            raise IdempotencyError("Invalid idempotency state snapshot: 'records' must be a dict.")
        with self._lock:
            for key, rec_dict in records_data.items():
                rec = IdempotencyRecord.from_dict(rec_dict)
                if key not in self._records:
                    self._records[key] = rec
