"""Bounded FIFO audio buffer implementation for Worker 1.

Features:
- Configurable maximum capacity enforcing strict bounded memory usage.
- Explicit backpressure policies (DROP_NEWEST by default, DROP_OLDEST optional).
- Observable metrics: dropped chunks, overflow counts, sequence gaps, late/duplicate chunks.
- Deterministic handling of out-of-order and late chunks without silent reordering or duplication.
- Thread-safe FIFO operations using reentrant locks.
"""

from __future__ import annotations

import collections
import enum
import threading
from dataclasses import dataclass
from typing import Deque, Optional

from .schemas import AudioChunk, AudioError


# ============================================================================
# Buffer Exceptions
# ============================================================================

class AudioBufferError(AudioError):
    """Base exception for audio buffer errors."""
    pass


class BufferCapacityError(AudioBufferError):
    """Raised when an invalid buffer capacity is configured."""
    pass


# ============================================================================
# Backpressure Policies
# ============================================================================

class BackpressurePolicy(str, enum.Enum):
    """Policy applied when pushing into a full buffer.

    DROP_NEWEST: The new incoming chunk is dropped/rejected. Existing buffered audio is preserved.
    DROP_OLDEST: The oldest chunk in the FIFO queue is evicted to make room for the new chunk.
    """
    DROP_NEWEST = "DROP_NEWEST"
    DROP_OLDEST = "DROP_OLDEST"


# ============================================================================
# Buffer Statistics
# ============================================================================

@dataclass(frozen=True)
class BufferStats:
    """Snapshot of buffer state and operational counters.

    Attributes:
        capacity: Maximum chunk capacity.
        current_size: Number of chunks currently stored.
        total_pushed: Total chunks accepted for push evaluation.
        total_popped: Total chunks successfully popped.
        dropped_chunks: Total chunks dropped due to buffer capacity overflow.
        overflow_count: Total overflow events recorded.
        sequence_gaps: Total missing sequence IDs observed.
        late_chunks: Chunks arriving with sequence ID earlier than seen so far.
        duplicate_chunks: Chunks arriving with sequence ID already seen.
        total_duration_ms: Total audio duration currently retained in buffer.
    """
    capacity: int
    current_size: int
    total_pushed: int
    total_popped: int
    dropped_chunks: int
    overflow_count: int
    sequence_gaps: int
    late_chunks: int
    duplicate_chunks: int
    total_duration_ms: float


# ============================================================================
# Bounded Audio Buffer Implementation
# ============================================================================

class BoundedAudioBuffer:
    """Bounded FIFO audio buffer with explicit backpressure and sequence tracking."""

    def __init__(
        self,
        max_capacity: int = 50,
        policy: BackpressurePolicy = BackpressurePolicy.DROP_NEWEST,
    ) -> None:
        """Initialize BoundedAudioBuffer.

        Args:
            max_capacity: Maximum number of chunks allowed in buffer (must be > 0).
            policy: BackpressurePolicy to use on overflow (default: DROP_NEWEST).

        Raises:
            BufferCapacityError: If max_capacity <= 0.
        """
        if not isinstance(max_capacity, int) or isinstance(max_capacity, bool) or max_capacity <= 0:
            raise BufferCapacityError(
                f"max_capacity must be a positive integer (> 0), got {max_capacity!r}"
            )

        self.max_capacity = max_capacity
        self.policy = BackpressurePolicy(policy)

        self._buffer: Deque[AudioChunk] = collections.deque()
        self._lock = threading.RLock()

        # Operational metrics
        self._total_pushed: int = 0
        self._total_popped: int = 0
        self._dropped_chunks: int = 0
        self._overflow_count: int = 0
        self._sequence_gaps: int = 0
        self._late_chunks: int = 0
        self._duplicate_chunks: int = 0
        self._last_seen_sequence_id: Optional[int] = None

    @property
    def capacity(self) -> int:
        """Maximum chunk capacity."""
        return self.max_capacity

    @property
    def size(self) -> int:
        """Number of chunks currently buffered."""
        with self._lock:
            return len(self._buffer)

    def __len__(self) -> int:
        return self.size

    @property
    def is_empty(self) -> bool:
        """Whether the buffer contains zero chunks."""
        with self._lock:
            return len(self._buffer) == 0

    @property
    def is_full(self) -> bool:
        """Whether the buffer is at full capacity."""
        with self._lock:
            return len(self._buffer) >= self.max_capacity

    @property
    def dropped_chunks(self) -> int:
        """Total chunks dropped due to overflow."""
        with self._lock:
            return self._dropped_chunks

    @property
    def overflow_count(self) -> int:
        """Total overflow events."""
        with self._lock:
            return self._overflow_count

    @property
    def sequence_gaps(self) -> int:
        """Total sequence gaps detected."""
        with self._lock:
            return self._sequence_gaps

    @property
    def late_chunks(self) -> int:
        """Total out-of-order/late chunks detected and rejected."""
        with self._lock:
            return self._late_chunks

    @property
    def total_duration_ms(self) -> float:
        """Total duration in milliseconds of chunks currently in the buffer."""
        with self._lock:
            return sum(c.duration_ms or 0.0 for c in self._buffer)

    def push(self, chunk: AudioChunk) -> bool:
        """Push an AudioChunk into the bounded FIFO buffer.

        Validates chunk integrity, tracks sequence continuity, rejects late/duplicate
        chunks deterministically, and applies the configured backpressure policy when full.

        Args:
            chunk: AudioChunk to push.

        Returns:
            True if the chunk was successfully enqueued; False if rejected or dropped.

        Raises:
            AudioBufferError: If chunk is not an AudioChunk.
        """
        if not isinstance(chunk, AudioChunk):
            raise AudioBufferError(f"Expected AudioChunk, got {type(chunk).__name__}")

        with self._lock:
            # 1. Sequence Continuity & Out-of-order check
            if self._last_seen_sequence_id is not None:
                if chunk.sequence_id == self._last_seen_sequence_id:
                    self._duplicate_chunks += 1
                    return False
                elif chunk.sequence_id < self._last_seen_sequence_id:
                    self._late_chunks += 1
                    return False
                elif chunk.sequence_id > self._last_seen_sequence_id + 1:
                    gap = chunk.sequence_id - (self._last_seen_sequence_id + 1)
                    self._sequence_gaps += gap

            self._last_seen_sequence_id = chunk.sequence_id
            self._total_pushed += 1

            # 2. Capacity & Backpressure Check
            if len(self._buffer) >= self.max_capacity:
                self._overflow_count += 1
                self._dropped_chunks += 1

                if self.policy == BackpressurePolicy.DROP_NEWEST:
                    # Drop incoming chunk, keep existing queue intact
                    return False
                elif self.policy == BackpressurePolicy.DROP_OLDEST:
                    # Evict oldest chunk from head of queue and append new chunk
                    self._buffer.popleft()
                    self._buffer.append(chunk)
                    return True

            self._buffer.append(chunk)
            return True

    def pop(self) -> Optional[AudioChunk]:
        """Remove and return the oldest AudioChunk from the FIFO queue.

        Returns:
            The next AudioChunk, or None if the buffer is empty.
        """
        with self._lock:
            if not self._buffer:
                return None
            self._total_popped += 1
            return self._buffer.popleft()

    def peek(self) -> Optional[AudioChunk]:
        """Inspect the oldest AudioChunk without removing it.

        Returns:
            The next AudioChunk, or None if the buffer is empty.
        """
        with self._lock:
            return self._buffer[0] if self._buffer else None

    def clear(self) -> None:
        """Clear all chunks from the buffer while retaining operational metrics."""
        with self._lock:
            self._buffer.clear()

    def reset_stats(self) -> None:
        """Reset operational and diagnostic metrics."""
        with self._lock:
            self._total_pushed = 0
            self._total_popped = 0
            self._dropped_chunks = 0
            self._overflow_count = 0
            self._sequence_gaps = 0
            self._late_chunks = 0
            self._duplicate_chunks = 0
            self._last_seen_sequence_id = None

    def get_stats(self) -> BufferStats:
        """Return an immutable snapshot of current buffer statistics."""
        with self._lock:
            return BufferStats(
                capacity=self.max_capacity,
                current_size=len(self._buffer),
                total_pushed=self._total_pushed,
                total_popped=self._total_popped,
                dropped_chunks=self._dropped_chunks,
                overflow_count=self._overflow_count,
                sequence_gaps=self._sequence_gaps,
                late_chunks=self._late_chunks,
                duplicate_chunks=self._duplicate_chunks,
                total_duration_ms=self.total_duration_ms,
            )
