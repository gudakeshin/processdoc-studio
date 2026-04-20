from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from app.services.branding_service import BrandingLevel, BrandingService


def _mock_db_with_project_brand(primary_color: str = "#112233") -> Mock:
    row = SimpleNamespace(
        primary_color=primary_color,
        font_family="Arial",
        font_size_base=12,
        logo_url=None,
        company_name="Custom Co",
        footer_text="Custom Footer",
    )
    db = Mock()
    db.query.return_value.filter_by.return_value.first.return_value = row
    return db


def test_project_custom_wins_over_ingested_design_system(monkeypatch) -> None:
    svc = BrandingService(_mock_db_with_project_brand("#112233"))
    css = ":root { --deloitte-green: #86BC24; --deloitte-blue: #0072B1; --coral-black: #0F0B0B; --light-gray: #E5E5E5; --white: #FFFFFF; }"
    tailwind = 'const x={ theme:{ extend:{ fontSize:{ "2xs":"0.6875rem" }}}};'
    monkeypatch.setattr(Path, "exists", lambda self: str(self).endswith(("tokens.css", "tailwind.config.ts")))
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda self, encoding="utf-8": css if str(self).endswith("tokens.css") else tailwind,
    )

    branding = svc.get_branding_for_run(project_id="p1")

    assert branding.level == BrandingLevel.PROJECT_CUSTOM
    assert branding.primary_color == "#112233"


def test_falls_back_to_project_custom_when_no_ingested_files(monkeypatch) -> None:
    svc = BrandingService(_mock_db_with_project_brand("#112233"))
    monkeypatch.setattr(Path, "exists", lambda self: False)

    branding = svc.get_branding_for_run(project_id="p1")

    assert branding.level == BrandingLevel.PROJECT_CUSTOM
    assert branding.primary_color == "#112233"


def test_ingests_project_tokens_json_when_project_brand_missing(tmp_path, monkeypatch) -> None:
    source_docs = tmp_path / "source_docs"
    source_docs.mkdir(parents=True, exist_ok=True)
    tokens_json = json.dumps(
        {
            "colors": {"primary": "#123456", "secondary": "#654321"},
            "typography": {"fontFamily": "Inter", "fontSizeBase": "12px"},
        }
    )
    (source_docs / "tokens.json").write_text(tokens_json, encoding="utf-8")
    db = Mock()
    db.query.return_value.filter_by.return_value.first.return_value = None
    svc = BrandingService(db)
    monkeypatch.setattr("app.services.branding_service.workspace_path", lambda _: tmp_path)
    monkeypatch.setattr(Path, "exists", lambda self: str(self).endswith("tokens.json"))
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda self, encoding="utf-8": (tokens_json if str(self).endswith("source_docs/tokens.json") else ""),
    )

    branding = svc.get_branding_for_run(project_id="p1")

    assert branding.level == BrandingLevel.INGESTED_DESIGN_SYSTEM
    assert branding.primary_color == "#123456"
    assert branding.palette.complementary == "#654321"
    assert branding.font_family == "Inter"
    assert branding.font_size_base == 12
