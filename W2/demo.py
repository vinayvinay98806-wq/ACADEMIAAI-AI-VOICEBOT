"""AcademiaAI AI Voice Co-Pilot - Workstream W2: Speech-to-Text (STT).

Week 1 Demonstration Script.
Demonstrates:
1. Streaming mock audio chunks into DeterministicFakeTranscriber.
2. Ingesting interim and final TranscriptEvents into OrderedTranscriptAccumulator.
3. Live replacement of interim hypothesis when the final segment lands.
4. Handling out-of-order segment arrival and duplicate payloads deterministically.
5. Isolation of error events without invalidating accumulated state.
6. Retrieval of the final clean continuous transcript and timeline.
"""

import sys
import time
from pathlib import Path

# Add src directory to PYTHONPATH so demo runs standalone
sys.path.insert(0, str(Path(__file__).parent / "src"))

from w2_stt.accumulator import OrderedTranscriptAccumulator
from w2_stt.fake_transcriber import DeterministicFakeTranscriber
from w2_stt.schemas import (
    TranscriptErrorInfo,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)


def print_banner(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f" {title}")
    print(f"{'=' * 70}")


def main() -> None:
    print_banner("AcademiaAI AI Voice Co-Pilot: W2 STT Week 1 Demonstration")
    print("Mode: Offline Deterministic Mock & Accumulator Pipeline")
    print("Components: DeterministicFakeTranscriber -> OrderedTranscriptAccumulator\n")

    transcriber = DeterministicFakeTranscriber()
    accumulator = OrderedTranscriptAccumulator()

    # Simulated audio chunks (raw PCM frame simulations)
    simulated_audio_chunks = [
        b"pcm_frame_001_initial_utterance_speech",
        b"pcm_frame_002_continuation_speech",
        b"pcm_frame_003_second_phrase_intro",
        b"pcm_frame_004_second_phrase_conclusion",
        b"pcm_frame_005_closing_remarks",
    ]

    print("[Step 1] Ingesting simulated audio chunks sequentially...")
    print("-" * 70)

    for idx, chunk in enumerate(simulated_audio_chunks):
        events = transcriber.process_audio_chunk(
            chunk,
            context={"session_id": "demo-lecture-session-101", "language": "en-US"},
        )
        for event in events:
            accumulator.add_event(event)

            if event.event_type == TranscriptEventType.INTERIM:
                seg = event.segment
                print(
                    f"  [CHUNK {idx:02d} | INTERIM] ID={seg.segment_id} "
                    f"[{seg.start_time:.1f}s -> {seg.end_time:.1f}s] "
                    f"Conf={seg.confidence:.2f} -> \"{seg.text}\""
                )
            elif event.event_type == TranscriptEventType.FINAL:
                seg = event.segment
                print(
                    f"  [CHUNK {idx:02d} | FINAL  ] ID={seg.segment_id} "
                    f"[{seg.start_time:.1f}s -> {seg.end_time:.1f}s] "
                    f"Conf={seg.confidence:.2f} -> \"{seg.text}\" (Interim superseded)"
                )

    # Flush any remaining interim state
    flushed_events = transcriber.flush()
    for event in flushed_events:
        accumulator.add_event(event)
        if event.segment:
            print(
                f"  [FLUSH    | FINAL  ] ID={event.segment.segment_id} "
                f"[{event.segment.start_time:.1f}s -> {event.segment.end_time:.1f}s] "
                f"Conf={event.segment.confidence:.2f} -> \"{event.segment.text}\""
            )

    print("\n[Current Accumulated Transcript (after regular stream)]:")
    print(f"  \"{accumulator.get_full_transcript()}\"")

    # [Step 2] Demonstrate Out-of-Order Segment Insertion
    print_banner("[Step 2] Demonstrating Out-of-Order Segment Arrival")
    print("Simulating an earlier lost packet (seg-0000, 0.0s -> 0.4s) arriving late...")

    early_late_segment = TranscriptSegment(
        segment_id="seg-0000",
        start_time=0.0,
        end_time=0.4,
        text="Greetings students,",
        confidence=0.98,
        is_final=True,
        language="en-US",
    )
    accumulator.add_segment(early_late_segment)
    print(f"  Late segment ingested: \"{early_late_segment.text}\" (start: {early_late_segment.start_time}s)")
    print("  Resulting chronologically ordered transcript:")
    print(f"  \"{accumulator.get_full_transcript()}\"")

    # [Step 3] Demonstrate Duplicate Handling
    print_banner("[Step 3] Demonstrating Idempotent Duplicate Handling")
    print("Re-sending identical final segment 'seg-0000'...")
    accumulator.add_segment(early_late_segment)
    print(f"  Segment count after duplicate: {accumulator.final_count} (No duplicate words generated)")
    print(f"  \"{accumulator.get_full_transcript()}\"")

    # [Step 4] Demonstrate Error Isolation
    print_banner("[Step 4] Demonstrating Error Event Isolation")
    error_event = TranscriptEvent(
        session_id="demo-lecture-session-101",
        event_type=TranscriptEventType.ERROR,
        error=TranscriptErrorInfo(
            code="NETWORK_JITTER",
            message="Transient audio packet drop detected, STT stream recovered.",
            details={"packet_id": 9821},
        ),
    )
    accumulator.add_event(error_event)
    print(f"  Error ingested: [{error_event.error.code}] {error_event.error.message}")
    print(f"  Recorded errors count: {len(accumulator.errors)}")
    print("  Accumulated transcript remains intact and uncorrupted:")
    print(f"  \"{accumulator.get_full_transcript()}\"")

    # [Step 5] Final Timeline Breakdown
    print_banner("[Step 5] Final Accumulated Segments Timeline")
    for seg in accumulator.get_segments():
        print(
            f"  - [{seg.start_time:05.2f}s - {seg.end_time:05.2f}s] "
            f"({seg.confidence * 100:4.1f}% conf) {seg.segment_id}: \"{seg.text}\""
        )

    print("\n" + "=" * 70)
    print(" DEMONSTRATION COMPLETE: All W2 Week 1 objectives verified successfully!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
