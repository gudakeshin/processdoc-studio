"""Heuristic extraction of a ProcessModel from free text (no external LLM)."""

from __future__ import annotations

import re
from typing import Iterable

from app.core.state import DecisionBranch, ProcessModel, ProcessStep

# Lines that declare a role / owner
_ROLE_LINE = re.compile(
    r"^\s*(?:role|owner|team|actor|stakeholder)\s*[:#\-–]\s*(.+?)\s*$",
    re.I,
)
# Numbered steps: "1. Foo" or "1) Foo"
_STEP_NUMBERED = re.compile(r"^\s*(\d+)[\.\)]\s+(.+?)\s*$")
# Bullets
_STEP_BULLET = re.compile(r"^\s*[-*•]\s+(.+?)\s*$")
# "Step 1: ..."
_STEP_LABEL = re.compile(r"^\s*step\s*\d+\s*[:.\-–]\s*(.+?)\s*$", re.I)
# Markdown heading as title
_MD_HEADING = re.compile(r"^\s*#+\s*(.+?)\s*$")
# Decision / branch hints
_DECISION = re.compile(r"\b(if|when|otherwise|else)\b", re.I)
_ACTION_HINT = re.compile(
    r"\b(review|approve|submit|collect|validate|check|create|update|notify|escalate|assign|prepare|draft|analyze|map|handoff|handover)\b",
    re.I,
)


def _uniq_roles(roles: Iterable[str], cap: int = 12) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for r in roles:
        r = r.strip()
        if len(r) < 2 or len(r) > 80:
            continue
        key = r.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
        if len(out) >= cap:
            break
    return out


def _infer_title(lines: list[str]) -> str:
    for line in lines[:8]:
        m = _MD_HEADING.match(line)
        if m:
            return m.group(1).strip()[:200]
    if lines and len(lines[0]) < 120 and not _STEP_NUMBERED.match(lines[0]):
        return lines[0].strip()[:200]
    return "Documented Process"


def _collect_roles(lines: list[str], steps: list[ProcessStep]) -> list[str]:
    found: list[str] = []
    for line in lines:
        m = _ROLE_LINE.match(line)
        if m:
            found.append(m.group(1).strip())
    # "by Sales" in step text
    by_pat = re.compile(r"\b(?:by|from)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b")
    for st in steps:
        for m in by_pat.finditer(st["name"] + " " + st.get("notes", "")):
            found.append(m.group(1).strip())
    roles = _uniq_roles(found)
    if not roles:
        roles = ["Process Owner", "Contributor"]
    return roles


def _parse_steps(lines: list[str]) -> list[tuple[str, str]]:
    """Return list of (raw_line, step_title)."""
    steps: list[tuple[str, str]] = []
    for line in lines:
        if not line.strip() or line.strip().startswith("#"):
            continue
        if _ROLE_LINE.match(line):
            continue
        m = _STEP_NUMBERED.match(line)
        if m:
            steps.append((line, m.group(2).strip()))
            continue
        m = _STEP_LABEL.match(line)
        if m:
            steps.append((line, m.group(1).strip()))
            continue
        m = _STEP_BULLET.match(line)
        if m:
            steps.append((line, m.group(1).strip()))
            continue
    return steps


def _assign_roles(steps: list[ProcessStep], roles: list[str]) -> None:
    if not roles:
        return
    for i, st in enumerate(steps):
        st["role"] = roles[i % len(roles)]


def _build_decisions(lines: list[str], step_ids: list[str]) -> list[DecisionBranch]:
    decisions: list[DecisionBranch] = []
    d = 0
    for line in lines:
        if not _DECISION.search(line):
            continue
        if len(line) > 240:
            continue
        d += 1
        sid = step_ids[0] if step_ids else "s1"
        decisions.append(
            {
                "id": f"d{d}",
                "condition": line.strip()[:200],
                "true_path": [sid],
                "false_path": [],
            }
        )
        if len(decisions) >= 5:
            break
    return decisions


def _swimlanes_from_steps(steps: list[ProcessStep]) -> dict[str, list[str]]:
    lanes: dict[str, list[str]] = {}
    for st in steps:
        role = st.get("role") or "General"
        lanes.setdefault(role, []).append(st["id"])
    return lanes


def extract_process_model(raw_text: str, assembled_context: str = "") -> ProcessModel:
    """Build a structured process from instruction text plus optional assembled context."""
    text = (raw_text or "").strip()
    ctx = (assembled_context or "").strip()
    blob = f"{text}\n{ctx}".strip()
    lines = [ln.rstrip() for ln in blob.splitlines()]

    parsed = _parse_steps(lines)
    process_name = _infer_title(lines)
    source_trace: list[str] = []

    steps: list[ProcessStep] = []
    if parsed:
        for i, (raw_line, title) in enumerate(parsed[:40], start=1):
            sid = f"s{i}"
            source_trace.append(raw_line.strip()[:300])
            steps.append(
                {
                    "id": sid,
                    "name": title[:500],
                    "role": "Contributor",
                    "inputs": [],
                    "outputs": [],
                    "tools": [],
                    "duration_estimate": "",
                    "notes": "",
                }
            )
    else:
        # Fallback: prioritize process-like lines from context/instruction.
        fallback: list[str] = []
        for line in lines:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if _ROLE_LINE.match(s):
                continue
            if len(s) < 8:
                continue
            if s.lower().startswith(("objective", "nonnegotiables", "knownfailures", "evidence", "whatchanged")):
                continue
            if s.startswith("[LP]"):
                continue
            if len(s) > 500:
                s = s[:500] + "…"
            score = 0
            if _ACTION_HINT.search(s):
                score += 3
            if "->" in s or "=>" in s or " then " in s.lower():
                score += 2
            if "|" in s:
                score += 1
            if re.search(r"\b(step|stage|phase|activity|owner|input|output)\b", s, re.I):
                score += 1
            if score > 0:
                fallback.append((score, s))
        fallback.sort(key=lambda x: x[0], reverse=True)
        ranked_lines = [line for _, line in fallback]
        if not ranked_lines and text:
            ranked_lines = [text[:800] + ("…" if len(text) > 800 else "")]
        for i, title in enumerate(ranked_lines[:15], start=1):
            source_trace.append(title.strip()[:300])
            steps.append(
                {
                    "id": f"s{i}",
                    "name": title,
                    "role": "Contributor",
                    "inputs": [],
                    "outputs": [],
                    "tools": [],
                    "duration_estimate": "",
                    "notes": "",
                }
            )

    roles = _collect_roles(lines, steps)
    _assign_roles(steps, roles)
    step_ids = [s["id"] for s in steps]
    decisions = _build_decisions(lines, step_ids)
    swimlanes = _swimlanes_from_steps(steps)

    return {
        "process_name": process_name,
        "roles": roles,
        "steps": steps,
        "decisions": decisions,
        "swimlanes": swimlanes,
        "metadata": {
            "source": "heuristic_extraction",
            "step_count": str(len(steps)),
            "source_trace": source_trace[:25],
        },
    }
