"""Final deliverable approval transitions runs to terminal done."""

import json

from fastapi.testclient import TestClient

from app.db.models import Run
from app.db.session import SessionLocal
from app.main import app
from app.services.storage import workspace_path
from app.tests.test_auth_hitl import auth_header


def test_final_approve_with_passing_reports_sets_done() -> None:
    client = TestClient(app)
    headers = auth_header(client, email="final-approve@example.com")
    project_resp = client.post("/api/projects", json={"name": "FinalApproveProj"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]
    run_id = "run_finalapprove01"
    db = SessionLocal()
    try:
        db.add(
            Run(
                id=run_id,
                project_id=project_id,
                status="review_ready",
                output_types='["docx"]',
                instruction="Fixture run for final approval",
                plan_payload=json.dumps({"output_type_representations": {"docx": "docx"}}),
            )
        )
        db.commit()
    finally:
        db.close()

    run_dir = workspace_path(project_id) / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "visual_qa_report.json").write_text(json.dumps({"status": "pass"}), encoding="utf-8")
    (run_dir / "guardrail_report.json").write_text(json.dumps({"status": "pass"}), encoding="utf-8")

    resp = client.post(
        f"/api/runs/{project_id}/{run_id}/final-approve",
        json={"notes": "Approved in test"},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "done"

    events = client.get(f"/api/runs/{project_id}/{run_id}/events", headers=headers)
    assert events.status_code == 200
    types = [item["event_type"] for item in events.json()["items"]]
    assert "done" in types
