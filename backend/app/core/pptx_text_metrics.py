"""Deterministic text measurement for PPTX layout.

PowerPoint renders Calibri; LibreOffice (our soffice QA path) substitutes the
metric-compatible Carlito. We bundle Carlito (SIL OFL) under
``backend/app/assets/fonts`` so the measurement engine, the soffice render, and
the prompt's character budgets all agree.

Measurement model: PIL ``getlength`` is called with the font em size set to the
point size in pixels. At that scale 1px == 1pt, so a width in those pixels is a
width in points, and ``points / 72`` is inches — the unit python-pptx wants.

Tiered font resolution (fail-soft):
  1. Bundled Carlito TTF (deterministic, committed, present everywhere).
  2. System font by family name via Pillow (Calibri on Windows, Arial /
     Liberation elsewhere) — used when a brand overrides the font family.
  3. Average advance-width heuristic — last resort, never raises.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

# Families we treat as Calibri-metric; all map onto the bundled Carlito faces.
_CALIBRI_FAMILIES = {"calibri", "calibri light", "carlito", ""}

_CARLITO_FACES = {
    (False, False): "Carlito-Regular.ttf",
    (True, False): "Carlito-Bold.ttf",
    (False, True): "Carlito-Italic.ttf",
    (True, True): "Carlito-BoldItalic.ttf",
}

# System fallbacks, tried by name when the family is not Calibri-metric.
_SYSTEM_FACES = {
    (False, False): ("Arial.ttf", "Arial", "LiberationSans-Regular.ttf", "Helvetica"),
    (True, False): ("Arial Bold.ttf", "Arial-Bold", "LiberationSans-Bold.ttf"),
    (False, True): ("Arial Italic.ttf", "LiberationSans-Italic.ttf"),
    (True, True): ("Arial Bold Italic.ttf", "LiberationSans-BoldItalic.ttf"),
}

# Heuristic average advance widths as a fraction of em (last-resort tier only).
_AVG_EM_REGULAR = 0.50
_AVG_EM_BOLD = 0.53

# Default line spacing multiple used for wrapped-height estimates.
DEFAULT_LINE_SPACING = 1.16


# Per-component character budgets. Single source of truth: consumed by schema
# validation (pptx_schema) and surfaced to the LLM in the slide prompt so the
# model writes copy that fits before a render is ever attempted.
CHAR_BUDGETS: dict[str, int] = {
    "headline": 90,        # assertion title (wraps to <= 2 lines)
    "kicker": 130,         # italic sub-headline
    "eyebrow": 38,         # ALL-CAPS section label
    "micro_label": 24,     # OWNER / TARGET CLIENT etc.
    "bullet": 160,         # one bullet line
    "card_title": 40,      # card / column heading
    "card_body": 220,      # card / column body
    "stat_value": 12,      # big number
    "stat_label": 28,      # stat caption
    "stat_desc": 120,      # stat description
    "lane_label": 16,      # BUILD / DEPLOY / PARTNER chip
    "lane_item_title": 44,
    "lane_item_meta": 80,
    "tower_header": 28,
    "tower_item": 60,
    "takeaway": 220,
    "synthesis_text": 280,
}


@dataclass
class FitResult:
    """Outcome of fitting text into a fixed box."""

    pt: float
    lines: list[str]
    height_in: float
    overflow: bool = False
    # How the text was made to fit, for the fit_report / QA surface.
    actions: list[str] = field(default_factory=list)


def _bundled_path(bold: bool, italic: bool) -> Path | None:
    name = _CARLITO_FACES[(bold, italic)]
    p = _FONT_DIR / name
    return p if p.exists() else None


@lru_cache(maxsize=256)
def _load_font(family_key: str, bold: bool, italic: bool, px: int):
    """Return a PIL ImageFont for (family, style, size) or None.

    ``family_key`` is the lowercased family; Calibri-metric families resolve to
    bundled Carlito, everything else tries the system by name.
    """
    try:
        from PIL import ImageFont
    except Exception as exc: # Pillow somehow unavailable -> heuristic tier
        logger.warning("%s: suppressed error: %s", '_load_font', exc)
        return None

    candidates: list[str] = []
    if family_key in _CALIBRI_FAMILIES:
        bp = _bundled_path(bold, italic)
        if bp is not None:
            candidates.append(str(bp))
    else:
        # Non-Calibri brand font: try the literal family, then system proxies,
        # then still fall back to bundled Carlito so we always measure *something*.
        candidates.append(family_key)
        candidates.extend(_SYSTEM_FACES.get((bold, italic), ()))
        bp = _bundled_path(bold, italic)
        if bp is not None:
            candidates.append(str(bp))

    for cand in candidates:
        try:
            return ImageFont.truetype(cand, px)
        except Exception as exc:
            logger.debug("%s: suppressed error: %s", '_load_font', exc)
            continue
    return None


def measure_text_width_in(
    text: str, family: str, pt: float, *, bold: bool = False, italic: bool = False
) -> float:
    """Width of a single line of text, in inches."""
    if not text:
        return 0.0
    px = max(1, int(round(pt)))
    font = _load_font((family or "").strip().lower(), bold, italic, px)
    if font is not None:
        try:
            return float(font.getlength(text)) / 72.0
        except Exception as exc:
            logger.warning("%s: suppressed error: %s", 'measure_text_width_in', exc)
    # Heuristic tier: average advance width.
    em = _AVG_EM_BOLD if bold else _AVG_EM_REGULAR
    return (len(text) * em * pt) / 72.0


def _wrap_words(
    text: str, family: str, pt: float, box_w_in: float, *, bold: bool, italic: bool
) -> list[str]:
    """Greedy word wrap; hard-breaks any single word wider than the box."""
    words = str(text).split()
    if not words:
        return []
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = word if not cur else f"{cur} {word}"
        if measure_text_width_in(trial, family, pt, bold=bold, italic=italic) <= box_w_in or not cur:
            # If even the lone word overflows, hard-break it character by character.
            if not cur and measure_text_width_in(word, family, pt, bold=bold, italic=italic) > box_w_in:
                lines.extend(_hard_break(word, family, pt, box_w_in, bold=bold, italic=italic))
                cur = ""
            else:
                cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _hard_break(
    word: str, family: str, pt: float, box_w_in: float, *, bold: bool, italic: bool
) -> list[str]:
    out: list[str] = []
    chunk = ""
    for ch in word:
        if measure_text_width_in(chunk + ch, family, pt, bold=bold, italic=italic) > box_w_in and chunk:
            out.append(chunk)
            chunk = ch
        else:
            chunk += ch
    if chunk:
        out.append(chunk)
    return out


def measure_wrapped(
    text: str,
    family: str,
    pt: float,
    box_w_in: float,
    *,
    bold: bool = False,
    italic: bool = False,
    line_spacing: float = DEFAULT_LINE_SPACING,
) -> tuple[list[str], float]:
    """Wrap ``text`` to ``box_w_in`` and return (lines, total_height_in)."""
    lines = _wrap_words(text, family, pt, box_w_in, bold=bold, italic=italic)
    height = len(lines) * pt * line_spacing / 72.0
    return lines, height


def fit_text(
    text: str,
    box_w_in: float,
    box_h_in: float,
    *,
    family: str = "Calibri",
    max_pt: float,
    min_pt: float,
    bold: bool = False,
    italic: bool = False,
    line_spacing: float = DEFAULT_LINE_SPACING,
    max_lines: int | None = None,
) -> FitResult:
    """Shrink font from ``max_pt`` toward ``min_pt`` until the text fits the box.

    Returns the largest size that fits within both width (wrapped) and height
    (and ``max_lines`` if given). If nothing fits at ``min_pt``, returns the
    min-pt wrap with ``overflow=True`` so callers can trim or spill.
    """
    text = str(text or "")
    if not text.strip():
        return FitResult(pt=max_pt, lines=[], height_in=0.0, overflow=False)

    pt = float(max_pt)
    step = 1.0
    last_lines: list[str] = []
    last_height = 0.0
    while pt >= min_pt:
        lines, height = measure_wrapped(
            text, family, pt, box_w_in, bold=bold, italic=italic, line_spacing=line_spacing
        )
        last_lines, last_height = lines, height
        fits_height = height <= box_h_in + 1e-6
        fits_lines = max_lines is None or len(lines) <= max_lines
        if fits_height and fits_lines:
            actions = [] if pt >= max_pt else [f"shrunk {max_pt:.0f}->{pt:.0f}pt"]
            return FitResult(pt=pt, lines=lines, height_in=height, overflow=False, actions=actions)
        pt -= step
    # Nothing fit even at min_pt.
    return FitResult(
        pt=min_pt,
        lines=last_lines,
        height_in=last_height,
        overflow=True,
        actions=["clipped: exceeds box at min_pt"],
    )


def fits_budget(text: str, budget_key: str) -> bool:
    """True if ``text`` is within the named character budget (unknown key -> True)."""
    limit = CHAR_BUDGETS.get(budget_key)
    if limit is None:
        return True
    return len(str(text or "")) <= limit
