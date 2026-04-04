#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / "config" / "skills"


def classify_tier(path: Path) -> str:
    name = path.name.lower()
    if "check_" in name or "validate_" in name:
        return "A"
    if name in {"recalc.py", "thumbnail.py", "convert_pdf_to_images.py"}:
        return "C"
    return "B"


def main() -> int:
    items: list[dict] = []
    for script in sorted(SKILLS_ROOT.glob("**/scripts/*.py")):
        if "/_shared_scripts/" in str(script):
            continue
        if script.name == "__init__.py":
            continue
        skill = script.parts[-3]
        tier = classify_tier(script)
        items.append(
            {
                "skill": skill,
                "script": str(script.relative_to(ROOT)),
                "tier": tier,
            }
        )
    out = {
        "skills_root": str(SKILLS_ROOT.relative_to(ROOT)),
        "script_count": len(items),
        "items": items,
    }
    target = SKILLS_ROOT / "_governance" / "script_inventory.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
