"""Tests for the narrative-coherence feedback loop."""

from __future__ import annotations

import json
from pathlib import Path

from app.core.narrative_feedback import (
    build_narrative_feedback_hints,
    extract_narrative_signals,
    narrative_signals_from_run_dir,
    persist_narrative_signals,
)


def _report(score: float, issues: list[str]) -> dict:
    return {
        "dimensions": {
            "narrative_coherence": {
                "score": score,
                "issues": issues,
                "remediation_hint": "Tighten the narrative arc.",
            }
        }
    }


def test_extract_narrative_signals_skips_passing_outputs() -> None:
    reports = {
        "docx": _report(0.9, []),
        "pdf": _report(0.6, ["No intro", "Missing transitions"]),
        "pptx": _report(0.2, ["Irrelevant for pptx"]),
    }
    signals = extract_narrative_signals(reports)
    assert "docx" not in signals
    assert "pptx" not in signals, "PPTX should be ignored; narrative rule is docx/pdf only"
    pdf_sig = signals["pdf"]
    assert pdf_sig["score"] == 0.6
    assert pdf_sig["issues"] == ["No intro", "Missing transitions"]
    assert pdf_sig["passed"] is False
    assert pdf_sig["remediation_hint"] == "Tighten the narrative arc."


def test_extract_fail_open_on_bad_shape() -> None:
    assert extract_narrative_signals(None) == {}
    assert extract_narrative_signals({"docx": "not-a-dict"}) == {}
    assert extract_narrative_signals({"docx": {"dimensions": "bad"}}) == {}


def test_build_feedback_hints_produces_instruction_records() -> None:
    signals = extract_narrative_signals(
        {"docx": _report(0.55, ["Disjointed sections", "Missing close"])}
    )
    hints = build_narrative_feedback_hints(signals, "docx")
    assert len(hints) == 3  # 2 issues + 1 remediation
    assert all(isinstance(h, dict) and "instruction" in h for h in hints)
    assert {h["instruction"] for h in hints} >= {
        "Disjointed sections",
        "Missing close",
        "Tighten the narrative arc.",
    }
    assert all(h.get("source", "").startswith("narrative_coherence") for h in hints)


def test_build_feedback_hints_empty_for_unknown_output() -> None:
    signals = extract_narrative_signals({"docx": _report(0.4, ["x"])})
    assert build_narrative_feedback_hints(signals, "pptx") == []
    assert build_narrative_feedback_hints(signals, "xlsx") == []


def test_persist_and_reload_roundtrip(tmp_path: Path) -> None:
    signals = extract_narrative_signals(
        {"docx": _report(0.5, ["A"]), "pdf": _report(0.6, ["B"])}
    )
    written = persist_narrative_signals(tmp_path, signals)
    assert written is not None and written.exists()
    loaded = narrative_signals_from_run_dir(tmp_path)
    assert set(loaded.keys()) == {"docx", "pdf"}
    assert loaded["docx"]["issues"] == ["A"]
    assert loaded["pdf"]["issues"] == ["B"]


def test_persist_merges_into_existing_file(tmp_path: Path) -> None:
    first = extract_narrative_signals({"docx": _report(0.5, ["A"])})
    persist_narrative_signals(tmp_path, first)
    second = extract_narrative_signals({"pdf": _report(0.5, ["B"])})
    persist_narrative_signals(tmp_path, second)
    merged = narrative_signals_from_run_dir(tmp_path)
    assert set(merged.keys()) == {"docx", "pdf"}
    raw = json.loads((tmp_path / "narrative_signals.json").read_text("utf-8"))
    assert "_meta" in raw


def test_persist_noop_for_empty_signals(tmp_path: Path) -> None:
    assert persist_narrative_signals(tmp_path, {}) is None
    assert not (tmp_path / "narrative_signals.json").exists()


def test_narrative_signals_from_missing_dir(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    assert narrative_signals_from_run_dir(missing) == {}
