"""Persist Visual QA outcomes into the project conversation as assistant messages."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Conversation, ConversationMessage, Project


def should_persist_visual_qa_chat(report: dict[str, Any]) -> bool:
    """Always mirror Visual QA into the instruction thread so the user can read it and reply."""
    if not isinstance(report, dict) or not report:
        return False
    return True


def build_visual_qa_chat_message_body(report: dict[str, Any], *, run_id: str) -> str:
    st = str(report.get("status") or "").lower() or "unknown"
    summary = str(report.get("summary") or "").strip()
    raw_findings = report.get("findings") or []
    findings: list[str] = []
    if isinstance(raw_findings, list):
        for x in raw_findings[:20]:
            t = str(x).strip()
            if t:
                findings.append(t)

    # Add personality based on status
    status_emoji_map = {
        "pass": "✨",
        "skip": "⏭️",
        "warn": "⚠️",
        "fail": "🔧",
    }
    status_emoji = status_emoji_map.get(st, "📋")

    # Status-specific tone
    status_tone_map = {
        "pass": "Great work! No layout or image issues flagged.",
        "skip": "Visual QA skipped for this run.",
        "warn": "A few visual polish opportunities found—see below.",
        "fail": "Found some visual issues to fix—let's address them:",
    }
    status_tone = status_tone_map.get(st, "Visual QA report ready.")

    lines = [
        f"{status_emoji} **Visual Quality Check: {st.upper()}**",
        "",
    ]

    if summary:
        lines.append(summary)
        lines.append("")

    if findings:
        lines.append(status_tone)
        lines.append("")
        for f in findings:
            lines.append(f"→ {f}")
    elif st in {"fail", "warn"}:
        lines.append("_No structured findings were returned; see the full report artifact if needed._")
        lines.append("")
    elif st in {"pass", "skip"}:
        lines.append(status_tone)
        lines.append("")

    if st in {"fail", "warn"} and findings:
        lines.append("")
        lines.append("🚀 Next up: Quick refinements and we're golden!")

    # Include run_id for tracking
    lines.append("")
    lines.append(f"_Run: {run_id}_")

    return "\n".join(lines).strip()


def persist_visual_qa_assistant_message(
    db: Session,
    *,
    project_id: str,
    user_id: str | None,
    run_id: str,
    report: dict[str, Any],
) -> bool:
    """
    Append one assistant message to the project's conversation for the given user.

    Returns True if a message was queued on the session (caller must commit).
    """
    if not should_persist_visual_qa_chat(report):
        return False

    uid = (user_id or "").strip() or None
    if not uid:
        proj = db.scalar(select(Project).where(Project.id == project_id))
        if not proj:
            return False
        uid = str(proj.created_by)

    conv = db.scalar(
        select(Conversation)
        .where(Conversation.project_id == project_id, Conversation.user_id == uid)
        .order_by(Conversation.updated_at.desc())
        .limit(1)
    )
    if not conv:
        conv = Conversation(
            id=f"conv_{uuid.uuid4().hex[:10]}",
            project_id=project_id,
            user_id=uid,
            title="Creative Studio",
        )
        db.add(conv)
        db.flush()

    body = build_visual_qa_chat_message_body(report, run_id=run_id)
    meta: dict[str, Any] = {
        "kind": "visual_qa_report",
        "run_id": run_id,
        "status": str(report.get("status") or ""),
    }
    msg = ConversationMessage(
        conversation_id=conv.id,
        role="assistant",
        content=body,
        metadata_json=json.dumps(meta),
    )
    db.add(msg)
    conv.updated_at = datetime.utcnow()
    return True
