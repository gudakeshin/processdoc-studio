"""Regression tests for POST /api/projects/{pid}/conversation/decisions.

The decisions endpoint used to re-invoke the LLM output-type recommender on
every save, so any transient Claude failure (rate limit, network blip, JSON
parse error) surfaced to the user as "Failed to apply decision updates" even
though their selections were valid. The endpoint now reuses the output routing
from the plan that generated the decision prompts and must succeed without any
Claude calls for text routing / outline previews.
"""

from __future__ import annotations

import hashlib
import json
import uuid

import pytest
from fastapi.testclient import TestClient

import app.services.claude as claude_mod
from app.db.models import Conversation, ConversationMessage, User
from app.db.session import SessionLocal
from app.main import app as fastapi_app


def _auth_header(client: TestClient, email: str) -> dict[str, str]:
    client.post("/api/auth/signup", json={"email": email, "password": "secret123"})
    resp = client.post("/api/auth/login", json={"email": email, "password": "secret123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _seed_plan(pid: str, email: str) -> tuple[str, str]:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        assert user is not None
        conv = Conversation(
            id=f"conv_{uuid.uuid4().hex[:10]}",
            project_id=pid,
            user_id=user.id,
            title="Regression",
        )
        db.add(conv)
        db.flush()
        plan_hash = hashlib.sha256(uuid.uuid4().bytes).hexdigest()[:16]
        plan_meta = {
            "instruction": "Create a proposal for the CFO of Varroc",
            "template_output_types": ["pptx", "docx"],
            "custom_output_types": [],
            "output_type_representations": {"pptx": "deck", "docx": "document"},
            "content_skill_targets": {
                "pptx": "proposal_finance_transformation",
                "docx": "proposal_finance_transformation",
            },
            "regeneration_directive": "",
            "rationale": "Proposal kickoff",
            "plan_hash": plan_hash,
            "ready_for_confirmation": False,
            "decision_prompts": [],
            "decision_answers": {},
            "discovery": {
                "client": {"name": "Varroc", "industry": "auto"},
                "audience": "cfo",
            },
            "open_questions": [],
            "soft_hints": [],
            "unresolved_prompt_ids": [
                "narrative_arc",
                "audience_role",
                "tone",
                "slide_length_budget",
            ],
        }
        db.add(ConversationMessage(conversation_id=conv.id, role="user", content="Help create a proposal please"))
        db.add(
            ConversationMessage(
                conversation_id=conv.id,
                role="assistant",
                content="Draft plan ready.",
                metadata_json=json.dumps(plan_meta),
            )
        )
        db.commit()
        return conv.id, plan_hash
    finally:
        db.close()


def test_decisions_endpoint_succeeds_without_claude(monkeypatch: pytest.MonkeyPatch) -> None:
    """Saving decisions must not depend on Claude being reachable.

    This is the exact bug the user hit as "Failed to apply decision updates":
    the endpoint was re-running ``_recommend_output_types`` (a Claude call)
    even though the plan already had template ids. The fix is to reuse the
    plan's routing and only refresh the answers + discovery.
    """
    monkeypatch.setattr(claude_mod, "is_claude_enabled", lambda: False)

    client = TestClient(fastapi_app)
    email = f"decrt-{uuid.uuid4().hex[:8]}@test.io"
    headers = _auth_header(client, email)

    project_resp = client.post("/api/projects", json={"name": "Decision save"}, headers=headers)
    assert project_resp.status_code == 200, project_resp.text
    pid = project_resp.json()["id"]

    conv_id, plan_hash = _seed_plan(pid, email)

    resp = client.post(
        f"/api/projects/{pid}/conversation/decisions",
        headers=headers,
        json={
            "conversation_id": conv_id,
            "plan_hash": plan_hash,
            "answers": [
                {"prompt_id": "narrative_arc", "selected_values": ["scqa"]},
                {"prompt_id": "audience_role", "selected_values": ["cfo"]},
                {"prompt_id": "tone", "selected_values": ["consultative"]},
                {"prompt_id": "slide_length_budget", "selected_values": ["10"]},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # The plan's routing must be preserved (no re-derivation from Claude).
    assert body.get("template_output_types") == ["pptx", "docx"]
    assert body.get("output_type_representations") == {"pptx": "deck", "docx": "document"}
    # Decision answers flow through and drive discovery enrichment.
    assert body.get("decision_answers", {}).get("narrative_arc") == ["scqa"]
    discovery = body.get("discovery") or {}
    assert discovery.get("narrative_arc") == "scqa"
    assert discovery.get("tone") == "consultative"
    assert (discovery.get("length_budget") or {}).get("pptx") == 10
    # Plan hash must change so the client knows the plan was refreshed.
    assert body.get("plan_hash") and body["plan_hash"] != plan_hash


def test_decisions_endpoint_surfaces_structured_error_on_empty_answers() -> None:
    """A user who hits Save without choosing anything gets a structured 400
    with a human-readable message — not a generic fallback."""
    client = TestClient(fastapi_app)
    email = f"decrt-empty-{uuid.uuid4().hex[:8]}@test.io"
    headers = _auth_header(client, email)
    project_resp = client.post("/api/projects", json={"name": "Decision empty"}, headers=headers)
    assert project_resp.status_code == 200, project_resp.text
    pid = project_resp.json()["id"]
    conv_id, plan_hash = _seed_plan(pid, email)

    resp = client.post(
        f"/api/projects/{pid}/conversation/decisions",
        headers=headers,
        json={
            "conversation_id": conv_id,
            "plan_hash": plan_hash,
            "answers": [
                {"prompt_id": "narrative_arc", "selected_values": []},
            ],
        },
    )
    assert resp.status_code == 400
    body = resp.json()
    detail = body.get("detail")
    assert isinstance(detail, dict)
    assert detail.get("code") == "answers_missing"
    assert "selected value" in (detail.get("message") or "").lower()
