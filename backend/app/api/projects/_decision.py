"""Pure decision-prompt and regeneration-directive helpers for the conversation router.

Extracted verbatim from conversation.py; re-imported there so the
monkeypatch contract on app.api.projects.conversation.<name> still holds.
"""

import re

from app.api.projects._intent import _PROPOSAL_DISCOVERY_OUTPUT_TYPES, _is_redo_followup
from app.core.config import settings
from app.services.proposal_policy import derive_proposal_skill_targets


_WIKI_REF_PATTERN = re.compile(r"\[Wiki:\s*([^\]\n]+?)\]")


def _extract_wiki_titles(excerpt: str) -> list[str]:
    """Pull out unique wiki page titles referenced in a planner excerpt."""
    if not excerpt:
        return []
    seen: list[str] = []
    for match in _WIKI_REF_PATTERN.finditer(excerpt):
        title = match.group(1).strip()
        if title and title not in seen:
            seen.append(title)
    return seen[:12]


def _sanitize_decision_answers(raw: object) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for k, v in raw.items():
        key = str(k or "").strip()
        if not key:
            continue
        values = [str(x).strip() for x in (v if isinstance(v, list) else []) if str(x).strip()]
        out[key] = values[:5]
    return out


def _build_decision_prompts(
    *,
    content: str,
    template_ids: list[str],
    custom_output_types: list[str],
    current_answers: dict[str, list[str]],
) -> tuple[list[dict], list[str], list[str], list[str]]:
    """Return (decision_prompts, unresolved_ids, blocking_questions, soft_hints).

    ``blocking_questions`` are tied 1-to-1 with ``unresolved_ids`` and gate
    confirmation.  ``soft_hints`` are advisory messages shown to the user but
    they never prevent plan confirmation.
    """
    is_proposal = bool({str(x).strip().lower() for x in (template_ids or [])} & _PROPOSAL_DISCOVERY_OUTPUT_TYPES)
    if not settings.instruction_decision_prompts_enabled and not (
        settings.proposal_discovery_prompts_enabled and is_proposal
    ):
        return [], [], [], []
    prompts: list[dict] = []
    unresolved: list[str] = []
    open_questions: list[str] = []
    soft_hints: list[str] = []
    deliverable_opts = [
        {"value": "proposal", "label": "Proposal"},
        {"value": "report", "label": "Report"},
        {"value": "sop", "label": "SOP"},
        {"value": "deck", "label": "Deck / presentation"},
    ]
    selected_primary = current_answers.get("primary_deliverable", [])
    prompts.append(
        {
            "id": "primary_deliverable",
            "label": "🎯 What's the primary deliverable?",
            "mode": "single_select",
            "required": True,
            "options": deliverable_opts,
            "selected_values": selected_primary[:1],
        }
    )
    if not selected_primary:
        unresolved.append("primary_deliverable")
        open_questions.append(
            "🎯 What's the primary deliverable? (This shapes everything—proposal, report, SOP, or deck?)"
        )

    if not template_ids and not custom_output_types:
        format_opts = [
            {"value": "process_map", "label": "Process map"},
            {"value": "docx", "label": "Word (DOCX)"},
            {"value": "pptx", "label": "Slides (PPTX)"},
            {"value": "xlsx", "label": "Spreadsheet (XLSX)"},
            {"value": "pdf", "label": "PDF"},
        ]
        selected_formats = current_answers.get("preferred_outputs", [])
        prompts.append(
            {
                "id": "preferred_outputs",
                "label": "✨ Which formats should we deliver?",
                "mode": "multi_select",
                "required": True,
                "options": format_opts,
                "selected_values": selected_formats[:5],
                "min_select": 1,
            }
        )
        if not selected_formats:
            unresolved.append("preferred_outputs")
            open_questions.append("✨ Which output formats work best for you? (Pick one or more: slides, Word, spreadsheet, PDF, or process map)")

    if len(content.split()) < 8:
        soft_hints.append("💡 Quick tip: More detail on scope, audience, and depth = better results. Worth adding?")

    if settings.proposal_discovery_prompts_enabled and is_proposal:
        narrative_selected = current_answers.get("narrative_arc", [])
        prompts.append(
            {
                "id": "narrative_arc",
                "label": "Story arc",
                "description": "How should the narrative unfold for this audience?",
                "mode": "single_select",
                "required": True,
                "allow_custom": True,
                "custom_placeholder": "Or describe your own storyline in 1–2 sentences…",
                "options": [
                    {
                        "value": "scqa",
                        "label": "Situation → Complication → Question → Answer",
                        "description": "Classic consulting arc. Frame today's state, the problem, the key question, then the recommendation.",
                    },
                    {
                        "value": "pyramid",
                        "label": "Recommendation-first (Pyramid)",
                        "description": "Lead with the answer, then back it up with supporting evidence. Best for senior, time-poor audiences.",
                    },
                    {
                        "value": "case_led",
                        "label": "Case-led story",
                        "description": "Anchor the narrative around a client case or success story and draw lessons for this client.",
                    },
                    {
                        "value": "compare",
                        "label": "Compare options",
                        "description": "Walk through 2–3 alternatives side-by-side, then land on a recommended option.",
                    },
                ],
                "selected_values": narrative_selected[:1],
            }
        )
        if not narrative_selected:
            unresolved.append("narrative_arc")
            open_questions.append(
                "Pick a story arc — or type your own — so Sheldon knows how to unfold the narrative."
            )

        audience_selected = current_answers.get("audience_role", [])
        prompts.append(
            {
                "id": "audience_role",
                "label": "Primary audience",
                "description": "Who will be reading this first? Sheldon tailors depth and tone to them.",
                "mode": "single_select",
                "required": True,
                "allow_custom": True,
                "custom_placeholder": "Or describe the audience (e.g. COO + transformation office)",
                "options": [
                    {
                        "value": "cfo",
                        "label": "CFO / Finance leadership",
                        "description": "Finance-led buyer: case for value, risk, and payback.",
                    },
                    {
                        "value": "board",
                        "label": "Board / ExCo",
                        "description": "Top-of-house: strategic narrative, 5-year arc, board-ready summaries.",
                    },
                    {
                        "value": "buying_committee",
                        "label": "Buying committee",
                        "description": "Mixed procurement / sponsor / IT committee evaluating vendors.",
                    },
                    {
                        "value": "mixed",
                        "label": "Mixed stakeholders",
                        "description": "Broad audience — Sheldon will balance depth across functions.",
                    },
                ],
                "selected_values": audience_selected[:1],
            }
        )
        if not audience_selected:
            unresolved.append("audience_role")
            open_questions.append("Who is the primary audience for this proposal?")

        length_selected = current_answers.get("slide_length_budget", [])
        prompts.append(
            {
                "id": "slide_length_budget",
                "label": "Deck length",
                "description": "How long should the first draft be? You can still edit slides later.",
                "mode": "single_select",
                "required": True,
                "allow_custom": True,
                "custom_placeholder": "Or type a specific slide count (e.g. 18)",
                "options": [
                    {"value": "8", "label": "8 slides (tight, exec summary style)"},
                    {"value": "10", "label": "10 slides (balanced, default)"},
                    {"value": "12", "label": "12 slides (room for detail + case study)"},
                    {"value": "15", "label": "15 slides (full narrative + appendix)"},
                ],
                "selected_values": length_selected[:1],
            }
        )
        if not length_selected:
            unresolved.append("slide_length_budget")
            open_questions.append("How many slides should the initial draft target?")

        tone_selected = current_answers.get("tone", [])
        prompts.append(
            {
                "id": "tone",
                "label": "Narrative tone",
                "description": "Pick the voice Sheldon should write in.",
                "mode": "single_select",
                "required": True,
                "allow_custom": False,
                "options": [
                    {
                        "value": "formal",
                        "label": "Formal",
                        "description": "Measured, reserved, full sentences. Board-room appropriate.",
                    },
                    {
                        "value": "consultative",
                        "label": "Consultative",
                        "description": "Structured and advisory — balanced between authority and dialogue.",
                    },
                    {
                        "value": "punchy",
                        "label": "Punchy",
                        "description": "Short, direct, impact-first — fewer words, sharper verbs.",
                    },
                ],
                "selected_values": tone_selected[:1],
            }
        )
        if not tone_selected:
            unresolved.append("tone")
            open_questions.append("Select the tone style for the proposal narrative.")

    return prompts, unresolved, open_questions, soft_hints


def _derive_content_skill_targets(
    *,
    instruction: str,
    template_ids: list[str],
    prior_plan_meta: dict | None = None,
    llm_skill_hint: dict | None = None,
) -> dict[str, str]:
    targets = derive_proposal_skill_targets(
        instruction=instruction, output_types=template_ids, base_targets=None, llm_skill_hint=llm_skill_hint
    )
    if prior_plan_meta and _is_redo_followup(instruction):
        prior_targets = prior_plan_meta.get("content_skill_targets")
        if isinstance(prior_targets, dict):
            for out in template_ids:
                prev = str(prior_targets.get(out) or "").strip()
                if prev:
                    targets[out] = prev
    return targets


def _build_regeneration_directive(content: str) -> str:
    if not _is_redo_followup(content):
        return ""
    return (
        "Regeneration directive: produce a materially different draft while preserving factual consistency. "
        "Change at least three dimensions: (1) storyline framing, (2) value-case structure and levers, "
        "(3) risk/mitigation articulation. Avoid near-verbatim reuse of prior section wording."
    )
