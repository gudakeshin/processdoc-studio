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


def test_critique_and_repair_pptx_empty_passthrough() -> None:
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
