"""Tests for GET /api/projects/{pid}/branding.

The endpoint exposes the same BrandingContext the deliverable renderers consume
so the frontend can honor a project's custom brand. Auth mirrors the other
project routes (require_project_role with Owner/Editor/Viewer).
"""

import uuid

from fastapi.testclient import TestClient

from app.db.models import ProjectBrand
from app.db.session import session_scope
from app.main import app as fastapi_app

_HEX = lambda v: isinstance(v, str) and v.startswith("#") and len(v) == 7  # noqa: E731


def auth_header(client: TestClient, email: str) -> dict[str, str]:
    resp = client.post("/api/auth/login", json={"email": email, "password": "secret123"})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _create_project(client: TestClient, headers: dict[str, str], name: str) -> str:
    resp = client.post("/api/projects", json={"name": name}, headers=headers)
    assert resp.status_code == 200
    return resp.json()["id"]


def test_branding_requires_auth() -> None:
    client = TestClient(fastapi_app)
    resp = client.get("/api/projects/p_anything/branding")
    assert resp.status_code == 401


def test_branding_forbidden_for_non_member() -> None:
    client = TestClient(fastapi_app)
    owner_headers = auth_header(client, "owner-branding@example.com")
    outsider_headers = auth_header(client, "outsider-branding@example.com")
    pid = _create_project(client, owner_headers, "PrivateBranding")

    resp = client.get(f"/api/projects/{pid}/branding", headers=outsider_headers)
    assert resp.status_code == 403


def test_branding_returns_resolved_palette_for_member() -> None:
    client = TestClient(fastapi_app)
    headers = auth_header(client, "member-branding@example.com")
    pid = _create_project(client, headers, "DefaultBranding")

    resp = client.get(f"/api/projects/{pid}/branding", headers=headers)
    assert resp.status_code == 200
    body = resp.json()

    assert body["project_id"] == pid
    # Structural contract: the renderers' BrandingContext shape, serialized.
    for key in ("level", "primary_color", "palette", "font_family", "font_size_base", "company_name"):
        assert key in body
    assert _HEX(body["primary_color"])
    palette = body["palette"]
    for role in ("primary", "complementary", "accent_light", "accent_dark"):
        assert _HEX(palette[role]), f"palette.{role} should be a #RRGGBB hex"
    # No ProjectBrand row exists, so resolution falls through to the repo's
    # ingested design system (or the Deloitte default if those files are absent).
    assert body["level"] in {"ingested_design_system", "deloitte_default"}


def test_branding_reflects_project_custom_brand() -> None:
    client = TestClient(fastapi_app)
    headers = auth_header(client, "custom-branding@example.com")
    pid = _create_project(client, headers, "CustomBranding")

    with session_scope() as db:
        db.add(
            ProjectBrand(
                id=f"pb_{uuid.uuid4().hex[:10]}",
                project_id=pid,
                primary_color="#990011",
                font_family="Georgia",
                font_size_base=12,
                company_name="Acme Corp",
            )
        )

    resp = client.get(f"/api/projects/{pid}/branding", headers=headers)
    assert resp.status_code == 200
    body = resp.json()

    assert body["level"] == "project_custom"
    assert body["primary_color"] == "#990011"
    assert body["palette"]["primary"] == "#990011"
    assert body["font_family"] == "Georgia"
    assert body["font_size_base"] == 12
    assert body["company_name"] == "Acme Corp"
