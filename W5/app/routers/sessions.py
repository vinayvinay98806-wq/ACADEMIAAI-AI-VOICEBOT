"""Session management and mock session routes for Week 1."""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from app.core.exceptions import SessionNotFoundError
from app.models.session import (
    CreateSessionRequest,
    MockSessionData,
    MockSessionResponse,
    Session,
    SessionEvent,
    SessionEventsResponse,
    SessionState,
    SingleSessionResponse,
)
from app.repositories.in_memory_session import (
    InMemorySessionRepository,
    get_session_repository,
)

router = APIRouter(prefix="/sessions", tags=["Sessions"])


class TransitionStateRequest(BaseModel):
    """Payload to request a session state transition."""

    target_state: SessionState = Field(..., description="Desired target state")


@router.post(
    "/mock",
    response_model=MockSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a Mock Session",
    description="Initializes a deterministic mock voice session and produces an initial mock event without external AI services.",
)
async def start_mock_session(
    request: CreateSessionRequest | None = None,
    repository: InMemorySessionRepository = Depends(get_session_repository),
) -> MockSessionResponse:
    """Start a mock session and generate initial mock event."""
    user_id = request.user_id if request and request.user_id else "anonymous-user"
    metadata = request.metadata if request and request.metadata else {}

    # Deterministic or controlled session ID
    session_uid = uuid.uuid4().hex[:10]
    session_id = f"mock-sess-{session_uid}"
    event_id = f"mock-evt-{session_uid}"

    now = datetime.now(timezone.utc)

    # Construct session model
    session = Session(
        session_id=session_id,
        user_id=user_id,
        state=SessionState.ACTIVE,
        metadata={
            "mode": "mock",
            "team": "SDE 7",
            "workstream": "W5",
            **metadata,
        },
        created_at=now,
        updated_at=now,
    )

    # Persist session to repository
    created_session = await repository.create(session)

    # Construct initial mock event
    event = SessionEvent(
        event_id=event_id,
        session_id=session_id,
        event_type="session.started",
        payload={
            "message": "Mock voice session initialized successfully",
            "bot_name": "Academiaai-Voicebot",
            "audio_channel": "mock-stream",
            "sample_rate_hz": 16000,
            "codec": "pcm_s16le",
            "initial_prompt": (
                "Hello! Welcome to Academiaai. How can I assist you with your academic queries today?"
            ),
            "mock_mode": True,
        },
        timestamp=now,
    )

    # Persist event to repository
    created_event = await repository.add_event(session_id, event)

    return MockSessionResponse(
        success=True,
        data=MockSessionData(
            session=created_session,
            event=created_event,
        ),
    )


@router.get(
    "/{session_id}",
    response_model=SingleSessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Session by ID",
    description="Retrieves session details by session ID from the in-memory repository.",
)
async def get_session(
    session_id: str,
    repository: InMemorySessionRepository = Depends(get_session_repository),
) -> SingleSessionResponse:
    """Retrieve session details."""
    session = await repository.get_by_id(session_id)
    if not session:
        raise SessionNotFoundError(session_id)
    return SingleSessionResponse(success=True, data=session)


@router.get(
    "/{session_id}/events",
    response_model=SessionEventsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Session Events",
    description="Retrieves all recorded events for a given session ID.",
)
async def get_session_events(
    session_id: str,
    repository: InMemorySessionRepository = Depends(get_session_repository),
) -> SessionEventsResponse:
    """Retrieve recorded events for a session."""
    session = await repository.get_by_id(session_id)
    if not session:
        raise SessionNotFoundError(session_id)

    events = await repository.get_events(session_id)
    return SessionEventsResponse(
        success=True,
        session_id=session_id,
        events=events,
        total=len(events),
    )


@router.get(
    "",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="List Sessions",
    description="Lists all active or stored sessions in the in-memory repository.",
)
async def list_sessions(
    repository: InMemorySessionRepository = Depends(get_session_repository),
) -> Dict[str, Any]:
    """List all stored sessions."""
    sessions = await repository.list_all()
    return {
        "success": True,
        "sessions": [s.model_dump(mode="json") for s in sessions],
        "total": len(sessions),
    }


@router.post(
    "/{session_id}/transition",
    response_model=SingleSessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Transition Session State",
    description="Enforces session state rules and transitions session to target state.",
)
async def transition_session(
    session_id: str,
    payload: TransitionStateRequest,
    repository: InMemorySessionRepository = Depends(get_session_repository),
) -> SingleSessionResponse:
    """Transition session state following defined transition rules."""
    session = await repository.get_by_id(session_id)
    if not session:
        raise SessionNotFoundError(session_id)

    # Enforce state rules
    session.transition_to(payload.target_state)
    updated_session = await repository.update(session)

    # Record transition event
    transition_event = SessionEvent(
        event_id=f"evt-trans-{uuid.uuid4().hex[:8]}",
        session_id=session_id,
        event_type="session.state_changed",
        payload={
            "previous_state": session.state.value,
            "new_state": payload.target_state.value,
        },
        timestamp=datetime.now(timezone.utc),
    )
    await repository.add_event(session_id, transition_event)

    return SingleSessionResponse(success=True, data=updated_session)
