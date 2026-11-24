"""Session-aware transcript revisions, finalization, and confidence review."""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Callable, Dict, List, Optional, Set, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from academiaai.audio.schemas import AudioChunk
from w2_stt.adapter import BaseTranscriptionAdapter
from w2_stt.exceptions import (
    STTConfigurationError,
    STTInputError,
    STTPermanentError,
    STTProviderError,
    normalize_provider_error,
    to_transcript_error_info,
)
from w2_stt.orchestrator import OrchestratorConfig, STTOrchestrator
from w2_stt.schemas import TranscriptErrorInfo, TranscriptEvent, TranscriptEventType


class TranscriptUpdateType(str, Enum):
    """Consumer-facing update types derived from W2 transcript events."""

    REVISION = "revision"
    FINALIZATION = "finalization"
    ERROR = "error"


class ConfidencePolicy:
    """Confidence threshold policy; missing scores are always flagged for review."""

    def __init__(self, threshold: float = 0.8) -> None:
        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, (int, float))
            or not math.isfinite(float(threshold))
            or not 0.0 <= threshold <= 1.0
        ):
            raise STTConfigurationError("confidence_threshold must be a finite number in [0.0, 1.0]")
        self.threshold = float(threshold)

    def requires_review(self, confidence: Optional[float]) -> bool:
        """Flag missing or below-threshold scores without discarding transcript text."""
        if confidence is None:
            return True
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(float(confidence))
            or not 0.0 <= confidence <= 1.0
        ):
            raise STTInputError("Transcript confidence must be a finite number in [0.0, 1.0]")
        return confidence < self.threshold


class SessionTranscriptEvent(BaseModel):
    """Session-scoped revision/finalization event for downstream consumers.

    Segment events carry the transcript segment fields directly. Error events omit
    segment-specific fields but retain the session, sequence, type, and timestamp.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1)
    session_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    segment_id: Optional[str] = None
    sequence_id: int = Field(ge=0)
    event_type: TranscriptUpdateType
    timestamp: float = Field(ge=0.0)
    text: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    revision: int = Field(default=0, ge=0)
    review_required: bool = False
    source_event_id: Optional[str] = None
    error: Optional[TranscriptErrorInfo] = None

    @model_validator(mode="after")
    def validate_event_payload(self) -> SessionTranscriptEvent:
        if self.event_type == TranscriptUpdateType.ERROR:
            if self.error is None:
                raise ValueError("Error updates must include normalized error details")
        elif self.segment_id is None or self.text is None:
            raise ValueError("Transcript revisions and finalizations require segment_id and text")
        return self


@dataclass
class _SessionStream:
    session_id: str
    correlation_id: str
    orchestrator: STTOrchestrator
    seen_event_ids: Set[str] = field(default_factory=set)
    last_interim_sequence: Dict[str, int] = field(default_factory=dict)
    revisions: Dict[str, int] = field(default_factory=dict)
    finalized_segment_ids: Set[str] = field(default_factory=set)
    events: List[SessionTranscriptEvent] = field(default_factory=list)
    last_sequence_id: int = 0
    closed: bool = False


class SessionAwareTranscriptionManager:
    """Owns isolated W2 orchestrators and emits revision/finalization events.

    A fresh adapter is created per session to prevent provider buffers, interim
    hypotheses, or sequence counters from leaking across concurrent sessions.
    """

    def __init__(
        self,
        adapter_factory: Callable[[], BaseTranscriptionAdapter],
        confidence_threshold: float = 0.8,
        orchestrator_config: Optional[OrchestratorConfig] = None,
    ) -> None:
        self._adapter_factory = adapter_factory
        self.confidence_policy = ConfidencePolicy(confidence_threshold)
        self._orchestrator_config = orchestrator_config or OrchestratorConfig()
        self._sessions: Dict[str, _SessionStream] = {}
        self._issued_adapters: List[BaseTranscriptionAdapter] = []

    @property
    def confidence_threshold(self) -> float:
        return self.confidence_policy.threshold

    def create_session(
        self,
        session_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> str:
        """Create a session with an isolated adapter, accumulator, and identifiers."""
        identifier = session_id if session_id is not None else str(uuid.uuid4())
        correlation = correlation_id if correlation_id is not None else str(uuid.uuid4())
        if (
            not isinstance(identifier, str)
            or not isinstance(correlation, str)
            or not identifier.strip()
            or not correlation.strip()
        ):
            raise STTConfigurationError("session_id and correlation_id must not be blank")
        if identifier in self._sessions:
            raise STTConfigurationError(f"Session already exists: {identifier}")

        try:
            adapter = self._adapter_factory()
        except Exception as exc:
            raise normalize_provider_error(exc, provider_name="adapter_factory") from exc
        if not isinstance(adapter, BaseTranscriptionAdapter):
            raise STTConfigurationError("adapter_factory must return a BaseTranscriptionAdapter")
        if any(adapter is previous for previous in self._issued_adapters):
            raise STTConfigurationError("adapter_factory must return a fresh adapter for each session")
        self._issued_adapters.append(adapter)

        config = replace(
            self._orchestrator_config,
            session_id=identifier,
            raise_on_error=False,
        )
        self._sessions[identifier] = _SessionStream(
            session_id=identifier,
            correlation_id=correlation,
            orchestrator=STTOrchestrator(adapter=adapter, config=config),
        )
        return identifier

    def process_chunk(
        self,
        session_id: str,
        chunk: Union[AudioChunk, bytes],
    ) -> List[SessionTranscriptEvent]:
        """Transcribe one chunk and emit deduplicated revisions or finalizations."""
        state = self._get_session(session_id)
        if state.closed:
            raise STTInputError(f"Session is closed: {session_id}")
        events = state.orchestrator.process_chunk(
            chunk,
            context={"correlation_id": state.correlation_id},
        )
        return self._convert_events(state, events)

    def finalize_session(self, session_id: str) -> List[SessionTranscriptEvent]:
        """Flush pending provider output and mark the session closed."""
        state = self._get_session(session_id)
        if state.closed:
            return []
        events = state.orchestrator.flush()
        updates = self._convert_events(state, events)
        state.closed = True
        return updates

    def get_transcript(self, session_id: str, include_interim: bool = False) -> str:
        return self._get_session(session_id).orchestrator.get_transcript(include_interim)

    def get_events(self, session_id: str) -> List[SessionTranscriptEvent]:
        return list(self._get_session(session_id).events)

    def _get_session(self, session_id: str) -> _SessionStream:
        try:
            return self._sessions[session_id]
        except KeyError:
            raise STTInputError(f"Unknown transcription session: {session_id}") from None

    def _convert_events(
        self,
        state: _SessionStream,
        events: List[TranscriptEvent],
    ) -> List[SessionTranscriptEvent]:
        updates: List[SessionTranscriptEvent] = []
        for event in events:
            if not isinstance(event, TranscriptEvent):
                updates.append(
                    self._error_update(
                        state,
                        STTPermanentError(
                            "STT orchestrator returned a malformed transcript event",
                            details={"event_type": type(event).__name__},
                        ),
                        state.last_sequence_id,
                    )
                )
                continue
            if event.event_id in state.seen_event_ids:
                continue
            state.seen_event_ids.add(event.event_id)

            sequence_id = event.metadata.get(
                "sequence_id",
                event.metadata.get("chunk_sequence_id", state.last_sequence_id),
            )
            if not isinstance(sequence_id, int) or isinstance(sequence_id, bool) or sequence_id < 0:
                updates.append(
                    self._error_update(
                        state,
                        STTPermanentError(
                            "Transcript event has invalid sequence metadata",
                            details={"source_event_id": event.event_id},
                        ),
                        state.last_sequence_id,
                    )
                )
                continue
            state.last_sequence_id = max(state.last_sequence_id, sequence_id)

            if event.session_id != state.session_id:
                updates.append(
                    self._error_update(
                        state,
                        STTPermanentError(
                            "Transcript event session does not match its transcription stream",
                            details={"source_event_id": event.event_id},
                        ),
                        sequence_id,
                    )
                )
                continue

            if event.event_type == TranscriptEventType.ERROR:
                if event.error is not None:
                    update = SessionTranscriptEvent(
                        event_id=event.event_id,
                        session_id=state.session_id,
                        correlation_id=state.correlation_id,
                        sequence_id=sequence_id,
                        event_type=TranscriptUpdateType.ERROR,
                        timestamp=event.timestamp,
                        source_event_id=event.event_id,
                        error=event.error,
                    )
                    updates.append(self._record(state, update))
                continue

            segment = event.segment
            if segment is None:
                updates.append(
                    self._error_update(
                        state,
                        STTPermanentError(
                            "Transcript event is missing its segment",
                            details={"source_event_id": event.event_id},
                        ),
                        sequence_id,
                    )
                )
                continue

            if event.event_type == TranscriptEventType.INTERIM:
                if segment.segment_id in state.finalized_segment_ids:
                    continue
                previous_sequence = state.last_interim_sequence.get(segment.segment_id)
                if previous_sequence is not None and sequence_id <= previous_sequence:
                    continue
                state.last_interim_sequence[segment.segment_id] = sequence_id
                revision = state.revisions.get(segment.segment_id, 0) + 1
                state.revisions[segment.segment_id] = revision
                update = SessionTranscriptEvent(
                    event_id=event.event_id,
                    session_id=state.session_id,
                    correlation_id=state.correlation_id,
                    segment_id=segment.segment_id,
                    sequence_id=sequence_id,
                    event_type=TranscriptUpdateType.REVISION,
                    timestamp=event.timestamp,
                    text=segment.text,
                    confidence=segment.confidence,
                    revision=revision,
                    review_required=self.confidence_policy.requires_review(segment.confidence),
                    source_event_id=event.event_id,
                )
                updates.append(self._record(state, update))
                continue

            if event.event_type == TranscriptEventType.FINAL:
                if segment.segment_id in state.finalized_segment_ids:
                    continue
                state.finalized_segment_ids.add(segment.segment_id)
                revision = state.revisions.get(segment.segment_id, 0) + 1
                state.revisions[segment.segment_id] = revision
                update = SessionTranscriptEvent(
                    event_id=event.event_id,
                    session_id=state.session_id,
                    correlation_id=state.correlation_id,
                    segment_id=segment.segment_id,
                    sequence_id=sequence_id,
                    event_type=TranscriptUpdateType.FINALIZATION,
                    timestamp=event.timestamp,
                    text=segment.text,
                    confidence=segment.confidence,
                    revision=revision,
                    review_required=self.confidence_policy.requires_review(segment.confidence),
                    source_event_id=event.event_id,
                )
                updates.append(self._record(state, update))
        return updates

    def _error_update(
        self,
        state: _SessionStream,
        error: Exception,
        sequence_id: int,
    ) -> SessionTranscriptEvent:
        normalized = error if isinstance(error, STTProviderError) else normalize_provider_error(error)
        update = SessionTranscriptEvent(
            session_id=state.session_id,
            correlation_id=state.correlation_id,
            sequence_id=sequence_id,
            event_type=TranscriptUpdateType.ERROR,
            timestamp=time.time(),
            error=to_transcript_error_info(normalized),
        )
        return self._record(state, update)

    @staticmethod
    def _record(
        state: _SessionStream,
        event: SessionTranscriptEvent,
    ) -> SessionTranscriptEvent:
        state.events.append(event)
        return event
