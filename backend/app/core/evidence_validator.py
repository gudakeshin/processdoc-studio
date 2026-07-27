"""Evidence validation for metric claims in PPTX slides.

Ensures numeric metrics, ROI, savings, and business-value claims come from
ProcessModel, uploaded/source context, or explicit user instruction.
Flags inferred/fabricated numbers unless labeled as assumptions.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Patterns that suggest business impact claims
BUSINESS_CLAIM_PATTERNS = {
    r"\$[\d,]+[MK]?": "Financial value",
    r"\d+%": "Percentage metric",
    r"(\d+)\s*%\s*(increase|decrease|reduction|improvement)": "Percentage improvement",
    r"(ROI|savings|cost|revenue|profit)": "Business metric",
    r"(\d+)\s+(FTE|employees|staff|headcount)": "Staffing impact",
    r"(\d+)\s+(days?|weeks?|months?)": "Timeline",
}

# Common assumptions that are acceptable without hard evidence
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


def extract_numeric_claims(text: str) -> list[dict[str, Any]]:
    """Extract numeric claims and metrics from text.

    Returns list of {
        "value": matched text,
        "type": claim type,
        "has_assumption_label": bool,
    }
    """
    claims = []
    lower_text = text.lower()

    for pattern, claim_type in BUSINESS_CLAIM_PATTERNS.items():
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            value = match.group()
            # Check if nearby text indicates this is an assumption
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


def validate_claims_against_evidence(
    claims: list[dict[str, Any]],
    process_model: dict[str, Any] | None,
    user_instructions: str = "",
    source_references: list[str] | None = None
) -> dict[str, Any]:
    """Validate claimed metrics against evidence sources.

    Returns: {
        "status": "pass" | "warn" | "fail",
        "unsupported_claims": list of unsubstantiated claims,
        "assumptions_needing_labels": list of claims without explicit labels,
        "evidence_coverage": percentage of claims with evidence,
        "remediation": suggested fixes,
    }
    """
    if not claims:
        return {
            "status": "pass",
            "unsupported_claims": [],
            "assumptions_needing_labels": [],
            "evidence_coverage": 100,
            "remediation": [],
        }

    evidence_map = _build_evidence_map(process_model, user_instructions, source_references)
    unsupported = []
    needs_labels = []

    for claim in claims:
        claim_value = claim["value"]
        has_evidence = _find_evidence_for_claim(claim_value, evidence_map)

        if not has_evidence:
            if claim["has_assumption_label"]:
                # Unsubstantiated but labeled as assumption—acceptable but note it
                pass
            else:
                # Unsubstantiated and not labeled—problematic
                unsupported.append({
                    "claim": claim_value,
                    "type": claim.get("type", "Unknown"),
                    "context": claim.get("context", ""),
                })

    # Calculate coverage
    coverage = ((len(claims) - len(unsupported)) / len(claims)) * 100 if claims else 100

    # Determine status
    if len(unsupported) > len(claims) * 0.2:  # > 20% unsupported
        status = "fail"
    elif unsupported:
        status = "warn"
    else:
        status = "pass"

    remediation = _generate_remediation(unsupported, process_model)

    return {
        "status": status,
        "unsupported_claims": unsupported,
        "assumptions_needing_labels": needs_labels,
        "evidence_coverage": round(coverage, 1),
        "remediation": remediation,
    }


def _build_evidence_map(
    process_model: dict[str, Any] | None,
    user_instructions: str,
    source_references: list[str] | None
) -> dict[str, Any]:
    """Build a searchable map of available evidence."""
    evidence = {
        "metrics": [],
        "numbers": [],
        "sources": source_references or [],
        "instructions": user_instructions or "",
    }

    if not process_model:
        return evidence

    # Extract metrics from process model
    if "kpis" in process_model and isinstance(process_model["kpis"], list):
        for kpi in process_model["kpis"]:
            if isinstance(kpi, dict):
                if "value" in kpi:
                    evidence["metrics"].append(str(kpi["value"]))
                if "target" in kpi:
                    evidence["numbers"].append(str(kpi["target"]))

    # Extract financial data
    if "financials" in process_model and isinstance(process_model["financials"], dict):
        for key, value in process_model["financials"].items():
            if isinstance(value, (int, float)):
                evidence["numbers"].append(str(value))

    # Extract volumes/scales
    if "scale" in process_model:
        scale_str = json.dumps(process_model["scale"])
        evidence["numbers"].extend(re.findall(r"\d+", scale_str))

    return evidence


def _find_evidence_for_claim(claim_value: str, evidence_map: dict[str, Any]) -> bool:
    """Check if a claim value appears in evidence."""
    # Extract numeric part
    numbers = re.findall(r"\d+", claim_value)

    # Check exact match in metrics
    if claim_value in evidence_map["metrics"]:
        return True

    # Check if any number in claim matches evidence
    for num in numbers:
        if num in evidence_map["numbers"]:
            return True

    # Check user instructions for explicit mention
    if claim_value.lower() in evidence_map["instructions"].lower():
        return True

    return False


def _generate_remediation(
    unsupported_claims: list[dict[str, Any]],
    process_model: dict[str, Any] | None
) -> list[str]:
    """Generate remediation suggestions."""
    if not unsupported_claims:
        return []

    suggestions = [
        "Remove unsupported metrics or replace with values from ProcessModel",
        "Add explicit assumption labels (e.g., 'estimated', 'projected') for unsubstantiated figures",
        "Include source citations or evidence references in slide notes",
    ]

    if process_model:
        suggestions.append("Verify metrics align with ProcessModel KPIs and financials")

    return suggestions


def validate_slide_evidence(
    slide: dict[str, Any],
    process_model: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Validate evidence for a single slide."""
    # Extract all text content
    text_parts = []

    for key in ("title", "subtitle", "description", "context"):
        if key in slide and slide[key]:
            text_parts.append(str(slide[key]))

    # Extract from nested structures
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

    # Two producers write speaker notes under different keys: the content agent
    # emits `notes` (the key the slide prompt asks for, and the one the renderer
    # reads), while pptx_layout_planner's notes_overflow writes `speaker_notes`.
    # Read both, or the "Source: ..." citation the model was told to write is
    # never seen by the validator.
    notes = " ".join(
        str(slide.get(key) or "") for key in ("notes", "speaker_notes")
    ).strip()

    # Extract and validate claims
    claims = extract_numeric_claims(combined_text)
    validation = validate_claims_against_evidence(
        claims,
        process_model,
        notes,
        slide.get("source_refs", [])
    )

    return {
        "slide_title": slide.get("title", "Untitled"),
        "slide_type": slide.get("slide_type", "unknown"),
        "claims_found": len(claims),
        "validation": validation,
    }


def validate_text_evidence(
    text: str,
    process_model: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Validate numeric claims in prose (DOCX markdown) against evidence.

    Same treatment slides get in ``validate_slide_evidence``; returns
    {"claims_found": int, "validation": {...}} so callers can share hint-building.
    """
    claims = extract_numeric_claims(text or "")
    validation = validate_claims_against_evidence(claims, process_model)
    return {"claims_found": len(claims), "validation": validation}


def validate_pptx_slides_evidence(
    pptx_slides: list[dict[str, Any]],
    process_model: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Validate evidence across all slides."""
    slide_validations = []
    total_claims = 0
    unsupported_count = 0

    for slide in pptx_slides:
        result = validate_slide_evidence(slide, process_model)
        slide_validations.append(result)

        total_claims += result["claims_found"]
        unsupported_count += len(result["validation"].get("unsupported_claims", []))

    # Overall status
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
        "summary": f"{total_claims} claims found; {unsupported_count} unsupported ({(unsupported_count/total_claims*100 if total_claims else 0):.1f}%)",
    }
