"""Narrative coherence feedback loop.

Extracts narrative-coherence signals from the unified quality framework reports,
persists them under ``narrative_signals.json`` in the run workspace, and
produces feedback hints that the docx / pdf subagents consume on retry — mirroring
the pattern established by ``pptx_visual_feedback`` + ``pptx_render_signals.json``.

The module is intentionally fail-open: missing reports, unwritable run dirs, and
malformed dimensions all resolve to empty hint lists rather than raising.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

NARRATIVE_OUTPUT_TYPES: frozenset[str] = frozenset({"docx", "pdf"})
DEFAULT_NARRATIVE_THRESHOLD: float = 0.75
_NARRATIVE_SIGNALS_FILENAME = "narrative_signals.json"


def _coerce_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _as_issue_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def extract_narrative_signals(
    unified_quality_reports: Any,
    *,
    threshold: float = DEFAULT_NARRATIVE_THRESHOLD,
    output_types: Iterable[str] = NARRATIVE_OUTPUT_TYPES,
) -> dict[str, dict[str, Any]]:
    """Pull narrative coherence signals out of a ``unified_quality_reports`` dict.

    Parameters
    ----------
    unified_quality_reports:
        The dict produced by ``UnifiedQualityFramework.evaluate_deliverable``
        keyed by output type (``"docx"``, ``"pdf"``, ...). Any other shape is
        treated as empty (fail-open).
    threshold:
        Scores strictly below this value trigger signal emission.
    output_types:
        Output types to inspect. Defaults to narrative-producing types.

    Returns
    -------
    A mapping ``{output_type: signal_record}`` containing only output types
    whose narrative_coherence dimension fell below the threshold. Each record
    includes ``score``, ``issues``, ``remediation_hint``, ``threshold``, and
    ``generated_at`` (ISO 8601 UTC).
    """

    signals: dict[str, dict[str, Any]] = {}
    if not isinstance(unified_quality_reports, dict):
        return signals

    allowed = {str(x).strip().lower() for x in output_types}
    now_iso = datetime.now(UTC).isoformat()

    for output_type, report in unified_quality_reports.items():
        key = str(output_type).strip().lower()
        if key not in allowed:
            continue
        if not isinstance(report, dict):
            continue
        dimensions = report.get("dimensions")
        if not isinstance(dimensions, dict):
            continue
        narrative = dimensions.get("narrative_coherence")
        if not isinstance(narrative, dict):
            continue
        score = _coerce_float(narrative.get("score"), 1.0)
        issues = _as_issue_list(narrative.get("issues"))
        remediation_hint = str(narrative.get("remediation_hint") or "").strip()

        if score >= threshold and not issues:
            continue

        signals[key] = {
            "output_type": key,
            "score": score,
            "threshold": float(threshold),
            "passed": bool(score >= threshold and not issues),
            "issues": issues[:20],
            "remediation_hint": remediation_hint or None,
            "generated_at": now_iso,
        }
    return signals


def persist_narrative_signals(run_dir: Path, signals: dict[str, dict[str, Any]]) -> Path | None:
    """Write ``narrative_signals.json`` under ``run_dir``.

    Always fail-open. Returns the written path on success, ``None`` otherwise.
    """

    if not signals:
        return None
    if not isinstance(run_dir, Path):
        try:
            run_dir = Path(str(run_dir))
        except Exception:
            return None
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("narrative_feedback: cannot create run_dir %s: %s", run_dir, exc)
        return None
    path = run_dir / _NARRATIVE_SIGNALS_FILENAME
    try:
        current: dict[str, Any] = {}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    current = loaded
            except Exception:
                current = {}
        current.update(signals)
        current["_meta"] = {
            "generated_at": datetime.now(UTC).isoformat(),
            "output_types": sorted(set(k for k in current if not k.startswith("_"))),
        }
        path.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
        return path
    except Exception as exc:
        logger.warning("narrative_feedback: failed to persist signals: %s", exc)
        return None


def build_narrative_feedback_hints(
    signals: dict[str, dict[str, Any]],
    output_type: str,
) -> list[dict[str, str]]:
    """Shape per-output narrative signals as agent-consumable feedback hints.

    The returned structure mirrors ``pptx_visual_feedback`` entries so the
    agent plumbing treats them the same way: a list of
    ``{"instruction": str, ...}`` records the subagent appends to its prompt.
    """

    key = str(output_type).strip().lower()
    record = signals.get(key)
    if not isinstance(record, dict):
        return []
    if record.get("passed"):
        return []

    issues = _as_issue_list(record.get("issues"))
    remediation = str(record.get("remediation_hint") or "").strip()

    hints: list[dict[str, str]] = []
    for issue in issues:
        hints.append({"instruction": issue, "source": "narrative_coherence"})
    if remediation and not any(h.get("instruction") == remediation for h in hints):
        hints.append({"instruction": remediation, "source": "narrative_coherence.remediation"})
    return hints


def narrative_signals_from_run_dir(run_dir: Path) -> dict[str, dict[str, Any]]:
    """Load previously persisted signals from ``narrative_signals.json``.

    Fail-open: returns ``{}`` on any error.
    """

    if not isinstance(run_dir, Path):
        try:
            run_dir = Path(str(run_dir))
        except Exception:
            return {}
    path = run_dir / _NARRATIVE_SIGNALS_FILENAME
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {k: v for k, v in loaded.items() if isinstance(v, dict) and not k.startswith("_")}


__all__ = [
    "NARRATIVE_OUTPUT_TYPES",
    "DEFAULT_NARRATIVE_THRESHOLD",
    "build_narrative_feedback_hints",
    "extract_narrative_signals",
    "narrative_signals_from_run_dir",
    "persist_narrative_signals",
]
