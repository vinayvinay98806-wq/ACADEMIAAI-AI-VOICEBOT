"""Unit tests for FakeMicrophoneSource and DeterministicChunker (Days 3–4)."""

import math
import struct
import unittest

from academiaai.audio.schemas import AudioChunk, AudioFormat
from academiaai.audio.sources import (
    DeterministicChunker,
    FakeMicrophoneSource,
    SignalType,
)


class TestDeterministicChunker(unittest.TestCase):
    """Test suite for DeterministicChunker buffer slicing and sequencing."""

    def setUp(self) -> None:
        self.format = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        # 20ms chunk = 640 bytes
        self.chunker = DeterministicChunker(
            audio_format=self.format,
            chunk_duration_ms=20.0,
        )

    def test_chunker_initial_state(self) -> None:
        """Verify initial state of chunker."""
        self.assertEqual(self.chunker.next_sequence_id, 0)
        self.assertEqual(self.chunker.current_timestamp_ms, 0.0)
        self.assertEqual(self.chunker.buffered_bytes, 0)
        self.assertEqual(self.chunker.chunk_byte_size, 640)

    def test_chunking_exact_multiple(self) -> None:
        """Test feeding exact multiple of chunk size (2 chunks = 1280 bytes)."""
        payload = b"\xaa" * 1280
        chunks = self.chunker.add_bytes(payload)

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].sequence_id, 0)
        self.assertEqual(chunks[0].timestamp_ms, 0.0)
        self.assertAlmostEqual(chunks[0].duration_ms, 20.0)
        self.assertEqual(len(chunks[0].data), 640)

        self.assertEqual(chunks[1].sequence_id, 1)
        self.assertEqual(chunks[1].timestamp_ms, 20.0)
        self.assertAlmostEqual(chunks[1].duration_ms, 20.0)
        self.assertEqual(len(chunks[1].data), 640)

        self.assertEqual(self.chunker.buffered_bytes, 0)
        self.assertEqual(self.chunker.next_sequence_id, 2)
        self.assertEqual(self.chunker.current_timestamp_ms, 40.0)

    def test_chunking_with_arbitrary_packet_sizes(self) -> None:
        """Test feeding irregular packet sizes (e.g. network/ring-buffer fragments)."""
        # Feed 100 bytes at a time
        total_chunks = []
        packet = b"\x55" * 100

        for i in range(15):  # 15 * 100 = 1500 bytes -> 2 full 640-byte chunks (1280 bytes) + 220 remainder
            produced = self.chunker.add_bytes(packet)
            total_chunks.extend(produced)

        self.assertEqual(len(total_chunks), 2)
        self.assertEqual(self.chunker.buffered_bytes, 220)

        # Sequence IDs must be strictly sequential
        self.assertEqual([c.sequence_id for c in total_chunks], [0, 1])
        self.assertEqual([c.timestamp_ms for c in total_chunks], [0.0, 20.0])

        # Flush remainder
        final_chunk = self.chunker.flush(drop_incomplete=False)
        self.assertIsNotNone(final_chunk)
        assert final_chunk is not None
        self.assertEqual(final_chunk.sequence_id, 2)
        self.assertEqual(final_chunk.timestamp_ms, 40.0)
        self.assertEqual(len(final_chunk.data), 220)
        # 220 bytes at 16-bit mono (32 bytes/ms) = 6.875 ms
        self.assertAlmostEqual(final_chunk.duration_ms, 6.875)
        self.assertEqual(self.chunker.buffered_bytes, 0)

    def test_chunk_stream(self) -> None:
        """Test processing stream generator via chunk_stream."""
        def stream_generator():
            yield b"\x01\x02" * 200   # 400 bytes
            yield b"\x03\x04" * 300   # 600 bytes (total 1000 bytes)
            yield b"\x05\x06" * 140   # 280 bytes (total 1280 bytes = 2 exact chunks)

        chunks = list(self.chunker.chunk_stream(stream_generator()))
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].sequence_id, 0)
        self.assertEqual(chunks[1].sequence_id, 1)

    def test_reset(self) -> None:
        """Test that reset clears buffer and sequence counter."""
        self.chunker.add_bytes(b"\x00" * 700)  # yields 1 chunk, 60 bytes remain
        self.assertEqual(self.chunker.next_sequence_id, 1)
        self.assertEqual(self.chunker.buffered_bytes, 60)

        self.chunker.reset()
        self.assertEqual(self.chunker.next_sequence_id, 0)
        self.assertEqual(self.chunker.current_timestamp_ms, 0.0)
        self.assertEqual(self.chunker.buffered_bytes, 0)


class TestFakeMicrophoneSource(unittest.TestCase):
    """Test suite for FakeMicrophoneSource deterministic audio generator."""

    def test_silence_signal(self) -> None:
        """Test generating silence produces zeroed byte chunks."""
        mic = FakeMicrophoneSource(
            signal_type=SignalType.SILENCE,
            chunk_duration_ms=20.0,
            total_chunks=3,
        )
        chunks = list(mic)
        self.assertEqual(len(chunks), 3)

        for i, chunk in enumerate(chunks):
            self.assertEqual(chunk.sequence_id, i)
            self.assertAlmostEqual(chunk.timestamp_ms, i * 20.0)
            self.assertEqual(chunk.data, b"\x00" * 640)

    def test_sine_wave_determinism(self) -> None:
        """Test sine wave generation produces non-zero, mathematically deterministic samples."""
        mic = FakeMicrophoneSource(
            signal_type=SignalType.SINE_WAVE,
            frequency=440.0,
            amplitude=0.8,
            chunk_duration_ms=20.0,
            total_chunks=5,
        )
        chunks_run1 = list(mic)

        # Reset and generate again
        mic.reset()
        chunks_run2 = list(mic)

        self.assertEqual(len(chunks_run1), 5)
        self.assertEqual(len(chunks_run2), 5)

        for c1, c2 in zip(chunks_run1, chunks_run2):
            self.assertEqual(c1.data, c2.data)
            self.assertEqual(c1.sequence_id, c2.sequence_id)
            self.assertEqual(c1.timestamp_ms, c2.timestamp_ms)

        # Check that sine wave is not silence
        first_chunk = chunks_run1[0]
        self.assertNotEqual(first_chunk.data, b"\x00" * len(first_chunk.data))

        # Check first sample is 0 (since sin(0) = 0)
        first_sample = struct.unpack("<h", first_chunk.data[:2])[0]
        self.assertEqual(first_sample, 0)

    def test_white_noise_reproducibility(self) -> None:
        """Test that identical seeds generate bit-for-bit identical white noise."""
        mic1 = FakeMicrophoneSource(
            signal_type=SignalType.WHITE_NOISE,
            seed=12345,
            total_chunks=4,
        )
        mic2 = FakeMicrophoneSource(
            signal_type=SignalType.WHITE_NOISE,
            seed=12345,
            total_chunks=4,
        )
        mic3 = FakeMicrophoneSource(
            signal_type=SignalType.WHITE_NOISE,
            seed=99999,
            total_chunks=4,
        )

        c1 = [c.data for c in mic1]
        c2 = [c.data for c in mic2]
        c3 = [c.data for c in mic3]

        self.assertEqual(c1, c2, "Same seed must generate identical noise")
        self.assertNotEqual(c1, c3, "Different seeds must generate distinct noise")

    def test_speech_like_pattern(self) -> None:
        """Test speech-like pattern produces chunks with voiced and unvoiced intervals."""
        # 50 chunks = 1000ms (two complete 500ms speech burst/silence cycles)
        mic = FakeMicrophoneSource(
            signal_type=SignalType.SPEECH_LIKE,
            chunk_duration_ms=20.0,
            total_chunks=50,
        )
        chunks = list(mic)
        self.assertEqual(len(chunks), 50)

        # First chunk (0-20ms) should be voiced (non-zero)
        self.assertNotEqual(chunks[0].data, b"\x00" * 640)
        # Chunks in the 320ms - 480ms range should be unvoiced / silence
        # (e.g., chunk index 18 is 360ms - 380ms)
        self.assertEqual(chunks[18].data, b"\x00" * 640)

    def test_total_duration_limit(self) -> None:
        """Test total_duration_ms stopping condition."""
        mic = FakeMicrophoneSource(
            chunk_duration_ms=20.0,
            total_duration_ms=100.0,  # Exactly 5 chunks
        )
        chunks = list(mic)
        self.assertEqual(len(chunks), 5)
        self.assertAlmostEqual(chunks[-1].timestamp_ms, 80.0)


if __name__ == "__main__":
    unittest.main()
