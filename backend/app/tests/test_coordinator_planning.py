"""Coordinator LLM planning (Phase 1) merge rules and fallbacks."""

import json

import pytest

from app.agents.coordinator import Coordinator, ExecutionPlan, _merge_planned_output_order


def test_merge_planned_output_order_preserves_planner_then_fills() -> None:
    assert _merge_planned_output_order(["sop", "narrative"], ["narrative", "raci", "sop"]) == [
        "sop",
        "narrative",
        "raci",
    ]


def test_merge_planned_output_order_ignores_unknown() -> None:
    assert _merge_planned_output_order(["docx", "narrative"], ["narrative", "raci"]) == [
        "narrative",
        "raci",
    ]


def test_plan_with_reasoning_claude_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.agents.coordinator.is_claude_enabled", lambda: False)
    from app.core.config import settings

    monkeypatch.setattr(settings, "coordinator_llm_planning_enabled", True)

    c = Coordinator()
    state: dict = {"user_instruction": "test", "process_model": {"process_name": "p", "steps": []}}
    wanted, plan = c._plan_with_reasoning(
        state,  # type: ignore[arg-type]
        ceiling_types=["narrative", "raci"],
        effective_registry=[],
        emit_event=None,
        contract_nodes=[],
    )
    assert wanted == ["narrative", "raci"]
    assert plan.used_llm_plan is False
    assert plan.fallback_reason == "claude_disabled"


def test_plan_with_reasoning_feature_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "coordinator_llm_planning_enabled", False)

    c = Coordinator()
    state: dict = {"user_instruction": "test", "process_model": {"process_name": "p", "steps": []}}
    wanted, plan = c._plan_with_reasoning(
        state,  # type: ignore[arg-type]
        ceiling_types=["narrative"],
        effective_registry=[],
        emit_event=None,
        contract_nodes=[],
    )
    assert wanted == ["narrative"]
    assert plan.used_llm_plan is False
    assert plan.fallback_reason == "coordinator_llm_planning_disabled"


def test_plan_with_reasoning_invalid_json_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.agents.coordinator.is_claude_enabled", lambda: True)
    from app.core.config import settings

    monkeypatch.setattr(settings, "coordinator_llm_planning_enabled", True)

    monkeypatch.setattr(
        "app.agents.coordinator.claude_generate_with_thinking",
        lambda **kw: {"thinking_text": "t", "text": "NOT VALID JSON {{{"},
    )

    c = Coordinator()
    state: dict = {"user_instruction": "test", "process_model": {"process_name": "p", "steps": []}}
    wanted, plan = c._plan_with_reasoning(
        state,  # type: ignore[arg-type]
        ceiling_types=["narrative", "raci"],
        effective_registry=[],
        emit_event=None,
        contract_nodes=[],
    )
    assert wanted == ["narrative", "raci"]
    assert plan.used_llm_plan is False
    assert plan.fallback_reason == "invalid_json"


def test_plan_with_reasoning_success_reorder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.agents.coordinator.is_claude_enabled", lambda: True)
    from app.core.config import settings

    monkeypatch.setattr(settings, "coordinator_llm_planning_enabled", True)

    monkeypatch.setattr(
        "app.agents.coordinator.claude_generate_with_thinking",
        lambda **kw: {
            "thinking_text": "reasoning",
            "text": '{"rationale":"do sop first","ordered_output_types":["sop","narrative","raci"],"per_output_notes":{"sop":"note"}}',
        },
    )

    c = Coordinator()
    state: dict = {"user_instruction": "test", "process_model": {"process_name": "p", "steps": []}}
    wanted, plan = c._plan_with_reasoning(
        state,  # type: ignore[arg-type]
        ceiling_types=["narrative", "raci", "sop"],
        effective_registry=[],
        emit_event=None,
        contract_nodes=[],
    )
    assert wanted == ["sop", "narrative", "raci"]
    assert plan.used_llm_plan is True
    assert "do sop" in plan.rationale
    assert plan.per_output_notes.get("sop") == "note"


def test_plan_with_reasoning_user_payload_includes_digest_and_grounding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.agents.coordinator.is_claude_enabled", lambda: True)
    from app.core.config import settings

    monkeypatch.setattr(settings, "coordinator_llm_planning_enabled", True)
    captured: dict[str, str] = {}

    def fake_think(*, user: str, **_kw: object) -> dict:
        captured["user"] = user
        return {
            "thinking_text": "",
            "text": '{"rationale":"","ordered_output_types":["narrative"],"per_output_notes":{}}',
        }

    monkeypatch.setattr("app.agents.coordinator.claude_generate_with_thinking", fake_think)

    c = Coordinator()
    state: dict = {
        "user_instruction": "hello",
        "process_model": {"process_name": "p", "steps": []},
        "conversation_digest": "user confirmed scope X",
        "planner_retrieval_excerpt": "## Planner retrieval excerpt\n\nchunk-ZETA here",
    }
    wanted, plan = c._plan_with_reasoning(
        state,  # type: ignore[arg-type]
        ceiling_types=["narrative"],
        effective_registry=[],
        emit_event=None,
        contract_nodes=[],
    )
    assert wanted == ["narrative"]
    assert plan.used_llm_plan is True
    payload = json.loads(captured["user"])
    assert "chunk-ZETA" in payload["grounding_excerpt"]
    assert "confirmed scope" in payload["conversation_digest"]


def test_emit_coordinator_plan_callback() -> None:
    received: list[tuple[str, dict]] = []

    def emit(et: str, payload: dict) -> None:
        received.append((et, payload))

    plan = ExecutionPlan(
        ordered_output_types=["narrative"],
        rationale="r",
        used_llm_plan=False,
        fallback_reason="x",
    )
    Coordinator._emit_coordinator_plan(emit, plan, wanted=["narrative"], contract_nodes=[])
    assert len(received) == 1
    assert received[0][0] == "coordinator_plan"
    assert received[0][1]["planned_outputs"] == ["narrative"]
    assert received[0][1]["fallback_reason"] == "x"
