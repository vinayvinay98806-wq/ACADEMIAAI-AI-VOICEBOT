"""Ordered Transcript Accumulator.

This module provides `OrderedTranscriptAccumulator`, which manages streaming transcription
results, enforces chronological ordering, handles interim-to-final transitions, and
safeguards against out-of-order and duplicate updates.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from w2_stt.schemas import (
    TranscriptErrorInfo,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)


class OrderedTranscriptAccumulator:
    """Maintains and synchronizes streaming transcript segments.

    Guarantees:
    1. Chronological Ordering: Segments are always sorted by `start_time`, `end_time`, `segment_id`.
    2. Interim-to-Final Transitions: Interim results are superseded and purged once a final segment
       for the same `segment_id` arrives.
    3. Idempotency & Duplicate Handling: Duplicate final segments with identical segment IDs do not
       cause duplicate words in the assembled transcript.
    4. Out-of-Order Safety: Segments received out of sequence are correctly sorted into position.
    5. Error Isolation: Error events are recorded without invalidating previously finalized segments.
    """

    def __init__(self) -> None:
        self._final_segments: Dict[str, TranscriptSegment] = {}
        self._interim_segments: Dict[str, TranscriptSegment] = {}
        self._recorded_errors: List[TranscriptErrorInfo] = []

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

    def add_event(self, event: TranscriptEvent) -> None:
        """Ingest a TranscriptEvent into the accumulator.

        Args:
            event: The TranscriptEvent containing either a segment or an error.
        """
        if event.event_type == TranscriptEventType.ERROR:
            if event.error:
                self._recorded_errors.append(event.error)
            return

        if event.segment is not None:
            self.add_segment(event.segment)

    def add_segment(self, segment: TranscriptSegment) -> None:
        """Ingest a TranscriptSegment, resolving interim vs. final status.

        Args:
            segment: The TranscriptSegment to store.
        """
        seg_id = segment.segment_id

        if segment.is_final:
            # 1. Purge any interim representation for this segment
            self._interim_segments.pop(seg_id, None)

            # 2. Store or update final segment (idempotent for identical content)
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
        # Return the interim segment with highest start_time
        return max(
            self._interim_segments.values(),
            key=lambda s: (s.start_time, s.end_time),
        )

    def get_segment_by_id(self, segment_id: str) -> Optional[TranscriptSegment]:
        """Look up a segment by its segment_id (checks finals first, then interims)."""
        return self._final_segments.get(segment_id) or self._interim_segments.get(segment_id)

    def reset(self) -> None:
        """Clear all stored segments and errors."""
        self._final_segments.clear()
        self._interim_segments.clear()
        self._recorded_errors.clear()
