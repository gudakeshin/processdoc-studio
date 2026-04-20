"""Swarm orchestration unit tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.db.session import SessionLocal, init_db
from app.services.swarm import (
    enrich_run_todos_with_dependencies,
    ensure_path_within_teammate_workspace,
    ensure_swarm_team,
    format_swarm_mailbox_for_teammate,
    lead_plan_with_optional_llm,
    promote_teammate_artifacts,
    send_swarm_message,
    teammate_workspace_dir,
    validate_task_dag,
)
from app.services.swarm_scheduler import SwarmScheduler


def test_enrich_run_todos_sets_depends_on_chain() -> None:
    rows = [
        {"id": "context", "label": "ctx", "status": "pending"},
        {"id": "process_model", "label": "pm", "status": "pending"},
        {"id": "plan", "label": "pl", "status": "pending"},
        {"id": "out:docx", "label": "docx", "status": "pending"},
        {"id": "qa", "label": "qa", "status": "pending"},
    ]
    out = enrich_run_todos_with_dependencies(rows)
    by_id = {r["id"]: r for r in out}
    assert by_id["process_model"]["depends_on"] == ["context"]
    assert by_id["plan"]["depends_on"] == ["process_model"]
    assert by_id["out:docx"]["depends_on"] == ["plan"]
    assert "out:docx" in by_id["qa"]["depends_on"]


def test_validate_task_dag_detects_cycle() -> None:
    is_valid, error = validate_task_dag({"a", "b"}, {"a": ["b"], "b": ["a"]})
    assert not is_valid
    assert "cycle" in error.lower()


def test_validate_task_dag_missing_dep() -> None:
    is_valid, error = validate_task_dag({"a"}, {"a": ["missing"]})
    assert not is_valid
    assert "unknown" in error.lower()


def test_teammate_workspace_path_containment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    project_id = "proj1"
    (tmp_path / project_id).mkdir(parents=True)
    base = teammate_workspace_dir(project_id, "run-1", "t1")
    assert "swarm" in str(base) and project_id in str(base)
    good = base / "foo" / "bar.txt"
    ensure_path_within_teammate_workspace(project_id, "run-1", "t1", good)
    outside = tmp_path / "outside.txt"
    with pytest.raises(ValueError, match="escapes"):
        ensure_path_within_teammate_workspace(project_id, "run-1", "t1", outside)


def test_promote_teammate_artifacts_copies_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    project_id = "p1"
    (tmp_path / project_id).mkdir(parents=True)
    run_id = "r1"
    tm = "t1"
    team = teammate_workspace_dir(project_id, run_id, tm)
    (team / "a.txt").parent.mkdir(parents=True, exist_ok=True)
    (team / "a.txt").write_text("hello", encoding="utf-8")
    promoted, conflicts = promote_teammate_artifacts(
        project_id=project_id,
        run_id=run_id,
        teammate_id=tm,
        relative_paths=["a.txt"],
    )
    assert "a.txt" in promoted
    assert conflicts == []


def test_swarm_scheduler_ready_tasks() -> None:
    init_db()
    from app.db.models import Project, Run, RunTask, User

    db = SessionLocal()
    try:
        db.add(User(id="u_sw", email="sw@example.com", hashed_password="x"))
        db.add(Project(id="p_sw", name="P", created_by="u_sw"))
        db.add(Run(id="r_sw", project_id="p_sw", status="running", output_types="[]", instruction="i", plan_payload="{}"))
        db.add(
            RunTask(
                id="t1",
                run_id="r_sw",
                project_id="p_sw",
                title="A",
                phase="act",
                status="completed",
                depends_on_json="[]",
            )
        )
        db.add(
            RunTask(
                id="t2",
                run_id="r_sw",
                project_id="p_sw",
                title="B",
                phase="act",
                status="queued",
                depends_on_json=json.dumps(["t1"]),
            )
        )
        db.commit()
        ready = SwarmScheduler.ready_task_ids(db, "r_sw")
        assert "t2" in ready
    finally:
        db.close()


def test_format_swarm_mailbox_includes_broadcast(monkeypatch: pytest.MonkeyPatch) -> None:
    init_db()
    from app.db.models import Project, Run, User

    monkeypatch.setattr(settings, "workspace_root", "/tmp")
    db = SessionLocal()
    try:
        db.add(User(id="u_mb", email="mb@example.com", hashed_password="x"))
        db.add(Project(id="p_mb", name="P", created_by="u_mb"))
        db.add(Run(id="r_mb", project_id="p_mb", status="running", output_types="[]", instruction="i", plan_payload="{}"))
        db.commit()
        ensure_swarm_team(db, project_id="p_mb", run_id="r_mb")
        send_swarm_message(
            db,
            run_id="r_mb",
            project_id="p_mb",
            from_teammate="teammate-2",
            body="hello team",
            to_teammate=None,
            team_id=None,
        )
        db.commit()
    finally:
        db.close()
    text = format_swarm_mailbox_for_teammate(run_id="r_mb", teammate_id="teammate-2", limit=5)
    assert "hello team" in text
    assert "broadcast" in text


def test_lead_plan_llm_merges_extra_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "swarm_llm_lead_enabled", True)
    fake_json = (
        '{"extra_tasks": ['
        '{"id": "custom_x", "title": "Extra review", "depends_on": ["plan"], "phase": "custom"}'
        "]}"
    )
    with patch("app.services.claude.claude_generate", return_value=fake_json), patch(
        "app.services.claude.is_claude_enabled", return_value=True
    ):
        plan = lead_plan_with_optional_llm(wanted=["docx"])
    assert plan.used_llm is True
    ids = {str(t.get("id")) for t in plan.tasks}
    assert "custom_x" in ids
    assert "plan" in ids


def test_lead_plan_llm_invalid_json_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "swarm_llm_lead_enabled", True)
    with patch("app.services.claude.claude_generate", return_value="not json"), patch(
        "app.services.claude.is_claude_enabled", return_value=True
    ):
        plan = lead_plan_with_optional_llm(wanted=["docx"])
    assert plan.used_llm is False
    assert any(t.get("id") == "plan" for t in plan.tasks)
