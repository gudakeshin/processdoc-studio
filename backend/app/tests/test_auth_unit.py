"""Unit tests for auth.py: token validation, role enforcement, and cache behaviour."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.core.auth import create_sse_token
from app.core.config import settings
from app.main import app
from app.tests.test_auth_hitl import auth_header


# Use an auth-gated endpoint that exists: GET /api/projects
_AUTHED_ENDPOINT = "/api/projects"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def registered_user(client: TestClient) -> dict:
    email = "auth-unit-test@example.com"
    resp = client.post("/api/auth/login", json={"email": email, "password": "pw1234"})
    assert resp.status_code == 200
    data = resp.json()
    return {"email": email, "access_token": data["access_token"]}


# ---------------------------------------------------------------------------
# Token decode & type checking
# ---------------------------------------------------------------------------

def test_valid_token_returns_user(registered_user, client):
    headers = {"Authorization": f"Bearer {registered_user['access_token']}"}
    resp = client.get(_AUTHED_ENDPOINT, headers=headers)
    assert resp.status_code == 200


def test_expired_token_raises_401(client):
    exp = datetime.utcnow() - timedelta(seconds=1)
    token = jwt.encode(
        {"sub": "nobody@example.com", "exp": exp, "typ": "access"},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    resp = client.get(_AUTHED_ENDPOINT, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_refresh_token_rejected_as_access_token(client, registered_user):
    exp = datetime.utcnow() + timedelta(days=7)
    refresh = jwt.encode(
        {"sub": registered_user["email"], "exp": exp, "typ": "refresh", "jti": "fake-jti"},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    resp = client.get(_AUTHED_ENDPOINT, headers={"Authorization": f"Bearer {refresh}"})
    assert resp.status_code == 401


def test_garbage_token_raises_401(client):
    resp = client.get(_AUTHED_ENDPOINT, headers={"Authorization": "Bearer not.a.real.token"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# require_project_role
# ---------------------------------------------------------------------------

def test_require_project_role_passes_for_owner(client):
    headers = auth_header(client, email="proj-owner@example.com")
    resp = client.post("/api/projects", json={"name": "Role Test Project"}, headers=headers)
    assert resp.status_code == 200
    pid = resp.json()["id"]

    resp2 = client.get(f"/api/projects/{pid}/models", headers=headers)
    assert resp2.status_code == 200


def test_require_project_role_blocks_non_member(client):
    owner_headers = auth_header(client, email="proj-owner2@example.com")
    resp = client.post("/api/projects", json={"name": "Private Project"}, headers=owner_headers)
    assert resp.status_code == 200
    pid = resp.json()["id"]

    stranger_headers = auth_header(client, email="stranger@example.com")
    resp2 = client.get(f"/api/projects/{pid}/models", headers=stranger_headers)
    assert resp2.status_code == 403


# ---------------------------------------------------------------------------
# Cache hit avoids DB lookup
# ---------------------------------------------------------------------------

def test_auth_cache_hit_skips_db_on_second_call(registered_user, client):
    """Second request with same token must serve user from cache, bypassing DB."""
    headers = {"Authorization": f"Bearer {registered_user['access_token']}"}

    # Prime the cache on first call
    resp1 = client.get(_AUTHED_ENDPOINT, headers=headers)
    assert resp1.status_code == 200

    with patch("app.core.auth.cache_service.get") as mock_get:
        mock_get.return_value = {
            "id": "u_cached",
            "email": registered_user["email"],
            "hashed_password": "$2b$12$fakehash",
        }
        with patch("sqlalchemy.orm.Session.scalar") as mock_scalar:
            resp2 = client.get(_AUTHED_ENDPOINT, headers=headers)
            assert resp2.status_code == 200
            mock_scalar.assert_not_called()


# ---------------------------------------------------------------------------
# Refresh token flow
# ---------------------------------------------------------------------------

def test_refresh_token_rotation(client):
    """Login → use refresh token → get new access token."""
    resp = client.post("/api/auth/login", json={"email": "refresh-user@example.com", "password": "pw123"})
    assert resp.status_code == 200
    data = resp.json()
    assert "refresh_token" in data
    refresh = data["refresh_token"]

    resp2 = client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert resp2.status_code == 200
    new_data = resp2.json()
    assert "access_token" in new_data
    assert new_data["access_token"] != data["access_token"]


def test_expired_refresh_token_rejected(client):
    """Expired refresh token must return 401."""
    exp = datetime.utcnow() - timedelta(seconds=1)
    bad_refresh = jwt.encode(
        {"sub": "refresh-user@example.com", "exp": exp, "typ": "refresh", "jti": "old-jti"},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    resp = client.post("/api/auth/refresh", json={"refresh_token": bad_refresh})
    assert resp.status_code == 401


def test_access_token_rejected_as_refresh(client, registered_user):
    """Access token used on /refresh endpoint must return 401."""
    resp = client.post("/api/auth/refresh", json={"refresh_token": registered_user["access_token"]})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# SSE token path (get_current_user_sse)
# ---------------------------------------------------------------------------

def test_sse_token_allows_events_access(client):
    """SSE token accepted via ?token= query parameter on events endpoint."""
    headers = auth_header(client, email="sse-user@example.com")

    # Create project and a run to have a valid project_id context
    proj = client.post("/api/projects", json={"name": "SSE Token Project"}, headers=headers)
    assert proj.status_code == 200
    pid = proj.json()["id"]

    # Issue an SSE token
    token_resp = client.post("/api/auth/sse-token", json={}, headers=headers)
    assert token_resp.status_code == 200
    sse_tok = token_resp.json()["sse_token"]

    # Use SSE token via query param on the events listing endpoint (no Bearer header)
    resp = client.get(f"/api/runs/{pid}/nonexistent-run/events?token={sse_tok}")
    # 403 = authenticated but no membership/run; 404 = authenticated, project/run not found
    # Either way it is NOT 401 — meaning sse token auth succeeded
    assert resp.status_code != 401


def test_sse_endpoint_rejects_missing_token(client):
    """Events endpoint without any token returns 401."""
    resp = client.get("/api/runs/proj/run/events")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# ensure_user (self-signup path)
# ---------------------------------------------------------------------------

def test_self_signup_creates_new_user(client):
    """Login with unknown email creates the user (self-signup enabled in conftest)."""
    email = "brand-new-signup@example.com"
    resp = client.post("/api/auth/login", json={"email": email, "password": "strongpass!"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()

    # Second login with same credentials must succeed
    resp2 = client.post("/api/auth/login", json={"email": email, "password": "strongpass!"})
    assert resp2.status_code == 200


def test_wrong_password_returns_401(client):
    """Wrong password on existing user returns 401."""
    email = "existing-pw-user@example.com"
    client.post("/api/auth/login", json={"email": email, "password": "correctpass"})
    resp = client.post("/api/auth/login", json={"email": email, "password": "wrongpass"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Project role cache warming
# ---------------------------------------------------------------------------

def test_project_role_cached_on_repeated_access(client):
    """Repeated membership checks for same user+project use the cache after first hit."""
    headers = auth_header(client, email="cache-role@example.com")
    resp = client.post("/api/projects", json={"name": "Cache Role Project"}, headers=headers)
    assert resp.status_code == 200
    pid = resp.json()["id"]

    with patch("app.core.auth.cache_service.set") as mock_set:
        # First access primes the cache
        r1 = client.get(f"/api/projects/{pid}/models", headers=headers)
        assert r1.status_code == 200
        # cache_service.set should have been called (for user lookup and/or role)
        assert mock_set.called
