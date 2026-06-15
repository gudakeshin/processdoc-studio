"""Regression: docx/pptx runs must not bypass evaluator gates."""

from __future__ import annotations

from app.services.run_worker import _build_evaluator_pipeline


def test_docx_pptx_run_fails_when_guardrails_fail() -> None:
    pipeline = _build_evaluator_pipeline(
        requested_outputs=["docx", "pptx"],
        plan_payload={},
        qa_report={"passed": True},
        visual_qa_report={"status": "pass"},
        guardrail_report={"status": "fail", "failed_gate": "gate_1_source_grounding"},
    )
    assert pipeline["guardrails_passed"] is False
    assert pipeline["status"] == "fail"


def test_docx_pptx_run_fails_when_final_artifact_qa_fails() -> None:
    pipeline = _build_evaluator_pipeline(
        requested_outputs=["docx", "pptx"],
        plan_payload={},
        qa_report={"passed": True},
        visual_qa_report={"status": "pass"},
        guardrail_report={"status": "pass"},
        final_artifact_report={"passed": False, "status": "fail", "issues": ["missing citations"]},
    )
    assert pipeline["final_artifact_qa_passed"] is False
    assert pipeline["status"] == "fail"
