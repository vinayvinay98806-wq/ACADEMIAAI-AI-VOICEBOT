"""Unit tests specifically covering invalid, empty, and corrupt audio chunks (Days 5–6)."""

import unittest

from academiaai.audio.schemas import (
    AudioChunk,
    AudioChunkError,
    AudioError,
    AudioFormat,
    AudioFormatError,
    CorruptChunkError,
    EmptyChunkError,
)
from academiaai.audio.sources import DeterministicChunker


class TestAudioChunkIntegrityAndErrors(unittest.TestCase):
    """Test suite targeting error conditions for invalid, empty, and corrupt chunks."""

    def setUp(self) -> None:
        self.mono_format = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        self.stereo_format = AudioFormat(sample_rate=16000, channels=2, sample_width=2)

    def test_exception_hierarchy(self) -> None:
        """Verify that all audio exceptions correctly inherit from AudioError."""
        self.assertTrue(issubclass(AudioFormatError, AudioError))
        self.assertTrue(issubclass(AudioChunkError, AudioError))
        self.assertTrue(issubclass(EmptyChunkError, AudioChunkError))
        self.assertTrue(issubclass(CorruptChunkError, AudioChunkError))
        self.assertTrue(issubclass(EmptyChunkError, AudioError))
        self.assertTrue(issubclass(CorruptChunkError, AudioError))

    def test_empty_chunk_rejection(self) -> None:
        """Verify that an empty byte payload raises EmptyChunkError."""
        with self.assertRaises(EmptyChunkError) as ctx:
            AudioChunk(
                data=b"",
                format=self.mono_format,
                sequence_id=0,
                timestamp_ms=0.0,
            )
        self.assertIn("empty", str(ctx.exception).lower())

    def test_non_bytes_payload_rejection(self) -> None:
        """Verify that non-bytes/non-bytearray objects raise AudioChunkError."""
        invalid_payloads = [
            "audio string data",
            [0, 1, 2, 3],
            {"data": b"\x00\x00"},
            12345,
            None,
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=type(payload)):
                with self.assertRaises(AudioChunkError):
                    AudioChunk(
                        data=payload,  # type: ignore
                        format=self.mono_format,
                        sequence_id=0,
                        timestamp_ms=0.0,
                    )

    def test_corrupt_chunk_unaligned_mono(self) -> None:
        """Verify that odd/unaligned byte counts raise CorruptChunkError in mono 16-bit."""
        # For mono 16-bit, bytes_per_frame = 2. Any odd length is corrupt.
        odd_lengths = [1, 3, 5, 7, 319, 641]
        for length in odd_lengths:
            corrupt_bytes = b"\x00" * length
            with self.subTest(length=length):
                with self.assertRaises(CorruptChunkError) as ctx:
                    AudioChunk(
                        data=corrupt_bytes,
                        format=self.mono_format,
                        sequence_id=0,
                        timestamp_ms=0.0,
                    )
                self.assertIn("not aligned to frame size", str(ctx.exception))

    def test_corrupt_chunk_unaligned_stereo(self) -> None:
        """Verify that byte counts not divisible by 4 raise CorruptChunkError in stereo 16-bit."""
        # For stereo 16-bit, bytes_per_frame = 4.
        unaligned_lengths = [1, 2, 3, 5, 6, 7, 10]
        for length in unaligned_lengths:
            corrupt_bytes = b"\x00" * length
            with self.subTest(length=length):
                with self.assertRaises(CorruptChunkError):
                    AudioChunk(
                        data=corrupt_bytes,
                        format=self.stereo_format,
                        sequence_id=0,
                        timestamp_ms=0.0,
                    )

    def test_negative_sequence_id_rejection(self) -> None:
        """Verify that negative or non-integer sequence IDs raise AudioChunkError."""
        valid_data = b"\x00\x00" * 320
        invalid_seqs = [-1, -999, 1.5, "0", None, False]
        for seq in invalid_seqs:
            with self.subTest(seq=seq):
                with self.assertRaises(AudioChunkError):
                    AudioChunk(
                        data=valid_data,
                        format=self.mono_format,
                        sequence_id=seq,  # type: ignore
                        timestamp_ms=0.0,
                    )

    def test_negative_timestamp_rejection(self) -> None:
        """Verify that negative or non-numeric timestamps raise AudioChunkError."""
        valid_data = b"\x00\x00" * 320
        invalid_timestamps = [-0.1, -100.0, "0.0", None, True]
        for ts in invalid_timestamps:
            with self.subTest(ts=ts):
                with self.assertRaises(AudioChunkError):
                    AudioChunk(
                        data=valid_data,
                        format=self.mono_format,
                        sequence_id=0,
                        timestamp_ms=ts,  # type: ignore
                    )

    def test_inconsistent_duration_rejection(self) -> None:
        """Verify that explicit duration_ms conflicting with payload raises CorruptChunkError."""
        valid_data = b"\x00\x00" * 320  # exactly 20.0 ms of 16kHz mono audio
        # Claim 50.0 ms instead of 20.0 ms
        with self.assertRaises(CorruptChunkError) as ctx:
            AudioChunk(
                data=valid_data,
                format=self.mono_format,
                sequence_id=0,
                timestamp_ms=0.0,
                duration_ms=50.0,
            )
        self.assertIn("inconsistent", str(ctx.exception).lower())

        # Claim negative duration
        with self.assertRaises(AudioChunkError):
            AudioChunk(
                data=valid_data,
                format=self.mono_format,
                sequence_id=0,
                timestamp_ms=0.0,
                duration_ms=-20.0,
            )

    def test_chunker_flush_corrupt_remainder(self) -> None:
        """Verify that flushing an unaligned remainder from chunker raises CorruptChunkError."""
        chunker = DeterministicChunker(audio_format=self.mono_format, chunk_duration_ms=20.0)
        # Add 3 bytes (unaligned for 2-byte frames)
        chunker.add_bytes(b"\x01\x02\x03")
        with self.assertRaises(CorruptChunkError):
            chunker.flush(drop_incomplete=False)


if __name__ == "__main__":
    unittest.main()
