"""Abstract repository interface for session persistence."""

import asyncio
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

from app.models.session import Session, SessionEvent


class BaseSessionRepository(ABC):
    """Abstract interface defining session storage operations."""

    @abstractmethod
    async def create(self, session: Session) -> Session:
        """Store a new session."""
        pass

    @abstractmethod
    async def get_by_id(self, session_id: str) -> Optional[Session]:
        """Retrieve a session by its ID."""
        pass

    @abstractmethod
    async def update(self, session: Session) -> Session:
        """Update an existing session."""
        pass

    @abstractmethod
    async def list_all(self) -> List[Session]:
        """List all stored sessions."""
        pass

    @abstractmethod
    async def add_event(self, session_id: str, event: SessionEvent) -> SessionEvent:
        """Append an event to a session's event history and notify active subscribers."""
        pass

    @abstractmethod
    async def get_events(
        self, session_id: str, since_event_id: Optional[str] = None
    ) -> List[SessionEvent]:
        """Retrieve chronological events associated with a session ID, optionally after since_event_id."""
        pass

    @abstractmethod
    async def subscribe_events(self, session_id: str) -> asyncio.Queue:
        """Subscribe to real-time events for a session."""
        pass

    @abstractmethod
    async def unsubscribe_events(self, session_id: str, queue: asyncio.Queue) -> None:
        """Unsubscribe from real-time events for a session."""
        pass

    @abstractmethod
    async def subscribe_and_replay(
        self,
        session_id: str,
        since_event_id: Optional[str] = None,
        since_seq: Optional[int] = None,
    ) -> Tuple[List[SessionEvent], asyncio.Queue]:
        """Atomically register a subscriber and capture historical events under a single lock boundary."""
        pass

    @abstractmethod
    async def has_overflowed(self, session_id: str, queue: asyncio.Queue) -> bool:
        """Check if a subscriber queue experienced overflow due to backpressure."""
        pass

    @abstractmethod
    async def clear(self) -> None:
        """Clear all stored data (for test isolation)."""
        pass
