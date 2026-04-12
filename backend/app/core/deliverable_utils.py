from __future__ import annotations

import re
from typing import Any


def safe_text(value: object, default: str = "") -> str:
    return str(value or default).strip()


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
    lines = (md_text or "").splitlines()
    blocks: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading_match:
            blocks.append({"type": "heading", "level": len(heading_match.group(1)), "text": heading_match.group(2).strip()})
            i += 1
            continue
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
        if re.match(r"^[-*]\s+.+$", stripped):
            bullets: list[str] = []
            while i < len(lines):
                m = re.match(r"^[-*]\s+(.+)$", lines[i].strip())
                if not m:
                    break
                bullets.append(m.group(1).strip())
                i += 1
            blocks.append({"type": "bullets", "items": bullets})
            continue
        blocks.append({"type": "paragraph", "text": stripped})
        i += 1
    return blocks

