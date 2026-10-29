"""
Synthetic frames and fixtures for safe demonstration and offline testing.

SAFETY GUARANTEE:
Screen capture is disabled by default (capture_enabled=False). No real screen capture,
webcam, audio recording, or student PII is collected or processed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional
from .schemas import (
    ScreenContext,
    ContextItem,
    SourceReference,
    ReasoningRequest,
)

# Predefined synthetic slide and screen scenarios
SYNTHETIC_SCREENS: Dict[str, Dict[str, str]] = {
    "binary_search_tree": {
        "frame_id": "SYNTH-FRAME-BST-001",
        "active_window": "PDF Viewer - Lecture 7: Tree Structures.pdf",
        "ocr_text": (
            "SLIDE 14: Binary Search Trees (BST)\n"
            "Property: For any node X, all keys in the left subtree are < key(X), "
            "and all keys in the right subtree are > key(X).\n"
            "Search Time Complexity: Average O(log N), Worst Case O(N) when degenerate."
        ),
    },
    "recursion_debug": {
        "frame_id": "SYNTH-FRAME-CODE-002",
        "active_window": "VS Code - recursion_exercise.py",
        "ocr_text": (
            "def factorial(n):\n"
            "    # Missing base case! Causes RecursionError\n"
            "    return n * factorial(n - 1)\n"
            "print(factorial(5))"
        ),
    },
    "course_syllabus": {
        "frame_id": "SYNTH-FRAME-SYL-003",
        "active_window": "Browser - Course Outline: CS201 Data Structures",
        "ocr_text": (
            "Unit 3: Balanced Trees and Heaps.\n"
            "Midterm Assessment: Week 5, covers Units 1 through 3.\n"
            "Weightage: 25% of final grade."
        ),
    },
}


def create_synthetic_screen_context(
    scenario: str = "binary_search_tree",
    capture_enabled: bool = False,
) -> ScreenContext:
    """
    Creates a synthetic ScreenContext for safe offline testing and demonstration.

    SAFETY NOTE:
    capture_enabled defaults to False. real screenshots are NEVER taken.
    """
    scene = SYNTHETIC_SCREENS.get(scenario, SYNTHETIC_SCREENS["binary_search_tree"])
    return ScreenContext(
        capture_enabled=capture_enabled,
        frame_id=scene["frame_id"],
        timestamp=datetime.now(timezone.utc).isoformat(),
        ocr_extracted_text=scene["ocr_text"],
        active_window_title=scene["active_window"],
        synthetic=True,
        metadata={"scenario_name": scenario, "mock_source": "synthetic_fixtures_v1"},
    )


def create_sample_context_items() -> List[ContextItem]:
    """Generates synthetic contextual items representing past dialogue and student state."""
    now = datetime.now(timezone.utc).isoformat()
    return [
        ContextItem(
            item_id="CTX-001",
            category="student_profile",
            content="Student enrolled in 3rd Semester CS, taking Data Structures and Algorithms.",
            timestamp=now,
            metadata={"semester": 3, "major": "Computer Science"},
            untrusted=True,
        ),
        ContextItem(
            item_id="CTX-002",
            category="conversation_history",
            content="User previously asked about binary tree traversals (inorder, preorder).",
            timestamp=now,
            metadata={"turn": 1},
            untrusted=True,
        ),
    ]


def create_sample_source_references() -> List[SourceReference]:
    """Generates synthetic grounded academic source references."""
    return [
        SourceReference(
            source_id="REF-BST-001",
            title="Data Structures & Algorithms - Chapter 4: BST Properties",
            snippet=(
                "A Binary Search Tree requires every node in the left subtree to have a key strictly less "
                "than the root node's key, and every node in the right subtree to have a key strictly greater. "
                "Average lookup time is O(log n)."
            ),
            uri_or_path="course_library://textbooks/dsa/chapter4.pdf",
            relevance_score=0.95,
            source_type="textbook",
        ),
        SourceReference(
            source_id="REF-REC-002",
            title="Programming Primer - Section 2.4: Recursion Termination",
            snippet=(
                "Every recursive function must possess at least one non-recursive base case that halts "
                "further recursion. Omission of a base case results in infinite recursion and stack overflow."
            ),
            uri_or_path="course_library://guides/recursion.py",
            relevance_score=0.92,
            source_type="code",
        ),
        SourceReference(
            source_id="REF-SYL-003",
            title="CS201 Official Syllabus - Midterm Exam Schedule",
            snippet="Midterm Examination will be held during Week 5, evaluating Units 1 through 3.",
            uri_or_path="course_library://syllabus/cs201.pdf",
            relevance_score=0.88,
            source_type="syllabus",
        ),
    ]


def create_sample_reasoning_request(
    query: str = "What is the key property of a binary search tree?",
    scenario: str = "binary_search_tree",
    prompt_version: str = "v1",
) -> ReasoningRequest:
    """Helper to construct a fully populated ReasoningRequest for tests and demos."""
    return ReasoningRequest(
        request_id=f"REQ-{uuid.uuid4().hex[:8]}",
        session_id="SESS-DEMO-001",
        user_query=query,
        screen_context=create_synthetic_screen_context(scenario=scenario),
        context_items=create_sample_context_items(),
        source_references=create_sample_source_references(),
        prompt_version=prompt_version,
        parameters={"temperature": 0.0, "mock_mode": True},
    )
