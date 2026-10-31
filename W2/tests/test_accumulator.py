"""Tests for OrderedTranscriptAccumulator."""

import unittest

from w2_stt.accumulator import OrderedTranscriptAccumulator
from w2_stt.schemas import TranscriptEvent, TranscriptEventType
from tests.fixtures.sample_events import (
    make_interim_segment,
    make_final_segment,
    make_error_event,
)


class TestOrderedTranscriptAccumulator(unittest.TestCase):
    """Test suite verifying ordered accumulation, interim replacement, and duplicate handling."""

    def setUp(self) -> None:
        self.accumulator = OrderedTranscriptAccumulator()

    def test_empty_accumulator_state(self) -> None:
        """Verify behavior of brand-new accumulator."""
        self.assertEqual(self.accumulator.final_count, 0)
        self.assertFalse(self.accumulator.has_pending_interim)
        self.assertEqual(self.accumulator.get_segments(), [])
        self.assertEqual(self.accumulator.get_full_transcript(), "")
        self.assertIsNone(self.accumulator.get_interim_segment())

    def test_in_order_final_segments(self) -> None:
        """Verify adding sequential final segments produces ordered transcript."""
        seg1 = make_final_segment(segment_id="seg-1", start_time=0.0, end_time=1.0, text="Hello")
        seg2 = make_final_segment(segment_id="seg-2", start_time=1.0, end_time=2.0, text="Academia")
        seg3 = make_final_segment(segment_id="seg-3", start_time=2.0, end_time=3.0, text="AI")

        self.accumulator.add_segment(seg1)
        self.accumulator.add_segment(seg2)
        self.accumulator.add_segment(seg3)

        self.assertEqual(self.accumulator.final_count, 3)
        self.assertEqual(self.accumulator.get_full_transcript(), "Hello Academia AI")

    def test_out_of_order_arrival_sorted_chronologically(self) -> None:
        """Verify out-of-order segment arrivals are placed into correct chronological sequence."""
        seg3 = make_final_segment(segment_id="seg-3", start_time=2.0, end_time=3.0, text="part three")
        seg1 = make_final_segment(segment_id="seg-1", start_time=0.0, end_time=1.0, text="part one")
        seg2 = make_final_segment(segment_id="seg-2", start_time=1.0, end_time=2.0, text="part two")

        # Ingest deliberately out of order (3, then 1, then 2)
        self.accumulator.add_segment(seg3)
        self.accumulator.add_segment(seg1)
        self.accumulator.add_segment(seg2)

        ordered = self.accumulator.get_segments()
        self.assertEqual([s.segment_id for s in ordered], ["seg-1", "seg-2", "seg-3"])
        self.assertEqual(self.accumulator.get_full_transcript(), "part one part two part three")

    def test_interim_replaced_by_newer_interim(self) -> None:
        """Verify that newer interim updates for the same segment replace earlier interims."""
        int1 = make_interim_segment(segment_id="seg-1", start_time=0.0, end_time=0.5, text="I think")
        int2 = make_interim_segment(segment_id="seg-1", start_time=0.0, end_time=0.8, text="I think therefore")

        self.accumulator.add_segment(int1)
        self.assertEqual(self.accumulator.get_full_transcript(include_interim=True), "I think")

        self.accumulator.add_segment(int2)
        self.assertEqual(self.accumulator.get_full_transcript(include_interim=True), "I think therefore")
        self.assertTrue(self.accumulator.has_pending_interim)
        self.assertEqual(self.accumulator.final_count, 0)

    def test_interim_replaced_by_final_segment(self) -> None:
        """Verify interim segment is cleanly replaced and purged when its final arrives."""
        interim = make_interim_segment(
            segment_id="seg-1",
            start_time=0.0,
            end_time=0.8,
            text="I think therefore",
        )
        final = make_final_segment(
            segment_id="seg-1",
            start_time=0.0,
            end_time=1.2,
            text="I think therefore I am.",
        )

        self.accumulator.add_segment(interim)
        self.assertTrue(self.accumulator.has_pending_interim)

        # Final segment arrives
        self.accumulator.add_segment(final)
        self.assertFalse(self.accumulator.has_pending_interim)
        self.assertEqual(self.accumulator.final_count, 1)

        # Neither include_interim True nor False should duplicate or retain interim
        self.assertEqual(self.accumulator.get_full_transcript(include_interim=False), "I think therefore I am.")
        self.assertEqual(self.accumulator.get_full_transcript(include_interim=True), "I think therefore I am.")
        self.assertIsNone(self.accumulator.get_interim_segment())

    def test_late_interim_arriving_after_final_is_ignored(self) -> None:
        """Verify stale interim arriving out of order after final has landed is discarded."""
        final = make_final_segment(segment_id="seg-1", start_time=0.0, end_time=1.0, text="Definitive text.")
        stale_interim = make_interim_segment(segment_id="seg-1", start_time=0.0, end_time=0.5, text="Stale...")

        self.accumulator.add_segment(final)
        self.accumulator.add_segment(stale_interim)  # Late arriving interim

        self.assertFalse(self.accumulator.has_pending_interim)
        self.assertEqual(self.accumulator.get_full_transcript(include_interim=True), "Definitive text.")

    def test_duplicate_final_segments_handled_idempotently(self) -> None:
        """Verify duplicate final events do not cause duplicate entries or duplicated text."""
        final = make_final_segment(segment_id="seg-dup", start_time=0.0, end_time=1.0, text="Single utterance.")

        # Ingest identical final segment three times
        self.accumulator.add_segment(final)
        self.accumulator.add_segment(final)
        self.accumulator.add_segment(final)

        self.assertEqual(self.accumulator.final_count, 1)
        self.assertEqual(self.accumulator.get_full_transcript(), "Single utterance.")

    def test_error_event_isolated_without_corrupting_segments(self) -> None:
        """Verify error events are captured into errors list without affecting accumulated segments."""
        seg = make_final_segment(segment_id="seg-ok", text="Good audio segment.")
        err_event = make_error_event(code="BUFFER_OVERFLOW", message="Audio frame dropped")

        self.accumulator.add_event(
            TranscriptEvent(
                event_type=TranscriptEventType.FINAL,
                segment=seg,
            )
        )
        self.accumulator.add_event(err_event)

        self.assertEqual(self.accumulator.final_count, 1)
        self.assertEqual(self.accumulator.get_full_transcript(), "Good audio segment.")
        self.assertEqual(len(self.accumulator.errors), 1)
        self.assertEqual(self.accumulator.errors[0].code, "BUFFER_OVERFLOW")

    def test_reset_clears_all_state(self) -> None:
        """Verify reset() empties all collections."""
        self.accumulator.add_segment(make_final_segment())
        self.accumulator.add_segment(make_interim_segment(segment_id="seg-int"))
        self.accumulator.add_event(make_error_event())

        self.accumulator.reset()
        self.assertEqual(self.accumulator.final_count, 0)
        self.assertFalse(self.accumulator.has_pending_interim)
        self.assertEqual(len(self.accumulator.errors), 0)
        self.assertEqual(self.accumulator.get_full_transcript(), "")

    def test_get_segment_by_id(self) -> None:
        """Verify looking up individual segments by id."""
        f_seg = make_final_segment(segment_id="target-final")
        i_seg = make_interim_segment(segment_id="target-interim")

        self.accumulator.add_segment(f_seg)
        self.accumulator.add_segment(i_seg)

        self.assertEqual(self.accumulator.get_segment_by_id("target-final").text, f_seg.text)
        self.assertEqual(self.accumulator.get_segment_by_id("target-interim").text, i_seg.text)
        self.assertIsNone(self.accumulator.get_segment_by_id("non-existent"))


if __name__ == "__main__":
    unittest.main()
