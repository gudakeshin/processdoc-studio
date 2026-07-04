"""Detect requested deliverable output formats from natural-language instructions."""

from __future__ import annotations

import re
from typing import Any

# Phrase lists — substring match on lowered instruction (same contract as runs._recommend_output_types).
EXPLICIT_FORMAT_PHRASES: dict[str, list[str]] = {
    "pptx": [
        "only pptx",
        "only slides",
        "only slide",
        "just pptx",
        "just slides",
        "pptx only",
        "slides only",
        "slide only",
        "in pptx",
        "in slides",
        "in slide",
        "in ppt",
        "in powerpoint",
        "presentation format",
        "presentation only",
        "ppt only",
        "ppt format",
        "powerpoint only",
        "powerpoint format",
        "as ppt",
        "as pptx",
    ],
    "docx": [
        "only docx",
        "only word",
        "only doc",
        "just docx",
        "just word",
        "docx only",
        "word only",
        "doc only",
        "in docx",
        "in word",
        "document format",
        "document only",
        "word format",
        "word document only",
        "as word",
        "as docx",
    ],
    "xlsx": [
        "only xlsx",
        "only excel",
        "only spreadsheet",
        "just xlsx",
        "just excel",
        "xlsx only",
        "excel only",
        "spreadsheet only",
        "in xlsx",
        "in excel",
        "spreadsheet format",
        "excel format",
        "as excel",
        "as xlsx",
        "workbook only",
        "in workbook",
    ],
    "process_map": [
        "only process map",
        "only process_map",
        "only diagram",
        "just process map",
        "process map only",
        "diagram only",
        "flowchart only",
        "as process map",
        "in drawio",
    ],
    "pdf": [
        "only pdf",
        "just pdf",
        "pdf only",
        "in pdf",
        "as pdf",
    ],
}

DELIVERABLE_KEYWORD_FORMATS: dict[str, list[str]] = {
    "proposal": ["docx", "pptx"],
    "approach note": ["docx", "pptx"],
    "process flow": ["process_map", "docx"],
    "narrative": ["docx"],
    "raci": ["xlsx"],
    "sop": ["docx"],
    "business requirement document": ["docx", "pptx"],
    "brd": ["docx", "pptx"],
    "improvement report": ["docx", "pptx"],
    "financial model": ["xlsx"],
    "training deck": ["pptx"],
}

_DEFAULT_REPR: dict[str, str] = {
    "pptx": "pptx",
    "docx": "docx",
    "xlsx": "xlsx",
    "pdf": "pdf",
    "process_map": "drawio_xml",
}

_STANDALONE_EXCEL_RE = re.compile(r"\b(excel|xlsx|spreadsheet|workbook)\b", re.IGNORECASE)
_DECK_FORMAT_RE = re.compile(r"\b(pptx?|powerpoint|slides?|deck|presentation)\b", re.IGNORECASE)
_EXCEL_INSTEAD_RE = re.compile(
    r"\b(?:instead|rather than|not|no|without|switch to|change to|want|need|give me|get me)\b.{0,40}\b(?:excel|xlsx|spreadsheet|workbook)\b",
    re.IGNORECASE,
)
_DECK_INSTEAD_RE = re.compile(
    r"\b(?:instead|rather than|not|no|without)\b.{0,40}\b(?:pptx?|powerpoint|slides?|deck|presentation)\b",
    re.IGNORECASE,
)
_FINANCIAL_MODEL_RE = re.compile(
    r"\b(?:financial\s+model(?:ing)?|three[\s-]statement|3[\s-]statement|dcf\s+model|fp&a\s+model|valuation\s+model)\b",
    re.IGNORECASE,
)


def detect_explicit_output_formats(instruction: str) -> list[str]:
    """Return format types named explicitly (e.g. 'excel only', 'in pptx')."""
    lowered = (instruction or "").lower()
    found: list[str] = []
    for output_type, phrases in EXPLICIT_FORMAT_PHRASES.items():
        for phrase in phrases:
            if phrase in lowered:
                found.append(output_type)
                break
    return list(dict.fromkeys(found))


def detect_deliverable_keyword_formats(instruction: str) -> list[str]:
    """Map deliverable nouns (proposal, RACI, financial model) to format types."""
    lowered = (instruction or "").lower()
    desired: list[str] = []
    if "proposal" in lowered:
        desired.extend(DELIVERABLE_KEYWORD_FORMATS["proposal"])
    if "approach note" in lowered or ("approach" in lowered and "note" in lowered):
        desired.extend(DELIVERABLE_KEYWORD_FORMATS["approach note"])
    if "process flow" in lowered:
        desired.extend(DELIVERABLE_KEYWORD_FORMATS["process flow"])
    if "narratives" in lowered or "narrative" in lowered:
        desired.extend(DELIVERABLE_KEYWORD_FORMATS["narrative"])
    if "raci" in lowered:
        desired.extend(DELIVERABLE_KEYWORD_FORMATS["raci"])
    if "sop" in lowered:
        desired.extend(DELIVERABLE_KEYWORD_FORMATS["sop"])
    if "business requirement document" in lowered or "brd" in lowered:
        desired.extend(DELIVERABLE_KEYWORD_FORMATS["brd"])
    if "improvement report" in lowered:
        desired.extend(DELIVERABLE_KEYWORD_FORMATS["improvement report"])
    if _FINANCIAL_MODEL_RE.search(lowered) or "financial model" in lowered:
        desired.extend(DELIVERABLE_KEYWORD_FORMATS["financial model"])
    if "training deck" in lowered:
        desired.extend(DELIVERABLE_KEYWORD_FORMATS["training deck"])
    return list(dict.fromkeys(desired))


def detect_standalone_excel_intent(instruction: str) -> bool:
    """True when the user clearly wants Excel without also asking for a deck."""
    text = instruction or ""
    if not _STANDALONE_EXCEL_RE.search(text):
        return False
    if _EXCEL_INSTEAD_RE.search(text):
        return True
    if _DECK_FORMAT_RE.search(text) and not _DECK_INSTEAD_RE.search(text):
        # Both mentioned — require excel to win via explicit phrasing or "instead"
        return bool(_EXCEL_INSTEAD_RE.search(text) or "in excel" in text.lower() or "as excel" in text.lower())
    return True


def detect_standalone_deck_intent(instruction: str) -> bool:
    """True when the user clearly wants a deck/slides without also asking for Excel."""
    text = instruction or ""
    if not _DECK_FORMAT_RE.search(text):
        return False
    if _DECK_INSTEAD_RE.search(text):
        return True
    if _STANDALONE_EXCEL_RE.search(text) and not _EXCEL_INSTEAD_RE.search(text):
        # Both mentioned — require deck to win via explicit phrasing or "instead"
        lowered = text.lower()
        return bool(_DECK_INSTEAD_RE.search(text) or "in pptx" in lowered or "as pptx" in lowered)
    return True


def is_financial_model_intent(instruction: str) -> bool:
    lowered = (instruction or "").lower()
    return bool(_FINANCIAL_MODEL_RE.search(lowered) or "financial model" in lowered)


def resolve_output_formats(
    instruction: str,
    allowed: set[str] | None = None,
) -> tuple[list[str], dict[str, str], str]:
    """
    Resolve output format types from instruction text.

    Returns (template_ids, output_type_representations, rationale).
    Empty template_ids means no strong format signal (caller keeps existing selection).
    """
    catalog = allowed or {"docx", "pptx", "xlsx", "pdf", "process_map"}
    lowered = (instruction or "").strip()
    if not lowered:
        return [], {}, ""

    explicit = detect_explicit_output_formats(lowered)
    deliverable = detect_deliverable_keyword_formats(lowered)
    standalone_excel = detect_standalone_excel_intent(lowered)
    standalone_deck = detect_standalone_deck_intent(lowered)
    financial_only = is_financial_model_intent(lowered)

    if explicit:
        chosen = explicit
        rationale = "Explicit output format constraint detected."
    elif financial_only:
        chosen = ["xlsx"]
        rationale = "Financial model deliverable maps to Excel (XLSX)."
    elif deliverable and standalone_excel:
        # User named both a deliverable and Excel — Excel wins for format selection.
        chosen = ["xlsx"]
        rationale = "Excel format requested; using spreadsheet output."
    elif standalone_excel:
        chosen = ["xlsx"]
        rationale = "Spreadsheet (Excel) format requested."
    elif standalone_deck:
        chosen = ["pptx"]
        rationale = "Presentation (deck) format requested."
    elif deliverable:
        chosen = deliverable
        rationale = "Deliverable intent maps to preferred output types."
    else:
        return [], {}, ""

    # Explicit xlsx / financial model must not also pull in pptx from proposal keywords.
    if "xlsx" in chosen and (explicit == ["xlsx"] or financial_only or standalone_excel):
        if "pptx" not in explicit and "docx" not in explicit:
            chosen = [t for t in chosen if t == "xlsx"]

    filtered = [t for t in chosen if t in catalog]
    filtered = list(dict.fromkeys(filtered))
    reps = {t: _DEFAULT_REPR[t] for t in filtered if t in _DEFAULT_REPR}
    return filtered, reps, rationale


def merge_format_intent_into_template_ids(
    instruction: str,
    template_ids: list[str],
    *,
    allowed: set[str] | None = None,
    output_type_representations: dict[str, str] | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Apply instruction format intent over existing template_ids when confident."""
    resolved, reps, _ = resolve_output_formats(instruction, allowed)
    if not resolved:
        return template_ids, dict(output_type_representations or {})
    merged_reps = dict(output_type_representations or {})
    merged_reps.update(reps)
    return resolved, merged_reps
