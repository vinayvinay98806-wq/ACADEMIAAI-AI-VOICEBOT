"""Offline mock demonstration of session-aware W2 transcript revisions."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from w2_stt.fake_transcriber import DeterministicFakeTranscriber
from w2_stt.session_transcription import SessionAwareTranscriptionManager


def main() -> None:
    manager = SessionAwareTranscriptionManager(
        adapter_factory=DeterministicFakeTranscriber,
        confidence_threshold=0.9,
    )
    session_id = manager.create_session(
        session_id="week3-demo-session",
        correlation_id="week3-demo-correlation",
    )
    print(f"Session: {session_id}")
    print("Provider: DeterministicFakeTranscriber (offline)")

    for chunk in (b"\x00\x01" * 80, b"\x01\x00" * 80):
        for event in manager.process_chunk(session_id, chunk):
            status = "REVIEW" if event.review_required else "ACCEPTED"
            print(
                f"{event.event_type.value}: sequence={event.sequence_id}, "
                f"segment={event.segment_id}, revision={event.revision}, "
                f"confidence={event.confidence}, status={status}, text={event.text!r}"
            )

    for event in manager.finalize_session(session_id):
        status = "REVIEW" if event.review_required else "ACCEPTED"
        print(
            f"{event.event_type.value}: sequence={event.sequence_id}, "
            f"segment={event.segment_id}, revision={event.revision}, "
            f"confidence={event.confidence}, status={status}, text={event.text!r}"
        )
    print(f"Final transcript: {manager.get_transcript(session_id)!r}")


if __name__ == "__main__":
    main()
