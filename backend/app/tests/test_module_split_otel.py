"""Tests for module split and OTel instrumentation."""

from __future__ import annotations

from app.agents.pptx_critique_repair import (
    critique_and_repair_pptx,
    merge_pptx_slides_repair,
)
from app.services.otel_tracing import get_tracer, start_span
from app.services.run_evaluator_pipeline import (
    build_evaluator_pipeline,
    pptx_evidence_gate_from_run_dir,
)


def test_run_evaluator_pipeline_module_exports() -> None:
    gate = pptx_evidence_gate_from_run_dir.__name__
    assert gate == "pptx_evidence_gate_from_run_dir"
    pipeline = build_evaluator_pipeline(
        requested_outputs=["pptx"],
        plan_payload={},
        qa_report={"passed": True},
        visual_qa_report={"status": "pass"},
        guardrail_report={"status": "pass"},
    )
    assert pipeline["status"] == "pass"


def test_pptx_critique_repair_module_merge() -> None:
    prior = [{"title": "A"}, {"title": "B"}]
    repaired = [{"title": "A"}, {"title": "B2"}]
    out = merge_pptx_slides_repair(prior, repaired, {2})
    assert out[1]["title"] == "B2"


def test_otel_start_span_noop_when_disabled() -> None:
    tracer = get_tracer("test")
    with start_span("test.span", attributes={"k": "v"}) as span:
        assert span is not None
    assert tracer is not None


def test_module_split_exports_docx_and_visual_qa(tmp_path) -> None:
    from pathlib import Path

    from app.agents.docx_critique_repair import critique_and_repair_docx, targeted_section_rewrite
    from app.services.run_evaluator_pipeline import guardrail_regeneration_directive
    from app.services.run_visual_qa_augment import augment_visual_qa_with_render_hints

    assert callable(critique_and_repair_docx)
    assert callable(targeted_section_rewrite)
    assert guardrail_regeneration_directive({}).startswith("Guardrail remediation")
    assert augment_visual_qa_with_render_hints({}, Path(tmp_path)) == {}


def test_run_execute_span_wrapper_exists() -> None:
    from app.services import run_worker

    assert callable(run_worker._execute_run_job)
    assert callable(run_worker._execute_run_job_impl)


def test_generate_slides_batched_module_export() -> None:
    from app.agents.pptx_slide_batching import generate_slides_batched, strip_title_override

    assert "Presentation title" not in strip_title_override(
        'Hello\nPresentation title (use exactly): "X"\nBye'
    )
    assert callable(generate_slides_batched)
    from app.agents.agent_types import AgentContext

    ctx = AgentContext(
        output_type="pptx",
        project_id="p1",
        run_id="r1",
        user_id=None,
        raw_text="",
        user_instruction="",
        user_intent_original="",
        process_model={},
        assembled_context="",
        output_type_representations={},
        skill_instructions_by_output={},
        skill_card=None,
        plan_payload={},
    )
    assert critique_and_repair_pptx(ctx, [], {}) == []
