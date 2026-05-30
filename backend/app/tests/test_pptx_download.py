"""Tests for canonical PPTX download endpoint."""

from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from app.db.models import Run
from app.db.session import SessionLocal
from app.main import app
from app.services.artifact_integrity import sha256_bytes
from app.services.storage import save_run_artifacts, workspace_path


def auth_header(client: TestClient, email: str) -> dict[str, str]:
    resp = client.post("/api/auth/login", json={"email": email, "password": "secret123"})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_pptx_download_streams_on_disk_output() -> None:
    client = TestClient(app)
    headers = auth_header(client, email="pptxdownload@example.com")
    project_resp = client.post("/api/projects", json={"name": "PPTX Download Test"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    run_id = "run_pptx_download"
    db = SessionLocal()
    try:
        db.add(
            Run(
                id=run_id,
                project_id=project_id,
                status="review_ready",
                output_types='["pptx"]',
                instruction="Need a quick deck",
                plan_payload='{"output_type_representations":{"pptx":"pptx"}}',
            )
        )
        db.commit()
    finally:
        db.close()

    save_run_artifacts(
        project_id,
        run_id,
        {
            "requested_outputs": ["pptx"],
            "pptx_slides": [
                {"slide_type": "title", "title": "Download Demo"},
                {"slide_type": "bullets", "title": "Signals", "bullets": ["One", "Two"]},
            ],
            "process_model": {"process_name": "Download"},
        },
    )

    run_dir = workspace_path(project_id) / "runs" / run_id
    disk_bytes = (run_dir / "output.pptx").read_bytes()
    assert disk_bytes[:2] == b"PK"

    artifacts_resp = client.get(f"/api/runs/{project_id}/{run_id}/artifacts", headers=headers)
    assert artifacts_resp.status_code == 200
    artifacts = artifacts_resp.json()["artifacts"]
    assert base64.b64decode(artifacts["pptx_base64"]) == disk_bytes
    assert artifacts["pptx_integrity"]["sha256"] == sha256_bytes(disk_bytes)

    download_resp = client.get(
        f"/api/runs/{project_id}/{run_id}/artifacts/pptx/download",
        headers=headers,
    )
    assert download_resp.status_code == 200
    assert download_resp.content == disk_bytes
    assert "ExecutiveDeck" in download_resp.headers.get("content-disposition", "")
