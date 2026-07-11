"""T45 — topic-aware direction prompts.

Tests ``harness.prompts._build_direction_gen_prompt`` (the prompt used
by UIPhase's direction-generation LLM step) and the extended
``_build_ui_prompt`` that now accepts ``intent`` + ``sections``.
"""

from __future__ import annotations

from harness.prompts import _build_direction_gen_prompt, _build_ui_prompt


class TestDirectionGenPrompt:
    def test_contains_n_placeholders(self):
        prompt = _build_direction_gen_prompt("plan text", n=3)
        assert "{N}" not in prompt  # template should already be filled
        # Just confirm mention of "3" (the N count).
        assert "3" in prompt

    def test_contains_brief(self):
        prompt = _build_direction_gen_prompt("student-growth-tracker brief", n=3)
        assert "student-growth-tracker brief" in prompt

    def test_contains_module_constraints(self):
        prompt = _build_direction_gen_prompt("...", n=3)
        for module in ["minimalist-ui", "gpt-taste", "industrial-brutalist-ui", "(none)"]:
            assert module in prompt, f"{module!r} missing from direction-gen prompt"


class TestBuildUiPromptExtended:
    """Verify ``_build_ui_prompt`` slots in ``intent`` and ``sections``
    when they are present on the direction dict."""

    BASE_AGENT_PROMPT = "You are a UI agent."

    def test_without_intent_sections_still_works(self):
        """Existing call sites without intent/sections must keep working."""
        prompt = _build_ui_prompt(
            base_prompt=self.BASE_AGENT_PROMPT,
            plan_text="PLAN",
            direction={"slug": "growth", "label": "Growth", "module": "(none)"},
            three_piece_text="3P",
            style_module_text="",
        )
        assert "---PLAN---" in prompt
        assert "growth" in prompt
        assert "---INTENT---" not in prompt  # optional block

    def test_with_intent_emits_intent_block(self):
        prompt = _build_ui_prompt(
            base_prompt=self.BASE_AGENT_PROMPT,
            plan_text="PLAN",
            direction={
                "slug": "growth",
                "label": "Growth",
                "module": "minimalist-ui",
                "intent": "Show per-student trend lines",
            },
            three_piece_text="3P",
            style_module_text="SM",
        )
        assert "---TOPIC INTENT---" in prompt
        assert "Show per-student trend lines" in prompt

    def test_with_sections_emits_sections_block(self):
        prompt = _build_ui_prompt(
            base_prompt=self.BASE_AGENT_PROMPT,
            plan_text="PLAN",
            direction={
                "slug": "growth",
                "label": "Growth",
                "module": "minimalist-ui",
                "intent": "...",
                "sections": ["trend line", "score comparison"],
            },
            three_piece_text="3P",
            style_module_text="SM",
        )
        assert "---KEY SECTIONS---" in prompt
        assert "trend line" in prompt
        assert "score comparison" in prompt
