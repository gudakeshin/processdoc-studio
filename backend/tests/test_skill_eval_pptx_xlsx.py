"""
Skill Eval: PPTX and XLSX rendering quality.

Deterministic (no Claude API calls). Run with:
    cd backend && python -m pytest tests/test_skill_eval_pptx_xlsx.py -v --tb=short

Dimensions evaluated:
  PPTX — slide-type coverage, text fidelity, placeholder freedom, branding,
          slide-count match, diversity validation, completeness checks,
          topic-palette detection, QA truncation detection.
  XLSX — typed-cells path, markdown path, raci path, process-model path,
          fallback path, named styles, formula prefix, chart/table objects,
          multi-sheet, column width, freeze panes.

A summary table is printed at the end by the EvalReporter fixture.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest
from openpyxl import load_workbook
from pptx import Presentation

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def eval_results() -> dict[str, dict[str, Any]]:
    """Accumulates pass/fail/notes per eval ID across the session."""
    return {}


@pytest.fixture(scope="session")
def run_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("eval_outputs")


@pytest.fixture(scope="session")
def branding() -> dict[str, Any]:
    return {
        "primary_color": "#86BC25",
        "secondary_color": "#E8007C",
        "accent_light": "#EBF5D3",
        "accent_dark": "#5A8A00",
        "font_family": "Calibri",
        "font_family_header": "Calibri Light",
        "company_name": "Deloitte",
        "footer_text": "Deloitte.",
        "text_primary": "#1A1A1A",
        "text_inverse": "#FFFFFF",
        "neutral_light": "#AAAAAA",
        "neutral_dark": "#1A1A1A",
    }


# ---------------------------------------------------------------------------
# Helper: record result
# ---------------------------------------------------------------------------

def _record(results: dict, eval_id: str, passed: bool, notes: str = "") -> None:
    results[eval_id] = {"passed": passed, "notes": notes}


# ---------------------------------------------------------------------------
# PPTX helpers
# ---------------------------------------------------------------------------

def _render_pptx(slides: list[dict], run_dir: Path, branding: dict, suffix: str = "") -> Path:
    from app.core.deliverable_pptx import PPTXDeliverable

    out = run_dir / f"pptx_{suffix}.pptx"
    payload = {"pptx_slides": slides}
    result = PPTXDeliverable().render(payload, out.parent, branding)
    # rename if renderer used default name
    default = out.parent / "output.pptx"
    if default.exists() and not out.exists():
        default.rename(out)
    return out if out.exists() else (default if default.exists() else out)


def _all_text(pptx_path: Path) -> str:
    prs = Presentation(str(pptx_path))
    parts = []
    for slide in prs.slides:
        for shape in slide.shapes:
            # Table shapes: shape.text is empty — extract cell text directly.
            if hasattr(shape, "table"):
                for row in shape.table.rows:
                    for cell in row.cells:
                        parts.append(cell.text_frame.text)
            elif hasattr(shape, "text"):
                parts.append(shape.text)
    return " ".join(parts)


# ---------------------------------------------------------------------------
# PPTX Evals
# ---------------------------------------------------------------------------

class TestPPTXSlideTypeCoverage:
    """Each supported slide_type renders without raising an exception."""

    SLIDE_TYPES = [
        ("title", {"slide_type": "title", "title": "Eval Title Slide", "subtitle": "Subtitle line"}),
        ("bullets", {"slide_type": "bullets", "title": "Key Findings",
                     "bullets": ["Finding one", "Finding two", "Finding three"]}),
        ("stat_cards", {"slide_type": "stat_cards", "title": "Headline Metrics",
                        "stat_cards": [
                            {"stat": "42%", "label": "Efficiency Gain", "description": "Post automation"},
                            {"stat": "$1.2M", "label": "Cost Saved", "description": "Annualised"},
                            {"stat": "6 wks", "label": "Time-to-Value", "description": "Pilot to prod"},
                        ]}),
        ("column_cards", {"slide_type": "column_cards", "title": "Three Pillars",
                          "column_cards": [
                              {"heading": "People", "body": "Culture & change management"},
                              {"heading": "Process", "body": "Standardise and automate"},
                              {"heading": "Technology", "body": "SAP S/4HANA integration"},
                          ]}),
        ("stack_layers", {"slide_type": "stack_layers", "title": "Maturity Layers",
                          "stack_layers": [
                              {"label": "Foundation", "description": "Data governance & MDM"},
                              {"label": "Enablement", "description": "Analytics platform"},
                              {"label": "Optimisation", "description": "AI-driven insights"},
                          ]}),
        ("table", {"slide_type": "table", "title": "RACI Matrix",
                   "table": {"headers": ["Activity", "Owner", "Accountable", "Consulted"],
                              "rows": [["Invoice matching", "AP Team", "CFO", "IT"],
                                       ["Reconciliation", "Finance", "Controller", "Audit"]]}}),
        ("big_number", {"slide_type": "big_number", "title": "Scale",
                        "big_number": {"stat": "$4.8B", "label": "Total Spend Managed",
                                       "context": "Across 12 business units"}}),
        ("process_flow", {"slide_type": "process_flow", "title": "End-to-End Flow",
                          "process_flow": {"steps": [
                              {"label": "Intake", "description": "PO creation"},
                              {"label": "Approval", "description": "3-way match"},
                              {"label": "Payment", "description": "EFT disbursement"},
                          ]}}),
        ("section_divider", {"slide_type": "section_divider", "title": "Phase 2",
                             "subtitle": "Implementation"}),
        ("chart", {"slide_type": "chart", "title": "Savings Trend",
                   "chart": {"type": "bar", "title": "Annual Savings ($M)",
                              "series": [{"name": "Savings", "values": [1.1, 1.8, 2.3]}],
                              "categories": ["2022", "2023", "2024"]}}),
    ]

    @pytest.mark.parametrize("slide_type,slide_def", SLIDE_TYPES)
    def test_slide_type_renders(self, slide_type, slide_def, run_dir, branding, eval_results):
        eid = f"pptx.slide_type.{slide_type}"
        try:
            from app.core.deliverable_pptx import PPTXDeliverable

            payload = {"pptx_slides": [slide_def]}
            out = run_dir / f"pptx_type_{slide_type}.pptx"
            PPTXDeliverable().render(payload, run_dir, branding)
            default = run_dir / "output.pptx"
            if default.exists():
                default.rename(out)
            prs = Presentation(str(out))
            assert len(prs.slides) >= 1, "No slides rendered"
            _record(eval_results, eid, True)
        except Exception as exc:
            _record(eval_results, eid, False, str(exc))
            pytest.fail(f"slide_type='{slide_type}' raised: {exc}")


class TestPPTXTextFidelity:
    """Title and body text from the JSON must appear in the rendered PPTX."""

    def test_title_text_present(self, run_dir, branding, eval_results):
        eid = "pptx.text_fidelity.title"
        slides = [{"slide_type": "title", "title": "UNIQUE_EVAL_TITLE_XYZ",
                   "subtitle": "UNIQUE_EVAL_SUBTITLE_ABC"}]
        try:
            from app.core.deliverable_pptx import PPTXDeliverable

            PPTXDeliverable().render({"pptx_slides": slides}, run_dir, branding)
            out = run_dir / "output.pptx"
            text = _all_text(out)
            assert "UNIQUE_EVAL_TITLE_XYZ" in text, "Title not found in rendered PPTX"
            _record(eval_results, eid, True)
        except Exception as exc:
            _record(eval_results, eid, False, str(exc))
            pytest.fail(str(exc))

    def test_bullet_text_present(self, run_dir, branding, eval_results):
        eid = "pptx.text_fidelity.bullets"
        marker = "EVAL_BULLET_MARKER_987"
        slides = [{"slide_type": "bullets", "title": "Findings",
                   "bullets": [marker, "Second bullet", "Third bullet"]}]
        try:
            from app.core.deliverable_pptx import PPTXDeliverable

            PPTXDeliverable().render({"pptx_slides": slides}, run_dir, branding)
            out = run_dir / "output.pptx"
            text = _all_text(out)
            assert marker in text, f"Bullet marker '{marker}' not found in rendered PPTX"
            _record(eval_results, eid, True)
        except Exception as exc:
            _record(eval_results, eid, False, str(exc))
            pytest.fail(str(exc))

    def test_stat_card_values_present(self, run_dir, branding, eval_results):
        eid = "pptx.text_fidelity.stat_cards"
        slides = [{"slide_type": "stat_cards", "title": "Metrics",
                   "stat_cards": [
                       {"stat": "EVAL_STAT_99", "label": "EVAL_LABEL_A", "description": "desc"},
                       {"stat": "EVAL_STAT_88", "label": "EVAL_LABEL_B", "description": "desc"},
                       {"stat": "EVAL_STAT_77", "label": "EVAL_LABEL_C", "description": "desc"},
                   ]}]
        try:
            from app.core.deliverable_pptx import PPTXDeliverable

            PPTXDeliverable().render({"pptx_slides": slides}, run_dir, branding)
            out = run_dir / "output.pptx"
            text = _all_text(out)
            for marker in ["EVAL_STAT_99", "EVAL_STAT_88", "EVAL_LABEL_A"]:
                assert marker in text, f"'{marker}' not found in rendered PPTX"
            _record(eval_results, eid, True)
        except Exception as exc:
            _record(eval_results, eid, False, str(exc))
            pytest.fail(str(exc))

    def test_table_headers_present(self, run_dir, branding, eval_results):
        eid = "pptx.text_fidelity.table"
        slides = [{"slide_type": "table", "title": "Data Table",
                   "table": {"headers": ["EVAL_COL_A", "EVAL_COL_B", "EVAL_COL_C"],
                              "rows": [["Row1A", "Row1B", "Row1C"]]}}]
        try:
            from app.core.deliverable_pptx import PPTXDeliverable

            PPTXDeliverable().render({"pptx_slides": slides}, run_dir, branding)
            out = run_dir / "output.pptx"
            text = _all_text(out)
            assert "EVAL_COL_A" in text, "Table header not found in rendered PPTX"
            _record(eval_results, eid, True)
        except Exception as exc:
            _record(eval_results, eid, False, str(exc))
            pytest.fail(str(exc))


class TestPPTXPlaceholderFreedom:
    """Rendered PPTX must not contain known placeholder strings."""

    FORBIDDEN = ["TBC", "[placeholder]", "[todo]", "{{", "}}",
                 "Content pending", "Coming soon", "To be completed"]

    def test_no_placeholders_in_basic_deck(self, run_dir, branding, eval_results):
        eid = "pptx.placeholder_freedom"
        slides = [
            {"slide_type": "title", "title": "Finance Automation", "subtitle": "Deloitte Engagement"},
            {"slide_type": "bullets", "title": "Observations",
             "bullets": ["Manual processes add 3 days cycle time",
                         "Error rate at 4% on invoice matching",
                         "No automated exception workflow"]},
            {"slide_type": "stat_cards", "title": "Scale",
             "stat_cards": [
                 {"stat": "12K", "label": "Invoices/Month", "description": "Current volume"},
                 {"stat": "4%", "label": "Error Rate", "description": "Manual keying"},
                 {"stat": "3 days", "label": "Cycle Time", "description": "End-to-end"},
             ]},
        ]
        try:
            from app.core.deliverable_pptx import PPTXDeliverable

            PPTXDeliverable().render({"pptx_slides": slides}, run_dir, branding)
            out = run_dir / "output.pptx"
            text = _all_text(out)
            found = [p for p in self.FORBIDDEN if p.lower() in text.lower()]
            assert not found, f"Forbidden placeholder(s) found: {found}"
            _record(eval_results, eid, True)
        except Exception as exc:
            _record(eval_results, eid, False, str(exc))
            pytest.fail(str(exc))


class TestPPTXSlideCount:
    """Rendered slide count must match JSON slide count."""

    @pytest.mark.parametrize("n_slides", [1, 3, 8, 12])
    def test_slide_count_matches(self, n_slides, run_dir, branding, eval_results):
        eid = f"pptx.slide_count.{n_slides}"
        slides = [
            {"slide_type": "bullets", "title": f"Slide {i + 1}",
             "bullets": ["Point A", "Point B", "Point C"]}
            for i in range(n_slides)
        ]
        try:
            from app.core.deliverable_pptx import PPTXDeliverable

            PPTXDeliverable().render({"pptx_slides": slides}, run_dir, branding)
            out = run_dir / "output.pptx"
            prs = Presentation(str(out))
            assert len(prs.slides) == n_slides, (
                f"Expected {n_slides} slides, got {len(prs.slides)}"
            )
            _record(eval_results, eid, True)
        except Exception as exc:
            _record(eval_results, eid, False, str(exc))
            pytest.fail(str(exc))


class TestPPTXCompletenessValidator:
    """_validate_pptx_completeness correctly gates incomplete slide JSON."""

    def test_valid_deck_passes(self, eval_results):
        eid = "pptx.completeness.valid_deck_passes"
        from app.services.deliverable_quality import _validate_pptx_completeness

        slides = [
            {"slide_type": "title", "title": "T"},
            {"slide_type": "bullets", "title": "B",
             "bullets": ["a", "b"]},
            {"slide_type": "stat_cards", "title": "S",
             "stat_cards": [{"stat": "1"}, {"stat": "2"}]},
            {"slide_type": "column_cards", "title": "C",
             "column_cards": [{"heading": "A"}, {"heading": "B"}, {"heading": "C"}]},
        ]
        ok, issues = _validate_pptx_completeness(json.dumps(slides))
        _record(eval_results, eid, ok, str(issues) if not ok else "")
        assert ok, f"Valid deck should pass completeness check. Issues: {issues}"

    def test_empty_stat_cards_fails(self, eval_results):
        eid = "pptx.completeness.empty_stat_cards_fails"
        from app.services.deliverable_quality import _validate_pptx_completeness

        slides = [{"slide_type": "stat_cards", "title": "Metrics", "stat_cards": []}]
        ok, issues = _validate_pptx_completeness(json.dumps(slides))
        _record(eval_results, eid, not ok, "Should have flagged empty stat_cards" if ok else "")
        assert not ok, "stat_cards with 0 items should fail completeness"
        assert any("stat_cards" in i for i in issues)

    def test_bullet_heavy_deck_flagged(self, eval_results):
        eid = "pptx.completeness.bullet_heavy_flagged"
        from app.services.deliverable_quality import _validate_pptx_completeness

        slides = [
            {"slide_type": "bullets", "title": f"Slide {i}", "bullets": ["a", "b"]}
            for i in range(8)
        ]
        ok, issues = _validate_pptx_completeness(json.dumps(slides))
        diversity_flagged = any("variety" in i.lower() or "bullets" in i.lower() for i in issues)
        _record(eval_results, eid, diversity_flagged,
                "Expected diversity warning" if not diversity_flagged else "")
        assert diversity_flagged, f"Bullet-heavy deck should trigger diversity warning. Issues: {issues}"

    def test_process_flow_needs_two_steps(self, eval_results):
        eid = "pptx.completeness.process_flow_min_steps"
        from app.services.deliverable_quality import _validate_pptx_completeness

        slides = [{"slide_type": "process_flow", "title": "Flow",
                   "process_flow": {"steps": [{"label": "Only step"}]}}]
        ok, issues = _validate_pptx_completeness(json.dumps(slides))
        _record(eval_results, eid, not ok, "Should fail with 1 step" if ok else "")
        assert not ok, "process_flow with 1 step should fail"

    def test_dict_format_slides_key(self, eval_results):
        eid = "pptx.completeness.dict_format"
        from app.services.deliverable_quality import _validate_pptx_completeness

        payload = {"slides": [{"slide_type": "bullets", "title": "B",
                                "bullets": ["a", "b"]}]}
        ok, issues = _validate_pptx_completeness(json.dumps(payload))
        _record(eval_results, eid, True)  # just check it doesn't crash
        # either pass or fail is acceptable — just verify no exception


class TestPPTXTopicPaletteDetection:
    """Topic-palette auto-detection returns correct palette overrides."""

    @pytest.mark.parametrize("process_name,expected_color", [
        ("Finance Close Process", "#990011"),
        ("Digital Transformation Strategy", "#065A82"),
        ("HR Talent Acquisition", "#6D2E46"),
        ("ESG Sustainability Reporting", "#2C5F2D"),
        ("Supply Chain Optimisation", ""),  # no override
    ])
    def test_palette_detection(self, process_name, expected_color, eval_results):
        eid = f"pptx.topic_palette.{process_name[:20].replace(' ', '_')}"
        from app.core.deliverable_pptx import _pick_topic_palette

        palette = _pick_topic_palette(process_name)
        if expected_color:
            got = palette.get("primary_color", "")
            passed = got == expected_color
            _record(eval_results, eid, passed,
                    f"Expected {expected_color}, got {got}" if not passed else "")
            assert passed, f"Process '{process_name}': expected color {expected_color}, got {got}"
        else:
            passed = palette == {}
            _record(eval_results, eid, passed,
                    f"Expected empty palette, got {palette}" if not passed else "")
            assert passed, f"Process '{process_name}': expected no palette override, got {palette}"


class TestPPTXQATruncationDetection:
    """pptx_qa truncation detector finds known bad signatures."""

    def test_known_truncation_signature_detected(self, run_dir, eval_results):
        eid = "pptx.qa.truncation_detection"
        from app.core.pptx_qa import _find_truncations

        # These are in TRUNCATION_SIGNATURES
        bad_text = "The system supports continuou processing across ide the platform"
        found = _find_truncations(bad_text)
        passed = len(found) >= 2
        _record(eval_results, eid, passed,
                f"Found: {found}" if not passed else f"Detected: {found}")
        assert passed, f"Expected >=2 truncation hits, got: {found}"

    def test_clean_text_not_flagged(self, eval_results):
        eid = "pptx.qa.clean_text_not_flagged"
        from app.core.pptx_qa import _find_truncations

        clean = "This slide presents key findings from the engagement."
        found = _find_truncations(clean)
        _record(eval_results, eid, not found,
                f"False positive truncations: {found}" if found else "")
        assert not found, f"Clean text produced false truncation hits: {found}"

    def test_validate_pptx_against_slides_missing_file(self, run_dir, eval_results):
        eid = "pptx.qa.missing_file_detected"
        from app.core.pptx_qa import validate_pptx_against_slides

        report = validate_pptx_against_slides(
            run_dir / "nonexistent_file.pptx",
            [{"slide_type": "title", "title": "Test"}],
        )
        passed = report["status"] == "fail"
        _record(eval_results, eid, passed,
                f"Status={report['status']}" if not passed else "")
        assert passed, "Missing file should produce status=fail"


class TestPPTXQASlideValidation:
    """validate_pptx_against_slides cross-checks rendered artifact vs JSON."""

    def test_pass_on_well_formed_deck(self, run_dir, branding, eval_results):
        eid = "pptx.qa.slide_validation_pass"
        from app.core.deliverable_pptx import PPTXDeliverable
        from app.core.pptx_qa import validate_pptx_against_slides

        slides = [
            {"slide_type": "title", "title": "Procurement Transformation", "subtitle": "Acme Corp"},
            {"slide_type": "bullets", "title": "Current State",
             "bullets": ["Manual PO process", "No e-invoicing", "3-way match takes 5 days"]},
        ]
        PPTXDeliverable().render({"pptx_slides": slides}, run_dir, branding)
        out = run_dir / "output.pptx"
        report = validate_pptx_against_slides(out, slides)
        passed = report["status"] == "pass"
        _record(eval_results, eid, passed,
                f"Issues: {report.get('issues')}" if not passed else "")
        assert passed, f"Well-formed deck should pass QA. Issues: {report.get('issues')}"


# ---------------------------------------------------------------------------
# XLSX Evals
# ---------------------------------------------------------------------------

class TestXLSXDataPaths:
    """All five data source paths write a valid .xlsx without raising."""

    def test_typed_cells_path(self, run_dir, branding, eval_results):
        eid = "xlsx.path.typed_cells"
        from app.core.deliverable_xlsx import XLSXDeliverable

        cells = [
            {"sheet": "Output", "row": 1, "col": 1, "value": "Activity",
             "named_style": "brand_header"},
            {"sheet": "Output", "row": 1, "col": 2, "value": "Owner",
             "named_style": "brand_header"},
            {"sheet": "Output", "row": 2, "col": 1, "value": "Invoice matching"},
            {"sheet": "Output", "row": 2, "col": 2, "value": "AP Team"},
        ]
        payload = {"xlsx_cells": cells}
        out = run_dir / "xlsx_typed_cells.xlsx"
        try:
            result = XLSXDeliverable().render(payload, run_dir, branding)
            if result and (run_dir / "output.xlsx").exists():
                (run_dir / "output.xlsx").rename(out)
            wb = load_workbook(str(out))
            ws = wb.active
            assert ws["A1"].value == "Activity"
            assert ws["A2"].value == "Invoice matching"
            _record(eval_results, eid, True)
        except Exception as exc:
            _record(eval_results, eid, False, str(exc))
            pytest.fail(str(exc))

    def test_markdown_path(self, run_dir, branding, eval_results):
        eid = "xlsx.path.markdown"
        from app.core.deliverable_xlsx import XLSXDeliverable

        md = "| Step | Owner | SLA |\n|---|---|---|\n| Receive Invoice | AP | 1 day |\n| Match PO | Finance | 2 days |"
        payload = {"xlsx_markdown": md}
        out = run_dir / "xlsx_markdown.xlsx"
        try:
            XLSXDeliverable().render(payload, run_dir, branding)
            if (run_dir / "output.xlsx").exists():
                (run_dir / "output.xlsx").rename(out)
            wb = load_workbook(str(out))
            ws = wb.active
            # Header row
            header_vals = [ws.cell(1, c).value for c in range(1, 4)]
            assert "Step" in header_vals or "step" in [str(v).lower() for v in header_vals if v]
            _record(eval_results, eid, True)
        except Exception as exc:
            _record(eval_results, eid, False, str(exc))
            pytest.fail(str(exc))

    def test_raci_path(self, run_dir, branding, eval_results):
        eid = "xlsx.path.raci"
        from app.core.deliverable_xlsx import XLSXDeliverable

        raci = "| Activity | CFO | AP Lead | IT | Audit |\n|---|---|---|---|---|\n| Month-end close | A | R | C | I |"
        payload = {"raci_markdown": raci}
        out = run_dir / "xlsx_raci.xlsx"
        try:
            XLSXDeliverable().render(payload, run_dir, branding)
            if (run_dir / "output.xlsx").exists():
                (run_dir / "output.xlsx").rename(out)
            wb = load_workbook(str(out))
            ws = wb.active
            assert ws.max_row >= 2
            _record(eval_results, eid, True)
        except Exception as exc:
            _record(eval_results, eid, False, str(exc))
            pytest.fail(str(exc))

    def test_process_model_path(self, run_dir, branding, eval_results):
        eid = "xlsx.path.process_model"
        from app.core.deliverable_xlsx import XLSXDeliverable

        pm = {
            "process_name": "Order-to-Cash",
            "activities": [
                {"name": "Order intake", "owner": "Sales", "duration": "1h"},
                {"name": "Credit check", "owner": "Finance", "duration": "30m"},
            ],
        }
        payload = {"process_model": pm}
        out = run_dir / "xlsx_process_model.xlsx"
        try:
            XLSXDeliverable().render(payload, run_dir, branding)
            if (run_dir / "output.xlsx").exists():
                (run_dir / "output.xlsx").rename(out)
            wb = load_workbook(str(out))
            assert wb.active.max_row >= 1
            _record(eval_results, eid, True)
        except Exception as exc:
            _record(eval_results, eid, False, str(exc))
            pytest.fail(str(exc))

    def test_fallback_path(self, run_dir, branding, eval_results):
        eid = "xlsx.path.fallback"
        from app.core.deliverable_xlsx import XLSXDeliverable

        payload = {"narrative_md": "Some narrative content for this engagement."}
        out = run_dir / "xlsx_fallback.xlsx"
        try:
            XLSXDeliverable().render(payload, run_dir, branding)
            if (run_dir / "output.xlsx").exists():
                (run_dir / "output.xlsx").rename(out)
            wb = load_workbook(str(out))
            ws = wb.active
            # Fallback writes ["Section", "Content"]
            assert ws["A1"].value in ("Section", "Content", "Summary")
            _record(eval_results, eid, True)
        except Exception as exc:
            _record(eval_results, eid, False, str(exc))
            pytest.fail(str(exc))


class TestXLSXFormulasAndSpecialCells:
    """Formulas, charts, and table objects are handled correctly."""

    def test_formula_gets_equals_prefix(self, run_dir, branding, eval_results):
        eid = "xlsx.formula.prefix"
        from app.core.deliverable_xlsx import XLSXDeliverable, apply_cells_to_workbook
        from openpyxl import Workbook

        wb = Workbook()
        cells = [
            {"sheet": "Sheet1", "row": 1, "col": 1, "value": "Base"},
            {"sheet": "Sheet1", "row": 1, "col": 2, "value": 100},
            {"sheet": "Sheet1", "row": 2, "col": 1, "value": "Total"},
            {"sheet": "Sheet1", "row": 2, "col": 2, "formula": "SUM(B1:B1)"},
        ]
        try:
            apply_cells_to_workbook(wb, cells)
            ws = wb.active
            formula_cell = ws["B2"]
            assert str(formula_cell.value or "").startswith("="), (
                f"Formula cell should start with '=', got: {formula_cell.value!r}"
            )
            _record(eval_results, eid, True)
        except Exception as exc:
            _record(eval_results, eid, False, str(exc))
            pytest.fail(str(exc))

    def test_chart_added_without_error(self, run_dir, branding, eval_results):
        eid = "xlsx.chart.added"
        from app.core.deliverable_xlsx import apply_cells_to_workbook
        from openpyxl import Workbook

        wb = Workbook()
        cells = [
            {"sheet": "Charts", "row": 1, "col": 1, "value": "Month"},
            {"sheet": "Charts", "row": 1, "col": 2, "value": "Revenue"},
            {"sheet": "Charts", "row": 2, "col": 1, "value": "Jan"},
            {"sheet": "Charts", "row": 2, "col": 2, "value": 120},
            {"sheet": "Charts", "row": 3, "col": 1, "value": "Feb"},
            {"sheet": "Charts", "row": 3, "col": 2, "value": 145},
            {
                "_type": "chart", "sheet": "Charts",
                "type": "bar", "title": "Monthly Revenue",
                "min_row": 1, "max_row": 3, "min_col": 1, "max_col": 2,
                "titles_from_data": True, "cats_col": 1,
                "anchor": "D2", "height": 10, "width": 18,
            },
        ]
        try:
            apply_cells_to_workbook(wb, cells)
            ws = wb["Charts"]
            assert len(ws._charts) >= 1, "Chart was not added to worksheet"
            _record(eval_results, eid, True)
        except Exception as exc:
            _record(eval_results, eid, False, str(exc))
            pytest.fail(str(exc))

    def test_table_added_without_error(self, run_dir, branding, eval_results):
        eid = "xlsx.table.added"
        from app.core.deliverable_xlsx import apply_cells_to_workbook
        from openpyxl import Workbook

        wb = Workbook()
        cells = [
            {"sheet": "Data", "row": 1, "col": 1, "value": "Activity"},
            {"sheet": "Data", "row": 1, "col": 2, "value": "Owner"},
            {"sheet": "Data", "row": 2, "col": 1, "value": "Invoice check"},
            {"sheet": "Data", "row": 2, "col": 2, "value": "AP Lead"},
            {
                "_type": "table", "sheet": "Data",
                "ref": "A1:B2", "display_name": "ActivityTable",
                "table_style": "TableStyleMedium9",
            },
        ]
        try:
            apply_cells_to_workbook(wb, cells)
            ws = wb["Data"]
            assert len(ws.tables) >= 1, "Table was not registered on worksheet"
            _record(eval_results, eid, True)
        except Exception as exc:
            _record(eval_results, eid, False, str(exc))
            pytest.fail(str(exc))

    def test_multi_sheet_split(self, run_dir, branding, eval_results):
        eid = "xlsx.multi_sheet"
        from app.core.deliverable_xlsx import apply_cells_to_workbook
        from openpyxl import Workbook

        wb = Workbook()
        cells = [
            {"sheet": "Assumptions", "row": 1, "col": 1, "value": "Discount Rate"},
            {"sheet": "Assumptions", "row": 2, "col": 1, "value": "0.08"},
            {"sheet": "Model", "row": 1, "col": 1, "value": "Year"},
            {"sheet": "Model", "row": 1, "col": 2, "value": "NPV"},
            {"sheet": "Model", "row": 2, "col": 1, "value": 2024},
            {"sheet": "Model", "row": 2, "col": 2, "formula": "Assumptions!A2*1000"},
        ]
        try:
            apply_cells_to_workbook(wb, cells)
            sheet_names = wb.sheetnames
            has_assumptions = any("Assumptions" in n for n in sheet_names)
            has_model = any("Model" in n for n in sheet_names)
            passed = has_assumptions and has_model
            _record(eval_results, eid, passed,
                    f"Sheets: {sheet_names}" if not passed else "")
            assert passed, f"Expected Assumptions and Model sheets, got: {sheet_names}"
        except Exception as exc:
            _record(eval_results, eid, False, str(exc))
            pytest.fail(str(exc))


class TestXLSXNamedStyles:
    """Named styles (brand_header, brand_input, etc.) are registered on the workbook."""

    @pytest.mark.parametrize("style_name", [
        "brand_header", "brand_total", "brand_input", "brand_calc",
        "brand_link", "brand_variance_pos", "brand_variance_neg",
        "brand_currency", "brand_pct",
    ])
    def test_named_style_registered(self, style_name, eval_results):
        eid = f"xlsx.named_style.{style_name}"
        from app.core.deliverable_xlsx import _build_named_styles

        styles = _build_named_styles("86BC25")
        names = {s.name for s in styles}
        passed = style_name in names
        _record(eval_results, eid, passed,
                f"Missing style. Available: {sorted(names)}" if not passed else "")
        assert passed, f"Named style '{style_name}' not built. Available: {sorted(names)}"

    def test_header_style_has_correct_fill(self, eval_results):
        eid = "xlsx.named_style.brand_header_fill"
        from app.core.deliverable_xlsx import _build_named_styles

        styles = _build_named_styles("FF5733")
        header = next((s for s in styles if s.name == "brand_header"), None)
        assert header is not None
        fill_color = header.fill.fgColor.rgb if header.fill and header.fill.fgColor else ""
        passed = "FF5733" in fill_color.upper()
        _record(eval_results, eid, passed,
                f"Expected FF5733 in fill, got: {fill_color}" if not passed else "")
        assert passed, f"brand_header fill should be FF5733, got: {fill_color}"


class TestXLSXStructuralChecks:
    """Freeze panes and auto-width are applied."""

    def test_freeze_panes_at_a2(self, run_dir, branding, eval_results):
        eid = "xlsx.structure.freeze_panes"
        from app.core.deliverable_xlsx import XLSXDeliverable

        md = "| Col1 | Col2 |\n|---|---|\n| A | B |\n| C | D |"
        payload = {"xlsx_markdown": md}
        out = run_dir / "xlsx_freeze.xlsx"
        try:
            XLSXDeliverable().render(payload, run_dir, branding)
            if (run_dir / "output.xlsx").exists():
                (run_dir / "output.xlsx").rename(out)
            wb = load_workbook(str(out))
            ws = wb.active
            fp = ws.freeze_panes
            passed = fp is not None and str(fp).upper() == "A2"
            _record(eval_results, eid, passed,
                    f"freeze_panes={fp!r}" if not passed else "")
            assert passed, f"Expected freeze at A2, got: {fp!r}"
        except Exception as exc:
            _record(eval_results, eid, False, str(exc))
            pytest.fail(str(exc))

    def test_columns_have_nondefault_width(self, run_dir, branding, eval_results):
        eid = "xlsx.structure.auto_width"
        from app.core.deliverable_xlsx import XLSXDeliverable

        md = "| Very Long Column Header Name | Another Long Header |\n|---|---|\n| Short | Data |"
        payload = {"xlsx_markdown": md}
        out = run_dir / "xlsx_width.xlsx"
        try:
            XLSXDeliverable().render(payload, run_dir, branding)
            if (run_dir / "output.xlsx").exists():
                (run_dir / "output.xlsx").rename(out)
            wb = load_workbook(str(out))
            ws = wb.active
            from openpyxl.utils import get_column_letter
            col_a_width = ws.column_dimensions[get_column_letter(1)].width
            passed = col_a_width > 8  # default is 8; auto-size should exceed it
            _record(eval_results, eid, passed,
                    f"col_a_width={col_a_width}" if not passed else "")
            assert passed, f"Column A width should exceed 8 (auto-sized), got: {col_a_width}"
        except Exception as exc:
            _record(eval_results, eid, False, str(exc))
            pytest.fail(str(exc))


class TestXLSXQualitySignals:
    """extract_quality_signals returns useful metadata from a rendered file."""

    def test_quality_signals_populated(self, run_dir, branding, eval_results):
        eid = "xlsx.quality_signals"
        from app.core.deliverable_xlsx import XLSXDeliverable

        cells = [
            {"sheet": "Sheet1", "row": 1, "col": 1, "value": "H1"},
            {"sheet": "Sheet1", "row": 1, "col": 2, "value": "H2"},
            {"sheet": "Sheet1", "row": 2, "col": 1, "value": "Val1"},
            {"sheet": "Sheet1", "row": 2, "col": 2, "value": "Val2"},
            {"sheet": "Sheet2", "row": 1, "col": 1, "value": "Other"},
        ]
        payload = {"xlsx_cells": cells}
        out = run_dir / "xlsx_qs.xlsx"
        try:
            XLSXDeliverable().render(payload, run_dir, branding)
            if (run_dir / "output.xlsx").exists():
                (run_dir / "output.xlsx").rename(out)
            signals = XLSXDeliverable().extract_quality_signals(out)
            passed = (
                signals.get("sheet_count", 0) >= 2
                and signals.get("max_rows", 0) >= 2
                and signals.get("max_cols", 0) >= 2
            )
            _record(eval_results, eid, passed, str(signals) if not passed else "")
            assert passed, f"Quality signals incomplete: {signals}"
        except Exception as exc:
            _record(eval_results, eid, False, str(exc))
            pytest.fail(str(exc))


# ---------------------------------------------------------------------------
# Regression tests for the 4 improvement opportunities
# ---------------------------------------------------------------------------

class TestPPTXCompletenessTableFix:
    """table slide type is checked correctly (rows key, not list-len of the dict)."""

    def test_table_with_rows_passes(self, eval_results):
        eid = "pptx.completeness.table_with_rows_passes"
        from app.services.deliverable_quality import _validate_pptx_completeness

        slides = [{"slide_type": "table", "title": "RACI",
                   "table": {"headers": ["Activity", "Owner"],
                              "rows": [["Invoice check", "AP Lead"]]}}]
        ok, issues = _validate_pptx_completeness(json.dumps(slides))
        _record(eval_results, eid, ok, str(issues) if not ok else "")
        assert ok, f"Table with rows should pass completeness. Issues: {issues}"

    def test_table_with_empty_rows_fails(self, eval_results):
        eid = "pptx.completeness.table_empty_rows_fails"
        from app.services.deliverable_quality import _validate_pptx_completeness

        slides = [{"slide_type": "table", "title": "Empty Table",
                   "table": {"headers": ["A", "B"], "rows": []}}]
        ok, issues = _validate_pptx_completeness(json.dumps(slides))
        _record(eval_results, eid, not ok, "Should fail with no rows" if ok else "")
        assert not ok, "Table with rows=[] should fail completeness"
        assert any("table" in i.lower() for i in issues), f"Issues: {issues}"

    def test_table_with_missing_rows_key_fails(self, eval_results):
        eid = "pptx.completeness.table_missing_rows_key_fails"
        from app.services.deliverable_quality import _validate_pptx_completeness

        slides = [{"slide_type": "table", "title": "No Rows Key",
                   "table": {"headers": ["A", "B"]}}]
        ok, issues = _validate_pptx_completeness(json.dumps(slides))
        _record(eval_results, eid, not ok, "Should fail without rows key" if ok else "")
        assert not ok, "Table missing rows key should fail completeness"


class TestPPTXCompletenessEmptyCardContent:
    """column_cards and stack_layers with empty heading/label are caught."""

    def test_column_cards_empty_heading_fails(self, eval_results):
        eid = "pptx.completeness.column_cards_empty_heading"
        from app.services.deliverable_quality import _validate_pptx_completeness

        slides = [{"slide_type": "column_cards", "title": "Pillars",
                   "column_cards": [{"heading": "People"}, {"heading": ""}, {"heading": "Tech"}]}]
        ok, issues = _validate_pptx_completeness(json.dumps(slides))
        _record(eval_results, eid, not ok, "Should flag empty heading" if ok else "")
        assert not ok, "column_card with empty 'heading' should fail"
        assert any("heading" in i for i in issues), f"Issues: {issues}"

    def test_stack_layers_empty_label_fails(self, eval_results):
        eid = "pptx.completeness.stack_layers_empty_label"
        from app.services.deliverable_quality import _validate_pptx_completeness

        slides = [{"slide_type": "stack_layers", "title": "Layers",
                   "stack_layers": [{"label": "Foundation"}, {"label": ""}, {"label": "Optimisation"}]}]
        ok, issues = _validate_pptx_completeness(json.dumps(slides))
        _record(eval_results, eid, not ok, "Should flag empty label" if ok else "")
        assert not ok, "stack_layer with empty 'label' should fail"
        assert any("label" in i for i in issues), f"Issues: {issues}"

    def test_column_cards_all_filled_passes(self, eval_results):
        eid = "pptx.completeness.column_cards_all_filled_passes"
        from app.services.deliverable_quality import _validate_pptx_completeness

        slides = [{"slide_type": "column_cards", "title": "Pillars",
                   "column_cards": [{"heading": "People", "body": "Culture & change"},
                                    {"heading": "Process", "body": "Standardise"},
                                    {"heading": "Tech", "body": "Automate"}]}]
        ok, issues = _validate_pptx_completeness(json.dumps(slides))
        _record(eval_results, eid, ok, str(issues) if not ok else "")
        assert ok, f"Well-formed column_cards should pass. Issues: {issues}"


class TestPPTXPaletteHighestMatchCount:
    """Ambiguous process names resolve to the palette with most keyword hits."""

    @pytest.mark.parametrize("process_name,expected_color,reason", [
        # Two finance keywords beats one ESG keyword
        ("Carbon Tax Audit", "#990011", "finance: tax+audit=2 > esg: carbon=1"),
        # Three tech keywords unambiguous
        ("Digital AI Cloud Platform", "#065A82", "tech: digital+ai+cloud+platform=4"),
        # Pure ESG still wins
        ("ESG Climate Sustainability Report", "#2C5F2D", "esg: esg+climate+sustainability=3"),
        # No keywords → default palette
        ("General Operations Review", "", "no palette keyword present"),
    ])
    def test_highest_match_count_wins(self, process_name, expected_color, reason, eval_results):
        eid = f"pptx.palette.highest_match.{process_name[:18].replace(' ', '_')}"
        from app.core.deliverable_pptx import _pick_topic_palette

        palette = _pick_topic_palette(process_name)
        got = palette.get("primary_color", "")
        passed = got == expected_color
        _record(eval_results, eid, passed,
                f"Expected {expected_color!r}, got {got!r} ({reason})" if not passed else reason)
        assert passed, (
            f"Process '{process_name}': expected {expected_color!r}, got {got!r}. ({reason})"
        )


class TestXLSXFreezeOnTypedCellsPath:
    """Typed-cells path (apply_cells_to_workbook) sets freeze_panes at A2."""

    def test_typed_cells_freeze_panes(self, run_dir, branding, eval_results):
        eid = "xlsx.structure.freeze_panes_typed_cells"
        from app.core.deliverable_xlsx import XLSXDeliverable

        cells = [
            {"sheet": "Output", "row": 1, "col": 1, "value": "Activity", "named_style": "brand_header"},
            {"sheet": "Output", "row": 1, "col": 2, "value": "Owner", "named_style": "brand_header"},
            {"sheet": "Output", "row": 2, "col": 1, "value": "Invoice check"},
            {"sheet": "Output", "row": 2, "col": 2, "value": "AP Lead"},
        ]
        out = run_dir / "xlsx_freeze_typed.xlsx"
        try:
            XLSXDeliverable().render({"xlsx_cells": cells}, run_dir, branding)
            if (run_dir / "output.xlsx").exists():
                (run_dir / "output.xlsx").rename(out)
            wb = load_workbook(str(out))
            ws = wb.active
            fp = ws.freeze_panes
            passed = fp is not None and str(fp).upper() == "A2"
            _record(eval_results, eid, passed,
                    f"freeze_panes={fp!r}" if not passed else "")
            assert passed, f"Typed-cells path should freeze at A2, got: {fp!r}"
        except Exception as exc:
            _record(eval_results, eid, False, str(exc))
            pytest.fail(str(exc))


# ---------------------------------------------------------------------------
# Summary reporter — prints eval table after all tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def eval_summary_reporter(eval_results):
    """Print a formatted eval scorecard after the session."""
    yield
    if not eval_results:
        return

    passed = [k for k, v in eval_results.items() if v["passed"]]
    failed = [k for k, v in eval_results.items() if not v["passed"]]
    total = len(eval_results)
    pct = round(100 * len(passed) / total) if total else 0

    SEP = "─" * 72
    print(f"\n\n{'=' * 72}")
    print(f"  SKILL EVAL SCORECARD  |  {len(passed)}/{total} passed ({pct}%)")
    print("=" * 72)

    # Group by prefix (pptx / xlsx)
    for prefix in ("pptx", "xlsx"):
        group = {k: v for k, v in eval_results.items() if k.startswith(prefix)}
        if not group:
            continue
        gp = sum(1 for v in group.values() if v["passed"])
        print(f"\n  {prefix.upper()} — {gp}/{len(group)} passed")
        print(SEP)
        for eid, result in sorted(group.items()):
            status = "PASS" if result["passed"] else "FAIL"
            notes = f"  # {result['notes'][:60]}" if result["notes"] else ""
            print(f"  [{status}]  {eid}{notes}")

    if failed:
        print(f"\n{'=' * 72}")
        print("  FAILED — improvement opportunities")
        print(SEP)
        for eid in failed:
            notes = eval_results[eid]["notes"]
            print(f"  ✗  {eid}")
            if notes:
                print(f"       {notes[:120]}")

    print(f"\n{'=' * 72}\n")
