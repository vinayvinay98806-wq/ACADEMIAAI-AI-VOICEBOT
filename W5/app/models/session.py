"""Session models, state definitions, and state transition rules."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional, Set
from pydantic import BaseModel, Field

from app.core.exceptions import InvalidStateTransitionError


class SessionState(str, Enum):
    """Enumeration of possible session states."""

    INITIALIZING = "initializing"
    ACTIVE = "active"
    IDLE = "idle"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


# Valid state transitions for Week 1 session flows
VALID_TRANSITIONS: Dict[SessionState, Set[SessionState]] = {
    SessionState.INITIALIZING: {SessionState.ACTIVE, SessionState.FAILED},
    SessionState.ACTIVE: {
        SessionState.IDLE,
        SessionState.PAUSED,
        SessionState.COMPLETED,
        SessionState.FAILED,
    },
    SessionState.IDLE: {
        SessionState.ACTIVE,
        SessionState.PAUSED,
        SessionState.COMPLETED,
        SessionState.FAILED,
    },
    SessionState.PAUSED: {
        SessionState.ACTIVE,
        SessionState.COMPLETED,
        SessionState.FAILED,
    },
    SessionState.COMPLETED: set(),  # Terminal state
    SessionState.FAILED: set(),     # Terminal state
}


class SessionEvent(BaseModel):
    """Event occurring within a voice session."""

    event_id: str = Field(..., description="Unique event ID")
    session_id: str = Field(..., description="Associated session ID")
    event_type: str = Field(..., description="Type of event (e.g. session.started)")
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured event payload",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Event UTC timestamp",
    )


class Session(BaseModel):
    """Representation of an AI Voicebot session."""

    session_id: str = Field(..., description="Unique session identifier")
    user_id: Optional[str] = Field(None, description="Optional user identifier")
    state: SessionState = Field(
        default=SessionState.ACTIVE,
        description="Current state of the session",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary session metadata",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Creation UTC timestamp",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Last update UTC timestamp",
    )

    def transition_to(self, new_state: SessionState) -> None:
        """Enforce transition rules and update state."""
        allowed = VALID_TRANSITIONS.get(self.state, set())
        if new_state not in allowed:
            raise InvalidStateTransitionError(
                current_state=self.state.value,
                target_state=new_state.value,
                reason=f"Transition from {self.state.value} to {new_state.value} is not permitted.",
            )
        self.state = new_state
        self.updated_at = datetime.now(timezone.utc)


class CreateSessionRequest(BaseModel):
    """Request payload to initiate a session."""

    user_id: Optional[str] = Field(
        None,
        description="Optional ID of the user initiating the session",
        max_length=128,
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Optional session metadata",
    )


class MockSessionData(BaseModel):
    """Data payload returned on mock session initialization."""

    session: Session
    event: SessionEvent


class MockSessionResponse(BaseModel):
    """Successful mock session creation response envelope."""

    success: bool = Field(True, description="Success status")
    data: MockSessionData


class SingleSessionResponse(BaseModel):
    """Single session lookup response envelope."""

    success: bool = Field(True, description="Success status")
    data: Session


class SessionEventsResponse(BaseModel):
    """Response containing events for a specific session."""

    success: bool = Field(True, description="Success status")
    session_id: str
    events: list[SessionEvent]
    total: int
