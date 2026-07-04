from __future__ import annotations

import logging
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.tz import IST

logger = logging.getLogger(__name__)


def safe_text(value: object, default: str = "") -> str:
    return str(value or default).strip()


# Wiki/internal markup that must never reach a client-facing deliverable.
_WIKI_LINK_RE = re.compile(r"\[\[([^\[\]]*?)\]\]")
_BARE_SCHEME_RE = re.compile(r"\b(?:lp|wiki)://\S+")
_INTERNAL_FILE_RE = re.compile(r"\b(?:index|log)\.md\b")


def _humanize_link_token(inner: str) -> str:
    """Reduce a ``[[id|Label]]`` / ``[[scheme://path|Label]]`` token to its human label."""
    inner = inner.strip()
    if "|" in inner:
        inner = inner.rsplit("|", 1)[-1].strip()
    inner = re.sub(r"^(?:lp|wiki)://", "", inner)
    if " " not in inner and "/" in inner:  # bare id path with no label — keep last segment
        inner = inner.rsplit("/", 1)[-1]
    return inner.strip()


def humanize_wiki_links(value: object) -> str:
    """Strip internal wiki-link grammar and pipeline filenames from client-facing text.

    ``[[page_id|Human Title]]`` → ``Human Title``; ``[[lp://id|Title]]`` → ``Title``;
    bare ``wiki://``/``lp://`` schemes collapse to their last segment; internal
    ``index.md``/``log.md`` markers are removed. Plain text is returned unchanged.
    """
    s = str(value or "")
    if not s:
        return s
    s = _WIKI_LINK_RE.sub(lambda m: _humanize_link_token(m.group(1)), s)
    s = _BARE_SCHEME_RE.sub(lambda m: m.group(0).rsplit("/", 1)[-1], s)
    s = _INTERNAL_FILE_RE.sub("", s)
    return re.sub(r"[ \t]{2,}", " ", s).strip()


def humanize_deep(obj: Any) -> Any:
    """Recursively apply :func:`humanize_wiki_links` to every string in a payload."""
    if isinstance(obj, str):
        return humanize_wiki_links(obj)
    if isinstance(obj, list):
        return [humanize_deep(v) for v in obj]
    if isinstance(obj, dict):
        return {k: humanize_deep(v) for k, v in obj.items()}
    return obj


def apply_pptx_core_properties(
    prs: Any,
    *,
    title: str,
    subject: str,
    author: str,
    keywords: str = "processdoc,pptx",
    last_modified_by: str = "ProcessDoc Studio",
) -> None:
    """Populate OOXML core document properties on a presentation.

    Shared by both PPTX render paths so client-facing decks never ship the
    python-pptx template defaults (empty title/creator, "Steve Canny",
    a 2013 timestamp). Best-effort: failures log and leave the deck intact.
    """
    try:
        cp = prs.core_properties
        cp.title = str(title or "Presentation").strip()[:255]
        cp.subject = str(subject or "Process documentation").strip()[:255]
        cp.author = str(author or "ProcessDoc Studio").strip()[:255]
        cp.keywords = str(keywords or "").strip()[:255]
        cp.last_modified_by = last_modified_by
        now = datetime.now(IST)
        if getattr(cp, "created", None) is None:
            cp.created = now
        cp.modified = now
    except Exception as exc:  # noqa: BLE001 - core properties are best-effort
        logger.debug("Core properties skipped: %s", exc)


def fetch_logo_source(logo_url: str) -> str | None:
    """Resolve a branding logo reference to a local file path, or None.

    Remote URLs go through the SSRF-safe ``safe_get`` (HTTPS-only, private-IP
    blocking, size cap); the logo is best-effort, so failures log and return None.
    """
    logo_url = str(logo_url or "").strip()
    if not logo_url:
        return None
    if logo_url.startswith(("http://", "https://")):
        try:
            from app.services.http_fetch import safe_get

            suffix = Path(logo_url.split("?")[0]).suffix or ".png"
            data = safe_get(logo_url, timeout=8.0)
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(data)
                return tmp.name
        except Exception as exc:  # noqa: BLE001 - logo is best-effort; slide renders without it
            logger.warning("Failed to download branding logo_url %s: %s", logo_url, exc)
        return None
    p = Path(logo_url)
    if p.exists() and p.is_file():
        return str(p)
    return None


def rows_from_markdown(md: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in (md or "").splitlines():
        text = line.strip()
        if not text.startswith("|") or "|" not in text[1:]:
            continue
        cols = [c.strip() for c in text.strip("|").split("|")]
        if not cols:
            continue
        if all(re.fullmatch(r"-{2,}:?", c.replace(" ", "")) for c in cols):
            continue
        rows.append(cols)
    return rows


def rows_from_process_model(pm: dict[str, Any]) -> list[list[str]]:
    steps = pm.get("steps") if isinstance(pm, dict) else []
    if not isinstance(steps, list):
        return []
    rows: list[list[str]] = [["Activity", "Responsible", "Accountable", "Consulted", "Informed"]]
    roles = [str(r).strip() for r in (pm.get("roles") or []) if str(r).strip()] if isinstance(pm, dict) else []
    accountable = roles[0] if roles else "Process Owner"
    for st in steps[:120]:
        if not isinstance(st, dict):
            continue
        activity = str(st.get("name") or "—").strip()
        responsible = str(st.get("role") or "—").strip()
        consulted = ", ".join([r for r in roles if r not in {responsible, accountable}][:4]) if roles else "—"
        rows.append([activity, responsible, accountable, consulted or "—", "—"])
    return rows


def parse_markdown_blocks(md_text: str) -> list[dict[str, Any]]:
    """Parse markdown into typed blocks: heading, paragraph, bullets, numbered, code, table."""
    lines = (md_text or "").splitlines()
    blocks: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue

        # Fenced code block (``` or ~~~)
        fence_match = re.match(r"^(```|~~~)", stripped)
        if fence_match:
            fence = fence_match.group(1)
            code_lines: list[str] = []
            i += 1
            while i < len(lines):
                if lines[i].strip().startswith(fence):
                    i += 1
                    break
                code_lines.append(lines[i])
                i += 1
            blocks.append({"type": "code", "text": "\n".join(code_lines)})
            continue

        # ATX heading
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading_match:
            blocks.append({"type": "heading", "level": len(heading_match.group(1)), "text": heading_match.group(2).strip()})
            i += 1
            continue

        # Markdown table
        if stripped.startswith("|") and "|" in stripped[1:]:
            table_lines: list[str] = []
            while i < len(lines):
                cur = lines[i].strip()
                if not cur.startswith("|") or "|" not in cur[1:]:
                    break
                table_lines.append(cur)
                i += 1
            rows = rows_from_markdown("\n".join(table_lines))
            if rows:
                blocks.append({"type": "table", "rows": rows})
            continue

        # Numbered list
        if re.match(r"^\d+[.)]\s+.+$", stripped):
            items: list[str] = []
            while i < len(lines):
                m = re.match(r"^\d+[.)]\s+(.+)$", lines[i].strip())
                if not m:
                    break
                items.append(m.group(1).strip())
                i += 1
            blocks.append({"type": "numbered", "items": items})
            continue

        # Unordered bullet list
        if re.match(r"^[-*+]\s+.+$", stripped):
            bullets: list[str] = []
            while i < len(lines):
                m = re.match(r"^[-*+]\s+(.+)$", lines[i].strip())
                if not m:
                    break
                bullets.append(m.group(1).strip())
                i += 1
            blocks.append({"type": "bullets", "items": bullets})
            continue

        blocks.append({"type": "paragraph", "text": stripped})
        i += 1
    return blocks

