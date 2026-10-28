"""Tests for TranscriptSegment, TranscriptEvent, and TranscriptErrorInfo schemas."""

import unittest
from pydantic import ValidationError

from w2_stt.schemas import (
    TranscriptErrorInfo,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)
from tests.fixtures.sample_events import (
    make_interim_segment,
    make_final_segment,
    make_error_event,
)


class TestTranscriptSchemas(unittest.TestCase):
    """Validation test suite for data contracts."""

    # -------------------------------------------------------------------------
    # TranscriptSegment Validations
    # -------------------------------------------------------------------------

    def test_valid_interim_segment(self) -> None:
        """Verify that a well-formed interim segment initializes cleanly."""
        seg = make_interim_segment()
        self.assertEqual(seg.segment_id, "seg-001")
        self.assertEqual(seg.start_time, 0.0)
        self.assertEqual(seg.end_time, 0.5)
        self.assertEqual(seg.text, "Hello")
        self.assertEqual(seg.confidence, 0.85)
        self.assertFalse(seg.is_final)
        self.assertEqual(seg.language, "en-US")

    def test_valid_final_segment(self) -> None:
        """Verify that a well-formed final segment initializes cleanly."""
        seg = make_final_segment()
        self.assertTrue(seg.is_final)
        self.assertEqual(seg.text, "Hello world")

    def test_segment_end_time_before_start_time_raises(self) -> None:
        """Verify that end_time < start_time is rejected."""
        with self.assertRaises(ValidationError) as ctx:
            TranscriptSegment(
                segment_id="seg-invalid-time",
                start_time=2.5,
                end_time=1.0,  # Invalid: precedes start_time
                text="Invalid timing",
                confidence=0.9,
                is_final=True,
            )
        self.assertIn("cannot precede start_time", str(ctx.exception))

    def test_segment_equal_start_and_end_time_allowed(self) -> None:
        """Verify instantaneous / zero-length segment (start_time == end_time) is permitted."""
        seg = TranscriptSegment(
            segment_id="seg-zero-duration",
            start_time=1.0,
            end_time=1.0,
            text="quick",
            confidence=0.5,
            is_final=False,
        )
        self.assertEqual(seg.start_time, seg.end_time)

    def test_segment_negative_timestamp_raises(self) -> None:
        """Verify negative timestamps are rejected by schema constraints."""
        with self.assertRaises(ValidationError):
            TranscriptSegment(
                segment_id="seg-neg-time",
                start_time=-0.1,
                end_time=1.0,
                text="Negative start",
                confidence=0.9,
            )

        with self.assertRaises(ValidationError):
            TranscriptSegment(
                segment_id="seg-neg-time2",
                start_time=0.0,
                end_time=-0.5,
                text="Negative end",
                confidence=0.9,
            )

    def test_segment_confidence_bounds(self) -> None:
        """Verify confidence is strictly constrained between 0.0 and 1.0."""
        # Boundary valid values
        seg_min = TranscriptSegment(
            segment_id="seg-c0",
            start_time=0.0,
            end_time=1.0,
            text="low confidence",
            confidence=0.0,
        )
        self.assertEqual(seg_min.confidence, 0.0)

        seg_max = TranscriptSegment(
            segment_id="seg-c1",
            start_time=0.0,
            end_time=1.0,
            text="high confidence",
            confidence=1.0,
        )
        self.assertEqual(seg_max.confidence, 1.0)

        # Invalid bounds
        with self.assertRaises(ValidationError):
            TranscriptSegment(
                segment_id="seg-c-under",
                start_time=0.0,
                end_time=1.0,
                text="underflow",
                confidence=-0.01,
            )

        with self.assertRaises(ValidationError):
            TranscriptSegment(
                segment_id="seg-c-over",
                start_time=0.0,
                end_time=1.0,
                text="overflow",
                confidence=1.05,
            )

    def test_segment_final_empty_text_rejected(self) -> None:
        """Verify final segments must contain non-empty text."""
        with self.assertRaises(ValidationError) as ctx:
            TranscriptSegment(
                segment_id="seg-empty-final",
                start_time=0.0,
                end_time=1.0,
                text="   ",
                confidence=0.9,
                is_final=True,
            )
        self.assertIn("must contain non-empty text", str(ctx.exception))

    def test_segment_blank_identifier_rejected(self) -> None:
        """Verify blank segment_id is rejected."""
        with self.assertRaises(ValidationError):
            TranscriptSegment(
                segment_id="   ",
                start_time=0.0,
                end_time=1.0,
                text="valid text",
                confidence=0.9,
            )

    # -------------------------------------------------------------------------
    # TranscriptErrorInfo Validations
    # -------------------------------------------------------------------------

    def test_valid_error_info(self) -> None:
        """Verify valid error info creation."""
        err = TranscriptErrorInfo(
            code="NETWORK_TIMEOUT",
            message="Connection closed unexpectedly",
            details={"retry_count": 3},
        )
        self.assertEqual(err.code, "NETWORK_TIMEOUT")
        self.assertEqual(err.details["retry_count"], 3)

    def test_error_info_empty_fields_rejected(self) -> None:
        """Verify whitespace or empty strings in error info are rejected."""
        with self.assertRaises(ValidationError):
            TranscriptErrorInfo(code="", message="Valid message")

        with self.assertRaises(ValidationError):
            TranscriptErrorInfo(code="VALID_CODE", message="   ")

    # -------------------------------------------------------------------------
    # TranscriptEvent Validations
    # -------------------------------------------------------------------------

    def test_valid_interim_event(self) -> None:
        """Verify valid interim event."""
        seg = make_interim_segment()
        evt = TranscriptEvent(
            session_id="session-123",
            event_type=TranscriptEventType.INTERIM,
            segment=seg,
        )
        self.assertEqual(evt.event_type, TranscriptEventType.INTERIM)
        self.assertEqual(evt.segment.segment_id, seg.segment_id)
        self.assertIsNotNone(evt.event_id)

    def test_valid_final_event(self) -> None:
        """Verify valid final event."""
        seg = make_final_segment()
        evt = TranscriptEvent(
            session_id="session-123",
            event_type=TranscriptEventType.FINAL,
            segment=seg,
        )
        self.assertEqual(evt.event_type, TranscriptEventType.FINAL)
        self.assertTrue(evt.segment.is_final)

    def test_interim_event_with_final_segment_rejected(self) -> None:
        """Verify INTERIM event rejects segment with is_final=True."""
        final_seg = make_final_segment()
        with self.assertRaises(ValidationError) as ctx:
            TranscriptEvent(
                event_type=TranscriptEventType.INTERIM,
                segment=final_seg,
            )
        self.assertIn("cannot have segment.is_final=True", str(ctx.exception))

    def test_final_event_with_interim_segment_rejected(self) -> None:
        """Verify FINAL event rejects segment with is_final=False."""
        interim_seg = make_interim_segment()
        with self.assertRaises(ValidationError) as ctx:
            TranscriptEvent(
                event_type=TranscriptEventType.FINAL,
                segment=interim_seg,
            )
        self.assertIn("must have segment.is_final=True", str(ctx.exception))

    def test_error_event_without_error_payload_rejected(self) -> None:
        """Verify ERROR event without error details is rejected."""
        with self.assertRaises(ValidationError) as ctx:
            TranscriptEvent(
                event_type=TranscriptEventType.ERROR,
                error=None,
            )
        self.assertIn("must include 'error' information", str(ctx.exception))

    def test_error_event_with_segment_rejected(self) -> None:
        """Verify ERROR event cannot carry segment payload."""
        with self.assertRaises(ValidationError) as ctx:
            TranscriptEvent(
                event_type=TranscriptEventType.ERROR,
                error=TranscriptErrorInfo(code="ERR", message="Something broke"),
                segment=make_final_segment(),
            )
        self.assertIn("must not include a segment payload", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
