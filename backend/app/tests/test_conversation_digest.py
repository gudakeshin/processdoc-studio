"""Conversation digest for HITL continuity."""

import pytest
from datetime import datetime, timedelta

from app.db.models import Conversation, ConversationMessage, Project, User
from app.db.session import SessionLocal, init_db
from app.services.compaction_trace import CompactionTrace
from app.services.conversation_digest import (
    build_conversation_digest_for_run,
    build_conversation_digest_for_run_with_trace,
)


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


def test_build_conversation_digest_tiered_compaction_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "conversation_digest_tiered_compaction_enabled", True)
    monkeypatch.setattr(settings, "conversation_digest_tiered_compaction_threshold_chars", 200)

    session = SessionLocal()
    try:
        uid, pid, cid = "u_digest3", "proj_digest3", "conv_digest3"
        session.add(User(id=uid, email="digest3@test.local", hashed_password="x"))
        session.add(Project(id=pid, name="P3", created_by=uid))
        session.add(Conversation(id=cid, project_id=pid, user_id=uid))
        for i in range(30):
            session.add(
                ConversationMessage(
                    conversation_id=cid,
                    role="user" if i % 2 == 0 else "assistant",
                    content=f"turn {i} " + ("signal " * 80),
                )
            )
        session.commit()

        digest, trace = build_conversation_digest_for_run_with_trace(
            session=session,
            project_id=pid,
            conversation_id=cid,
            char_cap=1200,
            message_limit=80,
            per_message_chars=120,
        )
        assert digest
        assert len(digest) <= 1200
        assert trace.original_char_count > trace.final_char_count
        assert trace.tiers_applied
    finally:
        session.close()


def test_compaction_trace_to_dict_ratio() -> None:
    trace = CompactionTrace(original_char_count=200, final_char_count=80)
    trace.add_tier("tier1_micro_compact")
    trace.drop_source("conversation_segments", "msg-1")
    payload = trace.to_dict()
    assert payload["compression_ratio"] == 0.4
    assert payload["tiers_applied"] == ["tier1_micro_compact"]


def test_build_conversation_digest_excludes_stale_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "conversation_digest_exclude_stale_sources", True)
    monkeypatch.setattr(settings, "conversation_source_freshness_ttl_seconds", 60)

    session = SessionLocal()
    try:
        uid, pid, cid = "u_digest4", "proj_digest4", "conv_digest4"
        session.add(User(id=uid, email="digest4@test.local", hashed_password="x"))
        session.add(Project(id=pid, name="P4", created_by=uid))
        session.add(Conversation(id=cid, project_id=pid, user_id=uid))
        stale_at = datetime.utcnow() - timedelta(hours=2)
        session.add(
            ConversationMessage(
                conversation_id=cid,
                role="user",
                content="old discovery",
                source_type="discovery_answer",
                source_freshness_at=stale_at,
            )
        )
        session.add(ConversationMessage(conversation_id=cid, role="assistant", content="fresh assistant turn"))
        session.commit()

        d = build_conversation_digest_for_run(
            session=session,
            project_id=pid,
            conversation_id=cid,
            char_cap=8000,
            message_limit=10,
        )
        assert "old discovery" not in d
        assert "fresh assistant turn" in d
    finally:
        session.close()


def test_build_conversation_digest_sectioned_assembly(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "conversation_digest_sectioned_assembly_enabled", True)
    monkeypatch.setattr(settings, "conversation_digest_tiered_compaction_enabled", False)

    session = SessionLocal()
    try:
        uid, pid, cid = "u_digest5", "proj_digest5", "conv_digest5"
        session.add(User(id=uid, email="digest5@test.local", hashed_password="x"))
        session.add(Project(id=pid, name="P5", created_by=uid))
        session.add(Conversation(id=cid, project_id=pid, user_id=uid))
        session.add(
            ConversationMessage(
                conversation_id=cid,
                role="user",
                content="We must avoid delays and reduce turnaround time.",
                metadata_json='{"kind":"discovery_answer","wiki_refs":["Ops baseline"]}',
            )
        )
        session.add(
            ConversationMessage(
                conversation_id=cid,
                role="assistant",
                content="Known issue: prior draft failed QA due to missing evidence.",
            )
        )
        session.commit()

        digest, trace = build_conversation_digest_for_run_with_trace(
            session=session,
            project_id=pid,
            conversation_id=cid,
            char_cap=3000,
            message_limit=20,
        )
        assert "## ObjectiveNow" in digest
        assert "## Evidence" in digest
        assert "## KnownFailures" in digest
        assert "sectioned_budget_assembly" in trace.tiers_applied
    finally:
        session.close()
