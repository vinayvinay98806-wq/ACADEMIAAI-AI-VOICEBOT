"""
Tests for W3 validation layer and error handling.
"""

import unittest
from w3_context_reasoning.schemas import (
    ScreenContext,
    ContextItem,
    SourceReference,
    ReasoningRequest,
    ReasoningResult,
)
from w3_context_reasoning.validation import (
    ValidationError,
    InvalidRequestError,
    InvalidResultError,
    GroundingError,
    validate_request,
    validate_result,
)


class TestValidation(unittest.TestCase):

    def setUp(self):
        self.valid_ref = SourceReference(
            source_id="REF-1",
            title="DSA Book",
            snippet="Binary search requires a sorted array.",
            relevance_score=0.9,
        )
        self.valid_ctx = ContextItem(item_id="CTX-1", content="Prior query was about arrays.")
        self.valid_request = ReasoningRequest(
            request_id="REQ-VALID-01",
            session_id="SESS-01",
            user_query="Can I use binary search on an unsorted list?",
            screen_context=ScreenContext(capture_enabled=False, synthetic=True),
            context_items=[self.valid_ctx],
            source_references=[self.valid_ref],
            prompt_version="v1",
        )

    def test_valid_request_passes(self):
        try:
            validate_request(self.valid_request)
        except ValidationError as e:
            self.fail(f"validate_request raised unexpected ValidationError: {e}")

    def test_empty_request_id_raises(self):
        self.valid_request.request_id = ""
        with self.assertRaises(InvalidRequestError) as ctx:
            validate_request(self.valid_request)
        self.assertIn("request_id", str(ctx.exception))

    def test_empty_user_query_raises(self):
        self.valid_request.user_query = "   "
        with self.assertRaises(InvalidRequestError) as ctx:
            validate_request(self.valid_request)
        self.assertIn("user_query", str(ctx.exception))

    def test_invalid_source_relevance_score_raises(self):
        bad_ref = SourceReference(
            source_id="R-BAD",
            title="Bad Ref",
            snippet="Snippet",
            relevance_score=1.5,  # Out of range 0.0 - 1.0
        )
        self.valid_request.source_references = [bad_ref]
        with self.assertRaises(InvalidRequestError) as ctx:
            validate_request(self.valid_request)
        self.assertIn("relevance_score", str(ctx.exception))

    def test_live_screen_capture_prohibited_in_mock(self):
        live_screen = ScreenContext(capture_enabled=True, synthetic=False)
        self.valid_request.screen_context = live_screen
        with self.assertRaises(InvalidRequestError) as ctx:
            validate_request(self.valid_request)
        self.assertIn("Live screen capture is not permitted", str(ctx.exception))

    def test_valid_result_passes(self):
        result = ReasoningResult(
            result_id="RES-01",
            request_id="REQ-VALID-01",
            status="success",
            response_text="No, binary search requires sorted data.",
            grounded_sources=["REF-1"],
            confidence_score=0.95,
        )
        try:
            validate_result(result, original_request=self.valid_request)
        except ValidationError as e:
            self.fail(f"validate_result raised unexpected ValidationError: {e}")

    def test_invalid_status_raises(self):
        result = ReasoningResult(
            result_id="RES-01",
            request_id="REQ-VALID-01",
            status="unknown_status",
            response_text="Some text",
        )
        with self.assertRaises(InvalidResultError) as ctx:
            validate_result(result)
        self.assertIn("status", str(ctx.exception))

    def test_invalid_confidence_raises(self):
        result = ReasoningResult(
            result_id="RES-01",
            request_id="REQ-VALID-01",
            status="success",
            response_text="Some text",
            confidence_score=1.2,
        )
        with self.assertRaises(InvalidResultError) as ctx:
            validate_result(result)
        self.assertIn("confidence_score", str(ctx.exception))

    def test_empty_response_text_on_success_raises(self):
        result = ReasoningResult(
            result_id="RES-01",
            request_id="REQ-VALID-01",
            status="success",
            response_text="",
        )
        with self.assertRaises(InvalidResultError) as ctx:
            validate_result(result)
        self.assertIn("response_text", str(ctx.exception))

    def test_request_id_mismatch_raises(self):
        result = ReasoningResult(
            result_id="RES-01",
            request_id="REQ-MISMATCH-99",
            status="success",
            response_text="Valid text",
        )
        with self.assertRaises(InvalidResultError) as ctx:
            validate_result(result, original_request=self.valid_request)
        self.assertIn("does not match", str(ctx.exception))

    def test_ungrounded_source_raises_grounding_error(self):
        result = ReasoningResult(
            result_id="RES-01",
            request_id="REQ-VALID-01",
            status="success",
            response_text="Hallucinated fact.",
            grounded_sources=["REF-HALLUCINATED-999"],  # Not in valid_request
            confidence_score=0.9,
        )
        with self.assertRaises(GroundingError) as ctx:
            validate_result(result, original_request=self.valid_request)
        self.assertIn("not in the request's supplied source references", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
