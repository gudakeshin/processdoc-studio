from fastapi.testclient import TestClient

from app.db.models import Run
from app.db.session import SessionLocal
from app.main import app
from app.services.storage import save_run_artifacts
from app.tests.plan_helpers import confirm_plan_for_project


def auth_header(client: TestClient, email: str = "formats@example.com") -> dict[str, str]:
    resp = client.post("/api/auth/login", json={"email": email, "password": "secret123"})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_start_run_accepts_extended_output_types() -> None:
    client = TestClient(app)
    headers = auth_header(client, email="extendedformats@example.com")
    project_resp = client.post("/api/projects", json={"name": "Extended Formats"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    conv_id, plan_hash = confirm_plan_for_project(client, headers, project_id)
    run_resp = client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "conversation_id": conv_id,
            "plan_hash": plan_hash,
            "instruction": "Need docx pptx xlsx pdf and process map",
            "output_types": ["docx", "pptx", "xlsx", "pdf", "process_map"],
            "output_type_representations": {
                "docx": "docx",
                "pptx": "pptx",
                "xlsx": "xlsx",
                "pdf": "pdf",
                "process_map": "drawio_xml",
            },
        },
        headers=headers,
    )
    assert run_resp.status_code == 200
    payload = run_resp.json()
    assert set(payload["plan"]["sub_agents"]) == {"docx", "pptx", "xlsx", "pdf", "process_map"}


def test_run_artifacts_expose_extended_binary_outputs() -> None:
    client = TestClient(app)
    headers = auth_header(client, email="artifactformats@example.com")
    project_resp = client.post("/api/projects", json={"name": "Artifact Formats"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    conv_id, plan_hash = confirm_plan_for_project(client, headers, project_id)
    run_resp = client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "conversation_id": conv_id,
            "plan_hash": plan_hash,
            "instruction": "Generate document package",
            "output_types": ["docx", "pptx", "xlsx", "pdf"],
            "output_type_representations": {
                "docx": "docx",
                "pptx": "pptx",
                "xlsx": "xlsx",
                "pdf": "pdf",
            },
        },
        headers=headers,
    )
    assert run_resp.status_code == 200
    run_id = run_resp.json()["run_id"]

    save_run_artifacts(
        project_id,
        run_id,
        {
            "requested_outputs": ["docx", "pptx", "xlsx", "pdf"],
            "docx_markdown": "# Title\n\nDocx body",
            "pptx_slides": [{"title": "Slide 1", "bullets": ["A", "B"]}],
            "xlsx_markdown": "| A | B |\n|---|---|\n| 1 | 2 |",
            "pdf_markdown": "# PDF\n\nBody",
            "process_model": {"process_name": "Pkg", "steps": []},
        },
    )

    artifacts = client.get(f"/api/runs/{project_id}/{run_id}/artifacts", headers=headers)
    assert artifacts.status_code == 200
    body = artifacts.json()
    assert body.get("output_type_representations") == {
        "docx": "docx",
        "pptx": "pptx",
        "xlsx": "xlsx",
        "pdf": "pdf",
    }
    payload = body["artifacts"]
    assert isinstance(payload["docx_base64"], str) and len(payload["docx_base64"]) > 0
    assert isinstance(payload["pptx_base64"], str) and len(payload["pptx_base64"]) > 0
    assert isinstance(payload["xlsx_base64"], str) and len(payload["xlsx_base64"]) > 0
    assert isinstance(payload["pdf_base64"], str) and len(payload["pdf_base64"]) > 0

    typed = payload.get("typed_outputs") or []
    output_types = {str(item.get("output_type")) for item in typed if isinstance(item, dict)}
    assert "docx" in output_types
    assert "pptx" in output_types
    assert "xlsx" in output_types
    assert "pdf" in output_types


def test_run_artifacts_api_exposes_rich_payload_outputs() -> None:
    client = TestClient(app)
    headers = auth_header(client, email="richpayloadformats@example.com")
    project_resp = client.post("/api/projects", json={"name": "Rich Payload Artifacts"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    run_id = "run_richpayload"
    db = SessionLocal()
    try:
        db.add(
            Run(
                id=run_id,
                project_id=project_id,
                status="review_ready",
                output_types='["docx","pptx","xlsx","pdf"]',
                instruction="Generate rich output package",
                plan_payload='{"output_type_representations":{"docx":"docx","pptx":"pptx","xlsx":"xlsx","pdf":"pdf"}}',
            )
        )
        db.commit()
    finally:
        db.close()

    save_run_artifacts(
        project_id,
        run_id,
        {
            "requested_outputs": ["docx", "pptx", "xlsx", "pdf"],
            "docx_markdown": "\n".join(
                [
                    "# Executive Summary",
                    "",
                    "## Actions",
                    "- Confirm baseline",
                    "- Finalize KPI owners",
                    "",
                    "| KPI | Target |",
                    "|---|---|",
                    "| ROI | 20% |",
                ]
            ),
            "pptx_slides": [
                {
                    "title": "KPI Table",
                    "layout": "title_only",
                    "table": {
                        "headers": ["Metric", "Value"],
                        "rows": [["ROI", "20%"], ["Payback", "8 months"]],
                        "x": 0.8,
                        "y": 1.4,
                        "w": 10.5,
                        "h": 3.0,
                    },
                },
                {
                    "title": "Trend",
                    "layout": "title_only",
                    "chart": {
                        "type": "bar",
                        "categories": ["Q1", "Q2", "Q3"],
                        "series": [{"name": "Margin", "values": [8, 11, 13]}],
                        "x": 0.8,
                        "y": 1.6,
                        "w": 10.5,
                        "h": 4.0,
                    },
                },
            ],
            "xlsx_cells": [
                {"sheet": "Finance", "row": 1, "col": 1, "value": "Revenue", "bold": True, "fill_color": "D9E1F2"},
                {"sheet": "Finance", "row": 1, "col": 2, "value": "Cost", "bold": True, "fill_color": "D9E1F2"},
                {"sheet": "Finance", "row": 1, "col": 3, "value": "Margin", "bold": True, "fill_color": "D9E1F2"},
                {"sheet": "Finance", "row": 2, "col": 1, "value": 1000, "number_format": "#,##0"},
                {"sheet": "Finance", "row": 2, "col": 2, "value": 600, "number_format": "#,##0"},
                {"sheet": "Finance", "row": 2, "col": 3, "formula": "A2-B2", "number_format": "#,##0"},
            ],
            "pdf_markdown": "# Report\n\n## Summary\n\nProcess output generated.",
            "process_model": {"process_name": "Rich Package", "steps": []},
        },
    )

    artifacts = client.get(f"/api/runs/{project_id}/{run_id}/artifacts", headers=headers)
    assert artifacts.status_code == 200
    payload = artifacts.json()["artifacts"]
    assert isinstance(payload["docx_base64"], str) and len(payload["docx_base64"]) > 0
    assert isinstance(payload["pptx_base64"], str) and len(payload["pptx_base64"]) > 0
    assert isinstance(payload["xlsx_base64"], str) and len(payload["xlsx_base64"]) > 0
    assert isinstance(payload["pdf_base64"], str) and len(payload["pdf_base64"]) > 0

    typed = payload.get("typed_outputs") or []
    typed_map = {
        str(item.get("output_type")): str(item.get("body"))
        for item in typed
        if isinstance(item, dict)
    }
    assert typed_map.get("docx") == "binary_file:output.docx"
    assert typed_map.get("pptx") == "binary_file:output.pptx"
    assert typed_map.get("xlsx") == "binary_file:output.xlsx"
    assert typed_map.get("pdf") == "binary_file:output.pdf"

    assert isinstance(payload.get("deck_html"), str) and payload["deck_html"]
    assert "<html" in payload["deck_html"].lower()
    ready = payload.get("ready_downloads") or []
    assert "deck_html" in ready
    filenames = payload.get("output_filenames") or {}
    assert filenames.get("deck_html", "").endswith(".html")
    assert filenames.get("deck_pdf", "").endswith(".pdf")
