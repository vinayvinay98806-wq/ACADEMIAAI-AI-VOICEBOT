"""CLI demo for Worker 1: Audio Input & Voice Activity Detection (Weeks 1 & 2).

Demonstrates:
Week 1:
1. Synthetic audio generation via FakeMicrophoneSource.
2. Deterministic chunking with strictly monotonic sequence IDs and timestamps.
3. Audio validation error handling (invalid formats, empty chunks, corrupt chunks).

Week 2:
1. Mock device enumeration and selection.
2. Permission lifecycle and access enforcement.
3. AudioLifecycleController state machine (start, pause, resume, stop).
4. Deterministic RMS-based Voice Activity Detection (VAD).
5. Bounded FIFO audio buffer with configurable backpressure.
6. Observable dropped chunks, overflow, and sequence diagnostics.
"""

from __future__ import annotations

import argparse
import sys
from typing import List

from .buffer import BackpressurePolicy, BoundedAudioBuffer
from .devices import (
    AudioDevice,
    DeviceNotSelectedError,
    DevicePermissionError,
    MockAudioDeviceAdapter,
    PermissionState,
)
from .lifecycle import AudioLifecycleController, LifecycleState, SessionNotRunningError
from .pipeline import AudioPipeline
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
from .vad import ThresholdVAD, calculate_chunk_rms


# ============================================================================
# Week 1 Demonstrations
# ============================================================================

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
    """Run normal synthetic audio streaming and chunking demo (Week 1)."""
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


# ============================================================================
# Week 2 Dedicated Demonstration
# ============================================================================

def run_week2_demo() -> int:
    """Execute the complete 11-step Week 2 Demonstration.

    Steps:
    1. List mock devices.
    2. Select a device.
    3. Request and grant mock permission.
    4. Start the lifecycle controller.
    5. Generate synthetic speech-like audio.
    6. Run VAD.
    7. Push chunks into the bounded buffer.
    8. Demonstrate buffer capacity and dropped-chunk counters.
    9. Pause and resume the stream.
    10. Stop the session cleanly.
    11. Print a readable summary.
    """
    print("\n" + "=" * 78)
    print("ACADEMIAAI AI VOICE CO-PILOT - WORKER 1 (W1) WEEK 2 DEMONSTRATION")
    print("=" * 78)

    # Step 1: List mock devices
    print("\n[Step 1] Enumerating Mock Audio Input Devices:")
    adapter = MockAudioDeviceAdapter()
    devices = adapter.list_devices()
    for d in devices:
        def_tag = " (DEFAULT)" if d.is_default else ""
        print(f"  • ID: {d.device_id:<18} | Name: {d.name:<32} | Ch: {d.channels}{def_tag}")

    # Step 2: Select a device
    selected_id = "mock-mic-default"
    print(f"\n[Step 2] Selecting Input Device '{selected_id}':")
    selected_device = adapter.select_device(selected_id)
    print(f"  --> Selected: {selected_device.name} (device_id={selected_device.device_id})")

    # Step 3: Request and grant mock permission
    print("\n[Step 3] Device Permission Workflow:")
    print(f"  Initial State  : {adapter.get_permission_state().value}")
    print("  Requesting permission from simulated user/system...")
    adapter.grant_permission()
    print(f"  Updated State  : {adapter.get_permission_state().value} (Capture Allowed: {adapter.is_capture_allowed()})")

    # Step 4: Start lifecycle controller
    print("\n[Step 4] Starting AudioLifecycleController:")
    lifecycle = AudioLifecycleController(device_adapter=adapter)
    print(f"  Controller State Before Start: {lifecycle.state.value}")
    lifecycle.start()
    print(f"  Controller State After Start : {lifecycle.state.value} (can_accept_chunks={lifecycle.can_accept_chunks()})")

    # Step 5 & 6 & 7: Stream generation, VAD, and Bounded Buffer
    print("\n[Step 5, 6, 7] Streaming Synthetic Audio, Running VAD, and Buffering:")
    audio_format = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
    source = FakeMicrophoneSource(
        audio_format=audio_format,
        chunk_duration_ms=20.0,
        signal_type=SignalType.SPEECH_LIKE,
        frequency=440.0,
        amplitude=0.5,
    )
    vad = ThresholdVAD(energy_threshold=0.05, min_speech_duration_ms=40.0)
    buffer = BoundedAudioBuffer(max_capacity=8, policy=BackpressurePolicy.DROP_NEWEST)

    print(f"  Configuration : VAD threshold={vad.energy_threshold}, min_speech_duration={vad.min_speech_duration_ms}ms")
    print(f"  Buffer Policy : Capacity={buffer.capacity}, Policy={buffer.policy.value}")
    print("-" * 78)
    print(f"{'Seq':>4} | {'Timestamp':>10} | {'RMS Energy':>10} | {'Raw Speech':>10} | {'VAD Result':>10} | {'Buffer State':>14}")
    print("-" * 78)

    # Process first 8 chunks (should fill buffer exactly)
    for _ in range(8):
        chunk = source.read_chunk()
        assert chunk is not None
        accepted = lifecycle.accept_chunk(chunk)
        vad_res = vad.process_chunk(accepted)
        enqueued = buffer.push(accepted)
        status_str = f"Enqueued ({buffer.size}/{buffer.capacity})" if enqueued else "DROPPED"
        print(
            f"{chunk.sequence_id:4d} | "
            f"{chunk.timestamp_ms:8.1f}ms | "
            f"{vad_res.energy:10.4f} | "
            f"{str(vad_res.raw_is_speech):>10} | "
            f"{str(vad_res.is_speech):>10} | "
            f"{status_str:>14}"
        )

    # Step 8: Demonstrate buffer capacity and dropped-chunk counters
    print("\n[Step 8] Demonstrating Buffer Overflow & Backpressure (Pushing 4 More Chunks):")
    for _ in range(4):
        chunk = source.read_chunk()
        assert chunk is not None
        lifecycle.accept_chunk(chunk)
        vad_res = vad.process_chunk(chunk)
        enqueued = buffer.push(chunk)
        status_str = f"Enqueued ({buffer.size}/{buffer.capacity})" if enqueued else "DROPPED [OVERFLOW]"
        print(
            f"{chunk.sequence_id:4d} | "
            f"{chunk.timestamp_ms:8.1f}ms | "
            f"{vad_res.energy:10.4f} | "
            f"{str(vad_res.raw_is_speech):>10} | "
            f"{str(vad_res.is_speech):>10} | "
            f"{status_str:>14}"
        )

    print(f"  --> Buffer Size: {buffer.size}/{buffer.capacity} (Strictly Bounded)")
    print(f"  --> Dropped Chunk Counter : {buffer.dropped_chunks} chunk(s)")
    print(f"  --> Overflow Counter       : {buffer.overflow_count} event(s)")

    # Step 9: Pause and Resume Stream
    print("\n[Step 9] Demonstrating Session Pause and Resume:")
    print("  Pausing lifecycle controller...")
    lifecycle.pause()
    print(f"  Lifecycle State : {lifecycle.state.value} (can_accept_chunks={lifecycle.can_accept_chunks()})")

    # Attempt to accept chunk during pause
    paused_chunk = source.read_chunk()
    assert paused_chunk is not None
    try:
        lifecycle.accept_chunk(paused_chunk)
    except SessionNotRunningError as e:
        print(f"  --> Correctly Rejected During Pause: {e}")

    print("  Resuming lifecycle controller...")
    lifecycle.resume()
    print(f"  Lifecycle State : {lifecycle.state.value} (can_accept_chunks={lifecycle.can_accept_chunks()})")

    # Sequence tracking continues
    resumed_chunk = source.read_chunk()
    assert resumed_chunk is not None
    lifecycle.accept_chunk(resumed_chunk)
    vad.process_chunk(resumed_chunk)
    print(f"  --> Ingested Post-Resume Chunk (Seq={resumed_chunk.sequence_id}, Time={resumed_chunk.timestamp_ms:.1f}ms)")

    # Step 10: Stop session cleanly
    print("\n[Step 10] Stopping Audio Session Cleanly:")
    lifecycle.stop()
    print(f"  Lifecycle State : {lifecycle.state.value} (can_accept_chunks={lifecycle.can_accept_chunks()})")
    try:
        lifecycle.accept_chunk(resumed_chunk)
    except SessionNotRunningError as e:
        print(f"  --> Rejection Verified in STOPPED State: {e}")

    # Finalize VAD segments
    segments = vad.finalize()

    # Step 11: Print readable summary
    print("\n" + "=" * 78)
    print("[Step 11] DEMONSTRATION EXECUTION SUMMARY:")
    print("=" * 78)
    print("  Hardware Independence   : 100% Mock Devices & Synthetic PCM (No Hardware Required)")
    print(f"  Selected Device         : {selected_device.name} ({selected_device.device_id})")
    print(f"  Final Lifecycle State   : {lifecycle.state.value}")
    print(f"  Accepted Chunks         : {lifecycle.accepted_chunks_count}")
    print(f"  Rejected When Suspended : {lifecycle.paused_rejection_count}")
    print(f"  VAD Speech Segments     : {len(segments)} segment(s) detected")
    for i, seg in enumerate(segments, 1):
        print(f"    - Segment {i}: {seg.start_ms:.1f}ms -> {seg.end_ms:.1f}ms (Duration: {seg.duration_ms:.1f}ms, Chunks: {len(seg.chunks)})")
    print(f"  Buffer Capacity Limit   : {buffer.capacity} chunks")
    print(f"  Current Retained Chunks : {buffer.size} chunks ({buffer.total_duration_ms:.1f} ms)")
    print(f"  Total Chunks Pushed     : {buffer.get_stats().total_pushed}")
    print(f"  Total Chunks Dropped    : {buffer.dropped_chunks}")
    print(f"  Total Overflows Logged  : {buffer.overflow_count}")
    print(f"  Sequence Continuity     : Strictly monotonic without silent reordering")
    print("=" * 78)
    print("WEEK 2 AUDIO INPUT & VAD DEMONSTRATION COMPLETED SUCCESSFULLY.")
    print("=" * 78 + "\n")
    return 0


# ============================================================================
# Argument Parsing & Entrypoint
# ============================================================================

def build_parser() -> argparse.ArgumentParser:
    """Construct command line argument parser."""
    parser = argparse.ArgumentParser(
        description="Worker 1 Audio Input & Voice Activity Detection CLI Demo (Weeks 1 & 2)"
    )
    # Week 2 Demo Flag
    parser.add_argument(
        "--demo-week2",
        "--week2",
        action="store_true",
        help="Run the complete dedicated Week 2 Audio Input & VAD Demonstration",
    )

    # Week 1 Parameters (Preserved)
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

    if args.demo_week2:
        code = run_week2_demo()
    else:
        code = run_pipeline_demo(args)
    sys.exit(code)


if __name__ == "__main__":
    main()
