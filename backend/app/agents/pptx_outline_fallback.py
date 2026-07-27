"""PPTX outline helpers extracted from subagents (module-split seed)."""

from __future__ import annotations

from typing import Any


def slides_from_outline_fallback(outline: list[dict]) -> list[dict]:
    """Deterministic slide stubs from an approved outline when LLM batching fails."""
    slides: list[dict] = []
    for i, entry in enumerate(outline):
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or entry.get("action_title") or f"Slide {i + 1}").strip()
        slide_type = str(entry.get("slide_type") or entry.get("suggested_visual") or "bullets").strip()
        if slide_type not in {
            "title", "bullets", "stat_cards", "column_cards", "table", "chart",
            "big_number", "process_flow", "section_divider",
        }:
            slide_type = "bullets"
        slide: dict[str, Any] = {
            "title": title,
            "slide_type": slide_type,
            "subtitle": str(entry.get("purpose") or entry.get("key_message") or "").strip() or None,
        }
        evidence_source = str(entry.get("evidence_source") or "").strip()
        if evidence_source:
            slide["footer_note"] = f"Source: {evidence_source}"
            slide["notes"] = slide["footer_note"]
        if slide_type == "bullets":
            km = str(entry.get("key_message") or entry.get("purpose") or "").strip()
            slide["bullets"] = [km] if km else ["Content to be refined from approved outline."]
        slides.append(slide)
    return slides
