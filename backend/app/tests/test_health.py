from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_health_ready_includes_database() -> None:
    client = TestClient(app)
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") in {"ready", "degraded"}
    assert "database" in body
    assert body["database"].get("ok") is True


def test_correlation_id_echoed_on_response() -> None:
    client = TestClient(app)
    resp = client.get("/health", headers={"X-Request-ID": "trace-123"})
    assert resp.status_code == 200
    assert resp.headers.get("x-request-id") == "trace-123"


def test_metrics_exposes_queue_and_observability() -> None:
    client = TestClient(app)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("service") == "processdoc-backend"
    assert isinstance(body.get("observability"), dict)
    bash = body.get("bash_tool", {})
    assert isinstance(bash, dict)
    assert "bash_tool_enabled" in bash
    text_editor = body.get("text_editor_tool", {})
    assert isinstance(text_editor, dict)
    assert "text_editor_tool_enabled" in text_editor
    queue = body.get("run_queue", {})
    assert queue.get("backend") in {"local", "redis"}
    assert "depth" in queue
    assert "worker_last_heartbeat_ms" in queue
    assert "worker_processed_total" in queue
    assert "worker_count" in queue
    assert "workers" in queue


def test_workers_health_endpoint() -> None:
    client = TestClient(app)
    resp = client.get("/workers/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("backend") in {"local", "redis"}
    assert isinstance(body.get("healthy"), bool)
    assert "worker_count" in body
    assert isinstance(body.get("workers"), list)


def test_bash_tool_health() -> None:
    client = TestClient(app)
    resp = client.get("/api/health/bash-tool")
    assert resp.status_code == 200
    body = resp.json()
    assert "bash_tool_enabled" in body
    assert "docker_cli_available" in body


def test_bash_capable_turn_requires_auth() -> None:
    client = TestClient(app)
    resp = client.post("/api/projects/p1/agent/bash-capable-turn", json={"message": "hello"})
    assert resp.status_code == 401


def test_text_editor_tool_health() -> None:
    client = TestClient(app)
    resp = client.get("/api/health/text-editor-tool")
    assert resp.status_code == 200
    body = resp.json()
    assert "text_editor_tool_enabled" in body
    assert "max_characters" in body


def test_admission_endpoint() -> None:
    client = TestClient(app)
    resp = client.get("/admission/test-project")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("project_id") == "test-project"
    assert "allowed" in body
    assert "project_limit" in body
    assert "global_limit" in body
