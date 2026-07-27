"""Shared raster figure engine (Deloitte-quality program, Pillar B).

Renders themed consulting diagrams to high-resolution PNG bytes that embed
identically in PPTX and DOCX. Implemented on Pillow (already a dependency) rather
than an SVG→raster toolchain so there is no native Cairo requirement; text uses
the bundled Carlito faces so output is deterministic across machines.

Colours arrive as a role→hex map (``DocTheme.colors`` / a ``DeckTheme``-derived
dict), so figures track branding and the topic palette automatically.

Public API::

    render_figure(spec, colors, *, width_in=9.0, height_in=4.6, dpi=200) -> bytes

``spec`` is ``{"type": <one of FIGURE_TYPES>, ...data}``. Unknown/empty specs
raise ``ValueError`` so callers can fall back to a text block.
"""
from __future__ import annotations

import io
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.core.pptx_text_metrics import _FONT_DIR
from app.core.pptx_theme import _mix, _norm_hex

FIGURE_TYPES: tuple[str, ...] = (
    "two_by_two",
    "value_chain",
    "maturity_curve",
    "heat_map",
    "roadmap_matrix",
    "waterfall",
    "gantt",
    "harvey_balls",
    "benchmark_bars",
)


# ── colour helpers ───────────────────────────────────────────────────────────

def _rgb(h: str) -> tuple[int, int, int]:
    h = _norm_hex(h, "#1A1A1A").lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


class _Palette:
    """Resolve role names to RGB tuples with sensible fallbacks."""

    def __init__(self, colors: dict[str, str] | None):
        self._c = {str(k): str(v) for k, v in (colors or {}).items()}

    def hex(self, role: str, default: str) -> str:
        return _norm_hex(self._c.get(role) or default, default)

    def rgb(self, role: str, default: str) -> tuple[int, int, int]:
        return _rgb(self.hex(role, default))

    @property
    def primary(self) -> str:
        return self.hex("primary", "#86BC25")

    @property
    def ink(self) -> str:
        return self.hex("ink", "#1A1A1A")

    @property
    def inverse(self) -> str:
        return self.hex("inverse", "#FFFFFF")

    @property
    def muted(self) -> str:
        return self.hex("muted", "#9AA0A6")

    @property
    def panel(self) -> str:
        return self.hex("panel", "#1F2426")

    @property
    def accent_light(self) -> str:
        return self.hex("accent_light", "#EBF5D3")

    @property
    def hairline(self) -> str:
        return self.hex("hairline", "#D8DCDE")


# ── font + draw helpers ──────────────────────────────────────────────────────

def _font(px: int, *, bold: bool = False, italic: bool = False) -> ImageFont.FreeTypeFont:
    name = "Carlito-" + (
        "BoldItalic" if bold and italic else "Bold" if bold else "Italic" if italic else "Regular"
    ) + ".ttf"
    try:
        return ImageFont.truetype(str(_FONT_DIR / name), px)
    except Exception:
        return ImageFont.load_default()


def _text_w(draw: ImageDraw.ImageDraw, s: str, font: ImageFont.FreeTypeFont) -> float:
    try:
        return draw.textlength(s, font=font)
    except Exception:
        return font.getlength(s)


def _wrap(draw: ImageDraw.ImageDraw, s: str, font: ImageFont.FreeTypeFont, max_w: float) -> list[str]:
    words = str(s or "").split()
    if not words:
        return []
    lines, cur = [], words[0]
    for w in words[1:]:
        if _text_w(draw, cur + " " + w, font) <= max_w:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def _ellipsize(draw: ImageDraw.ImageDraw, s: str, font: ImageFont.FreeTypeFont, max_w: float) -> str:
    """Truncate ``s`` with an ellipsis so it fits within ``max_w`` pixels."""
    if _text_w(draw, s, font) <= max_w:
        return s
    ell = "…"
    while s and _text_w(draw, s + ell, font) > max_w:
        s = s[:-1]
    return (s.rstrip() + ell) if s else ell


def _fit_font(
    draw: ImageDraw.ImageDraw, text: str, base_font: ImageFont.FreeTypeFont,
    max_w: int, max_h: int, *, line_gap: int = 4, min_px: int = 9,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Shrink ``base_font`` until the wrapped text fits ``max_w`` × ``max_h``.

    Both dimensions are checked: a long word in a narrow box (e.g. a value-chain
    chevron) must shrink to fit the *width* too, otherwise it overflows and gets
    ellipsised to a single letter. Never shrinks below ``min_px``.
    """
    size = getattr(base_font, "size", 14)
    bold = "Bold" in getattr(base_font, "path", "")
    italic = "Italic" in getattr(base_font, "path", "")
    font = base_font
    while True:
        lines = _wrap(draw, text, font, max_w)
        asc, desc = font.getmetrics()
        lh = asc + desc + line_gap
        widest = max((_text_w(draw, ln, font) for ln in lines), default=0)
        fits = lh * max(1, len(lines)) <= max_h and widest <= max_w
        if fits or size <= min_px:
            return font, lines
        size -= 1
        font = _font(size, bold=bold, italic=italic)


def _draw_centered(
    draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str,
    font: ImageFont.FreeTypeFont, fill: tuple[int, int, int], *, line_gap: int = 4,
) -> None:
    x0, y0, x1, y1 = box
    max_w, max_h = x1 - x0 - 8, y1 - y0
    # Auto-fit: shrink the font so wrapped text never overflows the box vertically,
    # then ellipsize any line that is still too wide at the minimum size.
    font, lines = _fit_font(draw, text, font, max_w, max_h, line_gap=line_gap)
    asc, desc = font.getmetrics()
    lh = asc + desc + line_gap
    max_lines = max(1, max_h // lh)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    total = lh * len(lines)
    cy = y0 + ((y1 - y0) - total) // 2
    for i, ln in enumerate(lines):
        if i == len(lines) - 1:
            ln = _ellipsize(draw, ln, font, max_w)
        w = _text_w(draw, ln, font)
        draw.text((x0 + ((x1 - x0) - w) / 2, cy), ln, font=font, fill=fill)
        cy += lh


def _rounded(draw: ImageDraw.ImageDraw, box, fill=None, outline=None, width=1, radius=14) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


# ── figure renderers ─────────────────────────────────────────────────────────

def _render_two_by_two(draw, W, H, P, spec) -> None:
    pad, top = int(W * 0.12), int(H * 0.06)
    gx0, gy0, gx1, gy1 = pad, top, W - int(W * 0.04), H - int(H * 0.12)
    midx, midy = (gx0 + gx1) // 2, (gy0 + gy1) // 2
    quads = spec.get("quadrants") if isinstance(spec.get("quadrants"), list) else []
    pos_box = {
        "tl": (gx0, gy0, midx, midy), "tr": (midx, gy0, gx1, gy0 + (midy - gy0)),
        "bl": (gx0, midy, midx, gy1), "br": (midx, midy, gx1, gy1),
    }
    order = ["tl", "tr", "bl", "br"]
    fills = [P.accent_light, _mix(P.primary, "#FFFFFF", 0.78), _mix(P.primary, "#FFFFFF", 0.6), _mix(P.primary, "#FFFFFF", 0.4)]
    for i, key in enumerate(order):
        b = pos_box[key]
        q = next((q for q in quads if str(q.get("pos") or "").lower() == key), None)
        if q is None and i < len(quads):
            q = quads[i]
        draw.rectangle(b, fill=_rgb(fills[i % 4]), outline=P.rgb("inverse", "#FFFFFF"), width=6)
        if isinstance(q, dict):
            label = str(q.get("label") or "")
            _draw_centered(draw, (b[0] + 14, b[1] + 14, b[2] - 14, b[3] - 14), label, _font(int(H * 0.05), bold=True), P.rgb("ink", "#1A1A1A"))
    # axes
    draw.line([(gx0, midy), (gx1, midy)], fill=P.rgb("panel", "#1F2426"), width=4)
    draw.line([(midx, gy0), (midx, gy1)], fill=P.rgb("panel", "#1F2426"), width=4)
    fnt = _font(int(H * 0.045), bold=True)
    xl = str(spec.get("x_label") or "")
    yl = str(spec.get("y_label") or "")
    if xl:
        w = _text_w(draw, xl, fnt)
        draw.text(((gx0 + gx1) / 2 - w / 2, gy1 + 12), xl, font=fnt, fill=P.rgb("muted", "#9AA0A6"))
    if yl:
        # rotate y label
        timg = Image.new("RGBA", (gy1 - gy0, int(H * 0.06)), (0, 0, 0, 0))
        td = ImageDraw.Draw(timg)
        td.text((0, 0), yl, font=fnt, fill=P.rgb("muted", "#9AA0A6"))
        timg = timg.rotate(90, expand=True)
        draw._image.paste(timg, (int(W * 0.02), gy0), timg)  # type: ignore[attr-defined]


def _render_value_chain(draw, W, H, P, spec) -> None:
    from app.core.deliverable_utils import humanize_wiki_links

    stages = [s for s in (spec.get("stages") or []) if isinstance(s, dict)]
    n = max(1, len(stages))
    pad = int(W * 0.03)
    gap = int(W * 0.012)
    notch = int(H * 0.10)
    avail = W - 2 * pad - gap * (n - 1)
    sw = avail // n
    y0, y1 = int(H * 0.34), int(H * 0.66)
    x = pad
    palette = [P.primary, _mix(P.primary, P.panel, 0.25), P.panel, _mix(P.primary, P.panel, 0.5)]
    for i, st in enumerate(stages):
        fill = _rgb(palette[i % len(palette)])
        left = x
        right = x + sw
        # chevron polygon
        pts = [(left, y0), (right - notch, y0), (right, (y0 + y1) // 2), (right - notch, y1), (left, y1)]
        if i > 0:
            pts.append((left + notch, (y0 + y1) // 2))
        draw.polygon(pts, fill=fill)
        # Defensive: strip any internal wiki-link markup that survived upstream so the
        # chevron never shows raw '[[id|Title]]' tokens to a client.
        label = humanize_wiki_links(st.get("label") or "")
        # Keep the text inside the chevron body: clear the left notch (present on every
        # chevron after the first) and the right arrow head, so long words are not clipped.
        tx0 = left + (notch if i > 0 else int(notch * 0.4))
        _draw_centered(draw, (tx0, y0, right - notch, y1), label, _font(int(H * 0.05), bold=True), P.rgb("inverse", "#FFFFFF"))
        sub = humanize_wiki_links(st.get("sub") or st.get("description") or "")
        if sub:
            _draw_centered(draw, (left, y1 + 10, right, y1 + int(H * 0.22)), sub, _font(int(H * 0.036)), P.rgb("muted", "#5A6066"))
        x += sw + gap


def _render_maturity_curve(draw, W, H, P, spec) -> None:
    stages = [str(s) for s in (spec.get("stages") or []) if str(s).strip()]
    n = max(2, len(stages))
    pad_l, pad_r, pad_t, pad_b = int(W * 0.07), int(W * 0.05), int(H * 0.10), int(H * 0.18)
    x0, y0, x1, y1 = pad_l, pad_t, W - pad_r, H - pad_b
    # axes
    draw.line([(x0, y1), (x1, y1)], fill=P.rgb("hairline", "#D8DCDE"), width=3)
    draw.line([(x0, y0), (x0, y1)], fill=P.rgb("hairline", "#D8DCDE"), width=3)
    # ascending curve points (ease-in growth)
    pts = []
    for i in range(n):
        t = i / (n - 1)
        ease = t * t * (3 - 2 * t)  # smoothstep
        px = x0 + t * (x1 - x0)
        py = y1 - ease * (y1 - y0)
        pts.append((px, py))
    draw.line(pts, fill=P.rgb("primary", "#86BC25"), width=8, joint="curve")
    # stage ticks + labels
    fnt = _font(int(H * 0.04), bold=True)
    for i, (px, py) in enumerate(pts):
        draw.ellipse([px - 7, y1 - 7, px + 7, y1 + 7], fill=P.rgb("panel", "#1F2426"))
        lbl = stages[i] if i < len(stages) else f"Stage {i+1}"
        _draw_centered(draw, (int(px - (x1 - x0) / (2 * n)), y1 + 10, int(px + (x1 - x0) / (2 * n)), y1 + pad_b - 6), lbl, fnt, P.rgb("muted", "#5A6066"))
    # current / target markers — label sits above the dot on a white backing so it
    # never collides with the curve.
    def _marker(idx, color_hex, label):
        if idx is None or not (0 <= idx < n):
            return
        px, py = pts[idx]
        draw.ellipse([px - 16, py - 16, px + 16, py + 16], fill=_rgb(color_hex), outline=P.rgb("inverse", "#FFFFFF"), width=5)
        if not label:
            return
        lf = _font(int(H * 0.044), bold=True)
        tw = _text_w(draw, label, lf)
        asc, desc = lf.getmetrics()
        th = asc + desc
        lx = min(max(px - tw / 2, 4), W - tw - 4)
        ly = py - 26 - th
        draw.rectangle([lx - 6, ly - 3, lx + tw + 6, ly + th + 3], fill=(255, 255, 255))
        draw.text((lx, ly), label, font=lf, fill=_rgb(color_hex))
    ci = spec.get("current_index")
    ti = spec.get("target_index")
    _marker(int(ci) if isinstance(ci, (int, float)) else None, P.panel, str(spec.get("current_label") or "Today"))
    _marker(int(ti) if isinstance(ti, (int, float)) else None, P.primary, str(spec.get("target_label") or "Target"))


def _heat_color(P: _Palette, v: float) -> tuple[int, int, int]:
    v = max(0.0, min(1.0, v))
    # light wash → primary as value rises
    return _rgb(_mix(P.accent_light, P.primary, v))


def _render_heat_map(draw, W, H, P, spec) -> None:
    rows = [str(r) for r in (spec.get("rows") or [])]
    cols = [str(c) for c in (spec.get("cols") or [])]
    cells = spec.get("cells") if isinstance(spec.get("cells"), list) else []
    if not rows or not cols:
        raise ValueError("heat_map requires rows and cols")
    lab_w = int(W * 0.20)
    lab_h = int(H * 0.12)
    gx0, gy0 = lab_w, lab_h
    gw, gh = W - gx0 - int(W * 0.03), H - gy0 - int(H * 0.06)
    cw, ch = gw / len(cols), gh / len(rows)
    cfont = _font(int(min(cw, ch) * 0.26), bold=True)
    hfont = _font(int(H * 0.036), bold=True)
    # column headers
    for j, c in enumerate(cols):
        _draw_centered(draw, (int(gx0 + j * cw), 0, int(gx0 + (j + 1) * cw), gy0), c, hfont, P.rgb("ink", "#1A1A1A"))
    scale = {"low": 0.2, "med": 0.55, "medium": 0.55, "high": 0.9}
    for i, r in enumerate(rows):
        _draw_centered(draw, (0, int(gy0 + i * ch), gx0 - 8, int(gy0 + (i + 1) * ch)), r, hfont, P.rgb("ink", "#1A1A1A"))
        row_vals = cells[i] if i < len(cells) and isinstance(cells[i], list) else []
        for j, c in enumerate(cols):
            raw = row_vals[j] if j < len(row_vals) else 0
            v = scale.get(str(raw).lower(), raw if isinstance(raw, (int, float)) else 0.0)
            try:
                v = float(v)
            except Exception:
                v = 0.0
            x0 = int(gx0 + j * cw) + 3
            y0 = int(gy0 + i * ch) + 3
            x1 = int(gx0 + (j + 1) * cw) - 3
            y1 = int(gy0 + (i + 1) * ch) - 3
            draw.rectangle([x0, y0, x1, y1], fill=_heat_color(P, v))
            txt = str(raw) if not isinstance(raw, (int, float)) else (f"{raw:g}")
            tc = P.rgb("inverse", "#FFFFFF") if v >= 0.6 else P.rgb("ink", "#1A1A1A")
            _draw_centered(draw, (x0, y0, x1, y1), txt, cfont, tc)


def _render_roadmap_matrix(draw, W, H, P, spec) -> None:
    tracks = [str(t) for t in (spec.get("tracks") or [])]
    periods = [str(p) for p in (spec.get("periods") or [])]
    bars = spec.get("bars") if isinstance(spec.get("bars"), list) else []
    if not tracks or not periods:
        raise ValueError("roadmap_matrix requires tracks and periods")
    lab_w = int(W * 0.20)
    head_h = int(H * 0.12)
    gx0, gy0 = lab_w, head_h
    gw, gh = W - gx0 - int(W * 0.03), H - gy0 - int(H * 0.05)
    pw = gw / len(periods)
    rh = gh / len(tracks)
    hfont = _font(int(H * 0.04), bold=True)
    bfont = _font(int(H * 0.036), bold=True)
    # period header + gridlines
    for j, p in enumerate(periods):
        _draw_centered(draw, (int(gx0 + j * pw), 0, int(gx0 + (j + 1) * pw), gy0), p, hfont, P.rgb("muted", "#5A6066"))
        gx = int(gx0 + j * pw)
        draw.line([(gx, gy0), (gx, gy0 + gh)], fill=P.rgb("hairline", "#E3E6E8"), width=2)
    for i, t in enumerate(tracks):
        _draw_centered(draw, (0, int(gy0 + i * rh), gx0 - 8, int(gy0 + (i + 1) * rh)), t, hfont, P.rgb("ink", "#1A1A1A"))
        if i % 2 == 0:
            draw.rectangle([gx0, int(gy0 + i * rh), gx0 + gw, int(gy0 + (i + 1) * rh)], fill=_rgb(_mix(P.hairline, "#FFFFFF", 0.5)))
    status_fill = {
        "live": P.primary, "in_build": _mix(P.primary, P.panel, 0.4),
        "planned": _mix(P.primary, "#FFFFFF", 0.45), "partner": P.panel,
    }
    for b in bars:
        if not isinstance(b, dict):
            continue
        try:
            ti = tracks.index(str(b.get("track")))
        except ValueError:
            continue
        start = float(b.get("start", 0))
        span = float(b.get("span", 1))
        x0 = int(gx0 + start * pw) + 6
        x1 = int(gx0 + (start + span) * pw) - 6
        y0 = int(gy0 + ti * rh) + int(rh * 0.22)
        y1 = int(gy0 + (ti + 1) * rh) - int(rh * 0.22)
        fill = _rgb(status_fill.get(str(b.get("status") or "in_build"), P.primary))
        _rounded(draw, [x0, y0, x1, y1], fill=fill, radius=int(rh * 0.18))
        lbl = str(b.get("label") or "")
        if lbl:
            tc = P.rgb("inverse", "#FFFFFF")
            _draw_centered(draw, (x0 + 6, y0, x1 - 6, y1), lbl, bfont, tc)


def _render_waterfall(draw, W, H, P, spec) -> None:
    bars = [b for b in (spec.get("bars") or []) if isinstance(b, dict)]
    if not bars:
        return
    pad_l, pad_r, pad_b, pad_t = int(W * 0.08), int(W * 0.05), int(H * 0.18), int(H * 0.08)
    gx0, gy0, gx1, gy1 = pad_l, pad_t, W - pad_r, H - pad_b
    n = len(bars)
    gap = int((gx1 - gx0) * 0.02)
    bw = max(20, (gx1 - gx0 - gap * (n - 1)) // n)
    baseline = gy1
    running = 0.0
    max_val = max(abs(float(b.get("delta") or 0)) for b in bars) or 1.0
    scale = (gy1 - gy0) * 0.75 / max_val
    fnt = _font(int(H * 0.038), bold=True)
    for i, b in enumerate(bars):
        x0 = gx0 + i * (bw + gap)
        x1 = x0 + bw
        kind = str(b.get("kind") or "increase").lower()
        delta = float(b.get("delta") or 0)
        if kind == "total":
            h = abs(running) * scale
            y0 = int(baseline - h)
            fill = P.rgb("panel", "#1F2426")
            running = delta
        elif kind == "decrease":
            y_top = int(baseline - running * scale)
            running += delta
            y0 = int(baseline - running * scale)
            fill = _rgb(_mix("#E8007C", "#FFFFFF", 0.35))
        else:
            y0 = int(baseline - running * scale)
            running += delta
            y_top = int(baseline - running * scale)
            y0, y_top = y_top, y0
            fill = P.rgb("primary", "#86BC25")
        if kind != "total":
            draw.rectangle([x0, min(y0, baseline), x1, baseline], fill=fill)
        else:
            draw.rectangle([x0, y0, x1, baseline], fill=fill)
        lbl = str(b.get("label") or "")
        if lbl:
            _draw_centered(draw, (x0, gy1 + 6, x1, gy1 + pad_b - 4), lbl, fnt, P.rgb("muted", "#5A6066"))


def _render_gantt(draw, W, H, P, spec) -> None:
    tasks = [t for t in (spec.get("tasks") or []) if isinstance(t, dict)]
    if not tasks:
        return
    lanes = sorted({str(t.get("lane") or "Track") for t in tasks})
    if not lanes:
        lanes = ["Track"]
    pad_l, pad_r, pad_t, pad_b = int(W * 0.18), int(W * 0.04), int(H * 0.08), int(H * 0.06)
    gx0, gy0, gx1, gy1 = pad_l, pad_t, W - pad_r, H - pad_b
    rh = max(24, (gy1 - gy0) // max(1, len(lanes)))
    tfont = _font(int(min(rh, H * 0.04)), bold=True)
    lfont = _font(int(H * 0.036), bold=True)
    for li, lane in enumerate(lanes):
        y0 = gy0 + li * rh
        y1 = y0 + rh - 4
        _draw_centered(draw, (0, y0, gx0 - 8, y1), lane, lfont, P.rgb("ink", "#1A1A1A"))
        lane_tasks = [t for t in tasks if str(t.get("lane") or "Track") == lane]
        for t in lane_tasks:
            start = max(0.0, min(1.0, float(t.get("start") or 0)))
            end = max(start, min(1.0, float(t.get("end") or start + 0.1)))
            x0 = int(gx0 + start * (gx1 - gx0))
            x1 = int(gx0 + end * (gx1 - gx0))
            bar_y0 = y0 + int(rh * 0.22)
            bar_y1 = y1 - int(rh * 0.22)
            _rounded(draw, [x0, bar_y0, x1, bar_y1], fill=P.rgb("primary", "#86BC25"), radius=6)
            lbl = str(t.get("label") or "")
            if lbl and x1 - x0 > 40:
                _draw_centered(draw, (x0 + 4, bar_y0, x1 - 4, bar_y1), lbl, tfont, P.rgb("inverse", "#FFFFFF"))


def _render_harvey_balls(draw, W, H, P, spec) -> None:
    rows = [r for r in (spec.get("rows") or []) if isinstance(r, dict)]
    if not rows:
        return
    max_scores = max(len(r.get("scores") or []) for r in rows) or 1
    pad_l, pad_t = int(W * 0.22), int(H * 0.10)
    rh = max(28, (H - pad_t - int(H * 0.08)) // max(1, len(rows)))
    ball_r = max(6, min(rh // 4, int(W * 0.018)))
    gap = ball_r * 3
    lfont = _font(int(H * 0.036), bold=True)
    for i, row in enumerate(rows):
        y = pad_t + i * rh
        label = str(row.get("label") or "")
        if label:
            draw.text((int(W * 0.02), y + rh // 3), label, font=lfont, fill=P.rgb("ink", "#1A1A1A"))
        scores = row.get("scores") or []
        for j, score in enumerate(scores[:max_scores]):
            cx = pad_l + j * gap
            cy = y + rh // 2
            filled = int(score) if isinstance(score, (int, float)) else (4 if str(score).lower() in ("full", "yes", "4") else 0)
            for k in range(4):
                bx = cx + k * (ball_r * 2 + 4)
                color = P.rgb("primary", "#86BC25") if k < filled else P.rgb("hairline", "#D8DCDE")
                draw.ellipse([bx - ball_r, cy - ball_r, bx + ball_r, cy + ball_r], fill=color)


def _render_benchmark_bars(draw, W, H, P, spec) -> None:
    series = [s for s in (spec.get("series") or []) if isinstance(s, dict)]
    if not series:
        return
    pad_l, pad_r, pad_t, pad_b = int(W * 0.22), int(W * 0.08), int(H * 0.08), int(H * 0.08)
    gx0, gy0, gx1, gy1 = pad_l, pad_t, W - pad_r, H - pad_b
    rh = max(28, (gy1 - gy0) // max(1, len(series)))
    max_val = max(
        max(float(s.get("value") or 0), float(s.get("benchmark") or 0)) for s in series
    ) or 1.0
    lfont = _font(int(H * 0.036), bold=True)
    vfont = _font(int(H * 0.032))
    for i, s in enumerate(series):
        y0 = gy0 + i * rh
        y1 = y0 + rh - 6
        label = str(s.get("label") or "")
        val = float(s.get("value") or 0)
        bench = float(s.get("benchmark") or 0)
        if label:
            draw.text((int(W * 0.02), y0 + rh // 3), label, font=lfont, fill=P.rgb("ink", "#1A1A1A"))
        bar_w = int((gx1 - gx0) * (val / max_val))
        bench_x = int(gx0 + (gx1 - gx0) * (bench / max_val))
        bar_y0 = y0 + int(rh * 0.25)
        bar_y1 = y1 - int(rh * 0.25)
        draw.rectangle([gx0, bar_y0, gx0 + bar_w, bar_y1], fill=P.rgb("primary", "#86BC25"))
        draw.line([(bench_x, bar_y0 - 2), (bench_x, bar_y1 + 2)], fill=P.rgb("panel", "#1F2426"), width=3)
        draw.text((gx0 + bar_w + 6, bar_y0), f"{val:g}", font=vfont, fill=P.rgb("muted", "#5A6066"))


_DISPATCH = {
    "two_by_two": _render_two_by_two,
    "value_chain": _render_value_chain,
    "maturity_curve": _render_maturity_curve,
    "heat_map": _render_heat_map,
    "roadmap_matrix": _render_roadmap_matrix,
    "waterfall": _render_waterfall,
    "gantt": _render_gantt,
    "harvey_balls": _render_harvey_balls,
    "benchmark_bars": _render_benchmark_bars,
}


def render_figure(
    spec: dict[str, Any],
    colors: dict[str, str] | None,
    *,
    width_in: float = 9.0,
    height_in: float = 4.6,
    dpi: int = 200,
) -> bytes:
    """Render a figure spec to PNG bytes. Raises ValueError on an unknown type."""
    if not isinstance(spec, dict):
        raise ValueError("figure spec must be a dict")
    ftype = str(spec.get("type") or "").strip()
    fn = _DISPATCH.get(ftype)
    if fn is None:
        raise ValueError(f"unknown figure type: {ftype!r}")
    W, H = max(320, int(width_in * dpi)), max(200, int(height_in * dpi))
    img = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    # stash the backing image so rotated-text helpers can paste onto it
    draw._image = img  # type: ignore[attr-defined]
    fn(draw, W, H, _Palette(colors), spec)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
