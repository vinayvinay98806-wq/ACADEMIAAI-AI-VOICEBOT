"""Tests for Event Replay, Reconnect, and Monotonic Event Sequencing (W5 Week 3)."""

import asyncio
import json
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.session import SessionEvent
from app.repositories.in_memory_session import get_session_repository


@pytest.mark.asyncio
async def test_monotonic_sequence_numbers():
    """Verify every event added to a session receives a strictly monotonic sequence number."""
    repo = get_session_repository()
    session_id = "test-seq-sess"

    evt1 = SessionEvent(session_id=session_id, event_type="test.event_1", payload={"step": 1})
    evt2 = SessionEvent(session_id=session_id, event_type="test.event_2", payload={"step": 2})
    evt3 = SessionEvent(session_id=session_id, event_type="test.event_3", payload={"step": 3})

    res1 = await repo.add_event(session_id, evt1)
    res2 = await repo.add_event(session_id, evt2)
    res3 = await repo.add_event(session_id, evt3)

    assert res1.sequence_number == 1
    assert res2.sequence_number == 2
    assert res3.sequence_number == 3

    events = await repo.get_events(session_id)
    assert len(events) == 3
    assert [e.sequence_number for e in events] == [1, 2, 3]


@pytest.mark.asyncio
async def test_subscribe_and_replay_atomicity():
    """Verify subscribe_and_replay captures history and registers queue atomically."""
    repo = get_session_repository()
    session_id = "test-atomic-sess"

    # Pre-populate 3 events
    for i in range(1, 4):
        await repo.add_event(
            session_id,
            SessionEvent(session_id=session_id, event_type=f"event.{i}", payload={"n": i}),
        )

    # Subscribe and replay from beginning
    history, queue = await repo.subscribe_and_replay(session_id=session_id)
    assert len(history) == 3
    assert [e.payload["n"] for e in history] == [1, 2, 3]

    # Add a live event
    live_evt = SessionEvent(session_id=session_id, event_type="event.live", payload={"n": 4})
    await repo.add_event(session_id, live_evt)

    # Queue should receive the live event
    received = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert received.payload["n"] == 4
    assert received.sequence_number == 4

    await repo.unsubscribe_events(session_id, queue)


@pytest.mark.asyncio
async def test_subscribe_and_replay_with_cursor():
    """Verify replaying events strictly after since_event_id."""
    repo = get_session_repository()
    session_id = "test-cursor-sess"

    emitted = []
    for i in range(1, 6):
        evt = await repo.add_event(
            session_id,
            SessionEvent(session_id=session_id, event_type=f"event.{i}", payload={"n": i}),
        )
        emitted.append(evt)

    cursor_id = emitted[2].event_id  # After event 3 (index 2)

    history, queue = await repo.subscribe_and_replay(
        session_id=session_id,
        since_event_id=cursor_id,
    )
    # Should only contain event 4 and 5
    assert len(history) == 2
    assert [e.payload["n"] for e in history] == [4, 5]

    await repo.unsubscribe_events(session_id, queue)


@pytest.mark.asyncio
async def test_subscribe_and_replay_unknown_cursor():
    """Verify invalid/unknown cursor falls back safely to returning all events without error."""
    repo = get_session_repository()
    session_id = "test-unknown-cursor"

    for i in range(1, 4):
        await repo.add_event(
            session_id,
            SessionEvent(session_id=session_id, event_type=f"event.{i}", payload={"n": i}),
        )

    history, queue = await repo.subscribe_and_replay(
        session_id=session_id,
        since_event_id="evt-non-existent-999",
    )
    assert len(history) == 3
    assert [e.payload["n"] for e in history] == [1, 2, 3]

    await repo.unsubscribe_events(session_id, queue)


def test_sse_endpoint_replay_all_events(client: TestClient):
    """Test SSE stream endpoint replays historical events."""
    create_res = client.post("/api/v1/sessions")
    sess_id = create_res.json()["data"]["session"]["session_id"]

    # Trigger interaction to generate events
    client.post(
        f"/api/v1/sessions/{sess_id}/interact",
        json={"user_query": "What courses are available?"},
    )

    # Connect to SSE without follow
    res = client.get(f"/api/v1/sessions/{sess_id}/events/stream?follow=false")
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]

    body = res.text
    assert f": connected to session {sess_id}" in body
    assert "event: session.started" in body
    assert "event: gateway.transcription_completed" in body
    assert "event: gateway.reasoning_completed" in body
    assert "event: gateway.workflow_executed" in body
    assert "event: gateway.interaction_completed" in body


def test_sse_reconnect_with_last_event_id_header(client: TestClient):
    """Test SSE reconnect using Last-Event-ID header skips already delivered events."""
    create_res = client.post("/api/v1/sessions")
    sess_id = create_res.json()["data"]["session"]["session_id"]

    # Initial interaction
    client.post(
        f"/api/v1/sessions/{sess_id}/interact",
        json={"user_query": "First question"},
    )

    # Get events list to extract an intermediate event ID
    events_res = client.get(f"/api/v1/sessions/{sess_id}/events")
    events = events_res.json()["events"]
    assert len(events) >= 5

    # Pick the 3rd event as Last-Event-ID
    last_event = events[2]
    last_event_id = last_event["event_id"]

    # Reconnect with Last-Event-ID
    reconnect_res = client.get(
        f"/api/v1/sessions/{sess_id}/events/stream?follow=false",
        headers={"Last-Event-ID": last_event_id},
    )
    assert reconnect_res.status_code == 200
    body = reconnect_res.text

    # The 1st and 2nd events must NOT appear in the replayed data
    assert f"id: {events[0]['event_id']}" not in body
    assert f"id: {events[1]['event_id']}" not in body
    assert f"id: {last_event_id}" not in body

    # Subsequent events must appear
    assert f"id: {events[3]['event_id']}" in body
    assert f"id: {events[4]['event_id']}" in body


@pytest.mark.asyncio
async def test_queue_overflow_tracking():
    """Verify repository detects bounded queue overflow when subscriber is slow."""
    repo = get_session_repository()
    session_id = "test-overflow-sess"

    history, queue = await repo.subscribe_and_replay(session_id=session_id)

    # Initially not overflowed
    assert not await repo.has_overflowed(session_id, queue)

    # Add 105 events (exceeding queue maxsize=100)
    for i in range(105):
        await repo.add_event(
            session_id,
            SessionEvent(session_id=session_id, event_type="spam.event", payload={"i": i}),
        )

    # Now overflow should be detected
    assert await repo.has_overflowed(session_id, queue)

    await repo.unsubscribe_events(session_id, queue)


@pytest.mark.asyncio
async def test_clean_unsubscription():
    """Verify unsubscribing cleanly removes queues from active subscribers."""
    repo = get_session_repository()
    session_id = "test-unsub-sess"

    h1, q1 = await repo.subscribe_and_replay(session_id)
    h2, q2 = await repo.subscribe_and_replay(session_id)

    assert len(repo._subscribers[session_id]) == 2

    await repo.unsubscribe_events(session_id, q1)
    assert len(repo._subscribers[session_id]) == 1

    await repo.unsubscribe_events(session_id, q2)
    assert len(repo._subscribers[session_id]) == 0
