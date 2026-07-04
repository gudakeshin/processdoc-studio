"""Action-title heuristics (Deloitte-quality program, Pillar A / scored by Pillar C).

Consulting decks use *action titles*: each title is an assertion that carries the
argument, not a topic label. This module classifies a single title and scores a
deck, with no NLP dependency — deliberately heuristic and conservative (it only
flags titles it is fairly sure are bare labels).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Bare-label phrases that are never assertions on their own.
_LABEL_PHRASES: frozenset[str] = frozenset(
    {
        "overview", "introduction", "background", "context", "current state",
        "as-is", "to-be", "future state", "agenda", "objectives", "scope",
        "approach", "methodology", "summary", "executive summary", "next steps",
        "appendix", "our team", "about us", "key findings", "findings",
        "recommendations", "conclusion", "conclusions", "process overview",
        "key activities", "roles and responsibilities", "challenges",
        "opportunities", "timeline", "roadmap", "the ask", "questions",
    }
)

# Common business verbs that signal a claim. Detection is lexicon + light
# inflection (-s/-ed/-ing) so we don't need a POS tagger.
_VERB_STEMS: frozenset[str] = frozenset(
    {
        "add", "cut", "save", "reduce", "raise", "lift", "drive", "deliver",
        "unlock", "enable", "create", "build", "grow", "shrink", "remove",
        "eliminate", "improve", "accelerate", "slow", "cost", "lose", "gain",
        "win", "free", "shift", "move", "close", "open", "double", "triple",
        "halve", "outperform", "lag", "lead", "exceed", "miss", "block",
        "stall", "expose", "threaten", "risk", "require", "demand", "need",
        "must", "should", "will", "cannot", "fail", "succeed", "prove",
        "show", "reveal", "confirm", "make", "take", "give", "turn", "boost",
        "trim", "trap", "stem", "fund", "pay", "earn", "yield", "return",
        "scale", "automate", "streamline", "consolidate", "rationalize",
        "capture", "depend", "hinge", "rest", "matter",
        # consulting-deck movement / causation verbs
        "derail", "collapse", "climb", "erode", "compound", "outpace",
        "surpass", "command", "anchor", "bleed", "leak", "drain", "slash",
        "shave", "compress", "expand", "widen", "narrow", "tighten", "mask",
        "signal", "point", "mean", "stem", "trap", "fuel", "spark", "stall",
        "hold", "carry", "cap", "limit", "constrain", "outweigh", "offset",
    }
)

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")
_NUM_RE = re.compile(r"[\$£€]|\d|%|\bx\b|×")


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _looks_like_verb(tok: str) -> bool:
    if tok in _VERB_STEMS:
        return True
    for suf in ("s", "es", "ed", "ing"):
        if tok.endswith(suf) and tok[: -len(suf)] in _VERB_STEMS:
            return True
    # irregular -> stem (e.g. "doubling" handled above; "cutting"/"cuts")
    if tok.endswith("ting") and tok[:-4] in _VERB_STEMS:
        return True
    if tok.endswith("tting") and tok[:-5] in _VERB_STEMS:
        return True
    return False


@dataclass(frozen=True)
class TitleVerdict:
    is_assertion: bool
    reason: str


def classify_title(title: str) -> TitleVerdict:
    """Classify a single slide title as an assertion or a bare topic label."""
    raw = (title or "").strip()
    norm = re.sub(r"\s+", " ", raw).strip().rstrip(":").lower()
    if not norm:
        return TitleVerdict(False, "empty")
    if norm in _LABEL_PHRASES:
        return TitleVerdict(False, "known topic label")
    toks = _tokens(raw)
    # A concrete number/currency/percentage almost always means a claim is present.
    if _NUM_RE.search(raw):
        return TitleVerdict(True, "carries a quantified claim")
    if len(toks) < 4:
        return TitleVerdict(False, "too short to be an assertion")
    if any(_looks_like_verb(t) for t in toks):
        return TitleVerdict(True, "contains an action verb")
    return TitleVerdict(False, "noun phrase without a verb or metric")


@dataclass(frozen=True)
class TitleScore:
    total: int
    assertions: int
    labels: int
    label_ratio: float
    label_titles: tuple[str, ...]


def score_titles(titles: list[str], *, max_label_ratio: float = 0.2) -> tuple[TitleScore, bool]:
    """Score a deck's titles. Returns (score, passed).

    ``passed`` is False when the share of bare-label titles exceeds
    ``max_label_ratio`` (default 20%).
    """
    clean = [t for t in (titles or []) if str(t or "").strip()]
    if not clean:
        return TitleScore(0, 0, 0, 0.0, ()), True
    labels = [t for t in clean if not classify_title(t).is_assertion]
    total = len(clean)
    label_ratio = len(labels) / total
    score = TitleScore(
        total=total,
        assertions=total - len(labels),
        labels=len(labels),
        label_ratio=round(label_ratio, 3),
        label_titles=tuple(labels),
    )
    return score, (label_ratio <= max_label_ratio)
