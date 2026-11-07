"""Voice Activity Detection (VAD) baseline implementation for Worker 1.

Provides deterministic energy/amplitude-based voice activity detection:
- VADResult: Data model associating speech classification with original AudioChunk.
- SpeechSegment: Aggregated continuous speech duration and chunk payload.
- VADInterface: Abstract interface/protocol for VAD components.
- ThresholdVAD: Deterministic baseline VAD using Root-Mean-Square (RMS) energy.

Chosen Energy Metric & Units:
- Metric: Normalized Root-Mean-Square (RMS) amplitude.
  RMS = sqrt( (1/N) * sum( (sample_i / max_sample_value)^2 ) )
- Units: Dimensionless normalized amplitude in range [0.0, 1.0].
  - 0.0 represents absolute digital silence.
  - ~0.354 represents a pure sine wave at 0.5 amplitude.
  - ~0.577 represents uniform white noise at 1.0 amplitude.
- Default threshold: 0.05 (distinguishes silence and low-level noise from speech).
"""

from __future__ import annotations

import abc
import math
import struct
from dataclasses import dataclass, field
from typing import Iterator, List, Optional, Sequence

from .schemas import AudioChunk, AudioError, AudioFormat


# ============================================================================
# VAD Exceptions
# ============================================================================

class VADError(AudioError):
    """Base exception for Voice Activity Detection errors."""
    pass


class VADConfigurationError(VADError):
    """Raised when VAD parameters (threshold, durations) are invalid."""
    pass


# ============================================================================
# VAD Data Models
# ============================================================================

@dataclass(frozen=True)
class VADResult:
    """Classification outcome for an individual AudioChunk.

    Attributes:
        is_speech: Final binary classification taking minimum duration into account.
        raw_is_speech: Whether this individual chunk's energy meets the threshold.
        energy: Calculated normalized RMS amplitude [0.0, 1.0].
        threshold: Configured decision threshold.
        timestamp_ms: Stream timestamp offset in milliseconds.
        duration_ms: Duration of the classified chunk in milliseconds.
        chunk: Reference to the original AudioChunk.
        consecutive_speech_ms: Accumulated speech duration up to this chunk.
    """
    is_speech: bool
    raw_is_speech: bool
    energy: float
    threshold: float
    timestamp_ms: float
    duration_ms: float
    chunk: AudioChunk
    consecutive_speech_ms: float = 0.0


@dataclass
class SpeechSegment:
    """Aggregated continuous speech utterance spanning one or more chunks.

    Attributes:
        start_ms: Stream timestamp where speech began.
        end_ms: Stream timestamp where speech ended.
        duration_ms: Total duration of the speech segment in milliseconds.
        chunks: List of constituent AudioChunk instances.
    """
    start_ms: float
    end_ms: float
    duration_ms: float
    chunks: List[AudioChunk] = field(default_factory=list)


# ============================================================================
# VAD Interface
# ============================================================================

class VADInterface(abc.ABC):
    """Abstract interface for Voice Activity Detection algorithms."""

    @abc.abstractmethod
    def process_chunk(self, chunk: AudioChunk) -> VADResult:
        """Analyze an individual AudioChunk and return classification."""
        raise NotImplementedError

    @abc.abstractmethod
    def finalize(self) -> List[SpeechSegment]:
        """Finalize any pending speech segment at end of stream and return all segments."""
        raise NotImplementedError

    @abc.abstractmethod
    def reset(self) -> None:
        """Reset internal speech state, segment buffers, and counters."""
        raise NotImplementedError


# ============================================================================
# Energy Calculation Utilities
# ============================================================================

def calculate_chunk_rms(chunk: AudioChunk) -> float:
    """Calculate normalized Root-Mean-Square (RMS) amplitude for an AudioChunk.

    Supports 16-bit PCM (pcm_s16le), 8-bit PCM, and 32-bit float PCM.

    Returns:
        Normalized RMS amplitude in [0.0, 1.0]. Returns 0.0 if chunk payload is empty.
    """
    data = chunk.data
    if not data:
        return 0.0

    sample_width = chunk.format.sample_width

    if sample_width == 2:
        # Signed 16-bit little-endian (pcm_s16le)
        sample_count = len(data) // 2
        if sample_count == 0:
            return 0.0
        # Unpack as little-endian signed 16-bit integers
        samples = struct.unpack(f"<{sample_count}h", data)
        sum_sq = sum((s / 32768.0) ** 2 for s in samples)
        return math.sqrt(sum_sq / sample_count)

    elif sample_width == 1:
        # Unsigned 8-bit PCM (128 is center/zero)
        sample_count = len(data)
        if sample_count == 0:
            return 0.0
        samples = struct.unpack(f"<{sample_count}B", data)
        sum_sq = sum(((s - 128) / 128.0) ** 2 for s in samples)
        return math.sqrt(sum_sq / sample_count)

    elif sample_width == 4:
        # 32-bit float PCM (normalized -1.0 to 1.0)
        sample_count = len(data) // 4
        if sample_count == 0:
            return 0.0
        samples = struct.unpack(f"<{sample_count}f", data)
        sum_sq = sum(s ** 2 for s in samples)
        return math.sqrt(sum_sq / sample_count)

    else:
        raise VADError(f"Unsupported sample width for RMS calculation: {sample_width}")


# ============================================================================
# Threshold-Based VAD Implementation
# ============================================================================

class ThresholdVAD(VADInterface):
    """Deterministic energy/amplitude threshold Voice Activity Detector.

    Classifies speech based on normalized RMS energy and enforces minimum speech duration
    to filter out transient noise bursts.
    """

    def __init__(
        self,
        energy_threshold: float = 0.05,
        min_speech_duration_ms: float = 0.0,
    ) -> None:
        """Initialize ThresholdVAD.

        Args:
            energy_threshold: Normalized RMS amplitude threshold [0.0, 1.0] (default: 0.05).
            min_speech_duration_ms: Minimum continuous speech duration in ms required
                to classify as active speech (default: 0.0ms for immediate classification).
        """
        if not isinstance(energy_threshold, (int, float)) or energy_threshold < 0.0:
            raise VADConfigurationError(
                f"energy_threshold must be non-negative numeric, got {energy_threshold!r}"
            )
        if not isinstance(min_speech_duration_ms, (int, float)) or min_speech_duration_ms < 0.0:
            raise VADConfigurationError(
                f"min_speech_duration_ms must be non-negative numeric, got {min_speech_duration_ms!r}"
            )

        self.energy_threshold = float(energy_threshold)
        self.min_speech_duration_ms = float(min_speech_duration_ms)

        # Internal state
        self._consecutive_speech_ms: float = 0.0
        self._active_segment_chunks: List[AudioChunk] = []
        self._completed_segments: List[SpeechSegment] = []
        self._total_chunks_processed: int = 0

    @property
    def consecutive_speech_ms(self) -> float:
        """Current accumulated consecutive speech duration in milliseconds."""
        return self._consecutive_speech_ms

    @property
    def is_speech_active(self) -> bool:
        """Whether speech is currently detected and exceeds minimum duration."""
        return self._consecutive_speech_ms >= self.min_speech_duration_ms and self._consecutive_speech_ms > 0.0

    @property
    def completed_segments(self) -> List[SpeechSegment]:
        """List of completed speech segments."""
        return list(self._completed_segments)

    def reset(self) -> None:
        """Reset internal speech counters and segment history."""
        self._consecutive_speech_ms = 0.0
        self._active_segment_chunks.clear()
        self._completed_segments.clear()
        self._total_chunks_processed = 0

    def process_chunk(self, chunk: AudioChunk) -> VADResult:
        """Analyze an individual AudioChunk and return classification.

        Args:
            chunk: AudioChunk instance to inspect.

        Returns:
            VADResult with energy, thresholds, and speech classification.
        """
        if not isinstance(chunk, AudioChunk):
            raise VADError(f"Expected AudioChunk instance, got {type(chunk).__name__}")

        energy = calculate_chunk_rms(chunk)
        raw_is_speech = energy >= self.energy_threshold
        duration = chunk.duration_ms or 0.0

        if raw_is_speech:
            self._consecutive_speech_ms += duration
            self._active_segment_chunks.append(chunk)
            is_speech = self._consecutive_speech_ms >= self.min_speech_duration_ms
        else:
            # End of speech run: commit segment if it meets minimum duration
            if self._active_segment_chunks:
                segment_duration = sum(c.duration_ms or 0.0 for c in self._active_segment_chunks)
                if segment_duration >= self.min_speech_duration_ms:
                    start_ms = self._active_segment_chunks[0].timestamp_ms
                    end_ms = start_ms + segment_duration
                    self._completed_segments.append(
                        SpeechSegment(
                            start_ms=start_ms,
                            end_ms=end_ms,
                            duration_ms=segment_duration,
                            chunks=list(self._active_segment_chunks),
                        )
                    )
                self._active_segment_chunks.clear()

            self._consecutive_speech_ms = 0.0
            is_speech = False

        self._total_chunks_processed += 1

        return VADResult(
            is_speech=is_speech,
            raw_is_speech=raw_is_speech,
            energy=energy,
            threshold=self.energy_threshold,
            timestamp_ms=chunk.timestamp_ms,
            duration_ms=duration,
            chunk=chunk,
            consecutive_speech_ms=self._consecutive_speech_ms,
        )

    def finalize(self) -> List[SpeechSegment]:
        """Finalize any pending speech segment at end of stream.

        Returns:
            List of all completed SpeechSegment instances recorded during stream.
        """
        if self._active_segment_chunks:
            segment_duration = sum(c.duration_ms or 0.0 for c in self._active_segment_chunks)
            if segment_duration >= self.min_speech_duration_ms:
                start_ms = self._active_segment_chunks[0].timestamp_ms
                end_ms = start_ms + segment_duration
                self._completed_segments.append(
                    SpeechSegment(
                        start_ms=start_ms,
                        end_ms=end_ms,
                        duration_ms=segment_duration,
                        chunks=list(self._active_segment_chunks),
                    )
                )
            self._active_segment_chunks.clear()

        return list(self._completed_segments)

    def process_stream(self, chunks: Sequence[AudioChunk]) -> Iterator[VADResult]:
        """Convenience method to process an iterable stream of AudioChunks."""
        for chunk in chunks:
            yield self.process_chunk(chunk)
