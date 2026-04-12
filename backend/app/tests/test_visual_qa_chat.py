"""Visual QA → conversation persistence and helpers."""

from sqlalchemy import select

from fastapi.testclient import TestClient

from app.db.models import ConversationMessage, User
from app.db.session import SessionLocal
from app.main import app
from app.services.visual_qa_chat import (
    build_visual_qa_chat_message_body,
    persist_visual_qa_assistant_message,
    should_persist_visual_qa_chat,
)
from app.tests.test_auth_hitl import auth_header


def test_should_persist_visual_qa_chat_rules() -> None:
    assert should_persist_visual_qa_chat({"status": "warn"}) is True
    assert should_persist_visual_qa_chat({"status": "fail"}) is True
    assert should_persist_visual_qa_chat({"status": "pass", "findings": []}) is True
    assert should_persist_visual_qa_chat({"status": "pass", "findings": ["note"]}) is True
    assert should_persist_visual_qa_chat({}) is False


def test_build_visual_qa_chat_message_body() -> None:
    body = build_visual_qa_chat_message_body(
        {"status": "fail", "summary": "Bad layout", "findings": ["A", "B"]},
        run_id="run_x",
    )
    assert "run_x" in body
    assert "FAIL" in body
    assert "Bad layout" in body
    assert "→ A" in body


def test_build_visual_qa_chat_message_body_pass_clean() -> None:
    body = build_visual_qa_chat_message_body({"status": "pass", "findings": []}, run_id="run_y")
    assert "run_y" in body
    assert "PASS" in body
    assert "No layout" in body or "No layout or image issues" in body


def test_persist_visual_qa_assistant_message_inserts_row() -> None:
    client = TestClient(app)
    headers = auth_header(client, email="vqa-chat@example.com")
    project_resp = client.post("/api/projects", json={"name": "VqaChatProj"}, headers=headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    conv_resp = client.get(f"/api/projects/{project_id}/conversation", headers=headers)
    assert conv_resp.status_code == 200
    conv_id = conv_resp.json()["conversation_id"]

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "vqa-chat@example.com"))
        assert user is not None
        ok = persist_visual_qa_assistant_message(
            db,
            project_id=project_id,
            user_id=user.id,
            run_id="run_test_vqa",
            report={"status": "warn", "summary": "Check slides", "findings": ["Slide 2 thin"]},
        )
        assert ok is True
        db.commit()

        rows = db.scalars(
            select(ConversationMessage).where(ConversationMessage.conversation_id == conv_id)
        ).all()
        assert any("Visual Quality Check" in m.content and "run_test_vqa" in m.content for m in rows)
        meta = next(m for m in rows if "run_test_vqa" in m.content)
        assert "visual_qa_report" in (meta.metadata_json or "")
    finally:
        db.close()
