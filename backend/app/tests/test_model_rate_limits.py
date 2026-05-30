"""Rate limit enforcement tests for calculation endpoints.

SlowAPI is globally disabled in conftest.py (autouse fixture). These tests
re-enable it for their scope with a fixture that resets state after each test.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import limiter
from app.main import app
from app.tests.test_auth_hitl import auth_header


@pytest.fixture()
def client_with_limits():
    """TestClient with rate limiting enabled; resets limiter state afterwards."""
    prev = limiter.enabled
    limiter.enabled = True
    # Reset any in-memory counters so this test starts fresh
    if hasattr(limiter, "_storage") and hasattr(limiter._storage, "_storage"):
        try:
            limiter._storage._storage.clear()  # type: ignore[union-attr]
        except Exception:
            pass
    try:
        yield TestClient(app)
    finally:
        limiter.enabled = prev


def _login_and_create_project(client: TestClient, email: str) -> tuple[dict, str, str]:
    headers = auth_header(client, email=email)
    resp = client.post("/api/projects", json={"name": f"RL-test-{email}"}, headers=headers)
    assert resp.status_code == 200
    pid = resp.json()["id"]
    # Create a model to use
    mr = client.post(
        f"/api/projects/{pid}/models",
        json={"name": "RL Model", "description": "rate limit test"},
        headers=headers,
    )
    assert mr.status_code in (200, 201)
    mid = mr.json()["id"]
    return headers, pid, mid


_NPV_BODY = {"cash_flows": [-100.0, 30.0, 40.0, 50.0], "discount_rate": 0.10}
_DCF_BODY = {
    "revenue_projections": [100.0, 110.0, 121.0],
    "cogs_percentages": 0.4,
    "opex_projections": 0.2,
    "tax_rate": 0.21,
    "wacc": 0.10,
    "terminal_growth": 0.02,
}


def test_npv_rate_limited(client_with_limits):
    """First 30 NPV requests succeed; 31st returns 429."""
    client = client_with_limits
    headers, pid, mid = _login_and_create_project(client, "npv-rate@example.com")
    url = f"/api/projects/{pid}/models/{mid}/calculate/npv"

    statuses = []
    for _ in range(31):
        resp = client.post(url, json=_NPV_BODY, headers=headers)
        statuses.append(resp.status_code)

    assert all(s == 200 for s in statuses[:30]), f"Expected all 200s, got {statuses[:30]}"
    assert statuses[30] == 429, f"Expected 429 on 31st request, got {statuses[30]}"


def test_dcf_rate_limited(client_with_limits):
    """First 10 DCF requests succeed; 11th returns 429."""
    client = client_with_limits
    headers, pid, mid = _login_and_create_project(client, "dcf-rate@example.com")
    url = f"/api/projects/{pid}/models/{mid}/calculate/dcf"

    statuses = []
    for _ in range(11):
        resp = client.post(url, json=_DCF_BODY, headers=headers)
        statuses.append(resp.status_code)

    assert all(s == 200 for s in statuses[:10]), f"Expected all 200s, got {statuses[:10]}"
    assert statuses[10] == 429, f"Expected 429 on 11th request, got {statuses[10]}"
