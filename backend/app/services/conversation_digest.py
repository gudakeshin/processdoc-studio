"""Compact HITL conversation digests for coordinator and subagent prompts."""

from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.sanitization import redact_emails
from app.db.models import Conversation, ConversationMessage
from app.core.config import settings
from app.services.compaction_trace import CompactionTrace
from app.services.context_compaction import CompactionLine, TieredCompactor
from app.services.source_freshness import mark_stale_sources

_FAILURE_HINT_RE = re.compile(r"\b(fail|error|issue|blocked|regression)\b", re.IGNORECASE)
_NON_NEGOTIABLE_RE = re.compile(r"\b(must|should not|cannot|required|non-negotiable)\b", re.IGNORECASE)


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
    freshness_map = mark_stale_sources(
        rows,
        ttl_seconds=int(settings.conversation_source_freshness_ttl_seconds or 259200),
    )

    lines: list[str] = []
    compaction_lines: list[CompactionLine] = []
    section_lines: list[tuple[ConversationMessage, str, dict]] = []
    used = 0
    for m in rows:
        role = (m.role or "unknown").strip()
        body = redact_emails((m.content or "").strip())
        info = freshness_map.get(int(m.id))
        if info and info.is_stale and settings.conversation_digest_exclude_stale_sources:
            continue
        if info and info.prefix:
            body = f"{info.prefix}{body}"

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
        section_lines.append((m, line, meta if isinstance(meta, dict) else {}))
        compaction_lines.append(CompactionLine(source_id=str(m.id), text=line))
        if len(body) > per_message_chars:
            body = body[:per_message_chars] + "…"
            line = f"[{role}]{extra_s}: {body}"
        if used + len(line) + 1 <= cap:
            lines.append(line)
            used += len(line) + 1

    if settings.conversation_digest_sectioned_assembly_enabled and section_lines:
        sectioned_digest, sectioned_trace = _assemble_sectioned_digest(section_lines, char_cap=cap)
        if sectioned_digest:
            return sectioned_digest, sectioned_trace

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


def _assemble_sectioned_digest(
    lines: list[tuple[ConversationMessage, str, dict]],
    *,
    char_cap: int,
) -> tuple[str, CompactionTrace]:
    cap = max(1200, int(char_cap))
    budgets = {
        "ObjectiveNow": max(120, int(cap * 0.16)),
        "NonNegotiables": max(140, int(cap * 0.22)),
        "WhatChanged": max(140, int(cap * 0.18)),
        "Evidence": max(260, int(cap * 0.34)),
        "KnownFailures": max(100, int(cap * 0.10)),
    }
    objective = _pick_objective(lines)
    non_negotiables = []
    what_changed = []
    evidence_wiki = []
    evidence_discovery = []
    evidence_other = []
    failures = []
    for _m, line, meta in lines:
        txt = str(line or "").strip()
        if not txt:
            continue
        if _NON_NEGOTIABLE_RE.search(txt):
            non_negotiables.append(txt)
        if _FAILURE_HINT_RE.search(txt):
            failures.append(txt)
        what_changed.append(txt)
        refs = meta.get("wiki_refs") if isinstance(meta, dict) else None
        kind = str(meta.get("kind") or "").strip().lower() if isinstance(meta, dict) else ""
        if isinstance(refs, list) and refs:
            evidence_wiki.append(txt)
        elif kind == "discovery_answer":
            evidence_discovery.append(txt)
        else:
            evidence_other.append(txt)
    evidence = [*evidence_wiki, *evidence_discovery, *evidence_other]
    sections = {
        "ObjectiveNow": _compact_block(objective, budgets["ObjectiveNow"]),
        "NonNegotiables": _compact_block(non_negotiables, budgets["NonNegotiables"]),
        "WhatChanged": _compact_block(what_changed[-24:], budgets["WhatChanged"]),
        "Evidence": _compact_block(evidence, budgets["Evidence"]),
        "KnownFailures": _compact_block(failures, budgets["KnownFailures"]),
    }
    text = (
        "## ObjectiveNow\n"
        f"{sections['ObjectiveNow']}\n\n"
        "## NonNegotiables\n"
        f"{sections['NonNegotiables']}\n\n"
        "## WhatChanged\n"
        f"{sections['WhatChanged']}\n\n"
        "## Evidence\n"
        f"{sections['Evidence']}\n\n"
        "## KnownFailures\n"
        f"{sections['KnownFailures']}"
    )
    digest = text[:cap]
    trace = CompactionTrace(
        tiers_applied=["sectioned_budget_assembly"],
        original_char_count=sum(len(t[1]) for t in lines) + max(0, len(lines) - 1),
        final_char_count=len(digest),
    )
    return digest, trace


def _compact_block(items: list[str], cap: int) -> str:
    if not items:
        return ""
    out: list[str] = []
    used = 0
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        add = len(text) + (1 if out else 0)
        if used + add > cap:
            break
        out.append(text)
        used += add
    return "\n".join(out)


def _pick_objective(lines: list[tuple[ConversationMessage, str, dict]]) -> list[str]:
    # Prefer latest user objective-like line; fallback to newest two lines.
    user_lines = [line for m, line, _meta in lines if str(getattr(m, "role", "")).strip() == "user"]
    if user_lines:
        return [user_lines[-1]]
    if not lines:
        return []
    return [line for _m, line, _meta in lines[-2:]]
