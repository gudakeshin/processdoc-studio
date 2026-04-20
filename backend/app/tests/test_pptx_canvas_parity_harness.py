"""Regression tests for the PPTX-canvas parity harness (PPT-201 follow-up).

These tests call into the script module directly so CI fails fast when:

- A new slide_type appears in a deck sample but is not yet listed in
  ``SUPPORTED_SLIDE_TYPES`` (schema drift between backend and canvas).
- A sample deck is missing titles in slides that require them.
- The parity score dips below the 0.95 threshold.

Importing the script requires adjusting ``sys.path`` because it lives in
``infra/scripts`` rather than inside the installed backend package.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_parity_module():
    script = _REPO_ROOT / "infra" / "scripts" / "pptx_canvas_parity_spike.py"
    spec = importlib.util.spec_from_file_location("pptx_canvas_parity_spike", script)
    assert spec and spec.loader, "Could not locate parity spike script"
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("pptx_canvas_parity_spike", module)
    spec.loader.exec_module(module)
    return module


def test_parity_harness_passes_known_samples() -> None:
    mod = _load_parity_module()
    report = mod.run_parity_spike()
    assert report["overall_pass"] is True
    for row in report["results"]:
        assert row["unsupported_slide_types"] == []
        assert row["missing_titles"] == 0
        assert row["pass_threshold"] is True


def test_parity_harness_flags_unknown_slide_type() -> None:
    mod = _load_parity_module()
    payload = {
        "slides": [
            {"slide_type": "title", "title": "Ok"},
            {"slide_type": "radial_chart", "title": "Unknown"},
        ]
    }
    result = mod._score_sample("new_schema.json", payload)
    assert "radial_chart" in result.unsupported_slide_types
    assert result.pass_threshold is False


def test_parity_harness_flags_missing_titles() -> None:
    mod = _load_parity_module()
    payload = {
        "slides": [
            {"slide_type": "title"},
            {"slide_type": "bullets", "bullets": ["x"]},
        ]
    }
    result = mod._score_sample("no_titles.json", payload)
    assert result.missing_titles >= 1
    assert result.pass_threshold is False


def test_parity_harness_accepts_section_divider_with_subtitle_only() -> None:
    mod = _load_parity_module()
    payload = {
        "slides": [
            {"slide_type": "title", "title": "Intro"},
            {"slide_type": "section_divider", "subtitle": "Appendix"},
        ]
    }
    result = mod._score_sample("section_only_subtitle.json", payload)
    assert result.missing_titles == 0
    assert result.unsupported_slide_types == []
    assert result.pass_threshold is True
