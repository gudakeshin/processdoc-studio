from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ProjectBrand
from app.services.storage import workspace_path


class BrandingLevel(StrEnum):
    DELOITTE_DEFAULT = "deloitte_default"
    PROJECT_CUSTOM = "project_custom"
    INGESTED_DESIGN_SYSTEM = "ingested_design_system"
    SKILL_OVERRIDE = "skill_override"
    RUNTIME_OVERRIDE = "runtime_override"


@dataclass
class ColorPalette:
    primary: str
    complementary: str
    accent_light: str
    accent_dark: str
    neutral_light: str = "#AAAAAA"
    neutral_dark: str = "#1A1A1A"
    text_primary: str = "#1A1A1A"
    text_inverse: str = "#FFFFFF"


@dataclass
class BrandingContext:
    level: BrandingLevel
    primary_color: str
    palette: ColorPalette
    font_family: str
    font_size_base: int
    logo_url: str | None
    company_name: str
    custom_footer_text: str | None
    # Deck design language: "" = unset (resolved at render time from the
    # pptx_editorial_theme_enabled flag), "classic" or "editorial" to force one.
    deck_theme: str = ""


class BrandingService:
    def __init__(self, db: Session):
        self.db = db
        self.default_brand = self._build_default()

    def _build_default(self) -> BrandingContext:
        return BrandingContext(
            level=BrandingLevel.DELOITTE_DEFAULT,
            primary_color="#86BC25",
            palette=ColorPalette(primary="#86BC25", complementary="#E8007C", accent_light="#EBF5D3", accent_dark="#5A8A00"),
            font_family="Calibri",
            font_size_base=11,
            logo_url=None,
            company_name="Deloitte",
            custom_footer_text="Deloitte.",
        )

    @staticmethod
    def _normalize_hex(raw: str, default: str = "#86BC25") -> str:
        v = str(raw or "").strip()
        if not v:
            return default
        if not v.startswith("#"):
            v = f"#{v}"
        return v[:7]

    def _palette(self, primary: str) -> ColorPalette:
        p = self._normalize_hex(primary)
        return ColorPalette(primary=p, complementary="#E8007C", accent_light="#EBF5D3", accent_dark="#5A8A00")

    def _repo_root(self) -> Path:
        # backend/app/services/branding_service.py -> repo root
        return Path(__file__).resolve().parents[3]

    def _extract_css_var(self, css: str, var_name: str) -> str | None:
        pattern = rf"--{re.escape(var_name)}\s*:\s*(#[0-9A-Fa-f]{{6}})\s*;"
        m = re.search(pattern, css)
        if not m:
            return None
        return self._normalize_hex(m.group(1))

    def _extract_tailwind_font_size_base(self, ts_source: str) -> int | None:
        m = re.search(r'"2xs"\s*:\s*"([0-9]*\.?[0-9]+)rem"', ts_source)
        if not m:
            return None
        try:
            return max(9, min(18, int(round(float(m.group(1)) * 16))))
        except Exception:
            return None

    def _extract_json_token_hex(self, payload: Any, keys: set[str]) -> str | None:
        if isinstance(payload, dict):
            for k, v in payload.items():
                k_norm = str(k).strip().lower().replace("-", "_")
                if isinstance(v, str):
                    m = re.search(r"#([0-9a-fA-F]{6})", v)
                    if m and any(needle in k_norm for needle in keys):
                        return self._normalize_hex(m.group(0))
                nested = self._extract_json_token_hex(v, keys)
                if nested:
                    return nested
        elif isinstance(payload, list):
            for item in payload:
                nested = self._extract_json_token_hex(item, keys)
                if nested:
                    return nested
        return None

    def _extract_json_font_family(self, payload: Any) -> str | None:
        if isinstance(payload, dict):
            for k, v in payload.items():
                key = str(k).strip().lower().replace("-", "_")
                if isinstance(v, str) and "font" in key and ("family" in key or key.endswith("font")):
                    candidate = v.strip().strip("'\"")
                    if candidate:
                        return candidate
                nested = self._extract_json_font_family(v)
                if nested:
                    return nested
        elif isinstance(payload, list):
            for item in payload:
                nested = self._extract_json_font_family(item)
                if nested:
                    return nested
        return None

    def _extract_json_font_size_base(self, payload: Any) -> int | None:
        if isinstance(payload, dict):
            for k, v in payload.items():
                key = str(k).strip().lower().replace("-", "_")
                if "font" in key and ("size" in key or "base" in key):
                    if isinstance(v, (int, float)):
                        return max(9, min(18, int(v)))
                    if isinstance(v, str):
                        m = re.search(r"([0-9]*\.?[0-9]+)\s*(px|rem)?", v)
                        if m:
                            raw = float(m.group(1))
                            unit = (m.group(2) or "px").lower()
                            px = raw * 16 if unit == "rem" else raw
                            return max(9, min(18, int(round(px))))
                nested = self._extract_json_font_size_base(v)
                if nested is not None:
                    return nested
        elif isinstance(payload, list):
            for item in payload:
                nested = self._extract_json_font_size_base(item)
                if nested is not None:
                    return nested
        return None

    def _ingested_design_system(self, project_id: str | int | None) -> BrandingContext | None:
        repo_root = self._repo_root()
        frontend_css_path = repo_root / "frontend" / "styles" / "tokens.css"
        frontend_tw_path = repo_root / "frontend" / "tailwind.config.ts"
        frontend_tokens_path = repo_root / "frontend" / "tokens.json"
        project_tokens_path: Path | None = None
        project_css_path: Path | None = None
        project_tw_path: Path | None = None
        if project_id:
            source_dir = workspace_path(str(project_id)) / "source_docs"
            project_tokens_path = source_dir / "tokens.json"
            project_css_path = source_dir / "tokens.css"
            project_tw_path = source_dir / "tailwind.config.ts"
        all_candidates = [
            frontend_css_path,
            frontend_tw_path,
            frontend_tokens_path,
            project_tokens_path,
            project_css_path,
            project_tw_path,
        ]
        if not any(p is not None and p.exists() for p in all_candidates):
            return None

        css_chunks: list[str] = []
        tw_chunks: list[str] = []
        json_sources: list[dict[str, Any]] = []

        for path in [frontend_css_path, project_css_path]:
            if path is None or not path.exists():
                continue
            try:
                css_chunks.append(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: S112 — best-effort, non-fatal
                continue
        for path in [frontend_tw_path, project_tw_path]:
            if path is None or not path.exists():
                continue
            try:
                tw_chunks.append(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: S112 — best-effort, non-fatal
                continue
        for path in [frontend_tokens_path, project_tokens_path]:
            if path is None or not path.exists():
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    json_sources.append(raw)
            except Exception:  # noqa: S112 — best-effort, non-fatal
                continue

        css = "\n".join(css_chunks)
        tw = "\n".join(tw_chunks)

        primary = (
            self._extract_css_var(css, "deloitte-green")
            or self._extract_css_var(css, "accent-green")
            or self._extract_css_var(css, "primary-900")
            or next(
                (
                    self._extract_json_token_hex(src, {"primary", "brand", "green", "accent"})
                    for src in json_sources
                    if self._extract_json_token_hex(src, {"primary", "brand", "green", "accent"})
                ),
                None,
            )
            or "#86BC25"
        )
        complementary = (
            self._extract_css_var(css, "deloitte-blue")
            or self._extract_css_var(css, "accent-blue")
            or next(
                (
                    self._extract_json_token_hex(src, {"secondary", "complementary", "blue"})
                    for src in json_sources
                    if self._extract_json_token_hex(src, {"secondary", "complementary", "blue"})
                ),
                None,
            )
            or "#E8007C"
        )
        neutral_light = (
            self._extract_css_var(css, "light-gray")
            or next(
                (
                    self._extract_json_token_hex(src, {"neutral_light", "gray", "light"})
                    for src in json_sources
                    if self._extract_json_token_hex(src, {"neutral_light", "gray", "light"})
                ),
                None,
            )
            or "#AAAAAA"
        )
        neutral_dark = (
            self._extract_css_var(css, "coral-black")
            or next(
                (
                    self._extract_json_token_hex(src, {"neutral_dark", "dark", "black"})
                    for src in json_sources
                    if self._extract_json_token_hex(src, {"neutral_dark", "dark", "black"})
                ),
                None,
            )
            or "#1A1A1A"
        )
        text_primary = self._extract_css_var(css, "text-default") or neutral_dark
        text_inverse = self._extract_css_var(css, "white") or "#FFFFFF"
        base_size = (
            self._extract_tailwind_font_size_base(tw)
            or next((self._extract_json_font_size_base(src) for src in json_sources if self._extract_json_font_size_base(src) is not None), None)
            or 11
        )
        font_family = next(
            (self._extract_json_font_family(src) for src in json_sources if self._extract_json_font_family(src)),
            None,
        ) or "Calibri"
        return BrandingContext(
            level=BrandingLevel.INGESTED_DESIGN_SYSTEM,
            primary_color=primary,
            palette=ColorPalette(
                primary=primary,
                complementary=complementary,
                accent_light="#EBF5D3",
                accent_dark="#5A8A00",
                neutral_light=neutral_light,
                neutral_dark=neutral_dark,
                text_primary=text_primary,
                text_inverse=text_inverse,
            ),
            font_family=font_family,
            font_size_base=base_size,
            logo_url=None,
            company_name="Deloitte",
            custom_footer_text="Deloitte.",
        )

    def _from_override(self, override: dict[str, Any], level: BrandingLevel) -> BrandingContext:
        primary = self._normalize_hex(str(override.get("primary_color") or "#86BC25"))
        return BrandingContext(
            level=level,
            primary_color=primary,
            palette=self._palette(primary),
            font_family=str(override.get("font_family") or "Calibri"),
            font_size_base=int(override.get("font_size_base") or 11),
            logo_url=(str(override.get("logo_url")).strip() or None) if override.get("logo_url") else None,
            company_name=str(override.get("company_name") or "Company"),
            custom_footer_text=(str(override.get("footer_text")).strip() or None) if override.get("footer_text") else None,
            deck_theme=str(override.get("deck_theme") or ""),
        )

    def get_branding_for_run(self, project_id: str | int | None, skill_card: dict | None = None, run_config: dict | None = None) -> BrandingContext:
        if isinstance(run_config, dict) and isinstance(run_config.get("brand_override"), dict):
            return self._from_override(run_config["brand_override"], BrandingLevel.RUNTIME_OVERRIDE)
        if isinstance(skill_card, dict) and isinstance(skill_card.get("brand_override"), dict):
            return self._from_override(skill_card["brand_override"], BrandingLevel.SKILL_OVERRIDE)
        if project_id:
            row = self.db.query(ProjectBrand).filter_by(project_id=str(project_id)).first()
            if row:
                primary = self._normalize_hex(row.primary_color or "#86BC25")
                return BrandingContext(
                    level=BrandingLevel.PROJECT_CUSTOM,
                    primary_color=primary,
                    palette=self._palette(primary),
                    font_family=row.font_family or "Calibri",
                    font_size_base=int(row.font_size_base or 11),
                    logo_url=row.logo_url,
                    company_name=row.company_name or "Company",
                    custom_footer_text=row.footer_text,
                )
        ingested = self._ingested_design_system(project_id)
        if ingested is not None:
            return ingested
        return self.default_brand

