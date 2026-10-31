"""Unit tests for the In-Memory Session Repository."""

import pytest
from datetime import datetime, timezone

from app.models.session import Session, SessionEvent, SessionState
from app.repositories.in_memory_session import InMemorySessionRepository


@pytest.mark.asyncio
async def test_repository_create_and_get():
    """Verify storing and retrieving sessions."""
    repo = InMemorySessionRepository()
    now = datetime.now(timezone.utc)
    session = Session(
        session_id="sess-001",
        user_id="user-001",
        state=SessionState.ACTIVE,
        metadata={"test": "val"},
        created_at=now,
        updated_at=now,
    )

    created = await repo.create(session)
    assert created.session_id == "sess-001"
    assert created.user_id == "user-001"

    retrieved = await repo.get_by_id("sess-001")
    assert retrieved is not None
    assert retrieved.session_id == "sess-001"
    assert retrieved.state == SessionState.ACTIVE


@pytest.mark.asyncio
async def test_repository_get_nonexistent():
    """Verify retrieving non-existent returns None."""
    repo = InMemorySessionRepository()
    retrieved = await repo.get_by_id("nonexistent")
    assert retrieved is None


@pytest.mark.asyncio
async def test_repository_update_session():
    """Verify updating a session."""
    repo = InMemorySessionRepository()
    now = datetime.now(timezone.utc)
    session = Session(
        session_id="sess-002",
        user_id="user-002",
        state=SessionState.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    await repo.create(session)

    session.state = SessionState.IDLE
    updated = await repo.update(session)
    assert updated.state == SessionState.IDLE

    fetched = await repo.get_by_id("sess-002")
    assert fetched is not None
    assert fetched.state == SessionState.IDLE


@pytest.mark.asyncio
async def test_repository_events_storage():
    """Verify appending and retrieving events for a session."""
    repo = InMemorySessionRepository()
    now = datetime.now(timezone.utc)
    session = Session(
        session_id="sess-003",
        user_id="user-003",
        state=SessionState.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    await repo.create(session)

    event1 = SessionEvent(
        event_id="evt-1",
        session_id="sess-003",
        event_type="session.started",
        payload={"msg": "hello"},
        timestamp=now,
    )
    event2 = SessionEvent(
        event_id="evt-2",
        session_id="sess-003",
        event_type="mock.audio.prompt",
        payload={"audio": "ready"},
        timestamp=now,
    )

    await repo.add_event("sess-003", event1)
    await repo.add_event("sess-003", event2)

    events = await repo.get_events("sess-003")
    assert len(events) == 2
    assert events[0].event_type == "session.started"
    assert events[1].event_type == "mock.audio.prompt"


@pytest.mark.asyncio
async def test_repository_clear():
    """Verify clear empties all data."""
    repo = InMemorySessionRepository()
    now = datetime.now(timezone.utc)
    session = Session(
        session_id="sess-004",
        user_id="user-004",
        state=SessionState.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    await repo.create(session)
    assert len(await repo.list_all()) == 1

    await repo.clear()
    assert len(await repo.list_all()) == 0
