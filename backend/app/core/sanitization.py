"""Bounded redaction helpers (avoid pathological regex on huge strings)."""

from __future__ import annotations

import json
import re
from typing import Any

# Tight domain label cap limits backtracking vs permissive patterns.
_EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,24}\b"
)


def redact_emails(text: str, *, max_scan_chars: int = 12_000) -> str:
    """Replace email-like substrings in a bounded prefix of text."""
    if not text:
        return text
    if len(text) <= max_scan_chars:
        return _EMAIL_PATTERN.sub("[redacted_email]", text)
    head = _EMAIL_PATTERN.sub("[redacted_email]", text[:max_scan_chars])
    return head + text[max_scan_chars:]


def sanitize_memory_payload_dict(payload_obj: Any) -> dict[str, Any]:
    """Match run_worker memory redaction: emails, long numbers, size cap, JSON round-trip."""
    text = payload_obj if isinstance(payload_obj, str) else json.dumps(payload_obj)
    text = redact_emails(text)
    text = re.sub(r"\b\d{10,16}\b", "[redacted_number]", text)
    if len(text) > 1200:
        text = text[:1200]
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {"summary": text}
    except Exception:
        return {"summary": text}
