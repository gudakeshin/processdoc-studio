import asyncio
from pathlib import Path

from app.agents.coordinator import Coordinator
from app.services.hooks import disable_hook, list_registered_hooks, register_hook, run_hooks
from app.services.permission_pipeline import evaluate_permission_pipeline
from app.services.retry_policy import (
    classify_retry_mode,
    compute_rate_limit_backoff,
    should_apply_fallback,
    fallback_strategy_for_output,
    validate_retry_transition,
)
from app.services.run_events import build_event_payload, lifecycle_event, hook_exec_id


def test_permission_pipeline_denies_without_approval() -> None:
    decisions = evaluate_permission_pipeline(
        run_status="approved",
        has_approval=False,
        requested_outputs=["docx"],
        plan_payload={"run_contract": {"nodes": [{"id": "n1"}]}},
    )
    assert decisions
    assert any(d.stage == "human_approval_gate" and not d.allowed for d in decisions)


def test_permission_pipeline_has_machine_readable_code() -> None:
    decisions = evaluate_permission_pipeline(
        run_status="approved",
        has_approval=True,
        requested_outputs=["root_shell"],
    )
    deny = [d for d in decisions if d.stage == "deny_rules"][0]
    assert deny.allowed is False
    assert deny.code == "deny.forbidden_output"
    classifier = [d for d in decisions if d.stage == "policy_classifier_gate"]
    if classifier:
        assert classifier[0].metadata is not None
        assert "policy_version" in classifier[0].metadata
        assert "policy_hash" in classifier[0].metadata
        assert "decision_path" in classifier[0].metadata


def test_permission_pipeline_dry_run_mode_allows_with_metadata() -> None:
    decisions = evaluate_permission_pipeline(
        run_status="approved",
        has_approval=True,
        requested_outputs=["docx"],
        classifier_score=0.1,
        classifier_threshold=0.9,
        enforce_policy=False,
    )
    classifier = [d for d in decisions if d.stage == "policy_classifier_gate"][0]
    assert classifier.allowed is True
    assert classifier.metadata is not None
    assert classifier.metadata["enforcement_mode"] == "dry_run"


def test_permission_pipeline_preflight_without_human_gate() -> None:
    decisions = evaluate_permission_pipeline(
        run_status="plan_ready",
        has_approval=False,
        requested_outputs=["docx"],
        include_human_gate=False,
        plan_payload={"run_contract": {"nodes": [{"id": "n1"}]}},
    )
    assert decisions
    assert all(d.stage != "human_approval_gate" for d in decisions)
    assert all(d.allowed for d in decisions)


def test_permission_pipeline_flags_incomplete_plan() -> None:
    decisions = evaluate_permission_pipeline(
        run_status="plan_ready",
        has_approval=True,
        requested_outputs=["docx"],
        classifier_threshold=0.8,
        plan_payload={},
        include_human_gate=False,
    )
    classifier = [d for d in decisions if d.stage == "policy_classifier_gate"][0]
    assert classifier.allowed is False
    assert classifier.metadata is not None
    assert classifier.metadata["policy_reason"] == "policy_plan_incomplete"


def test_retry_policy_honors_retry_after() -> None:
    backoff = compute_rate_limit_backoff(
        retry_after_sec=7.0,
        attempt=2,
        base_sec=1.5,
        max_sec=20.0,
    )
    assert backoff == 7.0


def test_retry_mode_classification_thresholds() -> None:
    assert classify_retry_mode(retry_after_sec=5, cooldown_threshold_sec=20) == "fast_retry"
    assert classify_retry_mode(retry_after_sec=30, cooldown_threshold_sec=20) == "cooldown_retry"


def test_retry_policy_fallback_threshold() -> None:
    assert should_apply_fallback(consecutive_failures=3) is True
    assert should_apply_fallback(consecutive_failures=2) is False


def test_retry_policy_fallback_strategy_matrix() -> None:
    assert fallback_strategy_for_output("docx")["mode"] == "degrade_fidelity"
    assert fallback_strategy_for_output("process_map")["mode"] == "deterministic_template"


def test_retry_transition_validation() -> None:
    assert validate_retry_transition("scheduled", "executing") is True
    assert validate_retry_transition("scheduled", "dead_letter") is False
    assert validate_retry_transition("executing", "scheduled") is True


def test_coordinator_async_generator_emits_events(monkeypatch) -> None:
    c = Coordinator()

    def fake_run(state, *, emit_event=None, abort_check=None):
        if emit_event:
            emit_event("step", {"status": "fake_stage"})
        return {"ok": True, **state}

    monkeypatch.setattr(c, "run", fake_run)

    async def _collect():
        out = []
        async for ev in c.coordinate({"raw_text": "hello"}):
            out.append(ev)
        return out

    events = asyncio.run(_collect())
    event_types = [str(e.get("event_type")) for e in events]
    assert "coordinator_started" in event_types
    assert "step" in event_types
    assert "coordinator_completed" in event_types
    assert "coordinator_state" in event_types


def test_run_event_payload_has_typed_envelope() -> None:
    payload = build_event_payload(
        run_id="run_1",
        event_type="permission_stage",
        payload_obj={"stage": "allow_rules", "allowed": True},
    )
    assert payload["run_id"] == "run_1"
    assert payload["event_type"] == "permission_stage"
    assert payload["schema_version"] == "run-events-v1"
    assert payload["phase"] == "permission"
    assert payload["payload"]["stage"] == "allow_rules"


def test_lifecycle_event_shape() -> None:
    payload = lifecycle_event(run_id="r1", event_type="run_paused", action="pause", actor="u1")
    assert payload["phase"] == "lifecycle"
    assert payload["payload"]["action"] == "pause"
    assert payload["payload"]["actor"] == "u1"


def test_hook_exec_id_deterministic() -> None:
    a = hook_exec_id(run_id="r1", hook_point="pre_run_execution", hook_name="x")
    b = hook_exec_id(run_id="r1", hook_point="pre_run_execution", hook_name="x")
    assert a == b


def test_hook_registry_resolves_platform_then_project() -> None:
    async def _platform_hook(_ctx):
        return {"outcome": "OK", "message": "platform"}

    async def _project_hook(_ctx):
        return {"outcome": "OK", "message": "project"}

    register_hook("pre_run_execution", "platform_test", _platform_hook)
    register_hook("pre_run_execution", "project_test", _project_hook, project_id="p123")

    async def _run():
        return await run_hooks("pre_run_execution", {"x": 1}, project_id="p123")

    results = asyncio.run(_run())
    names = [r.hook_name for r in results]
    assert names.index("platform_test") < names.index("project_test")


def test_hook_idempotency_and_concurrency_skip() -> None:
    async def _h(_ctx):
        await asyncio.sleep(0.001)
        return {"outcome": "OK", "message": "ok"}

    register_hook(
        "post_finalization",
        "idem_a",
        _h,
        source="builtin",
        order=1,
        idempotency_key="same",
        max_concurrency=1,
    )
    register_hook(
        "post_finalization",
        "idem_b",
        _h,
        source="builtin",
        order=2,
        idempotency_key="same",
        max_concurrency=1,
    )

    async def _run2():
        return await run_hooks("post_finalization", {"x": 1})

    results = asyncio.run(_run2())
    outcomes = {r.hook_name: r.outcome for r in results}
    assert outcomes["idem_a"] == "OK"
    assert outcomes["idem_b"] == "SKIP"


def test_hook_disable_visibility_and_skip() -> None:
    async def _h(_ctx):
        return {"outcome": "OK", "message": "ok"}

    register_hook("pre_run_execution", "disable_me", _h, source="platform", order=1)
    disable_hook("disable_me")
    hooks = list_registered_hooks()
    hook = [h for h in hooks if h["hook_name"] == "disable_me"][-1]
    assert hook["disabled"] is True

    async def _run3():
        return await run_hooks("pre_run_execution", {"x": 1})

    results = asyncio.run(_run3())
    target = [r for r in results if r.hook_name == "disable_me"][-1]
    assert target.outcome == "SKIP"
    assert target.message == "hook_disabled"


def test_v4_migration_file_present() -> None:
    versions_dir = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    expected = versions_dir / "010_run_controls_and_hook_execution.py"
    assert expected.exists()
    assert (versions_dir / "012_refresh_tokens.py").exists()
    assert (versions_dir / "013_swarm_orchestration.py").exists()


def test_retry_fsm_rejects_invalid_terminal_transitions_under_replay_pressure() -> None:
    assert validate_retry_transition("executing", "recovered") is True
    assert validate_retry_transition("recovered", "executing") is False
    assert validate_retry_transition("dead_letter", "executing") is False


def test_event_schema_consistent_for_mixed_lifecycle_retry_hook() -> None:
    lifecycle = build_event_payload(run_id="r1", event_type="run_paused", payload_obj={"action": "pause"})
    retry = build_event_payload(run_id="r1", event_type="retry_scheduled", payload_obj={"retry_state": "scheduled"})
    hook = build_event_payload(run_id="r1", event_type="hook_result", payload_obj={"outcome": "SKIP"})
    for ev in (lifecycle, retry, hook):
        assert ev["schema_version"] == "run-events-v1"
        assert "payload" in ev and isinstance(ev["payload"], dict)
        assert {"event_type", "phase", "ts_ms", "run_id"} <= set(ev.keys())


def test_hook_exception_defaults_to_abort() -> None:
    async def _boom(_ctx):
        raise ValueError("fail")

    register_hook("post_output_generation", "err_default", _boom, order=500)

    async def _run():
        return await run_hooks("post_output_generation", {})

    results = asyncio.run(_run())
    r = [x for x in results if x.hook_name == "err_default"][-1]
    assert r.outcome == "ABORT"
    assert "hook_error" in r.message


def test_hook_exception_advisory_stays_warn() -> None:
    async def _boom(_ctx):
        raise ValueError("fail")

    register_hook("post_output_generation", "err_advisory", _boom, order=501, advisory=True)

    async def _run():
        return await run_hooks("post_output_generation", {})

    results = asyncio.run(_run())
    r = [x for x in results if x.hook_name == "err_advisory"][-1]
    assert r.outcome == "WARN"
    assert "hook_error" in r.message


def test_hook_timeout_defaults_to_abort() -> None:
    async def _slow(_ctx):
        await asyncio.sleep(5.0)
        return {"outcome": "OK"}

    register_hook("post_output_generation", "slow_abort", _slow, order=502)

    async def _run():
        return await run_hooks("post_output_generation", {}, timeout_sec=0.05)

    results = asyncio.run(_run())
    r = [x for x in results if x.hook_name == "slow_abort"][-1]
    assert r.outcome == "ABORT"
    assert r.message == "hook_timeout"


def test_hook_timeout_advisory_is_warn() -> None:
    async def _slow(_ctx):
        await asyncio.sleep(5.0)
        return {"outcome": "OK"}

    register_hook("post_output_generation", "slow_warn", _slow, order=503, advisory=True)

    async def _run():
        return await run_hooks("post_output_generation", {}, timeout_sec=0.05)

    results = asyncio.run(_run())
    r = [x for x in results if x.hook_name == "slow_warn"][-1]
    assert r.outcome == "WARN"
    assert r.message == "hook_timeout"

