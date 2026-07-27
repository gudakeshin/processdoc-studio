"""DOCX pre-render critique, section rewrite, and evidence soft-block (extracted from subagents)."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.agent_types import AgentContext
from app.agents.pptx_critique_repair import (
    _claim_text,
    _evidence_remediation_directive,
    _load_run_storyline,
)
from app.core.config import settings
from app.services.claude import claude_generate_json
from app.services.otel_tracing import start_span

_LOG = logging.getLogger(__name__)

_SECTION_REPAIR_SYSTEM = (
    "You revise specific sections of a Markdown business document. You receive flagged "
    "H2 sections plus per-section fix instructions. Return ONLY JSON "
    "{\"sections\": [{\"index\": <n>, \"markdown\": \"## ...\"}]} with one entry per "
    "flagged section, each a complete section starting with its `## ` heading. Keep "
    "content you were not asked to change. No prose outside the JSON."
)


def section_hint_indices(hints: list[Any], n_sections: int) -> list[int]:
    """Valid 1-based section indices named by hints, ascending."""
    idxs: set[int] = set()
    for h in hints:
        if not isinstance(h, dict):
            continue
        raw = h.get("section_index")
        try:
            i = int(raw)
        except (TypeError, ValueError):
            continue
        if 1 <= i <= n_sections:
            idxs.add(i)
    return sorted(idxs)


def targeted_section_rewrite(
    ctx: AgentContext,
    md: str,
    hints: list[dict[str, Any]],
    *,
    directive: str = "",
    max_sections: int = 4,
) -> str:
    """ONE bounded rewrite of only the hint-flagged H2 sections; input on failure."""
    from app.services.design_review import split_h2_sections

    sections = split_h2_sections(md)
    if not sections:
        return md
    idxs = section_hint_indices(hints, len(sections))[:max_sections]
    if not idxs:
        return md
    by_idx: dict[int, list[str]] = {}
    for h in hints:
        if isinstance(h, dict) and h.get("instruction"):
            for i in section_hint_indices([h], len(sections)):
                by_idx.setdefault(i, []).append(str(h["instruction"]))
    payload = [
        {"index": i, "fix": by_idx.get(i, []), "markdown": sections[i - 1]["body"]}
        for i in idxs
    ]
    user = (
        (directive + "\n\n" if directive else "")
        + "FLAGGED SECTIONS:\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    try:
        obj = claude_generate_json(
            system=_SECTION_REPAIR_SYSTEM, user=user, temperature=0.2, max_tokens=3000
        )
    except Exception as exc:  # noqa: BLE001 — repair is best-effort
        _LOG.warning("targeted section rewrite skipped: %s", exc)
        return md
    reps = obj.get("sections") if isinstance(obj, dict) else None
    if not isinstance(reps, list):
        return md
    rep_map: dict[int, str] = {}
    for r in reps:
        if not isinstance(r, dict):
            continue
        try:
            i = int(r.get("index"))
        except (TypeError, ValueError):
            continue
        body = str(r.get("markdown") or "").strip()
        if i in set(idxs) and body.startswith("## "):
            rep_map[i] = body + "\n\n"
    if not rep_map:
        return md
    preamble = md[: len(md) - sum(len(s["body"]) for s in sections)]
    return preamble + "".join(rep_map.get(s["index"], s["body"]) for s in sections)


def critique_and_repair_docx(
    ctx: AgentContext, md: str, pm: dict[str, Any], deliverable: str
) -> str:
    """Pre-render critique→revise + evidence soft-block for markdown deliverables."""
    if not isinstance(md, str) or not md.strip():
        return md
    pm_dict = pm if isinstance(pm, dict) else None
    contract = _load_run_storyline(ctx) if deliverable in ("narrative", "proposal", "brd") else None

    with start_span(
        "docx.critique_and_repair",
        attributes={
            "project_id": str(ctx.project_id or ""),
            "run_id": str(ctx.run_id or ""),
            "deliverable": deliverable,
        },
    ):
        if getattr(settings, "deliverable_critique_loop_enabled", True):
            try:
                from app.services.design_review import review_document

                review = review_document(md, pm_dict, contract)
                hints = [h for h in (review.get("remediation_hints") or []) if isinstance(h, dict)]
                targetable = [h for h in hints if h.get("section_index")]
                if targetable:
                    md = targeted_section_rewrite(
                        ctx, md, targetable,
                        directive=(
                            "Revise each flagged section per its fix instructions. Keep the "
                            "section's structure and evidence; open with a topic sentence "
                            "that states the section's argument."
                        ),
                    )
                    after = review_document(md, pm_dict, contract)
                    if ctx.emit_event:
                        ctx.emit_event("critique_loop", {
                            "output_type": "docx",
                            "status_before": review.get("status"),
                            "status_after": after.get("status"),
                            "hints_before": len(hints),
                            "hints_after": len(after.get("remediation_hints") or []),
                        })
            except Exception as exc:  # noqa: BLE001 — critique is advisory
                _LOG.warning("docx critique loop skipped: %s", exc)

        if getattr(settings, "evidence_soft_block_enabled", True):
            try:
                from app.core.evidence_validator import validate_text_evidence
                from app.services.design_review import split_h2_sections

                sections = split_h2_sections(md)
                ev_hints = []
                claims_before = 0
                all_unsupported: list[dict[str, Any]] = []
                for s in sections:
                    validation = validate_text_evidence(s["body"], pm_dict).get("validation") or {}
                    unsupported = validation.get("unsupported_claims") or []
                    if not unsupported:
                        continue
                    claims_before += len(unsupported)
                    all_unsupported.extend(unsupported)
                    claims = ", ".join(_claim_text(c) for c in unsupported[:4] if _claim_text(c))
                    ev_hints.append({
                        "section_index": s["index"],
                        "instruction": f"Unsupported figure(s) in this section: [{claims}].",
                        "source": "evidence",
                    })
                if ev_hints:
                    md = targeted_section_rewrite(
                        ctx, md, ev_hints,
                        directive=_evidence_remediation_directive(all_unsupported, pm_dict),
                    )
                    after_validation = validate_text_evidence(md, pm_dict).get("validation") or {}
                    if ctx.emit_event:
                        ctx.emit_event("evidence_soft_block", {
                            "output_type": "docx",
                            "soft_block_applied": True,
                            "claims_before": claims_before,
                            "claims_after": len(after_validation.get("unsupported_claims") or []),
                        })
            except Exception as exc:  # noqa: BLE001 — soft-block never blocks render
                _LOG.warning("docx evidence soft-block skipped: %s", exc)

    return md


# Backward-compatible private aliases.
_section_hint_indices = section_hint_indices
_targeted_section_rewrite = targeted_section_rewrite
_critique_and_repair_docx = critique_and_repair_docx
