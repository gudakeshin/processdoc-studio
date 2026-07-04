"""Phase 2 — pptx_layout_planner: density estimation, demote, split, stable IDs."""
from __future__ import annotations

from app.core.pptx_layout_planner import (
    BULLET_SPLIT_THRESHOLD,
    estimate_density,
    plan_layout,
)


def _dense_column_cards() -> dict:
    long_body = "x" * 400
    return {
        "slide_type": "column_cards",
        "title": "Three pillars",
        "column_cards": [
            {"heading": "A", "body": long_body},
            {"heading": "B", "body": "short"},
        ],
    }


def test_estimate_density_flags_demote_candidate() -> None:
    d = estimate_density(_dense_column_cards())
    assert d["demote_candidate"] is True


def test_plan_layout_demotes_dense_column_cards() -> None:
    out = plan_layout([_dense_column_cards()])
    assert len(out) == 1
    assert out[0]["slide_type"] == "bullets"
    assert len(out[0]["bullets"]) == 2


def test_plan_layout_splits_long_bullet_list() -> None:
    slide = {
        "slide_type": "bullets",
        "title": "Many points",
        "slide_id": "slide_03",
        "bullets": [f"Point {i}" for i in range(BULLET_SPLIT_THRESHOLD + 4)],
    }
    out = plan_layout([slide])
    assert len(out) == 2
    assert len(out[0]["bullets"]) == BULLET_SPLIT_THRESHOLD
    assert out[1]["title"].endswith("(continued)")
    assert out[1]["slide_id"] == "slide_03_cont"
    assert out[0]["slide_index"] == 1
    assert out[1]["slide_index"] == 2


def test_plan_layout_splits_wide_table() -> None:
    header = ["Col1", "Col2"]
    rows = [header] + [[f"r{i}", f"v{i}"] for i in range(15)]
    slide = {"slide_type": "table", "title": "Detail", "table": rows, "slide_id": "slide_05"}
    out = plan_layout([slide])
    assert len(out) == 2
    assert len(out[0]["table"]) == 13  # header + 12 data rows
    assert out[1]["slide_id"] == "slide_05_cont"


def test_plan_layout_moves_overflow_to_speaker_notes() -> None:
    slide = {
        "slide_type": "bullets",
        "title": "Summary",
        "takeaway": "y" * 500,
        "bullets": ["one"],
    }
    out = plan_layout([slide])
    assert "speaker_notes" in out[0]
    assert len(out[0]["takeaway"]) < 500


def test_plan_layout_disabled_returns_input(monkeypatch) -> None:
    from app.core.config import settings
    from app.core.pptx_layout_planner import apply_layout_planner_if_enabled

    monkeypatch.setattr(settings, "pptx_layout_planner_enabled", False)
    slides = [{"slide_type": "bullets", "bullets": ["a"]}]
    assert apply_layout_planner_if_enabled(slides) is slides
