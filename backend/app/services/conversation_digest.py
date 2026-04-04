"""Compact HITL conversation digests for coordinator and subagent prompts."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.sanitization import redact_emails
from app.db.models import Conversation, ConversationMessage


def build_conversation_digest_for_run(
    *,
    session: Session,
    project_id: str,
    conversation_id: str | None,
    char_cap: int,
    message_limit: int = 40,
    per_message_chars: int = 600,
) -> str:
    """
    Build a deterministic oldest→newest digest of recent conversation messages.
    Verifies the conversation belongs to project_id.
    """
    if not conversation_id or not str(conversation_id).strip():
        return ""
    cid = str(conversation_id).strip()
    conv = session.scalar(
        select(Conversation).where(Conversation.id == cid, Conversation.project_id == project_id)
    )
    if not conv:
        return ""

    cap = max(200, int(char_cap))
    limit = max(1, min(80, int(message_limit)))
    rows = list(
        session.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == cid)
            .order_by(ConversationMessage.created_at.desc())
            .limit(limit)
        ).all()
    )
    rows.reverse()

    lines: list[str] = []
    used = 0
    for m in rows:
        role = (m.role or "unknown").strip()
        body = redact_emails((m.content or "").strip())
        if len(body) > per_message_chars:
            body = body[:per_message_chars] + "…"

        extras: list[str] = []
        try:
            meta = json.loads(m.metadata_json or "{}")
        except Exception:
            meta = {}
        if isinstance(meta, dict):
            ph = meta.get("plan_hash")
            if ph:
                extras.append(f"plan_hash={ph}")
            if meta.get("ready_for_confirmation") is not None:
                extras.append(f"ready_for_confirmation={meta.get('ready_for_confirmation')}")
            if meta.get("ready_to_run") is not None:
                extras.append(f"ready_to_run={meta.get('ready_to_run')}")
            dps = meta.get("decision_prompts")
            if isinstance(dps, list) and dps:
                extras.append(f"decision_prompts={len(dps)}")

        extra_s = f" ({', '.join(extras)})" if extras else ""
        line = f"[{role}]{extra_s}: {body}"
        if used + len(line) + 1 > cap:
            break
        lines.append(line)
        used += len(line) + 1

    return "\n".join(lines)
