"""End-to-end audio streaming pipeline integrating Worker 1 components.

Wires:
Mock device adapter
  -> Permission check
  -> Lifecycle controller
  -> FakeMicrophoneSource
  -> Voice Activity Detector (VAD)
  -> Bounded FIFO audio buffer
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from .buffer import BackpressurePolicy, BoundedAudioBuffer, BufferStats
from .devices import AudioDevice, MockAudioDeviceAdapter, PermissionState
from .lifecycle import AudioLifecycleController, LifecycleState
from .schemas import AudioChunk, AudioFormat
from .sources import FakeMicrophoneSource, SignalType
from .vad import SpeechSegment, ThresholdVAD, VADResult


@dataclass(frozen=True)
class PipelineStepResult:
    """Result of processing a single chunk through the pipeline."""
    chunk: AudioChunk
    vad_result: VADResult
    enqueued: bool


@dataclass(frozen=True)
class PipelineSummary:
    """Summary of pipeline execution."""
    lifecycle_state: LifecycleState
    total_chunks_processed: int
    speech_chunks_count: int
    buffer_stats: BufferStats
    speech_segments: List[SpeechSegment]


class AudioPipeline:
    """Coordinated audio pipeline integrating adapter, lifecycle, generator, VAD, and buffer."""

    def __init__(
        self,
        device_adapter: MockAudioDeviceAdapter,
        lifecycle: AudioLifecycleController,
        source: FakeMicrophoneSource,
        vad: ThresholdVAD,
        buffer: BoundedAudioBuffer,
    ) -> None:
        """Initialize AudioPipeline.

        Args:
            device_adapter: MockAudioDeviceAdapter managing devices and permissions.
            lifecycle: AudioLifecycleController enforcing state transitions.
            source: FakeMicrophoneSource providing synthetic audio chunks.
            vad: ThresholdVAD analyzing speech activity.
            buffer: BoundedAudioBuffer storing processed chunks with backpressure.
        """
        self.adapter = device_adapter
        self.lifecycle = lifecycle
        self.source = source
        self.vad = vad
        self.buffer = buffer

        # Wire dependency injection
        self.lifecycle.device_adapter = self.adapter

        self._step_results: List[PipelineStepResult] = []

    @classmethod
    def create_default(
        cls,
        signal_type: SignalType = SignalType.SPEECH_LIKE,
        chunk_duration_ms: float = 20.0,
        sample_rate: int = 16000,
        buffer_capacity: int = 20,
        energy_threshold: float = 0.05,
        min_speech_duration_ms: float = 40.0,
        backpressure_policy: BackpressurePolicy = BackpressurePolicy.DROP_NEWEST,
    ) -> AudioPipeline:
        """Convenience factory to instantiate a complete deterministic pipeline."""
        audio_format = AudioFormat(sample_rate=sample_rate, channels=1, sample_width=2)
        adapter = MockAudioDeviceAdapter()
        lifecycle = AudioLifecycleController(device_adapter=adapter)
        source = FakeMicrophoneSource(
            audio_format=audio_format,
            chunk_duration_ms=chunk_duration_ms,
            signal_type=signal_type,
            amplitude=0.5,
        )
        vad = ThresholdVAD(
            energy_threshold=energy_threshold,
            min_speech_duration_ms=min_speech_duration_ms,
        )
        buffer = BoundedAudioBuffer(
            max_capacity=buffer_capacity,
            policy=backpressure_policy,
        )
        return cls(
            device_adapter=adapter,
            lifecycle=lifecycle,
            source=source,
            vad=vad,
            buffer=buffer,
        )

    def start(self) -> None:
        """Start the audio session via lifecycle controller."""
        self.lifecycle.start()

    def pause(self) -> None:
        """Pause the audio session via lifecycle controller."""
        self.lifecycle.pause()

    def resume(self) -> None:
        """Resume the audio session via lifecycle controller."""
        self.lifecycle.resume()

    def stop(self) -> None:
        """Stop the audio session via lifecycle controller."""
        self.lifecycle.stop()

    def step(self) -> Optional[PipelineStepResult]:
        """Execute one complete processing step.

        1. Read next AudioChunk from FakeMicrophoneSource.
        2. Accept chunk through lifecycle controller (verifies RUNNING state).
        3. Pass chunk to VAD for speech classification.
        4. Push chunk into bounded buffer.

        Returns:
            PipelineStepResult, or None if the source stream has ended.

        Raises:
            SessionNotRunningError: If called while paused, stopped, or idle.
        """
        chunk = self.source.read_chunk()
        if chunk is None:
            return None

        # Lifecycle gate: ensures only running sessions accept chunks
        accepted_chunk = self.lifecycle.accept_chunk(chunk)

        # Voice Activity Detection
        vad_result = self.vad.process_chunk(accepted_chunk)

        # Bounded Buffer ingestion
        enqueued = self.buffer.push(accepted_chunk)

        result = PipelineStepResult(
            chunk=accepted_chunk,
            vad_result=vad_result,
            enqueued=enqueued,
        )
        self._step_results.append(result)
        return result

    def run(self, max_chunks: Optional[int] = None) -> List[PipelineStepResult]:
        """Run the pipeline for a specified number of chunks or until source ends."""
        results: List[PipelineStepResult] = []
        count = 0
        while max_chunks is None or count < max_chunks:
            res = self.step()
            if res is None:
                break
            results.append(res)
            count += 1
        return results

    def finalize(self) -> PipelineSummary:
        """Finalize VAD and return an execution summary."""
        segments = self.vad.finalize()
        speech_chunks = sum(1 for r in self._step_results if r.vad_result.is_speech)
        return PipelineSummary(
            lifecycle_state=self.lifecycle.state,
            total_chunks_processed=len(self._step_results),
            speech_chunks_count=speech_chunks,
            buffer_stats=self.buffer.get_stats(),
            speech_segments=segments,
        )
