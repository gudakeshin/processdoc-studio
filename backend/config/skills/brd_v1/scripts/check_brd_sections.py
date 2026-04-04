#!/usr/bin/env python3
"""Lightweight BRD section heading check for markdown or plain text.

Usage:
  python check_brd_sections.py [path]
  cat doc.md | python check_brd_sections.py

Exits 0 if all expected section keywords are found (case-insensitive), else 1.
"""
from __future__ import annotations

import re
import sys

# Minimum keywords matching the ProcessDoc BRD template
EXPECTED = [
    r"executive",
    r"\bscope\b",
    r"stakeholder",
    r"current state",
    r"assumption",
    r"functional requirement",
    r"non-functional",
    r"\bdata requirement",
    r"reporting",
    r"governance|traceability|sign[- ]off",
]


def main() -> int:
    raw = sys.stdin.read() if len(sys.argv) < 2 else __import__("pathlib").Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
    lower = raw.lower()
    missing: list[str] = []
    for pat in EXPECTED:
        if not re.search(pat, lower, re.IGNORECASE):
            missing.append(pat)
    if missing:
        print("Missing section signals (regex):", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        return 1
    print("BRD section signals: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
