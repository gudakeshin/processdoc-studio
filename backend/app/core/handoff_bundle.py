"""Claude Code handoff bundle builder.

Packages the essential artifacts produced by a run into a single ZIP file that
can be handed to Claude Code (or any other coding agent / reviewer) so they can
pick up where the run left off. The bundle focuses on the text-first artifacts
that an agent can act on — binary deliverables are referenced by filename only
to keep the bundle small and email-safe.

Contents (present only when the source exists):

- ``README.md``                — human-friendly overview + resume instructions.
- ``handoff_manifest.json``    — machine-readable inventory of included files.
- ``run_metadata.json``        — run identifiers, status, instruction, plan.
- ``instruction.md``           — the original user instruction.
- ``assembled_context.txt``    — retrieval context used by the run.
- ``process_model.json``       — structured process model.
- ``pptx_slides.json``         — slide JSON contract for the deck.
- ``narrative.md``             — generated narrative (if any).
- ``docx_markdown.md``         — DOCX source markdown (if any).
- ``qa_report.json``           — quality/evaluation report.
- ``guardrail_report.json``    — guardrail/DPDP report.
- ``visual_qa_report.json``    — visual QA report.
- ``pptx_render_signals.json`` — PPTX render/critic signals.
- ``deliverables.txt``         — plain list of binary deliverable filenames.

The builder is fully fail-open: it will include as much as it can and never
raises out to the caller. On any unexpected error it returns ``None``.
"""

from __future__ import annotations

import json
import logging
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_TEXT_SOURCES: tuple[tuple[str, str], ...] = (
    ("instruction.md", "user_instruction.txt"),
    ("assembled_context.txt", "assembled_context.txt"),
    ("process_model.json", "process_model.json"),
    ("pptx_slides.json", "pptx_slides.json"),
    ("narrative.md", "narrative.md"),
    ("docx_markdown.md", "docx_markdown.txt"),
    ("qa_report.json", "qa_report.json"),
    ("guardrail_report.json", "guardrail_report.json"),
    ("visual_qa_report.json", "visual_qa_report.json"),
    ("pptx_render_signals.json", "pptx_render_signals.json"),
    ("artifacts_typed.json", "artifacts_typed.json"),
    ("deck.html", "deck.html"),
)

_BINARY_DELIVERABLES: tuple[str, ...] = (
    "output.docx",
    "output.pptx",
    "output.xlsx",
    "output.pdf",
    "deck.pdf",
)


@dataclass
class HandoffBundleResult:
    """Outcome of a bundle build."""

    zip_path: Path | None
    manifest: dict[str, Any]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "zip_path": str(self.zip_path) if self.zip_path else None,
            "manifest": self.manifest,
            "errors": list(self.errors),
        }


def _read_text_safe(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("handoff_bundle: could not read %s: %s", path, exc)
        return None


def _build_readme(metadata: dict[str, Any], included: Iterable[str]) -> str:
    generated = metadata.get("generated_at") or datetime.now(UTC).isoformat()
    run_id = metadata.get("run_id") or "(unknown)"
    project_id = metadata.get("project_id") or "(unknown)"
    status = metadata.get("status") or "(unknown)"
    instruction = (metadata.get("instruction") or "").strip() or "(no instruction captured)"
    lines: list[str] = [
        "# Run Handoff Bundle",
        "",
        f"- Generated: {generated}",
        f"- Project: `{project_id}`",
        f"- Run: `{run_id}`",
        f"- Status: `{status}`",
        "",
        "## Original Instruction",
        "",
        "```",
        instruction,
        "```",
        "",
        "## How To Resume",
        "",
        "1. Unzip this bundle next to your working copy of the repo.",
        "2. Open `run_metadata.json` for plan hash, output types, and timestamps.",
        "3. Read `assembled_context.txt` to see the retrieval context the run used.",
        "4. Inspect the artifacts listed under **Included files** below; any JSON report",
        "   (`qa_report.json`, `guardrail_report.json`, `visual_qa_report.json`,",
        "   `pptx_render_signals.json`) describes outstanding issues to address.",
        "5. Binary deliverables (`output.docx`, `output.pptx`, ...) are **referenced by",
        "   filename** in `deliverables.txt`; fetch them from the run workspace if you",
        "   need the originals.",
        "",
        "## Included files",
        "",
    ]
    for name in included:
        lines.append(f"- `{name}`")
    lines.append("")
    return "\n".join(lines)


def _collect_run_metadata(run_dir: Path, overrides: dict[str, Any] | None) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "project_id": "",
        "run_id": "",
        "status": "",
        "instruction": "",
        "plan_hash": "",
        "output_types": [],
    }
    if overrides:
        for key, value in overrides.items():
            if value is None:
                continue
            meta[key] = value
    # Fallback to workspace-side flat files when DB metadata is unavailable.
    if not meta.get("project_id"):
        meta["project_id"] = (_read_text_safe(run_dir / "project_id.txt") or "").strip()
    if not meta.get("run_id"):
        meta["run_id"] = (_read_text_safe(run_dir / "run_id.txt") or "").strip()
    if not meta.get("instruction"):
        meta["instruction"] = (_read_text_safe(run_dir / "user_instruction.txt") or "").strip()
    return meta


def build_handoff_bundle(
    run_dir: Path,
    *,
    metadata: dict[str, Any] | None = None,
    output_filename: str = "handoff_bundle.zip",
) -> HandoffBundleResult:
    """Write a handoff bundle zip inside ``run_dir`` and return its path.

    Never raises on missing files; emits whatever is available. Unrecoverable
    errors (e.g. read-only run_dir) are captured in ``HandoffBundleResult.errors``
    and the zip path is returned as ``None``.
    """

    errors: list[str] = []
    manifest: dict[str, Any] = {"included": [], "missing": [], "deliverables": []}

    if not run_dir or not run_dir.exists():
        return HandoffBundleResult(zip_path=None, manifest=manifest, errors=[f"run_dir not found: {run_dir}"])

    run_meta = _collect_run_metadata(run_dir, metadata)

    included_files: list[tuple[str, str]] = []  # (archive_name, contents)
    for archive_name, source_name in _TEXT_SOURCES:
        src_path = run_dir / source_name
        contents = _read_text_safe(src_path)
        if contents is None:
            manifest["missing"].append(source_name)
            continue
        included_files.append((archive_name, contents))
        manifest["included"].append(archive_name)

    deliverables_present = [name for name in _BINARY_DELIVERABLES if (run_dir / name).exists()]
    manifest["deliverables"] = deliverables_present

    zip_path = run_dir / output_filename
    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "run_metadata.json",
                json.dumps(run_meta, indent=2, default=str),
            )
            manifest["included"].insert(0, "run_metadata.json")
            for archive_name, contents in included_files:
                zf.writestr(archive_name, contents)
            if deliverables_present:
                zf.writestr(
                    "deliverables.txt",
                    "\n".join(deliverables_present) + "\n",
                )
                manifest["included"].append("deliverables.txt")
            zf.writestr("handoff_manifest.json", json.dumps(manifest, indent=2))
            zf.writestr("README.md", _build_readme(run_meta, manifest["included"] + ["handoff_manifest.json"]))
        return HandoffBundleResult(zip_path=zip_path, manifest=manifest, errors=errors)
    except Exception as exc:
        logger.warning("handoff_bundle: failed to write %s: %s", zip_path, exc)
        errors.append(f"zip: {exc}")
        return HandoffBundleResult(zip_path=None, manifest=manifest, errors=errors)
