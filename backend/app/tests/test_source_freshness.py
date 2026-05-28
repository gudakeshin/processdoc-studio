from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db.models import ConversationMessage
from app.services.source_freshness import freshness_for_message


def test_freshness_for_message_marks_discovery_stale() -> None:
    msg = ConversationMessage(
        conversation_id="c1",
        role="user",
        content="foo",
        metadata_json="{}",
        source_type="discovery_answer",
        source_freshness_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=5),
    )
    info = freshness_for_message(msg, ttl_seconds=60)
    assert info.is_stale is True
    assert info.prefix.startswith("[STALE:")


def test_freshness_for_message_non_eligible_type_is_not_stale() -> None:
    msg = ConversationMessage(
        conversation_id="c1",
        role="assistant",
        content="ok",
        metadata_json="{}",
        source_type="chat_turn",
    )
    info = freshness_for_message(msg, ttl_seconds=60)
    assert info.is_stale is False
    assert info.prefix == ""
