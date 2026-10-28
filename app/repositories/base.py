"""Abstract repository interface for session persistence."""

from abc import ABC, abstractmethod
from typing import List, Optional

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
        """Append an event to a session's event history."""
        pass

    @abstractmethod
    async def get_events(self, session_id: str) -> List[SessionEvent]:
        """Retrieve all events associated with a session ID."""
        pass

    @abstractmethod
    async def clear(self) -> None:
        """Clear all stored data (for test isolation)."""
        pass
