"""Session lifecycle service orchestrating state transitions, expiry, and idempotency."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from fastapi import Depends

from app.config import Settings, get_settings
from app.core.exceptions import SessionNotFoundError
from app.core.logging import logger, session_id_ctx
from app.models.session import (
    CreateSessionRequest,
    Session,
    SessionEvent,
    SessionState,
    TERMINAL_STATES,
)
from app.repositories.base import BaseSessionRepository
from app.repositories.in_memory_session import (
    InMemorySessionRepository,
    get_session_repository,
)


class SessionService:
    """Service layer managing voice session lifecycles, idempotency, and events."""

    def __init__(
        self,
        repository: BaseSessionRepository,
        settings: Optional[Settings] = None,
    ) -> None:
        self.repository = repository
        self.settings = settings or get_settings()

    async def create_session(
        self,
        request: Optional[CreateSessionRequest] = None,
        is_mock: bool = False,
    ) -> Tuple[Session, SessionEvent]:
        """Create a new session with initial state and start event."""
        req = request or CreateSessionRequest()
        user_id = req.user_id if req.user_id else "anonymous-user"
        metadata = req.metadata if req.metadata else {}
        ttl = req.ttl_seconds or self.settings.session_ttl_seconds

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl)

        prefix = "mock-sess" if is_mock else "sess"
        evt_prefix = "mock-evt" if is_mock else "evt"
        uid = uuid.uuid4().hex[:10]
        session_id = f"{prefix}-{uid}"
        event_id = f"{evt_prefix}-{uid}"

        base_meta = {
            "mode": "mock" if (is_mock or self.settings.mock_mode) else "production",
            "team": self.settings.team,
            "workstream": self.settings.workstream,
            **metadata,
        }

        session = Session(
            session_id=session_id,
            user_id=user_id,
            state=SessionState.ACTIVE,
            metadata=base_meta,
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
        )

        stored_session = await self.repository.create(session)

        # Set session context for logging
        session_id_ctx.set(session_id)

        initial_payload = {
            "message": "Voice session initialized successfully",
            "user_id": user_id,
            "ttl_seconds": ttl,
            "expires_at": expires_at.isoformat(),
            "mock_mode": self.settings.mock_mode or is_mock,
        }
        if is_mock:
            initial_payload.update({
                "bot_name": "Academiaai-Voicebot",
                "audio_channel": "mock-stream",
                "sample_rate_hz": 16000,
                "codec": "pcm_s16le",
                "initial_prompt": (
                    "Hello! Welcome to Academiaai. How can I assist you with your academic queries today?"
                ),
            })

        event = SessionEvent(
            event_id=event_id,
            session_id=session_id,
            event_type="session.started",
            payload=initial_payload,
            timestamp=now,
        )

        stored_event = await self.repository.add_event(session_id, event)
        logger.info(f"Created session: {session_id} for user={user_id} with ttl={ttl}s")
        return stored_session, stored_event

    async def get_session(
        self, session_id: str, check_expiry: bool = True
    ) -> Session:
        """Retrieve session by ID, automatically evaluating expiry if requested."""
        session_id_ctx.set(session_id)
        session = await self.repository.get_by_id(session_id)
        if not session:
            raise SessionNotFoundError(session_id)

        if check_expiry and session.is_expired():
            logger.info(f"Session {session_id} has passed expiry ({session.expires_at}). Triggering automatic expiry.")
            session, _ = await self.expire_session(session_id, reason="Session TTL expired automatically")

        return session

    async def list_sessions(self, check_expiry: bool = True) -> List[Session]:
        """List all sessions, applying auto-expiry where needed."""
        sessions = await self.repository.list_all()
        result = []
        for s in sessions:
            if check_expiry and s.is_expired():
                expired_s, _ = await self.expire_session(s.session_id, reason="Session TTL expired")
                result.append(expired_s)
            else:
                result.append(s)
        return result

    async def pause_session(
        self, session_id: str, reason: Optional[str] = None
    ) -> Tuple[Session, Optional[SessionEvent]]:
        """Pause an active or idle session. Idempotent if already paused."""
        session_id_ctx.set(session_id)
        session = await self.get_session(session_id, check_expiry=True)

        # Idempotency check: repeated calls do nothing
        if session.state == SessionState.PAUSED:
            logger.info(f"Session {session_id} already PAUSED; returning idempotently without duplicate event.")
            return session, None

        # Transition state (enforces validity, e.g. terminal state rejection)
        session.transition_to(SessionState.PAUSED)
        now = datetime.now(timezone.utc)
        if reason:
            session.metadata["pause_reason"] = reason
        session.metadata["paused_at"] = now.isoformat()

        updated_session = await self.repository.update(session)

        # Record lifecycle event
        event = SessionEvent(
            event_id=f"evt-pause-{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            event_type="session.paused",
            payload={
                "reason": reason or "Session paused by user request",
                "paused_at": now.isoformat(),
            },
            timestamp=now,
        )
        stored_event = await self.repository.add_event(session_id, event)
        logger.info(f"Paused session {session_id}")
        return updated_session, stored_event

    async def resume_session(
        self, session_id: str, reason: Optional[str] = None
    ) -> Tuple[Session, Optional[SessionEvent]]:
        """Resume a paused session. Idempotent if already active."""
        session_id_ctx.set(session_id)
        session = await self.get_session(session_id, check_expiry=True)

        # Idempotency check: repeated calls do nothing
        if session.state == SessionState.ACTIVE:
            logger.info(f"Session {session_id} already ACTIVE; returning idempotently without duplicate event.")
            return session, None

        # Transition state (valid only from PAUSED or IDLE)
        session.transition_to(SessionState.ACTIVE)
        now = datetime.now(timezone.utc)
        # Refresh expiry on resume
        session.expires_at = now + timedelta(seconds=self.settings.session_ttl_seconds)
        if reason:
            session.metadata["resume_reason"] = reason
        session.metadata["resumed_at"] = now.isoformat()

        updated_session = await self.repository.update(session)

        # Record lifecycle event
        event = SessionEvent(
            event_id=f"evt-resume-{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            event_type="session.resumed",
            payload={
                "reason": reason or "Session resumed by user request",
                "resumed_at": now.isoformat(),
                "new_expires_at": session.expires_at.isoformat(),
            },
            timestamp=now,
        )
        stored_event = await self.repository.add_event(session_id, event)
        logger.info(f"Resumed session {session_id}")
        return updated_session, stored_event

    async def stop_session(
        self, session_id: str, reason: Optional[str] = None
    ) -> Tuple[Session, Optional[SessionEvent]]:
        """Stop/complete a session. Idempotent if already completed."""
        session_id_ctx.set(session_id)
        session = await self.get_session(session_id, check_expiry=True)

        # Idempotency check: repeated calls do nothing
        if session.state == SessionState.COMPLETED:
            logger.info(f"Session {session_id} already COMPLETED; returning idempotently without duplicate event.")
            return session, None

        # Transition state to COMPLETED
        session.transition_to(SessionState.COMPLETED)
        now = datetime.now(timezone.utc)
        if reason:
            session.metadata["stop_reason"] = reason
        session.metadata["stopped_at"] = now.isoformat()

        updated_session = await self.repository.update(session)

        # Record lifecycle event
        event = SessionEvent(
            event_id=f"evt-stop-{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            event_type="session.stopped",
            payload={
                "reason": reason or "Session terminated by user request",
                "stopped_at": now.isoformat(),
            },
            timestamp=now,
        )
        stored_event = await self.repository.add_event(session_id, event)
        logger.info(f"Stopped session {session_id}")
        return updated_session, stored_event

    async def expire_session(
        self, session_id: str, reason: Optional[str] = None
    ) -> Tuple[Session, Optional[SessionEvent]]:
        """Explicitly or automatically expire a session. Idempotent if already expired."""
        session_id_ctx.set(session_id)
        # Avoid recursive auto-expiry check
        session = await self.repository.get_by_id(session_id)
        if not session:
            raise SessionNotFoundError(session_id)

        # Idempotency check: repeated calls do nothing
        if session.state == SessionState.EXPIRED:
            logger.info(f"Session {session_id} already EXPIRED; returning idempotently without duplicate event.")
            return session, None

        # Transition state to EXPIRED
        session.transition_to(SessionState.EXPIRED)
        now = datetime.now(timezone.utc)
        if reason:
            session.metadata["expire_reason"] = reason
        session.metadata["expired_at"] = now.isoformat()

        updated_session = await self.repository.update(session)

        # Record lifecycle event
        event = SessionEvent(
            event_id=f"evt-expire-{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            event_type="session.expired",
            payload={
                "reason": reason or "Session expired due to TTL timeout",
                "expired_at": now.isoformat(),
            },
            timestamp=now,
        )
        stored_event = await self.repository.add_event(session_id, event)
        logger.info(f"Expired session {session_id}")
        return updated_session, stored_event

    async def transition_state(
        self,
        session_id: str,
        target_state: SessionState,
        reason: Optional[str] = None,
    ) -> Tuple[Session, Optional[SessionEvent]]:
        """Generic state transition router mapping to lifecycle methods."""
        if target_state == SessionState.PAUSED:
            return await self.pause_session(session_id, reason)
        elif target_state == SessionState.ACTIVE:
            return await self.resume_session(session_id, reason)
        elif target_state == SessionState.COMPLETED:
            return await self.stop_session(session_id, reason)
        elif target_state == SessionState.EXPIRED:
            return await self.expire_session(session_id, reason)

        # Other direct transitions (e.g. to IDLE or FAILED)
        session_id_ctx.set(session_id)
        session = await self.get_session(session_id, check_expiry=True)

        if session.state == target_state:
            return session, None

        prev_state = session.state.value
        session.transition_to(target_state)
        now = datetime.now(timezone.utc)
        updated_session = await self.repository.update(session)

        event = SessionEvent(
            event_id=f"evt-trans-{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            event_type="session.state_changed",
            payload={
                "previous_state": prev_state,
                "new_state": target_state.value,
                "reason": reason,
            },
            timestamp=now,
        )
        stored_event = await self.repository.add_event(session_id, event)
        return updated_session, stored_event


def get_session_service(
    repository: InMemorySessionRepository = Depends(get_session_repository),
    settings: Settings = Depends(get_settings),
) -> SessionService:
    """Dependency injection provider for SessionService."""
    return SessionService(repository=repository, settings=settings)

