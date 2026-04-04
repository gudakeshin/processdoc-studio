#!/usr/bin/env python3
"""Check finance proposal markdown/text for common section signals.

Usage: python check_proposal_signals.py [file]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

EXPECTED = [
    r"executive summary",
    r"client|situat|understanding",
    r"approach|method",
    r"value|benefit|outcome|roi|business case",
    r"risk",
    r"(delivery|implementation|plan)",
]


def main() -> int:
    raw = sys.stdin.read() if len(sys.argv) < 2 else Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
    t = raw.lower()
    missing = [p for p in EXPECTED if not re.search(p, t)]
    if missing:
        print("Missing proposal signals:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        return 1
    print("Proposal section signals: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
