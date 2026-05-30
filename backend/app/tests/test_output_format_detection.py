"""Tests for output format detection from natural-language instructions."""

import pytest

from app.services.output_format_detection import (
    detect_explicit_output_formats,
    detect_standalone_excel_intent,
    is_financial_model_intent,
    resolve_output_formats,
)


class TestExplicitFormats:
    def test_in_excel(self):
        assert "xlsx" in detect_explicit_output_formats("Build a financial model in Excel")

    def test_excel_only(self):
        assert detect_explicit_output_formats("only excel spreadsheet") == ["xlsx"]


class TestStandaloneExcel:
    @pytest.mark.parametrize(
        "instruction",
        [
            "I need Excel for this analysis",
            "Please give me an Excel workbook",
            "Can you build a spreadsheet?",
        ],
    )
    def test_standalone_excel_without_deck(self, instruction: str) -> None:
        assert detect_standalone_excel_intent(instruction) is True

    def test_excel_instead_of_ppt(self):
        assert detect_standalone_excel_intent("I want Excel instead of PPT") is True


class TestResolveOutputFormats:
    def test_financial_model_is_xlsx_only(self):
        ids, reps, _ = resolve_output_formats("Create a three-statement financial model")
        assert ids == ["xlsx"]
        assert reps.get("xlsx") == "xlsx"

    def test_proposal_alone_defaults_to_docx_pptx(self):
        ids, _, _ = resolve_output_formats("Create a proposal for the CFO")
        assert "docx" in ids
        assert "pptx" in ids

    def test_excel_overrides_proposal_pptx(self):
        ids, _, rationale = resolve_output_formats(
            "Create a proposal but deliver it in Excel only"
        )
        assert ids == ["xlsx"]
        assert rationale

    def test_i_need_excel(self):
        ids, _, _ = resolve_output_formats("I need Excel with revenue scenarios")
        assert ids == ["xlsx"]
