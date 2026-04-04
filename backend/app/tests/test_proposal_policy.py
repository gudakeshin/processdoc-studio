from app.services.proposal_policy import (
    PROPOSAL_SKILL_ID,
    derive_proposal_skill_targets,
    proposal_prompt_contract,
    proposal_quality_policy,
)
from app.services.run_worker import _build_evaluator_pipeline


def test_derive_proposal_skill_targets_detects_finance_proposal_synonyms() -> None:
    targets = derive_proposal_skill_targets(
        instruction="Create a statement of work for finance operating model and treasury transformation.",
        output_types=["docx", "pptx"],
    )
    assert targets.get("docx") == PROPOSAL_SKILL_ID
    assert targets.get("pptx") == PROPOSAL_SKILL_ID


def test_derive_proposal_skill_targets_requires_finance_and_proposal_intent() -> None:
    targets = derive_proposal_skill_targets(
        instruction="Write a technical SOP for customer onboarding.",
        output_types=["docx", "pptx"],
    )
    assert targets == {}


def test_proposal_quality_policy_activates_from_plan_targets() -> None:
    policy = proposal_quality_policy(
        {"content_skill_targets": {"docx": PROPOSAL_SKILL_ID}},
        ["docx"],
    )
    assert policy["active"] is True
    assert "docx" in set(policy["required_outputs"])


def test_build_evaluator_pipeline_requires_qa_for_policy_outputs() -> None:
    evaluator = _build_evaluator_pipeline(
        requested_outputs=["docx"],
        plan_payload={"content_skill_targets": {"docx": PROPOSAL_SKILL_ID}},
        qa_report={"passed": False},
        visual_qa_report={"status": "pass"},
        guardrail_report={"status": "pass"},
    )
    assert evaluator["qa_passed"] is False
    assert evaluator["status"] == "fail"


def test_proposal_prompt_contract_contains_core_sections() -> None:
    contract = proposal_prompt_contract("docx")
    sections = contract.get("sections") or []
    assert "Executive Summary" in sections
    assert "Value Case" in sections
