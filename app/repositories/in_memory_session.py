"""In-memory implementation of the Session repository for Week 1."""

import asyncio
from typing import Dict, List, Optional

from app.core.logging import logger
from app.models.session import Session, SessionEvent
from app.repositories.base import BaseSessionRepository


class InMemorySessionRepository(BaseSessionRepository):
    """Thread-safe in-memory session and event repository."""

    def __init__(self) -> None:
        self._sessions: Dict[str, Session] = {}
        self._events: Dict[str, List[SessionEvent]] = {}
        self._lock = asyncio.Lock()

    async def create(self, session: Session) -> Session:
        """Store a new session."""
        async with self._lock:
            # Copy model to prevent shared reference mutations
            stored = session.model_copy(deep=True)
            self._sessions[session.session_id] = stored
            if session.session_id not in self._events:
                self._events[session.session_id] = []
            logger.info(f"Session stored in memory: {session.session_id} [state={session.state.value}]")
            return stored.model_copy(deep=True)

    async def get_by_id(self, session_id: str) -> Optional[Session]:
        """Retrieve a session by ID."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            return session.model_copy(deep=True)

    async def update(self, session: Session) -> Session:
        """Update an existing session."""
        async with self._lock:
            if session.session_id not in self._sessions:
                raise KeyError(f"Session {session.session_id} not found for update")
            updated = session.model_copy(deep=True)
            self._sessions[session.session_id] = updated
            logger.info(f"Session updated: {session.session_id} [state={session.state.value}]")
            return updated.model_copy(deep=True)

    async def list_all(self) -> List[Session]:
        """List all stored sessions."""
        async with self._lock:
            return [s.model_copy(deep=True) for s in self._sessions.values()]

    async def add_event(self, session_id: str, event: SessionEvent) -> SessionEvent:
        """Append an event to a session."""
        async with self._lock:
            if session_id not in self._events:
                self._events[session_id] = []
            event_copy = event.model_copy(deep=True)
            self._events[session_id].append(event_copy)
            logger.info(f"Event added for session {session_id}: {event.event_type} [id={event.event_id}]")
            return event_copy.model_copy(deep=True)

    async def get_events(self, session_id: str) -> List[SessionEvent]:
        """Retrieve events for a session."""
        async with self._lock:
            events = self._events.get(session_id, [])
            return [e.model_copy(deep=True) for e in events]

    async def clear(self) -> None:
        """Clear all stored sessions and events."""
        async with self._lock:
            self._sessions.clear()
            self._events.clear()
            logger.info("In-memory repository cleared.")


# Singleton repository instance
_in_memory_repo_instance: Optional[InMemorySessionRepository] = None


def get_session_repository() -> InMemorySessionRepository:
    """Dependency injection provider for the session repository."""
    global _in_memory_repo_instance
    if _in_memory_repo_instance is None:
        _in_memory_repo_instance = InMemorySessionRepository()
    return _in_memory_repo_instance
