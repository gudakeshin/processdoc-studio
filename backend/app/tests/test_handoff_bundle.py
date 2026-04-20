"""Tests for the Claude Code handoff bundle builder and download endpoint (PPT-303)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.handoff_bundle import build_handoff_bundle
from app.main import app
from app.services.storage import save_run_artifacts
from app.tests.plan_helpers import confirm_plan_for_project


def auth_header(client: TestClient, email: str) -> dict[str, str]:
    resp = client.post("/api/auth/login", json={"email": email, "password": "secret123"})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_build_handoff_bundle_includes_available_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "p_test" / "runs" / "r_test"
    run_dir.mkdir(parents=True)
    (run_dir / "user_instruction.txt").write_text("Build a finance deck", encoding="utf-8")
    (run_dir / "assembled_context.txt").write_text("context snippet", encoding="utf-8")
    (run_dir / "process_model.json").write_text(json.dumps({"process_name": "P2P"}), encoding="utf-8")
    (run_dir / "pptx_slides.json").write_text(json.dumps([{"title": "Intro"}]), encoding="utf-8")
    (run_dir / "qa_report.json").write_text(json.dumps({"aggregate_score": 0.9}), encoding="utf-8")
    (run_dir / "output.pptx").write_bytes(b"not-a-real-pptx")

    result = build_handoff_bundle(
        run_dir,
        metadata={
            "project_id": "p_test",
            "run_id": "r_test",
            "status": "completed",
            "instruction": "Build a finance deck",
        },
    )
    assert result.zip_path is not None and result.zip_path.exists()
    with zipfile.ZipFile(result.zip_path) as zf:
        names = set(zf.namelist())
        assert "README.md" in names
        assert "run_metadata.json" in names
        assert "instruction.md" in names
        assert "assembled_context.txt" in names
        assert "process_model.json" in names
        assert "pptx_slides.json" in names
        assert "qa_report.json" in names
        assert "deliverables.txt" in names
        assert "handoff_manifest.json" in names
        meta = json.loads(zf.read("run_metadata.json").decode("utf-8"))
        assert meta["project_id"] == "p_test"
        assert meta["run_id"] == "r_test"
        manifest = json.loads(zf.read("handoff_manifest.json").decode("utf-8"))
        assert "pptx_slides.json" in manifest["included"]
        assert "output.pptx" in manifest["deliverables"]
        readme = zf.read("README.md").decode("utf-8")
        assert "p_test" in readme
        assert "r_test" in readme
        assert "pptx_slides.json" in readme


def test_build_handoff_bundle_handles_empty_run_dir(tmp_path: Path) -> None:
    run_dir = tmp_path / "empty" / "runs" / "r_empty"
    run_dir.mkdir(parents=True)
    result = build_handoff_bundle(run_dir)
    assert result.zip_path is not None and result.zip_path.exists()
    with zipfile.ZipFile(result.zip_path) as zf:
        names = set(zf.namelist())
        assert "README.md" in names
        assert "run_metadata.json" in names
        assert "handoff_manifest.json" in names
        manifest = json.loads(zf.read("handoff_manifest.json").decode("utf-8"))
        assert manifest["deliverables"] == []
        assert "user_instruction.txt" in manifest["missing"] or "pptx_slides.json" in manifest["missing"]


def test_build_handoff_bundle_missing_run_dir_fail_open(tmp_path: Path) -> None:
    result = build_handoff_bundle(tmp_path / "does" / "not" / "exist")
    assert result.zip_path is None
    assert result.errors and "not found" in result.errors[0].lower()


def test_handoff_bundle_endpoint_returns_zip() -> None:
    client = TestClient(app)
    headers = auth_header(client, email="handoff@example.com")
    project_resp = client.post("/api/projects", json={"name": "Handoff Test"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    conv_id, plan_hash = confirm_plan_for_project(client, headers, project_id)
    run_resp = client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "conversation_id": conv_id,
            "plan_hash": plan_hash,
            "instruction": "Need a quick deck",
            "output_types": ["pptx"],
            "output_type_representations": {"pptx": "pptx"},
        },
        headers=headers,
    )
    assert run_resp.status_code == 200
    run_id = run_resp.json()["run_id"]

    save_run_artifacts(
        project_id,
        run_id,
        {
            "requested_outputs": ["pptx"],
            "pptx_slides": [
                {"slide_type": "title", "title": "Handoff Demo"},
                {"slide_type": "bullets", "title": "Signals", "bullets": ["One", "Two"]},
            ],
            "process_model": {"process_name": "Handoff"},
        },
    )

    resp = client.get(
        f"/api/runs/{project_id}/{run_id}/handoff_bundle",
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert "HandoffBundle" in resp.headers.get("content-disposition", "")
    assert resp.content[:2] == b"PK"
