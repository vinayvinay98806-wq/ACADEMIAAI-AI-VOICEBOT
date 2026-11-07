"""
AcademiaAI AI Voice Co-Pilot - Worker 3 (Context & Reasoning)
Week 2 Complete Demonstration.

Demonstrates all 8 required scenarios:
- Scenario 1: Capture disabled by default.
- Scenario 2: Explicitly enabled synthetic capture.
- Scenario 3: OCR/Vision mock processing.
- Scenario 4: Context selection based on relevance and recency.
- Scenario 5: Token-budget enforcement.
- Scenario 6: Successful mock LLM response.
- Scenario 7: Timeout and retry handling.
- Scenario 8: Malformed-output handling.

100% Offline | Zero external network calls | Zero API keys required.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta

from w3_context_reasoning import (
    CaptureConfig,
    SyntheticCaptureAdapter,
    CaptureValidator,
    CaptureConsentError,
    MockOCRVisionAdapter,
    ContextBuilder,
    ContextBuilderConfig,
    ContextItem,
    SourceReference,
    ScreenContext,
    ReasoningRequest,
    ReasoningResult,
    MockLLMClient,
    LLMConfig,
    LLMRequest,
    PromptManager,
    ContextReasoningPipeline,
    create_sample_reasoning_request,
    create_sample_context_items,
    create_sample_source_references,
)


def print_banner(title: str) -> None:
    print("\n" + "=" * 76)
    print(f"  {title}")
    print("=" * 76)


def run_demonstration():
    print_banner("ACADEMIA-AI VOICE CO-PILOT: W3 CONTEXT & REASONING (WEEK 2 DEMO)")
    print("[INFO] Execution Mode : 100% Offline / Deterministic Mock Mode")
    print("[INFO] Network Calls  : 0 (Strictly local)")
    print("[INFO] API Keys       : None required")

    # ======================================================================
    # SCENARIO 1: Capture disabled by default
    # ======================================================================
    print_banner("SCENARIO 1: Capture Disabled by Default")
    capture_config = CaptureConfig()
    adapter = SyntheticCaptureAdapter(config=capture_config)
    print(f"[CONFIG] Default consent_granted      : {capture_config.consent_granted}")
    print(f"[CONFIG] allow_synthetic_only        : {capture_config.allow_synthetic_only}")
    print(f"[CONFIG] sampling_interval_seconds   : {capture_config.sampling_interval_seconds}s")
    print(f"[CONFIG] max_size_bytes              : {capture_config.max_size_bytes} bytes")

    try:
        print("[ACTION] Attempting capture with default settings (no explicit consent)...")
        adapter.capture()
        print("[ERROR] Capture unexpectedly succeeded without consent!")
    except CaptureConsentError as cce:
        print(f"[SAFETY VERIFIED] Capture blocked as expected: {cce}")

    # ======================================================================
    # SCENARIO 2: Explicitly enabled synthetic capture
    # ======================================================================
    print_banner("SCENARIO 2: Explicitly Enabled Synthetic Capture")
    print("[ACTION] Granting explicit user consent (adapter.set_consent(True))...")
    adapter.set_consent(True)
    frame = adapter.capture(scenario="binary_search_tree")
    print(f"[OUTPUT] Frame ID      : {frame.frame_id}")
    print(f"[OUTPUT] Active Window : {frame.active_window}")
    print(f"[OUTPUT] Dimensions    : {frame.width}x{frame.height}")
    print(f"[OUTPUT] Format        : {frame.format}")
    print(f"[OUTPUT] Synthetic     : {frame.synthetic}")
    print(f"[OUTPUT] Payload Size  : {frame.size_bytes} bytes")
    print(f"[OUTPUT] Content Sample: {repr(frame.data[:60])}...")

    # ======================================================================
    # SCENARIO 3: OCR/Vision mock processing
    # ======================================================================
    print_banner("SCENARIO 3: OCR / Vision Mock Processing")
    vision_adapter = MockOCRVisionAdapter(default_confidence=0.96)
    ocr_result = vision_adapter.extract_text(frame)
    print(f"[INPUT] Frame ID        : {ocr_result.frame_id}")
    print(f"[OUTPUT] Confidence     : {ocr_result.confidence_score * 100:.1f}%")
    print(f"[OUTPUT] Detected Lines : {len(ocr_result.lines)}")
    print(f"[OUTPUT] Extracted Text :")
    for line in ocr_result.lines[:3]:
        print(f"         | {line}")
    screen_ctx = ocr_result.to_screen_context(capture_enabled=True)
    print(f"[CONVERSION] Successfully converted to ScreenContext (synthetic={screen_ctx.synthetic})")

    # ======================================================================
    # SCENARIO 4: Context selection based on relevance and recency
    # ======================================================================
    print_banner("SCENARIO 4: Context Selection Based on Relevance and Recency")
    now = datetime.now(timezone.utc)
    recent_ts = (now - timedelta(minutes=5)).isoformat()
    older_ts = (now - timedelta(minutes=50)).isoformat()
    stale_ts = (now - timedelta(hours=4)).isoformat()

    context_items = [
        ContextItem(
            item_id="CTX-RECENT",
            content="Recent question regarding tree search efficiency and binary search trees.",
            timestamp=recent_ts,
            category="conversation_history",
        ),
        ContextItem(
            item_id="CTX-OLDER",
            content="Earlier question regarding tree search efficiency and binary search trees.",
            timestamp=older_ts,
            category="conversation_history",
        ),
        ContextItem(
            item_id="CTX-STALE",
            content="Outdated session item from 4 hours ago regarding matrix operations.",
            timestamp=stale_ts,
            category="conversation_history",
        ),
        ContextItem(
            item_id="CTX-PROFILE",
            content="Enrolled in Computer Science 201 - Data Structures and Algorithms.",
            timestamp=recent_ts,
            category="student_profile",
        ),
    ]

    source_refs = [
        SourceReference(
            source_id="REF-BST-01",
            title="Data Structures: Chapter 4 BST",
            snippet="A Binary Search Tree has average lookup complexity of O(log n).",
            relevance_score=0.95,
        ),
        SourceReference(
            source_id="REF-IRRELEVANT",
            title="Campus Dining Guidelines",
            snippet="Cafeteria hours and meal plan options for semester students.",
            relevance_score=0.05,
        ),
    ]

    builder = ContextBuilder(
        config=ContextBuilderConfig(
            max_token_budget=1500,
            max_context_entries=10,
            recency_threshold_seconds=3600.0,
            relevance_threshold=0.20,
            stale_context_threshold_seconds=7200.0,
        )
    )

    query = "What is the search complexity of a binary search tree?"
    built = builder.build_context(
        user_query=query,
        context_items=context_items,
        source_references=source_refs,
        screen_context=screen_ctx,
        current_time=now,
    )

    print(f"[INPUT] Query                 : \"{query}\"")
    print(f"[INPUT] Raw Context Items     : {len(context_items)}")
    print(f"[INPUT] Raw Source References : {len(source_refs)}")
    print(f"[OUTPUT] Selected Items       : {[item.item_id for item in built.selected_context_items]}")
    print(f"[OUTPUT] Selected Sources     : {[src.source_id for src in built.selected_source_references]}")
    print(f"[OUTPUT] Dropped Items Count  : {built.dropped_items_count}")
    print("[AUDIT TRAIL SAMPLE]:")
    for log_line in built.audit_log[:4]:
        print(f"  * {log_line}")

    # ======================================================================
    # SCENARIO 5: Token-budget enforcement
    # ======================================================================
    print_banner("SCENARIO 5: Token-Budget Enforcement")
    tight_budget_builder = ContextBuilder(
        config=ContextBuilderConfig(
            max_token_budget=50,  # Extremely tight budget (approx 200 chars)
            max_context_entries=2,
            approx_chars_per_token=4.0,
        )
    )
    tight_built = tight_budget_builder.build_context(
        user_query=query,
        context_items=context_items,
        source_references=source_refs,
        screen_context=None,
        current_time=now,
    )
    print(f"[BUDGET CONFIG] Max Token Budget : 50 tokens (~200 characters)")
    print(f"[OUTPUT] Total Approx Tokens Used: {tight_built.total_approx_tokens} tokens")
    print(f"[OUTPUT] Selected Items Count    : {len(tight_built.selected_context_items)}")
    print(f"[OUTPUT] Selected Sources Count  : {len(tight_built.selected_source_references)}")
    print(f"[OUTPUT] Dropped Items Count     : {tight_built.dropped_items_count}")
    assert tight_built.total_approx_tokens <= 50, "Token budget violated!"
    print("[SAFETY VERIFIED] Context strictly contained within configured token budget.")

    # ======================================================================
    # SCENARIO 6: Successful mock LLM response
    # ======================================================================
    print_banner("SCENARIO 6: Successful Mock LLM Response")
    pipeline = ContextReasoningPipeline()
    req6 = ReasoningRequest(
        request_id="REQ-DEMO-006",
        session_id="SESS-DEMO-WEEK2",
        user_query="What is the lookup complexity of a binary search tree?",
        source_references=[source_refs[0]],
        context_items=[context_items[0]],
    )

    result6 = pipeline.process(req6, capture_consent=False)
    print(f"[INPUT] Request ID     : {req6.request_id}")
    print(f"[INPUT] User Query     : \"{req6.user_query}\"")
    print(f"[OUTPUT] Status        : {result6.status}")
    print(f"[OUTPUT] Intent        : {result6.intent}")
    print(f"[OUTPUT] Confidence    : {result6.confidence_score * 100:.1f}%")
    print(f"[OUTPUT] Grounded Ref  : {result6.grounded_sources}")
    print(f"[OUTPUT] Response Text :")
    print(f"         \"{result6.response_text}\"")

    # ======================================================================
    # SCENARIO 7: Timeout and retry handling
    # ======================================================================
    print_banner("SCENARIO 7: Timeout and Retry Handling")
    print("[INFO] Simulating transient network/model timeout on attempt 1...")
    retry_llm = MockLLMClient(
        config=LLMConfig(timeout_seconds=0.5, max_retries=2, retry_backoff_seconds=0.01),
        simulated_timeout_count=1,  # Fails once, succeeds on retry attempt 2
    )
    prompt_mgr = PromptManager()
    rendered_p = prompt_mgr.render_prompt(req6)
    llm_req = LLMRequest.from_reasoning_request(req6, rendered_p)

    resp7 = retry_llm.generate(llm_req)
    print(f"[RESULT] Request Status : {'SUCCESS' if resp7.success else 'FAILED'}")
    print(f"[RESULT] Total Attempts : {resp7.attempts} (Attempt 1: Timed out -> Attempt 2: Recovered)")
    print(f"[RESULT] Result ID      : {resp7.reasoning_result.result_id}")
    print(f"[RESULT] Grounded Citations: {resp7.reasoning_result.grounded_sources}")

    # ======================================================================
    # SCENARIO 8: Malformed-output handling
    # ======================================================================
    print_banner("SCENARIO 8: Malformed-Output Handling")
    print("[INFO] Testing graceful error recovery when LLM returns malformed non-JSON data...")
    malformed_llm = MockLLMClient(
        config=LLMConfig(max_retries=1, retry_backoff_seconds=0.005),
        force_malformed_json=True,
    )
    safe_pipeline = ContextReasoningPipeline(
        llm_client=malformed_llm,
        safe_fallback_on_error=True,
    )

    result8 = safe_pipeline.process(req6, capture_consent=False)
    print(f"[RESULT] Pipeline Handled Without Crashing : YES")
    print(f"[RESULT] Response Status                   : {result8.status}")
    print(f"[RESULT] Confidence Score                  : {result8.confidence_score}")
    print(f"[RESULT] Fallback Message                  : \"{result8.response_text}\"")

    print_banner("DEMONSTRATION COMPLETED SUCCESSFULLY")
    print("[SUMMARY] All 8 scenarios executed deterministically.")
    print("[SUMMARY] 0 external network calls made. 0 API keys required.")
    print("=" * 76 + "\n")


if __name__ == "__main__":
    run_demonstration()
