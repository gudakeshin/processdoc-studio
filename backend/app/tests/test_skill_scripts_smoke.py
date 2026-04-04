from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _run(cmd: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        input=input_text,
        text=True,
        capture_output=True,
        cwd=str(ROOT),
        check=False,
    )


def test_validate_skill_script_contract_static_check() -> None:
    res = _run([sys.executable, "backend/scripts/validate_skill_script_contract.py"])
    assert res.returncode == 0, res.stderr or res.stdout


def test_brd_section_checker_smoke() -> None:
    text = """
    # Executive Overview
    ## Scope
    ## Stakeholders
    ## Current State
    ## Assumptions
    ## Functional Requirements
    ## Non-Functional Requirements
    ## Data Requirements
    ## Reporting
    ## Governance and Sign-off
    """
    res = _run(
        [sys.executable, "backend/config/skills/brd_v1/scripts/check_brd_sections.py"],
        input_text=text,
    )
    assert res.returncode == 0, res.stderr


def test_proposal_signal_checker_smoke() -> None:
    text = """
    # Executive Summary
    Client situation and understanding.
    Approach and delivery plan.
    Value and business case with outcomes.
    Risk register and mitigations.
    """
    res = _run(
        [sys.executable, "backend/config/skills/proposal_finance_transformation_v1/scripts/check_proposal_signals.py"],
        input_text=text,
    )
    assert res.returncode == 0, res.stderr


def test_raci_validator_smoke() -> None:
    table = """| Activity | Responsible | Accountable | Consulted | Informed |
|---|---|---|---|---|
| Prepare close calendar | Finance Lead | CFO | Controller | PMO |
"""
    fixture = ROOT / "backend" / "app" / "tests" / "_tmp_raci.md"
    fixture.write_text(table, encoding="utf-8")
    try:
        res = _run(
            [
                sys.executable,
                "backend/config/skills/raci_v2/scripts/validate_raci_markdown.py",
                str(fixture),
            ]
        )
        assert res.returncode == 0, res.stderr
    finally:
        fixture.unlink(missing_ok=True)
