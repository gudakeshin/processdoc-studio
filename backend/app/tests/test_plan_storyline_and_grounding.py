"""Regression tests for the refactored plan UX:

- Decision prompts expose self-explanatory labels/descriptions + `allow_custom`.
- The assistant's plan message no longer inlines open-question bullets
  (those live only in ``metadata`` so the UI panel is the single source of truth).
- Wiki-page titles cited in the planner excerpt are surfaced on the plan via
  ``metadata["wiki_context_refs"]``.
- The DOCX document-outline preview is generated alongside the PPTX deck outline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.api import projects as projects_module
from app.core.config import settings
from app.services.proposal_policy import (
    _discovery_brief,
    generate_document_outline_preview,
)


# ---------------------------------------------------------------------------
# 1) Decision prompt wording / schema
# ---------------------------------------------------------------------------
def test_build_decision_prompts_has_self_explanatory_narrative_arc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "instruction_decision_prompts_enabled", True)
    monkeypatch.setattr(settings, "proposal_discovery_prompts_enabled", True)

    prompts, unresolved, questions, _hints = projects_module._build_decision_prompts(
        content="Create a proposal pitching finance transformation for the CFO.",
        template_ids=["pptx"],
        custom_output_types=[],
        current_answers={},
    )
    narrative = next(p for p in prompts if p["id"] == "narrative_arc")
    assert narrative["label"].lower() == "story arc"
    assert narrative["description"], "narrative_arc prompt must carry a description"
    assert narrative["allow_custom"] is True
    assert narrative["custom_placeholder"]

    option_values = {o["value"] for o in narrative["options"]}
    assert option_values == {"scqa", "pyramid", "case_led", "compare"}
    for opt in narrative["options"]:
        assert opt["label"], "each option needs a plain-English label"
        assert opt["description"], "each option needs a self-explanatory description"

    # Tone stays a dropdown (no free text) and also has per-option descriptions.
    tone = next(p for p in prompts if p["id"] == "tone")
    assert tone["allow_custom"] is False
    assert tone["description"]
    assert all(opt.get("description") for opt in tone["options"])

    assert "narrative_arc" in unresolved
    assert any("story arc" in q.lower() for q in questions)


# ---------------------------------------------------------------------------
# 2) Wiki-title extraction powers the "Grounded in: …" UI pill
# ---------------------------------------------------------------------------
def test_extract_wiki_titles_pulls_unique_references_from_excerpt() -> None:
    excerpt = (
        "## Planner retrieval excerpt\n\n"
        "[Wiki: Finance Ops Baseline]\nDetails…\n\n---\n\n"
        "[Wiki: CFO Briefing Archive]\nMore details…\n\n---\n\n"
        "[Wiki: Finance Ops Baseline]\nRepeat — should dedupe.\n"
    )
    titles = projects_module._extract_wiki_titles(excerpt)
    assert titles == ["Finance Ops Baseline", "CFO Briefing Archive"]


def test_extract_wiki_titles_returns_empty_for_no_refs() -> None:
    assert projects_module._extract_wiki_titles("") == []
    assert projects_module._extract_wiki_titles("no wiki markers here") == []


# ---------------------------------------------------------------------------
# 3) Document outline preview: schema + project-context plumbing
# ---------------------------------------------------------------------------
def test_discovery_brief_normalises_defaults() -> None:
    brief = _discovery_brief(None)
    assert brief["audience"] == "mixed"
    assert brief["narrative_arc"] == "pyramid"
    assert brief["tone"] == "consultative"
    assert brief["client_name"]
    assert brief["win_themes_text"] == "N/A"


def test_generate_document_outline_preview_uses_claude_and_project_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_is_claude_enabled() -> bool:
        return True

    def fake_claude_generate_json(
        *, system: str, user: str, temperature: float, max_tokens: int
    ) -> dict[str, Any]:
        captured["system"] = system
        captured["user"] = user
        return {
            "sections": [
                {
                    "heading": "Executive Summary for Varroc CFO",
                    "purpose": "Frame the decision the CFO needs to make.",
                    "key_points": ["Value at stake", "Time-to-impact"],
                    "evidence_pointer": "Wiki: Finance Ops Baseline",
                },
                {
                    "heading": "Recommended transformation roadmap",
                    "purpose": "Lay out phasing and KPIs.",
                    "key_points": ["Phase 1", "Phase 2", "Phase 3"],
                    "evidence_pointer": "Client interview notes",
                },
                {
                    "heading": "Next steps",
                    "purpose": "Drive a yes.",
                    "key_points": ["Signoff by Q2"],
                    "evidence_pointer": "",
                },
            ],
            "rationale": "Recommendation-first arc for a time-poor CFO.",
            "target_pages": 9,
        }

    monkeypatch.setattr("app.services.claude.is_claude_enabled", fake_is_claude_enabled)
    monkeypatch.setattr(
        "app.services.claude.claude_generate_json", fake_claude_generate_json
    )

    out = generate_document_outline_preview(
        instruction="Create a CFO proposal for Varroc finance transformation.",
        skill_id=None,
        discovery={
            "client": {"name": "Varroc", "industry": "Auto components"},
            "audience": "cfo",
            "narrative_arc": "pyramid",
            "win_themes": ["process automation", "cost-to-serve"],
        },
        project_context="[Wiki: Finance Ops Baseline]\nExisting state…",
    )
    assert isinstance(out, dict)
    assert len(out["sections"]) == 3
    assert out["sections"][0]["heading"].startswith("Executive")
    assert out["target_pages"] == 9
    assert "Varroc" in captured["user"]
    assert "[Wiki: Finance Ops Baseline]" in captured["user"]
    assert "Required section scaffold" in captured["user"]


def test_generate_document_outline_preview_returns_none_when_claude_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.claude.is_claude_enabled", lambda: False)
    assert generate_document_outline_preview(instruction="anything") is None


# ---------------------------------------------------------------------------
# 4) Plan message no longer duplicates open questions in the markdown body
# ---------------------------------------------------------------------------
def test_assistant_plan_message_does_not_inline_open_questions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "instruction_decision_prompts_enabled", True)
    monkeypatch.setattr(settings, "proposal_discovery_prompts_enabled", True)
    monkeypatch.setattr(settings, "proposal_discovery_enabled", True)
    monkeypatch.setattr(settings, "strategy_options_planning_enabled", False)

    # Skip actual Claude calls for outline previews.
    monkeypatch.setattr(
        projects_module, "generate_deck_outline_preview", lambda **kwargs: None
    )
    monkeypatch.setattr(
        projects_module, "generate_document_outline_preview", lambda **kwargs: None
    )

    # Stub project-context loader so we don't touch the filesystem/DB heavily.
    monkeypatch.setattr(
        projects_module,
        "_load_project_context_bundle",
        lambda *_a, **_kw: {
            "text": "[Wiki: Finance Ops Baseline]\nSome content…",
            "wiki_refs": ["Finance Ops Baseline", "CFO Briefing Archive"],
        },
    )

    captured_messages: list[Any] = []

    class _StubDB:
        def add(self, obj: Any) -> None:
            captured_messages.append(obj)

        def commit(self) -> None:  # pragma: no cover - noop
            return None

        def flush(self) -> None:  # pragma: no cover - noop
            return None

        def scalar(self, *_a: Any, **_kw: Any) -> None:
            return None

        def execute(self, *_a: Any, **_kw: Any) -> None:  # pragma: no cover
            return None

    class _StubConv:
        id = "conv_test"
        project_id = "proj_test"
        updated_at = None

    # _serialize_messages hits the DB — stub it too.
    monkeypatch.setattr(projects_module, "_serialize_messages", lambda *_a, **_kw: [])

    result = projects_module._persist_assistant_plan_message(
        db=_StubDB(),
        conv=_StubConv(),
        content="Create a proposal for the CFO of Varroc.",
        instruction="Create a proposal for the CFO of Varroc.",
        template_ids=["pptx"],
        custom_output_types=[],
        output_type_representations={},
        rationale="Recommendation-first CFO proposal.",
        decision_answers={},
        content_skill_targets={},
        regeneration_directive="",
        discovery={
            "client": {"name": "Varroc", "industry": "Auto components"},
            "audience": "cfo",
            "win_themes": ["process automation"],
        },
    )

    # The assistant message was added with a clean body (no "Open questions:" list).
    assistant_msg = next(m for m in captured_messages if getattr(m, "role", None) == "assistant")
    body = assistant_msg.content
    assert "Open questions:" not in body, (
        "Assistant body should not inline the open questions block; "
        "the Plan Decisions panel is the single source of truth."
    )
    assert "Technical Details" not in body, (
        "We also dropped the Technical Details dump — UI renders those structurally."
    )
    # It should still gently point the user to the decisions panel.
    assert "decisions panel" in body.lower() or "decisions" in body.lower()

    # Metadata carries the decision prompts, wiki_context_refs, and open_questions.
    metadata = json.loads(assistant_msg.metadata_json)
    assert metadata["open_questions"], "open_questions live in metadata only"
    assert metadata["wiki_context_refs"] == [
        "Finance Ops Baseline",
        "CFO Briefing Archive",
    ]
    assert "document_outline_preview" in metadata
    assert "deck_outline_preview" in metadata
    narrative_prompt = next(
        p for p in metadata["decision_prompts"] if p["id"] == "narrative_arc"
    )
    assert narrative_prompt["allow_custom"] is True
    assert narrative_prompt["description"]

    # Top-level response payload exposes wiki_context_refs + document_outline_preview.
    assert result["wiki_context_refs"] == ["Finance Ops Baseline", "CFO Briefing Archive"]
    assert "document_outline_preview" in result
