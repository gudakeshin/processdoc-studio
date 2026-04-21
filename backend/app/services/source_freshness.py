"""Freshness utilities for conversation sources used in context assembly."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json

from app.db.models import ConversationMessage

_STALE_ELIGIBLE_TYPES = {"discovery_answer", "wiki_ref", "run_outcome"}
_KIND_TO_SOURCE_TYPE = {
    "discovery_answer": "discovery_answer",
    "conversational_response": "run_outcome",
    "assistant_plan": "run_outcome",
}


@dataclass(slots=True)
class FreshnessInfo:
    source_type: str
    is_stale: bool
    stale_age_hours: int
    freshness_at: datetime | None
    prefix: str


def _coerce_source_type(message: ConversationMessage) -> str:
    declared = str(getattr(message, "source_type", "") or "").strip().lower()
    if declared:
        return declared
    try:
        meta = json.loads(message.metadata_json or "{}")
    except Exception:
        meta = {}
    kind = str(meta.get("kind") or "").strip().lower() if isinstance(meta, dict) else ""
    return _KIND_TO_SOURCE_TYPE.get(kind, "chat_turn")


def _utc_now_naive() -> datetime:
    # DB rows are currently stored as naive UTC datetimes.
    return datetime.utcnow()


def freshness_for_message(
    message: ConversationMessage,
    *,
    ttl_seconds: int = 259200,
    now: datetime | None = None,
) -> FreshnessInfo:
    source_type = _coerce_source_type(message)
    if source_type not in _STALE_ELIGIBLE_TYPES:
        return FreshnessInfo(
            source_type=source_type,
            is_stale=False,
            stale_age_hours=0,
            freshness_at=getattr(message, "source_freshness_at", None),
            prefix="",
        )

    now_dt = now or _utc_now_naive()
    ttl = max(60, int(ttl_seconds))
    freshness_at = getattr(message, "source_freshness_at", None)
    if not isinstance(freshness_at, datetime):
        created = getattr(message, "created_at", None)
        base = created if isinstance(created, datetime) else now_dt
        freshness_at = base + timedelta(seconds=ttl)
    if now_dt <= freshness_at:
        return FreshnessInfo(
            source_type=source_type,
            is_stale=False,
            stale_age_hours=0,
            freshness_at=freshness_at,
            prefix="",
        )

    age_hours = max(1, int((now_dt - freshness_at).total_seconds() // 3600))
    return FreshnessInfo(
        source_type=source_type,
        is_stale=True,
        stale_age_hours=age_hours,
        freshness_at=freshness_at,
        prefix=f"[STALE: {age_hours}h old] ",
    )


def mark_stale_sources(
    messages: list[ConversationMessage],
    *,
    ttl_seconds: int = 259200,
    now: datetime | None = None,
) -> dict[int, FreshnessInfo]:
    out: dict[int, FreshnessInfo] = {}
    for m in messages:
        if getattr(m, "id", None) is None:
            continue
        out[int(m.id)] = freshness_for_message(m, ttl_seconds=ttl_seconds, now=now)
    return out
