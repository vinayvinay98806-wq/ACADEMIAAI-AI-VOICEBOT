"""
Prompt Manager supporting versioned prompt templates and structural trust separation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from ..schemas import ReasoningRequest


@dataclass
class RenderedPrompt:
    """Represents a rendered prompt ready for logging, auditing, or LLM inference."""
    version: str
    system_instruction: str
    untrusted_payload: str
    full_prompt: str


class PromptManager:
    """
    Manages versioned prompts and guarantees structural isolation
    between trusted system directives and untrusted user/retrieved inputs.
    """

    def __init__(self, prompts_root: Optional[Path] = None):
        if prompts_root is None:
            self.prompts_root = Path(__file__).parent
        else:
            self.prompts_root = Path(prompts_root)

    def list_available_versions(self) -> List[str]:
        """Lists all discovered prompt template versions."""
        versions = []
        if self.prompts_root.exists():
            for child in self.prompts_root.iterdir():
                if child.is_dir() and (child / "template.json").exists():
                    versions.append(child.name)
        return sorted(versions) if versions else ["v1"]

    def get_template_metadata(self, version: str) -> Dict[str, Any]:
        """Loads metadata dictionary for a specified prompt version."""
        version_dir = self.prompts_root / version
        template_file = version_dir / "template.json"
        if not template_file.exists():
            raise FileNotFoundError(f"Prompt template version '{version}' not found at {template_file}.")
        with open(template_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_system_prompt(self, version: str) -> str:
        """Loads trusted system prompt instructions for a given version."""
        version_dir = self.prompts_root / version
        sys_file = version_dir / "system_prompt.txt"
        if not sys_file.exists():
            raise FileNotFoundError(f"System prompt file for version '{version}' not found at {sys_file}.")
        return sys_file.read_text(encoding="utf-8").strip()

    def _sanitize_untrusted_text(self, text: str) -> str:
        """
        Escapes XML-like delimiter tokens in untrusted input to prevent jailbreaks/tag breakouts.
        """
        import re
        # Escape any <trusted_...>, </trusted_...>, <untrusted_...>, </untrusted_...> tags completely
        sanitized = re.sub(r"<(/?)trusted_([^>]+)>", r"&lt;\1trusted_\2&gt;", text)
        sanitized = re.sub(r"<(/?)untrusted_([^>]+)>", r"&lt;\1untrusted_\2&gt;", sanitized)
        return sanitized

    def render_prompt(self, request: ReasoningRequest) -> RenderedPrompt:
        """
        Renders a versioned prompt enforcing structural separation between trusted instructions
        and untrusted user / retrieved context.
        """
        version = request.prompt_version or "v1"
        try:
            system_instruction = self.get_system_prompt(version)
        except FileNotFoundError:
            # Fallback if custom directory not found
            system_instruction = (
                "You are AcademiaAI Voice Co-Pilot. Provide accurate academic reasoning "
                "grounded strictly in the supplied context."
            )

        # Assemble untrusted blocks with distinct, unambiguous boundary tags
        blocks: List[str] = []

        # 1. Untrusted user query block
        sanitized_query = self._sanitize_untrusted_text(request.user_query)
        blocks.append(
            f"<untrusted_student_query>\n{sanitized_query}\n</untrusted_student_query>"
        )

        # 2. Untrusted screen context block (if provided)
        if request.screen_context:
            sc = request.screen_context
            screen_info = [
                f"frame_id: {sc.frame_id or 'none'}",
                f"window: {sc.active_window_title or 'unknown'}",
                f"ocr_text: {sc.ocr_extracted_text or 'none'}",
                f"synthetic: {sc.synthetic}",
            ]
            sanitized_screen = self._sanitize_untrusted_text("\n".join(screen_info))
            blocks.append(
                f"<untrusted_screen_context>\n{sanitized_screen}\n</untrusted_screen_context>"
            )

        # 3. Untrusted retrieved context items (dialogue history, profile)
        if request.context_items:
            items_str = []
            for item in request.context_items:
                clean_content = self._sanitize_untrusted_text(item.content)
                items_str.append(f"[{item.category}] (id: {item.item_id}): {clean_content}")
            blocks.append(
                f"<untrusted_retrieved_context>\n" + "\n".join(items_str) + "\n</untrusted_retrieved_context>"
            )

        # 4. Untrusted grounded source references (textbook, slides, code)
        if request.source_references:
            refs_str = []
            for ref in request.source_references:
                clean_title = self._sanitize_untrusted_text(ref.title)
                clean_snippet = self._sanitize_untrusted_text(ref.snippet)
                refs_str.append(
                    f"[source_id: {ref.source_id}] (Type: {ref.source_type}, Title: {clean_title})\nSnippet: {clean_snippet}"
                )
            blocks.append(
                f"<untrusted_source_references>\n" + "\n\n".join(refs_str) + "\n</untrusted_source_references>"
            )

        untrusted_payload = "\n\n".join(blocks)

        full_prompt = (
            f"<trusted_system_instruction>\n{system_instruction}\n</trusted_system_instruction>\n\n"
            f"{untrusted_payload}"
        )

        return RenderedPrompt(
            version=version,
            system_instruction=system_instruction,
            untrusted_payload=untrusted_payload,
            full_prompt=full_prompt,
        )
