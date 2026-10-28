"""
Workflow Schemas for W4 Agentic Workflow.

Defines the core data contracts:
1. WorkflowPlan
2. WorkflowStep
3. ToolSpec
4. ApprovalRequest
5. WorkflowResult

Each schema is defined exactly once in this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _get_utc_now_iso() -> str:
    """Helper to return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class WorkflowResult:
    """
    Standardized execution output contract for steps and workflows.
    Encapsulates outcome status, result payload, and sanitized error messages.
    """
    success: bool
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, output: Optional[Dict[str, Any]] = None, metadata: Optional[Dict[str, Any]] = None) -> "WorkflowResult":
        """Factory for successful outcomes."""
        return cls(
            success=True,
            output=output if output is not None else {},
            error=None,
            metadata=metadata if metadata is not None else {},
        )

    @classmethod
    def fail(cls, error: str, metadata: Optional[Dict[str, Any]] = None) -> "WorkflowResult":
        """Factory for failed outcomes."""
        return cls(
            success=False,
            output=None,
            error=error,
            metadata=metadata if metadata is not None else {},
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary representation."""
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowResult":
        """Reconstruct result from dictionary."""
        return cls(
            success=bool(data.get("success", False)),
            output=data.get("output"),
            error=data.get("error"),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class ToolSpec:
    """
    Metadata specification for allow-listed tools.
    Specifies tool identifier, human description, input schema, and consequentiality flag.
    """
    name: str
    description: str
    parameters_schema: Dict[str, Any] = field(default_factory=dict)
    is_consequential: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert specification to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters_schema": dict(self.parameters_schema),
            "is_consequential": self.is_consequential,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolSpec":
        """Reconstruct ToolSpec from dictionary."""
        return cls(
            name=str(data["name"]),
            description=str(data.get("description", "")),
            parameters_schema=dict(data.get("parameters_schema", {})),
            is_consequential=bool(data.get("is_consequential", False)),
        )


@dataclass
class ApprovalRequest:
    """
    Contract representing human-in-the-loop approval gating for consequential actions.
    Explicitly tracks request status (PENDING, APPROVED, REJECTED) and audit metadata.
    """
    request_id: str
    workflow_id: str
    step_id: str
    tool_name: str
    action_description: str
    status: str = "PENDING"  # PENDING, APPROVED, REJECTED
    requested_at: str = field(default_factory=_get_utc_now_iso)
    decided_at: Optional[str] = None
    decision_reason: Optional[str] = None

    def approve(self, reason: Optional[str] = None) -> None:
        """Grant explicit approval for consequential action."""
        if self.status != "PENDING":
            raise ValueError(f"Cannot approve request with status '{self.status}'. Must be PENDING.")
        self.status = "APPROVED"
        self.decided_at = _get_utc_now_iso()
        self.decision_reason = reason or "Approved by operator"

    def reject(self, reason: Optional[str] = None) -> None:
        """Reject consequential action, preventing execution."""
        if self.status != "PENDING":
            raise ValueError(f"Cannot reject request with status '{self.status}'. Must be PENDING.")
        self.status = "REJECTED"
        self.decided_at = _get_utc_now_iso()
        self.decision_reason = reason or "Rejected by operator"

    def is_approved(self) -> bool:
        """Check if approved."""
        return self.status == "APPROVED"

    def is_rejected(self) -> bool:
        """Check if rejected."""
        return self.status == "REJECTED"

    def is_pending(self) -> bool:
        """Check if still pending approval."""
        return self.status == "PENDING"

    def to_dict(self) -> Dict[str, Any]:
        """Convert approval request to dictionary."""
        return {
            "request_id": self.request_id,
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "action_description": self.action_description,
            "status": self.status,
            "requested_at": self.requested_at,
            "decided_at": self.decided_at,
            "decision_reason": self.decision_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ApprovalRequest":
        """Reconstruct ApprovalRequest from dictionary."""
        return cls(
            request_id=str(data["request_id"]),
            workflow_id=str(data["workflow_id"]),
            step_id=str(data["step_id"]),
            tool_name=str(data["tool_name"]),
            action_description=str(data.get("action_description", "")),
            status=str(data.get("status", "PENDING")),
            requested_at=str(data.get("requested_at", _get_utc_now_iso())),
            decided_at=data.get("decided_at"),
            decision_reason=data.get("decision_reason"),
        )


@dataclass
class WorkflowStep:
    """
    Contract representing an atomic unit of execution in a workflow.
    Specifies step identification, tool target, inputs, dependencies, and execution state.
    """
    step_id: str
    tool_name: str
    input_payload: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)
    is_consequential: Optional[bool] = None  # None: inherit consequentiality from ToolSpec
    status: str = "pending"  # pending, awaiting_approval, running, completed, failed, skipped
    result: Optional[WorkflowResult] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert workflow step to dictionary."""
        return {
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "input_payload": dict(self.input_payload),
            "dependencies": list(self.dependencies),
            "is_consequential": self.is_consequential,
            "status": self.status,
            "result": self.result.to_dict() if self.result else None,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowStep":
        """Reconstruct WorkflowStep from dictionary."""
        res_data = data.get("result")
        res = WorkflowResult.from_dict(res_data) if res_data else None
        return cls(
            step_id=str(data["step_id"]),
            tool_name=str(data["tool_name"]),
            input_payload=dict(data.get("input_payload", {})),
            dependencies=list(data.get("dependencies", [])),
            is_consequential=data.get("is_consequential"),
            status=str(data.get("status", "pending")),
            result=res,
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class WorkflowPlan:
    """
    Top-level contract representing an ordered or DAG workflow execution plan.
    Encompasses goal definition, ordered step specifications, and lifecycle metadata.
    """
    workflow_id: str
    goal: str
    steps: List[WorkflowStep] = field(default_factory=list)
    state: str = "draft"
    created_at: str = field(default_factory=_get_utc_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        """Lookup a step by step_id."""
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None

    def add_step(self, step: WorkflowStep) -> None:
        """Append a step to the workflow plan."""
        self.steps.append(step)

    def to_dict(self) -> Dict[str, Any]:
        """Convert workflow plan to dictionary."""
        return {
            "workflow_id": self.workflow_id,
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "state": self.state,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowPlan":
        """Reconstruct WorkflowPlan from dictionary."""
        return cls(
            workflow_id=str(data["workflow_id"]),
            goal=str(data["goal"]),
            steps=[WorkflowStep.from_dict(s) for s in data.get("steps", [])],
            state=str(data.get("state", "draft")),
            created_at=str(data.get("created_at", _get_utc_now_iso())),
            metadata=dict(data.get("metadata", {})),
        )
