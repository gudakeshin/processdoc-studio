"""Consent checks for MemoryItem: field-level consent_state and optional DPDP Consent Ledger."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ConsentLedger, MemoryItem


def consent_ledger_latest_granted(session: Session, project_id: str, principal_id: str) -> bool:
    """
    True if the latest ledger row for (project_id, principal_id) exists and is granted.

    When no row exists, returns False (no recorded consent).
    """
    pid = (principal_id or "").strip()
    if not pid:
        return True
    row = session.scalar(
        select(ConsentLedger)
        .where(ConsentLedger.project_id == project_id, ConsentLedger.principal_id == pid)
        .order_by(ConsentLedger.created_at.desc())
        .limit(1)
    )
    if row is None:
        return False
    return bool(row.granted)


def memory_item_allowed_for_use(
    session: Session | None,
    project_id: str,
    item: MemoryItem,
    *,
    respect_consent: bool,
    enforce_consent_ledger: bool,
) -> tuple[bool, str]:
    """
    Returns (allowed, skip_reason) where skip_reason is empty if allowed.

    skip_reason values: consent_field, consent_ledger
    """
    if respect_consent:
        cs = (item.consent_state or "").strip().lower()
        if cs not in ("allowed", ""):
            return False, "consent_field"
    if enforce_consent_ledger and session is not None:
        principal = (getattr(item, "principal_id", None) or "").strip()
        if principal and not consent_ledger_latest_granted(session, project_id, principal):
            return False, "consent_ledger"
    return True, ""
