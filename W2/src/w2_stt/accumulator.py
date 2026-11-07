"""Ordered Transcript Accumulator with Event Reconciliation.

This module provides `OrderedTranscriptAccumulator`, which manages streaming transcription
results, enforces chronological ordering, handles interim-to-final transitions, suppresses
duplicate events, and safeguards against out-of-order and duplicate updates across sessions.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from w2_stt.schemas import (
    TranscriptErrorInfo,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)


class OrderedTranscriptAccumulator:
    """Maintains, reconciles, and synchronizes streaming transcript segments.

    Guarantees:
    1. Chronological Ordering: Segments are always sorted by `start_time`, `end_time`, `segment_id`.
    2. Interim-to-Final Transitions: Interim results are superseded and purged once a final segment
       for the same `segment_id` arrives.
    3. Duplicate Event Suppression: Events with previously processed `event_id`s are suppressed idempotently.
    4. Duplicate Final Segment Safety: Multiple arrivals of final segments with the same segment_id
       do not duplicate text or corrupt timeline.
    5. Out-of-Order Safety: Segments received out of chronological sequence are sorted into proper position.
    6. Error Isolation: Error events are recorded into diagnostic logs without corrupting valid segments.
    7. Session-Level State Management: Tracks session identifier, processed event counts, and total speech duration.
    """

    def __init__(self, session_id: Optional[str] = None) -> None:
        """Initialize accumulator session.

        Args:
            session_id: Optional session identifier for tracking this accumulation lifecycle.
        """
        self._session_id = session_id
        self._final_segments: Dict[str, TranscriptSegment] = {}
        self._interim_segments: Dict[str, TranscriptSegment] = {}
        self._recorded_errors: List[TranscriptErrorInfo] = []
        self._seen_event_ids: Set[str] = set()
        self._duplicate_events_count: int = 0
        self._total_event_count: int = 0

    @property
    def session_id(self) -> Optional[str]:
        """Identifier for the active transcription session."""
        return self._session_id

    @session_id.setter
    def session_id(self, value: Optional[str]) -> None:
        self._session_id = value

    @property
    def final_count(self) -> int:
        """The total number of finalized segments accumulated."""
        return len(self._final_segments)

    @property
    def has_pending_interim(self) -> bool:
        """True if there are active interim segments awaiting finalization."""
        return len(self._interim_segments) > 0

    @property
    def errors(self) -> List[TranscriptErrorInfo]:
        """List of all error payloads received during ingestion."""
        return list(self._recorded_errors)

    @property
    def duplicate_events_count(self) -> int:
        """Number of duplicate events suppressed by event_id check."""
        return self._duplicate_events_count

    @property
    def total_event_count(self) -> int:
        """Total number of unique events ingested."""
        return self._total_event_count

    @property
    def total_duration(self) -> float:
        """Total finalized speech duration in seconds."""
        return sum(s.end_time - s.start_time for s in self._final_segments.values())

    def add_event(self, event: TranscriptEvent) -> bool:
        """Ingest a TranscriptEvent into the accumulator with duplicate suppression.

        Args:
            event: The TranscriptEvent containing either a segment or an error.

        Returns:
            True if event was processed; False if suppressed as a duplicate.
        """
        # 1. Duplicate event suppression
        if event.event_id in self._seen_event_ids:
            self._duplicate_events_count += 1
            return False

        self._seen_event_ids.add(event.event_id)
        self._total_event_count += 1

        # 2. Update session_id if accumulator session was unset
        if self._session_id is None and event.session_id is not None:
            self._session_id = event.session_id

        # 3. Handle Error Event
        if event.event_type == TranscriptEventType.ERROR:
            if event.error:
                self._recorded_errors.append(event.error)
            return True

        # 4. Handle Interim or Final Segment Event
        if event.segment is not None:
            self.add_segment(event.segment)

        return True

    def add_segment(self, segment: TranscriptSegment) -> None:
        """Ingest a TranscriptSegment, resolving interim vs. final status.

        Args:
            segment: The TranscriptSegment to store.
        """
        seg_id = segment.segment_id

        if segment.is_final:
            # 1. Purge any interim representation for this segment
            self._interim_segments.pop(seg_id, None)

            # 2. Store final segment (idempotent for identical content)
            self._final_segments[seg_id] = segment
        else:
            # Only track interim if this segment has NOT already been finalized
            if seg_id not in self._final_segments:
                self._interim_segments[seg_id] = segment

    def get_segments(self, include_interim: bool = False) -> List[TranscriptSegment]:
        """Retrieve accumulated segments sorted chronologically.

        Args:
            include_interim: If True, pending interim segments are merged and sorted
                alongside finalized segments. If False, only finalized segments are returned.

        Returns:
            A chronologically sorted list of TranscriptSegment instances.
        """
        combined = list(self._final_segments.values())
        if include_interim:
            combined.extend(self._interim_segments.values())

        # Sort primarily by start_time, secondarily by end_time, tertiarily by segment_id
        return sorted(
            combined,
            key=lambda s: (s.start_time, s.end_time, s.segment_id),
        )

    def get_full_transcript(
        self,
        include_interim: bool = False,
        separator: str = " ",
    ) -> str:
        """Assembles and returns the full continuous transcript text.

        Args:
            include_interim: Whether to append pending interim segment text.
            separator: String separator between segments (default single space).

        Returns:
            Concatenated, normalized transcript text.
        """
        segments = self.get_segments(include_interim=include_interim)
        texts = [s.text.strip() for s in segments if s.text.strip()]
        return separator.join(texts)

    def get_interim_segment(self) -> Optional[TranscriptSegment]:
        """Returns the most recent active interim segment, if any exists."""
        if not self._interim_segments:
            return None
        # Return the interim segment with highest start_time / end_time
        return max(
            self._interim_segments.values(),
            key=lambda s: (s.start_time, s.end_time),
        )

    def get_segment_by_id(self, segment_id: str) -> Optional[TranscriptSegment]:
        """Look up a segment by its segment_id (checks finals first, then interims)."""
        return self._final_segments.get(segment_id) or self._interim_segments.get(segment_id)

    def clear_errors(self) -> None:
        """Clear recorded diagnostic errors without altering segments."""
        self._recorded_errors.clear()

    def reset(self) -> None:
        """Clear all stored segments, errors, and session deduplication states."""
        self._final_segments.clear()
        self._interim_segments.clear()
        self._recorded_errors.clear()
        self._seen_event_ids.clear()
        self._duplicate_events_count = 0
        self._total_event_count = 0
