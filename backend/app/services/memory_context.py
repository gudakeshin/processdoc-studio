"""Merge MemoryItem rows into coordinator profile payloads for assemble_v2."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import MemoryItem
from app.services.memory_consent import memory_item_allowed_for_use


def merge_long_term_items_into_profile(
    profile_payload: dict[str, Any],
    long_term_rows: list[Any],
    *,
    respect_consent: bool,
    session: Session | None = None,
    project_id: str | None = None,
    enforce_consent_ledger: bool = False,
) -> tuple[int, int, int]:
    """
    Prefer fresh ``MemoryItem`` query results over any stale ``long_term_items`` already
    present in ``profile_payload`` (e.g. from older profile JSON).

    Returns ``(injected_count, consent_skipped_count, ledger_skipped_count)``. When nothing
    is injected, ``long_term_items`` is removed from ``profile_payload`` so stale values
    are not used.
    """
    preferences: list[str] = []
    consent_skipped = 0
    ledger_skipped = 0
    ledger_on = bool(
        enforce_consent_ledger and session is not None and (project_id or "").strip()
    )
    for it in long_term_rows:
        if isinstance(it, MemoryItem):
            ok, reason = memory_item_allowed_for_use(
                session,
                (project_id or "").strip(),
                it,
                respect_consent=respect_consent,
                enforce_consent_ledger=ledger_on,
            )
            if not ok:
                if reason == "consent_field":
                    consent_skipped += 1
                elif reason == "consent_ledger":
                    ledger_skipped += 1
                continue
        else:
            if respect_consent:
                cs = (getattr(it, "consent_state", None) or "").strip().lower()
                if cs not in ("allowed", ""):
                    consent_skipped += 1
                    continue
        mt = (getattr(it, "memory_type", None) or "").strip()
        key = (getattr(it, "key", None) or "").strip()
        val = getattr(it, "value", None)
        val_s = (str(val).strip()) if val is not None else ""
        if mt and key:
            preferences.append(f"{mt}:{key}={val_s}")
    if preferences:
        profile_payload["long_term_items"] = preferences
        return len(preferences), consent_skipped, ledger_skipped
    profile_payload.pop("long_term_items", None)
    return 0, consent_skipped, ledger_skipped
