"""Unit and integration tests for Module Gateways (Day 15-16)."""

import asyncio
import pytest
from fastapi.testclient import TestClient

from app.gateways.coordinator import GatewayCoordinator
from app.gateways.mock_adapters import (
    MockAudioGatewayAdapter,
    MockReasoningGatewayAdapter,
    MockTranscriptionGatewayAdapter,
    MockWorkflowGatewayAdapter,
)
from app.gateways.protocols import (
    AudioChunkData,
    AudioGatewayProtocol,
    ReasoningGatewayProtocol,
    TranscriptionGatewayProtocol,
    WorkflowGatewayProtocol,
)
from app.repositories.in_memory_session import InMemorySessionRepository


@pytest.mark.asyncio
async def test_mock_audio_gateway_adapter():
    """Verify MockAudioGatewayAdapter generates deterministic PCM chunks with speech VAD."""
    adapter = MockAudioGatewayAdapter(sample_rate_hz=16000, chunk_duration_ms=20.0)
    chunk = await adapter.capture_chunk(session_id="test-sess", sequence_number=1, signal_type="speech")

    assert isinstance(chunk, AudioChunkData)
    assert chunk.sample_rate_hz == 16000
    assert chunk.channels == 1
    assert chunk.format_name == "pcm_s16le"
    assert chunk.sequence_number == 1
    assert chunk.is_speech is True
    assert chunk.rms_energy > 0.01
    assert len(chunk.data) == int(16000 * 0.02 * 2)  # 640 bytes for 20ms s16le

    health = await adapter.check_health()
    assert health["status"] == "ready"
    assert health["provider"] == "MockAudioGatewayAdapter"


@pytest.mark.asyncio
async def test_mock_transcription_gateway_adapter():
    """Verify MockTranscriptionGatewayAdapter transcribes audio chunks deterministically."""
    audio_adapter = MockAudioGatewayAdapter()
    chunk = await audio_adapter.capture_chunk(session_id="test-sess")

    stt_adapter = MockTranscriptionGatewayAdapter()
    res = await stt_adapter.transcribe(chunk, session_id="test-sess", language="en-US")

    assert res.text != ""
    assert res.is_final is True
    assert res.confidence >= 0.95
    assert len(res.segments) >= 1

    health = await stt_adapter.check_health()
    assert health["status"] == "ready"


@pytest.mark.asyncio
async def test_mock_reasoning_gateway_adapter():
    """Verify MockReasoningGatewayAdapter performs academic intent classification and grounding."""
    reasoning_adapter = MockReasoningGatewayAdapter()
    res = await reasoning_adapter.reason(
        query="What is the syllabus for CS-101?",
        session_id="test-sess",
    )

    assert res.intent == "explain_concept"
    assert "CS-101" in res.response_text
    assert len(res.grounded_sources) >= 1
    assert res.suggested_action == "academic_lookup"
    assert len(res.reasoning_steps) >= 1

    health = await reasoning_adapter.check_health()
    assert health["status"] == "ready"


@pytest.mark.asyncio
async def test_mock_workflow_gateway_adapter():
    """Verify MockWorkflowGatewayAdapter simulates agentic tool execution."""
    wf_adapter = MockWorkflowGatewayAdapter()
    res = await wf_adapter.execute_plan(goal="academic_lookup", session_id="test-sess")

    assert res.success is True
    assert res.status == "succeeded"
    assert "student_record" in res.output
    assert len(res.executed_steps) >= 1

    health = await wf_adapter.check_health()
    assert health["status"] == "ready"


@pytest.mark.asyncio
async def test_gateway_coordinator_full_pipeline():
    """Verify GatewayCoordinator executes Audio -> STT -> Reasoning -> Workflow pipeline with event logging."""
    repo = InMemorySessionRepository()
    coord = GatewayCoordinator(
        audio_gateway=MockAudioGatewayAdapter(),
        transcription_gateway=MockTranscriptionGatewayAdapter(),
        reasoning_gateway=MockReasoningGatewayAdapter(),
        workflow_gateway=MockWorkflowGatewayAdapter(),
        repository=repo,
    )

    # Initialize a dummy session
    from app.models.session import Session, SessionState
    sess = Session(session_id="gw-sess-101", state=SessionState.ACTIVE)
    await repo.create(sess)

    result = await coord.process_interaction(
        session_id="gw-sess-101",
        timeout_seconds=5.0,
    )

    assert result.session_id == "gw-sess-101"
    assert result.transcript is not None
    assert result.reasoning is not None
    assert result.workflow is not None
    assert len(result.events_emitted) == 5

    # Verify chronological events recorded in repository
    events = await repo.get_events("gw-sess-101")
    event_types = [e.event_type for e in events]
    assert event_types == [
        "gateway.audio_processed",
        "gateway.transcription_completed",
        "gateway.reasoning_completed",
        "gateway.workflow_executed",
        "gateway.interaction_completed",
    ]

    # Verify ID propagation in event payloads
    for e in events:
        assert e.payload["request_id"] == result.request_id
        assert e.payload["correlation_id"] == result.correlation_id


@pytest.mark.asyncio
async def test_gateway_coordinator_timeout_handling():
    """Verify GatewayCoordinator catches downstream timeout and normalizes into GatewayTimeoutError."""
    repo = InMemorySessionRepository()

    class SlowReasoningAdapter(ReasoningGatewayProtocol):
        async def reason(self, query: str, session_id: str, context=None):
            await asyncio.sleep(1.0)
            return None

        async def check_health(self):
            return {"status": "ready"}

    coord = GatewayCoordinator(
        audio_gateway=MockAudioGatewayAdapter(),
        transcription_gateway=MockTranscriptionGatewayAdapter(),
        reasoning_gateway=SlowReasoningAdapter(),
        workflow_gateway=MockWorkflowGatewayAdapter(),
        repository=repo,
    )

    from app.core.exceptions import GatewayTimeoutError
    with pytest.raises(GatewayTimeoutError) as exc_info:
        await coord.process_interaction(
            session_id="timeout-sess",
            timeout_seconds=0.1,  # Short timeout
        )
    assert "W3_Reasoning" in str(exc_info.value)

    # Verify failure event was recorded in session
    events = await repo.get_events("timeout-sess")
    assert any(e.event_type == "gateway.interaction_failed" for e in events)


def test_session_interact_endpoint(client: TestClient):
    """Verify POST /api/v1/sessions/{session_id}/interact triggers complete pipeline."""
    # Create session
    create_res = client.post("/api/v1/sessions")
    sess_id = create_res.json()["data"]["session"]["session_id"]

    # Trigger interaction
    interact_res = client.post(
        f"/api/v1/sessions/{sess_id}/interact",
        json={"user_query": "What is the syllabus for CS-101?"},
    )
    assert interact_res.status_code == 200
    data = interact_res.json()

    assert data["success"] is True
    assert data["session_id"] == sess_id
    assert data["transcript"]["text"] == "What is the syllabus for CS-101?"
    assert data["reasoning"]["intent"] == "explain_concept"
    assert data["workflow"]["status"] == "succeeded"
    assert len(data["events_emitted"]) >= 4

    # Interacting with a completed session must raise 409 Conflict
    client.post(f"/api/v1/sessions/{sess_id}/stop")
    bad_interact = client.post(f"/api/v1/sessions/{sess_id}/interact")
    assert bad_interact.status_code == 409
    assert bad_interact.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
