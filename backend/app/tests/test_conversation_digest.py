"""Conversation digest for HITL continuity."""

import pytest

from app.db.models import Conversation, ConversationMessage, Project, User
from app.db.session import SessionLocal, init_db
from app.services.conversation_digest import build_conversation_digest_for_run


@pytest.fixture(autouse=True)
def _init_db() -> None:
    init_db()


def test_build_conversation_digest_orders_oldest_first() -> None:
    session = SessionLocal()
    try:
        uid, pid, cid = "u_digest", "proj_digest", "conv_digest"
        session.add(User(id=uid, email="digest@test.local", hashed_password="x"))
        session.add(Project(id=pid, name="Digest Proj", created_by=uid))
        session.add(Conversation(id=cid, project_id=pid, user_id=uid))
        session.add(ConversationMessage(conversation_id=cid, role="user", content="older turn"))
        session.add(
            ConversationMessage(
                conversation_id=cid,
                role="assistant",
                content="newer turn",
                metadata_json='{"plan_hash":"ph1","ready_for_confirmation":true}',
            ),
        )
        session.commit()

        d = build_conversation_digest_for_run(
            session=session,
            project_id=pid,
            conversation_id=cid,
            char_cap=8000,
            message_limit=10,
        )
        assert "older turn" in d
        assert "newer turn" in d
        assert "plan_hash=ph1" in d
        assert d.index("older turn") < d.index("newer turn")
    finally:
        session.close()


def test_build_conversation_digest_wrong_project_returns_empty() -> None:
    session = SessionLocal()
    try:
        uid, pid, cid = "u_digest2", "proj_digest2", "conv_digest2"
        session.add(User(id=uid, email="digest2@test.local", hashed_password="x"))
        session.add(Project(id=pid, name="P2", created_by=uid))
        session.add(Conversation(id=cid, project_id=pid, user_id=uid))
        session.add(ConversationMessage(conversation_id=cid, role="user", content="secret"))
        session.commit()

        assert (
            build_conversation_digest_for_run(
                session=session,
                project_id="other_project",
                conversation_id=cid,
                char_cap=1000,
            )
            == ""
        )
    finally:
        session.close()
