"""Unified deliverable design-review gate (Deloitte-quality program, Pillar C).

Three advisory checks that previously lived apart — storyline-arc coherence,
action-title discipline (Pillar A), and evidence traceability — are scored
together here and turned into *prescriptive*, per-slide remediation hints that the
retry loop can act on (not just "looks crowded"). The output mirrors the
``remediation_hints`` shape the worker already consumes, plus a ``design_review``
block persisted for auditability.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.core.action_title import classify_title, score_titles
from app.core.evidence_validator import validate_pptx_slides_evidence
from app.core.pptx_schema import RICH_VISUAL_REQUIRED_FIELDS

logger = logging.getLogger(__name__)

# Rich storyline visuals the visual-fidelity gate enforces (the differentiated
# layouts that otherwise silently degrade to card/list/table).
_RICH_VISUALS = frozenset(RICH_VISUAL_REQUIRED_FIELDS)

_STOP = frozenset(
    {"the", "a", "an", "of", "to", "and", "or", "for", "in", "on", "with", "that",
     "this", "our", "their", "its", "is", "are", "we", "by", "at", "as", "from"}
)
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")

_RANK = {"pass": 0, "warn": 1, "fail": 2}
_RANK_INV = {0: "pass", 1: "warn", 2: "fail"}


def _significant(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text or "") if w.lower() not in _STOP and len(w) > 2}


def _content_slides(slides: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    """Return (1-based deck index, slide) for non-title/divider slides."""
    out = []
    for i, s in enumerate(slides):
        if not isinstance(s, dict):
            continue
        st = str(s.get("slide_type") or "").lower()
        if st in ("title", "section_divider"):
            continue
        out.append((i + 1, s))
    return out


def _arc_coherence(slides: list[dict[str, Any]], contract: dict[str, Any] | None) -> dict[str, Any]:
    """Score how well the deck honours the approved storyline spine."""
    spine = (contract or {}).get("slides") if isinstance(contract, dict) else None
    if not isinstance(spine, list) or not spine:
        return {"status": "skip", "score": None, "missing_beats": []}
    deck_titles = [str(s.get("title") or "") for _, s in _content_slides(slides)]
    deck_word_sets = [_significant(t) for t in deck_titles]
    missing: list[str] = []
    matched = 0
    for beat in spine:
        if not isinstance(beat, dict):
            continue
        at = str(beat.get("action_title") or "").strip()
        if not at:
            continue
        bw = _significant(at)
        if bw and any(len(bw & dw) >= 2 for dw in deck_word_sets):
            matched += 1
        else:
            missing.append(at)
    total = sum(1 for b in spine if isinstance(b, dict) and b.get("action_title"))
    score = (matched / total) if total else 1.0
    status = "pass" if score >= 0.7 else "warn" if score >= 0.4 else "fail"
    return {"status": status, "score": round(score, 3), "missing_beats": missing[:8], "matched": matched, "expected": total}


def _field_hint(visual: str) -> str:
    return "fields: " + ", ".join(RICH_VISUAL_REQUIRED_FIELDS.get(visual, ()))


def _rich_fields_ok(visual: str, slide: dict[str, Any]) -> bool:
    """True if the slide carries the inline fields its rich visual needs to render.

    A figure typed correctly but missing its data silently degrades to a bullet
    list at render time (``_compose_figure_slide`` returns False), so we treat a
    missing essential field as a fidelity miss.
    """
    if any(not slide.get(k) for k in RICH_VISUAL_REQUIRED_FIELDS.get(visual, ())):
        return False
    if visual == "process_flow":
        flow = slide.get("process_flow")
        steps = flow.get("steps") if isinstance(flow, dict) else flow
        return isinstance(steps, list) and len(steps) >= 2
    if visual == "roadmap_matrix":
        rm = slide.get("roadmap_matrix")
        return isinstance(rm, dict) and bool(rm.get("periods")) and bool(rm.get("tracks"))
    return True


def _visual_fidelity(slides: list[dict[str, Any]], contract: dict[str, Any] | None) -> dict[str, Any]:
    """Score whether the deck honours the spine's rich ``suggested_visual`` choices.

    Only the rich subset is enforced; near-synonym card/stat/bullet/table churn is
    ignored. A beat that matched no slide is an arc-coherence miss (reported there),
    so it does not count here.
    """
    spine = (contract or {}).get("slides") if isinstance(contract, dict) else None
    if not isinstance(spine, list) or not spine:
        return {"status": "skip", "score": None, "hints": []}
    deck = [
        (idx, str(s.get("slide_type") or "").lower().strip(), _significant(str(s.get("title") or "")), s)
        for idx, s in _content_slides(slides)
    ]
    hints: list[dict[str, Any]] = []
    present = 0
    correct = 0
    for beat in spine:
        if not isinstance(beat, dict):
            continue
        vis = str(beat.get("suggested_visual") or "").strip().lower()
        if vis not in _RICH_VISUALS:
            continue
        bw = _significant(str(beat.get("action_title") or ""))
        match = next(((idx, st, sd) for idx, st, dw, sd in deck if bw and len(bw & dw) >= 2), None)
        if match is None:
            continue
        idx, st, sd = match
        present += 1
        if st != vis:
            hints.append({
                "slide_index": idx,
                "instruction": (
                    f"Slide {idx} should use a `{vis}` layout per the approved storyline "
                    f"(you used `{st or 'an unspecified type'}`). Re-draft as slide_type "
                    f"`{vis}` with {_field_hint(vis)}."
                ),
                "source": "visual_fidelity",
            })
        elif not _rich_fields_ok(vis, sd):
            hints.append({
                "slide_index": idx,
                "instruction": (
                    f"Slide {idx} is typed `{vis}` but is missing the data it needs "
                    f"({_field_hint(vis)}); add it or the slide will fall back to a bullet list."
                ),
                "source": "visual_fidelity",
            })
        else:
            correct += 1
    if present == 0:
        return {"status": "skip", "score": None, "hints": []}
    score = correct / present
    status = "pass" if score >= 0.7 else "warn" if score >= 0.4 else "fail"
    return {"status": status, "score": round(score, 3), "correct": correct, "present": present, "hints": hints}


# Celebrating the *absence* of decision/governance/approval gates as a benefit —
# a red flag for regulated (BFSI) audiences, not a win.
_ZERO_GOV_RE = re.compile(
    r"\b(?:zero|no|0|eliminat\w*|without|remov\w*)\b[^.\n]{0,40}\b"
    r"(?:decision|governance|approval|control|oversight|gate|bottleneck|checkpoint)s?\b",
    re.I,
)


def _all_strings(obj: Any) -> list[str]:
    """Recursively collect every string in a nested dict/list payload."""
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _all_strings(v)]
    if isinstance(obj, list):
        return [s for v in obj for s in _all_strings(v)]
    return []


# Internal authoring/pipeline grammar that must never reach a client deliverable —
# the wiki-link syntax and bookkeeping filenames that garbled the value-chain figure
# and leaked into the process narrative. ``humanize_wiki_links`` should strip these
# before render; this gate flags any that slip through.
_MARKUP_LEAK_RE = re.compile(
    r"\[\[|\]\]|\bwiki://|\blp://|\bindex\.md\b|\blog\.md\b|\bpage_id\b|\bproject_id\b",
    re.I,
)


def _markup_leak(slides: list[dict[str, Any]]) -> dict[str, Any]:
    """Flag slides whose client-facing text still carries internal wiki/pipeline markup."""
    hits: list[dict[str, Any]] = []
    for idx, s in _content_slides(slides):
        leaked = sorted({
            m.group(0).lower()
            for txt in _all_strings(s)
            for m in _MARKUP_LEAK_RE.finditer(txt)
        })
        if leaked:
            hits.append({
                "slide_index": idx,
                "instruction": (
                    f"Slide {idx} leaks internal authoring markup ({', '.join(leaked)}) into "
                    "client-facing text. Run it through humanize_wiki_links: render '[[id|Title]]' "
                    "as 'Title' and drop wiki://, lp://, index.md and log.md tokens."
                ),
                "source": "markup_leak",
            })
    status = "fail" if hits else "pass"
    return {"status": status, "flagged": len(hits), "hints": hits}


def _governance_framing(slides: list[dict[str, Any]]) -> dict[str, Any]:
    """Flag slides that sell the absence of governance/decision gates as a benefit."""
    hits: list[dict[str, Any]] = []
    for idx, s in _content_slides(slides):
        blob = " ".join(_all_strings(s))
        if _ZERO_GOV_RE.search(blob):
            hits.append({
                "slide_index": idx,
                "instruction": (
                    f"Slide {idx} frames the absence of decision/governance gates as a benefit. "
                    "For regulated (e.g. BFSI) audiences this reads as a controls red flag — "
                    "reframe as automation/cycle-time gain and retain auditability/controls language, "
                    "or call out where human review still applies."
                ),
                "source": "governance_framing",
            })
    status = "warn" if hits else "pass"
    return {"status": status, "flagged": len(hits), "hints": hits}


def review_deck(
    slides: list[dict[str, Any]],
    process_model: dict[str, Any] | None = None,
    storyline_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the three checks and emit a scored, prescriptive design review."""
    slides = [s for s in (slides or []) if isinstance(s, dict)]
    content = _content_slides(slides)
    hints: list[dict[str, Any]] = []

    # 1) Action-title discipline ------------------------------------------------
    titles = [str(s.get("title") or "") for _, s in content]
    tscore, titles_pass = score_titles(titles)
    title_idx = {str(s.get("title") or ""): idx for idx, s in content}
    for bad in tscore.label_titles:
        hints.append({
            "slide_index": title_idx.get(bad, 0),
            "instruction": (
                f"Rewrite the title “{bad}” as an action title: a full assertion with a "
                "verb and a specific, sourced claim (e.g. 'Manual hand-offs add 11 days to every close')."
            ),
            "source": "action_title",
        })
    titles_status = "pass" if titles_pass else ("warn" if tscore.label_ratio <= 0.4 else "fail")

    # 2) Evidence traceability --------------------------------------------------
    ev = validate_pptx_slides_evidence(slides, process_model)
    for sv in ev.get("slide_validations", []):
        unsupported = (sv.get("validation") or {}).get("unsupported_claims") or []
        if not unsupported:
            continue
        idx = title_idx.get(str(sv.get("slide_title") or ""), 0)
        claims = ", ".join(str(c) for c in unsupported[:4])
        hints.append({
            "slide_index": idx,
            "instruction": (
                f"Source or qualify the unsupported figure(s) [{claims}] — tie each to the process "
                "model/evidence, or label it 'estimated'/'illustrative'. Never assert an unsourced number."
            ),
            "source": "evidence",
        })

    # 3) Arc coherence ----------------------------------------------------------
    arc = _arc_coherence(slides, storyline_contract)
    for beat in arc.get("missing_beats", []):
        hints.append({
            "slide_index": 0,
            "instruction": f"The approved storyline beat is unaddressed — add or align a slide for: “{beat}”.",
            "source": "arc_coherence",
        })

    # 4) Visual fidelity --------------------------------------------------------
    visual = _visual_fidelity(slides, storyline_contract)
    hints.extend(visual.get("hints", []))

    # 5) Governance framing -----------------------------------------------------
    governance = _governance_framing(slides)
    hints.extend(governance.get("hints", []))

    # 6) Internal-markup leak ---------------------------------------------------
    markup = _markup_leak(slides)
    hints.extend(markup.get("hints", []))

    # Overall status = worst of the checks (skips ignored) ---------------------
    statuses = [titles_status, ev.get("status", "skip"), arc.get("status", "skip"),
                visual.get("status", "skip"), governance.get("status", "skip"),
                markup.get("status", "skip")]
    rank = max((_RANK.get(s, 0) for s in statuses if s in _RANK), default=0)
    overall = _RANK_INV[rank]

    summary = (
        f"Action titles: {tscore.assertions}/{tscore.total} assertions "
        f"({int(tscore.label_ratio*100)}% labels); evidence: {ev.get('unsupported_claims_count', 0)} unsupported; "
        f"arc: {arc.get('matched', 0)}/{arc.get('expected', 0)} beats; "
        f"visuals: {visual.get('correct', 0)}/{visual.get('present', 0)} rich."
    )
    return {
        "status": overall,
        "summary": summary,
        "scores": {
            "action_titles": {"status": titles_status, "label_ratio": tscore.label_ratio,
                              "assertions": tscore.assertions, "total": tscore.total},
            "evidence": {"status": ev.get("status"), "unsupported": ev.get("unsupported_claims_count", 0),
                         "total_claims": ev.get("total_claims", 0)},
            "arc_coherence": arc,
            "visual_fidelity": visual,
            "governance_framing": governance,
            "markup_leak": markup,
        },
        "remediation_hints": hints,
    }
