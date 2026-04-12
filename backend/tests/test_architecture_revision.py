from __future__ import annotations

from app.agents.agent_types import build_agent_context
from app.core.quality_framework import UnifiedQualityFramework
from app.services.branding_service import BrandingService, BrandingLevel
from app.services.content_enrichment import ContentEnrichmentEngine


class _MockQuery:
    def __init__(self, row):
        self._row = row

    def filter_by(self, **kwargs):
        return self

    def first(self):
        return self._row


class _MockSession:
    def __init__(self, row=None):
        self._row = row

    def query(self, _model):
        return _MockQuery(self._row)


class _BrandRow:
    primary_color = "#112233"
    font_family = "Arial"
    font_size_base = 12
    logo_url = "https://logo.example"
    company_name = "ExampleCo"
    footer_text = "Example footer"


def test_branding_service_precedence_runtime_override():
    svc = BrandingService(_MockSession(_BrandRow()))
    out = svc.get_branding_for_run(
        project_id="p1",
        skill_card={"brand_override": {"primary_color": "#445566"}},
        run_config={"brand_override": {"primary_color": "#778899"}},
    )
    assert out.level == BrandingLevel.RUNTIME_OVERRIDE
    assert out.primary_color == "#778899"


def test_branding_service_project_fallback():
    svc = BrandingService(_MockSession(_BrandRow()))
    out = svc.get_branding_for_run(project_id="p1")
    assert out.level == BrandingLevel.PROJECT_CUSTOM
    assert out.primary_color == "#112233"


def test_unified_quality_reports_include_dimensions():
    framework = UnifiedQualityFramework()
    report = framework.evaluate_deliverable(
        output_type="docx",
        text="Title\n\nProblem\n\nApproach\n\nOutcome details with metric 20%.",
        metadata={},
        context={"branding": object()},
    )
    assert report["output_type"] == "docx"
    assert "narrative_coherence" in report["dimensions"]
    assert "branding_compliance" in report["dimensions"]
    assert "content_quality" in report["dimensions"]


def test_enrichment_propagates_into_agent_context_helpers():
    enrichment = ContentEnrichmentEngine().enrich(
        user_instruction="Create an executive risk-focused summary with ROI details.",
        process_model={
            "steps": [{"name": "Collect", "role": "Ops"}, {"name": "Review", "role": "Risk"}],
            "risks": [{"name": "Data quality"}],
            "improvement_opportunities": [{"name": "Cycle time reduction"}],
        },
        prior_artifacts={"narrative": "Prior narrative context"},
    )
    state = {
        "project_id": "p1",
        "run_id": "r1",
        "user_instruction": "Create an executive risk-focused summary with ROI details.",
        "process_model": {"steps": []},
        "content_enrichment": enrichment,
    }
    ctx = build_agent_context(state, "docx")
    assert "executive" in ctx.get_audience_hints().lower()
    assert "risk" in ctx.get_risk_focus().lower()
    assert "value drivers" in ctx.get_value_emphasis().lower()
