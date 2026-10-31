"""
AcademiaAI AI Voice Co-Pilot - Worker 3 (Context & Reasoning)
Week 1 Runnable Demonstration.

Demonstrates:
1. Safe context creation with screen capture disabled by default.
2. Request validation and error handling.
3. Versioned prompt rendering with structural trust boundaries.
4. Deterministic grounded mock reasoning (100% offline, 0 API keys).
5. Grounded source citation and step-by-step reasoning trace.
6. Edge case handling (unresolvable queries).
"""

from __future__ import annotations

import json
from w3_context_reasoning import (
    DeterministicMockReasoningEngine,
    PromptManager,
    create_sample_reasoning_request,
    create_synthetic_screen_context,
    validate_request,
    validate_result,
)


def print_banner(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def run_demonstration():
    print_banner("ACADEMIA-AI VOICE CO-PILOT: W3 CONTEXT & REASONING (WEEK 1 DEMO)")
    print("[INFO] Initializing W3 Context & Reasoning engine (Offline Mock Mode)...")

    engine = DeterministicMockReasoningEngine()
    prompt_mgr = PromptManager()

    # --- SCENARIO 1: Academic Concept Explanation (BST) ---
    print_banner("SCENARIO 1: Academic Concept Query (Binary Search Tree)")
    req1 = create_sample_reasoning_request(
        query="What is the property of a binary search tree and its search complexity?",
        scenario="binary_search_tree",
        prompt_version="v1",
    )
    print(f"[INPUT] Request ID    : {req1.request_id}")
    print(f"[INPUT] User Query    : \"{req1.user_query}\"")
    print(f"[INPUT] Screen Capture: enabled={req1.screen_context.capture_enabled} (synthetic={req1.screen_context.synthetic})")
    print(f"[INPUT] References    : {len(req1.source_references)} available (e.g., {[r.source_id for r in req1.source_references]})")

    # Step 1: Validate Request
    validate_request(req1)
    print("[VALIDATION] ReasoningRequest passed schema validation.")

    # Step 2: Show Rendered Prompt Separation
    rendered = prompt_mgr.render_prompt(req1)
    print("\n[PROMPT RENDERING] Structural Trust Boundary Preview:")
    print("--- [Trusted System Instruction Preview] ---")
    print(rendered.system_instruction[:180] + "...")
    print("--- [Untrusted Payload Preview] ---")
    print(rendered.untrusted_payload[:220] + "...\n")

    # Step 3: Run Deterministic Reasoning
    result1 = engine.reason(req1)
    print("[OUTPUT] Status          :", result1.status)
    print("[OUTPUT] Intent          :", result1.intent)
    print("[OUTPUT] Confidence      :", f"{result1.confidence_score * 100:.1f}%")
    print("[OUTPUT] Grounded Sources:", result1.grounded_sources)
    print("[OUTPUT] Response Text   :")
    print(f"         \"{result1.response_text}\"")
    print("\n[REASONING TRACE]:")
    for step in result1.reasoning_steps:
        print(f"  -> {step}")

    # --- SCENARIO 2: Interactive Code Debugging (Recursion) ---
    print_banner("SCENARIO 2: Code Debugging Query (Recursive Factorial Bug)")
    req2 = create_sample_reasoning_request(
        query="Help me debug my recursive factorial function that is causing an error",
        scenario="recursion_debug",
        prompt_version="v1",
    )
    print(f"[INPUT] User Query: \"{req2.user_query}\"")
    result2 = engine.reason(req2)
    print("[OUTPUT] Intent          :", result2.intent)
    print("[OUTPUT] Grounded Sources:", result2.grounded_sources)
    print("[OUTPUT] Response Text   :")
    print(f"         \"{result2.response_text}\"")

    # --- SCENARIO 3: Graceful Edge Case (Unresolvable Query) ---
    print_banner("SCENARIO 3: Graceful Handling of Unresolvable Query")
    req3 = create_sample_reasoning_request(
        query="How do I bake sourdough bread?",
        scenario="binary_search_tree",
        prompt_version="v1",
    )
    print(f"[INPUT] User Query: \"{req3.user_query}\"")
    result3 = engine.reason(req3)
    print("[OUTPUT] Status          :", result3.status)
    print("[OUTPUT] Confidence      :", f"{result3.confidence_score * 100:.1f}%")
    print("[OUTPUT] Grounded Sources:", result3.grounded_sources)
    print("[OUTPUT] Response Text   :")
    print(f"         \"{result3.response_text}\"")

    print_banner("DEMONSTRATION COMPLETED SUCCESSFULLY")
    print("[SUCCESS] All scenarios executed deterministically with 0 network calls and 0 API keys.\n")


if __name__ == "__main__":
    run_demonstration()
