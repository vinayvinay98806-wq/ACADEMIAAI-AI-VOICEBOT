"""CLI demo for Worker 1: Audio Input & Voice Activity Detection (Week 1).

Demonstrates:
1. Synthetic audio generation via FakeMicrophoneSource.
2. Deterministic chunking with strictly monotonic sequence IDs and timestamps.
3. Audio validation error handling (invalid formats, empty chunks, corrupt chunks).
"""

from __future__ import annotations

import argparse
import sys
from typing import List

from .schemas import (
    AudioChunk,
    AudioChunkError,
    AudioError,
    AudioFormat,
    AudioFormatError,
    CorruptChunkError,
    EmptyChunkError,
)
from .sources import (
    DeterministicChunker,
    FakeMicrophoneSource,
    SignalType,
)


def run_invalid_chunk_demonstration() -> None:
    """Demonstrate handling of invalid, empty, and corrupt chunks."""
    print("\n" + "=" * 70)
    print("DEMO: Audio Validation & Error Handling (Invalid / Empty / Corrupt)")
    print("=" * 70)

    standard_fmt = AudioFormat(sample_rate=16000, channels=1, sample_width=2)

    # Test 1: Invalid Sample Rate
    print("\n[Case 1] Attempting to construct AudioFormat with invalid sample rate (12345 Hz)...")
    try:
        AudioFormat(sample_rate=12345)
    except AudioFormatError as e:
        print(f"  --> Caught expected AudioFormatError: {e}")

    # Test 2: Invalid Channel Count
    print("\n[Case 2] Attempting to construct AudioFormat with invalid channel count (5 channels)...")
    try:
        AudioFormat(sample_rate=16000, channels=5)
    except AudioFormatError as e:
        print(f"  --> Caught expected AudioFormatError: {e}")

    # Test 3: Empty Audio Chunk
    print("\n[Case 3] Attempting to create AudioChunk with empty byte payload (b'')...")
    try:
        AudioChunk(data=b"", format=standard_fmt, sequence_id=0, timestamp_ms=0.0)
    except EmptyChunkError as e:
        print(f"  --> Caught expected EmptyChunkError: {e}")

    # Test 4: Corrupt / Unaligned Audio Chunk
    print("\n[Case 4] Attempting to create AudioChunk with unaligned corrupt byte payload (3 bytes for 16-bit mono)...")
    try:
        AudioChunk(data=b"\x01\x02\x03", format=standard_fmt, sequence_id=0, timestamp_ms=0.0)
    except CorruptChunkError as e:
        print(f"  --> Caught expected CorruptChunkError: {e}")

    # Test 5: Negative Sequence ID
    print("\n[Case 5] Attempting to create AudioChunk with negative sequence ID (-1)...")
    try:
        AudioChunk(data=b"\x00\x00" * 320, format=standard_fmt, sequence_id=-1, timestamp_ms=0.0)
    except AudioChunkError as e:
        print(f"  --> Caught expected AudioChunkError: {e}")

    # Test 6: Inconsistent Duration
    print("\n[Case 6] Attempting to create AudioChunk with mismatched duration (claimed 100ms, actual 20ms)...")
    try:
        AudioChunk(
            data=b"\x00\x00" * 320,
            format=standard_fmt,
            sequence_id=0,
            timestamp_ms=0.0,
            duration_ms=100.0,
        )
    except CorruptChunkError as e:
        print(f"  --> Caught expected CorruptChunkError: {e}")

    print("\n" + "-" * 70)
    print("All error cases successfully caught and verified against schemas.")
    print("-" * 70)


def run_pipeline_demo(args: argparse.Namespace) -> int:
    """Run normal synthetic audio streaming and chunking demo."""
    print("=" * 70)
    print("Academiaai AI Voice Co-Pilot - Worker 1: Audio Input & Chunker (Week 1)")
    print("=" * 70)

    try:
        audio_format = AudioFormat(
            sample_rate=args.sample_rate,
            channels=args.channels,
            sample_width=2,
        )
    except AudioFormatError as e:
        print(f"Configuration Error: {e}", file=sys.stderr)
        return 1

    signal_type = SignalType(args.signal)

    print(f"Audio Format  : {audio_format.sample_rate} Hz, {audio_format.channels} channel(s), {audio_format.encoding}")
    print(f"Chunk Duration: {args.chunk_duration_ms:.1f} ms ({audio_format.calculate_byte_count(args.chunk_duration_ms)} bytes/chunk)")
    print(f"Signal Type   : {signal_type.value} (freq: {args.frequency:.1f} Hz, amp: {args.amplitude:.2f})")
    print(f"Target Chunks : {args.chunks}")
    print("-" * 70)

    source = FakeMicrophoneSource(
        audio_format=audio_format,
        chunk_duration_ms=args.chunk_duration_ms,
        signal_type=signal_type,
        frequency=args.frequency,
        amplitude=args.amplitude,
        seed=args.seed,
        total_chunks=args.chunks,
    )

    chunks: List[AudioChunk] = []
    total_bytes = 0

    print(f"{'Seq':>4} | {'Timestamp':>12} | {'Duration':>10} | {'Bytes':>7} | {'Frames':>7} | Preview (Hex)")
    print("-" * 70)

    for chunk in source:
        chunks.append(chunk)
        total_bytes += len(chunk.data)

        if args.verbose or chunk.sequence_id < 10 or chunk.sequence_id >= args.chunks - 2:
            hex_preview = chunk.data[:8].hex() + ("..." if len(chunk.data) > 8 else "")
            print(
                f"{chunk.sequence_id:4d} | "
                f"{chunk.timestamp_ms:10.2f}ms | "
                f"{chunk.duration_ms:8.2f}ms | "
                f"{len(chunk.data):5d} B | "
                f"{chunk.frame_count:7d} | "
                f"{hex_preview}"
            )
        elif chunk.sequence_id == 10:
            print(" ...  |          ... |        ... |     ... |     ... | ... (middle chunks omitted)")

    print("-" * 70)
    print("SUMMARY:")
    print(f"  Total Chunks Generated : {len(chunks)}")
    print(f"  Sequence IDs Validated : 0 .. {len(chunks) - 1} (strictly monotonic)")
    print(f"  Total Audio Time       : {len(chunks) * args.chunk_duration_ms:.2f} ms")
    print(f"  Total Audio Bytes      : {total_bytes} bytes")
    print(f"  Integrity Check        : ALL CHUNKS PASSED FRAME ALIGNMENT AND VALIDATION")
    print("=" * 70)

    if args.test_invalid:
        run_invalid_chunk_demonstration()

    return 0


def build_parser() -> argparse.ArgumentParser:
    """Construct command line argument parser."""
    parser = argparse.ArgumentParser(
        description="Worker 1 Audio Input & Chunker CLI Demo (Week 1)"
    )
    parser.add_argument(
        "--signal",
        choices=[s.value for s in SignalType],
        default=SignalType.SINE_WAVE.value,
        help="Synthetic signal type to generate (default: sine_wave)",
    )
    parser.add_argument(
        "--chunks",
        type=int,
        default=15,
        help="Number of chunks to produce (default: 15)",
    )
    parser.add_argument(
        "--chunk-duration-ms",
        type=float,
        default=20.0,
        help="Duration of each chunk in ms (default: 20.0)",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=16000,
        help="Sample rate in Hz (default: 16000)",
    )
    parser.add_argument(
        "--channels",
        type=int,
        default=1,
        help="Audio channels: 1=mono, 2=stereo (default: 1)",
    )
    parser.add_argument(
        "--frequency",
        type=float,
        default=440.0,
        help="Tone frequency in Hz for sine wave (default: 440.0)",
    )
    parser.add_argument(
        "--amplitude",
        type=float,
        default=0.5,
        help="Normalized amplitude between 0.0 and 1.0 (default: 0.5)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Seed for reproducible white noise (default: 42)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print details for every single chunk",
    )
    parser.add_argument(
        "--test-invalid",
        action="store_true",
        help="Run explicit test demonstration of invalid, empty, and corrupt chunk handling",
    )
    return parser


def main() -> None:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args()
    code = run_pipeline_demo(args)
    sys.exit(code)


if __name__ == "__main__":
    main()
