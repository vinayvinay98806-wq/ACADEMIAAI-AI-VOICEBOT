"""Audio-to-Transcript Orchestrator for Workstream W2: Speech-to-Text.

This module provides `STTOrchestrator` and `OrchestratorConfig`, connecting:
AudioChunk -> Preprocessor -> Orchestrator (Reliability Layer) -> TranscriptionAdapter -> TranscriptEvents -> TranscriptAccumulator

Guarantees:
1. Provider Decoupling: Works with any compliant `BaseTranscriptionAdapter`.
2. Shared Contract Alignment: Directly accepts `AudioChunk` and `AudioFormat` from W1.
3. Metadata Fidelity: Preserves audio chunk sequence, timestamp, and duration metadata.
4. Error Resilience: Leverages retry policy and error normalization to withstand transient hiccups.
5. Ingestion Safety: Safely handles empty chunks, invalid inputs, and out-of-order streams.
6. Unified Public Interface: End-to-end ingestion, flush, reset, and transcript retrieval.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Union

from academiaai.audio.schemas import AudioChunk, AudioFormat, EmptyChunkError
from w2_stt.accumulator import OrderedTranscriptAccumulator
from w2_stt.adapter import BaseTranscriptionAdapter
from w2_stt.exceptions import (
    STTError,
    STTInputError,
    STTProviderError,
    to_transcript_error_info,
)
from w2_stt.preprocessing import AudioPreprocessingConfig, AudioPreprocessor
from w2_stt.reliability import RetryConfig, execute_with_retry
from w2_stt.schemas import (
    TranscriptErrorInfo,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)


@dataclass
class OrchestratorConfig:
    """Configuration options for STT orchestration.

    Attributes:
        session_id: Unique session identifier (auto-generated if omitted).
        default_language: Default BCP-47 language tag for transcription.
        raise_on_error: If True, raises exceptions; if False, emits and accumulates error events.
        preserve_chunk_metadata: If True, forwards chunk sequence/timestamp in event metadata.
        preprocessing_config: Optional audio preprocessing configuration (resampling/normalization).
        retry_config: Optional retry and timeout policy configuration.
    """

    session_id: Optional[str] = None
    default_language: str = "en-US"
    raise_on_error: bool = False
    preserve_chunk_metadata: bool = True
    preprocessing_config: Optional[AudioPreprocessingConfig] = None
    retry_config: Optional[RetryConfig] = None

    def __post_init__(self) -> None:
        if self.session_id is None:
            self.session_id = f"stt-session-{uuid.uuid4().hex[:8]}"


class STTOrchestrator:
    """Coordinates the end-to-end Speech-to-Text streaming pipeline.

    Workflow:
    AudioChunk
      -> AudioPreprocessor (resampling / mono downmix / peak normalization)
      -> execute_with_retry (timeout & bounded exponential backoff)
      -> BaseTranscriptionAdapter (provider engine)
      -> TranscriptEvent(s)
      -> OrderedTranscriptAccumulator (ordering, deduplication, interim replacement)
      -> Continuous Transcript Output
    """

    def __init__(
        self,
        adapter: BaseTranscriptionAdapter,
        accumulator: Optional[OrderedTranscriptAccumulator] = None,
        preprocessor: Optional[AudioPreprocessor] = None,
        config: Optional[OrchestratorConfig] = None,
        sleep_func: Callable[[float], None] = time.sleep,
    ) -> None:
        """Initialize the STT Orchestrator.

        Args:
            adapter: Compliant transcription adapter implementation.
            accumulator: Optional custom accumulator instance.
            preprocessor: Optional custom audio preprocessor.
            config: Orchestration settings (session ID, language, retry, error mode).
            sleep_func: Sleep function used during retry backoff (mockable for fast tests).
        """
        if not isinstance(adapter, BaseTranscriptionAdapter):
            raise TypeError("adapter must be an instance of BaseTranscriptionAdapter")

        self._adapter = adapter
        self._config = config or OrchestratorConfig()
        self._session_id = self._config.session_id or f"stt-session-{uuid.uuid4().hex[:8]}"
        self._accumulator = accumulator or OrderedTranscriptAccumulator(session_id=self._session_id)
        self._preprocessor = preprocessor or (
            AudioPreprocessor(self._config.preprocessing_config)
            if self._config.preprocessing_config is not None
            else None
        )
        self._retry_config = self._config.retry_config or RetryConfig()
        self._sleep_func = sleep_func

        self._chunk_counter: int = 0
        self._total_audio_duration_ms: float = 0.0

    @property
    def session_id(self) -> str:
        """Active session identifier."""
        return self._session_id

    @property
    def adapter(self) -> BaseTranscriptionAdapter:
        """The underlying transcription adapter."""
        return self._adapter

    @property
    def accumulator(self) -> OrderedTranscriptAccumulator:
        """The transcript accumulator maintaining session state."""
        return self._accumulator

    @property
    def preprocessor(self) -> Optional[AudioPreprocessor]:
        """The active audio preprocessor, if configured."""
        return self._preprocessor

    @property
    def retry_config(self) -> RetryConfig:
        """Configured retry and timeout policy."""
        return self._retry_config

    @property
    def chunk_counter(self) -> int:
        """Total number of successfully processed audio chunks."""
        return self._chunk_counter

    @property
    def total_audio_duration_ms(self) -> float:
        """Total duration in milliseconds of ingested audio."""
        return self._total_audio_duration_ms

    @property
    def errors(self) -> List[TranscriptErrorInfo]:
        """Diagnostic errors collected during the session."""
        return self._accumulator.errors

    def process_chunk(
        self,
        chunk: Union[AudioChunk, bytes],
        context: Optional[Dict[str, Any]] = None,
    ) -> List[TranscriptEvent]:
        """Process a single audio chunk through preprocessing, adapter, and accumulator.

        Args:
            chunk: Input audio as an AudioChunk object or raw PCM bytes.
            context: Optional contextual metadata (overrides default session/language).

        Returns:
            List of generated TranscriptEvent instances.

        Raises:
            STTInputError: If chunk is invalid, empty, or unaligned and raise_on_error is True.
            STTProviderError: If provider fails after retries and raise_on_error is True.
        """
        # 1. Normalize and validate input chunk
        audio_chunk: AudioChunk
        if isinstance(chunk, bytes):
            if len(chunk) == 0:
                return self._handle_error(
                    STTInputError("Audio byte payload is empty (0 bytes)"),
                    context,
                )
            # Default standard format for bare byte buffers: 16kHz, mono, 16-bit PCM
            default_fmt = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
            try:
                audio_chunk = AudioChunk(
                    data=chunk,
                    format=default_fmt,
                    sequence_id=self._chunk_counter,
                    timestamp_ms=self._total_audio_duration_ms,
                )
            except Exception as exc:
                return self._handle_error(
                    STTInputError(f"Failed to wrap raw audio bytes: {exc}"),
                    context,
                )
        elif isinstance(chunk, AudioChunk):
            audio_chunk = chunk
        else:
            return self._handle_error(
                STTInputError(
                    f"Invalid audio chunk type: {type(chunk).__name__}. Expected AudioChunk or bytes."
                ),
                context,
            )

        if len(audio_chunk.data) == 0:
            return self._handle_error(
                STTInputError("AudioChunk payload is empty (0 bytes)"),
                context,
            )

        # 2. Preprocess audio if preprocessor is configured
        processed_chunk: AudioChunk = audio_chunk
        if self._preprocessor is not None:
            try:
                processed_chunk = self._preprocessor.process(audio_chunk)
            except Exception as exc:
                return self._handle_error(exc, context)

        # 3. Assemble invocation context preserving chunk metadata
        merged_context: Dict[str, Any] = {
            "session_id": self._session_id,
            "language": self._config.default_language,
            "sequence_id": processed_chunk.sequence_id,
            "timestamp_ms": processed_chunk.timestamp_ms,
            "duration_ms": processed_chunk.duration_ms,
            "sample_rate": processed_chunk.format.sample_rate,
            "channels": processed_chunk.format.channels,
        }
        if context:
            merged_context.update(context)

        # 4. Invoke transcription adapter under retry & timeout policy
        def _invoke_adapter() -> List[TranscriptEvent]:
            return self._adapter.process_audio_chunk(
                processed_chunk.data,
                context=merged_context,
            )

        try:
            raw_events = execute_with_retry(
                _invoke_adapter,
                config=self._retry_config,
                provider_name=self._adapter.provider_name,
                sleep_func=self._sleep_func,
            )
        except Exception as exc:
            return self._handle_error(exc, merged_context)

        # 5. Enrich events with chunk telemetry if enabled
        emitted_events: List[TranscriptEvent] = []
        for raw_event in raw_events:
            event_to_accumulate = raw_event
            if self._config.preserve_chunk_metadata:
                metadata = dict(raw_event.metadata)
                metadata.setdefault("chunk_sequence_id", processed_chunk.sequence_id)
                metadata.setdefault("chunk_timestamp_ms", processed_chunk.timestamp_ms)
                metadata.setdefault("chunk_duration_ms", processed_chunk.duration_ms)
                metadata.setdefault("provider_name", self._adapter.provider_name)

                # Reconstruct event with enriched metadata
                event_to_accumulate = TranscriptEvent(
                    event_id=raw_event.event_id,
                    session_id=raw_event.session_id or self._session_id,
                    event_type=raw_event.event_type,
                    timestamp=raw_event.timestamp,
                    segment=raw_event.segment,
                    error=raw_event.error,
                    metadata=metadata,
                )

            # 6. Accumulate into session accumulator
            self._accumulator.add_event(event_to_accumulate)
            emitted_events.append(event_to_accumulate)

        # 7. Update internal metrics
        self._chunk_counter += 1
        if processed_chunk.duration_ms:
            self._total_audio_duration_ms += processed_chunk.duration_ms

        return emitted_events

    def process_chunks(
        self,
        chunks: Iterable[Union[AudioChunk, bytes]],
        context: Optional[Dict[str, Any]] = None,
    ) -> List[TranscriptEvent]:
        """Sequentially process an iterable of audio chunks.

        Args:
            chunks: Iterable of AudioChunk objects or raw PCM bytes.
            context: Optional shared contextual metadata.

        Returns:
            Concatenated list of all TranscriptEvent instances produced.
        """
        all_events: List[TranscriptEvent] = []
        for chunk in chunks:
            events = self.process_chunk(chunk, context=context)
            all_events.extend(events)
        return all_events

    def flush(self) -> List[TranscriptEvent]:
        """Flush any pending buffered interim transcription states from the provider.

        Executes under retry policy and ingests resulting finalized events into the accumulator.

        Returns:
            List of final TranscriptEvent instances emitted on flush.
        """
        def _invoke_flush() -> List[TranscriptEvent]:
            return self._adapter.flush()

        try:
            flushed_events = execute_with_retry(
                _invoke_flush,
                config=self._retry_config,
                provider_name=self._adapter.provider_name,
                sleep_func=self._sleep_func,
            )
        except Exception as exc:
            return self._handle_error(exc)

        enriched_events: List[TranscriptEvent] = []
        for event in flushed_events:
            enriched = event
            if self._config.preserve_chunk_metadata:
                meta = dict(event.metadata)
                meta.setdefault("provider_name", self._adapter.provider_name)
                meta.setdefault("flushed", True)
                enriched = TranscriptEvent(
                    event_id=event.event_id,
                    session_id=event.session_id or self._session_id,
                    event_type=event.event_type,
                    timestamp=event.timestamp,
                    segment=event.segment,
                    error=event.error,
                    metadata=meta,
                )
            self._accumulator.add_event(enriched)
            enriched_events.append(enriched)

        return enriched_events

    def reset(self) -> None:
        """Reset the orchestration session, provider adapter, and transcript accumulator."""
        self._adapter.reset()
        self._accumulator.reset()
        self._chunk_counter = 0
        self._total_audio_duration_ms = 0.0
        # If no explicit session_id was given at config, generate fresh session_id
        if self._config.session_id is None:
            self._session_id = f"stt-session-{uuid.uuid4().hex[:8]}"
            self._accumulator.session_id = self._session_id

    def get_transcript(self, include_interim: bool = False, separator: str = " ") -> str:
        """Retrieve the consolidated continuous transcript text.

        Args:
            include_interim: Whether to include unconfirmed interim words at the tail.
            separator: String delimiter between segments.

        Returns:
            Assembled transcript string.
        """
        return self._accumulator.get_full_transcript(
            include_interim=include_interim,
            separator=separator,
        )

    def get_segments(self, include_interim: bool = False) -> List[TranscriptSegment]:
        """Retrieve chronologically ordered transcript segments.

        Args:
            include_interim: Whether to include pending interim segments.

        Returns:
            List of sorted TranscriptSegment objects.
        """
        return self._accumulator.get_segments(include_interim=include_interim)

    def _handle_error(
        self,
        error: Exception,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[TranscriptEvent]:
        """Handle errors according to `config.raise_on_error`.

        If raise_on_error is True, raises the exception.
        If raise_on_error is False, generates a TranscriptEvent(event_type=ERROR),
        records it in the accumulator, and returns it.
        """
        if self._config.raise_on_error:
            if isinstance(error, STTError):
                raise error
            raise STTProviderError(
                message=str(error),
                provider_name=self._adapter.provider_name,
                cause=error,
            ) from error

        error_info = to_transcript_error_info(error)
        err_event = TranscriptEvent(
            session_id=self._session_id,
            event_type=TranscriptEventType.ERROR,
            error=error_info,
            metadata={"provider_name": self._adapter.provider_name},
        )
        self._accumulator.add_event(err_event)
        return [err_event]
