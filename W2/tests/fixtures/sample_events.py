"""Controlled sample events and segments for deterministic test cases."""

from w2_stt.schemas import (
    TranscriptErrorInfo,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)


def make_interim_segment(
    segment_id: str = "seg-001",
    start_time: float = 0.0,
    end_time: float = 0.5,
    text: str = "Hello",
    confidence: float = 0.85,
    language: str = "en-US",
) -> TranscriptSegment:
    """Helper to build a valid interim TranscriptSegment."""
    return TranscriptSegment(
        segment_id=segment_id,
        start_time=start_time,
        end_time=end_time,
        text=text,
        confidence=confidence,
        is_final=False,
        language=language,
    )


def make_final_segment(
    segment_id: str = "seg-001",
    start_time: float = 0.0,
    end_time: float = 1.0,
    text: str = "Hello world",
    confidence: float = 0.95,
    language: str = "en-US",
) -> TranscriptSegment:
    """Helper to build a valid final TranscriptSegment."""
    return TranscriptSegment(
        segment_id=segment_id,
        start_time=start_time,
        end_time=end_time,
        text=text,
        confidence=confidence,
        is_final=True,
        language=language,
    )


def make_error_event(
    code: str = "AUDIO_CORRUPTED",
    message: str = "Packet CRC mismatch",
    session_id: str = "test-session",
) -> TranscriptEvent:
    """Helper to build a valid error TranscriptEvent."""
    return TranscriptEvent(
        session_id=session_id,
        event_type=TranscriptEventType.ERROR,
        error=TranscriptErrorInfo(code=code, message=message),
    )
