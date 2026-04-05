"""HTTP integration tests for swarm routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.tests.plan_helpers import confirm_plan_for_project


def _auth_header(client: TestClient, email: str) -> dict[str, str]:
    resp = client.post("/api/auth/login", json={"email": email, "password": "secret123"})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def swarm_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "swarm_orchestration_enabled", True)


@pytest.fixture()
def allow_signup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_allow_self_signup", True)


def test_swarm_tasks_list_requires_flag(allow_signup: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "swarm_orchestration_enabled", False)
    client = TestClient(app)
    email = "swarm_flag_off@example.com"
    headers = _auth_header(client, email)
    pr = client.post("/api/projects", json={"name": "Swarm HTTP Proj"}, headers=headers)
    assert pr.status_code == 200
    pid = pr.json()["id"]
    conv_id, plan_hash = confirm_plan_for_project(client, headers, pid)
    rr = client.post(
        "/api/runs",
        json={
            "project_id": pid,
            "conversation_id": conv_id,
            "plan_hash": plan_hash,
            "instruction": "x",
            "output_types": ["docx"],
        },
        headers=headers,
    )
    assert rr.status_code == 200
    rid = rr.json()["run_id"]
    res = client.get(f"/api/runs/{pid}/{rid}/swarm/tasks", headers=headers)
    assert res.status_code == 403


def test_swarm_tasks_list_and_filter(swarm_on: None, allow_signup: None) -> None:
    client = TestClient(app)
    email = "swarm_list@example.com"
    headers = _auth_header(client, email)
    pr = client.post("/api/projects", json={"name": "Swarm List Proj"}, headers=headers)
    assert pr.status_code == 200
    pid = pr.json()["id"]
    conv_id, plan_hash = confirm_plan_for_project(client, headers, pid)
    rr = client.post(
        "/api/runs",
        json={
            "project_id": pid,
            "conversation_id": conv_id,
            "plan_hash": plan_hash,
            "instruction": "x",
            "output_types": ["docx"],
        },
        headers=headers,
    )
    assert rr.status_code == 200
    rid = rr.json()["run_id"]

    c1 = client.post(
        f"/api/runs/{pid}/{rid}/swarm/tasks",
        headers=headers,
        json={"title": "Alpha", "phase": "custom", "depends_on": []},
    )
    assert c1.status_code == 200
    tid_a = c1.json()["task"]["id"]

    c2 = client.post(
        f"/api/runs/{pid}/{rid}/swarm/tasks",
        headers=headers,
        json={"title": "Beta", "phase": "custom", "depends_on": [tid_a]},
    )
    assert c2.status_code == 200

    all_res = client.get(f"/api/runs/{pid}/{rid}/swarm/tasks", headers=headers)
    assert all_res.status_code == 200
    items = all_res.json()["items"]
    assert len(items) >= 2
    ids = {t["id"] for t in items}
    assert tid_a in ids

    q_res = client.get(f"/api/runs/{pid}/{rid}/swarm/tasks?status=queued", headers=headers)
    assert q_res.status_code == 200
    for t in q_res.json()["items"]:
        assert str(t.get("status") or "").lower() == "queued"


def test_start_run_broadcasts_instruction_to_swarm_when_enabled(swarm_on: None, allow_signup: None) -> None:
    """Cowork alignment: creating a run stores instruction as a swarm broadcast when swarm is on."""
    client = TestClient(app)
    email = "swarm_instr_bc@example.com"
    headers = _auth_header(client, email)
    pr = client.post("/api/projects", json={"name": "Swarm Instr Proj"}, headers=headers)
    assert pr.status_code == 200
    pid = pr.json()["id"]
    conv_id, plan_hash = confirm_plan_for_project(client, headers, pid)
    unique = "UniqueInstrBroadcastXYZ42"
    rr = client.post(
        "/api/runs",
        json={
            "project_id": pid,
            "conversation_id": conv_id,
            "plan_hash": plan_hash,
            "instruction": unique,
            "output_types": ["docx"],
        },
        headers=headers,
    )
    assert rr.status_code == 200
    rid = rr.json()["run_id"]
    mres = client.get(f"/api/runs/{pid}/{rid}/swarm/messages", headers=headers)
    assert mres.status_code == 200
    items = mres.json().get("items") or []
    bodies = [str(x.get("body") or "") for x in items]
    assert any(unique in b for b in bodies)
    assert any("Run instruction:" in b for b in bodies)


def test_start_run_does_not_swarm_broadcast_when_disabled(allow_signup: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "swarm_orchestration_enabled", False)
    client = TestClient(app)
    email = "swarm_instr_off@example.com"
    headers = _auth_header(client, email)
    pr = client.post("/api/projects", json={"name": "Swarm Off Proj"}, headers=headers)
    assert pr.status_code == 200
    pid = pr.json()["id"]
    conv_id, plan_hash = confirm_plan_for_project(client, headers, pid)
    unique = "NoSwarmBroadcast99"
    rr = client.post(
        "/api/runs",
        json={
            "project_id": pid,
            "conversation_id": conv_id,
            "plan_hash": plan_hash,
            "instruction": unique,
            "output_types": ["docx"],
        },
        headers=headers,
    )
    assert rr.status_code == 200
    monkeypatch.setattr(settings, "swarm_orchestration_enabled", True)
    rid = rr.json()["run_id"]
    mres = client.get(f"/api/runs/{pid}/{rid}/swarm/messages", headers=headers)
    assert mres.status_code == 200
    items = mres.json().get("items") or []
    bodies = [str(x.get("body") or "") for x in items]
    assert not any(unique in b for b in bodies)
