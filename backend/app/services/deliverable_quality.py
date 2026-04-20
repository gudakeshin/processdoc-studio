"""
Contract-driven deliverable critique, scoring, and revision orchestration.

Evaluators and weights are loaded from quality contract JSON — not hardcoded here.
"""

from __future__ import annotations

import contextlib
import json
import re
from collections.abc import Callable
from typing import Any

from app.core.config import settings
from app.core.quality_framework import UnifiedQualityFramework
from app.services.claude import claude_generate_json, is_claude_enabled
from app.services.langfuse_tracing import langfuse_span
from app.services.observability import increment
from app.services.quality_contract_registry import contract_for_outputs


# Phase 1 fix: PPTX completeness validation
def _validate_pptx_completeness(pptx_json: str) -> tuple[bool, list[str]]:
    """
    Check that PPTX slides have required content (not just titles).
    Returns (is_complete, issues_list).

    Handles both formats:
    - {"slides": [...]} (dict format)
    - [...] (list format, direct array)
    """
    issues = []
    try:
        parsed = json.loads(pptx_json)
    except json.JSONDecodeError:
        return False, ["Invalid JSON in pptx_slides"]

    # Handle both dict format {"slides": [...]} and list format [...]
    if isinstance(parsed, dict):
        slides = parsed.get("slides", [])
    elif isinstance(parsed, list):
        slides = parsed
    else:
        return False, ["pptx_slides must be a dict with 'slides' key or a list"]

    if not isinstance(slides, list):
        return False, ["pptx_slides 'slides' must be a list"]

    if not slides:
        return False, ["pptx_slides has no slides"]

    slide_type_requirements = {
        "stat_cards": ("stat_cards", 3),
        "column_cards": ("column_cards", 3),
        "stack_layers": ("stack_layers", 3),
        "table": ("table", 1),
        "bullets": ("bullets", 1),
    }

    for idx, slide in enumerate(slides):
        if not isinstance(slide, dict):
            continue

        slide_type = slide.get("slide_type")
        title = slide.get("title", f"[Slide {idx + 1}]")

        if slide_type in slide_type_requirements:
            field, min_items = slide_type_requirements[slide_type]
            items = slide.get(field, [])

            if not isinstance(items, list) or len(items) < min_items:
                actual = len(items) if isinstance(items, list) else 0
                issues.append(
                    f"Slide {idx + 1} ({title}): "
                    f"slide_type='{slide_type}' requires {min_items} {field}, got {actual}"
                )

    return len(issues) == 0, issues


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", errors="replace")
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _flatten_for_eval(output_key: str, raw: Any) -> str:
    text = _to_text(raw)
    if output_key != "pptx_slides":
        return text
    try:
        parsed = json.loads(text) if text.strip().startswith("{") else None
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict) and isinstance(parsed.get("slides"), list):
        parts: list[str] = []
        for sl in parsed["slides"]:
            if not isinstance(sl, dict):
                continue
            title = str(sl.get("title") or "").strip()
            body = str(sl.get("body") or sl.get("content") or "").strip()
            if title:
                parts.append(title)
            if body:
                parts.append(body)
        return "\n".join(parts)
    return text


def _fuzzy_title_match(required: str, candidate: str, threshold: float = 0.65) -> bool:
    """
    Fuzzy match a required section name against a candidate title.
    Handles common variations like '&' vs 'and', extra words, reordering.
    Returns True if the candidate is a close-enough match for the required section.
    """
    req = required.lower().strip()
    cand = candidate.lower().strip()
    # Exact substring match
    if req in cand or cand in req:
        return True
    # Normalize '&' / 'and', common punctuation
    for old, new in [("&", "and"), ("–", "-"), ("—", "-")]:
        req = req.replace(old, new)
        cand = cand.replace(old, new)
    if req in cand or cand in req:
        return True
    # Word-overlap ratio (handles reordering and partial matches)
    req_words = set(re.split(r"\W+", req)) - {"", "the", "a", "an", "of", "for", "in", "on", "to"}
    cand_words = set(re.split(r"\W+", cand)) - {"", "the", "a", "an", "of", "for", "in", "on", "to"}
    if not req_words:
        return True
    overlap = len(req_words & cand_words) / len(req_words)
    return overlap >= threshold


def _score_section_coverage_pptx(slides_raw: Any, dim: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    """
    Evaluate section coverage against PPTX slide structure directly (not flattened text).
    Uses fuzzy title matching to handle variations like 'Current State & Problem Statement'
    vs 'Current State and Problem Statement'.
    """
    required = dim.get("required_sections")
    if not isinstance(required, list) or not required:
        return 1.0, {"missing": []}

    # Parse slides from raw value
    slides: list[dict] = []
    if isinstance(slides_raw, list):
        slides = [s for s in slides_raw if isinstance(s, dict)]
    elif isinstance(slides_raw, str):
        try:
            parsed = json.loads(slides_raw)
            if isinstance(parsed, dict) and isinstance(parsed.get("slides"), list):
                slides = [s for s in parsed["slides"] if isinstance(s, dict)]
            elif isinstance(parsed, list):
                slides = [s for s in parsed if isinstance(s, dict)]
        except (json.JSONDecodeError, TypeError):
            pass

    # Collect all slide titles and bullet/body text for matching
    slide_titles = [str(s.get("title") or "").strip() for s in slides if s.get("title")]

    missing: list[str] = []
    matched_pairs: list[dict[str, str]] = []
    for sec in required:
        label = str(sec).strip()
        if not label:
            continue
        found = False
        for title in slide_titles:
            if _fuzzy_title_match(label, title):
                matched_pairs.append({"required": label, "matched_to": title})
                found = True
                break
        if not found:
            missing.append(label)

    total = len([s for s in required if str(s).strip()])
    if total == 0:
        return 1.0, {"missing": []}
    hit = total - len(missing)
    return hit / total, {
        "missing": missing,
        "required_total": total,
        "matched": hit,
        "matched_pairs": matched_pairs,
    }


def _score_section_coverage(text: str, dim: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    required = dim.get("required_sections")
    if not isinstance(required, list) or not required:
        return 1.0, {"missing": []}
    norm = text.lower()
    missing: list[str] = []
    for sec in required:
        label = str(sec).strip()
        if not label:
            continue
        escaped = re.escape(label.lower())
        if re.search(rf"^#+\s*{escaped}\s*$", norm, flags=re.MULTILINE):
            continue
        if label.lower() in norm:
            continue
        missing.append(label)
    total = len([s for s in required if str(s).strip()])
    if total == 0:
        return 1.0, {"missing": []}
    hit = total - len(missing)
    return hit / total, {"missing": missing, "required_total": total, "matched": hit}


def _score_citation_density(text: str, dim: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    patterns = dim.get("patterns")
    if not isinstance(patterns, list):
        patterns = []
    min_m = int(dim.get("min_markers") or 1)
    count = 0
    for p in patterns:
        try:
            count += len(re.findall(str(p), text, flags=re.IGNORECASE))
        except re.error:
            continue
    score = min(1.0, float(count) / float(max(1, min_m)))
    return score, {"marker_count": count, "min_markers": min_m}


def _score_llm_critique(text: str, dim: dict[str, Any], *, project_id: str | None) -> tuple[float, dict[str, Any]]:
    rubric = str(dim.get("rubric") or "").strip()
    if not rubric:
        return 1.0, {"skipped": True}
    if not is_claude_enabled() or len(text.strip()) < 80:
        return 0.78, {"fallback": True, "note": "claude_disabled_or_short"}
    user = (
        "Rate the deliverable against the rubric. Return strict JSON: "
        '{"score": number between 0 and 1, "issues": string[]}.\n\n'
        f"Rubric:\n{rubric}\n\nDeliverable:\n{text[:12000]}"
    )
    try:
        res = claude_generate_json(
            system="You are an expert editorial reviewer. Return JSON only.",
            user=user,
        )
        sc = float(res.get("score", 0.65)) if isinstance(res, dict) else 0.65
        sc = max(0.0, min(1.0, sc))
        issues = res.get("issues") if isinstance(res, dict) else []
        if not isinstance(issues, list):
            issues = []
        return sc, {"issues": [str(i) for i in issues if str(i).strip()][:12]}
    except Exception:
        return 0.7, {"error": True}


def _evaluate_one_output(
    output_key: str,
    raw_text: Any,
    contract: dict[str, Any],
    *,
    project_id: str | None,
) -> dict[str, Any]:
    text = _flatten_for_eval(output_key, raw_text)
    dims_in = contract.get("dimensions")
    if not isinstance(dims_in, list):
        dims_in = []
    dimension_results: list[dict[str, Any]] = []
    agg = 0.0
    wsum = 0.0
    for dim in dims_in:
        if not isinstance(dim, dict):
            continue
        kind = str(dim.get("kind") or "").strip().lower()
        weight = float(dim.get("weight") or 0)
        if weight <= 0:
            continue
        did = str(dim.get("id") or kind)
        if kind == "section_coverage":
            # Use structural JSON matching for PPTX slides instead of flat text
            if output_key == "pptx_slides":
                score, meta = _score_section_coverage_pptx(raw_text, dim)
            else:
                score, meta = _score_section_coverage(text, dim)
        elif kind == "citation_density":
            score, meta = _score_citation_density(text, dim)
        elif kind == "llm_critique":
            score, meta = _score_llm_critique(text, dim, project_id=project_id)
        else:
            continue
        dimension_results.append({"id": did, "kind": kind, "weight": weight, "score": score, "meta": meta})
        agg += weight * score
        wsum += weight
    aggregate = (agg / wsum) if wsum > 0 else 1.0
    threshold = float(contract.get("pass_threshold") or 0.72)
    return {
        "output_key": output_key,
        "contract_id": contract.get("_contract_id"),
        "aggregate_score": round(aggregate, 4),
        "pass_threshold": threshold,
        "passed": aggregate >= threshold,
        "dimensions": dimension_results,
    }


def _build_remediation(
    eval_summary: dict[str, Any],
    *,
    threshold: float,
) -> dict[str, Any] | None:
    """Shape compatible with coordinator._apply_qa_remediation."""
    out_key = str(eval_summary.get("output_key") or "")
    if not out_key:
        return None
    actions: list[str] = []
    for d in eval_summary.get("dimensions") or []:
        if not isinstance(d, dict):
            continue
        if float(d.get("score") or 0) >= 0.85:
            continue
        kind = str(d.get("kind") or "")
        meta = d.get("meta") if isinstance(d.get("meta"), dict) else {}
        if kind == "section_coverage":
            miss = meta.get("missing") if isinstance(meta.get("missing"), list) else []
            if miss:
                actions.append("Restore required sections: " + ", ".join(str(m) for m in miss[:8]))
        elif kind == "citation_density":
            actions.append("Add explicit citations, source markers, or [TBC] for unstated quantities per contract.")
        elif kind == "llm_critique":
            iss = meta.get("issues") if isinstance(meta.get("issues"), list) else []
            for i in iss[:5]:
                actions.append(str(i))
    if not actions:
        actions.append(f"Strengthen deliverable to exceed quality aggregate {threshold:.2f}.")
    return {
        out_key: {
            "reason": f"Deliverable quality aggregate {eval_summary.get('aggregate_score')} below {threshold}.",
            "target_score": threshold,
            "actions": actions,
            "rewrite_prompt": (
                f"Revise {out_key} to satisfy the registered deliverable quality contract "
                f"(threshold {threshold:.2f}). Address: " + " | ".join(actions[:6])
            ),
        }
    }


def run_deliverable_quality_loop(
    *,
    state: dict[str, Any],
    wanted: list[str],
    outputs: dict[str, Any],
    apply_remediation: Callable[..., dict[str, str]],
    emit_event: Callable[[str, dict[str, Any]], None] | None,
    project_id: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """
    Critique + optional revision using contract evaluators.
    Returns (report, outputs) — outputs may be refreshed after agent reruns.
    """
    if not getattr(settings, "deliverable_quality_enabled", True):
        return None, outputs

    skill_card = state.get("skill_card")
    primary = skill_card.get("primary_skill_by_output_type") if isinstance(skill_card, dict) else None
    if not isinstance(primary, dict):
        return None, outputs

    contracts_by_key = contract_for_outputs(primary_skills_by_output=primary, wanted=wanted)
    if not contracts_by_key:
        return None, outputs

    settings_cap = max(1, min(5, int(getattr(settings, "deliverable_quality_max_revision_rounds", 2) or 2)))
    contract_caps: list[int] = []
    for c in contracts_by_key.values():
        if not isinstance(c, dict):
            continue
        raw_m = c.get("max_revision_rounds")
        if raw_m is None:
            continue
        try:
            contract_caps.append(max(1, min(5, int(float(raw_m)))))
        except (TypeError, ValueError):
            continue
    max_rounds = min(settings_cap, min(contract_caps) if contract_caps else settings_cap)

    working = dict(outputs)
    rounds_meta: list[dict[str, Any]] = []
    unified_framework = UnifiedQualityFramework() if bool(getattr(settings, "enable_unified_quality_framework", False)) else None

    # Load contract-based rules into framework
    if unified_framework is not None and contracts_by_key:
        unified_framework.add_contract_rules(contracts_by_key)

    increment("deliverable_quality_runs_total")

    for rnd in range(max_rounds):
        per_output: dict[str, Any] = {}
        gated_failures: dict[str, Any] = {}
        for ok, raw in working.items():
            contract = contracts_by_key.get(ok)
            if not contract:
                continue
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                continue

            # PPTX completeness check: before quality evaluation
            if ok == "pptx_slides" and isinstance(raw, str):
                is_complete, issues = _validate_pptx_completeness(raw)
                if not is_complete:
                    # Log completeness failures and fail this slide type
                    for _issue in issues:
                        increment("deliverable_quality_pptx_incomplete")
                    gated_failures[ok] = {
                        "reason": f"PPTX completeness check failed: {len(issues)} slides incomplete",
                        "target_score": 0.85,
                        "actions": issues,
                        "rewrite_prompt": (
                            f"Regenerate pptx_slides: {'; '.join(issues[:3])}. "
                            f"Ensure stat_cards/column_cards/stack_layers/table have required items."
                        ),
                    }
                    continue

            ev = _evaluate_one_output(ok, raw, contract, project_id=project_id)
            if unified_framework is not None:
                output_type = ok.replace("_markdown", "").replace("_slides", "")
                uf = unified_framework.evaluate_deliverable(
                    output_type=output_type,
                    text=str(raw or ""),
                    metadata={},
                    context={},
                )
                ev["unified_quality"] = uf
            per_output[ok] = ev
            thr = float(contract.get("pass_threshold") or 0.72)
            if not ev.get("passed"):
                rem = _build_remediation(ev, threshold=thr)
                if rem:
                    gated_failures.update(rem)

        rounds_meta.append({"round": rnd + 1, "evaluations": per_output})
        expected = {k for k in contracts_by_key if k in working and working.get(k) not in (None, "")}
        if expected and set(per_output.keys()) != expected:
            all_pass = False
        else:
            all_pass = all(
                bool(isinstance(per_output.get(k), dict) and per_output[k].get("passed")) for k in expected
            )

        if emit_event:
            with contextlib.suppress(Exception):
                emit_event(
                    "deliverable_quality",
                    {
                        "iteration": rnd + 1,
                        "passed": all_pass,
                        "evaluations": per_output,
                    },
                )

        increment("deliverable_quality_rounds_total")
        if all_pass:
            increment("deliverable_quality_pass_total")
            if project_id:
                langfuse_span(
                    trace_id=str(project_id),
                    name="deliverable_quality.complete",
                    input_payload={"rounds": rnd + 1},
                    output_payload={"passed": True},
                )
            report = {
                "passed": True,
                "iterations": rnd + 1,
                "rounds": rounds_meta,
                "contracts": list({str(c.get("_contract_id")) for c in contracts_by_key.values()}),
            }
            return report, working

        if not gated_failures:
            increment("deliverable_quality_fail_total")
            break

        working = apply_remediation(state, wanted, gated_failures)

    increment("deliverable_quality_fail_total")
    if project_id:
        langfuse_span(
            trace_id=str(project_id),
            name="deliverable_quality.complete",
            input_payload={"rounds": len(rounds_meta)},
            output_payload={"passed": False},
        )
    return (
        {
            "passed": False,
            "iterations": len(rounds_meta),
            "rounds": rounds_meta,
            "contracts": list({str(c.get("_contract_id")) for c in contracts_by_key.values()}),
        },
        working,
    )
