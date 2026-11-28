"""
Approval Manager for W4 Agentic Workflow.

Manages human-in-the-loop approval workflows, enforcing:
- Explicit approval request creation and tracking scoped by (workflow_id, step_id).
- Strict state lifecycle: PENDING, APPROVED, REJECTED, EXPIRED.
- Approval expiry logic (time-based TTL or absolute ISO timestamps).
- Target workflow and step binding (an approval applies strictly to its intended workflow and step).
- Audit trail recording for all approval/rejection/expiry decisions.
- Safe workflow resumption validation and checkpoint snapshot support.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from .schemas import ApprovalRequest, _get_utc_now_iso


class ApprovalError(ValueError):
    """Exception raised for invalid approval operations."""
    pass


@dataclass(frozen=True)
class ApprovalAuditEntry:
    """Immutable audit record documenting an approval decision or transition."""
    request_id: str
    workflow_id: str
    step_id: str
    tool_name: str
    decision: str  # REQUESTED, APPROVED, REJECTED, EXPIRED
    decided_by: str
    decided_at: str
    reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert entry to dictionary."""
        return {
            "request_id": self.request_id,
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "decision": self.decision,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at,
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }


class _ScopedRequestsProxy(dict):
    """
    Backward-compatible dict proxy for `ApprovalManager.requests`.
    Tracks direct external writes (such as test injections) as manual overrides
    while keeping internal multi-workflow writes isolated by `(workflow_id, step_id)`.
    """

    def __init__(self, manager: "ApprovalManager") -> None:
        super().__init__()
        self._manager = manager

    def _internal_set(self, step_id: str, req: ApprovalRequest) -> None:
        super().__setitem__(step_id, req)

    def _internal_clear(self) -> None:
        super().clear()

    def __setitem__(self, step_id: str, req: ApprovalRequest) -> None:
        super().__setitem__(step_id, req)
        self._manager._manual_overrides.add(step_id)


class ApprovalManager:
    """
    Coordinates approval lifecycle for consequential actions.
    Ensures safe approval gating, expiry enforcement, and cross-workflow step isolation.
    """

    def __init__(self, default_ttl_seconds: Optional[int] = None) -> None:
        self.default_ttl_seconds = default_ttl_seconds
        self._requests_by_key: Dict[Tuple[str, str], ApprovalRequest] = {}  # (workflow_id, step_id) -> ApprovalRequest
        self._requests: _ScopedRequestsProxy = _ScopedRequestsProxy(self)  # legacy step_id view
        self._requests_by_id: Dict[str, ApprovalRequest] = {}  # request_id -> ApprovalRequest
        self._manual_overrides: Set[str] = set()
        self._audit_log: List[ApprovalAuditEntry] = []

    @property
    def requests(self) -> Dict[str, ApprovalRequest]:
        """Dictionary view of step_id -> ApprovalRequest (backward compatible)."""
        return self._requests

    @property
    def audit_log(self) -> List[ApprovalAuditEntry]:
        """Audit trail of all approval events."""
        return list(self._audit_log)

    def _resolve_request(
        self,
        step_id: str,
        workflow_id: Optional[str] = None,
    ) -> Optional[ApprovalRequest]:
        """Resolve an ApprovalRequest scoped by (workflow_id, step_id) safely."""
        if step_id in self._manual_overrides:
            return self._requests.get(step_id)

        if workflow_id is not None:
            return self._requests_by_key.get((workflow_id, step_id))

        matches = [req for (wf_id, sid), req in self._requests_by_key.items() if sid == step_id]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ApprovalError(
                f"Ambiguous approval lookup for step '{step_id}' across multiple workflows; "
                f"explicit 'workflow_id' is required."
            )
        return self._requests.get(step_id)

    def create_request(
        self,
        workflow_id: str,
        step_id: str,
        tool_name: str,
        action_description: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        expires_at: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ApprovalRequest:
        """
        Create a new PENDING approval request bound strictly to (workflow_id, step_id).
        """
        if not workflow_id or not str(workflow_id).strip():
            raise ApprovalError("Approval request must have a valid 'workflow_id'.")
        if not step_id or not str(step_id).strip():
            raise ApprovalError("Approval request must have a valid 'step_id'.")
        if not tool_name or not str(tool_name).strip():
            raise ApprovalError("Approval request must have a valid 'tool_name'.")

        request_id = f"apr-{workflow_id}-{step_id}"

        effective_ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        calculated_expires_at = expires_at
        if calculated_expires_at is None and effective_ttl is not None:
            now = datetime.now(timezone.utc)
            expiry_dt = now + timedelta(seconds=effective_ttl)
            calculated_expires_at = expiry_dt.isoformat()

        req = ApprovalRequest(
            request_id=request_id,
            workflow_id=workflow_id,
            step_id=step_id,
            tool_name=tool_name,
            action_description=action_description or f"Approval required for '{tool_name}'",
            status="PENDING",
            requested_at=_get_utc_now_iso(),
            expires_at=calculated_expires_at,
        )

        self._manual_overrides.discard(step_id)
        self._requests_by_key[(workflow_id, step_id)] = req
        self._requests._internal_set(step_id, req)
        self._requests_by_id[request_id] = req

        self._audit_log.append(
            ApprovalAuditEntry(
                request_id=req.request_id,
                workflow_id=req.workflow_id,
                step_id=req.step_id,
                tool_name=req.tool_name,
                decision="REQUESTED",
                decided_by="system",
                decided_at=req.requested_at,
                reason=action_description,
                metadata=metadata or {},
            )
        )

        return req

    def get_request(self, step_id: str, workflow_id: Optional[str] = None) -> Optional[ApprovalRequest]:
        """Retrieve approval request for (workflow_id, step_id), evaluating expiry."""
        req = self._resolve_request(step_id, workflow_id=workflow_id)
        if req is not None and req.is_pending():
            self._check_request_expiry(req)
        return req

    def get_requests_for_workflow(self, workflow_id: str) -> Dict[str, ApprovalRequest]:
        """Return step_id -> ApprovalRequest strictly scoped to `workflow_id`."""
        scoped: Dict[str, ApprovalRequest] = {}
        for (wf_id, step_id), req in self._requests_by_key.items():
            if wf_id == workflow_id:
                if req.is_pending():
                    self._check_request_expiry(req)
                scoped[step_id] = req
        for step_id in self._manual_overrides:
            req = self._requests.get(step_id)
            if req is not None and req.workflow_id == workflow_id:
                if req.is_pending():
                    self._check_request_expiry(req)
                scoped[step_id] = req
        return scoped

    def get_request_by_id(self, request_id: str) -> Optional[ApprovalRequest]:
        """Retrieve approval request by request_id, automatically evaluating expiry."""
        req = self._requests_by_id.get(request_id)
        if req is not None and req.is_pending():
            self._check_request_expiry(req)
        return req

    def approve(
        self,
        step_id: str,
        reason: Optional[str] = None,
        approver: str = "operator",
        workflow_id: Optional[str] = None,
    ) -> ApprovalRequest:
        """
        Explicitly approve a pending request for (workflow_id, step_id).
        Rejects if not found, workflow_id mismatches, not pending, or already expired.
        """
        req = self._resolve_request(step_id, workflow_id=workflow_id)
        if req is None:
            raise ApprovalError(f"No approval request found for step '{step_id}'.")
        if workflow_id is not None and req.workflow_id != workflow_id:
            raise ApprovalError(
                f"Approval binding mismatch: request '{req.request_id}' belongs to workflow "
                f"'{req.workflow_id}', not '{workflow_id}'."
            )

        self._check_request_expiry(req)

        if req.is_expired():
            raise ApprovalError(
                f"Cannot approve request for step '{step_id}': Request expired at {req.expires_at}."
            )
        if not req.is_pending():
            raise ApprovalError(
                f"Cannot approve request for step '{step_id}': Request is already {req.status}."
            )

        req.approve(reason=reason or f"Approved by {approver}")

        self._audit_log.append(
            ApprovalAuditEntry(
                request_id=req.request_id,
                workflow_id=req.workflow_id,
                step_id=req.step_id,
                tool_name=req.tool_name,
                decision="APPROVED",
                decided_by=approver,
                decided_at=req.decided_at or _get_utc_now_iso(),
                reason=req.decision_reason,
            )
        )
        return req

    def reject(
        self,
        step_id: str,
        reason: Optional[str] = None,
        approver: str = "operator",
        workflow_id: Optional[str] = None,
    ) -> ApprovalRequest:
        """
        Explicitly reject a pending request for (workflow_id, step_id).
        Rejects if not found, workflow_id mismatches, not pending, or already expired.
        """
        req = self._resolve_request(step_id, workflow_id=workflow_id)
        if req is None:
            raise ApprovalError(f"No approval request found for step '{step_id}'.")
        if workflow_id is not None and req.workflow_id != workflow_id:
            raise ApprovalError(
                f"Approval binding mismatch: request '{req.request_id}' belongs to workflow "
                f"'{req.workflow_id}', not '{workflow_id}'."
            )

        self._check_request_expiry(req)

        if req.is_expired():
            raise ApprovalError(
                f"Cannot reject request for step '{step_id}': Request is already expired."
            )
        if not req.is_pending():
            raise ApprovalError(
                f"Cannot reject request for step '{step_id}': Request is already {req.status}."
            )

        req.reject(reason=reason or f"Rejected by {approver}")

        self._audit_log.append(
            ApprovalAuditEntry(
                request_id=req.request_id,
                workflow_id=req.workflow_id,
                step_id=req.step_id,
                tool_name=req.tool_name,
                decision="REJECTED",
                decided_by=approver,
                decided_at=req.decided_at or _get_utc_now_iso(),
                reason=req.decision_reason,
            )
        )
        return req

    def expire(
        self,
        step_id: str,
        reason: Optional[str] = None,
        workflow_id: Optional[str] = None,
    ) -> ApprovalRequest:
        """Explicitly expire a pending approval request."""
        req = self._resolve_request(step_id, workflow_id=workflow_id)
        if req is None:
            raise ApprovalError(f"No approval request found for step '{step_id}'.")
        if workflow_id is not None and req.workflow_id != workflow_id:
            raise ApprovalError(
                f"Approval binding mismatch: request '{req.request_id}' belongs to workflow "
                f"'{req.workflow_id}', not '{workflow_id}'."
            )

        if not req.is_pending():
            raise ApprovalError(
                f"Cannot expire request for step '{step_id}': Request is already {req.status}."
            )

        req.expire(reason=reason or "Explicitly expired")

        self._audit_log.append(
            ApprovalAuditEntry(
                request_id=req.request_id,
                workflow_id=req.workflow_id,
                step_id=req.step_id,
                tool_name=req.tool_name,
                decision="EXPIRED",
                decided_by="system",
                decided_at=req.decided_at or _get_utc_now_iso(),
                reason=req.decision_reason,
            )
        )
        return req

    def check_expiries(self) -> List[str]:
        """
        Scan all pending requests across all workflows, mark expired requests as EXPIRED.
        Returns list of step_ids that were expired in this sweep.
        """
        expired_step_ids: List[str] = []
        now_iso = _get_utc_now_iso()

        seen_ids: Set[str] = set()
        all_reqs = list(self._requests_by_key.values()) + [
            self._requests[sid] for sid in self._manual_overrides if sid in self._requests
        ]
        for req in all_reqs:
            if req.request_id in seen_ids:
                continue
            seen_ids.add(req.request_id)
            if req.is_pending() and req.expires_at:
                if now_iso >= req.expires_at:
                    req.expire(reason=f"Approval request TTL expired at {req.expires_at}")
                    expired_step_ids.append(req.step_id)
                    self._audit_log.append(
                        ApprovalAuditEntry(
                            request_id=req.request_id,
                            workflow_id=req.workflow_id,
                            step_id=req.step_id,
                            tool_name=req.tool_name,
                            decision="EXPIRED",
                            decided_by="system_expiry_sweep",
                            decided_at=req.decided_at or now_iso,
                            reason=req.decision_reason,
                        )
                    )
        return expired_step_ids

    def can_execute_step(
        self,
        step_id: str,
        workflow_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        now_iso: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Verify whether a consequential step is authorized to execute.
        Enforces target workflow_id, step_id, and tool_name binding plus expiry.
        Returns (True, None) if approved.
        Returns (False, reason) if pending, rejected, expired, mismatched, or missing.
        """
        req = self.get_request(step_id, workflow_id=workflow_id)
        if req is None:
            return False, f"Step '{step_id}' requires approval but no approval request was created."

        if workflow_id is not None and req.workflow_id != workflow_id:
            return (
                False,
                f"Step '{step_id}' approval binding mismatch: bound to workflow '{req.workflow_id}', not '{workflow_id}'.",
            )
        if req.step_id != step_id:
            return (
                False,
                f"Approval step binding mismatch: bound to '{req.step_id}', not '{step_id}'.",
            )
        if tool_name is not None and req.tool_name != tool_name:
            return (
                False,
                f"Step '{step_id}' approval tool mismatch: bound to '{req.tool_name}', not '{tool_name}'.",
            )

        current_ts = now_iso or _get_utc_now_iso()
        if req.expires_at and current_ts >= req.expires_at:
            if req.is_pending():
                self._check_request_expiry(req)
            return False, f"Step '{step_id}' cannot execute: Approval request expired at {req.expires_at}."

        if req.is_pending():
            return False, f"Step '{step_id}' cannot execute: Approval is still pending."
        if req.is_rejected():
            return False, f"Step '{step_id}' cannot execute: Approval was rejected ({req.decision_reason})."
        if req.is_expired():
            return False, f"Step '{step_id}' cannot execute: Approval request expired at {req.expires_at}."
        if req.is_approved():
            return True, None

        return False, f"Step '{step_id}' has unrecognized approval status '{req.status}'."

    def export_state(self) -> Dict[str, Any]:
        """Serialize all scoped approval requests and audit log for checkpoint persistence."""
        return {
            "requests_list": [req.to_dict() for req in self._requests_by_key.values()],
            "audit_log": [entry.to_dict() for entry in self._audit_log],
        }

    def load_state(self, data: Dict[str, Any]) -> None:
        """Restore approval requests and audit log from a checkpoint snapshot."""
        if not data:
            return
        self._requests_by_key.clear()
        self._requests._internal_clear()
        self._requests_by_id.clear()
        self._manual_overrides.clear()

        if "requests_list" in data:
            for req_dict in data.get("requests_list") or []:
                req = ApprovalRequest.from_dict(req_dict)
                self._requests_by_key[(req.workflow_id, req.step_id)] = req
                self._requests._internal_set(req.step_id, req)
                self._requests_by_id[req.request_id] = req
        else:
            for step_id, req_dict in (data.get("requests") or {}).items():
                req = ApprovalRequest.from_dict(req_dict)
                self._requests_by_key[(req.workflow_id, step_id)] = req
                self._requests._internal_set(step_id, req)
                self._requests_by_id[req.request_id] = req

        restored_log: List[ApprovalAuditEntry] = []
        for entry_dict in data.get("audit_log") or []:
            restored_log.append(
                ApprovalAuditEntry(
                    request_id=str(entry_dict["request_id"]),
                    workflow_id=str(entry_dict["workflow_id"]),
                    step_id=str(entry_dict["step_id"]),
                    tool_name=str(entry_dict["tool_name"]),
                    decision=str(entry_dict["decision"]),
                    decided_by=str(entry_dict["decided_by"]),
                    decided_at=str(entry_dict["decided_at"]),
                    reason=entry_dict.get("reason"),
                    metadata=dict(entry_dict.get("metadata") or {}),
                )
            )
        self._audit_log = restored_log

    def _check_request_expiry(self, req: ApprovalRequest) -> None:
        """Internal helper to check and update single request expiry."""
        if req.status == "PENDING" and req.expires_at:
            now_iso = _get_utc_now_iso()
            if now_iso >= req.expires_at:
                req.expire(reason=f"Approval request TTL expired at {req.expires_at}")
                self._audit_log.append(
                    ApprovalAuditEntry(
                        request_id=req.request_id,
                        workflow_id=req.workflow_id,
                        step_id=req.step_id,
                        tool_name=req.tool_name,
                        decision="EXPIRED",
                        decided_by="system",
                        decided_at=req.decided_at or now_iso,
                        reason=req.decision_reason,
                    )
                )
