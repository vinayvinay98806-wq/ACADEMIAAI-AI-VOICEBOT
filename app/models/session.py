"""Session models, state definitions, and state transition rules."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field

from app.core.exceptions import InvalidStateTransitionError


class SessionState(str, Enum):
    """Enumeration of possible session states."""

    INITIALIZING = "initializing"
    ACTIVE = "active"
    IDLE = "idle"
    PAUSED = "paused"
    COMPLETED = "completed"
    EXPIRED = "expired"
    FAILED = "failed"


# Valid state transitions for complete session lifecycle
VALID_TRANSITIONS: Dict[SessionState, Set[SessionState]] = {
    SessionState.INITIALIZING: {
        SessionState.ACTIVE,
        SessionState.FAILED,
    },
    SessionState.ACTIVE: {
        SessionState.IDLE,
        SessionState.PAUSED,
        SessionState.COMPLETED,
        SessionState.EXPIRED,
        SessionState.FAILED,
    },
    SessionState.IDLE: {
        SessionState.ACTIVE,
        SessionState.PAUSED,
        SessionState.COMPLETED,
        SessionState.EXPIRED,
        SessionState.FAILED,
    },
    SessionState.PAUSED: {
        SessionState.ACTIVE,
        SessionState.COMPLETED,
        SessionState.EXPIRED,
        SessionState.FAILED,
    },
    SessionState.COMPLETED: set(),  # Terminal state
    SessionState.EXPIRED: set(),    # Terminal state
    SessionState.FAILED: set(),     # Terminal state
}

# Terminal states that cannot transition to any new state
TERMINAL_STATES: Set[SessionState] = {
    SessionState.COMPLETED,
    SessionState.EXPIRED,
    SessionState.FAILED,
}


class SessionEvent(BaseModel):
    """Event occurring within a voice session."""

    event_id: str = Field(..., description="Unique event ID")
    session_id: str = Field(..., description="Associated session ID")
    event_type: str = Field(..., description="Type of event (e.g. session.started, session.paused)")
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
    expires_at: Optional[datetime] = Field(
        None,
        description="Expiration UTC timestamp",
    )
    ended_at: Optional[datetime] = Field(
        None,
        description="Terminal end UTC timestamp",
    )

    def transition_to(self, new_state: SessionState) -> bool:
        """Enforce transition rules and update state.

        Returns:
            True if state changed, False if already in the target state (idempotent no-op).
        """
        if self.state == new_state:
            return False

        allowed = VALID_TRANSITIONS.get(self.state, set())
        if new_state not in allowed:
            raise InvalidStateTransitionError(
                current_state=self.state.value,
                target_state=new_state.value,
                reason=f"Transition from '{self.state.value}' to '{new_state.value}' is not permitted.",
            )

        now = datetime.now(timezone.utc)
        self.state = new_state
        self.updated_at = now
        if new_state in TERMINAL_STATES:
            self.ended_at = now

        return True

    def is_expired(self, current_time: Optional[datetime] = None) -> bool:
        """Check whether the session has passed its expiration time."""
        if self.state in TERMINAL_STATES:
            return False
        if self.expires_at is None:
            return False
        now = current_time or datetime.now(timezone.utc)
        return now >= self.expires_at


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
    ttl_seconds: Optional[int] = Field(
        None,
        gt=0,
        le=604800,
        description="Optional custom session TTL in seconds",
    )


class LifecycleActionRequest(BaseModel):
    """Payload for lifecycle action requests (pause, resume, stop, expire)."""

    reason: Optional[str] = Field(
        None,
        max_length=256,
        description="Optional explanation for the action",
    )


class PauseSessionRequest(LifecycleActionRequest):
    """Payload to pause a session."""
    pass


class ResumeSessionRequest(LifecycleActionRequest):
    """Payload to resume a paused session."""
    pass


class StopSessionRequest(LifecycleActionRequest):
    """Payload to stop/complete a session."""
    pass


class ExpireSessionRequest(LifecycleActionRequest):
    """Payload to explicitly expire a session."""
    pass


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


class SessionLifecycleResponse(BaseModel):
    """Lifecycle operation response envelope."""

    success: bool = Field(True, description="Success status")
    data: Session
    event: Optional[SessionEvent] = Field(None, description="Generated lifecycle event, if state changed")


class SessionEventsResponse(BaseModel):
    """Response containing events for a specific session."""

    success: bool = Field(True, description="Success status")
    session_id: str
    events: List[SessionEvent]
    total: int
