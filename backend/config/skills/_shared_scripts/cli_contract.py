from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CheckResult:
    check_name: str
    passed: bool
    issues: list[str]
    summary: str
    metadata: dict[str, Any] | None = None


def read_input(path_arg: str | None) -> str:
    if path_arg:
        return Path(path_arg).read_text(encoding="utf-8", errors="replace")
    import sys

    return sys.stdin.read()


def print_result(result: CheckResult, *, output_json: bool = False) -> None:
    import sys

    payload = {
        "check_name": result.check_name,
        "status": "pass" if result.passed else "fail",
        "summary": result.summary,
        "issues": result.issues,
        "metadata": result.metadata or {},
    }
    if output_json:
        print(json.dumps(payload, ensure_ascii=True))
        return
    if result.passed:
        print(result.summary)
        return
    print(result.summary, file=sys.stderr)
    for issue in result.issues:
        print(f"  - {issue}", file=sys.stderr)


def exit_code(result: CheckResult) -> int:
    return 0 if result.passed else 1
