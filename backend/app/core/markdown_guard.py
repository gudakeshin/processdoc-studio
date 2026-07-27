"""Representation guard for markdown deliverable bodies.

LLM document agents occasionally emit a *program that would generate the
document* (e.g. JavaScript using the npm ``docx`` package, or python-docx
code) instead of the document text itself. Rendering that verbatim produces a
deliverable whose body is source code. These helpers detect that failure mode
deterministically so callers can regenerate or fall back.
"""

from __future__ import annotations

import re

_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*$")

_CODE_SIGNATURES: list[tuple[str, re.Pattern[str]]] = [
    ("npm docx require", re.compile(r"require\(\s*['\"]docx['\"]\s*\)")),
    ("npm docx import", re.compile(r"import\s+.*\bfrom\s+['\"]docx['\"]")),
    ("npm docx Document/Packer", re.compile(r"new\s+Document\s*\(")),
    ("npm docx Packer", re.compile(r"\bPacker\.(toBuffer|toBlob|toBase64String)\b")),
    ("python-docx import", re.compile(r"from\s+docx\s+import\s+Document")),
    ("python-docx save", re.compile(r"\bdocument\.save\(\s*['\"].*\.docx['\"]")),
]


def detect_code_document(md: str) -> list[str]:
    """Return reasons the text looks like generator code rather than a document.

    Empty list means the text is acceptable markdown.
    """
    text = (md or "").strip()
    if not text:
        return []
    issues: list[str] = []

    for label, pattern in _CODE_SIGNATURES:
        if pattern.search(text):
            issues.append(f"contains document-generator code ({label})")

    lines = text.splitlines()
    if lines and _FENCE_RE.match(lines[0].strip()):
        # Measure how much of the document sits inside the opening fence.
        close_idx = next(
            (i for i, ln in enumerate(lines[1:], start=1) if ln.strip() == "```"),
            len(lines),
        )
        fenced_chars = sum(len(ln) for ln in lines[:close_idx + 1])
        if fenced_chars > 0.6 * len(text):
            issues.append("document body is a single fenced code block")

    return issues


def strip_outer_fence(md: str) -> str:
    """Unwrap a document that is entirely one ```markdown ... ``` fence.

    Only unwraps fences whose language tag is markdown-ish (or absent); a
    fenced *code* document is left intact for :func:`detect_code_document`.
    """
    text = (md or "").strip()
    lines = text.splitlines()
    if len(lines) < 3:
        return md
    first = lines[0].strip()
    if not _FENCE_RE.match(first):
        return md
    lang = first.lstrip("`").strip().lower()
    if lang not in {"", "markdown", "md"}:
        return md
    if lines[-1].strip() != "```":
        return md
    inner = "\n".join(lines[1:-1])
    # A fence terminator inside means the outer fence doesn't wrap everything.
    if "\n```" in f"\n{inner}":
        return md
    return inner.strip()
