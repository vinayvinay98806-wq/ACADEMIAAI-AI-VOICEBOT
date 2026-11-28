"""Typed protocols and cross-workstream data contracts for W5 Module Gateways."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@dataclass
class AudioChunkData:
    """Standardized transport representation of an audio chunk (W1 contract)."""

    data: bytes
    sample_rate_hz: int = 16000
    channels: int = 1
    format_name: str = "pcm_s16le"
    duration_ms: float = 20.0
    sequence_number: int = 0
    is_speech: bool = True
    rms_energy: float = 0.05
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sample_rate_hz": self.sample_rate_hz,
            "channels": self.channels,
            "format_name": self.format_name,
            "duration_ms": self.duration_ms,
            "sequence_number": self.sequence_number,
            "is_speech": self.is_speech,
            "rms_energy": self.rms_energy,
            "byte_length": len(self.data),
            "metadata": self.metadata,
        }


@dataclass
class TranscriptResult:
    """Standardized transport representation of speech transcription (W2 contract)."""

    text: str
    is_final: bool = True
    confidence: float = 0.98
    language: str = "en-US"
    segments: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "is_final": self.is_final,
            "confidence": self.confidence,
            "language": self.language,
            "segments_count": len(self.segments),
            "metadata": self.metadata,
        }


@dataclass
class ReasoningResultData:
    """Standardized transport representation of reasoning outcome (W3 contract)."""

    result_id: str
    query: str
    intent: str
    response_text: str
    confidence_score: float = 1.0
    grounded_sources: List[str] = field(default_factory=list)
    reasoning_steps: List[str] = field(default_factory=list)
    suggested_action: Optional[str] = None
    suggested_action_params: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "result_id": self.result_id,
            "query": self.query,
            "intent": self.intent,
            "response_text": self.response_text,
            "confidence_score": self.confidence_score,
            "grounded_sources": self.grounded_sources,
            "reasoning_steps": self.reasoning_steps,
            "suggested_action": self.suggested_action,
            "suggested_action_params": self.suggested_action_params,
            "metadata": self.metadata,
        }


@dataclass
class WorkflowResultData:
    """Standardized transport representation of workflow plan execution (W4 contract)."""

    workflow_id: str
    goal: str
    success: bool
    status: str
    output: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    executed_steps: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "goal": self.goal,
            "success": self.success,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "executed_steps_count": len(self.executed_steps),
            "metadata": self.metadata,
        }


@runtime_checkable
class AudioGatewayProtocol(Protocol):
    """Protocol for audio input capture and VAD processing (W1 Gateway)."""

    async def capture_chunk(
        self,
        session_id: str,
        sequence_number: int = 0,
        signal_type: str = "speech",
    ) -> AudioChunkData:
        """Capture or synthesize an audio chunk with VAD metadata."""
        ...

    async def check_health(self) -> Dict[str, Any]:
        """Verify gateway health status."""
        ...


@runtime_checkable
class TranscriptionGatewayProtocol(Protocol):
    """Protocol for audio-to-text transcription (W2 Gateway)."""

    async def transcribe(
        self,
        audio_chunk: AudioChunkData,
        session_id: str,
        language: str = "en-US",
    ) -> TranscriptResult:
        """Transcribe an audio chunk into text."""
        ...

    async def check_health(self) -> Dict[str, Any]:
        """Verify gateway health status."""
        ...


@runtime_checkable
class ReasoningGatewayProtocol(Protocol):
    """Protocol for academic context reasoning and grounding (W3 Gateway)."""

    async def reason(
        self,
        query: str,
        session_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ReasoningResultData:
        """Analyze query against student academic context."""
        ...

    async def check_health(self) -> Dict[str, Any]:
        """Verify gateway health status."""
        ...


@runtime_checkable
class WorkflowGatewayProtocol(Protocol):
    """Protocol for agentic workflow plan execution (W4 Gateway)."""

    async def execute_plan(
        self,
        goal: str,
        session_id: str,
        steps: Optional[List[Dict[str, Any]]] = None,
    ) -> WorkflowResultData:
        """Execute or simulate an agentic workflow plan."""
        ...

    async def check_health(self) -> Dict[str, Any]:
        """Verify gateway health status."""
        ...
