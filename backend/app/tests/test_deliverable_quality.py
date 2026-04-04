"""Tests for registry-backed deliverable quality contracts and scoring."""

from __future__ import annotations

from app.services.deliverable_quality import _evaluate_one_output, run_deliverable_quality_loop
from app.services.proposal_policy import PROPOSAL_SKILL_ID, proposal_prompt_contract
from app.services.quality_contract_registry import build_prompt_bundle, load_contract, resolve_contract_id


def test_resolve_contract_via_registry_and_skill_override() -> None:
    card = {"id": PROPOSAL_SKILL_ID, "quality_contract_id": "proposal_finance_v1"}
    cid = resolve_contract_id(skill_id=PROPOSAL_SKILL_ID, output_type="docx", skill_card=card)
    assert cid == "proposal_finance_v1"


def test_build_prompt_bundle_matches_contract_sections() -> None:
    bundle = build_prompt_bundle(
        skill_id=PROPOSAL_SKILL_ID,
        output_type="docx",
        skill_card={"id": PROPOSAL_SKILL_ID, "quality_contract_id": "proposal_finance_v1"},
    )
    assert bundle is not None
    contract = load_contract("proposal_finance_v1")
    assert contract is not None
    prompt = contract.get("prompt") or {}
    assert bundle["sections"] == prompt.get("sections")


def test_proposal_prompt_contract_loads_from_quality_contracts() -> None:
    c = proposal_prompt_contract(
        "docx",
        skill_id=PROPOSAL_SKILL_ID,
        skill_card={"quality_contract_id": "proposal_finance_v1"},
    )
    assert "Executive Summary" in c["sections"]
    assert c.get("contract_id") == "proposal_finance_v1"


def test_section_coverage_scores_partial_missing() -> None:
    contract = load_contract("proposal_finance_v1")
    assert contract is not None
    text = "# T\n## Executive Summary\nhello\n## Value Case\nx"
    ev = _evaluate_one_output("docx_markdown", text, {**contract, "_contract_id": "proposal_finance_v1"}, project_id=None)
    assert ev["aggregate_score"] < 1.0
    struct = next(d for d in ev["dimensions"] if d["kind"] == "section_coverage")
    assert struct["score"] < 1.0


def test_deliverable_quality_loop_skips_without_binding() -> None:
    state = {
        "skill_card": {
            "primary_skill_by_output_type": {
                "docx": {"id": "narrative_v2"},
            }
        }
    }
    report, out = run_deliverable_quality_loop(
        state=state,
        wanted=["docx"],
        outputs={"docx_markdown": "# x"},
        apply_remediation=lambda *a, **k: {},
        emit_event=None,
        project_id=None,
    )
    assert report is None
    assert out == {"docx_markdown": "# x"}
