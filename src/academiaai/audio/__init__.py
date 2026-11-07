"""Worker 1 (W1) - Audio Input & Voice Activity Detection Module.

Scope:
- Week 1: Core audio schemas (AudioChunk, AudioFormat, AudioError hierarchy),
  deterministic chunking, and fake microphone source.
- Week 2: Audio device adapters, lifecycle controller, Voice Activity Detection (VAD),
  bounded audio buffer, and stream pipeline integration.
"""

# Week 1 Exports
from .schemas import (
    AudioChunk,
    AudioFormat,
    AudioError,
    AudioFormatError,
    AudioChunkError,
    EmptyChunkError,
    CorruptChunkError,
)
from .sources import (
    DeterministicChunker,
    FakeMicrophoneSource,
    SignalType,
)

# Week 2 Exports
from .devices import (
    AudioDevice,
    AudioDeviceAdapter,
    MockAudioDeviceAdapter,
    PermissionState,
    DeviceError,
    DeviceNotFoundError,
    DevicePermissionError,
    DeviceNotSelectedError,
)
from .lifecycle import (
    AudioLifecycleController,
    LifecycleState,
    AudioLifecycleError,
    InvalidStateTransitionError,
    SessionNotRunningError,
)
from .vad import (
    VADInterface,
    ThresholdVAD,
    VADResult,
    SpeechSegment,
    VADError,
    VADConfigurationError,
    calculate_chunk_rms,
)
from .buffer import (
    BoundedAudioBuffer,
    BackpressurePolicy,
    BufferStats,
    AudioBufferError,
    BufferCapacityError,
)
from .pipeline import (
    AudioPipeline,
    PipelineStepResult,
    PipelineSummary,
)

__all__ = [
    # Week 1
    "AudioChunk",
    "AudioFormat",
    "AudioError",
    "AudioFormatError",
    "AudioChunkError",
    "EmptyChunkError",
    "CorruptChunkError",
    "DeterministicChunker",
    "FakeMicrophoneSource",
    "SignalType",
    # Week 2 - Devices
    "AudioDevice",
    "AudioDeviceAdapter",
    "MockAudioDeviceAdapter",
    "PermissionState",
    "DeviceError",
    "DeviceNotFoundError",
    "DevicePermissionError",
    "DeviceNotSelectedError",
    # Week 2 - Lifecycle
    "AudioLifecycleController",
    "LifecycleState",
    "AudioLifecycleError",
    "InvalidStateTransitionError",
    "SessionNotRunningError",
    # Week 2 - VAD
    "VADInterface",
    "ThresholdVAD",
    "VADResult",
    "SpeechSegment",
    "VADError",
    "VADConfigurationError",
    "calculate_chunk_rms",
    # Week 2 - Buffer
    "BoundedAudioBuffer",
    "BackpressurePolicy",
    "BufferStats",
    "AudioBufferError",
    "BufferCapacityError",
    # Week 2 - Pipeline
    "AudioPipeline",
    "PipelineStepResult",
    "PipelineSummary",
]
