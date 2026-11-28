"""Session management, lifecycle operations, event streaming, and gateway interaction routes."""

import asyncio
import base64
import json
from typing import Any, AsyncGenerator, Dict, List, Optional, Set
from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.exceptions import InvalidStateTransitionError
from app.core.logging import logger
from app.gateways.coordinator import GatewayCoordinator, get_gateway_coordinator
from app.gateways.protocols import AudioChunkData
from app.models.session import (
    CreateSessionRequest,
    ExpireSessionRequest,
    MockSessionData,
    MockSessionResponse,
    PauseSessionRequest,
    ResumeSessionRequest,
    SessionEventsResponse,
    SessionInteractionRequest,
    SessionInteractionResponse,
    SessionLifecycleResponse,
    SessionState,
    SingleSessionResponse,
    StopSessionRequest,
    TERMINAL_STATES,
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
# 4. EVENT STREAMING ENDPOINT WITH ATOMIC REPLAY (DAY 17-18)
# ============================================================================

@router.get(
    "/{session_id}/events/stream",
    summary="Stream Session Events (SSE)",
    description="Streams session events in chronological order via Server-Sent Events (SSE). Guarantees zero missed events via atomic replay and reconnect support.",
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
    """Server-Sent Events (SSE) endpoint with atomic replay boundary synchronization."""
    session = await service.get_session(session_id, check_expiry=True)
    effective_since_id = last_event_id_header or since_id

    # Atomically capture replay boundary and register live queue under single lock
    historical_events, queue = await repository.subscribe_and_replay(
        session_id=session_id,
        since_event_id=effective_since_id,
    )

    async def sse_generator() -> AsyncGenerator[str, None]:
        seen_event_ids: Set[str] = set()
        last_sent_id = effective_since_id

        try:
            # Initial SSE acknowledgement comment
            yield f": connected to session {session_id}\n\n"

            # 1. Replay historical events captured at registration
            for evt in historical_events:
                seen_event_ids.add(evt.event_id)
                last_sent_id = evt.event_id
                payload_json = json.dumps(evt.model_dump(mode="json"))
                yield f"id: {evt.event_id}\nevent: {evt.event_type}\ndata: {payload_json}\n\n"

            # 2. If follow is False or session is terminal, clean up and exit
            if not follow or session.state in TERMINAL_STATES:
                if session.state in TERMINAL_STATES:
                    yield ": session ended\n\n"
                return

            # 3. Stream live events from the registered queue
            while True:
                if await request.is_disconnected():
                    logger.info(f"SSE client disconnected from session {session_id}")
                    break

                # Check if queue experienced buffer overflow
                if await repository.has_overflowed(session_id, queue):
                    logger.warning(f"SSE queue overflow observed for session {session_id}")
                    overflow_payload = json.dumps({
                        "warning": "Buffer overflow detected. Some live events were dropped.",
                        "last_delivered_event_id": last_sent_id,
                        "action": "Reconnect with Last-Event-ID to replay missing events.",
                    })
                    yield f"event: stream.overflow\ndata: {overflow_payload}\n\n"

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    # Deduplicate in case event was present in historical slice
                    if event.event_id not in seen_event_ids:
                        seen_event_ids.add(event.event_id)
                        last_sent_id = event.event_id
                        payload_json = json.dumps(event.model_dump(mode="json"))
                        yield f"id: {event.event_id}\nevent: {event.event_type}\ndata: {payload_json}\n\n"

                    # If session reaches a terminal state, complete stream
                    if event.event_type in ("session.stopped", "session.expired") or event.payload.get("new_state") in ("completed", "expired", "failed"):
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


# ============================================================================
# 5. CROSS-WORKSTREAM INTERACTION ENDPOINT (DAY 15-16, 21)
# ============================================================================

@router.post(
    "/{session_id}/interact",
    response_model=SessionInteractionResponse,
    status_code=status.HTTP_200_OK,
    summary="Cross-Workstream Voice Co-Pilot Interaction",
    description="Runs the integration pipeline: Audio -> Transcription -> Context/Reasoning -> Workflow -> Session Events.",
)
async def process_session_interaction(
    session_id: str,
    payload: Optional[SessionInteractionRequest] = None,
    service: SessionService = Depends(get_session_service),
    coordinator: GatewayCoordinator = Depends(get_gateway_coordinator),
) -> SessionInteractionResponse:
    """Execute end-to-end integration flow within an active session."""
    session = await service.get_session(session_id, check_expiry=True)
    if session.state in TERMINAL_STATES:
        raise InvalidStateTransitionError(
            current_state=session.state.value,
            target_state="active",
            reason=f"Cannot interact in terminal session state '{session.state.value}'.",
        )

    req = payload or SessionInteractionRequest()
    audio_chunk: Optional[AudioChunkData] = None

    if req.audio_base64:
        try:
            raw_bytes = base64.b64decode(req.audio_base64)
            audio_chunk = AudioChunkData(
                data=raw_bytes,
                sequence_number=1,
                is_speech=True,
                metadata={"source": "client_upload_base64"},
            )
        except Exception as exc:
            logger.warning(f"Failed to decode audio_base64 payload: {exc}")

    result = await coordinator.process_interaction(
        session_id=session_id,
        user_query=req.user_query,
        audio_chunk=audio_chunk,
        workflow_goal=req.workflow_goal,
        timeout_seconds=req.timeout_seconds,
    )

    return SessionInteractionResponse(
        success=True,
        session_id=session_id,
        audio=result.audio_chunk.to_dict() if result.audio_chunk else None,
        transcript=result.transcript.to_dict() if result.transcript else None,
        reasoning=result.reasoning.to_dict() if result.reasoning else None,
        workflow=result.workflow.to_dict() if result.workflow else None,
        events_emitted=result.events_emitted,
    )
