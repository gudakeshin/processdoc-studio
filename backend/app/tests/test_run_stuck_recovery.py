"""Stuck-run detection & recovery: watchdog, startup-reconcile, and the /active health endpoint."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.models import Project, Run, RunEvent, User, utcnow
from app.db.session import SessionLocal, init_db
from app.main import app
from app.services import run_worker


def _seed_run(session, *, run_id: str, project_id: str, status: str, last_event_age_sec: float | None) -> None:
    session.add(
        Run(
            id=run_id,
            project_id=project_id,
            status=status,
            output_types="[]",
            instruction="x",
            plan_payload="{}",
            approved_by=None,
            approved_at=utcnow(),
        )
    )
    if last_event_age_sec is not None:
        session.add(
            RunEvent(
                run_id=run_id,
                event_type="step",
                payload="{}",
                created_at=utcnow() - timedelta(seconds=last_event_age_sec),
            )
        )


def test_auto_fail_stuck_runs_fails_stale_leaves_fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    init_db()
    monkeypatch.setattr(settings, "run_stuck_timeout_sec", 300)
    session = SessionLocal()
    try:
        session.add(User(id="u_stuck", email="stuck@test.local", hashed_password="x"))
        session.add(Project(id="p_stuck", name="StuckWatch", created_by="u_stuck"))
        _seed_run(session, run_id="r_stuck_hung", project_id="p_stuck", status="running", last_event_age_sec=400)
        _seed_run(session, run_id="r_stuck_fresh", project_id="p_stuck", status="running", last_event_age_sec=0)
        session.commit()
    finally:
        session.close()

    failed = run_worker.auto_fail_stuck_runs()
    assert failed >= 1

    verify = SessionLocal()
    try:
        hung = verify.get(Run, "r_stuck_hung")
        fresh = verify.get(Run, "r_stuck_fresh")
        assert hung.status == "failed"
        assert fresh.status == "running"
        events = [e.event_type for e in verify.query(RunEvent).filter_by(run_id="r_stuck_hung").all()]
        assert "stuck_auto_failed" in events
    finally:
        verify.close()


def test_auto_fail_disabled_when_timeout_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    init_db()
    monkeypatch.setattr(settings, "run_stuck_timeout_sec", 0)
    session = SessionLocal()
    try:
        session.add(User(id="u_off", email="off@test.local", hashed_password="x"))
        session.add(Project(id="p_off", name="WatchOff", created_by="u_off"))
        _seed_run(session, run_id="r_off_hung", project_id="p_off", status="running", last_event_age_sec=99999)
        session.commit()
    finally:
        session.close()

    assert run_worker.auto_fail_stuck_runs() == 0
    verify = SessionLocal()
    try:
        assert verify.get(Run, "r_off_hung").status == "running"
    finally:
        verify.close()


def test_startup_reconcile_fails_orphaned_running(monkeypatch: pytest.MonkeyPatch) -> None:
    init_db()
    monkeypatch.setattr(settings, "run_queue_startup_reconcile", True)
    # Avoid side effects from the approved-requeue branch.
    monkeypatch.setattr(run_worker, "enqueue_run_execution", lambda *a, **k: True)
    session = SessionLocal()
    try:
        session.add(User(id="u_orph", email="orph@test.local", hashed_password="x"))
        session.add(Project(id="p_orph", name="Orphan", created_by="u_orph"))
        _seed_run(session, run_id="r_orphan", project_id="p_orph", status="running", last_event_age_sec=5)
        session.commit()
    finally:
        session.close()

    run_worker.reconcile_stalled_approved_runs_on_startup()

    verify = SessionLocal()
    try:
        orphan = verify.get(Run, "r_orphan")
        assert orphan.status == "failed"
        events = [e.event_type for e in verify.query(RunEvent).filter_by(run_id="r_orphan").all()]
        assert "stuck_auto_failed" in events
    finally:
        verify.close()


@pytest.fixture()
def allow_signup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_allow_self_signup", True)


def _auth_header(client: TestClient, email: str) -> dict[str, str]:
    resp = client.post("/api/auth/login", json={"email": email, "password": "secret123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_active_runs_endpoint_states_and_role(allow_signup: None, monkeypatch: pytest.MonkeyPatch) -> None:
    init_db()
    monkeypatch.setattr(settings, "run_stuck_timeout_sec", 30)
    # Keep the background watchdog from mutating our seeded rows mid-assertion.
    monkeypatch.setattr(run_worker, "auto_fail_stuck_runs", lambda: 0)

    client = TestClient(app)
    headers = _auth_header(client, "ops_owner@example.com")
    pr = client.post("/api/projects", json={"name": "Active Health"}, headers=headers)
    assert pr.status_code == 200, pr.text
    pid = pr.json()["id"]

    session = SessionLocal()
    try:
        _seed_run(session, run_id="r_act_hung", project_id=pid, status="running", last_event_age_sec=120)
        _seed_run(session, run_id="r_act_working", project_id=pid, status="running", last_event_age_sec=2)
        _seed_run(session, run_id="r_act_wait", project_id=pid, status="plan_ready", last_event_age_sec=5)
        _seed_run(session, run_id="r_act_queued", project_id=pid, status="approved", last_event_age_sec=5)
        session.commit()
    finally:
        session.close()

    resp = client.get(f"/api/runs/{pid}/active", headers=headers)
    assert resp.status_code == 200, resp.text
    by_id = {it["id"]: it for it in resp.json()["items"]}
    assert by_id["r_act_hung"]["state"] == "hung" and by_id["r_act_hung"]["stale"] is True
    assert by_id["r_act_hung"]["seconds_since_last_event"] >= 100
    assert by_id["r_act_working"]["state"] == "working" and by_id["r_act_working"]["stale"] is False
    assert by_id["r_act_wait"]["state"] == "awaiting_approval"
    assert by_id["r_act_queued"]["state"] == "queued"

    # A non-member is rejected.
    outsider = _auth_header(client, "ops_outsider@example.com")
    forbidden = client.get(f"/api/runs/{pid}/active", headers=outsider)
    assert forbidden.status_code == 403
