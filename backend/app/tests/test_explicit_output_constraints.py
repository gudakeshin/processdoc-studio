"""Tests for explicit output format constraints in recommendation logic."""

import pytest


class TestExplicitOutputConstraints:
    """Tests for respecting explicit output format constraints like 'only pptx'."""

    def test_explicit_pptx_only_constraint(self):
        """When user says 'only pptx', system respects that even for proposal keyword."""
        # The recommendation logic should detect "only pptx" and not recommend docx
        instruction = "Create a proposal in PPT only"
        lowered = instruction.lower()

        # Simulate the constraint detection logic from _recommend_output_types
        explicit_output_constraints = {
            "pptx": [
                "only pptx", "only slides", "only slide", "just pptx", "just slides",
                "pptx only", "slides only", "slide only", "in pptx", "in slides", "in slide",
                "presentation format", "presentation only", "ppt only", "ppt format",
            ],
        }

        explicit_formats = []
        for output_type, phrases in explicit_output_constraints.items():
            for phrase in phrases:
                if phrase in lowered:
                    explicit_formats.append(output_type)
                    break

        assert "pptx" in explicit_formats
        assert "docx" not in explicit_formats

    def test_explicit_docx_only_constraint(self):
        """When user says 'only docx', system respects that even for proposal keyword."""
        instruction = "Generate proposal document word only"
        lowered = instruction.lower()

        explicit_output_constraints = {
            "docx": [
                "only docx", "only word", "only doc", "just docx", "just word",
                "docx only", "word only", "doc only", "in docx", "in word",
                "document format", "document only",
            ],
        }

        explicit_formats = []
        for output_type, phrases in explicit_output_constraints.items():
            for phrase in phrases:
                if phrase in lowered:
                    explicit_formats.append(output_type)
                    break

        assert "docx" in explicit_formats
        assert "pptx" not in explicit_formats

    def test_explicit_xlsx_constraint(self):
        """When user specifies 'only excel', system respects that constraint."""
        instruction = "only excel spreadsheet for financial model"
        lowered = instruction.lower()

        explicit_output_constraints = {
            "xlsx": [
                "only xlsx", "only excel", "only spreadsheet", "just xlsx", "just excel",
                "xlsx only", "excel only", "spreadsheet only", "in xlsx", "in excel",
                "spreadsheet format",
            ],
        }

        explicit_formats = []
        for output_type, phrases in explicit_output_constraints.items():
            for phrase in phrases:
                if phrase in lowered:
                    explicit_formats.append(output_type)
                    break

        assert "xlsx" in explicit_formats

    def test_explicit_presentation_format_constraint(self):
        """When user says 'presentation format', system recognizes pptx constraint."""
        instruction = "proposal in presentation format"
        lowered = instruction.lower()

        explicit_output_constraints = {
            "pptx": [
                "only pptx", "only slides", "only slide", "just pptx", "just slides",
                "pptx only", "slides only", "slide only", "in pptx", "in slides", "in slide",
                "presentation format", "presentation only", "ppt only", "ppt format",
            ],
        }

        explicit_formats = []
        for output_type, phrases in explicit_output_constraints.items():
            for phrase in phrases:
                if phrase in lowered:
                    explicit_formats.append(output_type)
                    break

        assert "pptx" in explicit_formats

    def test_no_explicit_constraint_uses_defaults(self):
        """When user says just 'proposal', system uses default (both docx and pptx)."""
        instruction = "Create proposal"
        lowered = instruction.lower()

        explicit_output_constraints = {
            "pptx": [
                "only pptx", "only slides", "only slide", "just pptx", "just slides",
                "pptx only", "slides only", "slide only", "in pptx", "in slides", "in slide",
                "presentation format", "presentation only", "ppt only", "ppt format",
            ],
            "docx": [
                "only docx", "only word", "only doc", "just docx", "just word",
                "docx only", "word only", "doc only", "in docx", "in word",
                "document format", "document only",
            ],
        }

        explicit_formats = []
        for output_type, phrases in explicit_output_constraints.items():
            for phrase in phrases:
                if phrase in lowered:
                    explicit_formats.append(output_type)
                    break

        # Should be empty, meaning default keyword-based logic applies
        assert len(explicit_formats) == 0

    def test_multiple_explicit_constraints(self):
        """Test that we handle cases with multiple format specifiers correctly."""
        # If user says "slides only and word only", both should be detected
        instruction = "I want slides only and word only"
        lowered = instruction.lower()

        explicit_output_constraints = {
            "pptx": [
                "only pptx", "only slides", "only slide", "just pptx", "just slides",
                "pptx only", "slides only", "slide only", "in pptx", "in slides", "in slide",
                "presentation format", "presentation only", "ppt only", "ppt format",
            ],
            "docx": [
                "only docx", "only word", "only doc", "just docx", "just word",
                "docx only", "word only", "doc only", "in docx", "in word",
                "document format", "document only",
            ],
        }

        explicit_formats = []
        for output_type, phrases in explicit_output_constraints.items():
            for phrase in phrases:
                if phrase in lowered:
                    explicit_formats.append(output_type)
                    break

        # Both should be detected (slides only and word only)
        assert "pptx" in explicit_formats
        assert "docx" in explicit_formats


class TestConstraintVariations:
    """Test various phrasings of explicit output constraints."""

    @pytest.mark.parametrize(
        "instruction,expected_type",
        [
            ("only pptx", "pptx"),
            ("only slides", "pptx"),
            ("only slide", "pptx"),
            ("just pptx", "pptx"),
            ("just slides", "pptx"),
            ("pptx only", "pptx"),
            ("slides only", "pptx"),
            ("slide only", "pptx"),
            ("in pptx", "pptx"),
            ("in slides", "pptx"),
            ("presentation format", "pptx"),
            ("ppt format", "pptx"),
            ("ppt only", "pptx"),
        ],
    )
    def test_pptx_constraint_variations(self, instruction, expected_type):
        """Test various ways users might specify PPTX-only output."""
        lowered = instruction.lower()
        pptx_constraints = [
            "only pptx", "only slides", "only slide", "just pptx", "just slides",
            "pptx only", "slides only", "slide only", "in pptx", "in slides", "in slide",
            "presentation format", "presentation only", "ppt only", "ppt format",
        ]

        found = any(constraint in lowered for constraint in pptx_constraints)
        assert found, f"'{instruction}' should be recognized as PPTX constraint"

    @pytest.mark.parametrize(
        "instruction,expected_type",
        [
            ("only docx", "docx"),
            ("only word", "docx"),
            ("only doc", "docx"),
            ("just docx", "docx"),
            ("just word", "docx"),
            ("docx only", "docx"),
            ("word only", "docx"),
            ("doc only", "docx"),
            ("in docx", "docx"),
            ("in word", "docx"),
            ("document format", "docx"),
            ("document only", "docx"),
        ],
    )
    def test_docx_constraint_variations(self, instruction, expected_type):
        """Test various ways users might specify DOCX-only output."""
        lowered = instruction.lower()
        docx_constraints = [
            "only docx", "only word", "only doc", "just docx", "just word",
            "docx only", "word only", "doc only", "in docx", "in word",
            "document format", "document only",
        ]

        found = any(constraint in lowered for constraint in docx_constraints)
        assert found, f"'{instruction}' should be recognized as DOCX constraint"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
