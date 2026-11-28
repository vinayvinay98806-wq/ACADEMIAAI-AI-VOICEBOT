"""
Tests for DeterministicMockReasoningEngine.
Verifies determinism, grounding, edge cases, and 100% offline execution.
"""

import unittest
from w3_context_reasoning.engine import DeterministicMockReasoningEngine
from w3_context_reasoning.fixtures import (
    create_sample_reasoning_request,
    create_synthetic_screen_context,
    create_sample_source_references,
    create_sample_context_items,
)
from w3_context_reasoning.schemas import ReasoningRequest


class TestDeterministicMockReasoning(unittest.TestCase):

    def setUp(self):
        self.engine = DeterministicMockReasoningEngine()

    def test_deterministic_output_identity(self):
        """Calling reason() twice with identical input produces identical outputs."""
        req1 = create_sample_reasoning_request(
            query="What is the property of a binary search tree?",
            scenario="binary_search_tree",
        )
        # Duplicate with same request_id for determinism check
        req2 = ReasoningRequest.from_dict(req1.to_dict())

        res1 = self.engine.reason(req1)
        res2 = self.engine.reason(req2)

        self.assertEqual(res1.status, res2.status)
        self.assertEqual(res1.response_text, res2.response_text)
        self.assertEqual(res1.grounded_sources, res2.grounded_sources)
        self.assertEqual(res1.confidence_score, res2.confidence_score)
        self.assertEqual(res1.intent, res2.intent)
        self.assertEqual(res1.reasoning_steps, res2.reasoning_steps)

    def test_grounding_bst_concept_query(self):
        """BST query grounds in REF-BST-001 and classifies as explain_concept."""
        req = create_sample_reasoning_request(
            query="Explain the ordering property of a binary search tree",
            scenario="binary_search_tree",
        )
        res = self.engine.reason(req)

        self.assertEqual(res.status, "success")
        self.assertEqual(res.intent, "explain_concept")
        self.assertIn("REF-BST-001", res.grounded_sources)
        self.assertIn("left subtree", res.response_text.lower())
        self.assertGreaterEqual(res.confidence_score, 0.90)

    def test_grounding_code_debugging_query(self):
        """Code debugging query grounds in REF-REC-002 and classifies as debug_code."""
        req = create_sample_reasoning_request(
            query="Help me debug my factorial recursion error and crash",
            scenario="recursion_debug",
        )
        res = self.engine.reason(req)

        self.assertEqual(res.status, "success")
        self.assertEqual(res.intent, "debug_code")
        self.assertIn("REF-REC-002", res.grounded_sources)
        self.assertIn("base case", res.response_text.lower())

    def test_grounding_syllabus_query(self):
        """Syllabus query grounds in REF-SYL-003 and classifies as academic_advising."""
        req = create_sample_reasoning_request(
            query="When is the midterm exam scheduled and what does it cover?",
            scenario="course_syllabus",
        )
        res = self.engine.reason(req)

        self.assertEqual(res.status, "success")
        self.assertEqual(res.intent, "academic_advising")
        self.assertIn("REF-SYL-003", res.grounded_sources)
        self.assertIn("week 5", res.response_text.lower())

    def test_edge_case_unresolvable_query_returns_clarification(self):
        """Queries completely unrelated to provided sources gracefully return clarification_needed."""
        req = create_sample_reasoning_request(
            query="How do I bake sourdough bread?",
            scenario="binary_search_tree",
        )
        res = self.engine.reason(req)

        self.assertEqual(res.status, "clarification_needed")
        self.assertEqual(res.grounded_sources, [])
        self.assertLess(res.confidence_score, 0.50)
        self.assertIn("clarification", res.response_text.lower())

    def test_edge_case_empty_source_references(self):
        """Requests with empty references do not crash and handle gracefully."""
        req = ReasoningRequest(
            request_id="REQ-EMPTY-REFS-01",
            session_id="SESS-01",
            user_query="Explain avl tree rotations",
            source_references=[],
            context_items=[],
        )
        res = self.engine.reason(req)
        self.assertEqual(res.status, "clarification_needed")
        self.assertEqual(res.grounded_sources, [])


if __name__ == "__main__":
    unittest.main()
