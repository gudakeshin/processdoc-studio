"""Regression: docx/pptx runs must not bypass evaluator gates."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.run_worker import (
    _build_evaluator_pipeline,
    _pptx_evidence_gate_from_run_dir,
)


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


def test_evaluator_pipeline_fails_on_evidence_hard_fail() -> None:
    pipeline = _build_evaluator_pipeline(
        requested_outputs=["pptx"],
        plan_payload={},
        qa_report={"passed": True},
        visual_qa_report={"status": "pass"},
        guardrail_report={"status": "pass"},
        evidence_gate={
            "passed": False,
            "hard_fail": True,
            "unsupported_claims_count": 2,
            "summary": "2 unsupported",
            "render_status": "degraded",
        },
    )
    assert pipeline["evidence_passed"] is False
    assert pipeline["status"] == "fail"
    assert pipeline["evidence_gate"]["hard_fail"] is True


def test_evaluator_pipeline_passes_when_evidence_ok() -> None:
    pipeline = _build_evaluator_pipeline(
        requested_outputs=["pptx"],
        plan_payload={},
        qa_report={"passed": True},
        visual_qa_report={"status": "pass"},
        guardrail_report={"status": "pass"},
        evidence_gate={"passed": True, "hard_fail": False, "unsupported_claims_count": 0},
    )
    assert pipeline["evidence_passed"] is True
    assert pipeline["status"] == "pass"


def test_pptx_evidence_gate_reads_hard_fail_flag(tmp_path: Path) -> None:
    (tmp_path / "render_status.json").write_text(
        json.dumps({"pptx": "degraded"}), encoding="utf-8"
    )
    (tmp_path / "pptx_render_quality.json").write_text(
        json.dumps(
            {
                "status": "fail",
                "evidence_hard_fail": True,
                "evidence": {
                    "unsupported_claims_count": 1,
                    "summary": "1 claim found; 1 unsupported",
                    "slide_validations": [
                        {
                            "slide_title": "Impact",
                            "validation": {
                                "unsupported_claims": [{"claim": "$900M", "type": "Financial value"}],
                            },
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    gate = _pptx_evidence_gate_from_run_dir(tmp_path)
    assert gate["passed"] is False
    assert gate["hard_fail"] is True
    assert gate["unsupported_claims_count"] == 1
    assert gate["render_status"] == "degraded"
    assert gate["remediation_hints"]
    assert "$900M" in gate["remediation_hints"][0]["instruction"]


def test_pptx_evidence_gate_passes_without_hard_fail(tmp_path: Path) -> None:
    (tmp_path / "render_status.json").write_text(
        json.dumps({"pptx": "ok"}), encoding="utf-8"
    )
    (tmp_path / "pptx_render_quality.json").write_text(
        json.dumps(
            {
                "status": "pass",
                "evidence": {"unsupported_claims_count": 0, "summary": "ok"},
            }
        ),
        encoding="utf-8",
    )
    gate = _pptx_evidence_gate_from_run_dir(tmp_path)
    assert gate["passed"] is True
    assert gate["hard_fail"] is False


def test_pptx_evidence_gate_infers_hard_fail_from_degraded_and_issues(tmp_path: Path) -> None:
    """Older artifacts may lack evidence_hard_fail flag — infer from degraded + issues."""
    (tmp_path / "render_status.json").write_text(
        json.dumps({"pptx": "degraded"}), encoding="utf-8"
    )
    (tmp_path / "pptx_render_quality.json").write_text(
        json.dumps(
            {
                "status": "fail",
                "issues": ["Evidence validation failed: 1 unsupported claim(s)."],
                "evidence": {
                    "unsupported_claims_count": 1,
                    "slide_validations": [],
                },
            }
        ),
        encoding="utf-8",
    )
    gate = _pptx_evidence_gate_from_run_dir(tmp_path)
    assert gate["passed"] is False
    assert gate["hard_fail"] is True


def test_guardrails_only_path_requires_evidence_passed() -> None:
    """Evidence failure must not be treated as guardrails-only (which ships review_ready)."""
    pipeline = _build_evaluator_pipeline(
        requested_outputs=["pptx"],
        plan_payload={},
        qa_report={"passed": True},
        visual_qa_report={"status": "pass"},
        guardrail_report={"status": "fail", "failed_gate": "gate_1_source_grounding"},
        evidence_gate={"passed": False, "hard_fail": True, "unsupported_claims_count": 1},
    )
    guardrails_only_failure = (
        not pipeline.get("guardrails_passed")
        and pipeline.get("qa_passed", True)
        and pipeline.get("visual_qa_passed", True)
        and pipeline.get("final_artifact_qa_passed", True)
        and pipeline.get("evidence_passed", True)
    )
    assert guardrails_only_failure is False
    assert pipeline["status"] == "fail"
