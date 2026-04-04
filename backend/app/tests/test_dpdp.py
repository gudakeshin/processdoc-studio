import json

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.dpdp import DPDPService, build_breach_notification_report, update_breach_incident_state


def _auth_header(client: TestClient, email: str = "owner@admin.com") -> dict[str, str]:
    resp = client.post("/api/auth/login", json={"email": email, "password": "secret123"})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_consent_ledger_lists_project_entries_newest_first() -> None:
    client = TestClient(app)
    headers = _auth_header(client)
    project_resp = client.post("/api/projects", json={"name": "Consent Ledger Proj"}, headers=headers)
    assert project_resp.status_code == 200
    pid = project_resp.json()["id"]

    r1 = client.post(
        f"/api/dpdp/{pid}/consent",
        json={"principal_id": "user_a", "purpose": "analytics"},
        headers=headers,
    )
    assert r1.status_code == 200
    r2 = client.post(
        f"/api/dpdp/{pid}/consent",
        json={"principal_id": "user_b", "purpose": "support"},
        headers=headers,
    )
    assert r2.status_code == 200

    ledger = client.get(f"/api/dpdp/{pid}/consent-ledger", headers=headers)
    assert ledger.status_code == 200
    data = ledger.json()
    assert data["project_id"] == pid
    items = data["items"]
    assert len(items) >= 2
    # Most recently recorded consent first (user_b after user_a).
    assert items[0]["principal_id"] == "user_b"
    principals = [x["principal_id"] for x in items]
    assert "user_a" in principals and "user_b" in principals
    assert all("created_at" in x and "granted" in x for x in items)


def test_dpdp_redacts_aadhaar() -> None:
    service = DPDPService()
    redacted, report = service.redact("Aadhaar 1234 5678 9012")
    assert "[PERSON_ID_AADHAAR]" in redacted
    assert report["pii_entities_redacted"] == 1
    assert report["detector_name"] == "regex_v1"
    assert report["detector_confidence"] > 0
    assert report["gate7_confidence_threshold"] == 0.6
    entity = report["pii_entities_found"][0]
    assert "confidence" in entity
    assert "detector_name" in entity


def test_gate7_uses_confidence_threshold() -> None:
    service = DPDPService(gate7_confidence_threshold=0.99)
    _, report = service.redact("PAN ABCDE1234F")
    # Regex detector confidence is 0.95, below 0.99 => gate7 remains pass.
    assert report["pii_entities_redacted"] == 1
    assert report["gate7_pass"] is True


def test_breach_incident_has_state_timeline_and_sanitized_entities(tmp_path) -> None:
    old_root = settings.workspace_root
    settings.workspace_root = str(tmp_path)
    try:
        service = DPDPService()
        _, report = service.redact("Aadhaar 1234 5678 9012")
        out = build_breach_notification_report("p1", "r1", report, dpo_email=None)
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["state"] == "open"
        assert isinstance(payload.get("timeline"), list) and payload["timeline"]
        assert payload["pii_entities_found"][0].get("match") is None
        assert payload["pii_entities_found"][0].get("pseudonym")

        updated = update_breach_incident_state(
            "p1",
            "r1",
            actor="owner@example.com",
            state="resolved",
            resolution_notes="Reviewed and closed",
        )
        assert updated is not None
        assert updated["state"] == "resolved"
        assert updated["resolution_notes"] == "Reviewed and closed"
        assert len(updated["timeline"]) >= 2
    finally:
        settings.workspace_root = old_root
