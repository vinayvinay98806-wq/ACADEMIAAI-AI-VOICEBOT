"""AcademiaAI AI Voice Co-Pilot - Workstream W2: Speech-to-Text (STT).

Week 1 Module:
- Schemas: TranscriptSegment, TranscriptEvent, TranscriptErrorInfo, TranscriptEventType
- Adapter: BaseTranscriptionAdapter
- Fake Transcriber: DeterministicFakeTranscriber
- Accumulator: OrderedTranscriptAccumulator

Week 2 Module Additions:
- Orchestration: STTOrchestrator, OrchestratorConfig
- Preprocessing: AudioPreprocessor, AudioPreprocessingConfig
- Reliability: RetryConfig, execute_with_retry
- Exceptions: STTError, STTConfigurationError, STTInputError, STTPreprocessingError,
  STTProviderError, STTTransientError, STTTimeoutError, STTPermanentError,
  normalize_provider_error, to_transcript_error_info
"""

from w2_stt.schemas import (
    TranscriptSegment,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptErrorInfo,
)
from w2_stt.adapter import BaseTranscriptionAdapter
from w2_stt.fake_transcriber import DeterministicFakeTranscriber
from w2_stt.accumulator import OrderedTranscriptAccumulator
from w2_stt.preprocessing import (
    AudioPreprocessor,
    AudioPreprocessingConfig,
)
from w2_stt.reliability import (
    RetryConfig,
    execute_with_retry,
)
from w2_stt.exceptions import (
    STTError,
    STTConfigurationError,
    STTInputError,
    STTPreprocessingError,
    STTProviderError,
    STTTransientError,
    STTTimeoutError,
    STTPermanentError,
    normalize_provider_error,
    to_transcript_error_info,
)
from w2_stt.orchestrator import (
    STTOrchestrator,
    OrchestratorConfig,
)

__all__ = [
    # Schemas
    "TranscriptSegment",
    "TranscriptEvent",
    "TranscriptEventType",
    "TranscriptErrorInfo",
    # Adapter
    "BaseTranscriptionAdapter",
    # Mock Provider
    "DeterministicFakeTranscriber",
    # Accumulator
    "OrderedTranscriptAccumulator",
    # Preprocessing
    "AudioPreprocessor",
    "AudioPreprocessingConfig",
    # Reliability
    "RetryConfig",
    "execute_with_retry",
    # Exceptions
    "STTError",
    "STTConfigurationError",
    "STTInputError",
    "STTPreprocessingError",
    "STTProviderError",
    "STTTransientError",
    "STTTimeoutError",
    "STTPermanentError",
    "normalize_provider_error",
    "to_transcript_error_info",
    # Orchestrator
    "STTOrchestrator",
    "OrchestratorConfig",
]
