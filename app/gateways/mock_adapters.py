"""Deterministic mock gateway adapters for local execution and zero-dependency testing."""

import math
import struct
import uuid
from typing import Any, Dict, List, Optional

from app.gateways.protocols import (
    AudioChunkData,
    AudioGatewayProtocol,
    ReasoningGatewayProtocol,
    ReasoningResultData,
    TranscriptionGatewayProtocol,
    TranscriptResult,
    WorkflowGatewayProtocol,
    WorkflowResultData,
)


class MockAudioGatewayAdapter(AudioGatewayProtocol):
    """Deterministic mock adapter providing synthetic PCM audio chunks and VAD (W1)."""

    def __init__(self, sample_rate_hz: int = 16000, chunk_duration_ms: float = 20.0) -> None:
        self.sample_rate_hz = sample_rate_hz
        self.chunk_duration_ms = chunk_duration_ms
        self.samples_per_chunk = int(self.sample_rate_hz * (self.chunk_duration_ms / 1000.0))
        self._status = "ready"

    def set_healthy(self, healthy: bool, status: str = "degraded") -> None:
        """Allow tests to simulate degraded/unavailable component state."""
        self._status = "ready" if healthy else status

    async def capture_chunk(
        self,
        session_id: str,
        sequence_number: int = 0,
        signal_type: str = "speech",
    ) -> AudioChunkData:
        """Generate a deterministic synthetic 16kHz PCM audio chunk."""
        freq = 440.0 if signal_type == "speech" else 0.0
        amplitude = 16000 if signal_type == "speech" else 100

        # Generate sine wave PCM s16le bytes
        pcm_bytes = bytearray()
        for i in range(self.samples_per_chunk):
            t = (sequence_number * self.samples_per_chunk + i) / float(self.sample_rate_hz)
            sample_val = int(amplitude * math.sin(2.0 * math.pi * freq * t))
            pcm_bytes.extend(struct.pack("<h", sample_val))

        is_speech = signal_type == "speech"
        rms_energy = 0.08 if is_speech else 0.001

        return AudioChunkData(
            data=bytes(pcm_bytes),
            sample_rate_hz=self.sample_rate_hz,
            channels=1,
            format_name="pcm_s16le",
            duration_ms=self.chunk_duration_ms,
            sequence_number=sequence_number,
            is_speech=is_speech,
            rms_energy=rms_energy,
            metadata={"source": "MockAudioGatewayAdapter", "signal_type": signal_type},
        )

    async def check_health(self) -> Dict[str, Any]:
        """Report component health status."""
        return {
            "status": self._status,
            "provider": "MockAudioGatewayAdapter",
            "adapter_type": "mock",
            "sample_rate_hz": self.sample_rate_hz,
            "vad": "deterministic_threshold",
        }


class MockTranscriptionGatewayAdapter(TranscriptionGatewayProtocol):
    """Deterministic mock adapter converting audio chunks into academic query text (W2)."""

    def __init__(self, default_text: Optional[str] = None) -> None:
        self.default_text = default_text or "What is the course syllabus and prerequisites for CS-101?"
        self._status = "ready"

    def set_healthy(self, healthy: bool, status: str = "degraded") -> None:
        """Allow tests to simulate degraded/unavailable component state."""
        self._status = "ready" if healthy else status

    async def transcribe(
        self,
        audio_chunk: AudioChunkData,
        session_id: str,
        language: str = "en-US",
    ) -> TranscriptResult:
        """Produce a deterministic transcript for the audio chunk."""
        # If chunk is explicitly silent, return empty transcript
        if not audio_chunk.is_speech and audio_chunk.rms_energy < 0.01:
            return TranscriptResult(
                text="",
                is_final=True,
                confidence=1.0,
                language=language,
                segments=[],
                metadata={"source": "MockTranscriptionGatewayAdapter", "note": "silence"},
            )

        return TranscriptResult(
            text=self.default_text,
            is_final=True,
            confidence=0.98,
            language=language,
            segments=[
                {
                    "start_ms": 0.0,
                    "end_ms": audio_chunk.duration_ms,
                    "text": self.default_text,
                    "confidence": 0.98,
                }
            ],
            metadata={
                "source": "MockTranscriptionGatewayAdapter",
                "chunk_seq": audio_chunk.sequence_number,
            },
        )

    async def check_health(self) -> Dict[str, Any]:
        """Report component health status."""
        return {
            "status": self._status,
            "provider": "MockTranscriptionGatewayAdapter",
            "adapter_type": "mock",
            "supported_languages": ["en-US", "es-ES", "hi-IN"],
        }


class MockReasoningGatewayAdapter(ReasoningGatewayProtocol):
    """Deterministic mock adapter performing academic query reasoning and grounding (W3)."""

    def __init__(self) -> None:
        self._status = "ready"

    def set_healthy(self, healthy: bool, status: str = "degraded") -> None:
        """Allow tests to simulate degraded/unavailable component state."""
        self._status = "ready" if healthy else status

    async def reason(
        self,
        query: str,
        session_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ReasoningResultData:
        """Analyze query against academic context items and synthesize grounded response."""
        result_id = f"rsn-{uuid.uuid4().hex[:8]}"
        q_lower = query.lower()

        if "syllabus" in q_lower or "prerequisite" in q_lower or "cs-101" in q_lower:
            intent = "explain_concept"
            response_text = (
                "CS-101 (Introduction to Computer Science) covers foundational programming concepts in Python, "
                "algorithmic problem-solving, and elementary data structures. Prerequisite: MATH-100 or equivalent."
            )
            grounded_sources = ["catalog:cs-101", "syllabus:2026-fall"]
            reasoning_steps = [
                "Classified student query intent as 'explain_concept'.",
                "Retrieved course catalog entry for CS-101.",
                "Grounded response in syllabus:2026-fall and course prerequisites.",
            ]
            suggested_action = "academic_lookup"
            suggested_action_params = {"course_code": "CS-101"}
        elif "status" in q_lower or "grade" in q_lower or "enroll" in q_lower:
            intent = "student_record_query"
            response_text = (
                "To inspect your enrollment or academic standing, I can initiate a verified academic status lookup."
            )
            grounded_sources = ["student_portal:records"]
            reasoning_steps = [
                "Identified request for student record lookup.",
                "Determined need for automated tool execution.",
            ]
            suggested_action = "student_status_update"
            suggested_action_params = {"action": "check_status"}
        else:
            intent = "general_academic_qa"
            response_text = f"Here is the guidance for your academic query: '{query}'. Let me know if you would like me to lookup specific records."
            grounded_sources = ["general_handbook"]
            reasoning_steps = ["Processed student query using general academic knowledgebase."]
            suggested_action = None
            suggested_action_params = {}

        return ReasoningResultData(
            result_id=result_id,
            query=query,
            intent=intent,
            response_text=response_text,
            confidence_score=0.95,
            grounded_sources=grounded_sources,
            reasoning_steps=reasoning_steps,
            suggested_action=suggested_action,
            suggested_action_params=suggested_action_params,
            metadata={"source": "MockReasoningGatewayAdapter"},
        )

    async def check_health(self) -> Dict[str, Any]:
        """Report component health status."""
        return {
            "status": self._status,
            "provider": "MockReasoningGatewayAdapter",
            "adapter_type": "mock",
            "model_version": "v1.2-deterministic",
        }


class MockWorkflowGatewayAdapter(WorkflowGatewayProtocol):
    """Deterministic mock adapter executing agentic workflow plans and tools (W4)."""

    def __init__(self) -> None:
        self._status = "ready"

    def set_healthy(self, healthy: bool, status: str = "degraded") -> None:
        """Allow tests to simulate degraded/unavailable component state."""
        self._status = "ready" if healthy else status

    async def execute_plan(
        self,
        goal: str,
        session_id: str,
        steps: Optional[List[Dict[str, Any]]] = None,
    ) -> WorkflowResultData:
        """Execute a simulated agentic workflow plan."""
        workflow_id = f"wf-{uuid.uuid4().hex[:8]}"

        executed_steps = [
            {
                "step_id": f"step-{uuid.uuid4().hex[:6]}",
                "tool_name": "academic_lookup",
                "status": "completed",
                "output": {
                    "course_code": "CS-101",
                    "term": "Fall 2026",
                    "credits": 4,
                    "instructor": "Dr. Alan Turing",
                    "prerequisites_met": True,
                },
            }
        ]

        output = {
            "goal": goal,
            "session_id": session_id,
            "result_summary": f"Successfully completed academic workflow for goal: '{goal}'.",
            "student_record": {
                "academic_standing": "Good",
                "eligible_courses": ["CS-101", "MATH-201"],
            },
        }

        return WorkflowResultData(
            workflow_id=workflow_id,
            goal=goal,
            success=True,
            status="succeeded",
            output=output,
            error=None,
            executed_steps=executed_steps,
            metadata={"source": "MockWorkflowGatewayAdapter"},
        )

    async def check_health(self) -> Dict[str, Any]:
        """Report component health status."""
        return {
            "status": self._status,
            "provider": "MockWorkflowGatewayAdapter",
            "adapter_type": "mock",
            "tool_registry": ["academic_lookup", "student_status_update"],
        }
