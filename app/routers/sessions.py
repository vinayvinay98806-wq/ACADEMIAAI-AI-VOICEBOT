"""Session management, lifecycle operations, and event streaming routes."""

import asyncio
import json
from typing import Any, AsyncGenerator, Dict, Optional
from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.logging import logger
from app.models.session import (
    CreateSessionRequest,
    ExpireSessionRequest,
    MockSessionData,
    MockSessionResponse,
    PauseSessionRequest,
    ResumeSessionRequest,
    SessionEventsResponse,
    SessionLifecycleResponse,
    SessionState,
    SingleSessionResponse,
    StopSessionRequest,
)
from app.repositories.in_memory_session import (
    InMemorySessionRepository,
    get_session_repository,
)
from app.services.session_service import SessionService, get_session_service

router = APIRouter(prefix="/sessions", tags=["Sessions"])


class TransitionStateRequest(BaseModel):
    """Payload to request a session state transition."""

    target_state: SessionState = Field(..., description="Desired target state")
    reason: Optional[str] = Field(None, description="Optional transition reason")


# ============================================================================
# 1. SESSION CREATION ENDPOINTS
# ============================================================================

@router.post(
    "",
    response_model=MockSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a Session",
    description="Initiates a new voice session with configurable user ID, metadata, and TTL.",
)
async def create_session(
    request: Optional[CreateSessionRequest] = None,
    service: SessionService = Depends(get_session_service),
) -> MockSessionResponse:
    """Create a standard session with initial event."""
    session, event = await service.create_session(request, is_mock=False)
    return MockSessionResponse(
        success=True,
        data=MockSessionData(
            session=session,
            event=event,
        ),
    )


@router.post(
    "/mock",
    response_model=MockSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a Mock Session",
    description="Initializes a deterministic mock voice session and produces an initial mock event without external AI services.",
)
async def start_mock_session(
    request: Optional[CreateSessionRequest] = None,
    service: SessionService = Depends(get_session_service),
) -> MockSessionResponse:
    """Start a mock session and generate initial mock event."""
    session, event = await service.create_session(request, is_mock=True)
    return MockSessionResponse(
        success=True,
        data=MockSessionData(
            session=session,
            event=event,
        ),
    )


# ============================================================================
# 2. LIFECYCLE OPERATION ENDPOINTS (DAY 8-9)
# ============================================================================

@router.post(
    "/{session_id}/pause",
    response_model=SessionLifecycleResponse,
    status_code=status.HTTP_200_OK,
    summary="Pause Session",
    description="Pauses an active or idle session. Idempotent if already paused.",
)
async def pause_session(
    session_id: str,
    payload: Optional[PauseSessionRequest] = None,
    service: SessionService = Depends(get_session_service),
) -> SessionLifecycleResponse:
    """Pause an active voice session."""
    reason = payload.reason if payload else None
    session, event = await service.pause_session(session_id, reason=reason)
    return SessionLifecycleResponse(success=True, data=session, event=event)


@router.post(
    "/{session_id}/resume",
    response_model=SessionLifecycleResponse,
    status_code=status.HTTP_200_OK,
    summary="Resume Session",
    description="Resumes a paused session back to active state. Idempotent if already active.",
)
async def resume_session(
    session_id: str,
    payload: Optional[ResumeSessionRequest] = None,
    service: SessionService = Depends(get_session_service),
) -> SessionLifecycleResponse:
    """Resume a paused voice session."""
    reason = payload.reason if payload else None
    session, event = await service.resume_session(session_id, reason=reason)
    return SessionLifecycleResponse(success=True, data=session, event=event)


@router.post(
    "/{session_id}/stop",
    response_model=SessionLifecycleResponse,
    status_code=status.HTTP_200_OK,
    summary="Stop Session",
    description="Stops and completes a session. Idempotent if already completed.",
)
async def stop_session(
    session_id: str,
    payload: Optional[StopSessionRequest] = None,
    service: SessionService = Depends(get_session_service),
) -> SessionLifecycleResponse:
    """Stop/complete a voice session."""
    reason = payload.reason if payload else None
    session, event = await service.stop_session(session_id, reason=reason)
    return SessionLifecycleResponse(success=True, data=session, event=event)


@router.post(
    "/{session_id}/expire",
    response_model=SessionLifecycleResponse,
    status_code=status.HTTP_200_OK,
    summary="Expire Session",
    description="Explicitly expires a session. Idempotent if already expired.",
)
async def expire_session(
    session_id: str,
    payload: Optional[ExpireSessionRequest] = None,
    service: SessionService = Depends(get_session_service),
) -> SessionLifecycleResponse:
    """Explicitly expire a voice session."""
    reason = payload.reason if payload else None
    session, event = await service.expire_session(session_id, reason=reason)
    return SessionLifecycleResponse(success=True, data=session, event=event)


# ============================================================================
# 3. QUERY & TRANSITION ENDPOINTS
# ============================================================================

@router.get(
    "/{session_id}",
    response_model=SingleSessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Session by ID",
    description="Retrieves session details by session ID, applying auto-expiry if TTL elapsed.",
)
async def get_session(
    session_id: str,
    service: SessionService = Depends(get_session_service),
) -> SingleSessionResponse:
    """Retrieve session details."""
    session = await service.get_session(session_id, check_expiry=True)
    return SingleSessionResponse(success=True, data=session)


@router.get(
    "/{session_id}/events",
    response_model=SessionEventsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Session Events",
    description="Retrieves all recorded events for a given session ID in chronological order.",
)
async def get_session_events(
    session_id: str,
    since_id: Optional[str] = Query(None, description="Optional event ID to filter events after"),
    service: SessionService = Depends(get_session_service),
    repository: InMemorySessionRepository = Depends(get_session_repository),
) -> SessionEventsResponse:
    """Retrieve recorded events for a session."""
    # Ensure session exists (auto-checks expiry)
    await service.get_session(session_id, check_expiry=True)
    events = await repository.get_events(session_id, since_event_id=since_id)
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
    description="Lists all active or stored sessions, applying auto-expiry checks.",
)
async def list_sessions(
    service: SessionService = Depends(get_session_service),
) -> Dict[str, Any]:
    """List all stored sessions."""
    sessions = await service.list_sessions(check_expiry=True)
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
    service: SessionService = Depends(get_session_service),
) -> SingleSessionResponse:
    """Transition session state following defined transition rules."""
    updated_session, _ = await service.transition_state(
        session_id=session_id,
        target_state=payload.target_state,
        reason=payload.reason,
    )
    return SingleSessionResponse(success=True, data=updated_session)


# ============================================================================
# 4. EVENT STREAMING ENDPOINT (DAY 10-11)
# ============================================================================

@router.get(
    "/{session_id}/events/stream",
    summary="Stream Session Events (SSE)",
    description="Streams session events in chronological order using Server-Sent Events (SSE). Supports reconnect/replay via Last-Event-ID.",
    response_class=StreamingResponse,
)
async def stream_session_events(
    session_id: str,
    request: Request,
    since_id: Optional[str] = Query(None, description="Event ID to replay after"),
    follow: bool = Query(False, description="Whether to keep the connection open for live events"),
    last_event_id_header: Optional[str] = Header(None, alias="Last-Event-ID"),
    service: SessionService = Depends(get_session_service),
    repository: InMemorySessionRepository = Depends(get_session_repository),
) -> StreamingResponse:
    """Server-Sent Events (SSE) endpoint for chronological event streaming."""
    # 1. Validate session existence; raises SessionNotFoundError (404) if unknown
    await service.get_session(session_id, check_expiry=True)

    # Reconnect / replay support: prioritize header or query param
    effective_since_id = last_event_id_header or since_id

    async def sse_generator() -> AsyncGenerator[str, None]:
        # Initial SSE comment to acknowledge connection
        yield f": connected to session {session_id}\n\n"

        # 2. Replay historical events in chronological order
        historical_events = await repository.get_events(
            session_id, since_event_id=effective_since_id
        )
        last_sent_id = effective_since_id
        for evt in historical_events:
            last_sent_id = evt.event_id
            payload_json = json.dumps(evt.model_dump(mode="json"))
            yield f"id: {evt.event_id}\nevent: {evt.event_type}\ndata: {payload_json}\n\n"

        # 3. If follow is not requested, finish the stream cleanly
        if not follow:
            return

        # 4. If follow is True, listen to live events
        queue = await repository.subscribe_events(session_id)
        try:
            while True:
                if await request.is_disconnected():
                    logger.info(f"SSE client disconnected from session {session_id}")
                    break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    # Deduplicate in case event was already replayed
                    if event.event_id != last_sent_id:
                        last_sent_id = event.event_id
                        payload_json = json.dumps(event.model_dump(mode="json"))
                        yield f"id: {event.event_id}\nevent: {event.event_type}\ndata: {payload_json}\n\n"

                    # If session reaches a terminal state, complete stream
                    if event.event_type in ("session.stopped", "session.expired"):
                        yield ": session ended\n\n"
                        break
                except asyncio.TimeoutError:
                    # Keep-alive heartbeat comment
                    yield ": ping\n\n"
        finally:
            await repository.unsubscribe_events(session_id, queue)

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(sse_generator(), media_type="text/event-stream", headers=headers)
