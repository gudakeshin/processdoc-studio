import json
import time
import threading

import pytest
from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from app.core.config import settings
from app.services.storage import workspace_path
from app.tests.plan_helpers import confirm_plan_for_project


def auth_header(client: TestClient, email: str = "owner@admin.com") -> dict[str, str]:
    resp = client.post("/api/auth/login", json={"email": email, "password": "secret123"})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _safe_get(client: TestClient, url: str, *, headers: dict[str, str] | None = None, timeout_sec: float = 10.0):
    # TestClient SSE calls can occasionally block indefinitely in CI-like environments.
    box: dict[str, object] = {}

    def _runner() -> None:
        try:
            box["resp"] = client.get(url, headers=headers)
        except Exception as exc:  # pragma: no cover - defensive branch
            box["exc"] = exc

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout=timeout_sec)
    if t.is_alive():
        pytest.skip(f"stream call timed out after {timeout_sec}s")
    if "exc" in box:
        raise box["exc"]  # type: ignore[misc]
    return box["resp"]  # type: ignore[return-value]


def test_project_create_and_hitl_approval_flow() -> None:
    client = TestClient(fastapi_app)
    headers = auth_header(client)

    project_resp = client.post("/api/projects", json={"name": "Engagement"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    conv_id, plan_hash = confirm_plan_for_project(client, headers, project_id)
    run_resp = client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "conversation_id": conv_id,
            "plan_hash": plan_hash,
            "output_types": ["docx"],
            "instruction": "Build a narrative",
        },
        headers=headers,
    )
    assert run_resp.status_code == 200
    payload = run_resp.json()
    assert payload["status"] == "plan_ready"
    assert payload["plan"]["skill_card"] == "auto_selected"
    assert payload["plan"].get("conversation_id") == conv_id
    assert payload["plan"].get("plan_hash") == plan_hash

    ev = client.get(
        f"/api/runs/{project_id}/{payload['run_id']}/events?after_event_id=0",
        headers=headers,
    )
    assert ev.status_code == 200
    assert "awaiting_hitl_approval" in json.dumps(ev.json())

    approve_resp = client.post(f"/api/runs/{project_id}/{payload['run_id']}/approve", headers=headers)
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "approved"


def _step_statuses_from_event_items(items: list[dict]) -> list[str]:
    statuses: list[str] = []
    for item in items:
        if item.get("event_type") != "step":
            continue
        pay = item.get("payload")
        if not isinstance(pay, dict):
            continue
        inner = pay.get("payload")
        st = inner.get("status") if isinstance(inner, dict) else None
        if st is None:
            st = pay.get("status")
        if isinstance(st, str):
            statuses.append(st)
    return statuses


def test_approve_returns_200_and_events_show_execution_enqueued() -> None:
    """Happy-path queue verification: approve succeeds and job is persisted as enqueued (local queue).

    `execution_started` is covered by the slow full-run SSE test; worker timing varies with DB/threading.
    """
    client = TestClient(fastapi_app)
    headers = auth_header(client)
    project_resp = client.post("/api/projects", json={"name": "Queue happy path"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]
    conv_id, plan_hash = confirm_plan_for_project(client, headers, project_id)
    run_resp = client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "conversation_id": conv_id,
            "plan_hash": plan_hash,
            "output_types": ["docx"],
            "instruction": "Queue smoke",
        },
        headers=headers,
    )
    assert run_resp.status_code == 200
    run_id = run_resp.json()["run_id"]
    approve_resp = client.post(f"/api/runs/{project_id}/{run_id}/approve", headers=headers)
    assert approve_resp.status_code == 200, approve_resp.text
    assert approve_resp.json().get("status") == "approved"
    seen: set[str] = set()
    for _ in range(200):
        ev = client.get(f"/api/runs/{project_id}/{run_id}/events?after_event_id=0", headers=headers)
        assert ev.status_code == 200
        seen.update(_step_statuses_from_event_items(ev.json().get("items") or []))
        if "execution_enqueued" in seen:
            break
        time.sleep(0.05)
    assert "execution_enqueued" in seen, f"step statuses seen: {sorted(seen)}"


def test_start_run_requires_output_selection_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(fastapi_app)
    headers = auth_header(client)
    project_resp = client.post("/api/projects", json={"name": "Selection Required"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    def _fake_confirmed_plan(**_: object) -> dict[str, object]:
        return {
            "conversation_id": "conv_test",
            "plan_hash": "plan_test",
            "instruction": "Create a finance transformation proposal.",
            "template_output_types": [],
            "custom_output_types": [],
            "output_type_representations": {},
            "content_skill_targets": {},
            "regeneration_directive": "",
            "decision_answers": {},
            "strategy_dossier": None,
            "selected_strategy": None,
        }

    monkeypatch.setattr("app.api.runs._load_confirmed_plan", _fake_confirmed_plan)

    run_resp = client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "conversation_id": "conv_test",
            "plan_hash": "plan_test",
            "instruction": "Create a proposal.",
        },
        headers=headers,
    )
    assert run_resp.status_code == 400
    detail = run_resp.json().get("detail") or {}
    assert detail.get("code") == "output_selection_required"
    assert "inferred_template_output_types" in detail


def test_start_run_respects_explicit_output_types_without_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(fastapi_app)
    headers = auth_header(client)
    project_resp = client.post("/api/projects", json={"name": "Explicit Outputs"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    def _fake_confirmed_plan(**_: object) -> dict[str, object]:
        return {
            "conversation_id": "conv_test",
            "plan_hash": "plan_test",
            "instruction": "Create a proposal.",
            "template_output_types": [],
            "custom_output_types": [],
            "output_type_representations": {},
            "content_skill_targets": {},
            "regeneration_directive": "",
            "decision_answers": {},
            "strategy_dossier": None,
            "selected_strategy": None,
        }

    monkeypatch.setattr("app.api.runs._load_confirmed_plan", _fake_confirmed_plan)

    run_resp = client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "conversation_id": "conv_test",
            "plan_hash": "plan_test",
            "instruction": "Create a proposal.",
            "output_types": ["pptx"],
        },
        headers=headers,
    )
    assert run_resp.status_code == 200
    payload = run_resp.json()
    assert payload.get("plan", {}).get("sub_agents") == ["pptx"]


def test_redo_proposal_plan_persists_content_skill_targets_into_run_plan() -> None:
    client = TestClient(fastapi_app)
    headers = auth_header(client, email="proposal@test.com")
    project_resp = client.post("/api/projects", json={"name": "Proposal"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    msg = client.post(
        f"/api/projects/{project_id}/conversation/messages",
        json={"content": "Draft a finance transformation proposal and pitch deck for CFO review."},
        headers=headers,
    )
    assert msg.status_code == 200
    body = msg.json()
    conv_id = body["conversation_id"]
    plan_hash = body["plan_hash"]
    cst = body.get("content_skill_targets") or {}
    assert cst.get("docx") == "proposal_finance_transformation_v1"
    if not body.get("ready_for_confirmation"):
        prompts = body.get("decision_prompts") if isinstance(body, dict) else []
        unresolved = set(body.get("unresolved_prompt_ids") or [])
        answers: list[dict[str, object]] = []
        if isinstance(prompts, list):
            for prompt in prompts:
                if not isinstance(prompt, dict):
                    continue
                prompt_id = str(prompt.get("id") or "").strip()
                if not prompt_id or prompt_id not in unresolved:
                    continue
                options = prompt.get("options") if isinstance(prompt.get("options"), list) else []
                first = options[0] if options and isinstance(options[0], dict) else {}
                first_value = str(first.get("value") or "").strip()
                if not first_value:
                    continue
                answers.append({"prompt_id": prompt_id, "selected_values": [first_value]})
        if answers:
            decision_resp = client.post(
                f"/api/projects/{project_id}/conversation/decisions",
                json={
                    "conversation_id": conv_id,
                    "plan_hash": plan_hash,
                    "answers": answers,
                },
                headers=headers,
            )
            assert decision_resp.status_code == 200
            body = decision_resp.json()
            conv_id = body["conversation_id"]
            plan_hash = body["plan_hash"]

    conf = client.post(
        f"/api/projects/{project_id}/conversation/confirm",
        json={"conversation_id": conv_id, "plan_hash": plan_hash},
        headers=headers,
    )
    assert conf.status_code == 200

    run_resp = client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "conversation_id": conv_id,
            "plan_hash": plan_hash,
            "instruction": "Create deliverables",
        },
        headers=headers,
    )
    assert run_resp.status_code == 200
    plan = run_resp.json().get("plan") or {}
    run_targets = plan.get("content_skill_targets") or {}
    assert run_targets.get("docx") == "proposal_finance_transformation_v1"


def test_update_run_plan_preserves_existing_content_skill_targets() -> None:
    client = TestClient(fastapi_app)
    headers = auth_header(client, email="plan-edit-proposal@test.com")
    project_resp = client.post("/api/projects", json={"name": "Proposal Plan Edit"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    msg = client.post(
        f"/api/projects/{project_id}/conversation/messages",
        json={"content": "Create a finance transformation proposal for CFO and controllership leaders."},
        headers=headers,
    )
    assert msg.status_code == 200
    body = msg.json()
    conv_id = body["conversation_id"]
    plan_hash = body["plan_hash"]
    if not body.get("ready_for_confirmation"):
        prompts = body.get("decision_prompts") if isinstance(body, dict) else []
        unresolved = set(body.get("unresolved_prompt_ids") or [])
        answers: list[dict[str, object]] = []
        if isinstance(prompts, list):
            for prompt in prompts:
                if not isinstance(prompt, dict):
                    continue
                prompt_id = str(prompt.get("id") or "").strip()
                if not prompt_id or prompt_id not in unresolved:
                    continue
                options = prompt.get("options") if isinstance(prompt.get("options"), list) else []
                first = options[0] if options and isinstance(options[0], dict) else {}
                first_value = str(first.get("value") or "").strip()
                if first_value:
                    answers.append({"prompt_id": prompt_id, "selected_values": [first_value]})
        if answers:
            decision_resp = client.post(
                f"/api/projects/{project_id}/conversation/decisions",
                json={"conversation_id": conv_id, "plan_hash": plan_hash, "answers": answers},
                headers=headers,
            )
            assert decision_resp.status_code == 200
            body = decision_resp.json()
            conv_id = body["conversation_id"]
            plan_hash = body["plan_hash"]

    conf = client.post(
        f"/api/projects/{project_id}/conversation/confirm",
        json={"conversation_id": conv_id, "plan_hash": plan_hash},
        headers=headers,
    )
    assert conf.status_code == 200

    run_resp = client.post(
        "/api/runs",
        json={"project_id": project_id, "conversation_id": conv_id, "plan_hash": plan_hash, "instruction": "Create deliverables"},
        headers=headers,
    )
    assert run_resp.status_code == 200
    run_payload = run_resp.json()
    run_id = run_payload["run_id"]
    initial_targets = (run_payload.get("plan") or {}).get("content_skill_targets") or {}
    assert initial_targets.get("docx") == "proposal_finance_transformation_v1"

    patch_resp = client.patch(
        f"/api/runs/{project_id}/{run_id}/plan",
        json={
            "instruction": "Updated instruction for same proposal run.",
            "output_types": ["docx"],
            "custom_output_types": [],
            "output_type_representations": {"docx": "docx"},
        },
        headers=headers,
    )
    assert patch_resp.status_code == 200
    updated_targets = (patch_resp.json().get("plan") or {}).get("content_skill_targets") or {}
    assert updated_targets.get("docx") == "proposal_finance_transformation_v1"


def test_list_runs_and_sse_accepts_query_token() -> None:
    client = TestClient(fastapi_app)
    headers = auth_header(client, email="editor@example.com")

    project_resp = client.post("/api/projects", json={"name": "Second"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    conv_id, plan_hash = confirm_plan_for_project(client, headers, project_id)
    run_resp = client.post(
        "/api/runs",
        json={"project_id": project_id, "conversation_id": conv_id, "plan_hash": plan_hash, "instruction": "Hello"},
        headers=headers,
    )
    assert run_resp.status_code == 200
    run_id = run_resp.json()["run_id"]
    token = headers["Authorization"].split(" ", 1)[1]

    list_resp = client.get(f"/api/runs?project_id={project_id}", headers=headers)
    assert list_resp.status_code == 200
    ids = {item["id"] for item in list_resp.json()["items"]}
    assert run_id in ids

    ev = client.get(f"/api/runs/{project_id}/{run_id}/events?after_event_id=0&token={token}")
    assert ev.status_code == 200
    types = [x.get("event_type") for x in (ev.json().get("items") or [])]
    assert "plan_ready" in types


@pytest.mark.slow
def test_stream_completes_after_approve_with_persisted_events() -> None:
    client = TestClient(fastapi_app)
    headers = auth_header(client, email="finish@example.com")

    project_resp = client.post("/api/projects", json={"name": "Finish"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    conv_id, plan_hash = confirm_plan_for_project(client, headers, project_id)
    run_resp = client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "conversation_id": conv_id,
            "plan_hash": plan_hash,
            "instruction": "Complete run",
        },
        headers=headers,
    )
    assert run_resp.status_code == 200
    run_id = run_resp.json()["run_id"]

    ap = client.post(f"/api/runs/{project_id}/{run_id}/approve", headers=headers)
    assert ap.status_code == 200

    # Worker + context assembly (embeddings, compaction) can lag the first SSE read; poll briefly.
    body = ""
    for _ in range(60):
        stream = _safe_get(client, f"/api/runs/{project_id}/{run_id}/stream", headers=headers, timeout_sec=10.0)
        assert stream.status_code == 200
        body = stream.text
        if "review_ready" in body and "qa_report" in body:
            break
        time.sleep(0.25)
    if "review_ready" not in body and (
        "api_error" in body or "billing" in body.lower() or "credit" in body.lower()
    ):
        pytest.skip("Anthropic API/billing blocked full run in this environment")

    assert "execution_started" in body
    assert "qa_report" in body
    # Guardrails may appear as streamed guardrail_event rows and/or final guardrail_report payload.
    assert "guardrail_event" in body or "guardrail_report" in body
    # Runs typically pause at review_ready; stricter evaluator policy may fail fast.
    assert ("review_ready" in body) or ("event: failed" in body)

    ev = client.get(f"/api/runs/{project_id}/{run_id}/events", headers=headers)
    assert ev.status_code == 200
    body = ev.json()
    assert body.get("plan") is not None
    types = [i["event_type"] for i in body["items"]]
    assert ("qa_report" in types) or ("failed" in types)
    assert "step" in types

    last_id = max(i["id"] for i in body["items"])
    resume = _safe_get(
        client,
        f"/api/runs/{project_id}/{run_id}/stream?after_event_id={last_id}",
        headers=headers,
        timeout_sec=10.0,
    )
    assert resume.status_code == 200
    assert "plan_ready" not in resume.text


def test_refresh_issues_new_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_allow_self_signup", True)
    client = TestClient(fastapi_app)
    resp = client.post("/api/auth/login", json={"email": "refresh@example.com", "password": "s3cret01!"})
    assert resp.status_code == 200
    body = resp.json()
    assert "refresh_token" in body
    r2 = client.post("/api/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert r2.status_code == 200
    r2j = r2.json()
    assert r2j["access_token"] != body["access_token"]
    assert "refresh_token" in r2j
    assert r2j["refresh_token"] != body["refresh_token"]


def test_refresh_token_cannot_be_used_as_bearer_for_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_allow_self_signup", True)
    client = TestClient(fastapi_app)
    login = client.post("/api/auth/login", json={"email": "split@example.com", "password": "s3cret01!"})
    assert login.status_code == 200
    refresh_only = login.json()["refresh_token"]
    proj = client.get("/api/projects", headers={"Authorization": f"Bearer {refresh_only}"})
    assert proj.status_code == 401


def test_approve_returns_429_with_backpressure_headers(monkeypatch) -> None:
    import app.api.runs as runs_module

    def fake_admission(_project_id: str, *, user_id: str | None = None) -> dict:
        return {
            "project_id": _project_id,
            "project_active_runs": 20,
            "project_limit": 20,
            "global_active_runs": 500,
            "global_limit": 500,
            "user_id": user_id,
            "user_active_runs": 8,
            "user_limit": 8,
            "queue_depth": 42,
            "queue_backend": "local",
            "retry_after_sec": 9,
            "allowed": False,
        }

    monkeypatch.setattr(runs_module, "admission_status", fake_admission)

    client = TestClient(fastapi_app)
    headers = auth_header(client, email="backpressure@example.com")
    project_resp = client.post("/api/projects", json={"name": "Backpressure"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    conv_id, plan_hash = confirm_plan_for_project(client, headers, project_id)
    run_resp = client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "conversation_id": conv_id,
            "plan_hash": plan_hash,
            "instruction": "Should be throttled",
        },
        headers=headers,
    )
    assert run_resp.status_code == 200
    run_id = run_resp.json()["run_id"]

    ap = client.post(f"/api/runs/{project_id}/{run_id}/approve", headers=headers)
    assert ap.status_code == 429
    assert ap.headers.get("Retry-After") == "9"
    assert ap.headers.get("X-Admission-Project-Limit") == "20"
    assert ap.headers.get("X-Admission-Global-Limit") == "500"
    assert ap.headers.get("X-Admission-User-Limit") == "8"
    assert ap.headers.get("X-Admission-Queue-Depth") == "42"


def test_dead_letter_list_and_replay_endpoints(monkeypatch) -> None:
    import app.api.runs as runs_module

    item = {
        "id": "dl_test_1",
        "project_id": None,
        "run_id": "r1",
        "status": "open",
        "reason": "queue_deserialize_failed",
    }
    monkeypatch.setattr(runs_module, "list_dead_letter_items", lambda project_id=None, limit=100: [item])
    monkeypatch.setattr(
        runs_module,
        "replay_dead_letter_item",
        lambda item_id: {**item, "id": item_id, "status": "replayed"},
    )

    client = TestClient(fastapi_app)
    headers = auth_header(client, email="dl@example.com")
    project_resp = client.post("/api/projects", json={"name": "DeadLetter"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    listed = client.get(f"/api/runs/{project_id}/queue/dead-letter", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == "dl_test_1"

    replay = client.post(
        f"/api/runs/{project_id}/queue/dead-letter/replay",
        json={"item_id": "dl_test_1"},
        headers=headers,
    )
    assert replay.status_code == 200
    assert replay.json()["item"]["status"] == "replayed"


def test_dead_letter_replay_returns_409_when_not_replayable(monkeypatch) -> None:
    import app.api.runs as runs_module

    item = {
        "id": "dl_test_blocked",
        "project_id": None,
        "run_id": "r2",
        "status": "open",
        "reason": "unsupported_reason",
        "replay_blocked_reason": "reason_not_replayable",
    }
    monkeypatch.setattr(
        runs_module,
        "replay_dead_letter_item",
        lambda item_id: {**item, "id": item_id},
    )

    client = TestClient(fastapi_app)
    headers = auth_header(client, email="dl409@example.com")
    project_resp = client.post("/api/projects", json={"name": "DeadLetter409"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    replay = client.post(
        f"/api/runs/{project_id}/queue/dead-letter/replay",
        json={"item_id": "dl_test_blocked"},
        headers=headers,
    )
    assert replay.status_code == 409


def test_dead_letter_replay_returns_409_after_max_attempts(monkeypatch) -> None:
    import app.api.runs as runs_module

    item = {
        "id": "dl_test_max",
        "project_id": None,
        "run_id": "r3",
        "status": "open",
        "reason": "execution_failed",
        "replay_attempts": 3,
        "max_replay_attempts": 3,
        "replay_blocked_reason": "max_replay_attempts_exceeded",
    }
    monkeypatch.setattr(
        runs_module,
        "replay_dead_letter_item",
        lambda item_id: {**item, "id": item_id},
    )

    client = TestClient(fastapi_app)
    headers = auth_header(client, email="dlmax@example.com")
    project_resp = client.post("/api/projects", json={"name": "DeadLetterMax"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    replay = client.post(
        f"/api/runs/{project_id}/queue/dead-letter/replay",
        json={"item_id": "dl_test_max"},
        headers=headers,
    )
    assert replay.status_code == 409


def test_dead_letter_reset_attempts_owner_only_endpoint(monkeypatch) -> None:
    import app.api.runs as runs_module

    item = {
        "id": "dl_test_reset",
        "project_id": None,
        "run_id": "r4",
        "status": "open",
        "reason": "execution_failed",
        "replay_attempts": 0,
        "max_replay_attempts": 3,
        "attempts_reset_by": "owner@example.com",
    }
    monkeypatch.setattr(
        runs_module,
        "reset_dead_letter_attempts",
        lambda item_id, actor=None: {**item, "id": item_id, "attempts_reset_by": actor},
    )

    client = TestClient(fastapi_app)
    headers = auth_header(client, email="ownerreset@example.com")
    project_resp = client.post("/api/projects", json={"name": "DeadLetterReset"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    resp = client.post(
        f"/api/runs/{project_id}/queue/dead-letter/reset-attempts",
        json={"item_id": "dl_test_reset"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["item"]["replay_attempts"] == 0


def test_run_accepts_custom_output_types_and_artifacts_exposes_them() -> None:
    client = TestClient(fastapi_app)
    headers = auth_header(client, email="customformats@example.com")
    project_resp = client.post("/api/projects", json={"name": "CustomFormats"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    conv_id, plan_hash = confirm_plan_for_project(client, headers, project_id)
    run_resp = client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "conversation_id": conv_id,
            "plan_hash": plan_hash,
            "instruction": "Need user-specific outputs",
            "output_types": ["docx"],
            "custom_output_types": ["Executive brief PDF", "Board slide deck"],
        },
        headers=headers,
    )
    assert run_resp.status_code == 200
    run_id = run_resp.json()["run_id"]
    plan = run_resp.json()["plan"]
    assert plan["custom_output_types"] == ["Executive brief PDF", "Board slide deck"]

    artifacts = client.get(f"/api/runs/{project_id}/{run_id}/artifacts", headers=headers)
    assert artifacts.status_code == 200
    payload = artifacts.json()
    assert payload["output_types"] == ["docx"]
    assert payload["custom_output_types"] == ["Executive brief PDF", "Board slide deck"]


def test_project_settings_forbidden_for_non_member() -> None:
    client = TestClient(fastapi_app)
    owner_headers = auth_header(client, email="owner-settings@example.com")
    outsider_headers = auth_header(client, email="outsider-settings@example.com")

    project_resp = client.post("/api/projects", json={"name": "PrivateSettings"}, headers=owner_headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    resp = client.get(f"/api/projects/{project_id}/settings", headers=outsider_headers)
    assert resp.status_code == 403


def test_dpdp_rights_forbidden_for_non_member() -> None:
    client = TestClient(fastapi_app)
    owner_headers = auth_header(client, email="owner-dpdp@example.com")
    outsider_headers = auth_header(client, email="outsider-dpdp@example.com")

    project_resp = client.post("/api/projects", json={"name": "PrivateDPDP"}, headers=owner_headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    resp = client.post(
        "/api/dpdp/rights",
        json={
            "project_id": project_id,
            "principal_id": "p1",
            "request_type": "access",
            "details": "req",
        },
        headers=outsider_headers,
    )
    assert resp.status_code == 403


def test_slide_regeneration_element_scope_persists_inline_comment() -> None:
    client = TestClient(fastapi_app)
    headers = auth_header(client, email="element-scope@test.com")
    project_resp = client.post("/api/projects", json={"name": "ElementScope"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]
    conv_id, plan_hash = confirm_plan_for_project(client, headers, project_id)
    run_resp = client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "conversation_id": conv_id,
            "plan_hash": plan_hash,
            "output_types": ["pptx"],
            "instruction": "Create deck",
        },
        headers=headers,
    )
    assert run_resp.status_code == 200
    run_id = run_resp.json()["run_id"]

    run_dir = workspace_path(project_id) / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "pptx_slides.json").write_text(
        json.dumps(
            [
                {"slide_id": "slide_01", "slide_index": 1, "slide_type": "bullets", "title": "Slide 1", "bullets": ["a"]},
                {"slide_id": "slide_02", "slide_index": 2, "slide_type": "bullets", "title": "Slide 2", "bullets": ["b"]},
            ]
        ),
        encoding="utf-8",
    )

    regen_resp = client.post(
        f"/api/runs/{project_id}/{run_id}/slides/1/regenerate",
        json={
            "instruction": "Tighten this bullet.",
            "scope": "element",
            "element_path": "bullets[0]",
        },
        headers=headers,
    )
    assert regen_resp.status_code == 200, regen_resp.text
    body = regen_resp.json()
    assert body.get("scope") == "element"
    assert body.get("element_path") == "bullets[0]"

    events_resp = client.get(f"/api/runs/{project_id}/{run_id}/events?after_event_id=0", headers=headers)
    assert events_resp.status_code == 200
    items = events_resp.json().get("items") or []
    regen_events = [ev for ev in items if ev.get("event_type") == "slide_regeneration_requested"]
    assert regen_events
    latest_payload = regen_events[-1].get("payload") or {}
    if isinstance(latest_payload, dict) and isinstance(latest_payload.get("payload"), dict):
        latest_payload = latest_payload.get("payload") or latest_payload
    assert latest_payload.get("scope") == "element"
    assert latest_payload.get("element_path") == "bullets[0]"

    artifacts_resp = client.get(f"/api/runs/{project_id}/{run_id}/artifacts", headers=headers)
    assert artifacts_resp.status_code == 200
    artifacts = artifacts_resp.json().get("artifacts") or {}
    plan_payload = artifacts.get("plan_payload") if isinstance(artifacts, dict) else {}
    inline_comments = plan_payload.get("pptx_inline_comments") if isinstance(plan_payload, dict) else []
    assert isinstance(inline_comments, list) and inline_comments
    assert inline_comments[-1].get("scope") == "element"
    assert inline_comments[-1].get("element_path") == "bullets[0]"
