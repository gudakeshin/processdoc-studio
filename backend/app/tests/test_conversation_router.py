from fastapi.testclient import TestClient

import app.api.projects as projects_module
import app.services.claude as claude_service
import app.services.conversation_router as router_module
from app.main import app as fastapi_app
from app.services.conversation_router import RouterDecision
from app.services.conversation_state import load_state
from app.db.session import SessionLocal
from app.db.models import Conversation
from app.services.storage import workspace_path


def _auth_header(client: TestClient, email: str = "router@admin.com") -> dict[str, str]:
    resp = client.post("/api/auth/login", json={"email": email, "password": "secret123"})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_route_turn_fallback_stays_in_discovery_on_llm_failure(monkeypatch) -> None:
    def _boom(**_: object) -> dict:
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(router_module, "claude_generate_json", _boom)
    decision = router_module.route_turn(
        user_message="Client is Varroc, CFO audience, outcomes needed",
        conv_state="discovery",
        conv_slots={"client": {"name": "Varroc"}},
        recent_messages=[],
        project_context="",
        available_output_types=[{"output_type_id": "docx"}],
    )
    assert decision.intent == "discovery_answer"
    assert decision.next_state == "discovery"
    assert "outcome" in decision.missing_slots


def test_route_turn_parses_payload_and_filters_output_types(monkeypatch) -> None:
    def _ok(**_: object) -> dict:
        return {
            "intent": "commit",
            "confidence": 0.92,
            "extracted_slots": {"client": {"name": "Varroc"}},
            "output_types": ["docx", "bad_type"],
            "representations": {"docx": "docx", "bad_type": "bad"},
            "content_skill_hint": {"domain": "proposal_finance_transformation", "confidence": 0.91},
            "next_state": "ready_to_plan",
            "missing_slots": ["outcome", "win_themes"],
            "reply_hint": "n/a",
            "rationale": "commit requested",
        }

    monkeypatch.setattr(router_module, "claude_generate_json", _ok)
    decision = router_module.route_turn(
        user_message="create proposal",
        conv_state="exploring",
        conv_slots={},
        recent_messages=[],
        project_context="",
        available_output_types=[{"output_type_id": "docx"}, {"output_type_id": "pptx"}],
    )
    assert decision.intent == "commit"
    assert decision.output_types == ["docx"]
    assert decision.representations == {"docx": "docx"}
    assert decision.next_state == "ready_to_plan"


def test_conversation_flow_persists_slots_and_generates_plan(monkeypatch) -> None:
    client = TestClient(fastapi_app)
    headers = _auth_header(client)
    project_resp = client.post("/api/projects", json={"name": "Router flow"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    def _fake_route_turn(**kwargs: object) -> RouterDecision:
        user_message = str(kwargs.get("user_message") or "")
        if "help create a proposal" in user_message.lower():
            return RouterDecision(
                intent="commit",
                confidence=0.95,
                extracted_slots={},
                output_types=["docx"],
                representations={"docx": "docx"},
                content_skill_hint={"domain": "proposal_finance_transformation", "confidence": 0.8},
                next_state="discovery",
                missing_slots=["client", "outcome", "win_themes"],
                reply_hint=None,
                rationale="proposal kickoff",
            )
        return RouterDecision(
            intent="discovery_answer",
            confidence=0.9,
            extracted_slots={
                "client": {"name": "Varroc", "industry": "Manufacturing"},
                "outcome": {"primary": "Secure CFO approval", "decision": "Approve transformation roadmap"},
                "win_themes": ["Transformation outcomes", "Operational impact"],
            },
            output_types=["docx"],
            representations={"docx": "docx"},
            content_skill_hint={"domain": "proposal_finance_transformation", "confidence": 0.8},
            next_state="ready_to_plan",
            missing_slots=[],
            reply_hint=None,
            rationale="slots captured",
        )

    monkeypatch.setattr(projects_module, "route_turn", _fake_route_turn)

    first = client.post(
        f"/api/projects/{project_id}/conversation/messages",
        json={"content": "Help create a proposal for the CFO please"},
        headers=headers,
    )
    assert first.status_code == 200
    first_msg = first.json()["messages"][-1]
    assert first_msg["metadata"]["kind"] == "discovery_questions"

    second = client.post(
        f"/api/projects/{project_id}/conversation/messages",
        json={"content": "Client is Varroc. Audience CFO. Win themes are outcomes and value."},
        headers=headers,
    )
    assert second.status_code == 200
    second_msg = second.json()["messages"][-1]
    assert "template_output_types" in second_msg["metadata"]

    with SessionLocal() as db:
        conv = db.query(Conversation).filter(Conversation.project_id == project_id).first()
        assert conv is not None
        state = load_state(conv)
        assert state.state == "plan_proposed"
        assert state.slots.get("client", {}).get("name") == "Varroc"


def test_out_of_scope_requires_high_confidence_and_no_deliverable_signal(monkeypatch) -> None:
    client = TestClient(fastapi_app)
    headers = _auth_header(client, email="router2@admin.com")
    project_resp = client.post("/api/projects", json={"name": "Router oos"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    def _fake_route_turn(**_: object) -> RouterDecision:
        return RouterDecision(
            intent="out_of_scope",
            confidence=0.9,
            extracted_slots={},
            output_types=[],
            representations={},
            content_skill_hint=None,
            next_state="exploring",
            missing_slots=[],
            reply_hint=None,
            rationale="clearly unsupported",
        )

    monkeypatch.setattr(projects_module, "route_turn", _fake_route_turn)
    monkeypatch.setattr(projects_module, "_contains_deliverable_signal", lambda _text: False)
    resp = client.post(
        f"/api/projects/{project_id}/conversation/messages",
        json={"content": "Book me a flight to Delhi tomorrow"},
        headers=headers,
    )
    assert resp.status_code == 200
    msg = resp.json()["messages"][-1]
    assert msg["metadata"]["kind"] == "out_of_scope_response"


def test_wiki_prefills_client_slot_from_wiki(monkeypatch) -> None:
    client = TestClient(fastapi_app)
    headers = _auth_header(client, email="wiki-prefill@admin.com")
    project_resp = client.post("/api/projects", json={"name": "Wiki prefill"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]
    wiki_dir = workspace_path(project_id) / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (wiki_dir / "client_profile.md").write_text("# Varroc Context\nClient: Varroc\nIndustry: Manufacturing\n", encoding="utf-8")

    monkeypatch.setattr(projects_module, "_extract_discovery_answers", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        projects_module,
        "_extract_discovery_answers_from_wiki",
        lambda **_kwargs: ({"client": {"name": "Varroc", "industry": "Manufacturing"}}, ["client_profile"]),
    )

    def _fake_route_turn(**_: object) -> RouterDecision:
        return RouterDecision(
            intent="clarify",
            confidence=0.7,
            extracted_slots={},
            output_types=[],
            representations={},
            content_skill_hint=None,
            next_state="discovery",
            missing_slots=["outcome", "win_themes"],
            reply_hint=None,
            rationale="need more info",
        )

    monkeypatch.setattr(projects_module, "route_turn", _fake_route_turn)
    resp = client.post(
        f"/api/projects/{project_id}/conversation/messages",
        json={"content": "Please help create a point of view for CFO"},
        headers=headers,
    )
    assert resp.status_code == 200
    with SessionLocal() as db:
        conv = db.query(Conversation).filter(Conversation.project_id == project_id).first()
        assert conv is not None
        state = load_state(conv)
        assert state.slots.get("client", {}).get("name") == "Varroc"


def test_discovery_questions_skip_wiki_filled_slots(monkeypatch) -> None:
    client = TestClient(fastapi_app)
    headers = _auth_header(client, email="wiki-questions@admin.com")
    project_resp = client.post("/api/projects", json={"name": "Wiki questions"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    monkeypatch.setattr(projects_module, "_extract_discovery_answers", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        projects_module,
        "_extract_discovery_answers_from_wiki",
        lambda **_kwargs: ({"client": {"name": "Varroc"}}, ["client_page"]),
    )

    def _fake_route_turn(**_: object) -> RouterDecision:
        return RouterDecision(
            intent="commit",
            confidence=0.9,
            extracted_slots={},
            output_types=["docx"],
            representations={"docx": "docx"},
            content_skill_hint=None,
            next_state="discovery",
            missing_slots=["client", "outcome", "win_themes"],
            reply_hint=None,
            rationale="proposal discovery",
        )

    monkeypatch.setattr(projects_module, "route_turn", _fake_route_turn)
    resp = client.post(
        f"/api/projects/{project_id}/conversation/messages",
        json={"content": "Create a proposal for CFO function"},
        headers=headers,
    )
    assert resp.status_code == 200
    msg = resp.json()["messages"][-1]
    assert msg["metadata"]["kind"] == "discovery_questions"
    rendered = "\n".join(msg["metadata"].get("discovery_questions") or [])
    assert "Who is the client" not in rendered


def test_assistant_reply_cites_wiki_refs(monkeypatch) -> None:
    client = TestClient(fastapi_app)
    headers = _auth_header(client, email="wiki-cite@admin.com")
    project_resp = client.post("/api/projects", json={"name": "Wiki citation"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    monkeypatch.setattr(projects_module, "_extract_discovery_answers", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(projects_module, "_extract_discovery_answers_from_wiki", lambda **_kwargs: ({}, ["Finance Baseline"]))
    monkeypatch.setattr(
        projects_module,
        "_load_project_context_bundle",
        lambda *_args, **_kwargs: {"text": "Context\n[Wiki: Finance Baseline]\nDetails", "wiki_refs": ["Finance Baseline"]},
    )
    monkeypatch.setattr(
        projects_module,
        "route_turn",
        lambda **_kwargs: RouterDecision(
            intent="clarify",
            confidence=0.8,
            extracted_slots={},
            output_types=[],
            representations={},
            content_skill_hint=None,
            next_state="exploring",
            missing_slots=[],
            reply_hint=None,
            rationale="clarify",
        ),
    )
    monkeypatch.setattr(projects_module, "_contains_deliverable_signal", lambda _text: True)
    monkeypatch.setattr(projects_module, "_is_proposal_instruction", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(projects_module, "_has_proposal_slot_signal", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(projects_module, "_recommend_output_types", lambda *_args, **_kwargs: ([], [], {}, "", None))
    monkeypatch.setattr(projects_module, "_grounded_conversational_fallback", lambda **_kwargs: "Using wiki context.")
    monkeypatch.setattr(claude_service, "claude_generate", lambda **_kwargs: "Using wiki context (source: [Wiki: Finance Baseline]).")
    resp = client.post(
        f"/api/projects/{project_id}/conversation/messages",
        json={"content": "what should we do next"},
        headers=headers,
    )
    assert resp.status_code == 200
    assistant_msgs = [m for m in resp.json()["messages"] if m.get("role") == "assistant"]
    assert assistant_msgs
    msg = assistant_msgs[-1]
    assert "Finance Baseline" in (msg.get("metadata", {}).get("wiki_refs") or [])
