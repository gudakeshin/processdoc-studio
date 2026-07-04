"""Extraction of a ProcessModel from free text.

Prefers an LLM structuring pass (which separates verb-led process *steps* from
*entities* such as orgs/systems/GL codes and drops tool-internal mechanics), and
falls open to the deterministic regex heuristic when the LLM is unavailable.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable

from app.core.deliverable_utils import humanize_wiki_links
from app.core.state import DecisionBranch, ProcessModel, ProcessStep

logger = logging.getLogger(__name__)

# Tokens that signal the model has documented the *tool's own* ingestion/RAG
# mechanics instead of the client's business process (self-referential output).
_TOOL_MECHANIC_RE = re.compile(
    r"\b(?:index\.md|log\.md|knowledge graph|relationship graph|entity extraction|"
    r"llm (?:writes|extracts|synthesi[sz]es)|wiki-link|page_id|ingest cycle)\b",
    re.I,
)

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


def _looks_self_referential(steps: list[ProcessStep]) -> bool:
    """True when extracted steps are dominated by the tool's own RAG/wiki mechanics."""
    if not steps:
        return False
    hits = sum(1 for st in steps if _TOOL_MECHANIC_RE.search(st.get("name", "")))
    return hits >= max(2, len(steps) // 3)


def _llm_structure(text: str, ctx: str) -> ProcessModel | None:
    """LLM structuring pass: separate verb-led steps from entities; fail-open to None."""
    try:
        from app.core.config import settings
        from app.services.claude import claude_generate_json, is_claude_enabled
    except Exception as exc:
        logger.warning("%s: suppressed error: %s", '_llm_structure', exc)
        return None
    if not is_claude_enabled() or not getattr(settings, "process_extraction_llm_enabled", True):
        return None
    system = (
        "You extract a structured BUSINESS process from messy notes/context for a consulting "
        "deliverable. Distinguish three things and DO NOT confuse them:\n"
        "- steps: verb-led ACTIVITIES the process performs, in order (e.g. 'Validate source "
        "document', 'Approve credit limit').\n"
        "- entities: organisations, systems, products, GL codes, sectors — these are NOUNS, "
        "NEVER steps. List them separately.\n"
        "- roles: the actors/owners.\n"
        "Rules: never emit a step that is just an entity/noun. Exclude tool-internal mechanics "
        "(LLM prompts, knowledge-graph rebuilds, index.md/log.md, wiki-link syntax) — those "
        "describe software plumbing, not the client's process. Never invent content not present "
        "in the input. Return ONLY JSON: {\"process_name\": str, \"roles\": [str], "
        "\"entities\": [str], \"steps\": [{\"name\": str, \"role\": str}], "
        "\"decisions\": [{\"condition\": str}]}"
    )
    user = f"Instruction:\n{text[:3000]}\n\nAssembled context:\n{ctx[:4000]}"
    try:
        payload = claude_generate_json(system=system, user=user, temperature=0.2, max_tokens=2000)
    except Exception as exc:  # noqa: BLE001 — fail-open onto the heuristic
        logger.warning("LLM process structuring failed: %s", exc)
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("steps"), list):
        return None

    steps: list[ProcessStep] = []
    for i, s in enumerate(payload["steps"][:40], start=1):
        if not isinstance(s, dict):
            continue
        name = humanize_wiki_links(s.get("name") or "")
        if not name:
            continue
        steps.append({
            "id": f"s{i}", "name": name[:500],
            "role": humanize_wiki_links(s.get("role") or "Contributor") or "Contributor",
            "inputs": [], "outputs": [], "tools": [], "duration_estimate": "", "notes": "",
        })
    if len(steps) < 2:
        return None

    roles = _uniq_roles(humanize_wiki_links(r) for r in (payload.get("roles") or []) if str(r).strip())
    if not roles:
        roles = ["Process Owner", "Contributor"]
    entities = [humanize_wiki_links(e) for e in (payload.get("entities") or []) if str(e).strip()]
    decisions: list[DecisionBranch] = []
    for j, d in enumerate(payload.get("decisions") or [], start=1):
        cond = humanize_wiki_links((d or {}).get("condition") if isinstance(d, dict) else d)
        if cond:
            decisions.append({"id": f"d{j}", "condition": cond[:200],
                              "true_path": [steps[0]["id"]], "false_path": []})
        if len(decisions) >= 5:
            break
    return {
        "process_name": humanize_wiki_links(payload.get("process_name") or "Documented Process") or "Documented Process",
        "roles": roles,
        "steps": steps,
        "decisions": decisions,
        "swimlanes": _swimlanes_from_steps(steps),
        "metadata": {
            "source": "llm_structured",
            "step_count": str(len(steps)),
            "entities": json.dumps(entities[:20], ensure_ascii=False),
        },
    }


def extract_process_model(raw_text: str, assembled_context: str = "") -> ProcessModel:
    """Build a structured process; prefer the LLM pass, fall open to the heuristic."""
    llm_model = _llm_structure((raw_text or "").strip(), (assembled_context or "").strip())
    if llm_model is not None:
        if _looks_self_referential(llm_model["steps"]):
            logger.warning(
                "Extracted process looks self-referential (tool mechanics, not client process); "
                "source may be the app's own docs — review run input."
            )
        return llm_model
    return _heuristic_process_model(raw_text, assembled_context)


def _heuristic_process_model(raw_text: str, assembled_context: str = "") -> ProcessModel:
    """Deterministic regex fallback when the LLM structuring pass is unavailable."""
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

    # Strip internal wiki-link grammar / pipeline filenames so the heuristic path
    # never leaks raw markup into a deliverable (the LLM path sanitizes its own).
    for st in steps:
        st["name"] = humanize_wiki_links(st["name"])
    process_name = humanize_wiki_links(process_name) or "Documented Process"

    roles = _collect_roles(lines, steps)
    _assign_roles(steps, roles)
    step_ids = [s["id"] for s in steps]
    decisions = _build_decisions(lines, step_ids)
    swimlanes = _swimlanes_from_steps(steps)

    if _looks_self_referential(steps):
        logger.warning(
            "Heuristic process extraction looks self-referential (tool mechanics, not client "
            "process); source may be the app's own docs — review run input."
        )

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
