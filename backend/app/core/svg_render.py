"""SVG-to-PNG rasterization bootstrap (Deloitte-quality program, Pillar B icons).

Wraps ``cairosvg`` so the vector icon library can rasterize themed icons without
a hard runtime dependency on a system Cairo install being on the default library
search path. On macOS, Homebrew's libcairo isn't on the dynamic-linker search
path by default, so we probe common Homebrew prefixes and extend
``DYLD_FALLBACK_LIBRARY_PATH`` *before* importing cairosvg. On Linux, apt's
``libcairo2`` is already on the standard path and no probing is needed.

Fails open: if Cairo can't be loaded at all (e.g. a minimal CI image without it),
``CAIRO_AVAILABLE`` is False and ``render_svg_to_png`` returns None so callers fall
back to their pre-existing Unicode-glyph/raster path.
"""
from __future__ import annotations

import ctypes.util
import logging
import os
import sys

logger = logging.getLogger(__name__)

_DARWIN_CAIRO_PREFIXES = (
    "/opt/homebrew/opt/cairo/lib",   # Apple Silicon Homebrew
    "/usr/local/opt/cairo/lib",      # Intel Homebrew
)


def _ensure_cairo_loadable() -> None:
    if sys.platform != "darwin":
        return
    if ctypes.util.find_library("cairo"):
        return
    for prefix in _DARWIN_CAIRO_PREFIXES:
        if os.path.isdir(prefix):
            existing = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
            os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = (
                f"{prefix}:{existing}" if existing else prefix
            )
            return


_ensure_cairo_loadable()

try:
    import cairosvg  # noqa: E402

    CAIRO_AVAILABLE = True
except Exception as exc:  # noqa: BLE001 - any import/runtime failure means "unavailable"
    cairosvg = None  # type: ignore[assignment]
    CAIRO_AVAILABLE = False
    logger.info("cairosvg unavailable, SVG rendering disabled: %s", exc)


def render_svg_to_png(svg_text: str, *, width_px: int, height_px: int) -> bytes | None:
    """Rasterize an SVG string to PNG bytes, or None if no SVG renderer is available."""
    if not CAIRO_AVAILABLE or cairosvg is None:
        return None
    try:
        return cairosvg.svg2png(
            bytestring=svg_text.encode("utf-8"),
            output_width=width_px,
            output_height=height_px,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("SVG rasterization failed: %s", exc)
        return None
