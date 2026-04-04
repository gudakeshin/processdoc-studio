#!/usr/bin/env python3
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / "config" / "skills"
ENFORCED_BASELINE = {
    "check_approach_sections.py",
    "check_brd_sections.py",
    "check_proposal_signals.py",
    "validate_raci_markdown.py",
}


def has_main_function(tree: ast.Module) -> bool:
    return any(isinstance(node, ast.FunctionDef) and node.name == "main" for node in tree.body)


def has_system_exit_main(tree: ast.Module) -> bool:
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "__name__"
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "__main__"
        ):
            continue
        body_src = ast.dump(ast.Module(body=node.body, type_ignores=[]))
        if "SystemExit" in body_src and "main" in body_src:
            return True
    return False


def main() -> int:
    errors: list[str] = []
    scripts = []
    for p in sorted(SKILLS_ROOT.glob("**/scripts/*.py")):
        if "/_shared_scripts/" in str(p):
            continue
        if p.name == "__init__.py":
            continue
        # Tier A enforcement baseline: start with approved validation scripts.
        if p.name not in ENFORCED_BASELINE:
            continue
        scripts.append(p)
    for path in scripts:
        src = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(src)
        except SyntaxError as exc:
            errors.append(f"{path.relative_to(ROOT)}: syntax error: {exc}")
            continue
        if not has_main_function(tree):
            errors.append(f"{path.relative_to(ROOT)}: missing main()")
        if not has_system_exit_main(tree):
            errors.append(f"{path.relative_to(ROOT)}: missing if __name__ == '__main__' -> SystemExit(main())")
    if errors:
        print("Skill script contract validation failed:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"Skill script contract validation passed for {len(scripts)} scripts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
