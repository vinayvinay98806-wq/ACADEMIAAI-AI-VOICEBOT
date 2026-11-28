"""
Integration Adapters for W4 Agentic Workflow (Week 3).

Provides clearly isolated, documented adapters for external workers whose codebases
live on separate branches and are not present in the W4 workspace:
1. WorkflowProposalAdapter (Worker 3 Reasoning `WorkflowProposals` integration)
2. BackendApprovalClient / MockBackendApprovalClient / HttpBackendApprovalClient
   (Worker 5 Backend approval-state synchronization; defaults to mock mode)
3. ApprovalUIService (Worker 6 UI approval/rejection API & event contract)
"""

from __future__ import annotations

import json
import math
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .mock_tools import ToolRegistry, create_default_registry
from .schemas import ApprovalRequest, WorkflowPlan, WorkflowStep, _get_utc_now_iso
from .validator import PlanValidationError, PlanValidator


# ---------------------------------------------------------------------------
# 1. Worker 3 Reasoning Proposal Adapter (`WorkflowProposals` contract)
# ---------------------------------------------------------------------------

class ProposalValidationError(PlanValidationError):
    """Raised when an incoming reasoning proposal fails validation or conversion."""


def _coerce_mapping(obj: Any) -> Dict[str, Any]:
    """Convert a dict or duck-typed model (dataclass / Pydantic / custom) into a dict."""
    if isinstance(obj, dict):
        return dict(obj)
    for attr in ("model_dump", "to_dict", "dict"):
        method = getattr(obj, attr, None)
        if callable(method):
            try:
                dumped = method()
            except (ValueError, TypeError, AttributeError) as exc:
                raise ProposalValidationError(
                    f"Failed to serialize proposal payload via '{attr}': {exc}"
                ) from exc
            if isinstance(dumped, dict):
                return dumped
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in vars(obj).items() if not k.startswith("_")}
    raise ProposalValidationError(
        f"Unsupported proposal payload type '{type(obj).__name__}'. Expected dict or contract model."
    )


class WorkflowProposalAdapter:
    """
    Isolated adapter converting Worker 3 `WorkflowProposals` payloads into
    validated W4 `WorkflowPlan` contracts.

    NOTE: Worker 3's reasoning codebase (`origin/feature/w3-context-reasoning`) is not
    present in this W4 workspace. This adapter accepts dictionary payloads or duck-typed
    proposal objects matching the `WorkflowProposals` contract without inventing duplicate
    workflow schemas.
    """

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        validator: Optional[PlanValidator] = None,
    ) -> None:
        self.registry = registry if registry is not None else create_default_registry()
        self.validator = validator if validator is not None else PlanValidator(self.registry)

    def validate_and_convert(
        self,
        proposal: Any,
        authorized_permissions: Optional[Set[str] | List[str]] = None,
        workflow_id_override: Optional[str] = None,
        proposals_batch_id: Optional[str] = None,
    ) -> WorkflowPlan:
        """
        Validate an incoming reasoning proposal and convert it into a WorkflowPlan.
        Preserves proposal_id, batch reference, and workflow_id.
        """
        raw = _coerce_mapping(proposal)

        if raw.get("supported") is False or raw.get("status") == "unsupported":
            raise ProposalValidationError("Reasoning proposal is marked unsupported.")

        proposal_id = raw.get("proposal_id") or raw.get("id")
        if isinstance(proposal_id, (dict, list, bool)) or not proposal_id or not str(proposal_id).strip():
            raise ProposalValidationError("Reasoning proposal must include a non-empty 'proposal_id'.")
        proposal_id = str(proposal_id).strip()

        goal = raw.get("goal") or raw.get("intent") or raw.get("summary") or raw.get("title")
        if isinstance(goal, (dict, list, bool)) or not goal or not str(goal).strip():
            raise ProposalValidationError(
                f"Proposal '{proposal_id}' must include a non-empty 'goal' (or 'intent'/'summary')."
            )
        goal = str(goal).strip()

        raw_steps = raw.get("steps")
        if raw_steps is None:
            raw_steps = raw.get("proposed_steps")
        if raw_steps is None:
            raw_steps = raw.get("actions")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ProposalValidationError(
                f"Proposal '{proposal_id}' must contain a non-empty list of steps."
            )

        workflow_id = (
            str(workflow_id_override).strip()
            if workflow_id_override
            else str(raw.get("workflow_id") or f"wf-{proposal_id}").strip()
        )
        if not workflow_id:
            raise ProposalValidationError(f"Proposal '{proposal_id}' produced an empty workflow_id.")

        steps: List[WorkflowStep] = []
        for idx, item in enumerate(raw_steps):
            step_raw = _coerce_mapping(item)
            step_id = step_raw.get("step_id") or step_raw.get("id") or f"step_{idx + 1}"
            if isinstance(step_id, (dict, list, bool)):
                raise ProposalValidationError(
                    f"Proposal '{proposal_id}' step at index {idx} has invalid 'step_id' type."
                )
            step_id = str(step_id).strip()
            tool_name = step_raw.get("tool_name") or step_raw.get("tool") or step_raw.get("action")
            if isinstance(tool_name, (dict, list, bool)) or not tool_name or not str(tool_name).strip():
                raise ProposalValidationError(
                    f"Proposal '{proposal_id}' step '{step_id}' must specify 'tool_name' (or 'tool'/'action')."
                )
            tool_name = str(tool_name).strip()

            # Resolve trusted ToolSpec from registry; reject unsupported/unregistered tools
            if not self.registry.has_tool(tool_name):
                raise ProposalValidationError(
                    f"Proposal '{proposal_id}' step '{step_id}' references unsupported or unregistered tool '{tool_name}'."
                )
            tool_spec = self.registry.get_spec(tool_name)

            payload = (
                step_raw.get("input_payload")
                if step_raw.get("input_payload") is not None
                else step_raw.get("parameters")
                if step_raw.get("parameters") is not None
                else step_raw.get("arguments")
                if step_raw.get("arguments") is not None
                else step_raw.get("payload")
                if step_raw.get("payload") is not None
                else {}
            )
            if not isinstance(payload, dict):
                raise ProposalValidationError(
                    f"Proposal '{proposal_id}' step '{step_id}' payload must be a dict."
                )

            deps = step_raw.get("dependencies")
            if deps is None:
                deps = step_raw.get("depends_on") or []
            if not isinstance(deps, list) or not all(isinstance(d, str) and d.strip() for d in deps):
                raise ProposalValidationError(
                    f"Proposal '{proposal_id}' step '{step_id}' dependencies must be a list of non-empty strings."
                )

            raw_step_meta = step_raw.get("metadata")
            if raw_step_meta is not None and not isinstance(raw_step_meta, dict):
                raise ProposalValidationError(
                    f"Proposal '{proposal_id}' step '{step_id}' metadata must be a dict."
                )
            step_meta = dict(raw_step_meta or {})
            step_meta["proposal_id"] = proposal_id
            if step_raw.get("idempotency_key"):
                step_meta["idempotency_key"] = str(step_raw["idempotency_key"])
            if step_raw.get("rationale"):
                step_meta["rationale"] = str(step_raw["rationale"])

            # Security enforcement: proposals NEVER downgrade consequentiality or escalate idempotency
            raw_is_conseq = step_raw.get("is_consequential")
            raw_req_app = step_raw.get("requires_approval")
            if raw_is_conseq is not None and not isinstance(raw_is_conseq, bool):
                raise ProposalValidationError(
                    f"Proposal '{proposal_id}' step '{step_id}' is_consequential flag must be a bool."
                )
            if raw_req_app is not None and not isinstance(raw_req_app, bool):
                raise ProposalValidationError(
                    f"Proposal '{proposal_id}' step '{step_id}' requires_approval flag must be a bool."
                )
            proposed_conseq = raw_is_conseq if raw_is_conseq is not None else raw_req_app

            if tool_spec.is_consequential:
                effective_consequential: Optional[bool] = True
                if raw_is_conseq is False or raw_req_app is False:
                    step_meta["downgrade_attempt_blocked"] = True
            else:
                effective_consequential = proposed_conseq

            proposed_idempotent = step_raw.get("is_idempotent")
            if proposed_idempotent is not None and not isinstance(proposed_idempotent, bool):
                raise ProposalValidationError(
                    f"Proposal '{proposal_id}' step '{step_id}' is_idempotent must be a bool."
                )
            effective_idempotent = False if not tool_spec.is_idempotent else proposed_idempotent

            raw_retries = step_raw.get("max_retries", 0)
            if isinstance(raw_retries, bool) or not isinstance(raw_retries, int) or raw_retries < 0:
                raise ProposalValidationError(
                    f"Proposal '{proposal_id}' step '{step_id}' max_retries must be a non-negative integer."
                )

            raw_step_timeout = step_raw.get("timeout_seconds")
            if raw_step_timeout is not None and (
                isinstance(raw_step_timeout, bool)
                or not isinstance(raw_step_timeout, (int, float))
                or not math.isfinite(float(raw_step_timeout))
                or raw_step_timeout <= 0
            ):
                raise ProposalValidationError(
                    f"Proposal '{proposal_id}' step '{step_id}' timeout_seconds must be a positive finite number."
                )

            steps.append(
                WorkflowStep(
                    step_id=step_id,
                    tool_name=tool_name,
                    input_payload=dict(payload),
                    dependencies=[str(d) for d in deps],
                    is_consequential=effective_consequential,
                    metadata=step_meta,
                    max_retries=raw_retries,
                    timeout_seconds=float(raw_step_timeout) if raw_step_timeout is not None else None,
                    is_idempotent=effective_idempotent,
                )
            )

        raw_plan_meta = raw.get("metadata")
        if raw_plan_meta is not None and not isinstance(raw_plan_meta, dict):
            raise ProposalValidationError(f"Proposal '{proposal_id}' metadata must be a dict.")
        plan_meta = dict(raw_plan_meta or {})
        plan_meta["proposal_id"] = proposal_id
        plan_meta["source"] = str(raw.get("source") or "reasoning_worker_proposal")
        if proposals_batch_id or raw.get("proposals_batch_id"):
            plan_meta["proposals_batch_id"] = str(proposals_batch_id or raw.get("proposals_batch_id"))
        if raw.get("confidence") is not None:
            plan_meta["confidence"] = raw.get("confidence")

        raw_wf_timeout = raw.get("timeout_seconds")
        if raw_wf_timeout is not None and (
            isinstance(raw_wf_timeout, bool)
            or not isinstance(raw_wf_timeout, (int, float))
            or not math.isfinite(float(raw_wf_timeout))
            or raw_wf_timeout <= 0
        ):
            raise ProposalValidationError(
                f"Proposal '{proposal_id}' timeout_seconds must be a positive finite number."
            )

        plan = WorkflowPlan(
            workflow_id=workflow_id,
            goal=goal,
            steps=steps,
            metadata=plan_meta,
            timeout_seconds=float(raw_wf_timeout) if raw_wf_timeout is not None else None,
        )

        # Enforce W4 static plan validation (tools, schemas, DAG, order, permissions)
        try:
            self.validator.validate(plan, authorized_permissions=authorized_permissions)
        except PlanValidationError as exc:
            raise ProposalValidationError(str(exc)) from exc
        return plan

    def convert_workflow_proposals(
        self,
        workflow_proposals: Any,
        authorized_permissions: Optional[Set[str] | List[str]] = None,
    ) -> List[WorkflowPlan]:
        """
        Validate and convert a `WorkflowProposals` container (or list of proposals)
        into a list of validated `WorkflowPlan` instances.
        """
        batch_id: Optional[str] = None
        if isinstance(workflow_proposals, list):
            items = workflow_proposals
        else:
            raw = _coerce_mapping(workflow_proposals)
            batch_id = raw.get("batch_id") or raw.get("proposals_id") or raw.get("request_id")
            items = raw.get("proposals")
            if items is None and "proposal_id" in raw:
                items = [raw]

        if not isinstance(items, list) or not items:
            raise ProposalValidationError("WorkflowProposals payload must contain at least one proposal.")

        return [
            self.validate_and_convert(
                item,
                authorized_permissions=authorized_permissions,
                proposals_batch_id=str(batch_id) if batch_id else None,
            )
            for item in items
        ]


# ---------------------------------------------------------------------------
# 2. Worker 5 Backend Approval-State Adapter (Mock Mode Default)
# ---------------------------------------------------------------------------

class BackendUnavailableError(RuntimeError):
    """Raised when the authoritative backend approval service is unreachable or failing."""


@dataclass
class BackendApprovalState:
    """Authoritative approval state representation returned by the backend service."""

    request_id: str
    workflow_id: str
    step_id: str
    status: str  # PENDING, APPROVED, REJECTED, EXPIRED
    tool_name: Optional[str] = None
    decided_by: Optional[str] = None
    decided_at: Optional[str] = None
    expires_at: Optional[str] = None
    decision_reason: Optional[str] = None
    version: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "status": self.status,
            "tool_name": self.tool_name,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at,
            "expires_at": self.expires_at,
            "decision_reason": self.decision_reason,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BackendApprovalState":
        status = str(data.get("status", "PENDING")).upper()
        if status not in {"PENDING", "APPROVED", "REJECTED", "EXPIRED"}:
            raise ValueError(f"Unsupported backend approval status '{status}'.")
        return cls(
            request_id=str(data["request_id"]),
            workflow_id=str(data["workflow_id"]),
            step_id=str(data["step_id"]),
            status=status,
            tool_name=data.get("tool_name"),
            decided_by=data.get("decided_by"),
            decided_at=data.get("decided_at"),
            expires_at=data.get("expires_at"),
            decision_reason=data.get("decision_reason"),
            version=int(data.get("version", 1)),
        )


class BackendApprovalClient:
    """Abstract interface for retrieving/updating authoritative backend approval state."""

    mode: str = "abstract"

    def publish_request(self, req: ApprovalRequest) -> BackendApprovalState:
        raise NotImplementedError

    def get_approval_state(
        self,
        workflow_id: str,
        step_id: str,
        request_id: Optional[str] = None,
    ) -> Optional[BackendApprovalState]:
        raise NotImplementedError

    def submit_decision(
        self,
        workflow_id: str,
        step_id: str,
        request_id: str,
        approved: bool,
        reason: Optional[str] = None,
        approver: str = "operator",
    ) -> BackendApprovalState:
        raise NotImplementedError


class MockBackendApprovalClient(BackendApprovalClient):
    """
    Default mock-mode backend approval client.
    Simulates authoritative backend persistence, expiry checks, availability failures,
    and conflict protection without requiring Worker 5's live backend server.
    """

    mode: str = "mock"

    def __init__(self, available: bool = True) -> None:
        self._lock = threading.RLock()
        self._available = available
        self._states: Dict[tuple[str, str], BackendApprovalState] = {}

    def set_available(self, available: bool) -> None:
        """Simulate backend availability / outage."""
        with self._lock:
            self._available = available

    def _ensure_available(self) -> None:
        if not self._available:
            raise BackendUnavailableError("Mock backend approval service is currently unavailable.")

    def seed_state(self, state: BackendApprovalState) -> None:
        """Directly seed authoritative backend state (useful for stale-cache tests)."""
        with self._lock:
            self._states[(state.workflow_id, state.step_id)] = state

    def publish_request(self, req: ApprovalRequest) -> BackendApprovalState:
        with self._lock:
            self._ensure_available()
            key = (req.workflow_id, req.step_id)
            existing = self._states.get(key)
            if existing is not None:
                return existing
            state = BackendApprovalState(
                request_id=req.request_id,
                workflow_id=req.workflow_id,
                step_id=req.step_id,
                status=req.status,
                tool_name=req.tool_name,
                decided_at=req.decided_at,
                expires_at=req.expires_at,
                decision_reason=req.decision_reason,
            )
            self._states[key] = state
            return state

    def get_approval_state(
        self,
        workflow_id: str,
        step_id: str,
        request_id: Optional[str] = None,
    ) -> Optional[BackendApprovalState]:
        with self._lock:
            self._ensure_available()
            state = self._states.get((workflow_id, step_id))
            if state is None:
                return None
            if request_id is not None and state.request_id != request_id:
                return None
            if state.expires_at and _get_utc_now_iso() >= state.expires_at and state.status in {"PENDING", "APPROVED"}:
                state.status = "EXPIRED"
                state.decided_at = state.decided_at or _get_utc_now_iso()
                state.decision_reason = state.decision_reason or f"Backend approval expired at {state.expires_at}"
                state.version += 1
            return BackendApprovalState.from_dict(state.to_dict())

    def submit_decision(
        self,
        workflow_id: str,
        step_id: str,
        request_id: str,
        approved: bool,
        reason: Optional[str] = None,
        approver: str = "operator",
    ) -> BackendApprovalState:
        with self._lock:
            self._ensure_available()
            state = self._states.get((workflow_id, step_id))
            if state is None or state.request_id != request_id:
                raise KeyError(
                    f"Backend approval request '{request_id}' for ({workflow_id}, {step_id}) not found."
                )
            if state.expires_at and _get_utc_now_iso() >= state.expires_at and state.status == "PENDING":
                state.status = "EXPIRED"
                state.decided_at = _get_utc_now_iso()
                state.decision_reason = f"Backend approval expired at {state.expires_at}"
                state.version += 1
            if state.status != "PENDING":
                raise ValueError(
                    f"Cannot submit decision for request '{request_id}': backend status is '{state.status}'."
                )
            state.status = "APPROVED" if approved else "REJECTED"
            state.decided_by = approver
            state.decided_at = _get_utc_now_iso()
            state.decision_reason = reason or (f"Approved by {approver}" if approved else f"Rejected by {approver}")
            state.version += 1
            return BackendApprovalState.from_dict(state.to_dict())


class HttpBackendApprovalClient(BackendApprovalClient):
    """
    Configurable HTTP adapter for Worker 5's backend approval API once live endpoints exist.
    Disabled unless `base_url` is explicitly provided; never hardcodes endpoints or credentials.
    """

    mode: str = "http"

    def __init__(
        self,
        base_url: str,
        status_path_template: str = "/approvals/{workflow_id}/{step_id}",
        decision_path_template: str = "/approvals/{request_id}/decision",
        publish_path: str = "/approvals",
        timeout_seconds: float = 5.0,
    ) -> None:
        if not base_url or not str(base_url).strip():
            raise ValueError("base_url must be provided for HttpBackendApprovalClient.")
        self.base_url = base_url.rstrip("/")
        self.status_path_template = status_path_template
        self.decision_path_template = decision_path_template
        self.publish_path = publish_path
        self.timeout_seconds = timeout_seconds

    def _request_json(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        req = urllib.request.Request(url=url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            raise BackendUnavailableError(f"Backend approval endpoint '{url}' failed: {exc}") from exc

    def publish_request(self, req: ApprovalRequest) -> BackendApprovalState:
        data = self._request_json("POST", self.publish_path, req.to_dict())
        return BackendApprovalState.from_dict(data)

    def get_approval_state(
        self,
        workflow_id: str,
        step_id: str,
        request_id: Optional[str] = None,
    ) -> Optional[BackendApprovalState]:
        path = self.status_path_template.format(
            workflow_id=workflow_id,
            step_id=step_id,
            request_id=request_id or "",
        )
        data = self._request_json("GET", path)
        if not data:
            return None
        return BackendApprovalState.from_dict(data)

    def submit_decision(
        self,
        workflow_id: str,
        step_id: str,
        request_id: str,
        approved: bool,
        reason: Optional[str] = None,
        approver: str = "operator",
    ) -> BackendApprovalState:
        path = self.decision_path_template.format(
            workflow_id=workflow_id,
            step_id=step_id,
            request_id=request_id,
        )
        data = self._request_json(
            "POST",
            path,
            {
                "workflow_id": workflow_id,
                "step_id": step_id,
                "approved": approved,
                "reason": reason,
                "approver": approver,
            },
        )
        return BackendApprovalState.from_dict(data)


# ---------------------------------------------------------------------------
# 3. Worker 6 UI Approval & Rejection Contract (`ApprovalUIService`)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UIApprovalView:
    """UI-facing representation of an approval request and current workflow status."""

    request_id: str
    workflow_id: str
    step_id: str
    tool_name: str
    action_description: str
    status: str
    requested_at: str
    decided_at: Optional[str]
    expires_at: Optional[str]
    decision_reason: Optional[str]
    can_decide: bool
    workflow_state: str
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "action_description": self.action_description,
            "status": self.status,
            "requested_at": self.requested_at,
            "decided_at": self.decided_at,
            "expires_at": self.expires_at,
            "decision_reason": self.decision_reason,
            "can_decide": self.can_decide,
            "workflow_state": self.workflow_state,
            "error_message": self.error_message,
        }


@dataclass(frozen=True)
class UIApprovalAction:
    """UI-submitted approval or rejection payload."""

    workflow_id: str
    step_id: str
    decision: str  # "APPROVE" or "REJECT"
    request_id: Optional[str] = None
    reason: Optional[str] = None
    operator_id: str = "operator"
    submission_id: Optional[str] = None


@dataclass(frozen=True)
class UIApprovalResponse:
    """Structured response returned to the frontend approval UI."""

    accepted: bool
    duplicate_submission: bool
    status: str
    workflow_state: str
    message: str
    error_code: Optional[str] = None
    approval_view: Optional[UIApprovalView] = None
    execution_result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "duplicate_submission": self.duplicate_submission,
            "status": self.status,
            "workflow_state": self.workflow_state,
            "message": self.message,
            "error_code": self.error_code,
            "approval_view": self.approval_view.to_dict() if self.approval_view else None,
            "execution_result": self.execution_result,
        }


class ApprovalUIService:
    """
    Documented API/event service connecting frontend approval UI controls
    (Worker 6) to W4 WorkflowExecutor and ApprovalManager without touching W6 files.
    Enforces idempotent UI submissions, binding checks, expiry errors, and safe resume.
    """

    def __init__(self, auto_resume_on_approve: bool = True) -> None:
        self._lock = threading.RLock()
        self._executors: Dict[str, Any] = {}
        self._submission_cache: Dict[tuple[str, str, str], UIApprovalResponse] = {}
        self.auto_resume_on_approve = auto_resume_on_approve

    def register_executor(self, executor: Any) -> None:
        """Register a WorkflowExecutor instance for UI approval queries and actions."""
        with self._lock:
            self._executors[executor.plan.workflow_id] = executor

    def _to_view(self, executor: Any, req: ApprovalRequest, error_message: Optional[str] = None) -> UIApprovalView:
        req.check_expiry()
        return UIApprovalView(
            request_id=req.request_id,
            workflow_id=req.workflow_id,
            step_id=req.step_id,
            tool_name=req.tool_name,
            action_description=req.action_description,
            status=req.status,
            requested_at=req.requested_at,
            decided_at=req.decided_at,
            expires_at=req.expires_at,
            decision_reason=req.decision_reason,
            can_decide=req.is_pending(),
            workflow_state=executor.current_state.value,
            error_message=error_message,
        )

    def get_approval_status(self, workflow_id: str, step_id: str) -> UIApprovalView:
        """Return current UI approval status view (syncing backend state if configured)."""
        with self._lock:
            executor = self._executors.get(workflow_id)
            if executor is None:
                raise KeyError(f"Workflow '{workflow_id}' is not registered.")

            # Sync authoritative backend state if configured
            if hasattr(executor, "sync_backend_approval"):
                try:
                    executor.sync_backend_approval(step_id)
                except BackendUnavailableError as exc:
                    req = executor.get_approval_request(step_id)
                    if req is None:
                        raise KeyError(f"Approval request for ({workflow_id}, {step_id}) not found.") from exc
                    return self._to_view(executor, req, error_message=str(exc))

            req = executor.get_approval_request(step_id)
            if req is None:
                raise KeyError(f"Approval request for ({workflow_id}, {step_id}) not found.")
            return self._to_view(executor, req)

    def list_pending_approvals(self, workflow_id: Optional[str] = None) -> List[UIApprovalView]:
        """List all pending approval requests across registered workflows (or one workflow)."""
        with self._lock:
            targets = (
                [self._executors[workflow_id]]
                if workflow_id is not None and workflow_id in self._executors
                else list(self._executors.values())
            )
            views: List[UIApprovalView] = []
            for executor in targets:
                executor.approval_manager.check_expiries()
                reqs = (
                    executor.get_workflow_approval_requests().values()
                    if hasattr(executor, "get_workflow_approval_requests")
                    else executor.approval_requests.values()
                )
                for req in reqs:
                    if req.is_pending():
                        views.append(self._to_view(executor, req))
            return views

    def submit_decision(self, action: UIApprovalAction) -> UIApprovalResponse:
        """
        Process an approve/reject decision from the UI safely:
        - Deduplicates repeated UI submission_id tokens strictly per (workflow_id, step_id, submission_id).
        - Syncs authoritative backend approval state before deciding when configured.
        - Rejects wrong workflow/step/request bindings.
        - Reports structured errors for expired, already-decided, or backend-unavailable states.
        """
        with self._lock:
            cache_key = (
                (action.workflow_id, action.step_id, action.submission_id)
                if action.submission_id
                else None
            )
            if cache_key is not None and cache_key in self._submission_cache:
                cached = self._submission_cache[cache_key]
                return UIApprovalResponse(
                    accepted=cached.accepted,
                    duplicate_submission=True,
                    status=cached.status,
                    workflow_state=cached.workflow_state,
                    message=f"Duplicate submission '{action.submission_id}' ignored; returning prior outcome.",
                    error_code=cached.error_code,
                    approval_view=cached.approval_view,
                    execution_result=cached.execution_result,
                )

            decision_norm = str(action.decision or "").strip().upper()
            if decision_norm not in {"APPROVE", "REJECT"}:
                return UIApprovalResponse(
                    accepted=False,
                    duplicate_submission=False,
                    status="UNKNOWN",
                    workflow_state="unknown",
                    message=f"Invalid decision '{action.decision}'. Must be 'APPROVE' or 'REJECT'.",
                    error_code="INVALID_DECISION",
                )

            executor = self._executors.get(action.workflow_id)
            if executor is None:
                return UIApprovalResponse(
                    accepted=False,
                    duplicate_submission=False,
                    status="NOT_FOUND",
                    workflow_state="unknown",
                    message=f"Workflow '{action.workflow_id}' was not found.",
                    error_code="WORKFLOW_NOT_FOUND",
                )

            if hasattr(executor, "sync_backend_approval"):
                try:
                    executor.sync_backend_approval(action.step_id)
                except BackendUnavailableError as exc:
                    local_req = executor.get_approval_request(action.step_id)
                    view = self._to_view(executor, local_req, error_message=str(exc)) if local_req else None
                    return UIApprovalResponse(
                        accepted=False,
                        duplicate_submission=False,
                        status=local_req.status if local_req else "UNKNOWN",
                        workflow_state=executor.current_state.value,
                        message=str(exc),
                        error_code="BACKEND_UNAVAILABLE",
                        approval_view=view,
                    )

            req = executor.get_approval_request(action.step_id)
            if req is None:
                return UIApprovalResponse(
                    accepted=False,
                    duplicate_submission=False,
                    status="NOT_FOUND",
                    workflow_state=executor.current_state.value,
                    message=f"No approval request found for step '{action.step_id}'.",
                    error_code="APPROVAL_NOT_FOUND",
                )

            if req.workflow_id != action.workflow_id:
                return UIApprovalResponse(
                    accepted=False,
                    duplicate_submission=False,
                    status=req.status,
                    workflow_state=executor.current_state.value,
                    message=f"Approval request belongs to workflow '{req.workflow_id}', not '{action.workflow_id}'.",
                    error_code="BINDING_MISMATCH",
                    approval_view=self._to_view(executor, req),
                )

            if action.request_id is not None and req.request_id != action.request_id:
                return UIApprovalResponse(
                    accepted=False,
                    duplicate_submission=False,
                    status=req.status,
                    workflow_state=executor.current_state.value,
                    message=f"Request ID mismatch: expected '{req.request_id}', got '{action.request_id}'.",
                    error_code="BINDING_MISMATCH",
                    approval_view=self._to_view(executor, req),
                )

            # Evaluate expiry before decision
            req.check_expiry()
            if req.is_expired():
                view = self._to_view(executor, req, error_message="Approval request has expired.")
                return UIApprovalResponse(
                    accepted=False,
                    duplicate_submission=False,
                    status="EXPIRED",
                    workflow_state=executor.current_state.value,
                    message=f"Approval request '{req.request_id}' has expired and cannot be decided.",
                    error_code="APPROVAL_EXPIRED",
                    approval_view=view,
                )

            if not req.is_pending():
                view = self._to_view(executor, req, error_message=f"Request already {req.status}.")
                return UIApprovalResponse(
                    accepted=False,
                    duplicate_submission=True,
                    status=req.status,
                    workflow_state=executor.current_state.value,
                    message=f"Approval request '{req.request_id}' was already {req.status}.",
                    error_code="ALREADY_DECIDED",
                    approval_view=view,
                )

            approved = decision_norm == "APPROVE"
            try:
                updated_req = executor.submit_approval(
                    action.step_id,
                    approved=approved,
                    reason=action.reason,
                    approver=action.operator_id,
                )
            except BackendUnavailableError as exc:
                view = self._to_view(executor, req, error_message=str(exc))
                return UIApprovalResponse(
                    accepted=False,
                    duplicate_submission=False,
                    status=req.status,
                    workflow_state=executor.current_state.value,
                    message=str(exc),
                    error_code="BACKEND_UNAVAILABLE",
                    approval_view=view,
                )
            except Exception as exc:
                view = self._to_view(executor, req, error_message=str(exc))
                return UIApprovalResponse(
                    accepted=False,
                    duplicate_submission=False,
                    status=req.status,
                    workflow_state=executor.current_state.value,
                    message=str(exc),
                    error_code="APPROVAL_ERROR",
                    approval_view=view,
                )

            exec_result_dict: Optional[Dict[str, Any]] = None
            if self.auto_resume_on_approve:
                exec_res = executor.run()
                exec_result_dict = exec_res.to_dict()

            view = self._to_view(executor, updated_req)
            response = UIApprovalResponse(
                accepted=True,
                duplicate_submission=False,
                status=updated_req.status,
                workflow_state=executor.current_state.value,
                message=(
                    f"Approval granted for step '{action.step_id}'."
                    if approved
                    else f"Approval rejected for step '{action.step_id}'."
                ),
                error_code=None,
                approval_view=view,
                execution_result=exec_result_dict,
            )

            if cache_key is not None:
                self._submission_cache[cache_key] = response
            return response
