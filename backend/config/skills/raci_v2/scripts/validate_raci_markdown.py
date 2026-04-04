#!/usr/bin/env python3
"""Validate a simple Markdown pipe-table RACI.

Rules:
- Parses the first pipe-delimited table in the file.
- Expects columns that include markers for R, A, C, I (header names).
- One 'A' per data row in the A column; at least one 'R' in the R column.

Usage: python validate_raci_markdown.py path/to/table.md
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def parse_table(text: str) -> tuple[list[str], list[list[str]]] | None:
    lines = [ln.strip() for ln in text.splitlines() if "|" in ln]
    if len(lines) < 2:
        return None
    rows: list[list[str]] = []
    for ln in lines:
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if set(cells) <= {"", "-", "---"} or all(re.match(r"^:?-+:?$", c) for c in cells):
            continue
        rows.append(cells)
    if not rows:
        return None
    header = rows[0]
    body = rows[1:]
    return header, body


def col_index(header: list[str], *substrings: str) -> int | None:
    for i, h in enumerate(header):
        n = h.lower()
        if any(s in n for s in substrings):
            return i
    return None


def _looks_like_letter_markers(*cells: str) -> bool:
    joined = " ".join(cells).upper()
    return bool(re.search(r"(^|\s)(R|A|C|I)(,|\s|$)", joined)) and len(joined) < 80


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: validate_raci_markdown.py <markdown file>", file=sys.stderr)
        return 2
    p = Path(sys.argv[1])
    text = p.read_text(encoding="utf-8", errors="replace")
    parsed = parse_table(text)
    if not parsed:
        print("No markdown pipe table found.", file=sys.stderr)
        return 1
    header, body = parsed
    i_a = col_index(header, "accountable")
    i_r = col_index(header, "responsible")
    if i_a is None:
        for i, h in enumerate(header):
            if h.strip().upper() == "A":
                i_a = i
                break
    if i_r is None:
        for i, h in enumerate(header):
            if h.strip().upper() == "R":
                i_r = i
                break
    if i_a is None or i_r is None:
        print("Could not find Accountable (A) and Responsible (R) columns in header:", header, file=sys.stderr)
        return 1
    errs = 0
    for n, row in enumerate(body, 1):
        if max(i_a, i_r) >= len(row):
            print(f"Row {n}: too few cells", file=sys.stderr)
            errs += 1
            continue
        a_cell, r_cell = row[i_a], row[i_r]
        if not a_cell.strip() or re.match(r"^(tbd|n/?a)\.?$", a_cell.strip(), re.I):
            print(f"Row {n}: Accountable cell empty or TBD ({a_cell!r})", file=sys.stderr)
            errs += 1
        if not r_cell.strip() or re.match(r"^(tbd|n/?a)\.?$", r_cell.strip(), re.I):
            print(f"Row {n}: Responsible cell empty or TBD ({r_cell!r})", file=sys.stderr)
            errs += 1
        if _looks_like_letter_markers(a_cell, r_cell):
            a_count = len(re.findall(r"\bA\b", a_cell.upper()))
            r_count = len(re.findall(r"\bR\b", r_cell.upper()))
            if a_count != 1:
                print(f"Row {n}: marker mode — expected exactly one A in Accountable column ({a_cell!r})", file=sys.stderr)
                errs += 1
            if r_count < 1:
                print(f"Row {n}: marker mode — expected R in Responsible column ({r_cell!r})", file=sys.stderr)
                errs += 1
    if errs:
        print(f"RACI validation failed with {errs} issue(s).", file=sys.stderr)
        return 1
    print("RACI table: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
