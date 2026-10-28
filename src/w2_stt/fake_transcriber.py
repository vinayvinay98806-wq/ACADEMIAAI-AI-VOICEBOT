"""Deterministic Fake Transcriber for offline testing and mock pipelines.

This module provides `DeterministicFakeTranscriber`, which satisfies `BaseTranscriptionAdapter`
without making any external network requests or incurring API costs.

Key Capabilities:
1. Scripted Mode: Replays predefined fixture events deterministically in order.
2. Synthetic Mode: Hashes incoming audio chunks to generate reproducible, pseudo-speech
   interim and final events with consistent timestamps and confidence metrics.
3. Strict Repeatability: Repeated executions with identical inputs produce identical outputs.
4. Error Simulation: Supports deterministic injection of error events for negative testing.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Sequence

from w2_stt.adapter import BaseTranscriptionAdapter
from w2_stt.schemas import (
    TranscriptErrorInfo,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)


class DeterministicFakeTranscriber(BaseTranscriptionAdapter):
    """Deterministic, provider-neutral fake transcriber for testing and local development.

    Attributes:
        scripted_events: Optional list of pre-configured event batches to yield sequentially.
        default_language: Language code to attach to generated segments.
        words_per_segment: Word vocabulary used for deterministic text synthesis.
    """

    DEFAULT_VOCABULARY = (
        "welcome",
        "to",
        "academiaai",
        "voice",
        "copilot",
        "lecture",
        "transcription",
        "pipeline",
        "speech",
        "processing",
        "module",
        "deterministic",
        "mock",
        "engine",
    )

    def __init__(
        self,
        scripted_events: Optional[Sequence[List[TranscriptEvent]]] = None,
        default_language: str = "en-US",
        error_on_chunk_index: Optional[int] = None,
        confidence_base: float = 0.95,
    ) -> None:
        """Initialize the fake transcriber.

        Args:
            scripted_events: Optional sequence of event lists. If provided, each call to
                `process_audio_chunk` pops the next list from this sequence.
            default_language: Language tag for synthesized segments.
            error_on_chunk_index: 0-indexed chunk count at which an error event will be emitted.
            confidence_base: Base confidence score for synthesized segments (bounded [0.0, 1.0]).
        """
        self._scripted_events: List[List[TranscriptEvent]] = (
            [list(batch) for batch in scripted_events] if scripted_events is not None else []
        )
        self._initial_scripted = [list(batch) for batch in self._scripted_events]
        self._default_language = default_language
        self._error_on_chunk_index = error_on_chunk_index
        self._confidence_base = max(0.0, min(1.0, confidence_base))

        self._chunk_counter: int = 0
        self._current_time_offset: float = 0.0
        self._pending_interim: Optional[TranscriptSegment] = None
        self._current_segment_id: int = 1

    @property
    def provider_name(self) -> str:
        return "DeterministicFakeTranscriber"

    @property
    def chunk_counter(self) -> int:
        """Total number of chunks processed in the current session."""
        return self._chunk_counter

    def process_audio_chunk(
        self,
        chunk: bytes,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[TranscriptEvent]:
        """Processes an audio chunk and returns deterministic transcript events."""
        chunk_idx = self._chunk_counter
        self._chunk_counter += 1
        ctx = context or {}
        session_id = ctx.get("session_id", "mock-session-001")
        language = ctx.get("language", self._default_language)

        # 1. Check for scripted error simulation
        if self._error_on_chunk_index is not None and chunk_idx == self._error_on_chunk_index:
            return [
                TranscriptEvent(
                    session_id=session_id,
                    event_type=TranscriptEventType.ERROR,
                    timestamp=self._current_time_offset,
                    error=TranscriptErrorInfo(
                        code="SIMULATED_TRANSCRIBER_ERROR",
                        message=f"Simulated deterministic error on chunk index {chunk_idx}.",
                        details={"chunk_index": chunk_idx, "chunk_bytes": len(chunk)},
                    ),
                )
            ]

        # 2. Check for scripted replay mode
        if self._scripted_events:
            events = self._scripted_events.pop(0)
            return events

        # 3. Synthetic deterministic transcription mode
        # Derive predictable output from chunk content and sequence counter
        hasher = hashlib.sha256(chunk)
        hasher.update(str(chunk_idx).encode("utf-8"))
        digest = hasher.hexdigest()

        # Deterministic slice of vocabulary based on hash
        word_index_1 = int(digest[0:4], 16) % len(self.DEFAULT_VOCABULARY)
        word_index_2 = int(digest[4:8], 16) % len(self.DEFAULT_VOCABULARY)
        word_1 = self.DEFAULT_VOCABULARY[word_index_1]
        word_2 = self.DEFAULT_VOCABULARY[word_index_2]

        events: List[TranscriptEvent] = []
        chunk_duration = 0.5  # Treat each mock chunk as 500ms of audio
        start_time = self._current_time_offset
        end_time = start_time + chunk_duration
        self._current_time_offset = end_time

        segment_id = f"seg-{self._current_segment_id:04d}"

        # Every 2nd chunk, finalize the segment; otherwise produce an interim update
        if chunk_idx % 2 == 0:
            # Interim segment
            interim_text = f"{word_1}"
            interim_segment = TranscriptSegment(
                segment_id=segment_id,
                start_time=start_time,
                end_time=end_time,
                text=interim_text,
                confidence=round(self._confidence_base * 0.9, 2),
                is_final=False,
                language=language,
            )
            self._pending_interim = interim_segment
            events.append(
                TranscriptEvent(
                    session_id=session_id,
                    event_type=TranscriptEventType.INTERIM,
                    timestamp=end_time,
                    segment=interim_segment,
                )
            )
        else:
            # Finalize segment with expanded text
            prior_text = self._pending_interim.text if self._pending_interim else word_1
            final_text = f"{prior_text} {word_2}"
            final_segment = TranscriptSegment(
                segment_id=segment_id,
                start_time=self._pending_interim.start_time if self._pending_interim else start_time,
                end_time=end_time,
                text=final_text,
                confidence=round(self._confidence_base, 2),
                is_final=True,
                language=language,
            )
            self._pending_interim = None
            self._current_segment_id += 1
            events.append(
                TranscriptEvent(
                    session_id=session_id,
                    event_type=TranscriptEventType.FINAL,
                    timestamp=end_time,
                    segment=final_segment,
                )
            )

        return events

    def flush(self) -> List[TranscriptEvent]:
        """Finalize any pending interim segment before closing the stream."""
        events: List[TranscriptEvent] = []
        if self._pending_interim is not None:
            final_segment = TranscriptSegment(
                segment_id=self._pending_interim.segment_id,
                start_time=self._pending_interim.start_time,
                end_time=self._pending_interim.end_time,
                text=self._pending_interim.text,
                confidence=round(self._confidence_base, 2),
                is_final=True,
                language=self._pending_interim.language,
            )
            events.append(
                TranscriptEvent(
                    session_id="mock-session-001",
                    event_type=TranscriptEventType.FINAL,
                    timestamp=self._current_time_offset,
                    segment=final_segment,
                )
            )
            self._pending_interim = None
            self._current_segment_id += 1
        return events

    def reset(self) -> None:
        """Reset internal sequence counters, buffers, and restore scripted events."""
        self._chunk_counter = 0
        self._current_time_offset = 0.0
        self._pending_interim = None
        self._current_segment_id = 1
        self._scripted_events = [list(batch) for batch in self._initial_scripted]
