"""Provider-neutral transcription adapter interface.

This module defines the abstract contract `BaseTranscriptionAdapter`. Any transcription
engine (deterministic mock, local offline engine, or future external API) must conform
to this contract to ensure the AcademiaAI pipeline remains decoupled from vendor lock-in.
"""

from __future__ import annotations

import abc
from typing import Any, Dict, List, Optional

from w2_stt.schemas import TranscriptEvent


class BaseTranscriptionAdapter(abc.ABC):
    """Abstract base class for provider-neutral Speech-to-Text adapters.

    Subclasses must implement:
    - `provider_name`: Name/identifier of the underlying transcription provider.
    - `process_audio_chunk`: Synchronously or asynchronously convert audio chunks
      into zero or more `TranscriptEvent` instances.
    - `flush`: Emits any remaining buffered interim states as final results.
    - `reset`: Resets internal session state for a fresh transcription cycle.
    """

    @property
    @abc.abstractmethod
    def provider_name(self) -> str:
        """The human-readable identifier for this transcription provider."""
        raise NotImplementedError

    @abc.abstractmethod
    def process_audio_chunk(
        self,
        chunk: bytes,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[TranscriptEvent]:
        """Process a single chunk of audio data and emit corresponding transcript events.

        Args:
            chunk: Raw bytes representing audio samples (e.g., PCM 16-bit 16kHz).
            context: Optional dictionary containing metadata such as 'session_id',
                'language', 'timestamp_offset', or 'sequence_number'.

        Returns:
            A list of TranscriptEvent objects (can be empty, interim, final, or error).
        """
        raise NotImplementedError

    @abc.abstractmethod
    def flush(self) -> List[TranscriptEvent]:
        """Signal end of stream; flush internal buffers and finalize any pending interim segments.

        Returns:
            A list of final TranscriptEvent objects, if any were pending in buffers.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def reset(self) -> None:
        """Clear all internal buffers and state, preparing the adapter for a new stream."""
        raise NotImplementedError

    def close(self) -> None:
        """Optional hook to release any held resources, connections, or thread pools."""
        self.reset()
