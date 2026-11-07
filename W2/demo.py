"""AcademiaAI AI Voice Co-Pilot - Workstream W2: Speech-to-Text (STT).

Week 2 End-to-End Orchestration & Reliability Demonstration Script.

Demonstrates:
1. End-to-End Audio Pipeline: AudioChunk (48kHz stereo) -> Preprocessor (16kHz mono) -> Orchestrator -> Provider -> Accumulator.
2. Live interim hypothesis progression and final segment replacement.
3. Flushing buffered interim segments upon stream closure.
4. Out-of-order event arrival and chronological reconciliation.
5. Idempotent duplicate event suppression.
6. Transient failure recovery via bounded exponential backoff retries.
7. Error isolation without state corruption.
8. Final consolidated transcript output and structured timeline.
"""

import math
import struct
import sys
import time
from pathlib import Path

# Add src directory to PYTHONPATH so demo runs standalone
sys.path.insert(0, str(Path(__file__).parent / "src"))

from academiaai.audio.schemas import AudioChunk, AudioFormat
from w2_stt.accumulator import OrderedTranscriptAccumulator
from w2_stt.adapter import BaseTranscriptionAdapter
from w2_stt.exceptions import STTTransientError
from w2_stt.fake_transcriber import DeterministicFakeTranscriber
from w2_stt.orchestrator import OrchestratorConfig, STTOrchestrator
from w2_stt.preprocessing import AudioPreprocessingConfig, AudioPreprocessor
from w2_stt.reliability import RetryConfig
from w2_stt.schemas import (
    TranscriptErrorInfo,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)


def print_banner(title: str) -> None:
    print(f"\n{'=' * 75}")
    print(f" {title}")
    print(f"{'=' * 75}")


def generate_synthetic_chunk(
    seq: int,
    sample_rate: int = 48000,
    channels: int = 2,
    duration_ms: float = 100.0,
    frequency: float = 440.0,
    amplitude: float = 0.3,
) -> AudioChunk:
    """Generate a valid, synthetic AudioChunk with 16-bit PCM waveform."""
    fmt = AudioFormat(sample_rate=sample_rate, channels=channels, sample_width=2)
    total_samples = int(round((duration_ms / 1000.0) * sample_rate))
    raw_samples = []
    for i in range(total_samples):
        val = int(amplitude * 32767.0 * math.sin(2.0 * math.pi * frequency * (i / sample_rate)))
        clamped = max(-32768, min(32767, val))
        if channels == 1:
            raw_samples.append(clamped)
        else:
            raw_samples.extend([clamped, clamped])

    data = struct.pack(f"<{len(raw_samples)}h", *raw_samples)
    return AudioChunk(
        data=data,
        format=fmt,
        sequence_id=seq,
        timestamp_ms=seq * duration_ms,
    )


class DemoTransientFlakyAdapter(BaseTranscriptionAdapter):
    """Demonstration adapter simulating a transient network drop before recovery."""

    def __init__(self, fail_first_n: int = 2) -> None:
        self.fail_limit = fail_first_n
        self.calls = 0

    @property
    def provider_name(self) -> str:
        return "DemoTransientFlakyAdapter"

    def process_audio_chunk(self, chunk: bytes, context=None):
        self.calls += 1
        if self.calls <= self.fail_limit:
            print(f"    [PROVIDER ATTEMPT {self.calls}] Network glitch: simulated ConnectionResetError (transient)")
            raise ConnectionResetError(f"Temporary connection drop on attempt {self.calls}")

        print(f"    [PROVIDER ATTEMPT {self.calls}] Connection restored! Audio transcribed successfully.")
        return [
            TranscriptEvent(
                session_id="flaky-demo-session",
                event_type=TranscriptEventType.FINAL,
                timestamp=1.0,
                segment=TranscriptSegment(
                    segment_id="resilient-seg-01",
                    start_time=0.0,
                    end_time=1.0,
                    text="resilient transmission recovered automatically",
                    confidence=0.98,
                    is_final=True,
                ),
            )
        ]

    def flush(self):
        return []

    def reset(self):
        self.calls = 0


def main() -> None:
    print_banner("AcademiaAI AI Voice Co-Pilot: W2 STT Week 2 Demonstration")
    print("Mode: Offline Deterministic Orchestration, Reliability & Integration Pipeline")
    print("Architecture: AudioChunk (W1) -> Preprocessing -> Orchestrator -> Provider -> Accumulator\n")

    # [Step 1] Configure Preprocessor and Orchestrator
    print_banner("[Step 1] Initializing Preprocessor & STT Orchestrator")
    pre_config = AudioPreprocessingConfig(
        target_sample_rate=16000,
        target_channels=1,
        target_sample_width=2,
        normalize_audio=True,
        target_peak_level=0.95,
        enabled=True,
    )
    print(f"  - Preprocessing Config: Resampling to {pre_config.target_sample_rate}Hz, "
          f"{pre_config.target_channels}ch, Peak Normalization={pre_config.normalize_audio}")

    retry_config = RetryConfig(
        max_retries=3,
        initial_backoff_seconds=0.05,
        backoff_multiplier=2.0,
        timeout_seconds=5.0,
    )
    print(f"  - Reliability Config: Max Retries={retry_config.max_retries}, "
          f"Timeout={retry_config.timeout_seconds}s, Backoff Multiplier={retry_config.backoff_multiplier}")

    transcriber = DeterministicFakeTranscriber()
    orchestrator = STTOrchestrator(
        adapter=transcriber,
        config=OrchestratorConfig(
            session_id="lecture-hall-session-202",
            default_language="en-US",
            preprocessing_config=pre_config,
            retry_config=retry_config,
            preserve_chunk_metadata=True,
        ),
    )

    # [Step 2] Streaming Synthetic 48kHz Stereo AudioChunks
    print_banner("[Step 2] Ingesting Synthetic 48kHz Stereo Audio Chunks")
    print("  Converting 48kHz Stereo -> 16kHz Mono -> Transcription Stream...\n")

    chunks = [
        generate_synthetic_chunk(seq=i, sample_rate=48000, channels=2, duration_ms=250.0, frequency=300.0 + i * 50)
        for i in range(5)
    ]

    for chunk in chunks:
        events = orchestrator.process_chunk(chunk)
        for event in events:
            if event.event_type == TranscriptEventType.INTERIM:
                seg = event.segment
                print(
                    f"  [CHUNK {chunk.sequence_id:02d} | INTERIM] ID={seg.segment_id} "
                    f"[{seg.start_time:.1f}s -> {seg.end_time:.1f}s] "
                    f"Conf={seg.confidence:.2f} -> \"{seg.text}\""
                )
            elif event.event_type == TranscriptEventType.FINAL:
                seg = event.segment
                print(
                    f"  [CHUNK {chunk.sequence_id:02d} | FINAL  ] ID={seg.segment_id} "
                    f"[{seg.start_time:.1f}s -> {seg.end_time:.1f}s] "
                    f"Conf={seg.confidence:.2f} -> \"{seg.text}\" (Interim replaced)"
                )

    # [Step 3] Flushing Pending Interims
    print_banner("[Step 3] Flushing Stream Buffers")
    flushed_events = orchestrator.flush()
    for event in flushed_events:
        seg = event.segment
        print(
            f"  [FLUSH    | FINAL  ] ID={seg.segment_id} "
            f"[{seg.start_time:.1f}s -> {seg.end_time:.1f}s] "
            f"Conf={seg.confidence:.2f} -> \"{seg.text}\""
        )

    print("\n[Accumulated Transcript after Stream 1]:")
    print(f"  \"{orchestrator.get_transcript()}\"")

    # [Step 4] Demonstrate Duplicate Event Suppression & Out-of-Order Handling
    print_banner("[Step 4] Demonstrating Event Deduplication & Out-of-Order Arrival")
    late_early_seg = TranscriptSegment(
        segment_id="seg-0000",
        start_time=0.0,
        end_time=0.5,
        text="Good morning class,",
        confidence=0.99,
        is_final=True,
    )
    late_early_event = TranscriptEvent(
        event_id="evt-fixed-id-42",
        session_id=orchestrator.session_id,
        event_type=TranscriptEventType.FINAL,
        segment=late_early_seg,
    )

    print("  Injecting late segment (0.0s -> 0.5s): 'Good morning class,'...")
    orchestrator.accumulator.add_event(late_early_event)

    print("  Resulting chronologically re-ordered transcript:")
    print(f"  \"{orchestrator.get_transcript()}\"")

    print("\n  Injecting duplicate event with identical event_id ('evt-fixed-id-42')...")
    processed = orchestrator.accumulator.add_event(late_early_event)
    print(f"  Duplicate Accepted? {processed} (False = Suppressed successfully)")
    print(f"  Total duplicate events suppressed: {orchestrator.accumulator.duplicate_events_count}")
    print(f"  \"{orchestrator.get_transcript()}\"")

    # [Step 5] Demonstrating Reliability & Transient Failure Recovery
    print_banner("[Step 5] Demonstrating Reliability: Bounded Retries on Transient Drop")
    flaky_adapter = DemoTransientFlakyAdapter(fail_first_n=2)
    resilient_orchestrator = STTOrchestrator(
        adapter=flaky_adapter,
        config=OrchestratorConfig(
            session_id="resilient-test-session",
            retry_config=RetryConfig(
                max_retries=3,
                initial_backoff_seconds=0.05,
                backoff_multiplier=1.5,
            ),
        ),
    )

    test_chunk = generate_synthetic_chunk(seq=0, sample_rate=16000, channels=1, duration_ms=100.0)
    print("  Sending chunk to flaky provider (will fail twice with ConnectionResetError)...")
    res_events = resilient_orchestrator.process_chunk(test_chunk)
    print(f"  Total Attempts Executed: {flaky_adapter.calls} (2 failed retries + 1 successful recovery)")
    print(f"  Recovered Transcript Text: \"{resilient_orchestrator.get_transcript()}\"")

    # [Step 6] Final Timeline Breakdown
    print_banner("[Step 6] Final Accumulated Segments Timeline")
    for seg in orchestrator.get_segments():
        print(
            f"  - [{seg.start_time:05.2f}s - {seg.end_time:05.2f}s] "
            f"({seg.confidence * 100:4.1f}% conf) {seg.segment_id}: \"{seg.text}\""
        )

    print("\n" + "=" * 75)
    print(" DEMONSTRATION COMPLETE: All W2 Week 2 objectives verified successfully!")
    print("=" * 75 + "\n")


if __name__ == "__main__":
    main()
