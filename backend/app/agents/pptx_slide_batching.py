"""Batched PPTX slide generation from an approved outline (extracted from subagents)."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.agent_types import AgentContext
from app.agents.pptx_outline_fallback import slides_from_outline_fallback
from app.agents.prompt_hygiene import process_model_json_block
from app.services.claude import _extract_first_json_object, claude_generate_json
from app.services.otel_tracing import start_span

_LOG = logging.getLogger(__name__)

_OUTLINE_CONFLICT_MARKER = "Presentation title (use exactly):"


def strip_title_override(user_core: str) -> str:
    """Remove the default "Presentation title (use exactly)" line from user_core.

    When we drive generation from the approved deck outline, the outline's
    first-slide title IS the presentation title; leaving the old override in
    place creates a conflicting instruction that lets the model hallucinate
    the user's raw chat message back onto the title slide.
    """
    if _OUTLINE_CONFLICT_MARKER not in user_core:
        return user_core
    cleaned_lines: list[str] = []
    for line in user_core.splitlines():
        if _OUTLINE_CONFLICT_MARKER in line:
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def generate_slides_batched(
    ctx: AgentContext,
    *,
    system: str,
    user_core: str,
    appendix: str,
    pm: dict,
    outline: list[dict],
    temperature: float = 0.3,
    max_rounds: int | None = None,
    presentation_title: str | None = None,
) -> list[dict] | None:
    """Generate slides in batches of 4–5, guided by the deck outline preview.

    Each batch receives the outline for its slides plus context from prior batches.
    Returns the combined slide list (outline fallback fills gaps); never returns None
    when the outline is non-empty.
    """
    # Lazy import: avoid circular import with subagents at module load time.
    from app.agents.subagents import _run_subagent_tool_loop_text, _session_debug_log

    with start_span(
        "pptx.generate_slides_batched",
        attributes={
            "project_id": str(getattr(ctx, "project_id", None) or ""),
            "run_id": str(getattr(ctx, "run_id", None) or ""),
            "outline_count": len(outline),
        },
    ):
        batch_size = 4
        all_slides: list[dict] = []
        n_total = len(outline)

        user_core_outline = strip_title_override(user_core)
        canonical_title = (presentation_title or "").strip()
        if canonical_title:
            user_core_outline = (
                f"Presentation title (use exactly): \"{canonical_title}\"\n"
                + user_core_outline
            )

        for batch_start in range(0, n_total, batch_size):
            batch_end = min(batch_start + batch_size, n_total)
            batch_outline = outline[batch_start:batch_end]

            outline_desc = "\n".join(
                (
                    f"  {batch_start + i + 1}. [{s.get('slide_type', 'bullets')}] {s.get('title', '')} — {s.get('purpose', '')}"
                    + (f" [source: {s.get('evidence_source')}]" if s.get("evidence_source") else "")
                )
                for i, s in enumerate(batch_outline)
            )
            batch_instruction = (
                f"Generate slides {batch_start + 1}–{batch_end} of {n_total} for this deck.\n"
                f"Follow this outline for these slides (titles and slide_types are authoritative):\n"
                f"{outline_desc}\n\n"
                "Return ONLY valid JSON: {\"slides\": [...]}\n"
                "Each slide MUST use the outline entry's title verbatim and its slide_type. "
                "Expand the outline purpose into concrete, client-specific content "
                "(use discovery inputs, process model, and any wiki references provided). "
                "Do NOT copy the user's raw chat instruction onto any slide — "
                "if you are unsure of a title, use the outline title exactly as given.\n"
                "When the outline entry includes a [source: ...] citation, copy that source "
                "verbatim into the slide's `footer_note` field as 'Source: <citation>' (and "
                "mirror the same line in `notes` for speaker notes).\n"
            )
            if batch_start == 0 and canonical_title:
                batch_instruction += (
                    f"\nThe first slide MUST be slide_type=\"title\" with title=\"{canonical_title}\". "
                    "Populate the subtitle/badges from the discovery inputs and process model — never "
                    "from the raw user instruction.\n"
                )
            if all_slides:
                prior_summary = json.dumps(
                    [{"title": s.get("title"), "slide_type": s.get("slide_type")} for s in all_slides],
                    ensure_ascii=False,
                )
                batch_instruction += f"\nPrior slides already generated (maintain continuity):\n{prior_summary}\n"

            batch_user = (
                batch_instruction
                + "\n"
                + user_core_outline
                + appendix
                + f"{process_model_json_block(pm)}"
            )

            raw_json = _run_subagent_tool_loop_text(
                ctx, agent_id="pptx", system=system, user=batch_user,
                temperature=temperature, max_rounds=max_rounds,
            )
            batch_obj: dict | None = None
            if raw_json:
                try:
                    batch_obj = _extract_first_json_object(raw_json)
                except Exception:
                    batch_obj = None
            if not batch_obj:
                try:
                    batch_obj = claude_generate_json(
                        system=system, user=batch_user, temperature=temperature, max_tokens=4096
                    )
                except Exception:
                    batch_obj = None

            batch_slides = batch_obj.get("slides") if isinstance(batch_obj, dict) else None
            if isinstance(batch_slides, list) and batch_slides:
                valid = [s for s in batch_slides if isinstance(s, dict) and s.get("title")]
                all_slides.extend(valid)
            else:
                try:
                    retry_obj = claude_generate_json(
                        system=system,
                        user=batch_user,
                        temperature=max(0.1, temperature - 0.1),
                        max_tokens=4096,
                    )
                    retry_slides = retry_obj.get("slides") if isinstance(retry_obj, dict) else None
                    if isinstance(retry_slides, list) and retry_slides:
                        valid = [s for s in retry_slides if isinstance(s, dict) and s.get("title")]
                        if valid:
                            all_slides.extend(valid)
                            continue
                except Exception as exc:
                    _LOG.debug("batched slide retry failed: %s", exc)

                _session_debug_log(
                    run_id=getattr(ctx, "run_id", None),
                    hypothesis_id="H5",
                    location="pptx_slide_batching.py:generate_slides_batched:batch_fail",
                    message=f"Batch {batch_start + 1}-{batch_end} failed; using outline fallback for range",
                    data={"batch_start": batch_start, "batch_end": batch_end},
                )
                all_slides.extend(slides_from_outline_fallback(batch_outline))

        return all_slides if all_slides else slides_from_outline_fallback(outline)


# Backward-compatible private aliases for subagents/tests.
_strip_title_override = strip_title_override
_generate_slides_batched = generate_slides_batched


def _slides_from_outline_fallback(outline: list[dict]) -> list[dict]:
    return slides_from_outline_fallback(outline)
