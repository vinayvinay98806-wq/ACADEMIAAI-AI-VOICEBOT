"""
Tests for W3 Context & Reasoning data contracts and schemas.
"""

import unittest
from w3_context_reasoning.schemas import (
    ScreenContext,
    ContextItem,
    SourceReference,
    ReasoningRequest,
    ReasoningResult,
)


class TestSchemas(unittest.TestCase):

    def test_source_reference_creation_and_dict(self):
        ref = SourceReference(
            source_id="REF-101",
            title="Introduction to Algorithms",
            snippet="Sorting algorithms have lower bound O(n log n).",
            uri_or_path="textbook://algorithms.pdf",
            relevance_score=0.98,
            source_type="textbook",
        )
        self.assertEqual(ref.source_id, "REF-101")
        self.assertEqual(ref.relevance_score, 0.98)

        data = ref.to_dict()
        self.assertIsInstance(data, dict)
        self.assertEqual(data["source_id"], "REF-101")

        reconstructed = SourceReference.from_dict(data)
        self.assertEqual(reconstructed.source_id, ref.source_id)
        self.assertEqual(reconstructed.snippet, ref.snippet)

    def test_context_item_defaults_and_untrusted(self):
        item = ContextItem(item_id="CTX-01", content="User asked for help with queues.")
        self.assertEqual(item.item_id, "CTX-01")
        self.assertEqual(item.category, "conversation_history")
        self.assertTrue(item.untrusted, "ContextItem must be untrusted by default.")
        self.assertIsNotNone(item.timestamp)

        data = item.to_dict()
        reconstructed = ContextItem.from_dict(data)
        self.assertEqual(reconstructed.item_id, item.item_id)
        self.assertTrue(reconstructed.untrusted)

    def test_screen_context_safe_defaults(self):
        sc = ScreenContext()
        self.assertFalse(sc.capture_enabled, "capture_enabled MUST default to False.")
        self.assertTrue(sc.synthetic, "synthetic flag MUST default to True for mock context.")
        self.assertIsNone(sc.frame_id)

        data = sc.to_dict()
        reconstructed = ScreenContext.from_dict(data)
        self.assertFalse(reconstructed.capture_enabled)
        self.assertTrue(reconstructed.synthetic)

    def test_reasoning_request_serialization_roundtrip(self):
        ref = SourceReference(source_id="R1", title="Title", snippet="Snippet")
        ctx = ContextItem(item_id="C1", content="Content")
        screen = ScreenContext(frame_id="F1", synthetic=True)

        req = ReasoningRequest(
            request_id="REQ-001",
            session_id="SESS-100",
            user_query="How does quicksort work?",
            screen_context=screen,
            context_items=[ctx],
            source_references=[ref],
            prompt_version="v1",
            parameters={"temperature": 0.0},
        )

        data = req.to_dict()
        self.assertEqual(data["request_id"], "REQ-001")
        self.assertEqual(len(data["source_references"]), 1)
        self.assertEqual(len(data["context_items"]), 1)
        self.assertIsNotNone(data["screen_context"])

        reconstructed = ReasoningRequest.from_dict(data)
        self.assertEqual(reconstructed.request_id, req.request_id)
        self.assertEqual(reconstructed.user_query, req.user_query)
        self.assertEqual(reconstructed.source_references[0].source_id, "R1")
        self.assertEqual(reconstructed.context_items[0].item_id, "C1")
        self.assertEqual(reconstructed.screen_context.frame_id, "F1")

    def test_reasoning_result_serialization_roundtrip(self):
        result = ReasoningResult(
            result_id="RES-001",
            request_id="REQ-001",
            status="success",
            response_text="Quicksort is a divide and conquer algorithm.",
            grounded_sources=["R1"],
            confidence_score=0.95,
            intent="explain_concept",
            reasoning_steps=["Step 1", "Step 2"],
            prompt_version="v1",
        )
        data = result.to_dict()
        self.assertEqual(data["result_id"], "RES-001")
        self.assertEqual(data["grounded_sources"], ["R1"])

        reconstructed = ReasoningResult.from_dict(data)
        self.assertEqual(reconstructed.result_id, result.result_id)
        self.assertEqual(reconstructed.status, "success")
        self.assertEqual(reconstructed.confidence_score, 0.95)


if __name__ == "__main__":
    unittest.main()
