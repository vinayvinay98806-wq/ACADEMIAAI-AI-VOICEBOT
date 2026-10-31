"""Audio schemas and validation for Worker 1 (Audio Input & VAD).

This module defines the core data contracts for the audio pipeline:
- AudioFormat: Specification of audio encoding parameters (sample rate, channels, bit depth).
- AudioChunk: Atomic unit of raw audio data transmitted through the pipeline.
- AudioError and subclasses: Structured exception hierarchy for audio validation errors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Set, Union


# ============================================================================
# Exception Hierarchy
# ============================================================================

class AudioError(Exception):
    """Base exception for all audio-related errors in the pipeline."""
    pass


class AudioFormatError(AudioError):
    """Raised when audio format parameters are invalid or unsupported."""
    pass


class AudioChunkError(AudioError):
    """Base exception for errors concerning audio chunk integrity or structure."""
    pass


class EmptyChunkError(AudioChunkError):
    """Raised when an audio chunk is empty but non-empty data is required."""
    pass


class CorruptChunkError(AudioChunkError):
    """Raised when audio chunk data is corrupted, misaligned, or truncated."""
    pass


# ============================================================================
# Audio Format Specification
# ============================================================================

# Standard sample rates commonly used in voice/speech pipelines (Hz)
STANDARD_SAMPLE_RATES: Set[int] = {
    8000,    # Telephony narrowband
    11025,   # Low-fi speech
    12000,   # Low-fi speech
    16000,   # Standard speech recognition / VAD rate (Recommended)
    22050,   # Medium quality audio
    24000,   # High-quality speech (e.g., Opus voice)
    32000,   # High-fidelity broadcast speech
    44100,   # CD audio
    48000,   # Studio audio / WebRTC standard
}

# Supported channel configurations
SUPPORTED_CHANNELS: Set[int] = {1, 2}  # Mono (1), Stereo (2)

# Supported sample widths (bytes per sample per channel)
SUPPORTED_SAMPLE_WIDTHS: Set[int] = {
    1,  # 8-bit PCM (unsigned or signed)
    2,  # 16-bit PCM (signed, standard int16)
    4,  # 32-bit PCM / float
}


@dataclass(frozen=True)
class AudioFormat:
    """Defines audio format characteristics and validation rules.

    Attributes:
        sample_rate: Samples per second in Hz (e.g., 16000 for standard voice pipelines).
        channels: Number of audio channels (1 for mono, 2 for stereo).
        sample_width: Bytes per sample per channel (default: 2 for 16-bit PCM).
        encoding: Text identifier of PCM encoding (default: 'pcm_s16le').
    """
    sample_rate: int = 16000
    channels: int = 1
    sample_width: int = 2
    encoding: str = "pcm_s16le"

    def __post_init__(self) -> None:
        """Validate format parameters strictly."""
        # 1. Sample rate validation
        if not isinstance(self.sample_rate, int) or isinstance(self.sample_rate, bool):
            raise AudioFormatError(
                f"Sample rate must be an integer, got {type(self.sample_rate).__name__}: {self.sample_rate!r}"
            )
        if self.sample_rate <= 0:
            raise AudioFormatError(
                f"Sample rate must be positive, got {self.sample_rate}"
            )
        if self.sample_rate not in STANDARD_SAMPLE_RATES:
            rates_sorted = sorted(STANDARD_SAMPLE_RATES)
            raise AudioFormatError(
                f"Unsupported sample rate: {self.sample_rate} Hz. "
                f"Supported standard rates are: {rates_sorted}"
            )

        # 2. Channel validation
        if not isinstance(self.channels, int) or isinstance(self.channels, bool):
            raise AudioFormatError(
                f"Channel count must be an integer, got {type(self.channels).__name__}: {self.channels!r}"
            )
        if self.channels not in SUPPORTED_CHANNELS:
            raise AudioFormatError(
                f"Invalid channel count: {self.channels}. Supported channels: {sorted(SUPPORTED_CHANNELS)} (1=mono, 2=stereo)"
            )

        # 3. Sample width validation
        if not isinstance(self.sample_width, int) or isinstance(self.sample_width, bool):
            raise AudioFormatError(
                f"Sample width must be an integer, got {type(self.sample_width).__name__}: {self.sample_width!r}"
            )
        if self.sample_width not in SUPPORTED_SAMPLE_WIDTHS:
            raise AudioFormatError(
                f"Unsupported sample width: {self.sample_width} bytes. "
                f"Supported sample widths: {sorted(SUPPORTED_SAMPLE_WIDTHS)}"
            )

        # 4. Encoding validation
        if not isinstance(self.encoding, str) or not self.encoding.strip():
            raise AudioFormatError(
                f"Encoding must be a non-empty string, got {self.encoding!r}"
            )

    @property
    def bytes_per_frame(self) -> int:
        """Number of bytes representing one audio frame across all channels."""
        return self.sample_width * self.channels

    @property
    def bytes_per_second(self) -> int:
        """Total throughput in bytes per second."""
        return self.sample_rate * self.bytes_per_frame

    def calculate_duration_ms(self, byte_count: int) -> float:
        """Calculate duration in milliseconds from byte count.

        Args:
            byte_count: Number of raw PCM bytes.

        Returns:
            Duration in milliseconds as float.
        """
        if byte_count < 0:
            raise AudioFormatError(f"Byte count cannot be negative: {byte_count}")
        return (byte_count / self.bytes_per_second) * 1000.0

    def calculate_byte_count(self, duration_ms: float) -> int:
        """Calculate required byte count for given duration in milliseconds.

        Ensures result is aligned to bytes_per_frame.
        """
        if duration_ms < 0:
            raise AudioFormatError(f"Duration cannot be negative: {duration_ms}")
        frames = int(round((duration_ms / 1000.0) * self.sample_rate))
        return frames * self.bytes_per_frame


# ============================================================================
# Audio Chunk Specification
# ============================================================================

@dataclass
class AudioChunk:
    """Atomic audio chunk transmitted from source to VAD/processing pipeline.

    Attributes:
        data: Raw PCM audio byte payload.
        format: AudioFormat describing sample rate, channels, bit depth.
        sequence_id: Monotonically increasing sequence ID (>= 0).
        timestamp_ms: Stream/session start timestamp offset in milliseconds (>= 0.0).
        duration_ms: Duration of this chunk in milliseconds.
    """
    data: bytes
    format: AudioFormat
    sequence_id: int
    timestamp_ms: float
    duration_ms: Optional[float] = None

    def __post_init__(self) -> None:
        """Validate chunk parameters and calculate duration if omitted."""
        # 1. Type validation for data
        if not isinstance(self.data, (bytes, bytearray)):
            raise AudioChunkError(
                f"Chunk data must be bytes or bytearray, got {type(self.data).__name__}"
            )
        if isinstance(self.data, bytearray):
            self.data = bytes(self.data)

        # 2. Format validation
        if not isinstance(self.format, AudioFormat):
            raise AudioFormatError(
                f"Chunk format must be an AudioFormat instance, got {type(self.format).__name__}"
            )

        # 3. Empty data check
        if len(self.data) == 0:
            raise EmptyChunkError("AudioChunk data is empty (0 bytes)")

        # 4. Alignment / corruption check (must be multiple of bytes_per_frame)
        bpf = self.format.bytes_per_frame
        if len(self.data) % bpf != 0:
            remainder = len(self.data) % bpf
            raise CorruptChunkError(
                f"Corrupt chunk: data length ({len(self.data)} bytes) is not aligned to frame size "
                f"({bpf} bytes = {self.format.sample_width} bytes/sample * {self.format.channels} channels). "
                f"Remainder: {remainder} byte(s)"
            )

        # 5. Sequence ID validation
        if not isinstance(self.sequence_id, int) or isinstance(self.sequence_id, bool):
            raise AudioChunkError(
                f"sequence_id must be an integer, got {type(self.sequence_id).__name__}: {self.sequence_id!r}"
            )
        if self.sequence_id < 0:
            raise AudioChunkError(
                f"sequence_id must be non-negative (>= 0), got {self.sequence_id}"
            )

        # 6. Timestamp validation
        if not isinstance(self.timestamp_ms, (int, float)) or isinstance(self.timestamp_ms, bool):
            raise AudioChunkError(
                f"timestamp_ms must be numeric, got {type(self.timestamp_ms).__name__}: {self.timestamp_ms!r}"
            )
        if self.timestamp_ms < 0:
            raise AudioChunkError(
                f"timestamp_ms must be non-negative (>= 0.0), got {self.timestamp_ms}"
            )
        self.timestamp_ms = float(self.timestamp_ms)

        # 7. Duration calculation or verification
        expected_duration = self.format.calculate_duration_ms(len(self.data))
        if self.duration_ms is None:
            self.duration_ms = expected_duration
        else:
            if not isinstance(self.duration_ms, (int, float)) or isinstance(self.duration_ms, bool):
                raise AudioChunkError(
                    f"duration_ms must be numeric, got {type(self.duration_ms).__name__}: {self.duration_ms!r}"
                )
            if self.duration_ms <= 0:
                raise AudioChunkError(f"duration_ms must be positive, got {self.duration_ms}")
            # Verify duration consistency with tolerance of 0.2 ms
            if abs(self.duration_ms - expected_duration) > 0.2:
                raise CorruptChunkError(
                    f"Chunk duration_ms ({self.duration_ms:.2f} ms) is inconsistent with payload length "
                    f"({len(self.data)} bytes = {expected_duration:.2f} ms)"
                )
            self.duration_ms = float(self.duration_ms)

    @property
    def frame_count(self) -> int:
        """Number of complete audio frames in this chunk."""
        return len(self.data) // self.format.bytes_per_frame

    @property
    def sample_count(self) -> int:
        """Total number of individual samples across all channels in this chunk."""
        return len(self.data) // self.format.sample_width

    @property
    def is_empty(self) -> bool:
        """Check if chunk has 0 bytes (always False for valid instances)."""
        return len(self.data) == 0
