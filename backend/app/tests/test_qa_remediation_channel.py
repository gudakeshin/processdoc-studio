"""Tests for isolated QA remediation channel."""

from __future__ import annotations

from app.services.qa_remediation_channel import strip_qa_feedback, wrap_qa_feedback


def test_wrap_and_strip_roundtrip() -> None:
    block = wrap_qa_feedback("Fix citations on slide 4")
    text = f"Original context.\n\n{block}\n\nMore context."
    stripped = strip_qa_feedback(text)
    assert "Fix citations" not in stripped
    assert "Original context" in stripped


def test_strip_legacy_qa_remediation_tail() -> None:
    text = "Create a POV note.\n\nQA remediation:\ndocx: add citations"
    assert "QA remediation" not in strip_qa_feedback(text)
    assert text.startswith("Create a POV note.")
