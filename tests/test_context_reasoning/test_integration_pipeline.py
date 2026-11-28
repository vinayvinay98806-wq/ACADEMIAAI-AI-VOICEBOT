"""
Integration tests for W3 Context & Reasoning Pipeline (Phase 7E).

Verifies:
- Complete end-to-end pipeline execution.
- Capture disabled by default in pipeline.
- Valid synthetic capture pipeline.
- Empty context pipeline.
- LLM failure pipeline (safe fallback handling).
- Malformed response pipeline (safe fallback handling).
"""

import unittest
from w3_context_reasoning.schemas import (
    ReasoningRequest,
    ReasoningResult,
    SourceReference,
    ContextItem,
    ScreenContext,
)
from w3_context_reasoning.capture import (
    SyntheticCaptureAdapter,
    CaptureConfig,
    CaptureConsentError,
)
from w3_context_reasoning.vision import MockOCRVisionAdapter
from w3_context_reasoning.context_builder import ContextBuilder, ContextBuilderConfig
from w3_context_reasoning.prompts.manager import PromptManager
from w3_context_reasoning.llm_adapter import MockLLMClient, LLMConfig
from w3_context_reasoning.pipeline import ContextReasoningPipeline


class TestIntegrationPipeline(unittest.TestCase):

    def setUp(self):
        self.pipeline = ContextReasoningPipeline()
        self.sample_ref = SourceReference(
            source_id="REF-BST-001",
            title="Data Structures - Binary Search Trees",
            snippet="BST left child is smaller, right child is larger. Search complexity is O(log n).",
            relevance_score=0.95,
        )
        self.sample_item = ContextItem(
            item_id="CTX-001",
            content="Student is studying CS201 Data Structures.",
            category="student_profile",
        )
        self.base_request = ReasoningRequest(
            request_id="REQ-INT-001",
            session_id="SESS-INT-001",
            user_query="What is the search complexity of a binary search tree?",
            context_items=[self.sample_item],
            source_references=[self.sample_ref],
        )

    def test_complete_pipeline_execution(self):
        """Executes full pipeline and verifies output structure, grounding, and steps."""
        result = self.pipeline.process(self.base_request, capture_consent=False)

        self.assertIsInstance(result, ReasoningResult)
        self.assertEqual(result.request_id, "REQ-INT-001")
        self.assertEqual(result.status, "success")
        self.assertIn("REF-BST-001", result.grounded_sources)
        self.assertGreaterEqual(result.confidence_score, 0.90)
        self.assertGreater(len(result.reasoning_steps), 3)

    def test_capture_disabled_by_default_in_pipeline(self):
        """Pipeline respects default disabled capture; does not capture without consent."""
        result = self.pipeline.process(self.base_request, capture_consent=False)
        self.assertEqual(result.status, "success")

        # Request attempting capture_enabled=True without capture_consent raises CaptureConsentError
        unauthorized_req = ReasoningRequest(
            request_id="REQ-UNAUTH-CAP",
            session_id="SESS-001",
            user_query="Check my screen",
            screen_context=ScreenContext(capture_enabled=True, synthetic=True, frame_id="FR-01"),
        )
        with self.assertRaises(CaptureConsentError):
            self.pipeline.process(unauthorized_req, capture_consent=False)

    def test_valid_synthetic_capture_pipeline(self):
        """Pipeline captures synthetic screen, extracts OCR, bounds context, and grounds response."""
        req = ReasoningRequest(
            request_id="REQ-INT-CAP-002",
            session_id="SESS-INT-001",
            user_query="What does my active slide say about binary search tree complexity?",
            source_references=[self.sample_ref],
        )

        result = self.pipeline.process(
            request=req,
            capture_consent=True,
            capture_scenario="binary_search_tree",
        )

        self.assertEqual(result.status, "success")
        self.assertIn("REF-BST-001", result.grounded_sources)
        self.assertTrue(any("Pipeline:" in step for step in result.reasoning_steps))

    def test_empty_context_pipeline(self):
        """Pipeline handles requests with zero context items or source references safely."""
        empty_req = ReasoningRequest(
            request_id="REQ-EMPTY-003",
            session_id="SESS-INT-001",
            user_query="Tell me about binary trees",
            context_items=[],
            source_references=[],
            screen_context=None,
        )

        result = self.pipeline.process(empty_req, capture_consent=False)
        self.assertIsInstance(result, ReasoningResult)
        self.assertEqual(result.status, "clarification_needed")
        self.assertEqual(result.grounded_sources, [])
        self.assertIn("clarification", result.response_text.lower())

    def test_llm_failure_pipeline_graceful_fallback(self):
        """Pipeline catches persistent LLM timeout and provides safe fallback result."""
        failing_client = MockLLMClient(
            config=LLMConfig(timeout_seconds=0.05, max_retries=1, retry_backoff_seconds=0.001),
            force_timeout=True,
        )
        pipeline_with_failing_llm = ContextReasoningPipeline(
            llm_client=failing_client,
            safe_fallback_on_error=True,
        )

        result = pipeline_with_failing_llm.process(self.base_request, capture_consent=False)
        self.assertIsInstance(result, ReasoningResult)
        self.assertEqual(result.status, "error")
        self.assertEqual(result.confidence_score, 0.0)
        self.assertIn("system error occurred", result.response_text.lower())

    def test_malformed_response_pipeline_graceful_fallback(self):
        """Pipeline catches malformed LLM response and produces safe fallback result."""
        malformed_client = MockLLMClient(
            config=LLMConfig(max_retries=1, retry_backoff_seconds=0.001),
            force_malformed_json=True,
        )
        pipeline_with_malformed_llm = ContextReasoningPipeline(
            llm_client=malformed_client,
            safe_fallback_on_error=True,
        )

        result = pipeline_with_malformed_llm.process(self.base_request, capture_consent=False)
        self.assertIsInstance(result, ReasoningResult)
        self.assertEqual(result.status, "error")
        self.assertEqual(result.confidence_score, 0.0)
        self.assertIn("system error occurred", result.response_text.lower())


if __name__ == "__main__":
    unittest.main()
