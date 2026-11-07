"""
Bounded Context Builder for W3 Context & Reasoning.

Collects, filters, ranks, and budgets context items, source references, and
screen context. Enforces recency, relevance, deduplication, stale data removal,
and strict token budget limits.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from .schemas import ContextItem, SourceReference, ScreenContext


STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but",
    "by", "can", "could", "did", "do", "does", "doing", "down", "during", "each", "few", "for",
    "from", "further", "had", "has", "have", "having", "he", "her", "here", "hers", "herself",
    "him", "himself", "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just",
    "me", "more", "most", "my", "myself", "no", "nor", "not", "now", "of", "off", "on", "once",
    "only", "or", "other", "our", "ours", "ourselves", "out", "over", "own", "s", "same", "she",
    "should", "so", "some", "such", "t", "than", "that", "the", "their", "theirs", "them",
    "themselves", "then", "there", "these", "they", "this", "those", "through", "to", "too",
    "under", "until", "up", "very", "was", "we", "were", "what", "when", "where", "which",
    "while", "who", "whom", "why", "will", "with", "would", "you", "your", "yours", "yourself",
}


def tokenize_text(text: str) -> Set[str]:
    """Tokenizes text into lowercase alphanumeric words, filtering stopwords."""
    words = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 1}


@dataclass
class ContextBuilderConfig:
    """
    Configuration options for the Bounded Context Builder.
    """
    max_token_budget: int = 1500
    max_context_entries: int = 10
    recency_threshold_seconds: float = 3600.0  # 1 hour
    relevance_threshold: float = 0.20  # Minimum relevance score
    stale_context_threshold_seconds: float = 7200.0  # 2 hours (stale data discarded)
    approx_chars_per_token: float = 4.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ContextBuilderConfig:
        return cls(
            max_token_budget=int(data.get("max_token_budget", 1500)),
            max_context_entries=int(data.get("max_context_entries", 10)),
            recency_threshold_seconds=float(data.get("recency_threshold_seconds", 3600.0)),
            relevance_threshold=float(data.get("relevance_threshold", 0.20)),
            stale_context_threshold_seconds=float(data.get("stale_context_threshold_seconds", 7200.0)),
            approx_chars_per_token=float(data.get("approx_chars_per_token", 4.0)),
        )


@dataclass
class BuiltContext:
    """
    Bounded and ranked context assembled by ContextBuilder.
    """
    selected_context_items: List[ContextItem] = field(default_factory=list)
    selected_source_references: List[SourceReference] = field(default_factory=list)
    screen_context: Optional[ScreenContext] = None
    total_approx_tokens: int = 0
    dropped_items_count: int = 0
    audit_log: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected_context_items": [item.to_dict() for item in self.selected_context_items],
            "selected_source_references": [ref.to_dict() for ref in self.selected_source_references],
            "screen_context": self.screen_context.to_dict() if self.screen_context else None,
            "total_approx_tokens": self.total_approx_tokens,
            "dropped_items_count": self.dropped_items_count,
            "audit_log": list(self.audit_log),
        }


class ContextBuilder:
    """
    Selects, deduplicates, scores, and bounds context inputs within a strict token budget.
    """

    def __init__(self, config: Optional[ContextBuilderConfig] = None):
        self.config = config or ContextBuilderConfig()

    def approximate_tokens(self, text: str) -> int:
        """
        Approximates token count based on character length.
        Deterministic rule: ceil(len(text) / approx_chars_per_token).
        """
        if not text:
            return 0
        return max(1, math.ceil(len(text) / self.config.approx_chars_per_token))

    def _parse_timestamp(self, ts_str: Optional[str]) -> Optional[datetime]:
        """Safely parses ISO timestamp strings to UTC datetime."""
        if not ts_str:
            return None
        try:
            # Handle Z or timezone offset
            clean_ts = ts_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None

    def is_stale(self, timestamp_str: Optional[str], current_time: datetime) -> bool:
        """Determines whether a timestamp exceeds stale context threshold."""
        dt = self._parse_timestamp(timestamp_str)
        if dt is None:
            return False  # If no timestamp, don't drop as stale
        elapsed = (current_time - dt).total_seconds()
        return elapsed > self.config.stale_context_threshold_seconds

    def compute_recency_score(self, timestamp_str: Optional[str], current_time: datetime) -> float:
        """
        Computes normalized recency score between 0.0 and 1.0.
        Brand new = 1.0, recency_threshold_seconds old = 0.0.
        """
        dt = self._parse_timestamp(timestamp_str)
        if dt is None:
            return 0.5  # Neutral default for timeless items
        elapsed = max(0.0, (current_time - dt).total_seconds())
        if elapsed >= self.config.recency_threshold_seconds:
            return 0.0
        return round(1.0 - (elapsed / self.config.recency_threshold_seconds), 4)

    def compute_relevance(self, query: str, text: str, base_score: float = 1.0) -> float:
        """
        Computes relevance score using token intersection overlap.
        """
        q_tokens = tokenize_text(query)
        if not q_tokens:
            return base_score

        t_tokens = tokenize_text(text)
        if not t_tokens:
            return 0.0

        overlap = len(q_tokens.intersection(t_tokens))
        overlap_score = overlap / len(q_tokens)

        # Blend token overlap with base score
        final_score = (0.7 * overlap_score) + (0.3 * base_score)
        return min(1.0, max(0.0, round(final_score, 4)))

    def deduplicate_context_items(self, items: List[ContextItem]) -> Tuple[List[ContextItem], int]:
        """Deduplicates items by item_id and content."""
        seen_ids: Set[str] = set()
        seen_contents: Set[str] = set()
        unique_items: List[ContextItem] = []
        dropped = 0

        for item in items:
            normalized_content = " ".join(item.content.strip().lower().split())
            if item.item_id in seen_ids or normalized_content in seen_contents:
                dropped += 1
                continue
            seen_ids.add(item.item_id)
            seen_contents.add(normalized_content)
            unique_items.append(item)

        return unique_items, dropped

    def deduplicate_source_references(self, refs: List[SourceReference]) -> Tuple[List[SourceReference], int]:
        """Deduplicates sources by source_id and snippet."""
        seen_ids: Set[str] = set()
        seen_snippets: Set[str] = set()
        unique_refs: List[SourceReference] = []
        dropped = 0

        for ref in refs:
            normalized_snippet = " ".join(ref.snippet.strip().lower().split())
            if ref.source_id in seen_ids or normalized_snippet in seen_snippets:
                dropped += 1
                continue
            seen_ids.add(ref.source_id)
            seen_snippets.add(normalized_snippet)
            unique_refs.append(ref)

        return unique_refs, dropped

    def build_context(
        self,
        user_query: str,
        context_items: Optional[List[ContextItem]] = None,
        source_references: Optional[List[SourceReference]] = None,
        screen_context: Optional[ScreenContext] = None,
        current_time: Optional[datetime] = None,
    ) -> BuiltContext:
        """
        Builds a bounded, ranked context respecting token budget and recency/relevance thresholds.
        """
        now = current_time or datetime.now(timezone.utc)
        items_in = list(context_items or [])
        sources_in = list(source_references or [])
        audit: List[str] = []
        total_dropped = 0

        audit.append(
            f"ContextBuilder starting with {len(items_in)} context item(s) and {len(sources_in)} source reference(s)."
        )

        # 1. Filter stale context items
        fresh_items: List[ContextItem] = []
        for item in items_in:
            if self.is_stale(item.timestamp, now):
                total_dropped += 1
                audit.append(f"Filtered stale item '{item.item_id}' (timestamp: {item.timestamp}).")
            else:
                fresh_items.append(item)

        # 2. Deduplication
        deduped_items, dropped_item_dups = self.deduplicate_context_items(fresh_items)
        if dropped_item_dups > 0:
            total_dropped += dropped_item_dups
            audit.append(f"Deduplicated {dropped_item_dups} duplicate context item(s).")

        deduped_sources, dropped_source_dups = self.deduplicate_source_references(sources_in)
        if dropped_source_dups > 0:
            total_dropped += dropped_source_dups
            audit.append(f"Deduplicated {dropped_source_dups} duplicate source reference(s).")

        # 3. Score and rank source references
        scored_sources: List[Tuple[float, SourceReference]] = []
        for ref in deduped_sources:
            text_to_match = f"{ref.title} {ref.snippet}"
            rel = self.compute_relevance(user_query, text_to_match, base_score=ref.relevance_score)
            if rel >= self.config.relevance_threshold:
                scored_sources.append((rel, ref))
            else:
                total_dropped += 1
                audit.append(
                    f"Dropped source '{ref.source_id}' due to low relevance ({rel:.2f} < {self.config.relevance_threshold})."
                )

        # Rank sources by relevance score descending
        scored_sources.sort(key=lambda x: x[0], reverse=True)

        # 4. Score and rank context items (blending relevance + recency)
        scored_items: List[Tuple[float, ContextItem]] = []
        for item in deduped_items:
            rel = self.compute_relevance(user_query, item.content, base_score=0.5)
            rec = self.compute_recency_score(item.timestamp, now)
            combined_score = round((0.6 * rel) + (0.4 * rec), 4)

            # Keep items with reasonable relevance or recent conversational turns
            if combined_score >= self.config.relevance_threshold or item.category == "student_profile":
                scored_items.append((combined_score, item))
            else:
                total_dropped += 1
                audit.append(
                    f"Dropped item '{item.item_id}' due to low score ({combined_score:.2f} < {self.config.relevance_threshold})."
                )

        # Rank context items by combined score descending
        scored_items.sort(key=lambda x: x[0], reverse=True)

        # 5. Token budget allocation
        remaining_budget = self.config.max_token_budget
        used_tokens = 0

        # Reserve for screen context if capture is enabled
        selected_screen: Optional[ScreenContext] = None
        if screen_context and screen_context.capture_enabled and screen_context.ocr_extracted_text:
            screen_tokens = self.approximate_tokens(
                f"{screen_context.active_window_title or ''} {screen_context.ocr_extracted_text}"
            )
            if screen_tokens <= remaining_budget:
                selected_screen = screen_context
                remaining_budget -= screen_tokens
                used_tokens += screen_tokens
                audit.append(f"Included screen context ({screen_tokens} tokens).")
            else:
                audit.append(f"Screen context ({screen_tokens} tokens) exceeded token budget.")

        # Allocate to source references first (critical academic grounding)
        selected_sources: List[SourceReference] = []
        for score, ref in scored_sources:
            ref_tokens = self.approximate_tokens(f"{ref.title} {ref.snippet}")
            if ref_tokens <= remaining_budget:
                selected_sources.append(ref)
                remaining_budget -= ref_tokens
                used_tokens += ref_tokens
                audit.append(f"Included source '{ref.source_id}' ({ref_tokens} tokens, score {score:.2f}).")
            else:
                total_dropped += 1
                audit.append(f"Dropped source '{ref.source_id}' - would exceed token budget.")

        # Allocate to context items up to max_context_entries and remaining budget
        selected_items: List[ContextItem] = []
        for score, item in scored_items:
            if len(selected_items) >= self.config.max_context_entries:
                total_dropped += 1
                audit.append(f"Dropped item '{item.item_id}' - reached max_context_entries limit ({self.config.max_context_entries}).")
                continue

            item_tokens = self.approximate_tokens(item.content)
            if item_tokens <= remaining_budget:
                selected_items.append(item)
                remaining_budget -= item_tokens
                used_tokens += item_tokens
                audit.append(f"Included context item '{item.item_id}' ({item_tokens} tokens, score {score:.2f}).")
            else:
                total_dropped += 1
                audit.append(f"Dropped context item '{item.item_id}' - would exceed token budget.")

        audit.append(
            f"ContextBuilder complete: {len(selected_items)} item(s), {len(selected_sources)} source(s), "
            f"{used_tokens}/{self.config.max_token_budget} tokens used, {total_dropped} item(s) dropped."
        )

        return BuiltContext(
            selected_context_items=selected_items,
            selected_source_references=selected_sources,
            screen_context=selected_screen,
            total_approx_tokens=used_tokens,
            dropped_items_count=total_dropped,
            audit_log=audit,
        )
