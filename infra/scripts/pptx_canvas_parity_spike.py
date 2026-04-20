#!/usr/bin/env python3
"""Tier-2 spike: structural parity check between PPTX JSON and canvas schema support."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

SUPPORTED_SLIDE_TYPES = {
    "title",
    "bullets",
    "stat_cards",
    "column_cards",
    "stack_layers",
    "table",
    "section_divider",
}


@dataclass
class SampleResult:
    sample_name: str
    slide_count: int
    unsupported_slide_types: list[str]
    missing_titles: int
    parity_score: float
    pass_threshold: bool


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _slides_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        raw = payload.get("slides", payload.get("pptx_slides", []))
        if isinstance(raw, list):
            return [x for x in raw if isinstance(x, dict)]
    return []


def _score_sample(sample_name: str, payload: Any) -> SampleResult:
    slides = _slides_from_payload(payload)
    unsupported: list[str] = []
    missing_titles = 0
    for slide in slides:
        st = str(slide.get("slide_type") or "").strip().lower()
        if st not in SUPPORTED_SLIDE_TYPES:
            unsupported.append(st or "unknown")
        slide_type_for_title = st
        if slide_type_for_title == "section_divider":
            # Section dividers may rely on subtitle only; accept either title or subtitle.
            if not (
                str(slide.get("title") or "").strip()
                or str(slide.get("subtitle") or "").strip()
            ):
                missing_titles += 1
        else:
            if not str(slide.get("title") or "").strip():
                missing_titles += 1
    total = max(1, len(slides))
    penalty = len(unsupported) + missing_titles
    parity_score = max(0.0, 1.0 - (penalty / total))
    # Schema-strict: any unsupported slide type OR any missing title is a hard
    # fail regardless of how many other slides in the sample are clean. This
    # keeps CI blocking new schemas that are not yet wired into the canvas.
    schema_clean = not unsupported and missing_titles == 0
    return SampleResult(
        sample_name=sample_name,
        slide_count=len(slides),
        unsupported_slide_types=sorted(set(unsupported)),
        missing_titles=missing_titles,
        parity_score=round(parity_score, 4),
        pass_threshold=schema_clean and parity_score >= 0.95,
    )


def run_parity_spike() -> dict[str, Any]:
    root = _repo_root()
    sample_dir = root / "infra" / "samples" / "deck_parity"
    out_dir = root / "infra" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)

    sample_paths = sorted(sample_dir.glob("*.json"))
    results: list[SampleResult] = []
    for sample_path in sample_paths:
        payload = json.loads(sample_path.read_text(encoding="utf-8"))
        results.append(_score_sample(sample_path.name, payload))

    report = {
        "spike": "pptx_canvas_parity",
        "sample_count": len(results),
        "supported_slide_types": sorted(SUPPORTED_SLIDE_TYPES),
        "results": [asdict(r) for r in results],
        "overall_pass": bool(results) and all(r.pass_threshold for r in results),
    }
    out_path = out_dir / "pptx_canvas_parity_report.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run PPTX-canvas structural parity spike")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when parity threshold is not met.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    report = run_parity_spike()
    print(json.dumps(report, indent=2))
    if args.strict and not bool(report.get("overall_pass")):
        print("ERROR: structural parity threshold failed.", file=sys.stderr)
        raise SystemExit(1)

