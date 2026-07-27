"""Visual QA augmentation helpers extracted from run_worker."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from app.core.tz import IST

_log = logging.getLogger("processdoc.run_visual_qa")


def load_pptx_render_signal_hints(run_dir: Any) -> tuple[list[dict[str, Any]], list[str]]:
    path = run_dir / "pptx_render_signals.json"
    if not path.exists():
        return [], []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return [], []
    pending = raw.get("content_pending") if isinstance(raw, dict) else None
    if not isinstance(pending, list):
        return [], []
    hints: list[dict[str, Any]] = []
    findings: list[str] = []
    for item in pending:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("slide_index") or 0)
        except Exception:
            idx = 0
        if idx <= 0:
            continue
        reason = str(item.get("reason") or "Rendered with content pending placeholder.").strip()
        title = str(item.get("title") or f"Slide {idx}").strip()
        hints.append({"slide_index": idx, "instruction": f"{title}: {reason}"})
        findings.append(f"[PPTX Render] Slide {idx} ({title}): {reason}")

    qa_path = run_dir / "pptx_render_quality.json"
    if qa_path.exists():
        try:
            qa_raw = json.loads(qa_path.read_text(encoding="utf-8"))
        except Exception:
            qa_raw = {}
        storytelling = qa_raw.get("storytelling_metrics") if isinstance(qa_raw, dict) else None
        if isinstance(storytelling, dict):
            clutter = storytelling.get("clutter_risk_slides") if isinstance(storytelling.get("clutter_risk_slides"), list) else []
            weak = storytelling.get("weak_slides") if isinstance(storytelling.get("weak_slides"), list) else []
            transitions = storytelling.get("transition_issues") if isinstance(storytelling.get("transition_issues"), list) else []
            for idx in clutter[:8]:
                try:
                    n = int(idx)
                except Exception as exc:
                    _log.debug("load_pptx_render_signal_hints: %s", exc)
                    continue
                hints.append({"slide_index": n, "instruction": "Reduce text density and split long bullets into visual elements."})
                findings.append(f"[PPTX Storytelling] Slide {n}: clutter/readability risk detected.")
            for idx in weak[:8]:
                try:
                    n = int(idx)
                except Exception as exc:
                    _log.debug("load_pptx_render_signal_hints: %s", exc)
                    continue
                hints.append({"slide_index": n, "instruction": "Strengthen storyline with a specific insight title and evidence-backed takeaway."})
                findings.append(f"[PPTX Storytelling] Slide {n}: weak storytelling signal detected.")
            if transitions:
                findings.append(
                    f"[PPTX Storytelling] Transition continuity risk near slides {transitions[:8]}."
                )
    return hints, findings


def augment_visual_qa_with_render_hints(visual_qa_report: dict[str, Any], run_dir: Any) -> dict[str, Any]:
    hints, findings = load_pptx_render_signal_hints(run_dir)
    if not hints:
        return visual_qa_report
    report = dict(visual_qa_report or {})
    per_artifact = report.get("per_artifact")
    if not isinstance(per_artifact, dict):
        per_artifact = {}
        report["per_artifact"] = per_artifact
    pptx_assessment = per_artifact.get("pptx")
    if not isinstance(pptx_assessment, dict):
        pptx_assessment = {}
    existing_hints = pptx_assessment.get("remediation_hints")
    merged_hints = existing_hints if isinstance(existing_hints, list) else []
    merged_hints.extend(hints)
    pptx_assessment["remediation_hints"] = merged_hints
    pptx_assessment["status"] = "fail"
    prior_summary = str(pptx_assessment.get("summary") or "").strip()
    suffix = f"{len(hints)} slide(s) contain render placeholders."
    pptx_assessment["summary"] = f"{prior_summary} {suffix}".strip()
    per_artifact["pptx"] = pptx_assessment
    report["pptx_assessment"] = pptx_assessment
    report_findings = report.get("findings")
    merged_findings = report_findings if isinstance(report_findings, list) else []
    merged_findings.extend(findings)
    report["findings"] = merged_findings
    report["status"] = "fail"
    base_summary = str(report.get("summary") or "").strip()
    report["summary"] = f"{base_summary} PPTX render checks found unresolved placeholders.".strip()
    return report


def augment_visual_qa_with_design_review(visual_qa_report: dict[str, Any], run_dir: Any) -> dict[str, Any]:
    """Fold unified design-review hints into the PPTX visual-QA assessment."""
    path = run_dir / "design_review.json"
    if not path.exists():
        return visual_qa_report
    try:
        design = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return visual_qa_report
    if not isinstance(design, dict):
        return visual_qa_report
    hints = design.get("remediation_hints") if isinstance(design.get("remediation_hints"), list) else []
    status = str(design.get("status") or "skip").lower()
    if not hints or status == "pass":
        return visual_qa_report
    report = dict(visual_qa_report or {})
    per_artifact = report.get("per_artifact")
    if not isinstance(per_artifact, dict):
        per_artifact = {}
        report["per_artifact"] = per_artifact
    pptx_assessment = per_artifact.get("pptx") if isinstance(per_artifact.get("pptx"), dict) else {}
    merged = pptx_assessment.get("remediation_hints")
    merged = merged if isinstance(merged, list) else []
    merged.extend(hints)
    pptx_assessment["remediation_hints"] = merged
    if status == "fail":
        pptx_assessment["status"] = "fail"
        report["status"] = "fail"
    elif pptx_assessment.get("status") not in ("fail",):
        pptx_assessment.setdefault("status", "warn")
    prior = str(pptx_assessment.get("summary") or "").strip()
    pptx_assessment["summary"] = f"{prior} Design review: {design.get('summary', '')}".strip()
    per_artifact["pptx"] = pptx_assessment
    report["pptx_assessment"] = pptx_assessment
    findings = report.get("findings")
    findings = findings if isinstance(findings, list) else []
    findings.append(f"[Design Review] {design.get('summary', '')}")
    report["findings"] = findings
    return report


def persist_pptx_visual_critic_signals(run_dir: Any, visual_qa_report: dict[str, Any]) -> None:
    """Persist PPTX critic signals into pptx_render_signals.json (best effort)."""
    if not isinstance(visual_qa_report, dict):
        return
    per_artifact = visual_qa_report.get("per_artifact")
    pptx = per_artifact.get("pptx") if isinstance(per_artifact, dict) else None
    if not isinstance(pptx, dict):
        pptx = visual_qa_report.get("pptx_assessment")
    if not isinstance(pptx, dict):
        return
    payload = {
        "status": str(pptx.get("status") or "skip").lower(),
        "summary": str(pptx.get("summary") or "").strip(),
        "per_slide_findings": pptx.get("per_slide_findings") if isinstance(pptx.get("per_slide_findings"), list) else [],
        "remediation_hints": pptx.get("remediation_hints") if isinstance(pptx.get("remediation_hints"), list) else [],
        "generated_at": datetime.now(IST).isoformat() + "Z",
    }
    path = run_dir / "pptx_render_signals.json"
    try:
        current: dict[str, Any] = {}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    current = loaded
            except Exception:
                current = {}
        current["visual_critic"] = payload
        path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    except Exception:  # noqa: S110 — best-effort, non-fatal
        pass


# Backward-compatible private aliases for run_worker/tests.
_load_pptx_render_signal_hints = load_pptx_render_signal_hints
_augment_visual_qa_with_render_hints = augment_visual_qa_with_render_hints
_augment_visual_qa_with_design_review = augment_visual_qa_with_design_review
_persist_pptx_visual_critic_signals = persist_pptx_visual_critic_signals
