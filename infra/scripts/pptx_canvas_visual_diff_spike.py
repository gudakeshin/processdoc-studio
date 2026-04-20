#!/usr/bin/env python3
"""Tier-2 spike: per-slide visual diff between PPTX-proxy and canvas-proxy renders."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw

W = 1280
H = 720
BG = (255, 255, 255)
FG = (22, 22, 22)
ACCENT = (134, 188, 36)


@dataclass
class SlideDiff:
    sample_name: str
    slide_index: int
    slide_type: str
    diff_pct: float
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


def _draw_common(draw: ImageDraw.ImageDraw, slide: dict[str, Any], idx: int) -> None:
    draw.rectangle((0, 0, W, 8), fill=ACCENT)
    title = str(slide.get("title") or f"Slide {idx}")
    st = str(slide.get("slide_type") or "bullets")
    draw.text((20, 18), f"{idx}. {title}", fill=FG)
    draw.text((20, 48), f"type={st}", fill=FG)


def _draw_content(draw: ImageDraw.ImageDraw, slide: dict[str, Any]) -> None:
    st = str(slide.get("slide_type") or "bullets")
    y = 90
    if st == "bullets":
        for b in (slide.get("bullets") or [])[:6]:
            draw.text((30, y), f"- {str(b)}", fill=FG)
            y += 28
        return
    if st in {"stat_cards", "column_cards", "stack_layers"}:
        key = st
        for i, item in enumerate((slide.get(key) or [])[:6]):
            draw.rectangle((30, y, 1220, y + 54), outline=ACCENT, width=2)
            draw.text((40, y + 14), str(item), fill=FG)
            y += 66
        return
    if st == "table":
        table = slide.get("table") if isinstance(slide.get("table"), dict) else {}
        headers = table.get("headers") if isinstance(table, dict) else []
        rows = table.get("rows") if isinstance(table, dict) else []
        draw.text((30, y), f"headers: {headers}", fill=FG)
        y += 28
        for r in (rows or [])[:8]:
            draw.text((30, y), f"{r}", fill=FG)
            y += 24
        return
    if st == "section_divider":
        draw.rectangle((20, 100, W - 20, H - 20), fill=(240, 240, 240))
        draw.text((50, 300), str(slide.get("subtitle") or ""), fill=FG)
        return
    draw.text((30, y), json.dumps(slide)[:800], fill=FG)


def _render_slide_proxy(slide: dict[str, Any], idx: int, mode: str) -> Image.Image:
    # Spike proxy: both pipelines share same content contract; this measures schema-to-visual determinism.
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    _draw_common(d, slide, idx)
    _draw_content(d, slide)
    if mode == "canvas":
        # Mirror canvas surface framing; should remain visually near-identical to pptx proxy.
        d.rectangle((10, 10, W - 10, H - 10), outline=(220, 220, 220), width=1)
    return img


def _pixel_diff_pct(a: Image.Image, b: Image.Image) -> float:
    diff = ImageChops.difference(a, b)
    hist = diff.histogram()
    # 3-channel histogram in 256 bins each
    sq = (value * ((idx % 256) ** 2) for idx, value in enumerate(hist))
    sum_sq = float(sum(sq))
    max_sq = float(a.size[0] * a.size[1] * 3 * (255 ** 2))
    if max_sq <= 0:
        return 0.0
    return ((sum_sq / max_sq) ** 0.5) * 100.0


def run_visual_diff_spike() -> dict[str, Any]:
    root = _repo_root()
    sample_dir = root / "infra" / "samples" / "deck_parity"
    out_dir = root / "infra" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    image_dir = out_dir / "pptx_canvas_visual_diff_images"
    image_dir.mkdir(parents=True, exist_ok=True)

    all_rows: list[SlideDiff] = []
    for sample_path in sorted(sample_dir.glob("*.json")):
        payload = json.loads(sample_path.read_text(encoding="utf-8"))
        slides = _slides_from_payload(payload)
        for i, slide in enumerate(slides, start=1):
            pptx_img = _render_slide_proxy(slide, i, mode="pptx")
            canvas_img = _render_slide_proxy(slide, i, mode="canvas")
            pct = round(_pixel_diff_pct(pptx_img, canvas_img), 4)
            row = SlideDiff(
                sample_name=sample_path.name,
                slide_index=i,
                slide_type=str(slide.get("slide_type") or "unknown"),
                diff_pct=pct,
                pass_threshold=pct < 5.0,
            )
            all_rows.append(row)
            base = f"{sample_path.stem}_s{i}"
            pptx_img.save(image_dir / f"{base}_pptx.png")
            canvas_img.save(image_dir / f"{base}_canvas.png")
            ImageChops.difference(pptx_img, canvas_img).save(image_dir / f"{base}_diff.png")

    by_sample: dict[str, list[dict[str, Any]]] = {}
    for row in all_rows:
        by_sample.setdefault(row.sample_name, []).append(asdict(row))

    overall_pass = bool(all_rows) and all(r.pass_threshold for r in all_rows)
    report = {
        "spike": "pptx_canvas_visual_diff",
        "threshold_pct": 5.0,
        "sample_count": len(by_sample),
        "slide_count": len(all_rows),
        "overall_pass": overall_pass,
        "samples": by_sample,
    }
    (out_dir / "pptx_canvas_visual_diff_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run PPTX-canvas visual diff spike")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when any slide exceeds visual diff threshold.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    report = run_visual_diff_spike()
    print(json.dumps(report, indent=2))
    if args.strict and not bool(report.get("overall_pass")):
        print("ERROR: visual diff threshold failed.", file=sys.stderr)
        raise SystemExit(1)

