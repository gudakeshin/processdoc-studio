"""DB pool integration: 20 concurrent requests must all succeed (no 500s)."""

from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi.testclient import TestClient

from app.main import app
from app.tests.test_auth_hitl import auth_header


def test_concurrent_requests_no_deadlock():
    """Fire 20 simultaneous authenticated requests; assert none return 5xx."""
    client = TestClient(app)
    headers = auth_header(client, email="pool-test@example.com")

    # Create a project once (sequentially) so the concurrent reads have a real endpoint
    resp = client.post("/api/projects", json={"name": "Pool Test Project"}, headers=headers)
    assert resp.status_code == 200

    def fetch(_: int) -> int:
        r = client.get("/api/projects", headers=headers)
        return r.status_code

    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = [pool.submit(fetch, i) for i in range(20)]
        statuses = [f.result() for f in as_completed(futures)]

    assert all(s < 500 for s in statuses), f"Got 5xx responses: {[s for s in statuses if s >= 500]}"
    assert all(s in (200, 401, 403) for s in statuses), f"Unexpected statuses: {set(statuses)}"
