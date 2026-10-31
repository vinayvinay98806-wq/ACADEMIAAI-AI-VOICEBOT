"""Worker 1 (W1) - Audio Input & Voice Activity Detection Module.

Week 1 Scope:
- Core audio schemas (AudioChunk, AudioFormat, AudioError hierarchy)
- Deterministic chunker and fake microphone source
- Validation for sample rates, channels, and chunk integrity
"""

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

__all__ = [
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
]
