"""Regression tests for PPTX title resolution and outline grounding.

These cover the smoking-gun bugs surfaced by the ``TestEngagement2`` deck
where the title slide rendered the user's raw chat message ("Help create the
proposal please") instead of the approved plan's outline/discovery.
"""

from __future__ import annotations

import pytest

from app.agents import subagents as subagents_module
from app.agents.subagents import (
    _generate_slides_batched,
    _looks_like_chat_line,
    _resolve_presentation_title,
    _strip_title_override,
    _title_from_discovery,
    _title_from_outline,
)


# ---------------------------------------------------------------------------
# 1) Chat-line detection
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "Help create the proposal please",
        "help me build a deck",
        "Can you put together a proposal?",
        "Could you draft a presentation for the CFO?",
        "please create a deck for Varroc",
        "Hi, I need a proposal",
        "hey, build a slide on finance ops",
        "write a short summary please",
        "",
    ],
)
def test_looks_like_chat_line_catches_conversational_titles(text: str) -> None:
    assert _looks_like_chat_line(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Varroc Finance Transformation Proposal",
        "CFO Briefing: Finance Operating Model",
        "Procure-to-Pay Modernisation Roadmap",
        "Executive Summary — Finance Transformation",
    ],
)
def test_looks_like_chat_line_passes_real_titles(text: str) -> None:
    assert _looks_like_chat_line(text) is False


# ---------------------------------------------------------------------------
# 2) Title resolution priority order
# ---------------------------------------------------------------------------
def test_resolve_presentation_title_prefers_outline_over_chat_intent() -> None:
    pm = {"process_name": "Help create the proposal please"}
    state = {"user_intent_original": "Help create the proposal please"}
    deck_outline = {
        "slides": [
            {
                "title": "Varroc — Finance Transformation Proposal",
                "slide_type": "title",
                "purpose": "Frame the CFO decision.",
            }
        ]
    }
    assert _resolve_presentation_title(
        pm, state, deck_outline=deck_outline
    ) == "Varroc — Finance Transformation Proposal"


def test_resolve_presentation_title_falls_back_to_discovery_when_outline_missing() -> None:
    pm = {"process_name": "Help create the proposal please"}
    state = {"user_intent_original": "Help create the proposal please"}
    discovery = {
        "client": {"name": "Varroc", "industry": "Auto components"},
        "outcome": {"primary": "Finance transformation roadmap"},
        "audience": "cfo",
    }
    title = _resolve_presentation_title(pm, state, discovery=discovery)
    assert "Varroc" in title
    # Conversational instruction must not leak through.
    assert "Help create the proposal please" not in title


def test_resolve_presentation_title_rejects_conversational_process_name() -> None:
    pm = {"process_name": "Help create the proposal please"}
    state = {"user_intent_original": "Help create the proposal please"}
    # With no outline and no discovery, we fall through to the hard fallback
    # rather than echoing the chat line.
    assert _resolve_presentation_title(pm, state) == "Executive Briefing"


def test_resolve_presentation_title_uses_genuine_process_name() -> None:
    pm = {"process_name": "Procure-to-Pay Transformation Roadmap"}
    state = {"user_intent_original": "Help create the proposal please"}
    assert (
        _resolve_presentation_title(pm, state)
        == "Procure-to-Pay Transformation Roadmap"
    )


def test_title_from_outline_rejects_conversational_outline_title() -> None:
    outline = {"slides": [{"title": "Help create the proposal please"}]}
    assert _title_from_outline(outline) == ""


def test_title_from_discovery_handles_missing_outcome_gracefully() -> None:
    # Minimal discovery with just client name should still yield a usable title.
    assert _title_from_discovery({"client": {"name": "Varroc"}}).startswith("Varroc")


# ---------------------------------------------------------------------------
# 3) Outline-driven generation — title override stripping + low threshold
# ---------------------------------------------------------------------------
def test_strip_title_override_removes_conflicting_line() -> None:
    user_core = (
        "Create a 6-slide executive presentation.\n"
        'Presentation title (use exactly): "Help create the proposal please"\n'
        "Use Deloitte visual conventions.\n"
    )
    cleaned = _strip_title_override(user_core)
    assert "Help create the proposal please" not in cleaned
    assert "Deloitte visual conventions" in cleaned


def test_generate_slides_batched_uses_outline_titles_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Integration check: the batched prompt carries the outline titles and
    the canonical presentation_title, and does NOT echo the raw chat line."""
    captured_prompts: list[str] = []

    def fake_tool_loop(ctx, *, agent_id, system, user, temperature, max_rounds=None):
        captured_prompts.append(user)
        # Return a simple JSON deck in the expected shape.
        return (
            '{"slides": ['
            '{"title": "Varroc — Finance Transformation Proposal", "slide_type": "title"},'
            '{"title": "Situation today", "slide_type": "bullets"},'
            '{"title": "Recommendation", "slide_type": "bullets"}'
            "]}"
        )

    monkeypatch.setattr(subagents_module, "_run_subagent_tool_loop_text", fake_tool_loop)

    class _DummyCtx:
        run_id = "run_test"
        plan_payload: dict = {}

    outline = [
        {
            "title": "Varroc — Finance Transformation Proposal",
            "slide_type": "title",
            "purpose": "Set up the CFO decision.",
        },
        {
            "title": "Situation today",
            "slide_type": "bullets",
            "purpose": "Capture baseline pain points.",
        },
        {
            "title": "Recommendation",
            "slide_type": "bullets",
            "purpose": "Land the pyramid recommendation.",
        },
    ]
    user_core = (
        "Create a 3-slide executive presentation.\n"
        'Presentation title (use exactly): "Help create the proposal please"\n'
        "Use Deloitte visual conventions.\n"
    )

    slides = _generate_slides_batched(
        _DummyCtx(),
        system="SYS",
        user_core=user_core,
        appendix="",
        pm={},
        outline=outline,
        temperature=0.3,
        presentation_title="Varroc — Finance Transformation Proposal",
    )
    assert slides is not None
    assert slides[0]["title"] == "Varroc — Finance Transformation Proposal"

    # The outbound prompt must not contain the conversational chat line, and
    # must contain the canonical title + outline titles.
    assert captured_prompts, "expected at least one batch call"
    full_prompt = captured_prompts[0]
    assert "Help create the proposal please" not in full_prompt
    assert "Varroc — Finance Transformation Proposal" in full_prompt
    assert "Situation today" in full_prompt
    assert "Recommendation" in full_prompt
    # Authoritative-outline instruction must be present.
    assert "outline titles" in full_prompt.lower() or "title verbatim" in full_prompt.lower()
