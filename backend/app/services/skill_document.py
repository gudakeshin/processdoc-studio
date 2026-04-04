"""
Load agent skills from Cursor/Claude-style SKILL.md files (YAML frontmatter + markdown body).

Produces the same dict shape historically used from skill_registry.json so coordinators
and APIs do not need to branch on storage format.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

_SKILL_MD_NAME = "SKILL.md"
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)

_CONFIG_PARENTS = 2  # app/services -> app
_BUILTIN_SKILLS_DIR = Path(__file__).resolve().parents[_CONFIG_PARENTS] / "config" / "skills"
_LEGACY_REGISTRY_JSON = Path(__file__).resolve().parents[_CONFIG_PARENTS] / "config" / "skill_registry.json"


def split_skill_markdown(raw: str) -> tuple[dict[str, Any], str]:
    raw = (raw or "").lstrip("\ufeff")
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        return {}, raw.strip()
    fm_text, body = m.group(1), m.group(2)
    try:
        loaded = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        loaded = {}
    if not isinstance(loaded, dict):
        return {}, body.strip()
    return dict(loaded), body.strip()


def _normalize_skill_dict(
    data: dict[str, Any],
    *,
    body: str,
    custom: bool,
    source_path: Path | None = None,
) -> dict[str, Any]:
    out = dict(data)
    out["custom"] = bool(custom)
    pi_fm = out.pop("prompt_instructions", None)
    if isinstance(pi_fm, str) and pi_fm.strip():
        out["prompt_instructions"] = pi_fm.strip()
    else:
        out["prompt_instructions"] = body.strip()
    if source_path is not None:
        out["_skill_md_path"] = str(source_path.resolve())
    return out


def skill_dict_from_markdown_file(path: Path, *, custom: bool) -> dict[str, Any] | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    fm, body = split_skill_markdown(raw)
    if not fm and not body.strip():
        return None
    return _normalize_skill_dict(fm, body=body, custom=custom, source_path=path)


def load_skills_from_tree(skills_root: Path, *, custom: bool) -> list[dict[str, Any]]:
    if not skills_root.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for skill_md in sorted(skills_root.glob(f"*/{_SKILL_MD_NAME}")):
        parsed = skill_dict_from_markdown_file(skill_md, custom=custom)
        if parsed and parsed.get("id"):
            items.append(parsed)
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        sid = str(item.get("id") or "")
        ver = str(item.get("version") or "")
        key = (sid, ver)
        if not sid or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def load_builtin_skills_from_markdown() -> list[dict[str, Any]]:
    return load_skills_from_tree(_BUILTIN_SKILLS_DIR, custom=False)


def load_legacy_json_registry() -> list[dict[str, Any]]:
    try:
        raw = _LEGACY_REGISTRY_JSON.read_text(encoding="utf-8")
        parsed = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def load_builtin_skills() -> list[dict[str, Any]]:
    md_items = load_builtin_skills_from_markdown()
    if md_items:
        return md_items
    legacy = load_legacy_json_registry()
    out: list[dict[str, Any]] = []
    for row in legacy:
        if isinstance(row, dict):
            r = dict(row)
            r.setdefault("custom", False)
            out.append(r)
    return out


def load_custom_skills_from_workspace(custom_skills_root: Path) -> list[dict[str, Any]]:
    if not custom_skills_root.is_dir():
        return []
    md_by_id: dict[str, dict[str, Any]] = {}
    for d in sorted(custom_skills_root.iterdir()):
        if not d.is_dir():
            continue
        skill_file = d / _SKILL_MD_NAME
        if skill_file.is_file():
            parsed = skill_dict_from_markdown_file(skill_file, custom=True)
            if parsed and parsed.get("id"):
                md_by_id[str(parsed["id"])] = parsed
    json_by_id: dict[str, dict[str, Any]] = {}
    for d in sorted(custom_skills_root.iterdir()):
        if not d.is_dir():
            continue
        for version_file in sorted(d.glob("*.json")):
            try:
                data = json.loads(version_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(data, dict) and data.get("id"):
                json_by_id[str(data["id"])] = data
    merged_ids = sorted(set(md_by_id.keys()) | set(json_by_id.keys()))
    return [md_by_id[i] if i in md_by_id else json_by_id[i] for i in merged_ids]


def skill_dict_to_skill_md(skill: dict[str, Any]) -> str:
    body_text = str(skill.get("prompt_instructions") or "").strip()
    meta = {k: v for k, v in skill.items() if k not in {"prompt_instructions", "_skill_md_path"}}
    fm_lines = yaml.safe_dump(meta, default_flow_style=False, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{fm_lines}\n---\n\n{body_text}\n"


def write_skill_md(path: Path, skill: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(skill_dict_to_skill_md(skill), encoding="utf-8")

def skill_dict_from_markdown_text(raw: str, *, custom: bool) -> dict[str, Any] | None:
    fm, body = split_skill_markdown(raw)
    if not fm and not body.strip():
        return None
    return _normalize_skill_dict(fm, body=body, custom=custom, source_path=None)


BUILTIN_SKILLS_ROOT = _BUILTIN_SKILLS_DIR
