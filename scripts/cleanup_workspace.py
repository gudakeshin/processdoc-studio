#!/usr/bin/env python3
"""Workspace cleanup utility.

The ``workspace/`` directory holds per-project scratch data (uploaded documents,
run artifacts, generated deliverables). It is already gitignored; this script
prunes finished runs and stale project directories so operators do not have to
clean up manually.

Usage
-----

    python scripts/cleanup_workspace.py --older-than-days 14 [--dry-run] [--keep-projects p_abc,p_xyz]

By default the script:
    * targets ``workspace/`` relative to the repository root,
    * refuses to run unless ``--force`` is passed when the target path is not
      named ``workspace`` (defence against accidental deletion),
    * only removes ``p_*`` project subtrees (runs, models, context) — it does
      not touch ``workspace/.lp_index`` or any non-project file.

The script is safe to run repeatedly and on CI. It emits a JSON summary on
stdout so operators can plug it into scheduled maintenance.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path


def _iter_project_dirs(workspace: Path) -> list[Path]:
    if not workspace.exists() or not workspace.is_dir():
        return []
    return sorted(p for p in workspace.iterdir() if p.is_dir() and p.name.startswith("p_"))


def _recent_mtime(path: Path) -> float:
    """Largest mtime across ``path`` and its direct contents.

    Using the deepest-touched file makes the 'older than' check reflect real
    activity rather than the project folder's creation time.
    """

    latest = path.stat().st_mtime
    try:
        for child in path.rglob("*"):
            try:
                m = child.stat().st_mtime
                if m > latest:
                    latest = m
            except OSError:
                continue
    except OSError:
        pass
    return latest


def _human_size(num_bytes: float) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    size = float(num_bytes)
    for unit in units:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PiB"


def _dir_size_bytes(path: Path) -> int:
    total = 0
    try:
        for child in path.rglob("*"):
            try:
                if child.is_file():
                    total += child.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


def cleanup(
    workspace: Path,
    *,
    older_than_days: float,
    dry_run: bool,
    keep_projects: frozenset[str],
) -> dict:
    cutoff_epoch = time.time() - older_than_days * 86400.0
    deleted: list[dict] = []
    retained: list[dict] = []
    errors: list[dict] = []
    total_bytes_reclaimed = 0

    for project_dir in _iter_project_dirs(workspace):
        name = project_dir.name
        if name in keep_projects:
            retained.append({"project": name, "reason": "keep-list"})
            continue
        mtime = _recent_mtime(project_dir)
        if mtime > cutoff_epoch:
            retained.append(
                {
                    "project": name,
                    "reason": "recent",
                    "last_activity_epoch": mtime,
                }
            )
            continue

        size_bytes = _dir_size_bytes(project_dir)
        entry = {
            "project": name,
            "last_activity_epoch": mtime,
            "size_bytes": size_bytes,
            "size_human": _human_size(size_bytes),
        }
        if dry_run:
            entry["action"] = "would_delete"
            deleted.append(entry)
            continue
        try:
            shutil.rmtree(project_dir)
            entry["action"] = "deleted"
            deleted.append(entry)
            total_bytes_reclaimed += size_bytes
        except Exception as exc:
            entry["action"] = "error"
            entry["error"] = str(exc)
            errors.append(entry)

    return {
        "workspace": str(workspace),
        "older_than_days": older_than_days,
        "dry_run": dry_run,
        "deleted": deleted,
        "retained": retained,
        "errors": errors,
        "total_bytes_reclaimed": total_bytes_reclaimed,
        "total_reclaimed_human": _human_size(total_bytes_reclaimed),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prune stale project folders from workspace/.")
    parser.add_argument(
        "--workspace",
        default=str(Path(__file__).resolve().parent.parent / "workspace"),
        help="Path to workspace directory (default: <repo>/workspace).",
    )
    parser.add_argument(
        "--older-than-days",
        type=float,
        default=14.0,
        help="Delete projects with no activity newer than this many days (default: 14).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be deleted without removing files.",
    )
    parser.add_argument(
        "--keep-projects",
        default="",
        help="Comma-separated list of project IDs (e.g. p_abc,p_xyz) to retain.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow running when the target path is not named 'workspace'.",
    )
    args = parser.parse_args(argv)

    workspace = Path(args.workspace).resolve()
    if workspace.name != "workspace" and not args.force:
        print(
            f"Refusing to operate on {workspace!s}: target is not named 'workspace'. "
            "Pass --force to override.",
            file=sys.stderr,
        )
        return 2
    if not workspace.exists():
        print(json.dumps({"workspace": str(workspace), "status": "missing"}, indent=2))
        return 0
    keep = frozenset(
        x.strip() for x in args.keep_projects.split(",") if x.strip()
    )
    summary = cleanup(
        workspace,
        older_than_days=args.older_than_days,
        dry_run=args.dry_run,
        keep_projects=keep,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not summary["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
