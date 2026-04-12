from app.services.guardrails import GuardrailPipeline


def test_gate7_quarantine() -> None:
    pipeline = GuardrailPipeline()
    result = pipeline.evaluate({"narrative": "ok"}, dpdp_gate7=False)
    # Local deterministic checks require references; this short output fails earlier.
    assert result["status"] == "fail"
    assert result["failed_gate"] == "gate_1_source_grounding"


def test_local_mode_fails_when_references_missing(monkeypatch) -> None:
    import app.services.guardrails as guardrails_module

    monkeypatch.setattr(guardrails_module, "is_claude_enabled", lambda: False)

    pipeline = GuardrailPipeline()
    result = pipeline.evaluate(
        {
            "narrative": "Research shows this will improve efficiency by 20 percent across teams.",
            "sop": "Do step one. Do step one.",
        },
        dpdp_gate7=True,
    )
    assert result["status"] == "fail"
    assert result["failed_gate"] in {"gate_1_source_grounding", "gate_2_hallucination_check"}
    first_event = result["guardrail_events"][0]
    # Check for updated personality-formatted message
    assert "Source grounding" in first_event["reason"] or "Hallucination check" in first_event["reason"]


def test_local_mode_passes_and_respects_gate7(monkeypatch) -> None:
    import app.services.guardrails as guardrails_module

    monkeypatch.setattr(guardrails_module, "is_claude_enabled", lambda: False)

    pipeline = GuardrailPipeline()
    outputs = {
        "narrative": (
            "## Process Summary\n"
            "- Validate intake checklist.\n"
            "- Confirm approvals before execution.\n"
            "According to prior assessments [1], this sequence reduces rework.\n"
            "(source: internal-controls-manual)\n"
        ),
        "sop": (
            "# SOP\n"
            "- Step 1: intake\n"
            "- Step 2: approval\n"
            "See reference https://example.com/control-framework.\n"
        ),
    }
    result = pipeline.evaluate(outputs, dpdp_gate7=False)
    assert result["status"] == "quarantined"
    assert result["gates"]["gate_6_style_enforcer"] == "pass"
    assert result["gates"]["gate_7_dpdp_compliance"] == "fail"
