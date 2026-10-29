"""
Deterministic Mock Reasoning Engine for W3 Context & Reasoning.

Provides 100% offline, deterministic, reproducible academic reasoning
grounded in provided context items and source references without external API calls.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional, Set, Tuple
from .schemas import ReasoningRequest, ReasoningResult, SourceReference
from .validation import validate_request, validate_result
from .prompts.manager import PromptManager


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


def tokenize(text: str) -> Set[str]:
    """Extracts lowercase alpha-numeric tokens excluding common stopwords."""
    import re
    words = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 1}


class DeterministicMockReasoningEngine:
    """
    Simulates LLM reasoning deterministically based on structured context and references.
    Complies fully with W3 Week 1 milestone requirements.
    """

    def __init__(self, prompt_manager: Optional[PromptManager] = None):
        self.prompt_manager = prompt_manager or PromptManager()

    def _classify_intent(self, query: str) -> str:
        """Deterministically classifies student query intent from keywords."""
        q = query.lower()
        if any(w in q for w in ["debug", "error", "bug", "fix", "recursion", "factorial", "overflow", "crash"]):
            return "debug_code"
        if any(w in q for w in ["bst", "binary search tree", "tree", "node", "complexity", "traversal"]):
            return "explain_concept"
        if any(w in q for w in ["slide", "screen", "window", "display"]):
            return "summarize_slide"
        if any(w in q for w in ["midterm", "exam", "syllabus", "test", "schedule", "grade", "unit"]):
            return "academic_advising"
        return "general_qa"

    def _match_sources(
        self, query: str, references: List[SourceReference]
    ) -> List[SourceReference]:
        """Matches and ranks source references relevant to query tokens."""
        q_tokens = tokenize(query)
        if not q_tokens:
            return []

        scored_matches: List[Tuple[int, float, SourceReference]] = []
        for ref in references:
            ref_tokens = tokenize(ref.title + " " + ref.snippet)
            overlap = q_tokens.intersection(ref_tokens)
            if overlap:
                scored_matches.append((len(overlap), ref.relevance_score, ref))

        # Sort primarily by overlap count descending, secondarily by relevance_score descending
        scored_matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in scored_matches]

    def reason(self, request: ReasoningRequest) -> ReasoningResult:
        """
        Executes deterministic reasoning for a given request.

        Validates input request -> renders versioned prompt -> performs grounded reasoning ->
        validates output result before returning.
        """
        # 1. Strict input validation
        validate_request(request)

        # 2. Render versioned prompt (enforcing trust boundaries)
        rendered_prompt = self.prompt_manager.render_prompt(request)

        # 3. Classify intent
        intent = self._classify_intent(request.user_query)

        reasoning_steps: List[str] = [
            f"Step 1: Validated incoming request '{request.request_id}' for session '{request.session_id}'.",
            f"Step 2: Rendered prompt version '{rendered_prompt.version}' with structural trust envelope.",
            f"Step 3: Identified student intent as '{intent}' based on query semantics.",
        ]

        # 4. Resolve grounded sources
        matched_refs = self._match_sources(request.user_query, request.source_references)
        grounded_source_ids: List[str] = []
        for r in matched_refs:
            grounded_source_ids.append(r.source_id)

        # Also inspect screen context if present and relevant (using token intersection, not substring)
        screen_grounded = False
        if request.screen_context and request.screen_context.ocr_extracted_text:
            sc_tokens = tokenize(request.screen_context.ocr_extracted_text)
            q_tokens = tokenize(request.user_query)
            if q_tokens.intersection(sc_tokens):
                if request.screen_context.frame_id:
                    grounded_source_ids.append(request.screen_context.frame_id)
                    screen_grounded = True

        reasoning_steps.append(
            f"Step 4: Grounded query against {len(grounded_source_ids)} verified source reference(s): {grounded_source_ids}."
        )

        # 5. Synthesize deterministic response text grounded in references
        if intent == "debug_code" and matched_refs:
            ref = matched_refs[0]
            response_text = (
                f"Based on our reference ({ref.title}), your recursive function is missing a base case. "
                f"{ref.snippet} To fix this, add a stopping condition such as 'if n <= 1: return 1' before the recursive call."
            )
            confidence = 0.95
            status = "success"
        elif intent == "explain_concept" and matched_refs:
            ref = matched_refs[0]
            response_text = (
                f"According to {ref.title}: {ref.snippet} "
                f"This ordering property guarantees efficient search operations."
            )
            confidence = 0.96
            status = "success"
        elif intent == "academic_advising" and matched_refs:
            ref = matched_refs[0]
            response_text = (
                f"According to the official course schedule ({ref.title}): {ref.snippet}"
            )
            confidence = 0.94
            status = "success"
        elif screen_grounded and request.screen_context and request.screen_context.ocr_extracted_text:
            response_text = (
                f"From your active screen ({request.screen_context.active_window_title}): "
                f"{request.screen_context.ocr_extracted_text.strip()}"
            )
            confidence = 0.88
            status = "success"
        elif matched_refs:
            ref = matched_refs[0]
            response_text = (
                f"Grounded in {ref.title}: {ref.snippet}"
            )
            confidence = 0.85
            status = "success"
        else:
            # Safe fallback when query cannot be grounded in provided references
            response_text = (
                "I need clarification to answer this query with sufficient academic confidence because "
                "no relevant course references or textbook materials were found in the current session context. "
                "Could you please specify the topic or provide the lecture reference?"
            )
            confidence = 0.40
            status = "clarification_needed"
            grounded_source_ids = []

        reasoning_steps.append(
            f"Step 5: Emitted response with status '{status}' and confidence {confidence:.2f}."
        )

        result_id = f"RES-{request.request_id.replace('REQ-', '')}"

        result = ReasoningResult(
            result_id=result_id,
            request_id=request.request_id,
            status=status,
            response_text=response_text,
            grounded_sources=grounded_source_ids,
            confidence_score=confidence,
            intent=intent,
            reasoning_steps=reasoning_steps,
            prompt_version=rendered_prompt.version,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        # 6. Strict output validation before returning
        validate_result(result, original_request=request)

        return result
