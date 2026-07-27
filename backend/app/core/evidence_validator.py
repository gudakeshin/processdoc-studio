"""Evidence validation for metric claims in PPTX slides.

Ensures numeric metrics, ROI, savings, and business-value claims come from
retrieved source documents, explicit user instruction, or labeled assumptions.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.core.source_chunks import (
    chunk_text,
    citation_label,
    extract_numeric_tokens,
    normalize_numeric,
)

logger = logging.getLogger(__name__)

# Patterns that suggest business impact claims
BUSINESS_CLAIM_PATTERNS = {
    r"\$[\d,]+(?:\.\d+)?[MKBmkb]?": "Financial value",
    r"\d+(?:\.\d+)?%": "Percentage metric",
    r"(\d+)\s*%\s*(increase|decrease|reduction|improvement)": "Percentage improvement",
    r"(ROI|savings|cost|revenue|profit)": "Business metric",
    r"(\d+)\s+(FTE|employees|staff|headcount)": "Staffing impact",
    r"(\d+)\s+(days?|weeks?|months?)": "Timeline",
}

ACCEPTABLE_ASSUMPTIONS = {
    "estimated",
    "expected",
    "projected",
    "potential",
    "approximately",
    "approx",
    "~",
    "±",
    "assumption",
    "assumed",
}

_NUMERIC_REL_TOLERANCE = 0.005


def extract_numeric_claims(text: str) -> list[dict[str, Any]]:
    """Extract numeric claims and metrics from text."""
    claims: list[dict[str, Any]] = []
    seen: set[str] = set()

    for pattern, claim_type in BUSINESS_CLAIM_PATTERNS.items():
        for match in re.finditer(pattern, text, re.IGNORECASE):
            value = match.group()
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            start = max(0, match.start() - 50)
            end = min(len(text), match.end() + 50)
            context = text[start:end].lower()
            has_assumption = any(asm in context for asm in ACCEPTABLE_ASSUMPTIONS)
            claims.append({
                "value": value,
                "type": claim_type,
                "context": context,
                "has_assumption_label": has_assumption,
            })
    return claims


def _numbers_close(a: float, b: float) -> bool:
    if a == b:
        return True
    denom = max(abs(a), abs(b), 1.0)
    return abs(a - b) / denom <= _NUMERIC_REL_TOLERANCE


def _build_evidence_from_source_chunks(source_chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Index numeric tokens from retrieved client-document chunks."""
    entries: list[dict[str, Any]] = []
    for chunk in source_chunks:
        if not isinstance(chunk, dict):
            continue
        text = chunk_text(chunk)
        if not text:
            continue
        for tok in extract_numeric_tokens(text):
            norm = normalize_numeric(tok)
            if norm is None:
                continue
            entries.append({
                "value": tok,
                "normalized": norm,
                "source_id": chunk.get("source_id"),
                "filename": chunk.get("filename"),
                "sheet": chunk.get("sheet"),
                "page": chunk.get("page"),
                "citation": citation_label(chunk),
                "excerpt": text[:240],
            })
    return entries


def _build_evidence_map(
    process_model: dict[str, Any] | None,
    user_instructions: str,
    source_references: list[str] | None,
    source_chunks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a searchable map of available evidence."""
    evidence: dict[str, Any] = {
        "metrics": [],
        "numbers": [],
        "source_entries": _build_evidence_from_source_chunks(source_chunks or []),
        "sources": source_references or [],
        "instructions": user_instructions or "",
    }

    if not process_model:
        return evidence

    if "kpis" in process_model and isinstance(process_model["kpis"], list):
        for kpi in process_model["kpis"]:
            if isinstance(kpi, dict):
                if "value" in kpi:
                    evidence["metrics"].append(str(kpi["value"]))
                if "target" in kpi:
                    evidence["numbers"].append(str(kpi["target"]))

    if "financials" in process_model and isinstance(process_model["financials"], dict):
        for value in process_model["financials"].values():
            if isinstance(value, (int, float)):
                evidence["numbers"].append(str(value))

    if "scale" in process_model:
        scale_str = json.dumps(process_model["scale"])
        for tok in extract_numeric_tokens(scale_str):
            evidence["numbers"].append(tok)

    return evidence


def _find_evidence_for_claim(claim_value: str, evidence_map: dict[str, Any]) -> dict[str, Any] | None:
    """Return matching provenance when a claim is grounded, else None."""
    claim_norm = normalize_numeric(claim_value)
    claim_lower = claim_value.lower()

    # Primary: retrieved client source chunks.
    for entry in evidence_map.get("source_entries") or []:
        if not isinstance(entry, dict):
            continue
        excerpt = str(entry.get("excerpt") or "")
        # Avoid spurious substring passes ("1" inside "1200").
        if claim_lower and len(re.sub(r"[^\d]", "", claim_lower)) <= 1:
            pass
        elif claim_lower and claim_lower in excerpt.lower():
            return {
                "source_id": entry.get("source_id"),
                "citation": entry.get("citation"),
                "match_type": "verbatim",
            }
        entry_norm = entry.get("normalized")
        if claim_norm is not None and isinstance(entry_norm, (int, float)):
            if _numbers_close(float(claim_norm), float(entry_norm)):
                return {
                    "source_id": entry.get("source_id"),
                    "citation": entry.get("citation"),
                    "match_type": "numeric",
                }

    if claim_value in evidence_map.get("metrics", []):
        return {"match_type": "process_model_metric"}

    if claim_norm is not None:
        for num_str in evidence_map.get("numbers", []):
            num_norm = normalize_numeric(str(num_str))
            if num_norm is not None and _numbers_close(float(claim_norm), float(num_norm)):
                return {"match_type": "process_model_number"}

    for ref in evidence_map.get("sources") or []:
        if claim_lower and claim_lower in str(ref).lower():
            return {"match_type": "source_ref", "citation": str(ref)}

    instructions = str(evidence_map.get("instructions") or "")
    if claim_lower and claim_lower in instructions.lower():
        return {"match_type": "speaker_notes"}

    return None


def validate_claims_against_evidence(
    claims: list[dict[str, Any]],
    process_model: dict[str, Any] | None,
    user_instructions: str = "",
    source_references: list[str] | None = None,
    source_chunks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate claimed metrics against evidence sources."""
    if not claims:
        return {
            "status": "pass",
            "unsupported_claims": [],
            "assumptions_needing_labels": [],
            "grounded_claims": [],
            "evidence_coverage": 100,
            "remediation": [],
        }

    evidence_map = _build_evidence_map(
        process_model, user_instructions, source_references, source_chunks
    )
    unsupported: list[dict[str, Any]] = []
    grounded: list[dict[str, Any]] = []
    needs_labels: list[dict[str, Any]] = []

    for claim in claims:
        claim_value = claim["value"]
        match = _find_evidence_for_claim(claim_value, evidence_map)

        if match:
            grounded.append({"claim": claim_value, **match})
            continue

        if claim["has_assumption_label"]:
            needs_labels.append({
                "claim": claim_value,
                "type": claim.get("type", "Unknown"),
                "context": claim.get("context", ""),
            })
            continue

        unsupported.append({
            "claim": claim_value,
            "type": claim.get("type", "Unknown"),
            "context": claim.get("context", ""),
        })

    coverage = ((len(claims) - len(unsupported)) / len(claims)) * 100 if claims else 100

    if len(unsupported) > len(claims) * 0.2:
        status = "fail"
    elif unsupported:
        status = "warn"
    else:
        status = "pass"

    remediation = _generate_remediation(unsupported, process_model, bool(source_chunks))

    return {
        "status": status,
        "unsupported_claims": unsupported,
        "assumptions_needing_labels": needs_labels,
        "grounded_claims": grounded,
        "evidence_coverage": round(coverage, 1),
        "remediation": remediation,
    }


def _generate_remediation(
    unsupported_claims: list[dict[str, Any]],
    process_model: dict[str, Any] | None,
    has_source_chunks: bool = False,
) -> list[str]:
    if not unsupported_claims:
        return []

    suggestions = [
        "Remove unsupported metrics or cite the matching source chunk in speaker notes",
        "Add explicit assumption labels (e.g., 'estimated', 'projected') for unsubstantiated figures",
        "Include 'Source: <filename, sheet/page>' in slide notes for every numeric claim",
    ]
    if has_source_chunks:
        suggestions.append("Use values present in retrieved source documents ([S#] markers in context)")
    elif process_model:
        suggestions.append("Verify metrics align with ProcessModel KPIs and financials")
    return suggestions


def validate_slide_evidence(
    slide: dict[str, Any],
    process_model: dict[str, Any] | None = None,
    source_chunks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate evidence for a single slide."""
    text_parts: list[str] = []

    for key in ("title", "subtitle", "description", "context"):
        if key in slide and slide[key]:
            text_parts.append(str(slide[key]))

    if "stat_cards" in slide and isinstance(slide["stat_cards"], list):
        for card in slide["stat_cards"]:
            if isinstance(card, dict):
                text_parts.extend(
                    str(card.get(k))
                    for k in ("stat", "label", "description")
                    if card.get(k)
                )

    if "bullets" in slide and isinstance(slide["bullets"], list):
        text_parts.extend(str(b) for b in slide["bullets"] if b)

    combined_text = " ".join(text_parts)
    notes = " ".join(
        str(slide.get(key) or "") for key in ("notes", "speaker_notes")
    ).strip()

    claims = extract_numeric_claims(combined_text)
    validation = validate_claims_against_evidence(
        claims,
        process_model,
        notes,
        slide.get("source_refs", []),
        source_chunks,
    )

    return {
        "slide_title": slide.get("title", "Untitled"),
        "slide_type": slide.get("slide_type", "unknown"),
        "claims_found": len(claims),
        "validation": validation,
    }


def validate_text_evidence(
    text: str,
    process_model: dict[str, Any] | None = None,
    source_chunks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    claims = extract_numeric_claims(text or "")
    validation = validate_claims_against_evidence(
        claims, process_model, source_chunks=source_chunks
    )
    return {"claims_found": len(claims), "validation": validation}


def validate_pptx_slides_evidence(
    pptx_slides: list[dict[str, Any]],
    process_model: dict[str, Any] | None = None,
    source_chunks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate evidence across all slides."""
    slide_validations: list[dict[str, Any]] = []
    total_claims = 0
    unsupported_count = 0

    for slide in pptx_slides:
        result = validate_slide_evidence(slide, process_model, source_chunks)
        slide_validations.append(result)
        total_claims += result["claims_found"]
        unsupported_count += len(result["validation"].get("unsupported_claims", []))

    if unsupported_count > 0:
        status = "fail" if unsupported_count > total_claims * 0.2 else "warn"
    else:
        status = "pass"

    return {
        "status": status,
        "total_slides": len(pptx_slides),
        "total_claims": total_claims,
        "unsupported_claims_count": unsupported_count,
        "slide_validations": slide_validations,
        "summary": (
            f"{total_claims} claims found; {unsupported_count} unsupported "
            f"({(unsupported_count / total_claims * 100 if total_claims else 0):.1f}%)"
        ),
    }


def load_source_registry(payload: dict[str, Any], run_dir: Any | None = None) -> list[dict[str, Any]]:
    """Load source chunk registry from run payload or compaction snapshot on disk."""
    registry: list[dict[str, Any]] = []
    snap = payload.get("compaction_snapshot")
    if isinstance(snap, dict):
        top = snap.get("source_registry")
        if isinstance(top, list):
            registry = [c for c in top if isinstance(c, dict)]
            if registry:
                return registry
        prov = snap.get("context_provenance")
        if isinstance(prov, dict) and isinstance(prov.get("source_registry"), list):
            registry = [c for c in prov["source_registry"] if isinstance(c, dict)]
    if registry:
        return registry
    if run_dir is not None:
        from pathlib import Path
        import json as _json

        path = Path(run_dir) / "compaction_snapshot.json"
        if path.is_file():
            try:
                data = _json.loads(path.read_text(encoding="utf-8"))
                prov = data.get("context_provenance") if isinstance(data, dict) else None
                if isinstance(prov, dict) and isinstance(prov.get("source_registry"), list):
                    return [c for c in prov["source_registry"] if isinstance(c, dict)]
            except Exception as exc:  # noqa: BLE001 — best-effort load
                logger.debug("could not load source_registry from %s: %s", path, exc)
    return []
