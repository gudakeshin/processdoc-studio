"""Compact HITL conversation digests for coordinator and subagent prompts."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.sanitization import redact_emails
from app.db.models import Conversation, ConversationMessage
from app.core.config import settings
from app.services.compaction_trace import CompactionTrace
from app.services.context_compaction import CompactionLine, TieredCompactor


def build_conversation_digest_for_run(
    *,
    session: Session,
    project_id: str,
    conversation_id: str | None,
    char_cap: int,
    message_limit: int = 40,
    per_message_chars: int = 600,
) -> str:
    digest, _trace = build_conversation_digest_for_run_with_trace(
        session=session,
        project_id=project_id,
        conversation_id=conversation_id,
        char_cap=char_cap,
        message_limit=message_limit,
        per_message_chars=per_message_chars,
    )
    return digest


def build_conversation_digest_for_run_with_trace(
    *,
    session: Session,
    project_id: str,
    conversation_id: str | None,
    char_cap: int,
    message_limit: int = 40,
    per_message_chars: int = 600,
) -> tuple[str, CompactionTrace]:
    """
    Build a deterministic oldest→newest digest of recent conversation messages.
    Verifies the conversation belongs to project_id.
    """
    if not conversation_id or not str(conversation_id).strip():
        return "", CompactionTrace()
    cid = str(conversation_id).strip()
    conv = session.scalar(
        select(Conversation).where(Conversation.id == cid, Conversation.project_id == project_id)
    )
    if not conv:
        return "", CompactionTrace()

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
    compaction_lines: list[CompactionLine] = []
    used = 0
    for m in rows:
        role = (m.role or "unknown").strip()
        body = redact_emails((m.content or "").strip())

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
        compaction_lines.append(CompactionLine(source_id=str(m.id), text=line))
        if len(body) > per_message_chars:
            body = body[:per_message_chars] + "…"
            line = f"[{role}]{extra_s}: {body}"
        if used + len(line) + 1 <= cap:
            lines.append(line)
            used += len(line) + 1

    original_char_count = sum(len(x.text) for x in compaction_lines) + max(0, len(compaction_lines) - 1)
    threshold = max(1, int(settings.conversation_digest_tiered_compaction_threshold_chars))
    if (not settings.conversation_digest_tiered_compaction_enabled) or original_char_count < threshold:
        trace = CompactionTrace(
            tiers_applied=[],
            original_char_count=original_char_count,
            final_char_count=len("\n".join(lines)),
        )
        return "\n".join(lines), trace

    compactor = TieredCompactor(per_message_chars=per_message_chars)
    digest, trace = compactor.assemble(lines=compaction_lines, char_cap=cap)
    return digest, trace
