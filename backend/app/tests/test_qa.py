from app.agents import coordinator as coordinator_module
from app.agents.agent_types import AgentContext, AgentOutput
from app.agents.coordinator import Coordinator
from app.services.qa import QAAgentLoop


def test_qa_returns_remediation_instructions_when_below_threshold() -> None:
    qa = QAAgentLoop()
    report = qa.run(
        {"narrative_md": "Very short output without sources."},
        threshold=0.9,
        project_id="p1",
    )
    assert report["passed"] is False
    remediation = report.get("remediation_instructions", {})
    assert "narrative_md" in remediation
    assert remediation["narrative_md"]["actions"]
    assert "target_score" in remediation["narrative_md"]


def test_qa_handles_non_string_outputs() -> None:
    qa = QAAgentLoop()
    report = qa.run(
        {"process_map_steps": ["step 1", "step 2"], "narrative_md": {"text": "short"}},
        threshold=0.9,
        project_id="p1",
    )
    assert isinstance(report["scores"], dict)
    assert "process_map_steps" in report["scores"]


def test_remediation_build_does_not_crash_on_list_deliverable() -> None:
    """Regression: re.search must not receive raw list from agent state."""
    qa = QAAgentLoop()
    remediation = qa._build_remediation_instructions(
        {"docx_markdown": ["# Section", "Bullet line"]},
        {"docx_markdown": 0.5},
        0.8,
    )
    assert "docx_markdown" in remediation
    assert remediation["docx_markdown"]["actions"]


def test_coordinator_applies_single_remediation_pass(monkeypatch) -> None:
    """
    "narrative" is a deliverable alias that maps to the "docx" output type with the
    narrative_v2 skill hint.  The coordinator dispatches run_docx_agent and stores
    the result in docx_markdown.  QA remediation therefore targets docx_markdown and
    re-invokes _OUTPUT_AGENTS["docx"].
    """
    calls: list[dict] = []
    docx_calls = {"n": 0}

    def tracked_docx_agent(_ctx: AgentContext) -> AgentOutput:
        docx_calls["n"] += 1
        if docx_calls["n"] == 1:
            return AgentOutput(updates={"docx_markdown": "# Briefing\n\nInitial draft without sources."})
        return AgentOutput(
            updates={"docx_markdown": "# Briefing\n\nInitial draft without sources.\n\nQA Remediation Applied\n"}
        )

    # "narrative" is a deliverable → routes to _OUTPUT_AGENTS["docx"]
    monkeypatch.setitem(coordinator_module._OUTPUT_AGENTS, "docx", tracked_docx_agent)

    c = Coordinator()

    def fake_qa_run(outputs, threshold=0.8, project_id=None, max_loops=2, **kwargs):
        _ = kwargs
        _ = max_loops
        calls.append(outputs)
        if len(calls) == 1:
            return {
                "passed": False,
                "iterations": 1,
                "scores": {"docx_markdown": 0.5},
                "verifications": {},
                "remediation_instructions": {
                    "docx_markdown": {
                        "reason": "Needs sources",
                        "target_score": threshold,
                        "actions": ["Add source markers", "Clarify evidence trail"],
                        "rewrite_prompt": "Revise docx_markdown",
                    }
                },
            }
        return {
            "passed": True,
            "iterations": 1,
            "scores": {"docx_markdown": 0.92},
            "verifications": {},
            "remediation_instructions": {},
        }

    monkeypatch.setattr(c.qa_loop, "run", fake_qa_run)
    monkeypatch.setattr(
        c.guardrails,
        "evaluate",
        lambda outputs, dpdp_gate7: {
            "status": "pass",
            "gates": {"gate_1_source_grounding": "pass", "gate_7_dpdp_compliance": "pass"},
            "guardrail_events": [],
            "failed_gate": None,
            "retry_count": 0,
        },
    )

    st = c.run(
        {
            "raw_text": "1. Do work",
            "requested_outputs": ["narrative"],
            "dpdp_flags": {"enabled": True},
        }
    )

    assert docx_calls["n"] >= 2, "docx agent should be called for initial dispatch and QA remediation"
    assert len(calls) >= 2
    assert st["qa_report"]["remediation_applied"] is True
    assert st["qa_report"]["remediation_converged"] is True
    assert "QA Remediation Applied" in st["docx_markdown"]
