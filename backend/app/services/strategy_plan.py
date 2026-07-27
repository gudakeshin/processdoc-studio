"""Optional LLM-generated execution strategy options (Phase C) for exploratory / analysis asks."""

from __future__ import annotations

import json
import re
from typing import Any

from app.services.claude import _extract_first_json_object, claude_generate_with_thinking, is_claude_enabled
from app.services.skill_document import load_builtin_skills

import logging
logger = logging.getLogger(__name__)


def _trim_skill_catalog(max_items: int = 36) -> list[dict[str, str]]:
    skills = load_builtin_skills()
    out: list[dict[str, str]] = []
    for s in skills:
        if len(out) >= max_items:
            break
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id") or "").strip()
        if not sid:
            continue
        uw = str(s.get("use_when") or "")[:160]
        out.append({"id": sid, "use_when": uw})
    return out


def _slug_option_id(title: str, idx: int) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", (title or "").lower()).strip("_")[:40]
    return (base or f"option_{idx + 1}")[:48]


def generate_strategy_options(*, instruction: str) -> dict[str, Any] | None:
    """Return a validated strategy dossier or None if disabled / unavailable / parse fails."""
    if not is_claude_enabled():
        return None
    catalog = _trim_skill_catalog()
    system = (
        "You are a helpful digital teammate and consulting expert for ProcessDoc Studio—clear, "
        "collaborative, and grounded in the user's goal—planning how the run should execute. "
        "The runtime has the listed skills (tools are implemented inside those skills). "
        "Return ONLY a JSON object (no markdown) with keys:\n"
        '- "problem_summary" (short string)\n'
        '- "assumptions" (array of short strings, max 6)\n'
        '- "options" (array of 2-4 objects, each with: '
        '"title" (string), "summary" (string), "steps" (string array, max 8), '
        '"tools_suggested" (string array of skill ids from available_skills only, max 8), '
        '"pros" (string array, max 4), "cons" (string array, max 4), "risks" (string array, max 3))\n'
        '- "comparison" (one short paragraph comparing the options)\n'
        '- "model_recommendation" (string: slug id of the recommended option — must match an option id you assign)\n'
        "Rules:\n"
        "- options must be meaningfully different.\n"
        "- Every tools_suggested value must appear in available_skills[].id; omit unknown tools.\n"
        "- Add stable string field \"id\" to each option (slug, lowercase, a-z0-9_ only).\n"
    )
    user = json.dumps(
        {
            "user_instruction": instruction[:8000],
            "available_skills": catalog,
        },
        ensure_ascii=True,
    )
    try:
        from app.core.config import settings

        result = claude_generate_with_thinking(
            system=system,
            user=user,
            max_tokens=min(4096, int(settings.anthropic_coordinator_plan_max_tokens)),
            budget_tokens=min(6000, int(settings.anthropic_thinking_budget_tokens)),
        )
    except Exception as exc:
        logger.warning("%s: suppressed error: %s", 'generate_strategy_options', exc)
        return None
    text = str(result.get("text") or "").strip()
    if not text:
        return None
    try:
        parsed = _extract_first_json_object(text)
    except Exception as exc:
        logger.warning("%s: suppressed error: %s", 'generate_strategy_options', exc)
        return None
    if not isinstance(parsed, dict):
        return None
    allowed_tool = {str(x["id"]) for x in catalog}
    raw_opts = parsed.get("options")
    if not isinstance(raw_opts, list):
        return None
    options: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_opts[:4]):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        oid = str(item.get("id") or "").strip() or _slug_option_id(title, idx)
        oid = re.sub(r"[^a-z0-9_]+", "_", oid.lower()).strip("_")[:48] or f"option_{idx + 1}"
        ts_raw = item.get("tools_suggested")
        tools_clean: list[str] = []
        if isinstance(ts_raw, list):
            for t in ts_raw[:8]:
                tid = str(t).strip()
                if tid in allowed_tool:
                    tools_clean.append(tid)
        options.append(
            {
                "id": oid,
                "title": title[:240],
                "summary": str(item.get("summary") or "")[:1200],
                "steps": [str(x).strip() for x in (item.get("steps") if isinstance(item.get("steps"), list) else []) if str(x).strip()][:8],
                "tools_suggested": tools_clean,
                "pros": [str(x).strip() for x in (item.get("pros") if isinstance(item.get("pros"), list) else []) if str(x).strip()][:4],
                "cons": [str(x).strip() for x in (item.get("cons") if isinstance(item.get("cons"), list) else []) if str(x).strip()][:4],
                "risks": [str(x).strip() for x in (item.get("risks") if isinstance(item.get("risks"), list) else []) if str(x).strip()][:3],
            }
        )
    if len(options) < 2:
        return None
    rec = str(parsed.get("model_recommendation") or "").strip()
    if rec not in {o["id"] for o in options}:
        rec = options[0]["id"]
    return {
        "problem_summary": str(parsed.get("problem_summary") or "")[:800],
        "assumptions": [
            str(x).strip()
            for x in (parsed.get("assumptions") if isinstance(parsed.get("assumptions"), list) else [])
            if str(x).strip()
        ][:6],
        "options": options,
        "comparison": str(parsed.get("comparison") or "")[:2000],
        "model_recommendation": rec,
    }


def resolve_selected_strategy(
    dossier: dict[str, Any] | None,
    decision_answers: dict[str, list[str]],
) -> dict[str, Any] | None:
    if not dossier or not isinstance(dossier.get("options"), list):
        return None
    picked = (decision_answers.get("execution_strategy") or [None])[0]
    picked = str(picked).strip() if picked else ""
    if not picked:
        return None
    for opt in dossier["options"]:
        if isinstance(opt, dict) and str(opt.get("id")) == picked:
            return {"option_id": picked, "option": opt}
    return {"option_id": picked}


def format_strategy_dossier_markdown(d: dict[str, Any]) -> str:
    from app.services.agent_personality import AgentPersonality

    lines = [
        "### Approaches",
        f"Here's what I'm seeing: {str(d.get('problem_summary') or '').strip()}",
        "",
    ]
    if d.get("comparison"):
        lines.extend(["**Trade-offs:**", str(d["comparison"]), ""])

    options = d.get("options") or []
    if options:
        lines.append("**Each approach has merit:**")
        lines.append("")

    for _i, o in enumerate(options, 1):
        if not isinstance(o, dict):
            continue
        emoji = AgentPersonality.PROGRESS_MARKERS.get("phase_start", "→")
        lines.append(f"{emoji} **{o.get('title')}** (`{o.get('id')}`): {str(o.get('summary') or '')[:400]}")

    rec = d.get("model_recommendation")
    if rec:
        lines.extend(
            [
                "",
                f"💡 **My recommendation:** Start with `{rec}` — it balances your constraints well.",
                "",
            ]
        )
    return "\n".join(lines).strip()
