#!/usr/bin/env python3
"""Mirror anthropics/skills folders into backend/config/skills/<id>/ with merged SKILL.md.

Preserves app-specific YAML frontmatter; uses upstream markdown body.
Run from repo root: python backend/scripts/mirror_anthropic_skills.py
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]  # backend/
CONFIG_SKILLS = ROOT / "config" / "skills"
REGISTRY_PATH = ROOT / "config" / "skill_registry.json"

# Clone path (override with env or argv)
DEFAULT_CLONE = Path("/tmp/anthropics-skills/skills")

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)

# (app_skill_id, upstream_folder_name)
MAPPING: list[tuple[str, str]] = [
    ("docx_v1", "docx"),
    ("pptx_v1", "pptx"),
    ("pdf_v1", "pdf"),
    ("xlsx_v1", "xlsx"),
    ("brand_guidelines_v1", "brand-guidelines"),
    ("frontend_design_docx_v1", "frontend-design"),
    ("frontend_design_pptx_v1", "frontend-design"),
    ("frontend_design_xlsx_v1", "frontend-design"),
]


def split_skill(raw: str) -> tuple[dict, str]:
    raw = (raw or "").lstrip("\ufeff")
    m = FRONTMATTER_RE.match(raw)
    if not m:
        return {}, raw.strip()
    fm = yaml.safe_load(m.group(1)) or {}
    if not isinstance(fm, dict):
        fm = {}
    body = (m.group(2) or "").strip()
    return fm, body


def read_app_frontmatter(skill_dir: Path) -> dict:
    p = skill_dir / "SKILL.md"
    if not p.is_file():
        return {}
    fm, _ = split_skill(p.read_text(encoding="utf-8"))
    return fm


def merge_skill_md(app_fm: dict, upstream_body: str) -> str:
    meta = {k: v for k, v in app_fm.items() if k not in {"_skill_md_path"}}
    fm_text = yaml.safe_dump(meta, default_flow_style=False, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{fm_text}\n---\n\n{upstream_body}\n"


def copy_tree_contents(src: Path, dst: Path) -> None:
    if not src.is_dir():
        raise FileNotFoundError(f"Missing upstream: {src}")
    dst.mkdir(parents=True, exist_ok=True)
    for child in dst.iterdir():
        if child.is_file():
            child.unlink()
        else:
            shutil.rmtree(child)
    for item in src.iterdir():
        if item.is_file():
            shutil.copy2(item, dst / item.name)
        else:
            shutil.copytree(item, dst / item.name)


def main() -> int:
    skills_root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CLONE
    if not skills_root.is_dir():
        print(f"Upstream skills root not found: {skills_root}", file=sys.stderr)
        return 1

    # Load registry for fallback frontmatter
    registry_by_id: dict = {}
    if REGISTRY_PATH.is_file():
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            for row in data:
                if isinstance(row, dict) and row.get("id"):
                    registry_by_id[str(row["id"])] = row

    for skill_id, folder in MAPPING:
        src = skills_root / folder
        dst = CONFIG_SKILLS / skill_id
        app_fm = read_app_frontmatter(dst)
        if not app_fm and skill_id in registry_by_id:
            # Minimal: treat registry row as frontmatter-like (exclude non-scalar complex?)
            raw = dict(registry_by_id[skill_id])
            raw.pop("prompt_instructions", None)
            app_fm = raw
        _, upstream_body = split_skill((src / "SKILL.md").read_text(encoding="utf-8"))

        # Companion docs live next to SKILL.md upstream; allowlist relative paths for API
        if skill_id == "pptx_v1":
            app_fm["companion_files"] = ["./editing.md", "./pptxgenjs.md"]
        elif skill_id == "pdf_v1":
            app_fm["companion_files"] = ["./forms.md", "./reference.md"]

        copy_tree_contents(src, dst)
        merged = merge_skill_md(app_fm, upstream_body)
        (dst / "SKILL.md").write_text(merged, encoding="utf-8")
        print(f"Mirrored {folder} -> {skill_id}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
