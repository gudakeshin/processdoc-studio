"""PPTX pre-render critique, targeted rewrite, and evidence soft-block (extracted from subagents)."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.agent_types import AgentContext
from app.core.config import settings
from app.services.claude import claude_generate_json

_LOG = logging.getLogger(__name__)

_SLIDE_REPAIR_SYSTEM = (
    "You repair individual slides of a consulting deck. You receive flagged slides as "
    "JSON plus per-slide fix instructions. Return ONLY JSON {\"slides\": [...]} with the "
    "repaired slides in the same order as given — same count, same slide_id and "
    "slide_index, same slide_type unless an instruction names a different one. Preserve "
    "every field you were not asked to change. No prose, no markdown fences."
)

_EVIDENCE_SOFT_BLOCK_DIRECTIVE = (
    "EVIDENCE FIX: for each flagged number either (a) add an explicit caveat such as "
    "'directional estimate' or 'illustrative', or (b) remove the number and state the "
    "point qualitatively. Never invent sources or new figures."
)


def pptx_visual_feedback_indices(feedback: list[Any]) -> set[int]:
    """1-based slide indices from Visual QA remediation_hints."""
    idxs: set[int] = set()
    for h in feedback:
        if not isinstance(h, dict):
            continue
        raw = h.get("slide_index")
        if isinstance(raw, int) and raw >= 1:
            idxs.add(raw)
        elif isinstance(raw, float) and raw >= 1.0:
            idxs.add(int(raw))
        elif isinstance(raw, str) and raw.strip().isdigit():
            idxs.add(int(raw.strip()))
    return idxs


def merge_pptx_slides_repair(
    prior: list[dict[str, Any]],
    repaired: list[dict[str, Any]],
    fix_indices_1based: set[int],
) -> list[dict[str, Any]]:
    """Prefer prior slides; overwrite positions flagged by Visual QA when the model returned a dict."""
    out: list[dict[str, Any]] = [dict(s) for s in prior]
    if not fix_indices_1based:
        return repaired if repaired else out
    for j in range(len(out)):
        if (j + 1) in fix_indices_1based and j < len(repaired) and isinstance(repaired[j], dict):
            out[j] = repaired[j]
    return out


def normalize_pptx_slide_identities(slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ensure stable slide/element identities for targeted regeneration workflows."""
    normalized: list[dict[str, Any]] = []
    collection_key_map: dict[str, str] = {
        "stat_cards": "card_id",
        "column_cards": "card_id",
        "stack_layers": "layer_id",
    }
    for idx, raw_slide in enumerate(slides, start=1):
        if not isinstance(raw_slide, dict):
            continue
        slide = dict(raw_slide)
        if not str(slide.get("slide_id") or "").strip():
            slide["slide_id"] = f"slide_{idx:02d}"
        slide.setdefault("slide_index", idx)
        for key, id_field in collection_key_map.items():
            value = slide.get(key)
            if not isinstance(value, list):
                continue
            out_items: list[Any] = []
            for item_idx, item in enumerate(value, start=1):
                if isinstance(item, dict):
                    next_item = dict(item)
                    if not str(next_item.get(id_field) or "").strip():
                        next_item[id_field] = f"{slide['slide_id']}_{key}_{item_idx:02d}"
                    out_items.append(next_item)
                else:
                    out_items.append(item)
            slide[key] = out_items
        bullets = slide.get("bullets")
        if isinstance(bullets, list) and bullets:
            slide.setdefault(
                "bullet_ids",
                [f"{slide['slide_id']}_bullets_{i:02d}" for i in range(1, len(bullets) + 1)],
            )
        normalized.append(slide)
    return normalized


def evidence_remediation_directive(
    unsupported_claims: list[dict[str, Any]],
    pm: dict[str, Any] | None,
) -> str:
    """Fixed soft-block directive plus validator remediation suggestions."""
    from app.core.evidence_validator import _generate_remediation

    base = _EVIDENCE_SOFT_BLOCK_DIRECTIVE
    extra = _generate_remediation(unsupported_claims, pm)
    if extra:
        return base + " Remediation guidance: " + "; ".join(extra)
    return base


def load_run_storyline(ctx: AgentContext) -> dict[str, Any] | None:
    """Load the persisted ``<run_dir>/storyline.json`` contract; None on any miss."""
    try:
        from app.services.storage import workspace_path
        from app.services.storyline_builder import load_storyline_contract

        pid = str(ctx.project_id or "").strip()
        rid = str(ctx.run_id or "").strip()
        if pid and rid:
            return load_storyline_contract(workspace_path(pid) / "runs" / rid)
    except Exception:  # noqa: BLE001 — contract is optional context
        return None
    return None


def claim_text(claim: Any) -> str:
    if isinstance(claim, dict):
        return str(claim.get("claim") or claim.get("value") or "")
    return str(claim or "")


def source_registry_for_ctx(ctx: AgentContext) -> list[dict[str, Any]]:
    """Retrieved client-document chunks from the run's compaction snapshot."""
    snap = ctx.compaction_snapshot
    if not isinstance(snap, dict):
        return []
    from app.core.evidence_validator import load_source_registry

    return load_source_registry({"compaction_snapshot": snap})


def critique_slides(
    ctx: AgentContext,
    slide_dicts: list[dict[str, Any]],
    pm: dict[str, Any] | None,
    contract: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Pre-render critique over slide dicts; returns (hints, review_report)."""
    from app.services.design_review import review_deck

    pm_dict = pm if isinstance(pm, dict) else None
    review = review_deck(slide_dicts, pm_dict, contract)
    hints: list[dict[str, Any]] = [
        h for h in (review.get("remediation_hints") or []) if isinstance(h, dict)
    ]

    try:
        from app.core.narrative_feedback import (
            build_narrative_feedback_hints,
            narrative_signals_from_run_dir,
        )
        from app.services.storage import workspace_path

        pid = str(ctx.project_id or "").strip()
        rid = str(ctx.run_id or "").strip()
        if pid and rid:
            signals = narrative_signals_from_run_dir(workspace_path(pid) / "runs" / rid)
            for nh in build_narrative_feedback_hints(signals, "pptx"):
                if isinstance(nh, dict) and nh.get("instruction"):
                    hints.append(dict(nh))
    except Exception:  # noqa: BLE001, S110 — narrative signals are optional
        pass

    if not hints and review.get("status") in ("warn", "fail"):
        try:
            from app.core.model_tiers import critique_model

            titles = [
                str(s.get("title") or "")
                for s in slide_dicts
                if isinstance(s, dict)
                and str(s.get("slide_type") or "").lower() not in ("title", "section_divider")
            ]
            user = (
                "Review this deck's slide titles for consulting quality. Return ONLY JSON "
                '{"hints": [{"slide_index": <1-based int>, "instruction": "<fix>"}]} '
                "with at most 4 prescriptive fixes. Titles:\n"
                + json.dumps(titles[:12], ensure_ascii=False)
            )
            obj = claude_generate_json(
                system="You critique executive-deck slide titles. JSON only.",
                user=user,
                model=critique_model(),
                temperature=0.1,
                max_tokens=600,
            )
            for h in (obj.get("hints") if isinstance(obj, dict) else []) or []:
                if isinstance(h, dict) and h.get("instruction"):
                    hints.append({
                        "slide_index": h.get("slide_index"),
                        "instruction": str(h["instruction"]),
                        "source": "llm_critique",
                    })
        except Exception:  # noqa: BLE001, S110 — LLM critique is optional
            pass

    return hints, review


def targeted_slide_rewrite(
    ctx: AgentContext,
    slide_dicts: list[dict[str, Any]],
    hints: list[dict[str, Any]],
    *,
    directive: str = "",
    max_slides: int = 6,
) -> list[dict[str, Any]]:
    """ONE bounded rewrite of only the hint-flagged slides; input on any failure."""
    fix_indices = sorted(
        i for i in pptx_visual_feedback_indices(hints) if 1 <= i <= len(slide_dicts)
    )[:max_slides]
    if not fix_indices:
        return slide_dicts
    fix_set = set(fix_indices)
    by_idx: dict[int, list[str]] = {}
    for h in hints:
        if not isinstance(h, dict):
            continue
        for i in pptx_visual_feedback_indices([h]):
            if i in fix_set and h.get("instruction"):
                by_idx.setdefault(i, []).append(str(h["instruction"]))
    payload = [
        {"slide_index": i, "fix": by_idx.get(i, []), "slide": slide_dicts[i - 1]}
        for i in fix_indices
    ]
    user = (
        (directive + "\n\n" if directive else "")
        + "FLAGGED SLIDES:\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    try:
        obj = claude_generate_json(
            system=_SLIDE_REPAIR_SYSTEM, user=user, temperature=0.2, max_tokens=4096
        )
    except Exception as exc:  # noqa: BLE001 — repair is best-effort
        _LOG.warning("targeted slide rewrite skipped: %s", exc)
        return slide_dicts
    reps = obj.get("slides") if isinstance(obj, dict) else None
    if not isinstance(reps, list) or not reps:
        return slide_dicts
    full = [dict(s) for s in slide_dicts]
    for pos, rep in zip(fix_indices, reps):
        if isinstance(rep, dict) and rep.get("title"):
            rep = dict(rep)
            rep.setdefault("slide_type", slide_dicts[pos - 1].get("slide_type"))
            full[pos - 1] = rep
    merged = merge_pptx_slides_repair(slide_dicts, full, fix_set)
    return normalize_pptx_slide_identities(merged)


def critique_and_repair_pptx(
    ctx: AgentContext, slide_dicts: list[dict[str, Any]], pm: dict[str, Any]
) -> list[dict[str, Any]]:
    """Pre-render critique→revise (1 round) + evidence soft-block (1 round).

    Both stages are flag-gated, bounded, and fail-open — the deck always renders.
    """
    if not isinstance(slide_dicts, list) or not slide_dicts:
        return slide_dicts
    pm_dict = pm if isinstance(pm, dict) else None
    contract = load_run_storyline(ctx)
    source_registry = source_registry_for_ctx(ctx)

    from app.services.otel_tracing import start_span

    with start_span(
        "pptx.critique_and_repair",
        attributes={
            "project_id": str(ctx.project_id or ""),
            "run_id": str(ctx.run_id or ""),
            "slide_count": len(slide_dicts),
            "has_source_registry": bool(source_registry),
        },
    ):
        if getattr(settings, "deliverable_critique_loop_enabled", True):
            try:
                from app.services.design_review import review_deck

                hints, review = critique_slides(ctx, slide_dicts, pm_dict, contract)
                targetable = [h for h in hints if pptx_visual_feedback_indices([h])]
                if targetable:
                    slide_dicts = targeted_slide_rewrite(
                        ctx, slide_dicts, targetable,
                        directive=(
                            "Repair each flagged slide per its fix instructions. Keep the "
                            "slide's argument and evidence; make every title a specific "
                            "assertion, not a topic label."
                        ),
                    )
                    after = review_deck(slide_dicts, pm_dict, contract)
                    if ctx.emit_event:
                        ctx.emit_event("critique_loop", {
                            "output_type": "pptx",
                            "status_before": review.get("status"),
                            "status_after": after.get("status"),
                            "hints_before": len(hints),
                            "hints_after": len(after.get("remediation_hints") or []),
                        })
            except Exception as exc:  # noqa: BLE001 — critique is advisory
                _LOG.warning("pptx critique loop skipped: %s", exc)

        if getattr(settings, "evidence_soft_block_enabled", True):
            try:
                from app.core.evidence_validator import validate_pptx_slides_evidence

                ev = validate_pptx_slides_evidence(slide_dicts, pm_dict, source_registry or None)
                claims_before = int(ev.get("unsupported_claims_count") or 0)
                if claims_before:
                    ev_hints: list[dict[str, Any]] = []
                    all_unsupported: list[dict[str, Any]] = []
                    for i, sv in enumerate(ev.get("slide_validations") or [], start=1):
                        validation = (sv or {}).get("validation") or {}
                        unsupported = validation.get("unsupported_claims") or []
                        if not unsupported:
                            continue
                        all_unsupported.extend(unsupported)
                        claims = ", ".join(claim_text(c) for c in unsupported[:4] if claim_text(c))
                        ev_hints.append({
                            "slide_index": i,
                            "instruction": f"Unsupported figure(s) on this slide: [{claims}].",
                            "source": "evidence",
                        })
                    slide_dicts = targeted_slide_rewrite(
                        ctx, slide_dicts, ev_hints,
                        directive=evidence_remediation_directive(all_unsupported, pm_dict),
                    )
                    ev_after = validate_pptx_slides_evidence(
                        slide_dicts, pm_dict, source_registry or None
                    )
                    if ctx.emit_event:
                        ctx.emit_event("evidence_soft_block", {
                            "output_type": "pptx",
                            "soft_block_applied": True,
                            "claims_before": claims_before,
                            "claims_after": int(ev_after.get("unsupported_claims_count") or 0),
                        })
            except Exception as exc:  # noqa: BLE001 — soft-block never blocks render
                _LOG.warning("pptx evidence soft-block skipped: %s", exc)

        if source_registry:
            try:
                from app.core.evidence_validator import apply_source_citations_to_slides

                slide_dicts = apply_source_citations_to_slides(slide_dicts, source_registry, pm_dict)
            except Exception as exc:  # noqa: BLE001 — citation band is advisory
                _LOG.warning("pptx source citation annotation skipped: %s", exc)

    return slide_dicts


# Backward-compatible private aliases for subagents/tests importing underscore names.
_pptx_visual_feedback_indices = pptx_visual_feedback_indices
_merge_pptx_slides_repair = merge_pptx_slides_repair
_normalize_pptx_slide_identities = normalize_pptx_slide_identities
_evidence_remediation_directive = evidence_remediation_directive
_load_run_storyline = load_run_storyline
_claim_text = claim_text
_source_registry_for_ctx = source_registry_for_ctx
_critique_slides = critique_slides
_targeted_slide_rewrite = targeted_slide_rewrite
_critique_and_repair_pptx = critique_and_repair_pptx
