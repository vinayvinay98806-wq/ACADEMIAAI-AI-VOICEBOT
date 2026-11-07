"""
Approval Manager for W4 Agentic Workflow.

Manages human-in-the-loop approval workflows, enforcing:
- Explicit approval request creation and tracking.
- Strict state lifecycle: PENDING, APPROVED, REJECTED, EXPIRED.
- Approval expiry logic (time-based TTL or absolute ISO timestamps).
- Target step binding (an approval applies strictly to its intended step).
- Audit trail recording for all approval/rejection/expiry decisions.
- Safe workflow resumption validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

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


class ApprovalManager:
    """
    Coordinates approval lifecycle for consequential actions.
    Ensures safe approval gating, expiry enforcement, and step validation.
    """

    def __init__(self, default_ttl_seconds: Optional[int] = None) -> None:
        self.default_ttl_seconds = default_ttl_seconds
        self._requests: Dict[str, ApprovalRequest] = {}  # step_id -> ApprovalRequest
        self._requests_by_id: Dict[str, ApprovalRequest] = {}  # request_id -> ApprovalRequest
        self._audit_log: List[ApprovalAuditEntry] = []

    @property
    def requests(self) -> Dict[str, ApprovalRequest]:
        """Dictionary of step_id -> ApprovalRequest."""
        return self._requests

    @property
    def audit_log(self) -> List[ApprovalAuditEntry]:
        """Audit trail of all approval events."""
        return list(self._audit_log)

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
        Create a new PENDING approval request bound strictly to workflow_id and step_id.
        """
        if not workflow_id or not str(workflow_id).strip():
            raise ApprovalError("Approval request must have a valid 'workflow_id'.")
        if not step_id or not str(step_id).strip():
            raise ApprovalError("Approval request must have a valid 'step_id'.")
        if not tool_name or not str(tool_name).strip():
            raise ApprovalError("Approval request must have a valid 'tool_name'.")

        request_id = f"apr-{workflow_id}-{step_id}"

        # Calculate expires_at if ttl_seconds provided or default_ttl_seconds configured
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

        self._requests[step_id] = req
        self._requests_by_id[request_id] = req

        # Log creation in audit trail
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

    def get_request(self, step_id: str) -> Optional[ApprovalRequest]:
        """Retrieve approval request for a step, automatically evaluating expiry."""
        req = self._requests.get(step_id)
        if req is not None and req.is_pending():
            self._check_request_expiry(req)
        return req

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
    ) -> ApprovalRequest:
        """
        Explicitly approve a pending request for step_id.
        Rejects if not found, not pending, or already expired.
        """
        req = self._requests.get(step_id)
        if req is None:
            raise ApprovalError(f"No approval request found for step '{step_id}'.")

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
    ) -> ApprovalRequest:
        """
        Explicitly reject a pending request for step_id.
        Rejects if not found, not pending, or already expired.
        """
        req = self._requests.get(step_id)
        if req is None:
            raise ApprovalError(f"No approval request found for step '{step_id}'.")

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
    ) -> ApprovalRequest:
        """
        Explicitly expire a pending approval request.
        """
        req = self._requests.get(step_id)
        if req is None:
            raise ApprovalError(f"No approval request found for step '{step_id}'.")

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
        Scan all pending requests, mark expired requests as EXPIRED.
        Returns list of step_ids that were expired in this sweep.
        """
        expired_step_ids: List[str] = []
        now_iso = _get_utc_now_iso()

        for step_id, req in list(self._requests.items()):
            if req.is_pending() and req.expires_at:
                if now_iso >= req.expires_at:
                    req.expire(reason=f"Approval request TTL expired at {req.expires_at}")
                    expired_step_ids.append(step_id)
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

    def can_execute_step(self, step_id: str) -> Tuple[bool, Optional[str]]:
        """
        Verify whether a consequential step is authorized to execute.
        Returns (True, None) if approved.
        Returns (False, reason) if pending, rejected, expired, or missing.
        """
        req = self.get_request(step_id)
        if req is None:
            return False, f"Step '{step_id}' requires approval but no approval request was created."

        if req.is_pending():
            return False, f"Step '{step_id}' cannot execute: Approval is still pending."
        if req.is_rejected():
            return False, f"Step '{step_id}' cannot execute: Approval was rejected ({req.decision_reason})."
        if req.is_expired():
            return False, f"Step '{step_id}' cannot execute: Approval request expired at {req.expires_at}."
        if req.is_approved():
            return True, None

        return False, f"Step '{step_id}' has unrecognized approval status '{req.status}'."

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
