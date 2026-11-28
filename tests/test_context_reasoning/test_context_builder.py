"""
Unit tests for Bounded Context Builder (Phase 7C).

Verifies:
- Recency selection.
- Relevance ranking.
- Token budget enforcement.
- Stale context filtering.
- Duplicate removal.
- Empty context handling.
- Oversized context handling.
"""

import unittest
from datetime import datetime, timezone, timedelta
from w3_context_reasoning.schemas import ContextItem, SourceReference, ScreenContext
from w3_context_reasoning.context_builder import (
    ContextBuilder,
    ContextBuilderConfig,
    BuiltContext,
)


class TestContextBuilder(unittest.TestCase):

    def setUp(self):
        self.now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        self.config = ContextBuilderConfig(
            max_token_budget=200,
            max_context_entries=3,
            recency_threshold_seconds=3600.0,
            relevance_threshold=0.20,
            stale_context_threshold_seconds=7200.0,
            approx_chars_per_token=4.0,
        )
        self.builder = ContextBuilder(config=self.config)

    def test_empty_context_handling(self):
        """Builder handles completely empty context inputs safely."""
        built = self.builder.build_context(
            user_query="What is a binary tree?",
            context_items=[],
            source_references=[],
            screen_context=None,
            current_time=self.now,
        )
        self.assertIsInstance(built, BuiltContext)
        self.assertEqual(len(built.selected_context_items), 0)
        self.assertEqual(len(built.selected_source_references), 0)
        self.assertIsNone(built.screen_context)
        self.assertEqual(built.total_approx_tokens, 0)
        self.assertEqual(built.dropped_items_count, 0)

    def test_stale_context_filtering(self):
        """Context items older than stale_context_threshold_seconds (2 hours) are discarded."""
        fresh_time = (self.now - timedelta(minutes=10)).isoformat()
        stale_time = (self.now - timedelta(hours=3)).isoformat()  # 3 hours old > 2 hours threshold

        items = [
            ContextItem(item_id="CTX-FRESH", content="Fresh discussion on tree balancing", timestamp=fresh_time),
            ContextItem(item_id="CTX-STALE", content="Very old discussion on arrays", timestamp=stale_time),
        ]

        built = self.builder.build_context(
            user_query="tree balancing",
            context_items=items,
            current_time=self.now,
        )

        selected_ids = [item.item_id for item in built.selected_context_items]
        self.assertIn("CTX-FRESH", selected_ids)
        self.assertNotIn("CTX-STALE", selected_ids)
        self.assertGreaterEqual(built.dropped_items_count, 1)

    def test_duplicate_removal(self):
        """Duplicate item IDs and identical content are deduplicated."""
        fresh_time = self.now.isoformat()
        items = [
            ContextItem(item_id="CTX-01", content="Student is enrolled in CS201", timestamp=fresh_time),
            ContextItem(item_id="CTX-01", content="Duplicate ID item", timestamp=fresh_time),
            ContextItem(item_id="CTX-02", content="Student is enrolled in CS201", timestamp=fresh_time),  # Duplicate content
            ContextItem(item_id="CTX-03", content="Distinct unique content", timestamp=fresh_time),
        ]

        sources = [
            SourceReference(source_id="REF-01", title="Title A", snippet="Snippet unique"),
            SourceReference(source_id="REF-01", title="Title A Dup ID", snippet="Snippet other"),
            SourceReference(source_id="REF-02", title="Title B", snippet="Snippet unique"),  # Duplicate snippet
        ]

        built = self.builder.build_context(
            user_query="enrolled CS201",
            context_items=items,
            source_references=sources,
            current_time=self.now,
        )

        self.assertEqual(len(built.selected_context_items), 2)
        self.assertEqual(len(built.selected_source_references), 1)
        self.assertGreaterEqual(built.dropped_items_count, 3)

    def test_relevance_ranking(self):
        """Higher relevance items and sources are ranked first."""
        fresh_time = self.now.isoformat()
        sources = [
            SourceReference(
                source_id="REF-LOW",
                title="Syllabus",
                snippet="General grading policies and academic honesty rules.",
                relevance_score=0.1,
            ),
            SourceReference(
                source_id="REF-HIGH",
                title="BST Chapter",
                snippet="Binary search tree search complexity is O(log n) in average case.",
                relevance_score=0.95,
            ),
        ]

        built = self.builder.build_context(
            user_query="What is binary search tree complexity?",
            source_references=sources,
            current_time=self.now,
        )

        self.assertEqual(len(built.selected_source_references), 1)
        self.assertEqual(built.selected_source_references[0].source_id, "REF-HIGH")

    def test_recency_selection(self):
        """Between similar items, more recent items receive higher rank."""
        recent_time = (self.now - timedelta(minutes=2)).isoformat()
        older_time = (self.now - timedelta(minutes=50)).isoformat()

        items = [
            ContextItem(
                item_id="CTX-OLDER",
                content="User asked question about sorting algorithms",
                timestamp=older_time,
            ),
            ContextItem(
                item_id="CTX-RECENT",
                content="User asked question about sorting algorithms",
                timestamp=recent_time,
            ),
        ]

        # Use distinct contents so they aren't deduplicated
        items[0].content = "User asked about sorting algorithms and quicksort partition."
        items[1].content = "User asked about sorting algorithms and mergesort divide."

        # Configure small budget allowing only 1 item
        small_cfg = ContextBuilderConfig(max_token_budget=30, max_context_entries=1)
        builder = ContextBuilder(config=small_cfg)

        built = builder.build_context(
            user_query="sorting algorithms",
            context_items=items,
            current_time=self.now,
        )

        self.assertEqual(len(built.selected_context_items), 1)
        self.assertEqual(built.selected_context_items[0].item_id, "CTX-RECENT")

    def test_token_budget_enforcement(self):
        """Items that would exceed max_token_budget are dropped."""
        # 100 characters = ~25 tokens
        # Config max_token_budget = 40 tokens
        strict_config = ContextBuilderConfig(max_token_budget=40, approx_chars_per_token=4.0)
        builder = ContextBuilder(config=strict_config)

        sources = [
            SourceReference(
                source_id="REF-1",
                title="Reference 1",
                snippet="A" * 80,  # ~20 tokens
                relevance_score=0.9,
            ),
            SourceReference(
                source_id="REF-2",
                title="Reference 2",
                snippet="B" * 80,  # ~20 tokens
                relevance_score=0.85,
            ),
            SourceReference(
                source_id="REF-3",
                title="Reference 3",
                snippet="C" * 80,  # ~20 tokens
                relevance_score=0.80,
            ),
        ]

        built = builder.build_context(
            user_query="test query",
            source_references=sources,
            current_time=self.now,
        )

        self.assertLessEqual(built.total_approx_tokens, strict_config.max_token_budget)
        self.assertLess(len(built.selected_source_references), len(sources))
        self.assertGreater(built.dropped_items_count, 0)

    def test_oversized_context_handling(self):
        """Oversized lists of hundreds of items are safely truncated within limits without crashing."""
        many_items = [
            ContextItem(
                item_id=f"CTX-MASSIVE-{i}",
                content=f"Context entry number {i} discussing academic material in detail.",
                timestamp=self.now.isoformat(),
            )
            for i in range(100)
        ]

        built = self.builder.build_context(
            user_query="academic material",
            context_items=many_items,
            current_time=self.now,
        )

        self.assertLessEqual(len(built.selected_context_items), self.config.max_context_entries)
        self.assertLessEqual(built.total_approx_tokens, self.config.max_token_budget)
        self.assertGreater(built.dropped_items_count, 90)


if __name__ == "__main__":
    unittest.main()
