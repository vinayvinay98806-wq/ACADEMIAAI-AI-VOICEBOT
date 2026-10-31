"""Deterministic audio sources and chunking mechanisms for Worker 1.

This module provides mock audio sources for testing and pipeline integration:
- SignalType: Enum of available synthetic signal patterns (sine, silence, noise, speech-like).
- DeterministicChunker: Takes raw audio streams or byte buffers and produces validated AudioChunks
  with strictly monotonic sequence IDs and accurate timestamps.
- FakeMicrophoneSource: Simulates an audio input capture device generating reproducible,
  deterministic synthetic audio chunks without requiring physical hardware or third-party drivers.
"""

from __future__ import annotations

import enum
import math
import random
import struct
from typing import Generator, Iterable, Iterator, List, Optional

from .schemas import (
    AudioChunk,
    AudioFormat,
    AudioFormatError,
    CorruptChunkError,
    EmptyChunkError,
)


class SignalType(str, enum.Enum):
    """Supported deterministic synthetic signal patterns."""
    SINE_WAVE = "sine_wave"
    SILENCE = "silence"
    WHITE_NOISE = "white_noise"
    SPEECH_LIKE = "speech_like"


class DeterministicChunker:
    """Slices arbitrary incoming PCM audio bytes into fixed-duration AudioChunk objects.

    Maintains internal state including:
    - Monotonically increasing sequence IDs (0, 1, 2, ...).
    - Monotonically advancing timestamps in milliseconds.
    - An internal byte buffer for unchunked remainders across add_bytes() calls.
    """

    def __init__(
        self,
        audio_format: Optional[AudioFormat] = None,
        chunk_duration_ms: float = 20.0,
        start_sequence_id: int = 0,
        start_timestamp_ms: float = 0.0,
    ) -> None:
        """Initialize the deterministic chunker.

        Args:
            audio_format: AudioFormat specification (default: 16kHz, mono, 16-bit).
            chunk_duration_ms: Nominal duration of each chunk in milliseconds (default: 20.0ms).
            start_sequence_id: Initial sequence ID (default: 0).
            start_timestamp_ms: Initial timestamp offset in milliseconds (default: 0.0ms).
        """
        self.format = audio_format or AudioFormat()
        if chunk_duration_ms <= 0:
            raise AudioFormatError(f"chunk_duration_ms must be positive, got {chunk_duration_ms}")
        self.chunk_duration_ms = float(chunk_duration_ms)

        # Calculate exact byte count for each chunk
        self.chunk_byte_size = self.format.calculate_byte_count(self.chunk_duration_ms)
        if self.chunk_byte_size <= 0:
            raise AudioFormatError("Calculated chunk byte size is 0; check duration and sample rate")

        # Recalculate true chunk duration from the aligned byte size for sub-millisecond precision
        self.actual_chunk_duration_ms = self.format.calculate_duration_ms(self.chunk_byte_size)

        self._start_sequence_id = start_sequence_id
        self._start_timestamp_ms = start_timestamp_ms

        self._sequence_id = start_sequence_id
        self._timestamp_ms = float(start_timestamp_ms)
        self._buffer = bytearray()

    @property
    def next_sequence_id(self) -> int:
        """Sequence ID that will be assigned to the next produced chunk."""
        return self._sequence_id

    @property
    def current_timestamp_ms(self) -> float:
        """Current stream timestamp position in milliseconds."""
        return self._timestamp_ms

    @property
    def buffered_bytes(self) -> int:
        """Number of unchunked bytes currently held in buffer."""
        return len(self._buffer)

    def reset(self) -> None:
        """Reset sequence counter, timestamp, and clear internal buffer."""
        self._sequence_id = self._start_sequence_id
        self._timestamp_ms = float(self._start_timestamp_ms)
        self._buffer.clear()

    def add_bytes(self, raw_bytes: bytes) -> List[AudioChunk]:
        """Append raw PCM bytes to internal buffer and extract all complete AudioChunks.

        Args:
            raw_bytes: New incoming PCM bytes.

        Returns:
            List of generated AudioChunk instances.
        """
        if not isinstance(raw_bytes, (bytes, bytearray)):
            raise TypeError(f"raw_bytes must be bytes or bytearray, got {type(raw_bytes).__name__}")

        if len(raw_bytes) == 0:
            return []

        self._buffer.extend(raw_bytes)
        chunks: List[AudioChunk] = []

        while len(self._buffer) >= self.chunk_byte_size:
            chunk_data = bytes(self._buffer[:self.chunk_byte_size])
            del self._buffer[:self.chunk_byte_size]

            chunk = AudioChunk(
                data=chunk_data,
                format=self.format,
                sequence_id=self._sequence_id,
                timestamp_ms=self._timestamp_ms,
                duration_ms=self.actual_chunk_duration_ms,
            )
            chunks.append(chunk)

            self._sequence_id += 1
            self._timestamp_ms += self.actual_chunk_duration_ms

        return chunks

    def flush(self, drop_incomplete: bool = False) -> Optional[AudioChunk]:
        """Flush any remaining bytes in the buffer.

        Args:
            drop_incomplete: If True, discards remaining bytes smaller than chunk_byte_size.
                             If False, yields a partial AudioChunk if remainder is frame-aligned.

        Returns:
            An AudioChunk for the final partial remainder, or None if buffer was empty / dropped.
        """
        if not self._buffer or drop_incomplete:
            self._buffer.clear()
            return None

        remainder = bytes(self._buffer)
        self._buffer.clear()

        # Check alignment with frame size
        bpf = self.format.bytes_per_frame
        if len(remainder) % bpf != 0:
            raise CorruptChunkError(
                f"Cannot flush remainder of {len(remainder)} bytes; not aligned to frame size {bpf} bytes"
            )

        duration = self.format.calculate_duration_ms(len(remainder))
        chunk = AudioChunk(
            data=remainder,
            format=self.format,
            sequence_id=self._sequence_id,
            timestamp_ms=self._timestamp_ms,
            duration_ms=duration,
        )
        self._sequence_id += 1
        self._timestamp_ms += duration
        return chunk

    def chunk_stream(self, stream: Iterable[bytes], flush_at_end: bool = True) -> Iterator[AudioChunk]:
        """Process an iterable stream of raw byte segments into an iterator of AudioChunks.

        Args:
            stream: Iterable yielding bytes segments.
            flush_at_end: Whether to flush remaining bytes upon stream completion.

        Yields:
            AudioChunk instances.
        """
        for byte_block in stream:
            for chunk in self.add_bytes(byte_block):
                yield chunk

        if flush_at_end:
            final_chunk = self.flush(drop_incomplete=False)
            if final_chunk is not None:
                yield final_chunk


class FakeMicrophoneSource:
    """Deterministic synthetic audio source simulating microphone capture.

    Produces reproducible audio streams without requiring hardware access or platform drivers.
    Ideal for unit testing, VAD development, and end-to-end integration benchmarks.
    """

    def __init__(
        self,
        audio_format: Optional[AudioFormat] = None,
        chunk_duration_ms: float = 20.0,
        signal_type: SignalType = SignalType.SINE_WAVE,
        frequency: float = 440.0,
        amplitude: float = 0.5,
        seed: int = 42,
        total_duration_ms: Optional[float] = None,
        total_chunks: Optional[int] = None,
    ) -> None:
        """Initialize FakeMicrophoneSource.

        Args:
            audio_format: AudioFormat specification (default: 16kHz, mono, 16-bit).
            chunk_duration_ms: Duration per chunk in ms (default: 20ms).
            signal_type: Synthetic pattern (SINE_WAVE, SILENCE, WHITE_NOISE, SPEECH_LIKE).
            frequency: Tone frequency in Hz for sine wave or speech pulses (default: 440.0 Hz).
            amplitude: Signal amplitude normalized between 0.0 and 1.0 (default: 0.5).
            seed: Random seed for WHITE_NOISE reproducibility (default: 42).
            total_duration_ms: Optional total stream limit in ms.
            total_chunks: Optional total chunk limit.
        """
        self.format = audio_format or AudioFormat()
        self.chunk_duration_ms = float(chunk_duration_ms)
        self.signal_type = SignalType(signal_type)
        self.frequency = float(frequency)
        self.amplitude = max(0.0, min(1.0, float(amplitude)))
        self.seed = int(seed)

        # Limits
        self.total_duration_ms = float(total_duration_ms) if total_duration_ms is not None else None
        self.total_chunks = int(total_chunks) if total_chunks is not None else None

        # Calculate chunk sizing
        self.chunker = DeterministicChunker(
            audio_format=self.format,
            chunk_duration_ms=self.chunk_duration_ms,
        )
        self.frames_per_chunk = self.chunker.chunk_byte_size // self.format.bytes_per_frame

        # Internal state
        self._samples_generated = 0
        self._chunks_emitted = 0
        self._rng = random.Random(self.seed)

    def reset(self) -> None:
        """Reset internal generator state and chunker."""
        self.chunker.reset()
        self._samples_generated = 0
        self._chunks_emitted = 0
        self._rng = random.Random(self.seed)

    def _generate_frame_samples(self, frame_index: int) -> List[int]:
        """Generate sample value(s) for a single frame at frame_index across all channels.

        Returns 16-bit signed integer values in [-32767, 32767].
        """
        max_int16 = 32767
        t_sec = frame_index / self.format.sample_rate

        if self.signal_type == SignalType.SILENCE:
            sample_val = 0

        elif self.signal_type == SignalType.SINE_WAVE:
            # Deterministic sine wave: A * sin(2 * pi * f * t)
            val = math.sin(2.0 * math.pi * self.frequency * t_sec)
            sample_val = int(round(val * self.amplitude * max_int16))

        elif self.signal_type == SignalType.WHITE_NOISE:
            # Deterministic pseudo-random uniform noise between -amplitude and +amplitude
            val = self._rng.uniform(-1.0, 1.0)
            sample_val = int(round(val * self.amplitude * max_int16))

        elif self.signal_type == SignalType.SPEECH_LIKE:
            # Emulate speech rhythm: 300ms voiced burst, 200ms pause cycle
            cycle_ms = 500.0
            pos_in_cycle_ms = (t_sec * 1000.0) % cycle_ms
            if pos_in_cycle_ms < 300.0:
                # Modulated harmonic tone
                tone = math.sin(2.0 * math.pi * self.frequency * t_sec)
                sub_harmonic = 0.3 * math.sin(2.0 * math.pi * (self.frequency * 0.5) * t_sec)
                val = (tone + sub_harmonic) / 1.3
                sample_val = int(round(val * self.amplitude * max_int16))
            else:
                # Silence between speech utterances
                sample_val = 0
        else:
            sample_val = 0

        # Clamp int16 bounds
        sample_val = max(-max_int16, min(max_int16, sample_val))

        # Replicate for all channels (e.g. mono: [s], stereo: [s, s])
        return [sample_val] * self.format.channels

    def read_chunk(self) -> Optional[AudioChunk]:
        """Generate and return the next single AudioChunk.

        Returns:
            The next AudioChunk, or None if stream limits (duration or chunk count) have been reached.
        """
        # Check termination conditions
        if self.total_chunks is not None and self._chunks_emitted >= self.total_chunks:
            return None

        if self.total_duration_ms is not None:
            current_ms = self.chunker.current_timestamp_ms
            if current_ms >= self.total_duration_ms:
                return None

        # Generate audio frame bytes
        raw_bytes_list: List[bytes] = []
        for _ in range(self.frames_per_chunk):
            channel_samples = self._generate_frame_samples(self._samples_generated)
            self._samples_generated += 1

            # Pack samples according to format
            if self.format.sample_width == 2:
                # signed 16-bit little-endian
                raw_bytes_list.append(struct.pack(f"<{self.format.channels}h", *channel_samples))
            elif self.format.sample_width == 1:
                # 8-bit unsigned PCM
                u8_samples = [max(0, min(255, int((s + 32767) / 256))) for s in channel_samples]
                raw_bytes_list.append(struct.pack(f"<{self.format.channels}B", *u8_samples))
            elif self.format.sample_width == 4:
                # 32-bit float PCM
                f32_samples = [s / 32767.0 for s in channel_samples]
                raw_bytes_list.append(struct.pack(f"<{self.format.channels}f", *f32_samples))
            else:
                raise AudioFormatError(f"Unsupported sample width: {self.format.sample_width}")

        chunk_bytes = b"".join(raw_bytes_list)

        chunks = self.chunker.add_bytes(chunk_bytes)
        if not chunks:
            return None

        chunk = chunks[0]
        self._chunks_emitted += 1
        return chunk

    def __iter__(self) -> Iterator[AudioChunk]:
        """Iterate over audio chunks until termination conditions are reached."""
        while True:
            chunk = self.read_chunk()
            if chunk is None:
                break
            yield chunk

    def generate_chunks(self, count: int) -> List[AudioChunk]:
        """Convenience method to generate an exact number of chunks.

        Args:
            count: Number of chunks to generate.

        Returns:
            List of generated AudioChunk instances.
        """
        if count < 0:
            raise ValueError(f"count must be non-negative, got {count}")
        result: List[AudioChunk] = []
        for _ in range(count):
            c = self.read_chunk()
            if c is None:
                break
            result.append(c)
        return result
