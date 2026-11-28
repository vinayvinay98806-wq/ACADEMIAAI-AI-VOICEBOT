"""
Workflow State Machine for W4 Agentic Workflow.

Manages explicit lifecycle transitions across the required states:
- draft
- awaiting_approval
- running
- paused
- succeeded
- failed
- cancelled

Rejects illegal transitions and documents valid transition paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Set


def _get_utc_now_iso() -> str:
    """Helper to return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


class WorkflowState(str, Enum):
    """
    Standard workflow execution states.
    All state names are lowercase strings as required by the specification.
    """
    DRAFT = "draft"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    def __str__(self) -> str:
        return self.value


class IllegalStateTransitionError(ValueError):
    """Exception raised when an illegal or unsupported state transition is attempted."""

    def __init__(
        self,
        current_state: WorkflowState,
        target_state: WorkflowState,
        valid_targets: Set[WorkflowState],
        message: Optional[str] = None,
    ):
        self.current_state = current_state
        self.target_state = target_state
        self.valid_targets = valid_targets

        if message is None:
            if not valid_targets:
                msg = (
                    f"Illegal transition from terminal state '{current_state.value}' to '{target_state.value}'. "
                    f"Terminal states cannot transition to any other state."
                )
            else:
                allowed_str = ", ".join(f"'{s.value}'" for s in sorted(valid_targets, key=lambda s: s.value))
                msg = (
                    f"Illegal transition from '{current_state.value}' to '{target_state.value}'. "
                    f"Valid transitions from '{current_state.value}' are: [{allowed_str}]."
                )
        else:
            msg = message
        super().__init__(msg)


# Strict map of allowed state transitions
VALID_TRANSITIONS: Dict[WorkflowState, Set[WorkflowState]] = {
    WorkflowState.DRAFT: {
        WorkflowState.RUNNING,
        WorkflowState.AWAITING_APPROVAL,
        WorkflowState.CANCELLED,
    },
    WorkflowState.RUNNING: {
        WorkflowState.AWAITING_APPROVAL,
        WorkflowState.PAUSED,
        WorkflowState.SUCCEEDED,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    },
    WorkflowState.AWAITING_APPROVAL: {
        WorkflowState.RUNNING,       # Approved by operator -> resumes execution
        WorkflowState.PAUSED,        # Paused while awaiting approval
        WorkflowState.FAILED,        # Rejected by operator/policy -> workflow fails
        WorkflowState.CANCELLED,     # Workflow cancelled while waiting
    },
    WorkflowState.PAUSED: {
        WorkflowState.RUNNING,            # Resumed back to running
        WorkflowState.AWAITING_APPROVAL,  # Resumed into waiting for pending approval
        WorkflowState.CANCELLED,          # Workflow cancelled while paused
    },
    # Terminal states have no valid subsequent transitions
    WorkflowState.SUCCEEDED: set(),
    WorkflowState.FAILED: set(),
    WorkflowState.CANCELLED: set(),
}

TERMINAL_STATES: Set[WorkflowState] = {
    WorkflowState.SUCCEEDED,
    WorkflowState.FAILED,
    WorkflowState.CANCELLED,
}


@dataclass(frozen=True)
class StateTransitionRecord:
    """Audit record capturing an individual state transition."""
    from_state: WorkflowState
    to_state: WorkflowState
    timestamp: str
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, str]:
        """Convert record to dictionary."""
        d = {
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "timestamp": self.timestamp,
        }
        if self.reason:
            d["reason"] = self.reason
        return d


class WorkflowStateMachine:
    """
    Finite State Machine (FSM) enforcing valid lifecycle transitions for workflows.
    Maintains current state and audit history of transitions.
    """

    def __init__(
        self,
        initial_state: WorkflowState = WorkflowState.DRAFT,
        history: Optional[List[StateTransitionRecord]] = None,
    ):
        if not isinstance(initial_state, WorkflowState):
            initial_state = WorkflowState(str(initial_state))
        self._state: WorkflowState = initial_state
        self._history: List[StateTransitionRecord] = list(history) if history else []

    @property
    def current_state(self) -> WorkflowState:
        """Returns the current state."""
        return self._state

    @property
    def is_terminal(self) -> bool:
        """Returns True if the current state is terminal (succeeded, failed, cancelled)."""
        return self._state in TERMINAL_STATES

    @property
    def history(self) -> List[StateTransitionRecord]:
        """Returns an immutable copy of the state transition history."""
        return list(self._history)

    def can_transition_to(self, target_state: WorkflowState | str) -> bool:
        """Checks if a transition to the target state is legally allowed."""
        if not isinstance(target_state, WorkflowState):
            try:
                target_state = WorkflowState(str(target_state))
            except ValueError:
                return False
        return target_state in VALID_TRANSITIONS.get(self._state, set())

    def get_valid_transitions(self) -> Set[WorkflowState]:
        """Returns the set of valid target states from the current state."""
        return set(VALID_TRANSITIONS.get(self._state, set()))

    def transition_to(self, target_state: WorkflowState | str, reason: Optional[str] = None) -> WorkflowState:
        """
        Transitions the machine to a new state if valid.
        Raises IllegalStateTransitionError if the transition is rejected.
        """
        if not isinstance(target_state, WorkflowState):
            try:
                target_state = WorkflowState(str(target_state))
            except ValueError as err:
                raise IllegalStateTransitionError(
                    current_state=self._state,
                    target_state=None,  # type: ignore
                    valid_targets=VALID_TRANSITIONS.get(self._state, set()),
                    message=f"Unknown target state '{target_state}'. Valid states: {[s.value for s in WorkflowState]}.",
                ) from err

        valid_targets = VALID_TRANSITIONS.get(self._state, set())

        if target_state not in valid_targets:
            raise IllegalStateTransitionError(
                current_state=self._state,
                target_state=target_state,
                valid_targets=valid_targets,
            )

        # Record transition
        from_state = self._state
        self._state = target_state
        self._history.append(
            StateTransitionRecord(
                from_state=from_state,
                to_state=target_state,
                timestamp=_get_utc_now_iso(),
                reason=reason,
            )
        )
        return self._state

    def recover_to(
        self,
        target_state: WorkflowState | str = WorkflowState.RUNNING,
        reason: Optional[str] = None,
    ) -> WorkflowState:
        """
        Explicitly recover a FAILED workflow from a valid checkpoint into an active state
        (RUNNING, PAUSED, or AWAITING_APPROVAL). Terminal SUCCEEDED and CANCELLED states
        remain permanently locked and cannot be recovered.
        """
        if not isinstance(target_state, WorkflowState):
            try:
                target_state = WorkflowState(str(target_state))
            except ValueError as err:
                raise IllegalStateTransitionError(
                    current_state=self._state,
                    target_state=None,  # type: ignore
                    valid_targets=set(),
                    message=f"Unknown recovery target state '{target_state}'.",
                ) from err

        recoverable_targets = {
            WorkflowState.RUNNING,
            WorkflowState.PAUSED,
            WorkflowState.AWAITING_APPROVAL,
        }
        if self._state != WorkflowState.FAILED or target_state not in recoverable_targets:
            raise IllegalStateTransitionError(
                current_state=self._state,
                target_state=target_state,
                valid_targets=recoverable_targets if self._state == WorkflowState.FAILED else set(),
                message=(
                    f"Cannot recover from state '{self._state.value}' to '{target_state.value}'. "
                    f"Only FAILED workflows can recover into {[s.value for s in sorted(recoverable_targets, key=lambda s: s.value)]}."
                ),
            )

        from_state = self._state
        self._state = target_state
        self._history.append(
            StateTransitionRecord(
                from_state=from_state,
                to_state=target_state,
                timestamp=_get_utc_now_iso(),
                reason=reason or "Recovered workflow from checkpoint",
            )
        )
        return self._state

    def restore_history(self, records: List[StateTransitionRecord]) -> None:
        """Restore transition history records (e.g., when loading from a checkpoint)."""
        self._history = list(records)
