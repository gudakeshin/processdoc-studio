"""Editorial component library.

Reusable slide primitives built on python-pptx, driven by a ``DeckTheme`` and the
deterministic text-measurement engine. Components take ``(slide, theme, rect...)``
and return geometry so composers can stack them. Every text-bearing primitive
measures before it draws, which is what lets the editorial renderer beat the
reference deck's overlap/clip bugs.

Canvas is the same widescreen 16:9 as the rest of the renderer (13.333 x 7.5 in).
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from typing import Any

from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from app.core import pptx_text_metrics as tm
from app.core.pptx_theme import DeckTheme

logger = logging.getLogger(__name__)

SLIDE_W = 13.333
SLIDE_H = 7.5


def rgb(hexstr: str) -> RGBColor:
    h = str(hexstr or "").strip().lstrip("#")
    if len(h) >= 6:
        with contextlib.suppress(ValueError):
            return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    return RGBColor(0x1A, 0x1A, 0x1A)


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def right(self) -> float:
        return self.x + self.w


# --- low-level shape/text helpers -------------------------------------------

def add_rect(
    slide: Any,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    fill: str | None = None,
    line: str | None = None,
    line_pt: float | None = None,
    shape: Any = MSO_SHAPE.RECTANGLE,
) -> Any:
    sp = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill is None:
        sp.fill.background()
    else:
        sp.fill.solid()
        sp.fill.fore_color.rgb = rgb(fill)
    if line is None:
        sp.line.fill.background()
    else:
        sp.line.color.rgb = rgb(line)
        sp.line.width = Pt(line_pt if line_pt is not None else 1.0)
    sp.shadow.inherit = False
    return sp


def soft_shadow(shape: Any) -> None:
    """Best-effort subtle drop shadow for visual depth. Fail-open."""
    with contextlib.suppress(Exception):
        shadow = shape.shadow
        shadow.inherit = False
        shadow.visible = True


def linear_gradient(shape: Any, color_a: str, color_b: str, *, angle: float = 35.0) -> None:
    """Best-effort linear gradient fill for hero/section shapes. Falls back to solid."""
    try:
        fill = shape.fill
        fill.gradient()
        with contextlib.suppress(Exception):
            fill.gradient_angle = angle
        stops = list(fill.gradient_stops)
        if len(stops) >= 2:
            stops[0].color.rgb = rgb(color_a)
            stops[1].color.rgb = rgb(color_b)
    except Exception:
        with contextlib.suppress(Exception):
            shape.fill.solid()
            shape.fill.fore_color.rgb = rgb(color_a)


def _set_letter_spacing(run: Any, pt: float) -> None:
    """Apply tracking via the OOXML ``spc`` attr (1/100 pt). Fail-open."""
    if not pt:
        return
    with contextlib.suppress(Exception):
        run._r.get_or_add_rPr().set("spc", str(int(pt * 100)))


def textbox(
    slide: Any,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    anchor: Any = MSO_ANCHOR.TOP,
    wrap: bool = True,
    margin: float = 0.0,
) -> Any:
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = wrap
    tf.vertical_anchor = anchor
    tf.margin_left = Inches(margin)
    tf.margin_right = Inches(margin)
    tf.margin_top = Inches(margin)
    tf.margin_bottom = Inches(margin)
    return tf


def add_run(
    p: Any,
    text: str,
    *,
    font: str,
    size: float,
    color: str,
    bold: bool = False,
    italic: bool = False,
    spc: float = 0.0,
    caps: bool = False,
) -> Any:
    run = p.add_run()
    run.text = (text or "").upper() if caps else (text or "")
    run.font.name = font
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = rgb(color)
    if spc:
        _set_letter_spacing(run, spc)
    return run


def _split_emphasis(text: str, emphasis: str | None) -> list[tuple[str, bool]]:
    """Split a headline into (segment, is_emphasis) runs around ``emphasis``.

    Falls back to a single non-emphasis segment if the substring is absent.
    """
    text = text or ""
    emph = (emphasis or "").strip()
    if not emph or emph not in text:
        return [(text, False)]
    idx = text.find(emph)
    out: list[tuple[str, bool]] = []
    if idx > 0:
        out.append((text[:idx], False))
    out.append((emph, True))
    tail = text[idx + len(emph):]
    if tail:
        out.append((tail, False))
    return out


# --- chrome ------------------------------------------------------------------

def slide_border_frame(slide: Any, theme: DeckTheme) -> None:
    """Thin primary perimeter frame — the editorial deck's signature chrome."""
    if not theme.chrome.get("border"):
        return
    inset = 0.09
    add_rect(
        slide, inset, inset, SLIDE_W - 2 * inset, SLIDE_H - 2 * inset,
        fill=None, line=theme.color("primary"), line_pt=1.25,
    )


def footer_band(slide: Any, theme: DeckTheme, deck_label: str, page_num: int, total: int) -> None:
    """Hairline rule + left micro-label (square bullet) + right CONFIDENTIAL · nn / NN."""
    m_h = theme.spacing["margin_h"]
    y = SLIDE_H - theme.spacing["margin_v"] - 0.18
    hairline_rule(slide, theme, m_h, y - 0.08, SLIDE_W - 2 * m_h)
    spc = theme.spacing.get("letter_spacing", 2.0)
    # Left: square bullet + deck label.
    add_rect(slide, m_h, y + 0.045, 0.06, 0.06, fill=theme.color("primary"))
    left = textbox(slide, m_h + 0.14, y, (SLIDE_W - 2 * m_h) * 0.7, 0.22)
    p = left.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    add_run(p, deck_label, font=theme.font_body, size=theme.type_scale["footer"],
            color=theme.color("muted"), spc=spc, caps=True)
    # Right: confidential + page.
    tmpl = theme.chrome.get("footer_right_template", "{nn} / {NN}")
    right_text = tmpl.format(nn=f"{page_num:02d}", NN=f"{total:02d}")
    right = textbox(slide, m_h + (SLIDE_W - 2 * m_h) * 0.4, y, (SLIDE_W - 2 * m_h) * 0.6, 0.22)
    rp = right.paragraphs[0]
    rp.alignment = PP_ALIGN.RIGHT
    add_run(rp, right_text, font=theme.font_body, size=theme.type_scale["footer"],
            color=theme.color("muted"), spc=spc, caps=True)


def hairline_rule(slide: Any, theme: DeckTheme, x: float, y: float, w: float) -> None:
    pt = theme.spacing.get("hairline_pt", 0.75)
    add_rect(slide, x, y, w, pt / 72.0, fill=theme.color("hairline"))


def micro_label(
    slide: Any, theme: DeckTheme, x: float, y: float, w: float, text: str,
    *, color: str | None = None, size: float | None = None,
) -> Any:
    tf = textbox(slide, x, y, w, 0.2)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    add_run(p, text, font=theme.font_body, size=size or theme.type_scale["micro"],
            color=color or theme.color("muted"),
            spc=theme.spacing.get("letter_spacing", 2.0), bold=True, caps=True)
    return tf


# --- header block ------------------------------------------------------------

def header_block(
    slide: Any,
    theme: DeckTheme,
    *,
    title: str,
    eyebrow: str = "",
    section_number: str = "",
    emphasis: str | None = None,
    kicker: str = "",
    x: float | None = None,
    y: float | None = None,
    w: float | None = None,
) -> float:
    """Eyebrow + two-tone assertion headline + italic kicker. Returns content-top y."""
    m_h = theme.spacing["margin_h"]
    m_v = theme.spacing["margin_v"]
    x = m_h if x is None else x
    y = m_v if y is None else y
    w = (SLIDE_W - 2 * m_h) if w is None else w
    cursor = y

    if eyebrow or section_number:
        label = eyebrow.strip()
        if section_number:
            label = f"{section_number} · {label}" if label else section_number
        tf = textbox(slide, x, cursor, w, 0.22)
        p = tf.paragraphs[0]
        add_run(p, label, font=theme.font_body, size=theme.type_scale["eyebrow"],
                color=theme.color("primary"), spc=theme.spacing.get("letter_spacing", 2.0),
                bold=True, caps=True)
        cursor += 0.30

    # Headline — measured so it never clips; shrink within the title band.
    max_pt = theme.type_scale["headline"]
    fit = tm.fit_text(
        title, box_w_in=w, box_h_in=1.05, family=theme.font_header,
        max_pt=max_pt, min_pt=max_pt * 0.62, bold=True, max_lines=2,
    )
    pt = fit.pt
    line_h = pt * 1.12 / 72.0
    head_h = max(line_h * max(1, len(fit.lines)), line_h)
    tf = textbox(slide, x, cursor, w, head_h + 0.1, anchor=MSO_ANCHOR.TOP)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    for seg, is_emph in _split_emphasis(title, emphasis):
        add_run(p, seg, font=theme.font_header, size=pt, bold=True,
                color=theme.color("primary") if is_emph else theme.color("ink"))
    cursor += head_h + 0.12

    if kicker:
        kf = tm.fit_text(kicker, box_w_in=w, box_h_in=0.7, family=theme.font_header,
                         max_pt=theme.type_scale["kicker"], min_pt=12, italic=True, max_lines=2)
        ktf = textbox(slide, x, cursor, w, kf.height_in + 0.12)
        kp = ktf.paragraphs[0]
        add_run(kp, kicker, font=theme.font_header, size=kf.pt, italic=True,
                color=theme.color("primary"))
        cursor += kf.height_in + 0.14

    return cursor + theme.spacing["gutter"]


# --- small repeating widgets -------------------------------------------------

def label_chip(
    slide: Any, theme: DeckTheme, x: float, y: float, text: str,
    *, fill: str | None = None, text_color: str | None = None, height: float = 0.26,
) -> float:
    """Filled caps chip (BUILD / DEPLOY / PARTNER). Returns chip width."""
    fill = fill or theme.color("panel")
    text_color = text_color or theme.color("inverse")
    pt = theme.type_scale.get("micro", 8.5) + 0.5
    w = max(0.7, tm.measure_text_width_in(text.upper(), theme.font_body, pt, bold=True) + 0.28)
    sp = add_rect(slide, x, y, w, height, fill=fill)
    tf = sp.text_frame
    tf.word_wrap = False
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = Inches(0.08)
    tf.margin_right = Inches(0.08)
    tf.margin_top = Inches(0)
    tf.margin_bottom = Inches(0)
    p = tf.paragraphs[0]
    add_run(p, text, font=theme.font_body, size=pt, color=text_color,
            spc=theme.spacing.get("letter_spacing", 2.0), bold=True, caps=True)
    return w


def status_dot(slide: Any, theme: DeckTheme, x: float, y: float, status: str, *, d: float = 0.12) -> None:
    add_rect(slide, x, y, d, d, fill=theme.status_color(status), shape=MSO_SHAPE.OVAL)


def status_legend(slide: Any, theme: DeckTheme, x: float, y: float, items: list[tuple[str, str]]) -> None:
    """items: list of (status_key, label)."""
    cursor = x
    for status, label in items:
        status_dot(slide, theme, cursor, y + 0.02, status, d=0.11)
        pt = theme.type_scale.get("micro", 8.5)
        w = tm.measure_text_width_in(label, theme.font_body, pt) + 0.16
        tf = textbox(slide, cursor + 0.16, y, w, 0.2, anchor=MSO_ANCHOR.MIDDLE)
        add_run(tf.paragraphs[0], label, font=theme.font_body, size=pt, color=theme.color("muted"))
        cursor += 0.16 + w + 0.22


def numbered_circle(slide: Any, theme: DeckTheme, x: float, y: float, n: int, *, d: float = 0.4) -> None:
    sp = add_rect(slide, x, y, d, d, fill=None, line=theme.color("primary"), line_pt=1.5, shape=MSO_SHAPE.OVAL)
    tf = sp.text_frame
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    for m in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
        setattr(tf, m, Inches(0))
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    add_run(p, str(n), font=theme.font_header, size=d * 72 * 0.42, bold=True, color=theme.color("primary"))


def stat_block(
    slide: Any, theme: DeckTheme, r: Rect,
    *, value: str, label: str = "", desc: str = "", accent: str | None = None,
) -> None:
    """Colored left border + big number + caps label + description."""
    accent = accent or theme.color("primary")
    panel = add_rect(slide, r.x, r.y, r.w, r.h, fill=theme.color("inverse"),
                     line=theme.color("hairline"), line_pt=0.75)
    soft_shadow(panel)
    add_rect(slide, r.x, r.y, 0.06, r.h, fill=accent)
    tx = r.x + 0.22
    tw = r.w - 0.3
    # Big number (measured).
    vf = tm.fit_text(value, box_w_in=tw, box_h_in=r.h * 0.5, family=theme.font_header,
                     max_pt=theme.type_scale.get("stat_value", 40), min_pt=20, bold=True, max_lines=1)
    vtf = textbox(slide, tx, r.y, tw, vf.pt * 1.2 / 72.0 + 0.05)
    add_run(vtf.paragraphs[0], value, font=theme.font_header, size=vf.pt, bold=True, color=theme.color("ink"))
    cursor = r.y + vf.pt * 1.2 / 72.0 + 0.06
    if label:
        micro_label(slide, theme, tx, cursor, tw, label, color=theme.color("primary"))
        cursor += 0.22
    if desc:
        df = tm.fit_text(desc, box_w_in=tw, box_h_in=max(0.3, r.bottom - cursor), family=theme.font_body,
                         max_pt=theme.type_scale["body"] - 1, min_pt=8)
        dtf = textbox(slide, tx, cursor, tw, max(0.3, r.bottom - cursor))
        add_run(dtf.paragraphs[0], desc, font=theme.font_body, size=df.pt, color=theme.color("muted"))


def card(
    slide: Any, theme: DeckTheme, r: Rect,
    *, heading: str = "", body: str = "", top_color: str | None = None,
    owner: str = "", status: str | None = None, status_label: str = "",
) -> None:
    """Top-bordered card with heading, body, optional OWNER micro-label + status chip."""
    top_color = top_color or theme.color("primary")
    bg = add_rect(slide, r.x, r.y, r.w, r.h, fill=theme.color("inverse"), line=theme.color("hairline"), line_pt=0.75)
    soft_shadow(bg)
    add_rect(slide, r.x, r.y, r.w, 0.05, fill=top_color)
    pad = 0.16
    tx = r.x + pad
    tw = r.w - 2 * pad
    cursor = r.y + 0.18
    if heading:
        hf = tm.fit_text(heading, box_w_in=tw, box_h_in=0.6, family=theme.font_header,
                         max_pt=theme.type_scale.get("card_title", 14), min_pt=10, bold=True, max_lines=2)
        htf = textbox(slide, tx, cursor, tw, hf.height_in + 0.06)
        add_run(htf.paragraphs[0], heading, font=theme.font_header, size=hf.pt, bold=True, color=theme.color("ink"))
        cursor += hf.height_in + 0.1
    if body:
        body_bottom = r.bottom - (0.5 if (owner or status) else 0.18)
        bf = tm.fit_text(body, box_w_in=tw, box_h_in=max(0.3, body_bottom - cursor), family=theme.font_body,
                         max_pt=theme.type_scale["body"], min_pt=8)
        btf = textbox(slide, tx, cursor, tw, max(0.3, body_bottom - cursor))
        bp = btf.paragraphs[0]
        for i, ln in enumerate(bf.lines or [body]):
            p = bp if i == 0 else btf.add_paragraph()
            add_run(p, ln, font=theme.font_body, size=bf.pt, color=theme.color("muted"))
    if owner or status:
        oy = r.bottom - 0.42
        hairline_rule(slide, theme, tx, oy - 0.04, tw)
        if owner:
            micro_label(slide, theme, tx, oy, tw * 0.6, owner)
        if status:
            label_chip(slide, theme, tx, oy + 0.16, status_label or status,
                       fill=theme.status_color(status), text_color=theme.color("inverse"), height=0.2)


def takeaway_strip(slide: Any, theme: DeckTheme, x: float, y: float, w: float, text: str, *, label: str = "") -> None:
    pt = theme.type_scale["body"] - 1
    if label:
        micro_label(slide, theme, x, y, w, label, color=theme.color("primary"))
        y += 0.2
    tf = textbox(slide, x, y, w, 0.6)
    add_run(tf.paragraphs[0], text, font=theme.font_body, size=pt, color=theme.color("muted"))


def synthesis_band(
    slide: Any, theme: DeckTheme,
    *, label: str, text: str, right_label: str = "", right_text: str = "",
) -> None:
    """Full-width dark strip near the slide bottom (WHAT THIS BUYS US ...)."""
    m_h = theme.spacing["margin_h"]
    w = SLIDE_W - 2 * m_h
    h = 0.95
    y = SLIDE_H - theme.spacing["margin_v"] - 0.5 - h
    add_rect(slide, m_h, y, w, h, fill=theme.color("panel"))
    pad = 0.24
    left_w = w * (0.62 if right_text else 0.96)
    lf = textbox(slide, m_h + pad, y + pad * 0.7, left_w - pad, h - pad)
    micro_p = lf.paragraphs[0]
    add_run(micro_p, label, font=theme.font_body, size=theme.type_scale["micro"],
            color=theme.color("primary"), spc=theme.spacing.get("letter_spacing", 2.0), bold=True, caps=True)
    body_p = lf.add_paragraph()
    body_p.space_before = Pt(4)
    tf = tm.fit_text(text, box_w_in=left_w - pad, box_h_in=h - pad - 0.25, family=theme.font_body,
                     max_pt=theme.type_scale["body"], min_pt=9)
    add_run(body_p, text, font=theme.font_body, size=tf.pt, color=theme.color("inverse"))
    if right_text:
        rx = m_h + left_w
        rf = textbox(slide, rx, y + pad * 0.7, w - left_w - pad, h - pad, anchor=MSO_ANCHOR.MIDDLE)
        if right_label:
            rp = rf.paragraphs[0]
            rp.alignment = PP_ALIGN.RIGHT
            add_run(rp, right_label, font=theme.font_body, size=theme.type_scale["micro"],
                    color=theme.color("primary"), spc=theme.spacing.get("letter_spacing", 2.0), bold=True, caps=True)
            vp = rf.add_paragraph()
        else:
            vp = rf.paragraphs[0]
        vp.alignment = PP_ALIGN.RIGHT
        add_run(vp, right_text, font=theme.font_header, size=theme.type_scale["card_title"] + 4,
                bold=True, color=theme.color("inverse"))


def cover_metadata_band(slide: Any, theme: DeckTheme, items: list[tuple[str, str]]) -> None:
    """PREPARED FOR / HORIZON / DATE row over hairline rules at the cover bottom."""
    if not items:
        return
    m_h = theme.spacing["margin_h"]
    w = SLIDE_W - 2 * m_h
    y = SLIDE_H - theme.spacing["margin_v"] - 0.8
    col_w = w / len(items)
    for i, (label, value) in enumerate(items):
        cx = m_h + i * col_w
        hairline_rule(slide, theme, cx, y - 0.1, col_w - 0.2)
        micro_label(slide, theme, cx, y, col_w - 0.2, label, color=theme.color("muted"))
        vtf = textbox(slide, cx, y + 0.22, col_w - 0.2, 0.5)
        vf = tm.fit_text(value, box_w_in=col_w - 0.25, box_h_in=0.45, family=theme.font_header,
                         max_pt=theme.type_scale["body"] + 1, min_pt=9, bold=True, max_lines=2)
        for j, ln in enumerate(vf.lines or [value]):
            p = vtf.paragraphs[0] if j == 0 else vtf.add_paragraph()
            add_run(p, ln, font=theme.font_header, size=vf.pt, bold=True, color=theme.color("ink"))


def concentric_circles_motif(slide: Any, theme: DeckTheme, cx: float, cy: float, *, on_dark: bool = False) -> None:
    """Abstract concentric-circle motif (cover accent). Native unfilled ovals + one filled core."""
    line_color = theme.color("tint") if not on_dark else theme.color("primary")
    for d in (4.4, 3.2):
        add_rect(slide, cx - d / 2, cy - d / 2, d, d, fill=None, line=line_color, line_pt=1.0, shape=MSO_SHAPE.OVAL)
    # Light filled disc + gradient primary core for focal depth.
    add_rect(slide, cx - 1.5, cy - 1.5, 3.0, 3.0, fill=theme.color("tint"), shape=MSO_SHAPE.OVAL)
    core = add_rect(slide, cx - 0.55, cy - 0.55, 1.1, 1.1, fill=theme.color("primary"), shape=MSO_SHAPE.OVAL)
    linear_gradient(core, theme.color("primary"), theme.color("accent"))
