#!/usr/bin/env python3
"""Check approach note text for the seven section headings or keywords.

Usage: python check_approach_sections.py [file]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Keywords for each of the seven ProcessDoc sections
SECTION_SIGNALS = [
    r"problem fram|problem statement",
    r"standard approach|why.*fail|failure",
    r"hypothesis",
    r"proposed approach|our approach",
    r"what we (will )?learn|when we",
    r"risk|limitation|uncertainty",
    r"conclusion|decision request",
]


def main() -> int:
    raw = sys.stdin.read() if len(sys.argv) < 2 else Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
    t = raw.lower()
    missing: list[str] = []
    for pat in SECTION_SIGNALS:
        if not re.search(pat, t):
            missing.append(pat)
    if missing:
        print("Missing approach-note signals:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        return 1
    print("Approach note section signals: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
