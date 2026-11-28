"""In-memory implementation of the Session repository with event pubsub and atomic replay."""

import asyncio
from typing import Dict, List, Optional, Set, Tuple

from app.core.logging import logger
from app.models.session import Session, SessionEvent
from app.repositories.base import BaseSessionRepository


class InMemorySessionRepository(BaseSessionRepository):
    """Thread-safe in-memory session and event repository with atomic subscriber notifications."""

    def __init__(self) -> None:
        self._sessions: Dict[str, Session] = {}
        self._events: Dict[str, List[SessionEvent]] = {}
        self._subscribers: Dict[str, List[asyncio.Queue[SessionEvent]]] = {}
        self._overflowed_queues: Dict[str, Set[asyncio.Queue[SessionEvent]]] = {}
        self._lock = asyncio.Lock()

    async def create(self, session: Session) -> Session:
        """Store a new session."""
        async with self._lock:
            stored = session.model_copy(deep=True)
            self._sessions[session.session_id] = stored
            if session.session_id not in self._events:
                self._events[session.session_id] = []
            if session.session_id not in self._subscribers:
                self._subscribers[session.session_id] = []
            if session.session_id not in self._overflowed_queues:
                self._overflowed_queues[session.session_id] = set()
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
        """Append an event to a session and notify active subscriber queues."""
        async with self._lock:
            if session_id not in self._events:
                self._events[session_id] = []
            if session_id not in self._subscribers:
                self._subscribers[session_id] = []
            if session_id not in self._overflowed_queues:
                self._overflowed_queues[session_id] = set()

            event_copy = event.model_copy(deep=True)
            # Assign strictly monotonic sequence number within this session
            event_copy.sequence_number = len(self._events[session_id]) + 1
            self._events[session_id].append(event_copy)
            logger.info(
                f"Event added for session {session_id}: {event.event_type} "
                f"[id={event.event_id}, seq={event_copy.sequence_number}]"
            )

            # Broadcast to live subscribers
            queues = self._subscribers.get(session_id, [])
            for q in list(queues):
                try:
                    q.put_nowait(event_copy)
                except asyncio.QueueFull:
                    logger.warning(f"Subscriber queue full for session {session_id}; marking overflow.")
                    self._overflowed_queues[session_id].add(q)

            return event_copy.model_copy(deep=True)

    async def get_events(
        self, session_id: str, since_event_id: Optional[str] = None
    ) -> List[SessionEvent]:
        """Retrieve events for a session, optionally after a specified event ID."""
        async with self._lock:
            events = self._events.get(session_id, [])
            if not since_event_id:
                return [e.model_copy(deep=True) for e in events]

            # Find position of since_event_id
            idx = -1
            for i, evt in enumerate(events):
                if evt.event_id == since_event_id:
                    idx = i
                    break

            if idx == -1:
                # If since_event_id is not found, return all events
                return [e.model_copy(deep=True) for e in events]

            return [e.model_copy(deep=True) for e in events[idx + 1:]]

    async def subscribe_events(self, session_id: str) -> asyncio.Queue[SessionEvent]:
        """Subscribe to real-time events for a session."""
        async with self._lock:
            if session_id not in self._subscribers:
                self._subscribers[session_id] = []
            if session_id not in self._overflowed_queues:
                self._overflowed_queues[session_id] = set()
            q: asyncio.Queue[SessionEvent] = asyncio.Queue(maxsize=100)
            self._subscribers[session_id].append(q)
            logger.info(f"Subscriber connected to session {session_id}")
            return q

    async def unsubscribe_events(
        self, session_id: str, queue: asyncio.Queue[SessionEvent]
    ) -> None:
        """Unsubscribe from real-time events for a session."""
        async with self._lock:
            if session_id in self._subscribers:
                try:
                    self._subscribers[session_id].remove(queue)
                    logger.info(f"Subscriber disconnected from session {session_id}")
                except ValueError:
                    pass
            if session_id in self._overflowed_queues and queue in self._overflowed_queues[session_id]:
                self._overflowed_queues[session_id].discard(queue)

    async def subscribe_and_replay(
        self,
        session_id: str,
        since_event_id: Optional[str] = None,
        since_seq: Optional[int] = None,
    ) -> Tuple[List[SessionEvent], asyncio.Queue[SessionEvent]]:
        """Atomically register a subscriber queue and capture historical events under a single lock boundary.

        Eliminates any race condition between historical replay and live stream ingestion.
        Guarantees zero missed events and zero duplicates.
        """
        async with self._lock:
            if session_id not in self._subscribers:
                self._subscribers[session_id] = []
            if session_id not in self._overflowed_queues:
                self._overflowed_queues[session_id] = set()

            q: asyncio.Queue[SessionEvent] = asyncio.Queue(maxsize=100)
            self._subscribers[session_id].append(q)

            events = self._events.get(session_id, [])
            historical: List[SessionEvent] = []

            if since_seq is not None:
                historical = [
                    e.model_copy(deep=True)
                    for e in events
                    if (e.sequence_number or 0) > since_seq
                ]
            elif since_event_id is not None:
                idx = -1
                for i, evt in enumerate(events):
                    if evt.event_id == since_event_id:
                        idx = i
                        break
                if idx != -1:
                    historical = [e.model_copy(deep=True) for e in events[idx + 1:]]
                else:
                    historical = [e.model_copy(deep=True) for e in events]
            else:
                historical = [e.model_copy(deep=True) for e in events]

            logger.info(
                f"Atomic subscribe_and_replay for {session_id}: "
                f"captured {len(historical)} historical events under lock."
            )
            return historical, q

    async def has_overflowed(self, session_id: str, queue: asyncio.Queue[SessionEvent]) -> bool:
        """Check if a subscriber queue experienced overflow due to backpressure."""
        async with self._lock:
            return queue in self._overflowed_queues.get(session_id, set())

    async def clear(self) -> None:
        """Clear all stored sessions and events."""
        async with self._lock:
            self._sessions.clear()
            self._events.clear()
            self._subscribers.clear()
            self._overflowed_queues.clear()
            logger.info("In-memory repository cleared.")


# Singleton repository instance
_in_memory_repo_instance: Optional[InMemorySessionRepository] = None


def get_session_repository() -> InMemorySessionRepository:
    """Dependency injection provider for the session repository."""
    global _in_memory_repo_instance
    if _in_memory_repo_instance is None:
        _in_memory_repo_instance = InMemorySessionRepository()
    return _in_memory_repo_instance
