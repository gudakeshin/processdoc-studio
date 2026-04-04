"""Sub-agent and process extraction behavior."""

import pytest

from app.agents.agent_types import build_agent_context, merge_agent_output
from app.agents.coordinator import Coordinator
from app.agents.subagents import (
    run_docx_agent,
    run_drawio_agent,
    run_narrative_agent,
    run_pdf_agent,
    run_pptx_agent,
    run_process_extraction,
    run_xlsx_agent,
)
from app.services.process_extraction import extract_process_model
from app.services.drawio_builder import process_model_to_drawio_xml


def _run_agent(state: dict, output_type: str, fn) -> dict:
    merge_agent_output(state, fn(build_agent_context(state, output_type)))
    return state


def test_extract_process_model_numbered_steps() -> None:
    text = """# Client onboarding
Role: Account Manager
1. Collect KYC documents
2. Run compliance check
3. Provision workspace
"""
    m = extract_process_model(text, "")
    assert m["process_name"] == "Client onboarding"
    assert len(m["steps"]) == 3
    assert m["steps"][0]["name"] == "Collect KYC documents"
    assert "Account Manager" in m["roles"]


def test_extract_fallback_single_paragraph() -> None:
    m = extract_process_model("We need to review the contract and sign off.", "")
    assert len(m["steps"]) >= 1


def test_format_agents_produce_artifacts() -> None:
    """All five format output types produce non-empty artifacts."""
    state = {
        "raw_text": "1. First action\n2. Second action\nRole: Ops",
        "assembled_context": "Tier0 context",
    }
    state = run_process_extraction(state)
    state = _run_agent(state, "process_map", run_drawio_agent)
    state = _run_agent(state, "xlsx", run_xlsx_agent)
    state = _run_agent(state, "pdf", run_pdf_agent)
    state = _run_agent(state, "docx", run_docx_agent)
    state = _run_agent(state, "pptx", run_pptx_agent)

    assert "<mxGraphModel" in state["drawio_xml"]
    assert "mxCell" in state["drawio_xml"]
    assert isinstance(state.get("xlsx_markdown"), str) and "|" in str(state.get("xlsx_markdown"))
    assert isinstance(state.get("pdf_markdown"), str) and len(str(state.get("pdf_markdown"))) > 10
    assert isinstance(state.get("docx_markdown"), str) and len(str(state.get("docx_markdown"))) > 10
    assert isinstance(state.get("pptx_slides"), list) and len(state.get("pptx_slides") or []) >= 1


def test_docx_agent_generates_sop_content_when_sop_skill_active() -> None:
    """When sop_v2 is the primary skill, run_docx_agent produces SOP-structured content."""
    from app.services.skill_document import load_builtin_skills
    skills = load_builtin_skills()
    sop_card = next((s for s in skills if s.get("id") == "sop_v2"), None)

    state = {
        "raw_text": "1. Intake request\n2. Approve request\n3. Provision access\nRole: Ops",
        "assembled_context": "",
        "skill_card": {
            "primary_skill_by_output_type": {"docx": sop_card or {}},
            "post_processor_skills_by_output_type": {},
        },
        "skill_instructions_by_output": {},
    }
    state = run_process_extraction(state)
    state = _run_agent(state, "docx", run_docx_agent)
    md = state.get("docx_markdown") or ""
    assert isinstance(md, str) and len(md) > 10
    # SOP content should have procedure structure
    assert "# " in md


def test_xlsx_agent_generates_raci_when_raci_skill_active() -> None:
    """When raci_v2 is the primary skill, run_xlsx_agent produces RACI columns."""
    from app.services.skill_document import load_builtin_skills
    skills = load_builtin_skills()
    raci_card = next((s for s in skills if s.get("id") == "raci_v2"), None)

    state = {
        "raw_text": "1. Intake request\n2. Approve request\nRole: Ops",
        "assembled_context": "",
        "skill_card": {
            "primary_skill_by_output_type": {"xlsx": raci_card or {}},
            "post_processor_skills_by_output_type": {},
        },
        "skill_instructions_by_output": {},
    }
    state = run_process_extraction(state)
    state = _run_agent(state, "xlsx", run_xlsx_agent)
    md = state.get("xlsx_markdown") or ""
    assert isinstance(md, str)
    assert "|" in md
    # RACI should have Responsible/Accountable columns
    md_lower = md.lower()
    assert "responsible" in md_lower or "accountable" in md_lower or "activity" in md_lower


def test_process_map_respects_mermaid_preference() -> None:
    state = {
        "raw_text": "1. Intake request\n2. Approve request\nRole: Ops",
        "assembled_context": "",
        "output_type_representations": {"process_map": "mermaid"},
    }
    state = run_process_extraction(state)
    state = _run_agent(state, "process_map", run_drawio_agent)
    assert "flowchart TD" in state["process_map_mermaid"]


def test_coordinator_uses_format_output_types_only() -> None:
    """Coordinator accepts docx as an output type and produces docx_markdown."""
    c = Coordinator()
    st = c.run(
        {
            "raw_text": "1. Alpha\n2. Beta",
            "requested_outputs": ["docx"],
            "dpdp_flags": {"enabled": True},
        }
    )
    assert st.get("docx_markdown")
    assert not st.get("narrative_md")
    assert not st.get("raci_html")
    assert not st.get("sop_markdown")
    assert not st.get("drawio_xml")


def test_coordinator_sop_alias_maps_to_docx() -> None:
    """Requesting 'sop' maps to docx output type with sop_v2 content skill hint."""
    c = Coordinator()
    st = c.run(
        {
            "raw_text": "1. Review contract\n2. Sign off\nRole: Legal",
            "requested_outputs": ["sop"],
            "dpdp_flags": {"enabled": True},
        }
    )
    assert st.get("docx_markdown"), "sop alias must produce docx_markdown"
    assert not st.get("sop_markdown"), "sop_markdown is a legacy key — must not be set"
    hints = st.get("content_skill_hints") or {}
    assert hints.get("docx") == "sop_v2", "sop alias must set sop_v2 as content skill hint for docx"


def test_coordinator_raci_alias_maps_to_xlsx() -> None:
    """Requesting 'raci' maps to xlsx output type with raci_v2 content skill hint."""
    c = Coordinator()
    st = c.run(
        {
            "raw_text": "1. Intake\n2. Approve\nRole: Ops",
            "requested_outputs": ["raci"],
            "dpdp_flags": {"enabled": True},
        }
    )
    assert st.get("xlsx_markdown"), "raci alias must produce xlsx_markdown"
    assert not st.get("raci_html"), "raci_html is a legacy key — must not be set"
    hints = st.get("content_skill_hints") or {}
    assert hints.get("xlsx") == "raci_v2", "raci alias must set raci_v2 as content skill hint for xlsx"


def test_coordinator_finance_proposal_intent_sets_proposal_hint_for_format_outputs() -> None:
    c = Coordinator()
    st = c.run(
        {
            "raw_text": (
                "Create a finance transformation proposal and pitch deck for CFO review, "
                "covering FP&A redesign and close acceleration."
            ),
            "requested_outputs": ["docx", "pptx"],
            "dpdp_flags": {"enabled": True},
        }
    )
    hints = st.get("content_skill_hints") or {}
    assert hints.get("docx") == "proposal_finance_transformation_v1"
    assert hints.get("pptx") == "proposal_finance_transformation_v1"


def test_coordinator_finance_statement_of_work_intent_sets_proposal_hint() -> None:
    c = Coordinator()
    st = c.run(
        {
            "raw_text": (
                "Prepare a statement of work for finance operating model redesign and record to report "
                "improvement with CFO sponsorship."
            ),
            "requested_outputs": ["docx", "pdf"],
            "dpdp_flags": {"enabled": True},
        }
    )
    hints = st.get("content_skill_hints") or {}
    assert hints.get("docx") == "proposal_finance_transformation_v1"
    assert hints.get("pdf") == "proposal_finance_transformation_v1"


def test_coordinator_uses_plan_payload_content_skill_targets_over_heuristics() -> None:
    c = Coordinator()
    st = c.run(
        {
            "raw_text": "Create a generic document",
            "requested_outputs": ["docx"],
            "dpdp_flags": {"enabled": True},
            "plan_payload": {
                "content_skill_targets": {"docx": "proposal_finance_transformation_v1"},
            },
        }
    )
    hints = st.get("content_skill_hints") or {}
    assert hints.get("docx") == "proposal_finance_transformation_v1"


def test_coordinator_includes_all_required_skill_instructions_for_output() -> None:
    """
    Primary generator skills (role=primary) must appear in skill_instructions_by_output.
    Post-processor skills (role=post_processor, e.g. brand_guidelines_v1) must NOT appear
    in the generation instructions — they are stored separately in
    skill_card["post_processor_skills_by_output_type"] and applied as a second pass.
    """
    c = Coordinator()
    st = c.run(
        {
            "raw_text": "1. Draft executive summary\n2. Review and publish",
            "requested_outputs": ["docx"],
            "dpdp_flags": {"enabled": True},
        }
    )
    # Primary generator skills must be in the generation prompt
    instructions = str((st.get("skill_instructions_by_output") or {}).get("docx") or "")
    assert "[frontend_design_docx_v1]" in instructions
    assert "[docx_v1]" in instructions
    # Post-processors must NOT be mixed into the generation instructions
    assert "[brand_guidelines_v1]" not in instructions, (
        "brand_guidelines_v1 is a post_processor skill — its instructions must not be "
        "injected into the primary generation prompt."
    )
    # Post-processor must appear in the dedicated post-processor slot
    skill_card = st.get("skill_card") or {}
    post_processors = (skill_card.get("post_processor_skills_by_output_type") or {}).get("docx") or []
    post_ids = [str(s.get("id") or "") for s in post_processors]
    assert "brand_guidelines_v1" in post_ids, (
        "brand_guidelines_v1 must be registered in post_processor_skills_by_output_type['docx']"
    )


def test_drawio_builder_contains_decision_shapes_when_decisions_present() -> None:
    model = {
        "process_name": "Onboarding",
        "roles": ["Sales", "Compliance"],
        "steps": [
            {"id": "s1", "name": "Collect documents", "role": "Sales"},
            {"id": "s2", "name": "Run checks", "role": "Compliance"},
            {"id": "s3", "name": "Approve", "role": "Compliance"},
        ],
        "decisions": [
            {"id": "d1", "condition": "Documents complete?", "true_path": ["s2"], "false_path": ["s1"]},
        ],
        "swimlanes": {"Sales": ["s1"], "Compliance": ["s2", "s3"]},
        "metadata": {},
    }
    xml = process_model_to_drawio_xml(model)
    assert "<mxGraphModel" in xml
    assert "rhombus;" in xml
    assert "Yes" in xml or "No" in xml


def test_narrative_thinking_emits_event_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "subagent_narrative_thinking_enabled", True)
    monkeypatch.setattr("app.agents.subagents.is_claude_enabled", lambda: True)
    captured: list[tuple[str, dict]] = []

    def capture_emit(et: str, payload: dict) -> None:
        captured.append((et, payload))

    monkeypatch.setattr(
        "app.agents.subagents.claude_generate_with_thinking",
        lambda **kw: {
            "thinking_text": "internal reasoning",
            "text": "# Proc — Executive Briefing\n\n## What This Process Does\n\nBody.",
        },
    )

    state: dict = {
        "raw_text": "Role: Ops\n1. Step one",
        "assembled_context": "ctx",
        "skill_card": {},
        "skill_instructions_by_output": {},
        "_emit_run_event": capture_emit,
    }
    state = run_process_extraction(state)
    merge_agent_output(state, run_narrative_agent(build_agent_context(state, "narrative")))
    assert any(et == "narrative_thinking_excerpt" for et, _ in captured)
