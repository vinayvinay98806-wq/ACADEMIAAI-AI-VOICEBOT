"""AcademiaAI AI Voice Co-Pilot - Workstream W2: Speech-to-Text (STT).

Week 1 Module:
- Schemas: TranscriptSegment, TranscriptEvent, TranscriptErrorInfo, TranscriptStatus
- Adapter: BaseTranscriptionAdapter
- Fake Transcriber: DeterministicFakeTranscriber
- Accumulator: OrderedTranscriptAccumulator
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

__all__ = [
    "TranscriptSegment",
    "TranscriptEvent",
    "TranscriptEventType",
    "TranscriptErrorInfo",
    "BaseTranscriptionAdapter",
    "DeterministicFakeTranscriber",
    "OrderedTranscriptAccumulator",
]
