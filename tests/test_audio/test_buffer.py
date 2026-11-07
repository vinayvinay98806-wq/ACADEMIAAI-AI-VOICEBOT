"""Unit tests for BoundedAudioBuffer (Week 2)."""

import unittest

from academiaai.audio.buffer import (
    AudioBufferError,
    BackpressurePolicy,
    BoundedAudioBuffer,
    BufferCapacityError,
)
from academiaai.audio.schemas import AudioChunk, AudioFormat


class TestBoundedAudioBuffer(unittest.TestCase):
    """Test suite for BoundedAudioBuffer FIFO queue and backpressure policies."""

    def setUp(self) -> None:
        self.format = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        self.payload = b"\x00\x00" * 320  # 20ms silence payload

    def _make_chunk(self, seq_id: int, timestamp_ms: float = 0.0) -> AudioChunk:
        """Helper to create valid AudioChunk with specified sequence_id."""
        return AudioChunk(
            data=self.payload,
            format=self.format,
            sequence_id=seq_id,
            timestamp_ms=timestamp_ms,
        )

    def test_initial_state(self) -> None:
        """Verify initial buffer properties and metrics."""
        buf = BoundedAudioBuffer(max_capacity=5)
        self.assertEqual(buf.capacity, 5)
        self.assertEqual(buf.size, 0)
        self.assertTrue(buf.is_empty)
        self.assertFalse(buf.is_full)
        self.assertEqual(buf.dropped_chunks, 0)
        self.assertEqual(buf.overflow_count, 0)
        self.assertEqual(buf.sequence_gaps, 0)
        self.assertEqual(buf.late_chunks, 0)
        self.assertEqual(buf.total_duration_ms, 0.0)

    def test_invalid_capacity(self) -> None:
        """Verify non-positive or non-integer capacity raises BufferCapacityError."""
        for cap in [0, -1, -100, "5", 5.5, True]:
            with self.subTest(cap=cap):
                with self.assertRaises(BufferCapacityError):
                    BoundedAudioBuffer(max_capacity=cap)  # type: ignore

    def test_fifo_ordering(self) -> None:
        """Verify standard first-in-first-out ordering of chunks."""
        buf = BoundedAudioBuffer(max_capacity=5)
        c0 = self._make_chunk(0, 0.0)
        c1 = self._make_chunk(1, 20.0)
        c2 = self._make_chunk(2, 40.0)

        self.assertTrue(buf.push(c0))
        self.assertTrue(buf.push(c1))
        self.assertTrue(buf.push(c2))

        self.assertEqual(buf.size, 3)
        self.assertEqual(buf.pop(), c0)
        self.assertEqual(buf.pop(), c1)
        self.assertEqual(buf.pop(), c2)
        self.assertTrue(buf.is_empty)

    def test_peek_operation(self) -> None:
        """Verify peek inspects head without removing it."""
        buf = BoundedAudioBuffer(max_capacity=3)
        c0 = self._make_chunk(0)
        buf.push(c0)

        self.assertEqual(buf.peek(), c0)
        self.assertEqual(buf.size, 1)
        self.assertEqual(buf.pop(), c0)
        self.assertIsNone(buf.peek())

    def test_empty_pop_behavior(self) -> None:
        """Verify popping an empty buffer returns None."""
        buf = BoundedAudioBuffer(max_capacity=5)
        self.assertIsNone(buf.pop())
        self.assertIsNone(buf.peek())

    def test_capacity_enforcement_and_drop_newest_policy(self) -> None:
        """Test DROP_NEWEST backpressure policy when buffer is full."""
        buf = BoundedAudioBuffer(max_capacity=3, policy=BackpressurePolicy.DROP_NEWEST)

        c0 = self._make_chunk(0)
        c1 = self._make_chunk(1)
        c2 = self._make_chunk(2)
        c3 = self._make_chunk(3)  # Over capacity!

        self.assertTrue(buf.push(c0))
        self.assertTrue(buf.push(c1))
        self.assertTrue(buf.push(c2))
        self.assertTrue(buf.is_full)
        self.assertEqual(buf.size, 3)

        # 4th chunk should be dropped
        accepted = buf.push(c3)
        self.assertFalse(accepted)
        self.assertEqual(buf.size, 3)
        self.assertEqual(buf.dropped_chunks, 1)
        self.assertEqual(buf.overflow_count, 1)

        # Chunks in buffer must still be c0, c1, c2
        self.assertEqual(buf.pop(), c0)
        self.assertEqual(buf.pop(), c1)
        self.assertEqual(buf.pop(), c2)
        self.assertIsNone(buf.pop())

    def test_capacity_enforcement_and_drop_oldest_policy(self) -> None:
        """Test DROP_OLDEST backpressure policy evicts oldest chunk."""
        buf = BoundedAudioBuffer(max_capacity=2, policy=BackpressurePolicy.DROP_OLDEST)

        c0 = self._make_chunk(0)
        c1 = self._make_chunk(1)
        c2 = self._make_chunk(2)  # Should evict c0!

        buf.push(c0)
        buf.push(c1)
        self.assertTrue(buf.is_full)

        accepted = buf.push(c2)
        self.assertTrue(accepted)
        self.assertEqual(buf.size, 2)
        self.assertEqual(buf.dropped_chunks, 1)
        self.assertEqual(buf.overflow_count, 1)

        # c0 was evicted, c1 and c2 remain
        self.assertEqual(buf.pop(), c1)
        self.assertEqual(buf.pop(), c2)
        self.assertIsNone(buf.pop())

    def test_clear_operation(self) -> None:
        """Verify clear() empties buffer while preserving metrics."""
        buf = BoundedAudioBuffer(max_capacity=5)
        buf.push(self._make_chunk(0))
        buf.push(self._make_chunk(1))

        self.assertEqual(buf.size, 2)
        buf.clear()
        self.assertEqual(buf.size, 0)
        self.assertTrue(buf.is_empty)

    def test_late_chunks_rejection(self) -> None:
        """Verify late/out-of-order chunks are rejected and counted deterministically."""
        buf = BoundedAudioBuffer(max_capacity=5)

        c0 = self._make_chunk(0)
        c2 = self._make_chunk(2)
        c1 = self._make_chunk(1)  # Late! Came after 2

        self.assertTrue(buf.push(c0))
        self.assertTrue(buf.push(c2))  # Gaps: seq 1 missed (+1)
        self.assertEqual(buf.sequence_gaps, 1)

        # Push c1 (late chunk: seq 1 < last seen 2)
        pushed = buf.push(c1)
        self.assertFalse(pushed)
        self.assertEqual(buf.late_chunks, 1)

        # Buffer must retain c0, c2 and NOT insert c1
        self.assertEqual(buf.size, 2)
        self.assertEqual(buf.pop(), c0)
        self.assertEqual(buf.pop(), c2)

    def test_duplicate_chunk_rejection(self) -> None:
        """Verify duplicate chunks with identical sequence_id are rejected."""
        buf = BoundedAudioBuffer(max_capacity=5)

        c0 = self._make_chunk(0)
        c0_dup = self._make_chunk(0)

        self.assertTrue(buf.push(c0))
        self.assertFalse(buf.push(c0_dup))
        self.assertEqual(buf.size, 1)
        self.assertEqual(buf.get_stats().duplicate_chunks, 1)

    def test_sequence_gaps_counter(self) -> None:
        """Verify multiple sequence gaps are accurately counted."""
        buf = BoundedAudioBuffer(max_capacity=10)

        buf.push(self._make_chunk(0))
        buf.push(self._make_chunk(5))  # Gap of 4 (1, 2, 3, 4)
        self.assertEqual(buf.sequence_gaps, 4)

        buf.push(self._make_chunk(8))  # Gap of 2 (6, 7)
        self.assertEqual(buf.sequence_gaps, 6)

    def test_long_streams_bounded_memory(self) -> None:
        """Verify memory stays strictly bounded during a high-volume stream."""
        capacity = 25
        buf = BoundedAudioBuffer(max_capacity=capacity, policy=BackpressurePolicy.DROP_NEWEST)

        # Push 1000 chunks
        for i in range(1000):
            chunk = self._make_chunk(i, timestamp_ms=i * 20.0)
            buf.push(chunk)

        self.assertEqual(buf.size, capacity)
        self.assertEqual(buf.dropped_chunks, 1000 - capacity)
        self.assertEqual(buf.overflow_count, 1000 - capacity)

    def test_stats_reporting_and_reset(self) -> None:
        """Verify get_stats returns full snapshot and reset_stats clears metrics."""
        buf = BoundedAudioBuffer(max_capacity=5)
        c0 = self._make_chunk(0)
        buf.push(c0)
        buf.pop()

        stats = buf.get_stats()
        self.assertEqual(stats.capacity, 5)
        self.assertEqual(stats.total_pushed, 1)
        self.assertEqual(stats.total_popped, 1)
        self.assertEqual(stats.current_size, 0)

        buf.reset_stats()
        stats_after = buf.get_stats()
        self.assertEqual(stats_after.total_pushed, 0)
        self.assertEqual(stats_after.total_popped, 0)

    def test_push_non_chunk_raises(self) -> None:
        """Verify pushing non-AudioChunk raises AudioBufferError."""
        buf = BoundedAudioBuffer(max_capacity=5)
        with self.assertRaises(AudioBufferError):
            buf.push("invalid")  # type: ignore


if __name__ == "__main__":
    unittest.main()
