"""
Unit tests for LLM Client Adapter (Phase 7D).

Verifies:
- Successful mock response.
- Timeout handling.
- Retry handling.
- Malformed JSON handling.
- Invalid structured output.
- Missing required fields.
- Maximum retry limit.
- Grounding verification.
"""

import unittest
from w3_context_reasoning.schemas import ReasoningRequest, ReasoningResult, SourceReference
from w3_context_reasoning.prompts.manager import RenderedPrompt
from w3_context_reasoning.llm_adapter import (
    MockLLMClient,
    LLMConfig,
    LLMRequest,
    LLMResponse,
    LLMTimeoutError,
    LLMMalformedResponseError,
    LLMValidationError,
)


class TestLLMAdapter(unittest.TestCase):

    def setUp(self):
        self.config = LLMConfig(
            model_name="mock-academic-llm-v1",
            timeout_seconds=1.0,
            max_retries=2,
            retry_backoff_seconds=0.005,
            mock_mode=True,
        )
        self.client = MockLLMClient(config=self.config)
        self.sample_ref = SourceReference(
            source_id="REF-BST-01",
            title="BST Properties",
            snippet="BST ordering guarantees O(log n) lookup.",
            relevance_score=0.95,
        )
        self.sample_request = ReasoningRequest(
            request_id="REQ-TEST-001",
            session_id="SESS-001",
            user_query="What is BST complexity?",
            source_references=[self.sample_ref],
        )
        self.sample_rendered = RenderedPrompt(
            version="v1",
            system_instruction="System prompt",
            untrusted_payload="Untrusted payload",
            full_prompt="System prompt\nUntrusted payload",
        )

    def test_successful_mock_response(self):
        """MockLLM generates a valid, grounded ReasoningResult successfully."""
        result = self.client.generate_reasoning_result(self.sample_request, self.sample_rendered)
        self.assertIsInstance(result, ReasoningResult)
        self.assertEqual(result.request_id, "REQ-TEST-001")
        self.assertEqual(result.status, "success")
        self.assertIn("REF-BST-01", result.grounded_sources)
        self.assertGreaterEqual(result.confidence_score, 0.9)
        self.assertEqual(result.intent, "explain_concept")

    def test_timeout_handling_exceeding_max_retries(self):
        """Persistent timeout triggers LLMTimeoutError after retry exhaustion."""
        timeout_client = MockLLMClient(config=self.config, force_timeout=True)
        llm_req = LLMRequest.from_reasoning_request(self.sample_request, self.sample_rendered)

        with self.assertRaises(LLMTimeoutError) as ctx:
            timeout_client.generate(llm_req)
        self.assertIn("Simulated request timeout", str(ctx.exception))

    def test_transient_timeout_recovery_via_retries(self):
        """Transient timeout on attempt 1 succeeds on retry attempt 2."""
        # 1 simulated timeout, then succeeds on attempt 2 (within max_retries=2)
        recovering_client = MockLLMClient(config=self.config, simulated_timeout_count=1)
        llm_req = LLMRequest.from_reasoning_request(self.sample_request, self.sample_rendered)

        response = recovering_client.generate(llm_req)
        self.assertTrue(response.success)
        self.assertEqual(response.attempts, 2)
        self.assertIsNotNone(response.reasoning_result)

    def test_malformed_json_handling(self):
        """Malformed, non-JSON output triggers LLMMalformedResponseError after retries."""
        malformed_client = MockLLMClient(config=self.config, force_malformed_json=True)
        llm_req = LLMRequest.from_reasoning_request(self.sample_request, self.sample_rendered)

        with self.assertRaises(LLMMalformedResponseError) as ctx:
            malformed_client.generate(llm_req)
        self.assertIn("malformed JSON", str(ctx.exception))

    def test_transient_malformed_json_recovery(self):
        """Transient malformed JSON on attempt 1 succeeds on attempt 2."""
        recovering_client = MockLLMClient(config=self.config, simulated_malformed_count=1)
        llm_req = LLMRequest.from_reasoning_request(self.sample_request, self.sample_rendered)

        response = recovering_client.generate(llm_req)
        self.assertTrue(response.success)
        self.assertEqual(response.attempts, 2)

    def test_missing_required_fields_triggers_validation_error(self):
        """Missing required fields in LLM response triggers LLMValidationError."""
        missing_fields_client = MockLLMClient(config=self.config, force_missing_fields=True)
        llm_req = LLMRequest.from_reasoning_request(self.sample_request, self.sample_rendered)

        with self.assertRaises(LLMValidationError) as ctx:
            missing_fields_client.generate(llm_req)
        self.assertIn("failed contract validation", str(ctx.exception))

    def test_invalid_status_value_triggers_validation_error(self):
        """Invalid status string triggers LLMValidationError."""
        invalid_status_client = MockLLMClient(config=self.config, force_invalid_status=True)
        llm_req = LLMRequest.from_reasoning_request(self.sample_request, self.sample_rendered)

        with self.assertRaises(LLMValidationError) as ctx:
            invalid_status_client.generate(llm_req)
        self.assertIn("Field 'status' must be one of", str(ctx.exception))

    def test_hallucinated_source_triggers_grounding_validation_error(self):
        """Citing sources absent from the request triggers LLMValidationError."""
        ungrounded_client = MockLLMClient(config=self.config, force_ungrounded_source=True)
        llm_req = LLMRequest.from_reasoning_request(self.sample_request, self.sample_rendered)

        with self.assertRaises(LLMValidationError) as ctx:
            ungrounded_client.generate(llm_req)
        self.assertIn("Grounded source 'HALLUCINATED-SOURCE-REF-999' is not in the request", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
