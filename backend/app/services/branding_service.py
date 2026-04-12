from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Union

from sqlalchemy.orm import Session

from app.db.models import ProjectBrand


class BrandingLevel(str, Enum):
    DELOITTE_DEFAULT = "deloitte_default"
    PROJECT_CUSTOM = "project_custom"
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
    logo_url: Optional[str]
    company_name: str
    custom_footer_text: Optional[str]


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
        )

    def get_branding_for_run(self, project_id: Optional[Union[str, int]], skill_card: Optional[dict] = None, run_config: Optional[dict] = None) -> BrandingContext:
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
        return self.default_brand

