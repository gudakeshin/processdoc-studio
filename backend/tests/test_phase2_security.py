"""Phase 2: login enumeration, SSE run scope, CORS headers, prompt hygiene helpers."""

import uuid
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agents.prompt_hygiene import UNTRUSTED_JSON_USER_NOTE, UNTRUSTED_SKILL_SYSTEM_NOTE, wrap_untrusted
from app.core.auth import ensure_user, get_password_hash
from app.core.config import Settings
from app.db.models import Run, User
from app.db.session import SessionLocal
from app.main import app


def _auth_header(client: TestClient, *, email: str = "owner@admin.com", password: str = "secret123") -> dict[str, str]:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_ensure_user_no_enumeration_when_signup_disabled() -> None:
    """Unknown email + disabled self-signup must mirror wrong-password (same 401 body)."""
    from app.core.config import settings

    db = SessionLocal()
    try:
        email = "phase2_enum_owner@example.com"
        u = db.scalar(select(User).where(User.email == email))
        if not u:
            u = User(
                id=f"u_{uuid.uuid4().hex[:10]}",
                email=email,
                hashed_password=get_password_hash("secret123"),
            )
            db.add(u)
            db.commit()

        with patch.object(settings, "auth_allow_self_signup", False):
            with pytest.raises(HTTPException) as wrong_pw:
                ensure_user(email, "not-the-right-password", db)
            with pytest.raises(HTTPException) as unknown:
                ensure_user("phase2_no_such_user@example.com", "x", db)
        assert wrong_pw.value.status_code == unknown.value.status_code == 401
        assert wrong_pw.value.detail == unknown.value.detail
    finally:
        db.close()


def test_sse_token_for_foreign_run_forbidden() -> None:
    client = TestClient(app)
    owner = _auth_header(client, email="sse_owner@example.com")
    outsider = _auth_header(client, email="sse_outsider@example.com")

    pr = client.post("/api/projects", json={"name": "SSE Proj"}, headers=owner)
    assert pr.status_code == 200
    pid = pr.json()["id"]

    rid = f"run_{uuid.uuid4().hex[:12]}"
    db = SessionLocal()
    try:
        db.add(
            Run(
                id=rid,
                project_id=pid,
                status="draft",
                output_types='["docx"]',
                instruction="test",
                plan_payload="{}",
            )
        )
        db.commit()
    finally:
        db.close()

    tok = client.post("/api/auth/sse-token", json={"run_id": rid}, headers=outsider)
    assert tok.status_code == 403
    assert "run" in tok.json().get("detail", "").lower()


def test_sse_token_for_missing_run_forbidden() -> None:
    client = TestClient(app)
    h = _auth_header(client)
    tok = client.post("/api/auth/sse-token", json={"run_id": "run_does_not_exist_zzzz"}, headers=h)
    assert tok.status_code == 403


def test_cors_preflight_allows_explicit_methods() -> None:
    client = TestClient(app)
    r = client.options(
        "/api/health/ready",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code == 200
    allow = r.headers.get("access-control-allow-methods", "")
    assert "*" not in allow
    assert "GET" in allow.upper()


def test_wrap_untrusted_escapes_label() -> None:
    w = wrap_untrusted("bad<label", "hello")
    assert "<untrusted" in w
    assert "hello" in w
    assert 'source="badlabel"' in w.replace(" ", "")


def test_settings_reject_bash_in_production() -> None:
    with pytest.raises(ValueError, match="BASH_TOOL_ENABLED"):
        Settings.model_validate(
            {
                "jwt_secret": "x" * 32,
                "database_url": "sqlite:///:memory:",
                "processdoc_env": "production",
                "cors_origins": "https://app.example.com",
                "bash_tool_enabled": True,
            }
        )


def test_settings_require_cors_origins_in_production() -> None:
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        Settings.model_validate(
            {
                "jwt_secret": "x" * 32,
                "database_url": "sqlite:///:memory:",
                "processdoc_env": "production",
                "cors_origins": "",
            }
        )


def test_untrusted_json_note_present() -> None:
    assert "untrusted" in UNTRUSTED_JSON_USER_NOTE.lower()


def test_untrusted_skill_system_note_present() -> None:
    assert "untrusted" in UNTRUSTED_SKILL_SYSTEM_NOTE.lower()


def test_settings_reject_cors_wildcard() -> None:
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        Settings.model_validate(
            {
                "jwt_secret": "x" * 32,
                "database_url": "sqlite:///:memory:",
                "cors_origins": "http://localhost:3000,*",
            }
        )


def test_login_http_same_response_wrong_password_vs_unknown_user(monkeypatch: pytest.MonkeyPatch) -> None:
    """API must not distinguish unknown accounts from bad passwords when self-signup is off."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "auth_allow_self_signup", False)
    client = TestClient(app)
    bad_pw = client.post("/api/auth/login", json={"email": "owner@admin.com", "password": "not-the-password"})
    unknown = client.post("/api/auth/login", json={"email": "no_such_user_phase2@example.com", "password": "x"})
    assert bad_pw.status_code == unknown.status_code == 401
    assert bad_pw.json() == unknown.json()


def test_login_rate_limit_returns_429_when_limiter_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """SlowAPI is disabled by default in tests; re-enable briefly and use a tight limit."""
    from app.core.config import settings
    from app.core.rate_limit import limiter

    monkeypatch.setattr(settings, "auth_login_rate_limit", "2/minute")
    limiter.reset()
    limiter.enabled = True
    try:
        client = TestClient(app)
        for _ in range(2):
            r = client.post("/api/auth/login", json={"email": "owner@admin.com", "password": "secret123"})
            assert r.status_code == 200, r.text
        r429 = client.post("/api/auth/login", json={"email": "owner@admin.com", "password": "secret123"})
        assert r429.status_code == 429
    finally:
        limiter.reset()
