"""Transcript Schemas and Validation for Workstream W2: Speech-to-Text.

This module defines the core data contracts:
- `TranscriptSegment`: Represents a single speech segment/utterance with timestamps,
  confidence, text, language, and interim/final status.
- `TranscriptEvent`: Represents the event emitted by a transcription provider or adapter,
  carrying either a segment or structured error info.
- `TranscriptErrorInfo`: Structured error payload for transcription errors.
- `TranscriptEventType`: Enumeration of recognized event types.

All models are strictly validated using Pydantic v2.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TranscriptEventType(str, Enum):
    """Enumeration of transcript event types."""

    INTERIM = "interim"
    FINAL = "final"
    ERROR = "error"


class TranscriptErrorInfo(BaseModel):
    """Structured diagnostic information for transcription errors."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(
        ...,
        min_length=1,
        description="Machine-readable error code (e.g., 'AUDIO_CORRUPTED', 'ADAPTER_TIMEOUT').",
    )
    message: str = Field(
        ...,
        min_length=1,
        description="Human-readable explanation of the error condition.",
    )
    details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional diagnostic dictionary containing additional context.",
    )

    @field_validator("code", "message")
    @classmethod
    def strip_whitespace(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Field cannot be empty or purely whitespace.")
        return trimmed


class TranscriptSegment(BaseModel):
    """A bounded segment of transcribed speech.

    Fields:
        segment_id: Unique, stable identifier for the utterance segment.
        start_time: Start offset in seconds from audio stream origin (>= 0.0).
        end_time: End offset in seconds from audio stream origin (>= start_time).
        text: Transcribed text content.
        confidence: Normalized confidence score bounded between 0.0 and 1.0.
        is_final: True if the segment is confirmed final; False if interim/provisional.
        language: BCP-47 / ISO language code (e.g. 'en-US', 'hi-IN').
        speaker_id: Optional identifier for diarized speakers.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    segment_id: str = Field(
        ...,
        min_length=1,
        description="Unique, stable identifier for the segment (used for interim-to-final correlation).",
    )
    start_time: float = Field(
        ...,
        ge=0.0,
        description="Start timestamp in seconds relative to stream inception (non-negative).",
    )
    end_time: float = Field(
        ...,
        ge=0.0,
        description="End timestamp in seconds relative to stream inception (must be >= start_time).",
    )
    text: str = Field(
        ...,
        description="Transcribed textual representation of speech.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Transcription confidence score strictly bounded in [0.0, 1.0].",
    )
    is_final: bool = Field(
        default=False,
        description="Flag indicating whether this segment is final (immutable) or interim (provisional).",
    )
    language: str = Field(
        default="en-US",
        min_length=2,
        description="Language code for the transcription (e.g. 'en', 'en-US', 'es').",
    )
    speaker_id: Optional[str] = Field(
        default=None,
        description="Optional speaker identification label.",
    )

    @field_validator("segment_id", "language")
    @classmethod
    def clean_identifier(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Identifier cannot be blank or whitespace.")
        return trimmed

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_segment_boundaries(self) -> TranscriptSegment:
        # Validate temporal order
        if self.end_time < self.start_time:
            raise ValueError(
                f"end_time ({self.end_time:.3f}s) cannot precede start_time ({self.start_time:.3f}s)."
            )

        # Validate that finalized segments must contain text
        if self.is_final and not self.text:
            raise ValueError("Finalized transcript segment must contain non-empty text.")

        return self


class TranscriptEvent(BaseModel):
    """Event wrapper emitted by transcription adapters for downstream streaming.

    Fields:
        event_id: Unique event identifier.
        session_id: Optional identifier tying event to a session or stream.
        event_type: Type of event ('interim', 'final', or 'error').
        timestamp: Wall-clock UTC timestamp when the event was generated.
        segment: The TranscriptSegment payload (required for interim & final events).
        error: Structured error info (required for error events).
        metadata: Extensible key-value metadata for telemetry and tracing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique event ID for deduplication and tracing.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Optional session identifier for grouping events across connections.",
    )
    event_type: TranscriptEventType = Field(
        ...,
        description="The nature of the event: 'interim', 'final', or 'error'.",
    )
    timestamp: float = Field(
        default_factory=time.time,
        ge=0.0,
        description="Epoch timestamp (seconds) when the event was emitted.",
    )
    segment: Optional[TranscriptSegment] = Field(
        default=None,
        description="Transcript segment payload for interim and final events.",
    )
    error: Optional[TranscriptErrorInfo] = Field(
        default=None,
        description="Error details payload, mandatory when event_type is 'error'.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional telemetry and consumer metadata.",
    )

    @model_validator(mode="after")
    def validate_event_consistency(self) -> TranscriptEvent:
        # Error event validation
        if self.event_type == TranscriptEventType.ERROR:
            if self.error is None:
                raise ValueError("TranscriptEvent with event_type='error' must include 'error' information.")
            if self.segment is not None:
                raise ValueError("TranscriptEvent with event_type='error' must not include a segment payload.")

        # Interim event validation
        elif self.event_type == TranscriptEventType.INTERIM:
            if self.segment is None:
                raise ValueError("TranscriptEvent with event_type='interim' must include a segment payload.")
            if self.segment.is_final:
                raise ValueError("TranscriptEvent with event_type='interim' cannot have segment.is_final=True.")
            if self.error is not None:
                raise ValueError("TranscriptEvent with event_type='interim' must not include error details.")

        # Final event validation
        elif self.event_type == TranscriptEventType.FINAL:
            if self.segment is None:
                raise ValueError("TranscriptEvent with event_type='final' must include a segment payload.")
            if not self.segment.is_final:
                raise ValueError("TranscriptEvent with event_type='final' must have segment.is_final=True.")
            if self.error is not None:
                raise ValueError("TranscriptEvent with event_type='final' must not include error details.")

        return self
