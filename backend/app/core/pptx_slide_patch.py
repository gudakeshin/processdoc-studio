"""Deterministic in-place mutation of PPTX slide JSON (no LLM)."""

from __future__ import annotations

from typing import Any


def _set_path(obj: Any, path: str, value: Any) -> bool:
    """Set a dotted/indexed path like ``stat_cards.0.stat`` or ``bullets.2``."""
    if not path or not isinstance(obj, dict):
        return False
    parts = [p for p in path.replace("[", ".").replace("]", "").split(".") if p]
    if not parts:
        return False
    cur: Any = obj
    for part in parts[:-1]:
        if part.isdigit():
            idx = int(part)
            if not isinstance(cur, list) or idx >= len(cur):
                return False
            cur = cur[idx]
        else:
            if not isinstance(cur, dict) or part not in cur:
                return False
            cur = cur[part]
    leaf = parts[-1]
    if leaf.isdigit():
        idx = int(leaf)
        if not isinstance(cur, list) or idx >= len(cur):
            return False
        cur[idx] = value
        return True
    if not isinstance(cur, dict):
        return False
    cur[leaf] = value
    return True


def patch_slide_element(
    slides: list[dict[str, Any]],
    slide_index: int,
    *,
    element_path: str,
    value: Any,
) -> list[dict[str, Any]]:
    """Return a copy of slides with one element mutated. ``slide_index`` is 1-based."""
    if not isinstance(slides, list) or slide_index < 1 or slide_index > len(slides):
        raise ValueError("slide_index out of range")
    out = [dict(s) if isinstance(s, dict) else s for s in slides]
    target = out[slide_index - 1]
    if not isinstance(target, dict):
        raise ValueError("slide is not an object")
    target = dict(target)
    path = (element_path or "").strip()
    # Convenience aliases used by DeckCanvas clicks
    aliases = {
        "title": "title",
        "subtitle": "subtitle",
        "footer_note": "footer_note",
        "notes": "notes",
    }
    resolved = aliases.get(path, path)
    if not _set_path(target, resolved, value):
        # Direct top-level set as last resort for simple keys
        if "." not in resolved and "[" not in resolved:
            target[resolved] = value
        else:
            raise ValueError(f"could not resolve element_path: {element_path}")
    out[slide_index - 1] = target
    return out
