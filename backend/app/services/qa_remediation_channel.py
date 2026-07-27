"""Isolated QA remediation channel — keep feedback out of user intent fields."""

from __future__ import annotations

import re

QA_FEEDBACK_START = "[[QA_FEEDBACK_START]]"
QA_FEEDBACK_END = "[[QA_FEEDBACK_END]]"

_BLOCK_RE = re.compile(
    re.escape(QA_FEEDBACK_START) + r"[\s\S]*?" + re.escape(QA_FEEDBACK_END),
    re.MULTILINE,
)


def wrap_qa_feedback(text: str) -> str:
    body = (text or "").strip()
    if not body:
        return ""
    return f"{QA_FEEDBACK_START}\n{body}\n{QA_FEEDBACK_END}"


def strip_qa_feedback(text: str) -> str:
    """Remove sentinel-wrapped QA blocks and legacy 'QA remediation:' tail pollution."""
    cleaned = _BLOCK_RE.sub("", text or "")
    # Legacy runs appended remediation without sentinels.
    legacy_idx = cleaned.find("\n\nQA remediation:")
    if legacy_idx >= 0:
        cleaned = cleaned[:legacy_idx]
    legacy_guard = cleaned.find("\n\nGuardrail remediation required")
    if legacy_guard >= 0:
        cleaned = cleaned[:legacy_guard]
    return cleaned.strip()
