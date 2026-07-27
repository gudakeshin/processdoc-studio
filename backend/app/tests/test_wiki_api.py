from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.tests.test_auth_hitl import auth_header


def _create_project(client: TestClient, headers: dict[str, str], name: str) -> str:
    resp = client.post("/api/projects", json={"name": name}, headers=headers)
    assert resp.status_code == 200
    return resp.json()["id"]


def test_wiki_health_scorecard_contract() -> None:
    client = TestClient(app)
    headers = auth_header(client, email="wiki-scorecard@example.com")
    project_id = _create_project(client, headers, "Wiki Scorecard Contract")
    resp = client.get(f"/api/wiki/project/health/scorecard?project_id={project_id}", headers=headers)
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "success"
    scorecard = payload["scorecard"]
    assert "stats" in scorecard
    assert "relationship_validation" in scorecard
    assert "lint" in scorecard
    # Internal schema envelopes must not leak through this API contract.
    assert "schema_version" not in scorecard


def test_storyline_roundtrip_save_then_read(monkeypatch) -> None:
    monkeypatch.setattr(settings, "wiki_storyline_canvas_enabled", True)
    client = TestClient(app)
    headers = auth_header(client, email="wiki-storyline@example.com")
    project_id = _create_project(client, headers, "Wiki Storyline")
    draft = {
        "title": "Transformation Storyline",
        "sections": [
            {"order": 1, "name": "Context", "purpose": "Set baseline", "relationship_intent": "references"},
            {"order": 2, "name": "Plan", "purpose": "Define actions", "relationship_intent": "supports"},
        ],
    }
    put_resp = client.put(
        f"/api/wiki/project/storyline/draft?project_id={project_id}",
        json={"draft": draft},
        headers=headers,
    )
    assert put_resp.status_code == 200
    get_resp = client.get(
        f"/api/wiki/project/storyline/draft?project_id={project_id}",
        headers=headers,
    )
    assert get_resp.status_code == 200
    got = get_resp.json()["draft"]
    assert got["title"] == draft["title"]
    assert len(got["sections"]) == 2


def test_storyline_rejects_malformed_section_order(monkeypatch) -> None:
    monkeypatch.setattr(settings, "wiki_storyline_canvas_enabled", True)
    client = TestClient(app)
    headers = auth_header(client, email="wiki-storyline-invalid@example.com")
    project_id = _create_project(client, headers, "Wiki Storyline Invalid")
    bad_draft = {
        "sections": [
            {"order": 1, "name": "Context"},
            {"order": 3, "name": "Gap"},  # non-contiguous order should fail
        ]
    }
    resp = client.put(
        f"/api/wiki/project/storyline/draft?project_id={project_id}",
        json={"draft": bad_draft},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "Section order" in resp.json().get("detail", "")
