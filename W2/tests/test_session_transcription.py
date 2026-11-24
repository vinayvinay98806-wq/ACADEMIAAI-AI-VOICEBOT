"""Week 3 Stage 1 session-aware transcription tests."""

import unittest
from typing import Any, Dict, List, Optional

from academiaai.audio.schemas import AudioChunk, AudioFormat
from w2_stt.adapter import BaseTranscriptionAdapter
from w2_stt.exceptions import STTConfigurationError
from w2_stt.fake_transcriber import DeterministicFakeTranscriber
from w2_stt.schemas import TranscriptEvent, TranscriptEventType, TranscriptSegment
from w2_stt.session_transcription import (
    ConfidencePolicy,
    SessionAwareTranscriptionManager,
    TranscriptUpdateType,
)


class ScriptedAdapter(BaseTranscriptionAdapter):
    def __init__(self, batches: List[List[Any]]) -> None:
        self.batches = list(batches)

    @property
    def provider_name(self) -> str:
        return "ScriptedAdapter"

    def process_audio_chunk(
        self,
        chunk: bytes,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Any]:
        return self.batches.pop(0) if self.batches else []

    def flush(self) -> List[TranscriptEvent]:
        return []

    def reset(self) -> None:
        self.batches.clear()


def transcript_event(
    event_id: str,
    segment_id: str,
    text: str,
    *,
    final: bool = False,
    confidence: Optional[float] = 0.9,
    start_time: float = 0.0,
    timestamp: float = 1.0,
) -> TranscriptEvent:
    confidence_fields: Dict[str, Optional[float]] = {}
    if confidence is not None:
        confidence_fields["confidence"] = confidence
    segment = TranscriptSegment(
        segment_id=segment_id,
        start_time=start_time,
        end_time=start_time + 0.5,
        text=text,
        is_final=final,
        **confidence_fields,
    )
    return TranscriptEvent(
        event_id=event_id,
        event_type=TranscriptEventType.FINAL if final else TranscriptEventType.INTERIM,
        timestamp=timestamp,
        segment=segment,
    )


def manager_with_batches(
    *batches: List[Any],
    confidence_threshold: float = 0.8,
) -> SessionAwareTranscriptionManager:
    adapter = ScriptedAdapter(list(batches))
    return SessionAwareTranscriptionManager(
        adapter_factory=lambda: adapter,
        confidence_threshold=confidence_threshold,
    )


def pcm_chunk(sequence_id: int) -> AudioChunk:
    return AudioChunk(
        data=b"\x00\x00",
        format=AudioFormat(sample_rate=16000, channels=1, sample_width=2),
        sequence_id=sequence_id,
        timestamp_ms=float(sequence_id),
    )


class TestSessionAwareTranscription(unittest.TestCase):
    def test_session_id_and_sequence_propagate(self) -> None:
        manager = manager_with_batches([transcript_event("evt-1", "seg-1", "hello")])
        manager.create_session("session-1", "corr-1")

        updates = manager.process_chunk("session-1", pcm_chunk(7))

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].session_id, "session-1")
        self.assertEqual(updates[0].correlation_id, "corr-1")
        self.assertEqual(updates[0].segment_id, "seg-1")
        self.assertEqual(updates[0].sequence_id, 7)
        self.assertEqual(updates[0].text, "hello")
        self.assertEqual(updates[0].event_type, TranscriptUpdateType.REVISION)

    def test_two_sessions_have_independent_provider_and_transcript_state(self) -> None:
        manager = SessionAwareTranscriptionManager(DeterministicFakeTranscriber)
        manager.create_session("session-a")
        manager.create_session("session-b")

        interim_a = manager.process_chunk("session-a", pcm_chunk(0))
        interim_b = manager.process_chunk("session-b", pcm_chunk(0))
        final_a = manager.process_chunk("session-a", pcm_chunk(1))

        self.assertEqual(interim_a[0].session_id, "session-a")
        self.assertEqual(interim_b[0].session_id, "session-b")
        self.assertEqual(final_a[0].event_type, TranscriptUpdateType.FINALIZATION)
        self.assertEqual(manager.get_transcript("session-b", include_interim=True), interim_b[0].text)
        self.assertNotEqual(manager.get_transcript("session-a"), manager.get_transcript("session-b"))

    def test_interim_produces_revision_event(self) -> None:
        manager = manager_with_batches([transcript_event("evt-1", "seg-1", "draft")])
        manager.create_session("session-1")

        update = manager.process_chunk("session-1", b"\x00\x00")[0]

        self.assertEqual(update.event_type, TranscriptUpdateType.REVISION)
        self.assertEqual(update.revision, 1)

    def test_multiple_interim_revisions_advance_revision_number(self) -> None:
        manager = manager_with_batches(
            [transcript_event("evt-1", "seg-1", "draft")],
            [transcript_event("evt-2", "seg-1", "revised")],
        )
        manager.create_session("session-1")

        first = manager.process_chunk("session-1", pcm_chunk(0))[0]
        second = manager.process_chunk("session-1", pcm_chunk(1))[0]

        self.assertEqual((first.revision, second.revision), (1, 2))
        self.assertEqual(second.text, "revised")

    def test_finalization_replaces_interim_in_transcript(self) -> None:
        manager = manager_with_batches(
            [transcript_event("evt-1", "seg-1", "draft")],
            [transcript_event("evt-2", "seg-1", "final words", final=True)],
        )
        manager.create_session("session-1")
        manager.process_chunk("session-1", pcm_chunk(0))

        update = manager.process_chunk("session-1", pcm_chunk(1))[0]

        self.assertEqual(update.event_type, TranscriptUpdateType.FINALIZATION)
        self.assertEqual(manager.get_transcript("session-1"), "final words")

    def test_finalize_session_flushes_pending_interim_as_finalization(self) -> None:
        manager = SessionAwareTranscriptionManager(DeterministicFakeTranscriber)
        manager.create_session("session-1")
        manager.process_chunk("session-1", pcm_chunk(0))

        updates = manager.finalize_session("session-1")

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].event_type, TranscriptUpdateType.FINALIZATION)
        self.assertEqual(updates[0].sequence_id, 0)
        self.assertEqual(manager.finalize_session("session-1"), [])

    def test_duplicate_interim_event_does_not_create_revision(self) -> None:
        duplicate = transcript_event("same-event", "seg-1", "draft")
        manager = manager_with_batches([duplicate], [duplicate])
        manager.create_session("session-1")

        first = manager.process_chunk("session-1", pcm_chunk(0))
        second = manager.process_chunk("session-1", pcm_chunk(1))

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(len(manager.get_events("session-1")), 1)

    def test_duplicate_finalization_is_idempotent(self) -> None:
        manager = manager_with_batches(
            [transcript_event("final-1", "seg-1", "final words", final=True)],
            [transcript_event("final-2", "seg-1", "changed final", final=True)],
        )
        manager.create_session("session-1")

        first = manager.process_chunk("session-1", pcm_chunk(0))
        second = manager.process_chunk("session-1", pcm_chunk(1))

        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].event_type, TranscriptUpdateType.FINALIZATION)
        self.assertEqual(second, [])
        self.assertEqual(manager.get_transcript("session-1"), "final words")

    def test_late_interim_after_final_is_ignored(self) -> None:
        manager = manager_with_batches(
            [transcript_event("final-1", "seg-1", "final words", final=True)],
            [transcript_event("late-1", "seg-1", "stale interim")],
        )
        manager.create_session("session-1")
        manager.process_chunk("session-1", pcm_chunk(0))

        self.assertEqual(manager.process_chunk("session-1", pcm_chunk(1)), [])
        self.assertEqual(manager.get_transcript("session-1"), "final words")

    def test_older_interim_sequence_does_not_replace_newer_revision(self) -> None:
        manager = manager_with_batches(
            [transcript_event("newer", "seg-1", "newest")],
            [transcript_event("older", "seg-1", "stale")],
        )
        manager.create_session("session-1")
        first = manager.process_chunk("session-1", pcm_chunk(8))[0]

        self.assertEqual(manager.process_chunk("session-1", pcm_chunk(4)), [])
        self.assertEqual(manager.get_transcript("session-1", include_interim=True), "newest")
        self.assertEqual(first.sequence_id, 8)

    def test_out_of_order_segments_are_accumulated_chronologically(self) -> None:
        manager = manager_with_batches(
            [transcript_event("late", "seg-late", "second", final=True, start_time=1.0)],
            [transcript_event("early", "seg-early", "first", final=True, start_time=0.0)],
        )
        manager.create_session("session-1")
        manager.process_chunk("session-1", pcm_chunk(2))
        manager.process_chunk("session-1", pcm_chunk(1))

        self.assertEqual(manager.get_transcript("session-1"), "first second")

    def test_configurable_confidence_threshold_accepts_high_confidence(self) -> None:
        manager = manager_with_batches(
            [transcript_event("evt-1", "seg-1", "confident", confidence=0.91)],
            confidence_threshold=0.9,
        )
        manager.create_session("session-1")

        update = manager.process_chunk("session-1", b"\x00\x00")[0]

        self.assertFalse(update.review_required)
        self.assertEqual(manager.confidence_threshold, 0.9)

    def test_invalid_confidence_threshold_is_rejected(self) -> None:
        for threshold in (-0.1, 1.1, float("nan"), float("inf"), True):
            with self.subTest(threshold=threshold):
                with self.assertRaises(STTConfigurationError):
                    SessionAwareTranscriptionManager(
                        adapter_factory=DeterministicFakeTranscriber,
                        confidence_threshold=threshold,
                    )

    def test_missing_confidence_is_explicitly_flagged_for_review(self) -> None:
        policy = ConfidencePolicy(0.8)
        event = transcript_event("evt-1", "seg-1", "unknown score", confidence=None)
        manager = manager_with_batches([event])
        manager.create_session("session-1")

        update = manager.process_chunk("session-1", b"\x00\x00")[0]

        self.assertIsNone(event.segment.confidence)
        self.assertIsNone(update.confidence)
        self.assertTrue(policy.requires_review(None))
        self.assertTrue(update.review_required)
        self.assertEqual(manager.get_transcript("session-1", include_interim=True), "unknown score")

    def test_low_confidence_is_emitted_and_flagged_not_discarded(self) -> None:
        manager = manager_with_batches(
            [transcript_event("evt-1", "seg-1", "review this", confidence=0.2)],
            confidence_threshold=0.8,
        )
        manager.create_session("session-1")

        update = manager.process_chunk("session-1", b"\x00\x00")[0]

        self.assertTrue(update.review_required)
        self.assertEqual(update.text, "review this")
        self.assertEqual(manager.get_transcript("session-1", include_interim=True), "review this")

    def test_malformed_provider_event_becomes_normalized_error(self) -> None:
        manager = manager_with_batches([object()])
        manager.create_session("session-1")

        updates = manager.process_chunk("session-1", pcm_chunk(3))

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].event_type, TranscriptUpdateType.ERROR)
        self.assertEqual(updates[0].session_id, "session-1")
        self.assertEqual(updates[0].sequence_id, 3)
        self.assertEqual(updates[0].error.code, "STT_PERMANENT_ERROR")


if __name__ == "__main__":
    unittest.main()
