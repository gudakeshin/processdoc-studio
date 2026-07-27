"""Tests for markdown representation guard."""

from __future__ import annotations

import json
from pathlib import Path

from app.core.markdown_guard import detect_code_document, strip_outer_fence

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "run_pov_apollo"


def test_detect_code_document_flags_js_docx_fixture() -> None:
    body = (FIXTURE_DIR / "docx_markdown.txt").read_text(encoding="utf-8")
    issues = detect_code_document(body)
    assert issues
    assert any("docx" in i.lower() or "generator" in i.lower() or "fence" in i.lower() for i in issues)


def test_strip_outer_fence_unwraps_markdown_only() -> None:
    md = "```markdown\n# Title\n\nBody\n```"
    assert strip_outer_fence(md).startswith("# Title")


def test_clean_markdown_not_flagged() -> None:
    md = "# Executive Summary\n\n## Context\n\nApollo Tyres R2R cycle.\n"
    assert detect_code_document(md) == []
