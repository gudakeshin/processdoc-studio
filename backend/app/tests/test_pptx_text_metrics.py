"""Phase 1 — deterministic text measurement.

Exercises width measurement, word wrapping, hard-break of over-long tokens, and
the shrink-to-fit behaviour that lets the renderer beat the reference deck's
clipping bugs. Uses the bundled Carlito faces so results are stable on CI.
"""

from __future__ import annotations

from app.core import pptx_text_metrics as tm


def test_width_grows_with_length_and_size() -> None:
    short = tm.measure_text_width_in("AI", "Calibri", 40)
    long = tm.measure_text_width_in("Agentic AI for Enterprise Finance", "Calibri", 40)
    assert long > short > 0
    big = tm.measure_text_width_in("Agentic", "Calibri", 54)
    small = tm.measure_text_width_in("Agentic", "Calibri", 18)
    assert big > small


def test_bold_is_wider_than_regular() -> None:
    reg = tm.measure_text_width_in("Enterprise Finance", "Calibri", 32, bold=False)
    bold = tm.measure_text_width_in("Enterprise Finance", "Calibri", 32, bold=True)
    assert bold >= reg


def test_wrapping_produces_multiple_lines_in_narrow_box() -> None:
    text = "Six workstreams. Named owners. One coordinated build."
    lines, height = tm.measure_wrapped(text, "Calibri", 34, box_w_in=4.0, bold=True)
    assert len(lines) >= 2
    assert height > 0
    # Every wrapped line fits the box width.
    for ln in lines:
        assert tm.measure_text_width_in(ln, "Calibri", 34, bold=True) <= 4.0 + 1e-6


def test_hard_break_of_unbreakable_token() -> None:
    # A single token wider than the box must still be split, never dropped.
    token = "Supercalifragilisticexpialidocious" * 2
    lines, _ = tm.measure_wrapped(token, "Calibri", 24, box_w_in=1.5)
    assert len(lines) >= 2
    assert "".join(lines) == token


def test_fit_text_shrinks_to_fit_then_reports_clean() -> None:
    text = "Three modes unlock AI-ready enterprise finance."
    res = tm.fit_text(text, box_w_in=9.0, box_h_in=1.0, family="Calibri",
                      max_pt=40, min_pt=18, bold=True, max_lines=2)
    assert not res.overflow
    assert 18 <= res.pt <= 40
    assert len(res.lines) <= 2


def test_fit_text_flags_overflow_when_nothing_fits() -> None:
    # A long paragraph forced into a tiny box cannot fit even at min_pt.
    text = " ".join(["overflow"] * 60)
    res = tm.fit_text(text, box_w_in=2.0, box_h_in=0.4, family="Calibri",
                      max_pt=18, min_pt=10)
    assert res.overflow
    assert res.pt == 10
    assert any("clipped" in a for a in res.actions)


def test_fit_text_records_shrink_action() -> None:
    text = "Margin defence has replaced volume growth and conventional diagnostics."
    res = tm.fit_text(text, box_w_in=6.0, box_h_in=1.6, family="Calibri",
                      max_pt=40, min_pt=16, bold=True)
    if res.pt < 40:
        assert any("shrunk" in a for a in res.actions)


def test_char_budgets_present_and_enforced() -> None:
    assert tm.CHAR_BUDGETS["headline"] > 0
    assert tm.fits_budget("short", "headline") is True
    assert tm.fits_budget("x" * 999, "headline") is False
    # Unknown budget key is permissive.
    assert tm.fits_budget("anything", "no_such_key") is True


def test_empty_text_is_zero_width_no_lines() -> None:
    assert tm.measure_text_width_in("", "Calibri", 40) == 0.0
    res = tm.fit_text("   ", box_w_in=5, box_h_in=1, family="Calibri", max_pt=30, min_pt=12)
    assert res.lines == []
    assert not res.overflow
